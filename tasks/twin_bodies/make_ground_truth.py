from pathlib import Path
import json
from build123d import BuildPart, Box, Locations, Align, export_step, export_stl
OUT = Path(__file__).resolve().parent / "ground_truth"; OUT.mkdir(exist_ok=True)
def build():
    with BuildPart() as p:
        with Locations((-40,0,0),(40,0,0)):   # two identical boxes, 80mm apart, symmetric
            Box(30, 30, 20, align=(Align.CENTER, Align.CENTER, Align.MIN))
    return p.part
solid = build()
export_step(solid, str(OUT/"result.step")); export_stl(solid, str(OUT/"result.stl"), tolerance=0.05)
bb=solid.bounding_box()
(OUT/"meta.json").write_text(json.dumps({"volume": float(abs(solid.volume)), "bbox":[float(bb.size.X),float(bb.size.Y),float(bb.size.Z)]}))
from OCP.TopExp import TopExp_Explorer
from OCP.TopAbs import TopAbs_FACE,TopAbs_EDGE,TopAbs_VERTEX,TopAbs_SHELL,TopAbs_SOLID
w=solid.wrapped
def c(k):
    e=TopExp_Explorer(w,k); s=set()
    while e.More(): s.add(e.Current().__hash__()); e.Next()
    return len(s)
_f=c(TopAbs_FACE);_e=c(TopAbs_EDGE);_v=c(TopAbs_VERTEX)
sig={"faces":_f,"edges":_e,"vertices":_v,"shells":c(TopAbs_SHELL),"solids":c(TopAbs_SOLID),"euler":_v-_e+_f}
(OUT/"topology.json").write_text(json.dumps(sig))
print("GT:", {"vol":round(abs(solid.volume),1),"bbox":[round(bb.size.X,1),round(bb.size.Y,1),round(bb.size.Z,1)],"topo":sig})
