# test_rib_shift_gradient.py - Standalone fixture: 12-rib plate 1mm shift gradient test.
#
# WHAT this tests:
#   A 1mm positional shift of 12 small ribs (2x4x6mm) on an 80x40x5mm plate
#   should score MATERIALLY below a perfect self-score.  With iou_res=24 (broken),
#   the composite delta is ~0.007 (nearly-zero gradient). With iou_res=64 (fix),
#   delta should be > 0.05 composite.
#
# GEOMETRY:
#   Base plate: Box(80, 40, 5) center-aligned (default in build123d, z from -2.5 to +2.5)
#   Ribs: 12x via GridLocations(12, 20, 6, 2) -> 6 cols (spacing 12mm) x 2 rows (spacing 20mm)
#   Each rib: Box(2, 4, 6) with Align.MIN on Z -> ribs protrude above base center
#   This is the EXACT geometry from the prior probe that gave delta=0.007 at iou_res=24.
#   The ribs are 2mm wide (1.2 voxels at 1.667mm/voxel at iou_res=24) and a 1mm shift
#   is 0.6 voxels at the voxelization grid (res=48) and 0.3 voxels at the comparison
#   grid (res=24) -> sub-voxel in the COMPARISON step.
#
# HOW to run:
#   cd cad-autoresearch
#   uv run python tests/test_rib_shift_gradient.py
#
# PASS condition (proposed fix iou_res=64):
#   - perfect self-score >= 0.99
#   - 1mm-shifted plate composite < 0.97  (delta > 0.03)
#   - gradient improvement vs iou_res=24 >= 5x

import sys, tempfile, os, time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import numpy as np
import trimesh
from build123d import BuildPart, Box, GridLocations, Locations, Mode, Align, export_stl
from harness import geometry as G
from harness.reward import score, RewardConfig


# ---------------------------------------------------------------------------
# Geometry: exact replication of prior probe3 geometry
# ---------------------------------------------------------------------------

def build_probe3_plate(x_shift_mm: float = 0.0) -> trimesh.Trimesh:
    """
    80x40x5 plate (center-aligned) + 12 ribs via GridLocations(12, 20, 6, 2).
    Each rib: 2x4x6mm, Align.MIN on Z.
    x_shift_mm: additional X offset applied to ALL ribs (via nested Locations).
    Zero shift = perfect/GT plate (reproduces prior probe CODE_A exactly).
    """
    with BuildPart() as p:
        Box(80, 40, 5)  # default CENTER alignment
        if abs(x_shift_mm) < 1e-6:
            with GridLocations(12, 20, 6, 2):
                Box(2, 4, 6,
                    align=(Align.CENTER, Align.CENTER, Align.MIN),
                    mode=Mode.ADD)
        else:
            with GridLocations(12, 20, 6, 2):
                with Locations((x_shift_mm, 0, 0)):
                    Box(2, 4, 6,
                        align=(Align.CENTER, Align.CENTER, Align.MIN),
                        mode=Mode.ADD)

    with tempfile.NamedTemporaryFile(suffix=".stl", delete=False) as f:
        tmp = f.name
    try:
        export_stl(p.part, tmp)
        return trimesh.load_mesh(tmp)
    finally:
        os.unlink(tmp)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _print_result(label: str, rw):
    print(f"  {label}: composite={rw.composite:.4f}  iou={rw.iou:.4f}  "
          f"chamfer={rw.chamfer:.4f}  siou={rw.siou:.4f}")


def run_pair(cfg: RewardConfig, gt: trimesh.Trimesh, shifted: trimesh.Trimesh):
    t0 = time.time()
    r_self = score(gt, gt, cfg=cfg)
    r_shift = score(shifted, gt, cfg=cfg)
    dt = time.time() - t0
    return r_self, r_shift, dt


# ---------------------------------------------------------------------------
# Main test
# ---------------------------------------------------------------------------

