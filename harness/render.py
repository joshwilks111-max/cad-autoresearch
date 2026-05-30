"""
render.py — headless multi-view renders for multimodal feedback.

An agent reasoning about CAD from code needs the static equivalent of "walking
around the part": a few viewpoints it can actually look at. We render candidate
and (optionally) ground-truth meshes from four canonical views using matplotlib's
Agg backend, so this works on a headless box with no OpenGL context. These PNGs
are what a worker's vision subagent inspects before deciding what to fix.
"""
from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt           # noqa: E402
import numpy as np                         # noqa: E402
import trimesh                             # noqa: E402

_VIEWS = {"iso": (28, 45), "front": (0, -90), "top": (90, -90), "right": (0, 0)}


def _draw(ax, mesh: trimesh.Trimesh, title: str):
    if mesh is None or len(mesh.faces) == 0:
        ax.set_title(f"{title}\n(empty)")
        ax.set_axis_off()
        return
    v, f = mesh.vertices, mesh.faces
    ax.plot_trisurf(v[:, 0], v[:, 1], v[:, 2], triangles=f,
                    color=(0.62, 0.67, 0.72), edgecolor=(0.25, 0.28, 0.32),
                    linewidth=0.1, antialiased=True, shade=True)
    c = v.mean(axis=0)
    r = float(np.max(np.abs(v - c))) or 1.0
    ax.set_xlim(c[0] - r, c[0] + r)
    ax.set_ylim(c[1] - r, c[1] + r)
    ax.set_zlim(c[2] - r, c[2] + r)
    ax.set_box_aspect((1, 1, 1))
    ax.set_title(title, fontsize=9)
    ax.set_axis_off()


def render_compare(candidate_mesh: trimesh.Trimesh,
                   gt_mesh: trimesh.Trimesh | None,
                   out_dir: str | Path,
                   tag: str = "attempt") -> list[str]:
    """Write one PNG per viewpoint (candidate top, GT bottom if given).
    Returns the written file paths."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for name, (elev, azim) in _VIEWS.items():
        rows = 2 if gt_mesh is not None else 1
        fig = plt.figure(figsize=(4, 4 * rows))
        ax1 = fig.add_subplot(rows, 1, 1, projection="3d")
        ax1.view_init(elev=elev, azim=azim)
        _draw(ax1, candidate_mesh, f"CANDIDATE · {name}")
        if gt_mesh is not None:
            ax2 = fig.add_subplot(rows, 1, 2, projection="3d")
            ax2.view_init(elev=elev, azim=azim)
            _draw(ax2, gt_mesh, f"GROUND TRUTH · {name}")
        p = out_dir / f"{tag}_{name}.png"
        fig.tight_layout()
        fig.savefig(p, dpi=90)
        plt.close(fig)
        paths.append(str(p))
    return paths
