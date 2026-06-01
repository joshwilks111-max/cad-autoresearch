"""
test_tool_selftests.py — wire the standalone tools' self-tests into pytest.

occ_guard and perceive already have in-file self-tests (run via `python tool.py`);
they were not collected by pytest, so CI told you nothing about them. This bridges
them: a failing self-test now fails the suite. Also a fast import-smoke for all 8 tools
(catches a syntax/import break in any of them) and the surface_histogram kernel-stability
property (its headline guarantee).

Run from repo root:   pytest -q tests/test_tool_selftests.py
"""
import importlib
import sys
import tempfile
import os
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

_TOOLS = ["preflight", "occ_guard", "hole_metrics", "unit_normalize",
          "regiondiff", "perceive", "surface_histogram", "drawing_extract"]


@pytest.mark.parametrize("mod", _TOOLS)
def test_tool_imports_clean(mod):
    importlib.import_module(mod)


def test_occ_guard_selftest_passes():
    import occ_guard
    assert occ_guard._selftest() == 0


def test_perceive_selftest_passes():
    import perceive
    assert perceive._selftest() == 0


def test_surface_histogram_kernel_stable():
    """The headline guarantee: a part's surface-type histogram is IDENTICAL in-memory
    vs after a STEP export->reimport (where exact edge counts shift, e.g. 51->49 on the
    L-bracket). Build the bearing in-process (GT-free), export to a scratch STEP, compare."""
    import importlib.util
    import surface_histogram as sh
    from build123d import export_step, import_step

    gen = REPO / "tasks" / "bearing_608" / "make_ground_truth.py"
    if not gen.exists():
        pytest.skip("bearing_608 generator not present")
    spec = importlib.util.spec_from_file_location("bearing_gen", str(gen))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    solid = m.build()

    h_mem = sh.surface_histogram(solid)
    ws = tempfile.mkdtemp(prefix="test_sh_")
    step = os.path.join(ws, "b.step")
    export_step(solid, step)
    h_step = sh.surface_histogram(import_step(step))
    assert h_mem == h_step, f"histogram changed across STEP round-trip: {h_mem} vs {h_step}"
    # and a self-similarity sanity check
    assert abs(sh.histogram_similarity(h_mem, h_mem) - 1.0) < 1e-9
