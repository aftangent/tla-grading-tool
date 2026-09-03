# -*- coding: utf-8 -*-
import traceback, math
import clr
from pyrevit import forms, script
from Autodesk.Revit.DB import (
    FilteredElementCollector, Transaction, XYZ,
    BuiltInParameter, BuiltInCategory, ViewPlan,
    SpotDimension, SpotDimensionType, Options, UV,
)

doc   = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument

M_TO_FT = 3.28084
FT_TO_M = 1.0 / M_TO_FT
TOW_THRESHOLD_M = 0.300
ALL_PREFIXES = ["FFL","FSL","TOW","TOS","TOR","TOK","FRL","WL","BL","TOM","SSL","RL","BOK"]

CLOCK_DEG = {
    "12":90.0,"1:30":45.0,"3":0.0,"4:30":-45.0,
    "6":-90.0,"7:30":-135.0,"9":180.0,"10:30":135.0,
}

CAT_MAP = {
    int(BuiltInCategory.OST_Floors):        "FFL",
    int(BuiltInCategory.OST_Toposolid):     "FFL",
    int(BuiltInCategory.OST_Walls):         "TOW",
    int(BuiltInCategory.OST_Planting):      "FSL",
    int(BuiltInCategory.OST_Railings):      "TOR",
    int(BuiltInCategory.OST_Ramps):         "FFL",
    int(BuiltInCategory.OST_Stairs):        "FFL",
    int(BuiltInCategory.OST_Furniture):     "TOS",
    int(BuiltInCategory.OST_SiteHardscape): "FFL",
}
WORKSET_MAP = {
    "planting":"FSL","landscape":"FFL","hardscape":"FFL",
    "furniture":"TOS","seating":"TOS","water":"WL","railing":"TOR","wall":"TOW",
}

def get_top_m(elem):
    try:
        bb = elem.get_BoundingBox(None)
        if bb: return bb.Max.Z * FT_TO_M
    except: pass
    return None

def get_workset_name(elem):
    try:
        ws = doc.GetWorksetTable().GetWorkset(elem.WorksetId)
        return ws.Name.lower() if ws else ""
    except: return ""

def auto_classify(elem, arc_ffl_m):
    cat_id = elem.Category.Id.IntegerValue if elem.Category else None
    pfx = CAT_MAP.get(cat_id)
    if pfx:
        if pfx == "FFL" and arc_ffl_m is not None:
            top = get_top_m(elem)
            if top is not None and (top - arc_ffl_m) > TOW_THRESHOLD_M:
                return "TOW"
        return pfx
    ws = get_workset_name(elem)
    for kw, p in WORKSET_MAP.items():
        if kw in ws: return p
    return None

def get_family_name(elem):
    try:
        fp = elem.get_Parameter(BuiltInParameter.ELEM_FAMILY_PARAM)
        if fp: return fp.AsString() or "(no family)"
    except: pass
    try: return elem.Category.Name if elem.Category else "(unknown)"
    except: return "(unknown)"

def get_slab_pts(elem):
    try:
        sse = elem.GetSlabShapeEditor()
        if sse is None: return []
        creases = sse.SlabShapeCreaseArray
        if creases is None or creases.Size == 0: return []
        pts = []
        for c in creases:
            v = c.SlabShapeVertexArray
            if v:
                for vtx in v: pts.append(vtx.Position)
        return pts
    except: return []

def get_centroid(pts):
    if not pts: return None
    n = float(len(pts))
    return XYZ(sum(p.X for p in pts)/n, sum(p.Y for p in pts)/n, sum(p.Z for p in pts)/n)

def get_ref_point(elem):
    pts = get_slab_pts(elem)
    centroid = get_centroid(pts) if pts else None
    if centroid is None:
        bb = elem.get_BoundingBox(None)
        if bb is None: return None, None
        centroid = XYZ((bb.Min.X+bb.Max.X)/2.0,(bb.Min.Y+bb.Max.Y)/2.0, bb.Max.Z)
    ref = None
    try:
        opts = Options(); opts.ComputeReferences = True
        geom = elem.get_Geometry(opts)
        if geom:
            for obj in geom:
                try:
                    for face in obj.Faces:
                        if face.FaceNormal.Z > 0.5:
                            ref = face.Reference
                            bb2 = face.GetBoundingBox()
                            fp = face.Evaluate(UV((bb2.Min.U+bb2.Max.U)/2.0,(bb2.Min.V+bb2.Max.V)/2.0))
                            centroid = XYZ(centroid.X, centroid.Y, fp.Z)
                            break
                    if ref: break
                except: continue
    except: pass
    return centroid, ref

def find_spot_type(prefix):
    name = "LA_SP_2.5mm-{}".format(prefix)
    for t in FilteredElementCollector(doc).OfClass(SpotDimensionType):
        n = t.get_Parameter(BuiltInParameter.ALL_MODEL_TYPE_NAME)
        if n and n.AsString() == name: return t
    all_t = list(FilteredElementCollector(doc).OfClass(SpotDimensionType))
    return all_t[0] if all_t else None

