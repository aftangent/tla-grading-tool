import sys, os, traceback, math, re
from pyrevit import forms, script
from Autodesk.Revit.DB import (
    FilteredElementCollector, Level, Transaction,
    XYZ, CurveLoop, Line, ToposolidType, Toposolid,
    BuiltInParameter, MaterialFunctionAssignment,
    FailureHandlingOptions, FailureProcessingResult, IFailuresPreprocessor
)
from System.Collections.Generic import List as NetList

doc = __revit__.ActiveUIDocument.Document
MM_TO_FT = 1.0 / 304.8
M_TO_FT  = 3.28084
BACKSLASH_P = chr(92) + "P"
TOPO_TYPE_NAME = "Dummy Floor For grading (edtrafc)"
SLOPE_SEARCH_R = 15000.0
SLOPE_INTERP_N = 5

ext_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
lib_dir = os.path.join(ext_dir, "lib")
if lib_dir not in sys.path:
    sys.path.insert(0, lib_dir)
from tla_grading.review_form import (
    show_review_form, show_list_dialog, show_alert,
    show_yes_no, show_input_dialog, show_copyable_alert
)

def strip_mtext(text):
    if not text: return text
    t = text.strip()
    if t.startswith("{") and t.endswith("}"):
        t = re.sub(r'\\[A-Za-z]\d*;', '', t[1:-1]).strip()
    return t

def parse_level(raw):
    if not raw: return None
    text = strip_mtext(raw)
    if BACKSLASH_P in text:
        parts = text.split(BACKSLASH_P)
        pfx = parts[0].strip().replace(" ", "")
        for part in parts[1:]:
            es = part.strip()
            if es.startswith("+") or (es and es[0].isdigit()):
                try: return {"prefix": pfx, "value": float(es.lstrip("+"))}
                except: pass
        return None
    if "+" not in text: return None
    idx = text.index("+")
    pfx = text[:idx].strip().replace(" ", "")
    vs  = text[idx+1:].strip()
    if not pfx or not all(c.isalpha() and c.isupper() for c in pfx): return None
    try: return {"prefix": pfx, "value": float(vs)}
    except: return None

def _rot(x, y, deg):
    a = math.radians(deg)
    return (x*math.cos(a)-y*math.sin(a), x*math.sin(a)+y*math.cos(a))

def read_dxf(dxf_path, target_layer="TLA-LEVEL TEXT"):
    with open(dxf_path, "r") as f:
        lines = [l.strip() for l in f.readlines()]
    results, skipped = [], []
    total = len(lines)
    i = 0; lix, liy = None, None
    while i < total - 1:
        if lines[i] == "0" and lines[i+1] == "INSERT":
            ix, iy = None, None; j = i + 2
            while j < total - 1:
                if lines[j] == "0": break
                if lines[j] == "10" and j+1 < total:
                    try: ix = float(lines[j+1])
                    except: pass
                elif lines[j] == "20" and j+1 < total:
                    try: iy = float(lines[j+1])
                    except: pass
                j += 2
            if ix is not None and iy is not None: lix, liy = ix, iy
        if lines[i] == "0" and lines[i+1] == "ATTRIB":
            ent = {"layer": None, "text": None, "tag": None}; j = i + 2
            while j < total - 1:
                if lines[j] == "0": break
                if lines[j] == "8"  and j+1 < total: ent["layer"] = lines[j+1]
                elif lines[j] == "1" and j+1 < total: ent["text"]  = lines[j+1]
                elif lines[j] == "2" and j+1 < total: ent["tag"]   = lines[j+1]
                j += 2
            if (ent["layer"] == target_layer and ent["tag"]
                    and "LEVEL1" in ent["tag"].upper() and lix is not None):
                raw = ent["text"] or ""
                cleaned = strip_mtext(raw)
                parsed = parse_level(raw)
                if parsed:
                    results.append({"prefix": parsed["prefix"], "value": parsed["value"],
                                    "raw": cleaned, "x": lix, "y": liy, "confidence": "ok"})
                else:
                    skipped.append(cleaned or raw)
        i += 2
    return results, skipped

