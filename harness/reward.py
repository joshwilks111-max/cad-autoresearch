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

# Hybrid Layer-4 (topology). The histogram half uses the SCALE-AWARE count-ratio
# blend, NOT bare cosine: cosine is scale-invariant, so a part missing most of its
# features scores ~0.99 on type-ratio alone (the Risk-H failure). count_ratio_similarity
# scales cosine by the fraction of faces present, so missing features cost monotonically.
# Tolerant import: surface_histogram lives at the repo root (on sys.path for in-repo
# callers); if it's unavailable the layer degrades to exact-count matching only.
try:
    from surface_histogram import count_ratio_similarity as _hist_sim
except Exception:
    _hist_sim = None


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
    # Hybrid Layer-4 blend (within the topology layer — NOT a layer weight). When a
    # candidate + GT surface histogram are both available, the topology sub-score is
    #   topo_s = topo_exact_w * exact_count_match + (1 - topo_exact_w) * count_ratio_sim
    # exact-count is kernel-FRAGILE (a STEP roundtrip shifts edge/vertex counts) but
    # discriminative for simple parts; the count-ratio histogram is roundtrip-STABLE
    # (surface TYPE survives seam merges) and scale-aware. 0.5 = equal blend; raise
    # toward exact for a more conservative (count-strict) layer. w_topology is unchanged
    # — this makes the layer more RELIABLE, not more IMPORTANT. The exact + histogram
    # sub-scores are always reported in raw[] so the blend is auditable, never a black box.
    topo_exact_w: float = 0.5
    # sampling — IoU needs FAR more points than chamfer to stay self-consistent
    n_points: int = 8000        # chamfer surface samples
    iou_points: int = 60000     # IoU interior samples (dense vs iou_res grid)
    iou_res: int = 64           # IoU voxel-grid resolution CAP. With
                                # iou_target_pitch_mm set, the actual res is derived
                                # per-part to hit that pitch, clamped to [24, iou_res]:
                                # small parts use a lower res (cheaper) and huge parts
                                # are capped here for cost. (Was a flat 64.)
    iou_target_pitch_mm: float = 1.25  # adaptive IoU pitch: res = clamp(max_extent /
                                # this, 24, iou_res). 1.25mm registers a ~1mm feature
                                # shift (for an 80mm part -> res 64; a 40mm part -> 32;
                                # a 305mm part -> capped 64). Fixes the small-feature
                                # gradient gap without flat-64 cost on small parts.
    seed: int = 0
    # Adaptive weighting for feature-rich parts. WF-M (2026-05-30) measured that on a
    # part with many small features (holes/pockets), volumetric IoU is the ONLY layer
    # sensitive to missing material (it drops ~proportionally to the missing volume),
    # while Chamfer and Surface-IoU are structurally blind (a 7%-volume hole field shifts
    # them less than the sampling floor). So a hole-less box scored high on the surface
    # terms. Fix: as the GROUND TRUTH's B-rep face count rises, shift weight OUT of the
    # blind surface layers (chamfer, siou) INTO the sensitive ones (iou, topology). Keyed
    # on the GT (not the candidate) -> a proposer cannot game it by adding faces. Disabled
    # (no shift) when the GT has no B-rep face count or for simple parts.
    adaptive_feature_weighting: bool = True
    afw_face_lo: int = 15     # at/below this GT face count: no shift (simple part)
    afw_face_hi: int = 120    # at/above this GT face count: full shift (complex real part)
    afw_max_shift: float = 0.10   # total weight moved from {chamfer,siou} to {iou,topology}
    afw_iou_share: float = 0.70   # fraction of the shift that goes to iou (rest to topology)


def _ramp(err: float, soft: float, hard: float) -> float:
    if err <= soft:
        return 1.0
    if err >= hard:
        return 0.0
    return 1.0 - (err - soft) / (hard - soft)


