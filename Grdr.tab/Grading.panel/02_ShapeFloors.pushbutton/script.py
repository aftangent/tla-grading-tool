# -*- coding: utf-8 -*-
import traceback
import clr
clr.AddReference("PresentationFramework")
clr.AddReference("PresentationCore")
clr.AddReference("WindowsBase")
clr.AddReference("System.Xml")

from pyrevit import forms, script
from Autodesk.Revit.DB import (
    Transaction, XYZ, Floor, Toposolid,
    BuiltInParameter, Options, Level
)
from Autodesk.Revit.UI.Selection import ObjectType, ISelectionFilter

doc   = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument

class ToposolidFilter(ISelectionFilter):
    def AllowElement(self, e):
        return isinstance(e, Toposolid)
    def AllowReference(self, r, p):
        return False

class FloorFilter(ISelectionFilter):
    def AllowElement(self, e):
        return isinstance(e, Floor)
    def AllowReference(self, r, p):
        return False

def build_topo_mesh(topo):
    opt = Options()
    opt.ComputeReferences = False
    opt.IncludeNonVisibleObjects = False
    triangles = []
    try:
        geom = topo.get_Geometry(opt)
        for obj in geom:
            try:
                for face in obj.Faces:
                    try:
                        mesh = face.Triangulate()
                        if mesh is None:
                            continue
                        for i in range(mesh.NumTriangles):
                            tri = mesh.get_Triangle(i)
                            triangles.append((
                                tri.get_Vertex(0),
                                tri.get_Vertex(1),
                                tri.get_Vertex(2)
                            ))
                    except:
                        continue
            except:
                continue
    except:
        pass
    return triangles

def interpolate_z_detailed(triangles, x, y):
    best_z    = None
    best_dist = float('inf')
    hits      = 0
    for (v0, v1, v2) in triangles:
        denom = ((v1.Y - v2.Y)*(v0.X - v2.X) +
                 (v2.X - v1.X)*(v0.Y - v2.Y))
        if abs(denom) < 1e-9:
            continue
        a = ((v1.Y - v2.Y)*(x - v2.X) +
             (v2.X - v1.X)*(y - v2.Y)) / denom
        b = ((v2.Y - v0.Y)*(x - v2.X) +
             (v0.X - v2.X)*(y - v2.Y)) / denom
        c = 1.0 - a - b
        if a >= -0.01 and b >= -0.01 and c >= -0.01:
            hits += 1
            return a*v0.Z + b*v1.Z + c*v2.Z, "barycentric"
        cx = (v0.X + v1.X + v2.X) / 3.0
        cy = (v0.Y + v1.Y + v2.Y) / 3.0
        dist = (cx - x)**2 + (cy - y)**2
        if dist < best_dist:
            best_dist = dist
            best_z    = (v0.Z + v1.Z + v2.Z) / 3.0
    return best_z, "FALLBACK dist={:.1f}ft".format(best_dist**0.5)

try:
    forms.alert("Select SOURCE Toposolid.", title="XY Audit", ok=True)
    try:
        topo_ref  = uidoc.Selection.PickObject(ObjectType.Element,
                                               ToposolidFilter(), "Select Toposolid")
        topo_elem = doc.GetElement(topo_ref.ElementId)
    except:
        script.exit()

    forms.alert("Select TARGET floors.", title="XY Audit", ok=True)
    try:
        floor_refs  = uidoc.Selection.PickObjects(ObjectType.Element,
                                                  FloorFilter(), "Select floors")
        floor_elems = [doc.GetElement(r.ElementId) for r in floor_refs]
    except:
        script.exit()

    triangles = build_topo_mesh(topo_elem)
    z_all = [v.Z for tri in triangles for v in tri]
    x_all = [v.X for tri in triangles for v in tri]
    y_all = [v.Y for tri in triangles for v in tri]

    log = [
        "XY BOUNDS AUDIT",
        "Topo X: {:.1f} to {:.1f}ft".format(min(x_all), max(x_all)),
        "Topo Y: {:.1f} to {:.1f}ft".format(min(y_all), max(y_all)),
        "Topo Z: {:.3f} to {:.3f}ft".format(min(z_all), max(z_all)),
        "Triangles: {}".format(len(triangles)),
        ""
    ]

    for floor in floor_elems:
        try:
            bb   = floor.get_BoundingBox(None)
            fxmn = bb.Min.X
            fxmx = bb.Max.X
            fymn = bb.Min.Y
            fymx = bb.Max.Y
            cx   = (fxmn + fxmx) / 2.0
            cy   = (fymn + fymx) / 2.0
            xov  = fxmx >= min(x_all) and fxmn <= max(x_all)
            yov  = fymx >= min(y_all) and fymn <= max(y_all)
            tz, method = interpolate_z_detailed(triangles, cx, cy)
            log.append("Floor id={}".format(floor.Id))
            log.append("  Floor X: {:.1f} to {:.1f}".format(fxmn, fxmx))
            log.append("  Floor Y: {:.1f} to {:.1f}".format(fymn, fymx))
            log.append("  Centre: ({:.1f}, {:.1f})".format(cx, cy))
            log.append("  Overlaps topo: X={} Y={}".format(xov, yov))
            log.append("  Topo Z: {:.4f}ft via {}".format(
                tz if tz is not None else -9999, method))
            log.append("")
        except Exception:
            log.append("Floor {}: ERROR\n{}".format(
                floor.Id, traceback.format_exc()))

    forms.alert("\n".join(log), title="XY Audit", ok=True)

except Exception:
    forms.alert(traceback.format_exc(), title="ERROR", ok=True)