def read_slope_arrows(dxf_path):
    with open(dxf_path, "r") as f:
        lines = [l.strip() for l in f.readlines()]
    total = len(lines); arrows = []; i = 0
    LOW_OFF  = -2623.672863902379
    HIGH_OFF =  1835.827136097621
    while i < total - 1:
        if lines[i] == "0" and lines[i+1] == "INSERT":
            bname = None; ix, iy, ang, scl = None, None, 0.0, 1.0; j = i + 2
            while j < total - 1:
                if lines[j] == "0": break
                if lines[j] == "2" and j+1 < total: bname = lines[j+1]
                elif lines[j] == "10" and j+1 < total:
                    try: ix = float(lines[j+1])
                    except: pass
                elif lines[j] == "20" and j+1 < total:
                    try: iy = float(lines[j+1])
                    except: pass
                elif lines[j] == "50" and j+1 < total:
                    try: ang = float(lines[j+1])
                    except: pass
                elif lines[j] == "41" and j+1 < total:
                    try: scl = float(lines[j+1])
                    except: pass
                j += 2
            if ix is None: i += 2; continue
            lvl_text = None; k = j
            while k < total - 1:
                if lines[k] == "0" and k+1 < total:
                    if lines[k+1] == "SEQEND": break
                    if lines[k+1] == "ATTRIB":
                        tag, text = None, None; m = k + 2
                        while m < total - 1:
                            if lines[m] == "0": break
                            if lines[m] == "2" and m+1 < total: tag  = lines[m+1]
                            elif lines[m] == "1" and m+1 < total: text = lines[m+1]
                            m += 2
                        if tag == "LVL": lvl_text = text
                k += 1
            if not lvl_text: i += 2; continue
            m2 = re.match(r"([\d.]+)\s*%", lvl_text.strip())
            if not m2: i += 2; continue
            try: pct = float(m2.group(1))
            except: i += 2; continue
            cos_a = math.cos(math.radians(ang))
            sin_a = math.sin(math.radians(ang))
            lx = LOW_OFF  * scl * cos_a
            ly = LOW_OFF  * scl * sin_a
            hx = HIGH_OFF * scl * cos_a
            hy = HIGH_OFF * scl * sin_a
            arrows.append({"bname": bname, "insert": (ix, iy),
                           "low": (ix+lx, iy+ly), "high": (ix+hx, iy+hy),
                           "pct": pct, "lvl": lvl_text})
        i += 2
    return arrows

def build_slope_preview(arrows, level_pts_abs):
    preview = []; arrow_data = []; warnings = []
    for arr in arrows:
        low_pt = arr["low"]; high_pt = arr["high"]
        pct = arr["pct"];    lvl = arr["lvl"]
        def cands(pt):
            return sorted([(math.sqrt((p["x"]-pt[0])**2+(p["y"]-pt[1])**2), p)
                           for p in level_pts_abs
                           if math.sqrt((p["x"]-pt[0])**2+(p["y"]-pt[1])**2) <= SLOPE_SEARCH_R])
        lc = cands(low_pt); hc = cands(high_pt)
        if not lc:
            warnings.append("SKIPPED '{}' at (X:{:.0f},Y:{:.0f}): no level within {:.0f}mm of LOW end".format(
                lvl, low_pt[0], low_pt[1], SLOPE_SEARCH_R))
            arrow_data.append(None); continue
        if not hc:
            warnings.append("SKIPPED '{}' at (X:{:.0f},Y:{:.0f}): no level within {:.0f}mm of HIGH end".format(
                lvl, high_pt[0], high_pt[1], SLOPE_SEARCH_R))
            arrow_data.append(None); continue
        z_low  = lc[0][1]["value"]
        z_high = hc[0][1]["value"]
        if z_high < z_low:
            z_low, z_high = z_high, z_low
            low_pt, high_pt = high_pt, low_pt
        run_mm = math.sqrt((high_pt[0]-low_pt[0])**2+(high_pt[1]-low_pt[1])**2)
        if pct is not None and run_mm > 0:
            calc = ((z_high-z_low)*1000.0/run_mm)*100.0
            rd   = math.floor(calc/0.5)*0.5
            if abs(rd-pct) > 1.0:
                warnings.append("WARNING '{}' at (X:{:.0f},Y:{:.0f}): stated {}% but calc {:.2f}% (rounded {}%) - using stated".format(
                    lvl, low_pt[0], low_pt[1], pct, calc, rd))
        stated_rise = (pct/100.0)*(run_mm/1000.0) if pct else (z_high-z_low)
        elev_label  = "{:.2f}->{:.2f}".format(z_high, z_low)
        mid_x = (low_pt[0]+high_pt[0])/2.0
        mid_y = (low_pt[1]+high_pt[1])/2.0
        preview.append({"prefix": lvl, "value": (z_high+z_low)/2.0, "raw": lvl,
                        "elev_label": elev_label, "x": mid_x, "y": mid_y, "confidence": "slope"})
        arrow_data.append({"arr": arr, "z_high": z_high, "z_low": z_low,
                           "stated_rise": stated_rise, "elev_label": elev_label})
    return preview, arrow_data, warnings

