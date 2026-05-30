from pathlib import Path
import json
from build123d import *
OUT=Path(__file__).resolve().parent/"ground_truth"; OUT.mkdir(exist_ok=True)
with BuildPart() as p:
    Box(80,40,5, align=(Align.CENTER,Align.CENTER,Align.MIN))
    with Locations((0,0,5)):
        with GridLocations(12,20,6,2): Box(2,4,6,align=(Align.CENTER,Align.CENTER,Align.MIN))
solid=p.part
export_step(solid,str(OUT/"result.step")); export_stl(solid,str(OUT/"result.stl"),tolerance=0.05)
bb=solid.bounding_box()
(OUT/"meta.json").write_text(json.dumps({"volume":float(abs(solid.volume)),"bbox":[float(bb.size.X),float(bb.size.Y),float(bb.size.Z)]}))
from OCP.TopExp import TopExp_Explorer
from OCP.TopAbs import TopAbs_FACE,TopAbs_EDGE,TopAbs_VERTEX,TopAbs_SHELL,TopAbs_SOLID
w=solid.wrapped
def c(k):
    e=TopExp_Explorer(w,k); s=set()
    while e.More(): s.add(e.Current().__hash__()); e.Next()
    return len(s)
_f,_e,_v=c(TopAbs_FACE),c(TopAbs_EDGE),c(TopAbs_VERTEX)
(OUT/"topology.json").write_text(json.dumps({"faces":_f,"edges":_e,"vertices":_v,"shells":c(TopAbs_SHELL),"solids":c(TopAbs_SOLID),"euler":_v-_e+_f}))
print("rib GT built")