def _adaptive_weights(cfg: "RewardConfig", gt_faces: int | None) -> dict:
    """Return per-layer weights, shifted toward IoU+topology for feature-rich GTs.

    See ``RewardConfig.adaptive_feature_weighting``. ``richness`` ramps 0->1 over
    [afw_face_lo, afw_face_hi] GT faces; at full richness ``afw_max_shift`` of weight
    moves from the blind surface layers (chamfer, siou, split by their current weight)
    into iou (``afw_iou_share``) and topology (the remainder). Returns the base weights
    unchanged when disabled, when ``gt_faces`` is None (no B-rep signature), or for
    simple parts (richness 0)."""
    base = dict(volume=cfg.w_volume, bbox=cfg.w_bbox, topology=cfg.w_topology,
                iou=cfg.w_iou, chamfer=cfg.w_chamfer, siou=cfg.w_siou)
    if not cfg.adaptive_feature_weighting or not gt_faces:
        return base
    span = max(cfg.afw_face_hi - cfg.afw_face_lo, 1)
    richness = min(max((gt_faces - cfg.afw_face_lo) / span, 0.0), 1.0)
    if richness <= 0.0:
        return base
    shift = cfg.afw_max_shift * richness
    blind_total = base["chamfer"] + base["siou"]
    if blind_total <= 0:
        return base
    w = dict(base)
    w["chamfer"] = base["chamfer"] - shift * (base["chamfer"] / blind_total)
    w["siou"] = base["siou"] - shift * (base["siou"] / blind_total)
    w["iou"] = base["iou"] + shift * cfg.afw_iou_share
    w["topology"] = base["topology"] + shift * (1.0 - cfg.afw_iou_share)
    return w


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
          candidate_hist: dict | None = None,
          gt_hist: dict | None = None,
          cfg: RewardConfig | None = None) -> RewardResult:
    """Grade a candidate against ground truth.

    Topology signatures resolve in priority order:
      1. an explicit precomputed dict (`*_sig`) — used when the runner computed
         the B-rep signature inside its sandbox subprocess (OCP objects can't be
         pickled across processes);
      2. a live build123d / CadQuery object (`*_solid`);
      3. a mesh-based proxy as a last resort.

    Layer 4 (topology) is HYBRID when both `candidate_hist` and `gt_hist` (surface-
    type histograms) are supplied: it blends the exact-count match with a scale-aware
    surface-type-histogram similarity (see `RewardConfig.topo_exact_w`). When the
    histograms are absent (None) the layer falls back to exact-count matching ONLY —
    identical to the pre-hybrid behaviour, so every existing caller keeps working
    unchanged. The `*_hist` params sit BEFORE `cfg` and all callers pass `cfg=` by
    keyword, so the inserted params are back-compatible.
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
    # Hybrid Layer-4: exact-count match (kernel-fragile, discriminative for simple
    # parts) blended with the scale-aware surface-type histogram (roundtrip-stable,
    # lifts the topology ceiling on complex parts). Falls back to exact-only when the
    # histograms aren't supplied — the pre-hybrid path, so existing callers are
    # unaffected. Both sub-scores are ALWAYS exposed in raw[] (Risk-H: the blend must
    # be auditable, never a silent default), even on the exact-only fallback.
    exact_topo = G.topology_match(sig_c, sig_g)
    raw["topology_exact"] = exact_topo
    # The hybrid fires iff the histogram tool is importable AND a usable GT histogram
    # exists (a GT with at least one classified face — the reference to compare against).
    # The CANDIDATE histogram is deliberately NOT part of the gate: an empty/all-zero
    # candidate histogram is a REAL signal (degenerate/featureless solid) that must score
    # the histogram half LOW, not silently skip to exact-only. Without this, `{}` (falsy)
    # would skip the hybrid while `{Plane:0}` (truthy, sums to 0) would tank it to 0 — the
    # same physical situation scored oppositely depending on representation. We normalise:
    # a None candidate hist becomes {} (count_ratio_similarity returns 0.0 either way).
    def _has_face(h) -> bool:
        return bool(h) and sum(h.values()) > 0
    if _hist_sim is not None and _has_face(gt_hist):
        hist_topo = _hist_sim(candidate_hist or {}, gt_hist)
        raw["topology_hist"] = hist_topo
        topo_s = cfg.topo_exact_w * exact_topo + (1.0 - cfg.topo_exact_w) * hist_topo
    else:
        # No histogram tool, or no usable GT reference -> exact-only (pre-hybrid path).
        raw["topology_hist"] = None
        topo_s = exact_topo
    raw["topology_candidate"], raw["topology_gt"] = sig_c, sig_g
    raw["topology_hist_candidate"], raw["topology_hist_gt"] = candidate_hist, gt_hist

    # ---- Layer 5: IoU (pose invariant) ------------------------------------
    iou_s = G.iou(candidate_mesh, gt_mesh, res=cfg.iou_res,
                  n=cfg.iou_points, seed=cfg.seed,
                  target_pitch_mm=cfg.iou_target_pitch_mm)
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
    # Adaptive weighting: for a feature-rich GT (high B-rep face count), shift weight
    # from the blind surface layers (chamfer, siou) toward the layers that actually
    # catch missing material (iou, topology). Keyed on the GT face count -> ungameable.
    gt_faces = sig_g.get("faces") if isinstance(sig_g, dict) else None
    w = _adaptive_weights(cfg, gt_faces)
    raw["weights"] = w
    wsum = sum(w.values())
    weighted = (w["volume"] * vol_s + w["bbox"] * bbox_s +
                w["topology"] * topo_s + w["iou"] * iou_s +
                w["chamfer"] * cham_s + w["siou"] * siou_s) / wsum
    composite = body * weighted

    return RewardResult(
        composite=round(composite, 4),
        body=body, volume=round(vol_s, 4), bbox=round(bbox_s, 4),
        topology=round(topo_s, 4), iou=round(iou_s, 4), chamfer=round(cham_s, 4),
        siou=round(siou_s, 4),
        raw=raw,
    )