def build_interp_and_splits(arrow_data_list, ref_value):
    interp = []; splits = []
    for ad in arrow_data_list:
        if ad is None: continue
        arr = ad["arr"]; z_high = ad["z_high"]; z_low = ad["z_low"]
        stated_rise = ad["stated_rise"]; elev_label = ad["elev_label"]
        lvl = arr["lvl"]; low_pt = arr["low"]; high_pt = arr["high"]
        ix, iy = arr["insert"]
        for step in range(1, SLOPE_INTERP_N+1):
            t = step / (SLOPE_INTERP_N+1)
            px = high_pt[0] + t*(low_pt[0]-high_pt[0])
            py = high_pt[1] + t*(low_pt[1]-high_pt[1])
            pz = z_high - t*stated_rise - ref_value
            interp.append({"prefix": lvl, "value": pz, "raw": lvl,
                           "elev_label": elev_label, "x": px, "y": py, "confidence": "slope"})
        z_low_ft  = (z_low  - ref_value) * M_TO_FT
        z_high_ft = (z_high - ref_value) * M_TO_FT
        splits.append({"p1": XYZ(low_pt[0]*MM_TO_FT,  low_pt[1]*MM_TO_FT,  z_low_ft),
                       "p2": XYZ(high_pt[0]*MM_TO_FT, high_pt[1]*MM_TO_FT, z_high_ft),
                       "lvl": lvl})
    return interp, splits

class ErrorCatcher(IFailuresPreprocessor):
    def __init__(self): self.errors = []
    def PreprocessFailures(self, fa):
        from Autodesk.Revit.DB import FailureSeverity
        for msg in fa.GetFailureMessages():
            if msg.GetSeverity() == FailureSeverity.Error:
                self.errors.append(msg.GetDescriptionText())
                fa.ResolveFailure(msg); return FailureProcessingResult.ProceedWithRollBack
        return FailureProcessingResult.Continue

def find_ground_level(doc):
    lvls = sorted(FilteredElementCollector(doc).OfClass(Level).ToElements(), key=lambda l: l.Elevation)
    for lv in lvls:
        if "ground" in lv.Name.lower(): return lv
    return lvls[0] if lvls else None

def pick_level(doc):
    lvls = sorted(FilteredElementCollector(doc).OfClass(Level).ToElements(), key=lambda l: l.Elevation)
    names = ["{} ({:.0f} mm)".format(lv.Name, lv.Elevation*304.8) for lv in lvls]
    ch = show_list_dialog("Select Base Level", "Select Base Level", names, multiselect=False)
    if not ch: return None
    return lvls[names.index(ch)]

def calc_thickness_ft(pts):
    vals = [p["value"] for p in pts]
    return math.ceil((max(vals)-min(vals))*1000.0/500.0)*500.0/304.8

def set_cs_thickness(tt, thickness_ft):
    try:
        cs = tt.GetCompoundStructure()
        if cs is None: return
        layers = cs.GetLayers()
        for idx, layer in enumerate(layers):
            if layer.Function == MaterialFunctionAssignment.Structure:
                cs.SetLayerWidth(idx, thickness_ft); tt.SetCompoundStructure(cs); return
        if layers.Count > 0:
            cs.SetLayerWidth(0, thickness_ft); tt.SetCompoundStructure(cs)
    except: pass

