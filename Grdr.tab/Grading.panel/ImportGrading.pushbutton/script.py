import sys, os, traceback
from pyrevit import forms, script
from Autodesk.Revit.DB import (
    FilteredElementCollector, Level, Transaction,
    XYZ, CurveLoop, Line, ToposolidType, Toposolid
)
from System.Collections.Generic import List as NetList

doc = __revit__.ActiveUIDocument.Document
MM_TO_FT = 1.0 / 304.8
M_TO_FT  = 3.28084
BACKSLASH_P = chr(92) + "P"

def parse_level(raw):
    if not raw:
        return None
    text = raw.strip()
    if BACKSLASH_P in text:
        parts = text.split(BACKSLASH_P)
        prefix_part = parts[0].strip().replace(" ", "")
        for part in parts[1:]:
            elev_str = part.strip()
            if elev_str.startswith("+") or (elev_str and elev_str[0].isdigit()):
                try:
                    return {"prefix": prefix_part, "value": float(elev_str.lstrip("+"))}
                except ValueError:
                    pass
        return None
    if "+" not in text:
        return None
    idx = text.index("+")
    prefix = text[:idx].strip().replace(" ", "")
    value_str = text[idx+1:].strip()
    if not prefix or not all(c.isalpha() and c.isupper() for c in prefix):
        return None
    try:
        return {"prefix": prefix, "value": float(value_str)}
    except ValueError:
        return None

def read_dxf(dxf_path, target_layer="TLA-LEVEL TEXT"):
    with open(dxf_path, "r") as f:
        lines = [l.strip() for l in f.readlines()]
    results = []
    total = len(lines)
    i = 0
    while i < total - 1:
        if lines[i] == "0" and i+1 < total and lines[i+1] == "ATTRIB":
            entity = {"layer":None,"text":None,"x":None,"y":None,"tag":None}
            j = i + 2
            while j < total - 1:
                if lines[j] == "0": break
                if lines[j] == "8" and j+1 < total: entity["layer"] = lines[j+1]
                elif lines[j] == "1" and j+1 < total: entity["text"] = lines[j+1]
                elif lines[j] == "10" and j+1 < total:
                    try: entity["x"] = float(lines[j+1])
                    except ValueError: pass
                elif lines[j] == "20" and j+1 < total:
                    try: entity["y"] = float(lines[j+1])
                    except ValueError: pass
                elif lines[j] == "2" and j+1 < total: entity["tag"] = lines[j+1]
                j += 2
            if (entity["layer"] == target_layer
                    and entity["tag"] and "LEVEL1" in entity["tag"].upper()
                    and entity["x"] is not None
                    and entity["y"] is not None):
                text = entity["text"] or ""
                parsed = parse_level(text)
                if parsed:
                    results.append({
                        "prefix": parsed["prefix"],
                        "value": parsed["value"],
                        "raw": text,
                        "x": entity["x"],
                        "y": entity["y"],
                        "confidence": "ok"
                    })
        i += 2
    return results

def find_ground_level(doc):
    levels = sorted(FilteredElementCollector(doc).OfClass(Level).ToElements(),
                    key=lambda l: l.Elevation)
    for lv in levels:
        if "ground" in lv.Name.lower():
            return lv
    return levels[0] if levels else None

def pick_level(doc):
    levels = sorted(FilteredElementCollector(doc).OfClass(Level).ToElements(),
                    key=lambda l: l.Elevation)
    names = ["{} ({:.0f} mm)".format(lv.Name, lv.Elevation * 304.8) for lv in levels]
    chosen = forms.SelectFromList.show(names, title="Select Base Level",
                                       message="Choose the Toposolid base level:",
                                       multiselect=False)
    if not chosen: return None
    return levels[names.index(chosen)]

def create_toposolid(doc, confirmed_points, base_level):
    revit_points = []
    for pt in confirmed_points:
        x_ft = pt["x"] * MM_TO_FT
        y_ft = pt["y"] * MM_TO_FT
        z_ft = pt["value"] * M_TO_FT
        revit_points.append(XYZ(x_ft, y_ft, z_ft))
    xs = [p.X for p in revit_points]
    ys = [p.Y for p in revit_points]
    zs = [p.Z for p in revit_points]
    pad = 5.0
    min_x, max_x = min(xs)-pad, max(xs)+pad
    min_y, max_y = min(ys)-pad, max(ys)+pad
    min_z = min(zs)
    p1 = XYZ(min_x, min_y, min_z)
    p2 = XYZ(max_x, min_y, min_z)
    p3 = XYZ(max_x, max_y, min_z)
    p4 = XYZ(min_x, max_y, min_z)
    loop = CurveLoop()
    loop.Append(Line.CreateBound(p1, p2))
    loop.Append(Line.CreateBound(p2, p3))
    loop.Append(Line.CreateBound(p3, p4))
    loop.Append(Line.CreateBound(p4, p1))
    curve_loops = NetList[CurveLoop]()
    curve_loops.Add(loop)
    net_points = NetList[XYZ]()
    for p in revit_points:
        net_points.Add(p)
    topo_types = FilteredElementCollector(doc).OfClass(ToposolidType).ToElements()
    if not topo_types:
        return None, "No ToposolidType found."
    topo_type_id = topo_types[0].Id
    t = Transaction(doc, "TLA Grading - Create Toposolid")
    t.Start()
    try:
        topo = Toposolid.Create(doc, curve_loops, net_points, topo_type_id, base_level.Id)
        t.Commit()
        return topo, None
    except Exception as e:
        t.RollBack()
        return None, str(e)

try:
    dxf_path = forms.pick_file(file_ext="dxf", title="Select the DXF file")
    if not dxf_path: script.exit()

    all_points = read_dxf(dxf_path)
    if not all_points:
        forms.alert("No level points found on layer TLA-LEVEL TEXT.", ok=True)
        script.exit()

    counts = {}
    for pt in all_points:
        counts[pt["prefix"]] = counts.get(pt["prefix"], 0) + 1
    prefix_options = ["{} ({} found)".format(k, v) for k, v in sorted(counts.items())]
    chosen = forms.SelectFromList.show(prefix_options, title="Select Level Types",
                                       message="Choose prefixes to import:",
                                       multiselect=True)
    if not chosen: script.exit()
    selected = [c.split(" ")[0] for c in chosen]
    filtered = [pt for pt in all_points if pt["prefix"] in selected]

    ext_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
    lib_dir = os.path.join(ext_dir, "lib")
    if lib_dir not in sys.path:
        sys.path.insert(0, lib_dir)
    from tla_grading import review_form
    confirmed = review_form.show_review_form(filtered)
    if confirmed is None: script.exit()
    if not confirmed:
        forms.alert("No points selected.", ok=True)
        script.exit()

    ground = find_ground_level(doc)
    if ground:
        use_ground = forms.alert(
            "Found level {} ({:.0f} mm).\nUse as Toposolid base level?".format(
                ground.Name, ground.Elevation * 304.8),
            title="Base Level", yes=True, no=True)
        base_level = ground if use_ground else pick_level(doc)
    else:
        base_level = pick_level(doc)
    if not base_level: script.exit()

    topo, error = create_toposolid(doc, confirmed, base_level)
    if error:
        forms.alert("Failed:\n\n{}".format(error), title="Error", ok=True)
        script.exit()

    forms.alert(
        "Toposolid created!\n\n{} points\nBase level: {}".format(
            len(confirmed), base_level.Name),
        title="TLA Grading - Done", ok=True)

except Exception:
    forms.alert(traceback.format_exc(), title="ERROR", ok=True)