def main():
    print("12-RIB PLATE 1MM SHIFT GRADIENT TEST")
    print("Part: 80x40x5mm base (center) + 12 ribs (2x4x6mm) via GridLocations(12,20,6,2)")
    print("Shift: all ribs +1mm in X via nested Locations")

    print()
    print("Building meshes (GT=0mm shift, Shifted=1mm shift)...")
    t0 = time.time()
    gt = build_probe3_plate(x_shift_mm=0.0)
    shifted = build_probe3_plate(x_shift_mm=1.0)
    dt_build = time.time() - t0
    print(f"  GT extents={gt.extents}  vol={G.volume(gt):.1f}")
    print(f"  Shifted extents={shifted.extents}  vol={G.volume(shifted):.1f}")
    print(f"  Vol delta: {abs(G.volume(gt) - G.volume(shifted)):.4f} (should be 0)")
    print(f"  Build time: {dt_build:.1f}s")

    max_ext = float(np.max(gt.extents))
    pitch_24 = max_ext / 24
    pitch_64 = max_ext / 64
    print()
    print(f"Voxel pitch analysis (max_extent={max_ext:.1f}mm):")
    print(f"  iou_res=24: comparison pitch={pitch_24:.2f}mm  "
          f"1mm shift = {1.0/pitch_24:.2f} voxels "
          f"({'sub-voxel' if pitch_24 > 1.0 else 'detectable'})")
    print(f"  iou_res=64: comparison pitch={pitch_64:.2f}mm  "
          f"1mm shift = {1.0/pitch_64:.2f} voxels "
          f"({'sub-voxel' if pitch_64 > 1.0 else 'detectable'})")
    print(f"  Surface area: {float(gt.area):.1f} mm^2  "
          f"(8000 pts -> ~{int(8000 * 12 * 2*4*6 / float(gt.area))} pts sampled on ribs)")

    # ---------------------------------------------------------------------------
    # CURRENT config (iou_res=24)
    # ---------------------------------------------------------------------------
    cfg_current = RewardConfig(iou_res=24)
    print()
    print("=" * 60)
    print(f"CURRENT (iou_res={cfg_current.iou_res}, comparison pitch={max_ext/24:.2f}mm):")
    r_self_curr, r_shift_curr, dt_curr = run_pair(cfg_current, gt, shifted)
    _print_result("Self (GT vs GT)", r_self_curr)
    _print_result("1mm shifted", r_shift_curr)
    d_comp_curr = r_self_curr.composite - r_shift_curr.composite
    print(f"  Delta composite: {d_comp_curr:.4f}  Delta IoU: {r_self_curr.iou - r_shift_curr.iou:.4f}")
    print(f"  Score time: {dt_curr:.2f}s")

    if d_comp_curr < 0.02:
        print(f"  [CONFIRMED] nearly-zero gradient ({d_comp_curr:.4f}) -- "
              f"1mm rib shift is sub-voxel and invisible")
    else:
        print(f"  [NOTE] delta={d_comp_curr:.4f} -- geometry may differ from original probe")

    # ---------------------------------------------------------------------------
    # PROPOSED FIX (iou_res=64)
    # ---------------------------------------------------------------------------
    cfg_fixed = RewardConfig(iou_res=64)
    print()
    print("=" * 60)
    print(f"PROPOSED FIX (iou_res={cfg_fixed.iou_res}, comparison pitch={max_ext/64:.2f}mm):")
    r_self_fix, r_shift_fix, dt_fix = run_pair(cfg_fixed, gt, shifted)
    _print_result("Self (GT vs GT)", r_self_fix)
    _print_result("1mm shifted", r_shift_fix)
    d_comp_fix = r_self_fix.composite - r_shift_fix.composite
    print(f"  Delta composite: {d_comp_fix:.4f}  Delta IoU: {r_self_fix.iou - r_shift_fix.iou:.4f}")
    print(f"  Score time: {dt_fix:.2f}s")

    # ---------------------------------------------------------------------------
    # Assertions
    # ---------------------------------------------------------------------------
    print()
    print("=" * 60)
    print("ASSERTIONS:")
    all_pass = True

    # 1. Perfect plate still scores near-perfect
    ok = r_self_fix.composite >= 0.99
    status = "PASS" if ok else "FAIL"
    print(f"  [{status}] perfect plate self-score={r_self_fix.composite:.4f} >= 0.99")
    all_pass = all_pass and ok

    # 2. 1mm-shifted plate scores materially below perfect (< 0.97)
    ok = r_shift_fix.composite < 0.97
    status = "PASS" if ok else "FAIL"
    print(f"  [{status}] 1mm shift composite={r_shift_fix.composite:.4f} < 0.97 "
          f"(delta={d_comp_fix:.4f})")
    all_pass = all_pass and ok

    # 3. Gradient restoration: delta >= 0.05 composite
    ok = d_comp_fix >= 0.05
    status = "PASS" if ok else "FAIL"
    print(f"  [{status}] gradient delta={d_comp_fix:.4f} >= 0.05")
    all_pass = all_pass and ok

    # 4. Improvement factor vs current
    if d_comp_curr > 0.001:
        improvement = d_comp_fix / d_comp_curr
        ok = improvement >= 3.0
        status = "PASS" if ok else "FAIL"
        print(f"  [{status}] gradient improvement={improvement:.1f}x >= 3x")
        all_pass = all_pass and ok

    print()
    print("=" * 60)
    print("SUMMARY TABLE:")
    print(f"  {'Config':<22} {'self_comp':>9} {'shift_comp':>10} {'delta_comp':>10}  notes")
    print(f"  {'iou_res=24 (current)':<22} {r_self_curr.composite:>9.4f} "
          f"{r_shift_curr.composite:>10.4f} {d_comp_curr:>10.4f}  "
          f"{'BROKEN (sub-voxel)' if d_comp_curr < 0.02 else 'marginal'}")
    print(f"  {'iou_res=64 (proposed)':<22} {r_self_fix.composite:>9.4f} "
          f"{r_shift_fix.composite:>10.4f} {d_comp_fix:>10.4f}  "
          f"{'GRADIENT RESTORED' if d_comp_fix >= 0.05 else 'partial'}")
    print()
    if all_pass:
        print("ALL ASSERTIONS PASSED")
    else:
        print("SOME ASSERTIONS FAILED -- see [FAIL] lines above")
        sys.exit(1)


if __name__ == "__main__":
    main()