def get_or_create_topo_type(doc, thickness_ft):
    all_types = list(FilteredElementCollector(doc).OfClass(ToposolidType).ToElements())
    if not all_types: return None, "No ToposolidType found."
    target = None
    for tt in all_types:
        np = tt.get_Parameter(BuiltInParameter.ALL_MODEL_TYPE_NAME)
        if np and np.AsString() == TOPO_TYPE_NAME: target = tt; break
    t = Transaction(doc, "TLA Grading - Setup Type")
    t.Start()
    try:
        if target is None: target = all_types[0].Duplicate(TOPO_TYPE_NAME)
        set_cs_thickness(target, thickness_ft)
        t.Commit(); return target, None
    except Exception as e:
        t.RollBack(); return None, str(e)

def create_toposolid(doc, pts, base_level, topo_type):
    rpts = [XYZ(p["x"]*MM_TO_FT, p["y"]*MM_TO_FT, p["value"]*M_TO_FT) for p in pts]
    xs=[p.X for p in rpts]; ys=[p.Y for p in rpts]; zs=[p.Z for p in rpts]
    pad=5.0
    c1=XYZ(min(xs)-pad,min(ys)-pad,min(zs)); c2=XYZ(max(xs)+pad,min(ys)-pad,min(zs))
    c3=XYZ(max(xs)+pad,max(ys)+pad,min(zs)); c4=XYZ(min(xs)-pad,max(ys)+pad,min(zs))
    loop=CurveLoop()
    loop.Append(Line.CreateBound(c1,c2)); loop.Append(Line.CreateBound(c2,c3))
    loop.Append(Line.CreateBound(c3,c4)); loop.Append(Line.CreateBound(c4,c1))
    cl=NetList[CurveLoop](); cl.Add(loop)
    np_list=NetList[XYZ]()
    for p in rpts: np_list.Add(p)
    catcher=ErrorCatcher()
    t=Transaction(doc, "TLA Grading - Create Toposolid")
    fho=t.GetFailureHandlingOptions(); fho.SetFailuresPreprocessor(catcher)
    t.SetFailureHandlingOptions(fho); t.Start()
    try:
        topo=Toposolid.Create(doc, cl, np_list, topo_type.Id, base_level.Id)
        t.Commit()
        if catcher.errors: return None, "\n".join(catcher.errors)
        return topo, None
    except Exception as e:
        t.RollBack(); return None, str(e)

def add_split_lines(doc, topo, splits):
    if not splits: return 0, []
    errors = []; added = 0
    t = Transaction(doc, "TLA Grading - Split Lines")
    t.Start()
    try:
        sse = topo.GetSlabShapeEditor(); sse.Enable()
        for sl in splits:
            try:
                v1 = sse.DrawPoint(sl["p1"]); v2 = sse.DrawPoint(sl["p2"])
                sse.DrawSplitLine(v1, v2); added += 1
            except Exception as e:
                errors.append("Split '{}': {}".format(sl["lvl"], str(e)))
        t.Commit()
    except Exception as e:
        t.RollBack(); errors.append("Split lines failed: {}".format(str(e)))
    return added, errors

