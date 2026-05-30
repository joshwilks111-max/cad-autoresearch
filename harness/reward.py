"""
reward.py — the verifiable reward function.

The heart of the autoresearch loop: one scalar in [0, 1] saying "how close is
this candidate to ground truth", composited from six independent geometric layers
(after Reshef Elisha's Onshape MCP eval rubric). Independent layers matter — a
model can nail bounding box while getting topology completely wrong, and the score
should reflect partial credit honestly.

Layers (each in [0,1], then weighted):
  1. body       did we get a non-empty solid at all?            (gate)
  2. volume     |Vc - Vg| / Vg  ->  1 at 0% error, 0 at >=tol_hard
  3. bbox       worst-axis relative error over sorted extents
  4. topology   exact-match fraction of B-rep counts (or mesh proxy)
  5. iou        rotation/translation-invariant volumetric IoU
  6. chamfer    surface Chamfer distance, mapped through scale

Composite = body_gate * (weighted sum). The gate forces ~0 for empty / invalid
results no matter what the other layers say. Returns every sub-score so the
ledger and the agent feedback can see exactly which layer failed.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict

import numpy as np
import trimesh

from . import geometry as G


@dataclass
class RewardConfig:
    # tolerance bands (fraction). err <= soft -> full credit; err >= hard -> 0;
    # linear ramp between.
    vol_tol_soft: float = 0.01
    vol_tol_hard: float = 0.25
    bbox_tol_soft: float = 0.01
    bbox_tol_hard: float = 0.25
    # chamfer mapped relative to gt bbox diagonal -> unit-agnostic fraction
    cham_tol_soft: float = 0.005
    cham_tol_hard: float = 0.10
    # weights (need not sum to 1; composite renormalises by total weight)
    w_volume: float = 0.20
    w_bbox: float = 0.15
    w_topology: float = 0.15
    w_iou: float = 0.25      # reduced from 0.30 to fund w_siou
    w_chamfer: float = 0.20
    w_siou: float = 0.10     # Surface IoU: catches surface errors volumetric IoU misses
    # sampling — IoU needs FAR more points than chamfer to stay self-consistent
    n_points: int = 8000        # chamfer surface samples
    iou_points: int = 60000     # IoU interior samples (dense vs iou_res grid)
    iou_res: int = 64           # IoU voxel grid resolution. Raised from 24 so the
                                # comparison-grid pitch (max_extent/iou_res) is fine
                                # enough to register small-feature placement errors:
                                # for an 80mm part, 1.25mm/voxel, so a 1mm feature
                                # shift moves ~0.8 voxels and the IoU drops (measured
                                # rib-shift 0.992 -> 0.910). At 24 the pitch was 3.3mm
                                # and a 1mm shift was sub-voxel (invisible). Self-IoU
                                # stays 1.0; cost ~11-18x the IoU layer (score() still
                                # <15s on a 305mm part). TODO: adaptive pitch (res =
                                # clamp(max_extent/1.25, 24, cap)) for large parts +
                                # the surface-area-fraction case (FTC-09) is separate.
    seed: int = 0


def _ramp(err: float, soft: float, hard: float) -> float:
    if err <= soft:
        return 1.0
    if err >= hard:
        return 0.0
    return 1.0 - (err - soft) / (hard - soft)


@dataclass
class RewardResult:
    composite: float
    body: float
    volume: float
    bbox: float
    topology: float
    iou: float
    chamfer: float
    siou: float = 0.0          # Layer 7: Surface IoU (default keeps old ledger rows loadable)
    raw: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    def summary(self) -> str:
        return (f"composite={self.composite:.3f} "
                f"[body={self.body:.0f} vol={self.volume:.3f} bbox={self.bbox:.3f} "
                f"topo={self.topology:.3f} iou={self.iou:.3f} cham={self.chamfer:.3f} "
                f"siou={self.siou:.3f}]")


def score(candidate_mesh: trimesh.Trimesh,
          gt_mesh: trimesh.Trimesh,
          candidate_solid=None,
          gt_solid=None,
          candidate_sig: dict | None = None,
          gt_sig: dict | None = None,
          cfg: RewardConfig | None = None) -> RewardResult:
    """Grade a candidate against ground truth.

    Topology signatures resolve in priority order:
      1. an explicit precomputed dict (`*_sig`) — used when the runner computed
         the B-rep signature inside its sandbox subprocess (OCP objects can't be
         pickled across processes);
      2. a live build123d / CadQuery object (`*_solid`);
      3. a mesh-based proxy as a last resort.
    """
    cfg = cfg or RewardConfig()
    raw: dict = {}

    # ---- Layer 1: body gate ------------------------------------------------
    body_ok = (candidate_mesh is not None
               and len(candidate_mesh.faces) > 0
               and G.volume(candidate_mesh) > 1e-9)
    body = 1.0 if body_ok else 0.0
    raw["candidate_watertight"] = (bool(getattr(candidate_mesh, "is_watertight", False))
                                   if body_ok else False)
    if not body_ok:
        return RewardResult(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, raw)

    # ---- Layer 2: volume ---------------------------------------------------
    vc, vg = G.volume(candidate_mesh), G.volume(gt_mesh)
    vol_err = G.relative_error(vc, vg)
    vol_s = _ramp(vol_err, cfg.vol_tol_soft, cfg.vol_tol_hard)
    raw["volume_candidate"], raw["volume_gt"], raw["volume_rel_err"] = vc, vg, vol_err

    # ---- Layer 3: bounding box (worst sorted axis) -------------------------
    bc, bg = G.bbox_dims(candidate_mesh), G.bbox_dims(gt_mesh)
    axis_err = [G.relative_error(a, b) for a, b in zip(bc, bg)]
    bbox_err = max(axis_err) if axis_err else 1.0
    bbox_s = _ramp(bbox_err, cfg.bbox_tol_soft, cfg.bbox_tol_hard)
    raw["bbox_candidate"], raw["bbox_gt"] = bc.tolist(), bg.tolist()
    raw["bbox_worst_axis_err"] = bbox_err

    # ---- Layer 4: topology -------------------------------------------------
    sig_c = (candidate_sig
             or (G.topology_signature_from_solid(candidate_solid)
                 if candidate_solid is not None else None)
             or G.topology_signature_from_mesh(candidate_mesh))
    sig_g = (gt_sig
             or (G.topology_signature_from_solid(gt_solid)
                 if gt_solid is not None else None)
             or G.topology_signature_from_mesh(gt_mesh))
    topo_s = G.topology_match(sig_c, sig_g)
    raw["topology_candidate"], raw["topology_gt"] = sig_c, sig_g

    # ---- Layer 5: IoU (pose invariant) ------------------------------------
    iou_s = G.iou(candidate_mesh, gt_mesh, res=cfg.iou_res,
                  n=cfg.iou_points, seed=cfg.seed)
    raw["iou"] = iou_s

    # ---- Layer 6: Chamfer (scaled by gt diagonal) -------------------------
    diag = float(np.linalg.norm(bg)) or 1.0
    cd = G.chamfer_distance(candidate_mesh, gt_mesh, n=cfg.n_points, seed=cfg.seed)
    cham_frac = cd / diag
    cham_s = _ramp(cham_frac, cfg.cham_tol_soft, cfg.cham_tol_hard)
    raw["chamfer_abs"], raw["chamfer_frac_of_diag"] = cd, cham_frac

    # ---- Layer 7: Surface IoU (SIoU) --------------------------------------
    # Complementary to volumetric IoU: catches surface-shape errors (a flat face
    # where a curved one belongs) that volume-identical solids mask. Uses the
    # Chamfer point budget (surface samples, not interior).
    siou_s = G.surface_iou(candidate_mesh, gt_mesh, n=cfg.n_points, seed=cfg.seed)
    raw["siou"] = siou_s

    # ---- Composite ---------------------------------------------------------
    wsum = (cfg.w_volume + cfg.w_bbox + cfg.w_topology + cfg.w_iou +
            cfg.w_chamfer + cfg.w_siou)
    weighted = (cfg.w_volume * vol_s + cfg.w_bbox * bbox_s +
                cfg.w_topology * topo_s + cfg.w_iou * iou_s +
                cfg.w_chamfer * cham_s + cfg.w_siou * siou_s) / wsum
    composite = body * weighted

    return RewardResult(
        composite=round(composite, 4),
        body=body, volume=round(vol_s, 4), bbox=round(bbox_s, 4),
        topology=round(topo_s, 4), iou=round(iou_s, 4), chamfer=round(cham_s, 4),
        siou=round(siou_s, 4),
        raw=raw,
    )