def place_spot(elem, prefix, centroid, ref, dx, dy):
    if find_spot_type(prefix) is None:
        return False, "No SpotDimensionType for {}".format(prefix)
    view = doc.ActiveView
    tp = XYZ(centroid.X+dx,     centroid.Y+dy,     centroid.Z)
    le = XYZ(centroid.X+dx*0.3, centroid.Y+dy*0.3, centroid.Z)
    try:
        doc.Create.NewSpotElevation(view, ref, centroid, le, tp, tp, True)
        return True, None
    except Exception as ex:
        try:
            doc.Create.NewSpotElevation(view, None, centroid, le, tp, tp, False)
            return True, "No face ref: {}".format(str(ex))
        except Exception as ex2:
            return False, str(ex2)

try:
    # Guard
    if not isinstance(doc.ActiveView, ViewPlan):
        forms.alert("Please open a Plan View first.", title="Place Annotation")
        script.exit()

    # Step 1: Select prefixes
    chosen_pfx = forms.SelectFromList.show(
        ALL_PREFIXES,
        title="Place Annotation - Select Prefixes",
        multiselect=True,
        button_name="Next"
    )
    if not chosen_pfx: script.exit()
    active_prefixes = list(chosen_pfx)

    # Step 2: Select elements
    forms.alert(
        "Draw a selection box around elements to annotate (max 30 recommended).\nPress Finish when done.",
        title="Select Elements"
    )
    try:
        sel = uidoc.Selection.PickElementsByRectangle("Select elements")
    except Exception:
        try:
            from Autodesk.Revit.UI.Selection import ObjectType
            sel_refs = uidoc.Selection.PickObjects(ObjectType.Element, "Select elements")
            sel = [doc.GetElement(r.ElementId) for r in sel_refs]
        except: sel = []

    if not sel:
        forms.alert("No elements selected."); script.exit()
    if len(sel) > 30:
        forms.alert("Warning: {} elements selected (max 30 recommended). Proceeding.".format(len(sel)))

    # Step 3: ARC FFL
    arc_val = forms.ask_for_string(
        prompt="Enter ARC FFL elevation in metres (e.g. 7.050).\nLeave blank to skip.",
        title="ARC FFL Reference",
        default=""
    )
    if arc_val is None: script.exit()
    try: arc_ffl_m = float(arc_val.strip()) if arc_val.strip() else 0.0
    except: arc_ffl_m = 0.0

    # Step 4: Auto-classify
    classified = {}; unresolved = {}
    for elem in sel:
        prefix = auto_classify(elem, arc_ffl_m)
        if prefix and prefix in active_prefixes:
            classified[elem.Id.IntegerValue] = (elem, prefix)
        else:
            fname = get_family_name(elem)
            if fname not in unresolved: unresolved[fname] = []
            unresolved[fname].append(elem)

    # Step 5: Match unresolved families -> prefixes one by one
    if unresolved:
        for fname in sorted(unresolved.keys()):
            chosen = forms.SelectFromList.show(
                active_prefixes,
                title="Map Family to Prefix",
                prompt="Family: {}\nSelect prefix:".format(fname),
                multiselect=False,
                button_name="Assign"
            )
            if chosen:
                for elem in unresolved[fname]:
                    classified[elem.Id.IntegerValue] = (elem, chosen)

    if not classified:
        forms.alert("No elements classified. Nothing to place."); script.exit()

    # Step 6: Direction
    clock_opts = list(CLOCK_DEG.keys()) + ["Custom angle..."]
    chosen_dir = forms.SelectFromList.show(
        clock_opts,
        title="Annotation Direction",
        prompt="Select clock position for annotation offset:",
        multiselect=False,
        button_name="Next"
    )
    if not chosen_dir: script.exit()

    if chosen_dir == "Custom angle...":
        ca = forms.ask_for_string(prompt="Enter angle in degrees (0=East, 90=North):", title="Custom Angle", default="0")
        if ca is None: script.exit()
        try: deg = float(ca)
        except: deg = 0.0
    else:
        deg = CLOCK_DEG[chosen_dir]

    # Step 7: Offset
    off_val = forms.ask_for_string(prompt="Enter offset distance in metres:", title="Offset Distance", default="2.0")
    if off_val is None: script.exit()
    try: offset_m = float(off_val.strip())
    except: offset_m = 2.0

    rad = math.radians(deg)
    dx_ft = math.cos(rad) * offset_m * M_TO_FT
    dy_ft = math.sin(rad) * offset_m * M_TO_FT

    # Step 8: Place
    placed = 0; errors = []
    t = Transaction(doc, "TLA - Place Spot Annotations")
    t.Start()
    try:
        for eid, (elem, prefix) in classified.items():
            centroid, ref = get_ref_point(elem)
            if centroid is None:
                errors.append("No geometry: element {}".format(eid)); continue
            ok, msg = place_spot(elem, prefix, centroid, ref, dx_ft, dy_ft)
            if ok: placed += 1
            else: errors.append("{} ({}): {}".format(prefix, eid, msg))
        t.Commit()
    except Exception:
        t.RollBack()
        forms.alert("Transaction failed:\n{}".format(traceback.format_exc()), title="ERROR")
        script.exit()

    summary = "Placed {} spot annotation(s).".format(placed)
    if errors: summary += "\n\nWarnings/Errors:\n" + "\n".join(errors[:15])
    forms.alert(summary, title="Place Annotation - Done")

except Exception:
    forms.alert(traceback.format_exc(), title="ERROR")