try:
    dxf_path = forms.pick_file(file_ext="dxf", title="Select the DXF file")
    if not dxf_path: script.exit()

    all_points, skipped_tbc = read_dxf(dxf_path)
    if not all_points:
        show_alert("No level points found on layer TLA-LEVEL TEXT."); script.exit()

    counts = {}
    for pt in all_points: counts[pt["prefix"]] = counts.get(pt["prefix"],0)+1
    prefix_opts = ["{} ({} found)".format(k,v) for k,v in sorted(counts.items())]
    chosen = show_list_dialog("Select Level Types","Select Level Types",prefix_opts,multiselect=True)
    if not chosen: script.exit()
    selected = [c.split(" ")[0] for c in chosen]
    filtered = [pt for pt in all_points if pt["prefix"] in selected]

    if skipped_tbc:
        show_alert("Note: {} annotation(s) skipped:\n{}".format(
            len(skipped_tbc), "\n".join(skipped_tbc[:10])))

    use_slopes = show_yes_no("Apply slope arrows from DXF to shape the Toposolid surface?",
                             title="Slope Arrows")
    slope_preview = []; arrow_data_list = []; pre_warnings = []
    if use_slopes:
        arrows = read_slope_arrows(dxf_path)
        if not arrows:
            show_alert("No slope arrow blocks (TLA_SLOPE PERCENTAGE) found in DXF.")
        else:
            slope_preview, arrow_data_list, pre_warnings = build_slope_preview(arrows, filtered)

    confirmed = show_review_form(filtered + slope_preview)
    if confirmed is None: script.exit()
    if not confirmed: show_alert("No points selected."); script.exit()

    confirmed_level  = [p for p in confirmed if p.get("confidence") != "slope"]
    confirmed_slopes = [p for p in confirmed if p.get("confidence") == "slope"]
    absolute_points  = [dict(p) for p in confirmed_level]

    SKIP_LABEL   = "[ Skip - use raw DXF elevations (manual align later) ]"
    CUSTOM_LABEL = "[ Enter custom reference value... ]"
    ref_opts = [SKIP_LABEL, CUSTOM_LABEL] + [
        "{} {:.3f} m  (x={:.0f}, y={:.0f})".format(p["prefix"],p["value"],p["x"],p["y"])
        for p in confirmed_level]
    ref_chosen = show_list_dialog("Select 0 mm Reference Point",
                                  "Pick a reference point, enter custom, or skip",
                                  ref_opts, multiselect=False)
    if not ref_chosen: script.exit()

    if ref_chosen == SKIP_LABEL:
        ref_value = 0.0
    elif ref_chosen == CUSTOM_LABEL:
        cs = show_input_dialog(
            prompt="Enter the DXF elevation (in metres) that equals 0 mm in Revit.\nExample: 35.140",
            title="Custom Reference Value", default="")
        if cs is None: script.exit()
        try: ref_value = float(cs.strip())
        except ValueError: show_alert("Invalid number: {}".format(cs)); script.exit()
    else:
        ref_value = confirmed_level[ref_opts.index(ref_chosen)-2]["value"]

    for pt in confirmed_level: pt["value"] = pt["value"] - ref_value

    kept_lvls = set(p["raw"] for p in confirmed_slopes)
    filtered_ad = [ad if (ad and ad["arr"]["lvl"] in kept_lvls) else None
                   for ad in arrow_data_list]
    interp_pts, split_lines = build_interp_and_splits(filtered_ad, ref_value)
    all_confirmed = confirmed_level + interp_pts

    ground = find_ground_level(doc)
    if ground:
        ug = show_yes_no("Found level {} ({:.0f} mm).\nUse as Toposolid base level?".format(
            ground.Name, ground.Elevation*304.8), title="Base Level")
        base_level = ground if ug else pick_level(doc)
    else:
        base_level = pick_level(doc)
    if not base_level: script.exit()

    thickness_ft = calc_thickness_ft(all_confirmed)
    thickness_mm = int(round(thickness_ft*304.8))
    topo_type, type_error = get_or_create_topo_type(doc, thickness_ft)
    if type_error: show_alert("Failed to set up type:\n\n{}".format(type_error)); script.exit()

    topo, error = create_toposolid(doc, all_confirmed, base_level, topo_type)
    if error: show_alert("Failed:\n\n{}".format(error)); script.exit()

    split_added, split_errors = 0, []
    if split_lines and topo:
        split_added, split_errors = add_split_lines(doc, topo, split_lines)

    n_lv = len(confirmed_level); n_sl = len(interp_pts)
    summary = ("Toposolid created!\n\n"
               "{} level points\n{} slope interpolated points\n{} split lines added\n"
               "Base level: {}\nType: {}\nThickness: {} mm".format(
                   n_lv, n_sl, split_added, base_level.Name, TOPO_TYPE_NAME, thickness_mm))
    all_warns = pre_warnings + split_errors
    if all_warns: summary += "\n\nWarnings:\n" + "\n".join(all_warns)
    show_copyable_alert(summary, title="TLA Grading - Done")

except Exception:
    show_alert(traceback.format_exc(), title="ERROR")
