# -*- coding: utf-8 -*-
import traceback, math
LOGFILE = r"C:\Users\mohamed.asif\Desktop\place_annotation_error.txt"
def dump(msg):
    try:
        with open(LOGFILE, "a") as f: f.write(str(msg) + "\n")
    except: pass

dump("=== start ===")
try:
    import clr
    from pyrevit import forms, script
    from Autodesk.Revit.DB import (
        FilteredElementCollector, Transaction, XYZ,
        BuiltInParameter, BuiltInCategory, ViewPlan,
        SpotDimensionType, Options, UV,
        GeometryInstance, Solid,
    )
    from Autodesk.Revit.UI.Selection import ObjectType, ISelectionFilter

    doc   = __revit__.ActiveUIDocument.Document
    uidoc = __revit__.ActiveUIDocument

    if not isinstance(doc.ActiveView, ViewPlan):
        forms.alert("Please open a Plan View first.", title="Place Annotation")
        script.exit()

    M_TO_FT = 3.28084

    # ── Geometry helper — FAST, capped, bbox-first ───────────────────────────
    def get_placement_data(elem):
        """Return (origin_XYZ, face_ref_or_None).
        Strategy by category:
          Toposolid / Mesh-only → bbox top centroid, no ref (fast, no geometry traversal)
          Floor / Wall / solid family → geometry scan, capped at first valid upward face
        """
        cat_id = elem.Category.Id.IntegerValue if elem.Category else None
        topo_id = None
        try: topo_id = int(BuiltInCategory.OST_Toposolid)
        except: pass

        bb = elem.get_BoundingBox(None)

        # For Toposolids: skip geometry entirely — always crashes/slow
        if cat_id is not None and cat_id == topo_id:
            if bb:
                pt = XYZ((bb.Min.X+bb.Max.X)/2.0, (bb.Min.Y+bb.Max.Y)/2.0, bb.Max.Z)
                dump("    topo bbox: z={}".format(bb.Max.Z))
                return pt, None
            return None, None

        # For everything else: geometry scan, first upward face only
        try:
            opts = Options()
            opts.ComputeReferences = True
            opts.IncludeNonVisibleObjects = False
            geom = elem.get_Geometry(opts)
            if geom:
                for obj in geom:
                    try:
                        solids = []
                        sym_solids = []
                        if isinstance(obj, Solid) and obj.Faces.Size > 0:
                            solids = [obj]
                            sym_solids = [obj]
                        elif isinstance(obj, GeometryInstance):
                            ig = obj.GetInstanceGeometry()
                            sg = obj.GetSymbolGeometry()
                            if ig:
                                for o in ig:
                                    if isinstance(o, Solid) and o.Faces.Size > 0:
                                        solids.append(o)
                            if sg:
                                for o in sg:
                                    if isinstance(o, Solid) and o.Faces.Size > 0:
                                        sym_solids.append(o)

                        # Build paired face lists
                        inst_faces = []
                        sym_faces  = []
                        for s in solids:
                            for f in s.Faces: inst_faces.append(f)
                        for s in sym_solids:
                            for f in s.Faces: sym_faces.append(f)

                        n = min(len(inst_faces), len(sym_faces))
                        for i in range(n):
                            iface = inst_faces[i]
                            sface = sym_faces[i]
                            try:
                                if iface.FaceNormal.Z < 0.7: continue
                                fbb = iface.GetBoundingBox()
                                fpt = iface.Evaluate(UV(
                                    (fbb.Min.U+fbb.Max.U)/2.0,
                                    (fbb.Min.V+fbb.Max.V)/2.0
                                ))
                                if fpt is None: continue
                                dump("    face found z={}".format(fpt.Z))
                                return fpt, sface.Reference  # return on first hit
                            except: continue

                        # Instance-only fallback (no ref)
                        for iface in inst_faces:
                            try:
                                if iface.FaceNormal.Z < 0.7: continue
                                fbb = iface.GetBoundingBox()
                                fpt = iface.Evaluate(UV(
                                    (fbb.Min.U+fbb.Max.U)/2.0,
                                    (fbb.Min.V+fbb.Max.V)/2.0
                                ))
                                if fpt is None: continue
                                dump("    inst-only face z={}".format(fpt.Z))
                                return fpt, None
                            except: continue
                    except: continue
        except Exception as gex:
            dump("    geom error: " + str(gex))

        # Final fallback: bbox
        if bb:
            pt = XYZ((bb.Min.X+bb.Max.X)/2.0, (bb.Min.Y+bb.Max.Y)/2.0, bb.Max.Z)
            dump("    bbox fallback z={}".format(bb.Max.Z))
            return pt, None
        return None, None

    # ── STEP 1: Select prefixes ───────────────────────────────────────────────
    ALL_PREFIXES = ["FFL","FSL","TOW","TOS","TOR","TOK","FRL","WL","BL","TOM","SSL","RL","BOK"]
    chosen_pfx = forms.SelectFromList.show(
        ALL_PREFIXES,
        title="Place Annotation - Select Prefixes",
        multiselect=True,
        button_name="Next"
    )
    dump("prefixes: " + str(chosen_pfx))
    if not chosen_pfx: script.exit()

    # ── STEP 2: Pick ARC reference floor ─────────────────────────────────────
    forms.alert(
        "Select the ARC reference floor in the model, then press Finish.",
        title="Step 2 of 4 - Select ARC Reference Floor"
    )

    class FloorFilter(ISelectionFilter):
        def AllowElement(self, e):
            try:
                cid = e.Category.Id.IntegerValue if e.Category else None
                return cid in [int(BuiltInCategory.OST_Floors), int(BuiltInCategory.OST_Toposolid)]
            except: return False
        def AllowReference(self, r, pt): return False

    try:
        arc_refs  = uidoc.Selection.PickObjects(ObjectType.Element, FloorFilter(), "Select ARC reference floor - Finish when done")
        arc_elems = [doc.GetElement(r.ElementId) for r in arc_refs]
    except: arc_elems = []

    if not arc_elems:
        forms.alert("No ARC reference floor selected.", title="Place Annotation"); script.exit()

    if len(arc_elems) == 1:
        arc_elem = arc_elems[0]
    else:
        def elbl(e):
            try:
                fp = e.get_Parameter(BuiltInParameter.ELEM_FAMILY_AND_TYPE_PARAM)
                return (fp.AsString() if fp else "(unknown)") + " [{}]".format(e.Id.IntegerValue)
            except: return str(e.Id.IntegerValue)
        lmap = {elbl(e): e for e in arc_elems}
        c = forms.SelectFromList.show(sorted(lmap.keys()), title="Select ARC Reference Floor", multiselect=False, button_name="Use")
        if not c: script.exit()
        arc_elem = lmap[c]

    dump("arc elem: " + str(arc_elem.Id.IntegerValue))
    arc_pt, _ = get_placement_data(arc_elem)
    if arc_pt:
        arc_ffl_ft = arc_pt.Z
    else:
        bb = arc_elem.get_BoundingBox(None)
        arc_ffl_ft = bb.Max.Z if bb else 0.0
    arc_ffl_m = arc_ffl_ft / M_TO_FT
    dump("arc_ffl_m={}".format(arc_ffl_m))

    # ── STEP 3: Pick target elements ──────────────────────────────────────────
    forms.alert("Select all elements to annotate, then press Finish.", title="Step 3 of 4 - Select Target Elements")

    try:
        tgt_refs   = uidoc.Selection.PickObjects(ObjectType.Element, "Select elements to annotate - Finish when done")
        target_sel = [doc.GetElement(r.ElementId) for r in tgt_refs]
        target_sel = [e for e in target_sel if e.Id.IntegerValue != arc_elem.Id.IntegerValue]
    except: target_sel = []

    dump("targets: " + str(len(target_sel)))
    if not target_sel:
        forms.alert("No target elements selected.", title="Place Annotation"); script.exit()

    # ── STEP 4: Auto-classify, then single mapping dialog ────────────────────
    CAT_MAP = {
        int(BuiltInCategory.OST_Floors):    "FFL",
        int(BuiltInCategory.OST_Toposolid): "FFL",
        int(BuiltInCategory.OST_Walls):     "TOW",
        int(BuiltInCategory.OST_Planting):  "FSL",
        int(BuiltInCategory.OST_Railings):  "TOR",
        int(BuiltInCategory.OST_Ramps):     "FFL",
        int(BuiltInCategory.OST_Stairs):    "FFL",
        int(BuiltInCategory.OST_Furniture): "TOS",
    }
    TOW_THRESHOLD_FT = 0.300 * M_TO_FT

    def fam_type_label(e):
        try:
            fp = e.get_Parameter(BuiltInParameter.ELEM_FAMILY_AND_TYPE_PARAM)
            v  = fp.AsString() if fp else None
            if v: return v
        except: pass
        try: return (e.Category.Name if e.Category else "Unknown") + " : (unknown)"
        except: return "(unknown)"

    # Group by family+type
    family_groups = {}
    for elem in target_sel:
        lbl = fam_type_label(elem)
        family_groups.setdefault(lbl, []).append(elem)

    dump("family groups: " + str(list(family_groups.keys())))

    # Auto-suggest prefix for each family group
    family_suggestion = {}  # lbl -> suggested prefix or None
    for lbl, elems in family_groups.items():
        sample = elems[0]
        cat_id = sample.Category.Id.IntegerValue if sample.Category else None
        pfx    = CAT_MAP.get(cat_id)
        if pfx == "FFL":
            try:
                bb = sample.get_BoundingBox(None)
                if bb and bb.Max.Z > (arc_ffl_ft + TOW_THRESHOLD_FT):
                    pfx = "TOW"
            except: pass
        # Only suggest if it's in the chosen prefixes
        family_suggestion[lbl] = pfx if (pfx and pfx in list(chosen_pfx)) else None

    # ── Mapping UI: one SelectFromList per unresolved family ─────────────────
    # Show a summary of auto-resolved first, then ask for unresolved ones
    auto_resolved   = {lbl: pfx for lbl, pfx in family_suggestion.items() if pfx is not None}
    needs_mapping   = [lbl for lbl, pfx in family_suggestion.items() if pfx is None]

    dump("auto-resolved: " + str(auto_resolved))
    dump("needs mapping: " + str(needs_mapping))

    # Build the final mapping: start with auto
    family_map = dict(auto_resolved)  # lbl -> prefix

    if needs_mapping:
        # Show table summary as a formatted alert
        # Each row: "Family Name  |  auto-prefix or UNASSIGNED"
        table_lines = []
        col_w = max(len(l) for l in needs_mapping) + 2
        for lbl in sorted(needs_mapping):
            table_lines.append(u"{:<{w}}  [UNASSIGNED]".format(lbl, w=col_w))

        forms.alert(
            u"Step 4 of 4 \u2014 Assign Prefixes\n\n"
            u"These families need a prefix. You will assign each one:\n\n"
            + u"\n".join(table_lines),
            title="Map Families to Prefixes"
        )

        for lbl in sorted(needs_mapping):
            count = len(family_groups[lbl])
            # Format list items as "PREFIX  (description)" for clarity
            prefix_opts = [u"{}  \u2014  {} element(s) will get this".format(p, count) if False else p
                           for p in list(chosen_pfx)]
            chosen = forms.SelectFromList.show(
                list(chosen_pfx),
                title=u"Assign Prefix \u2014 {} element(s)".format(count),
                prompt=u"Family:  {}".format(lbl),
                multiselect=False,
                button_name="Assign"
            )
            dump("  {} -> {}".format(lbl, chosen))
            if chosen:
                family_map[lbl] = chosen
            # If skipped, family simply gets no annotation

    # Build classified dict
    classified = {}
    for lbl, pfx in family_map.items():
        for e in family_groups[lbl]:
            classified[e.Id.IntegerValue] = (e, pfx)

    dump("classified: " + str(len(classified)))
    if not classified:
        forms.alert("No elements classified.", title="Place Annotation"); script.exit()

    # ── STEP 5: Direction & offset ────────────────────────────────────────────
    CLOCK_DEG = {
        "12 o'clock (North)":  90.0,
        "1:30":                45.0,
        "3 o'clock (East)":     0.0,
        "4:30":               -45.0,
        "6 o'clock (South)": -90.0,
        "7:30":              -135.0,
        "9 o'clock (West)":  180.0,
        "10:30":             135.0,
        "Custom angle...":    None,
    }
    chosen_dir = forms.SelectFromList.show(list(CLOCK_DEG.keys()), title="Annotation Direction", multiselect=False, button_name="Next")
    if not chosen_dir: script.exit()

    if chosen_dir == "Custom angle...":
        ca = forms.ask_for_string(prompt="Angle in degrees (0=East, 90=North):", title="Custom Angle", default="0")
        if ca is None: script.exit()
        try: deg = float(ca)
        except: deg = 0.0
    else:
        deg = CLOCK_DEG[chosen_dir]

    off_val = forms.ask_for_string(prompt="Offset distance in metres:", title="Offset Distance", default="2.0")
    if off_val is None: script.exit()
    try: offset_m = float(off_val.strip())
    except: offset_m = 2.0

    rad  = math.radians(deg)
    dx_ft = math.cos(rad) * offset_m * M_TO_FT
    dy_ft = math.sin(rad) * offset_m * M_TO_FT
    dump("direction={} offset={}m dx={} dy={}".format(deg, offset_m, dx_ft, dy_ft))

    # ── STEP 6: Find SpotElevation types ─────────────────────────────────────
    all_spot_types = list(FilteredElementCollector(doc).OfClass(SpotDimensionType))
    elev_types = []
    for st in all_spot_types:
        try:
            n    = st.get_Parameter(BuiltInParameter.ALL_MODEL_TYPE_NAME)
            name = n.AsString() if n else ""
            try: sstr = str(st.StyleType)
            except: sstr = ""
            dump("  spot id={} name='{}' style='{}'".format(st.Id, name, sstr))
            if "Elevation" in sstr or "Elev" in name or name.startswith("LA_SP_"):
                elev_types.append((name, st))
        except: pass
    if not elev_types:
        for st in all_spot_types:
            n = st.get_Parameter(BuiltInParameter.ALL_MODEL_TYPE_NAME)
            elev_types.append((n.AsString() if n else "", st))
    dump("elev types: " + str([n for n,_ in elev_types]))

    def find_spot_type(prefix):
        tname = "LA_SP_2.5mm-{}".format(prefix)
        for name, st in elev_types:
            if name == tname: return st
        return elev_types[0][1] if elev_types else None

    # ── STEP 7: Place SpotElevations ─────────────────────────────────────────
    dump("step 7: placing {} spots".format(len(classified)))
    placed = 0; errors = []
    view   = doc.ActiveView

    t = Transaction(doc, "TLA - Place Spot Annotations")
    t.Start()
    try:
        for eid, (elem, prefix) in classified.items():
            dump("  {} elem={}".format(prefix, eid))
            try:
                stype = find_spot_type(prefix)
                if stype is None:
                    errors.append("{} id={}: no type".format(prefix, eid)); continue
                try:
                    if not stype.IsActive: stype.Activate()
                except: pass

                origin, face_ref = get_placement_data(elem)
                if origin is None:
                    errors.append("{} id={}: no origin".format(prefix, eid)); continue

                bend   = XYZ(origin.X + dx_ft*0.5, origin.Y + dy_ft*0.5, origin.Z)
                end_pt = XYZ(origin.X + dx_ft,     origin.Y + dy_ft,     origin.Z)

                ok = False
                if face_ref is not None:
                    try:
                        doc.Create.NewSpotElevation(view, face_ref, origin, bend, end_pt, end_pt, True)
                        dump("    OK with ref")
                        ok = True
                    except Exception as e1:
                        dump("    ref failed: " + str(e1))

                if not ok:
                    # Bbox fallback origin — avoids "not on ref" error
                    bb = elem.get_BoundingBox(None)
                    if bb:
                        bo = XYZ((bb.Min.X+bb.Max.X)/2.0, (bb.Min.Y+bb.Max.Y)/2.0, bb.Max.Z)
                        bb2 = XYZ(bo.X+dx_ft*0.5, bo.Y+dy_ft*0.5, bo.Z)
                        be  = XYZ(bo.X+dx_ft,     bo.Y+dy_ft,     bo.Z)
                        try:
                            doc.Create.NewSpotElevation(view, None, bo, bb2, be, be, False)
                            dump("    OK no ref")
                            ok = True
                        except Exception as e2:
                            dump("    no-ref failed: " + str(e2))
                            errors.append("{} id={}: {}".format(prefix, eid, str(e2)))

                if ok: placed += 1

            except Exception as eex:
                dump("  elem error: " + str(eex))
                errors.append("id={}: {}".format(eid, str(eex)))

        t.Commit()
        dump("committed placed={}".format(placed))
    except Exception:
        t.RollBack()
        dump("rolled back:\n" + traceback.format_exc())
        forms.alert("Transaction failed:\n" + traceback.format_exc(), title="ERROR")
        script.exit()

    summary = "Placed {} spot annotation(s).\nARC FFL: {:.3f}m".format(placed, arc_ffl_m)
    if errors:
        summary += "\n\nErrors ({}):\n".format(len(errors)) + "\n".join(errors[:10])
    forms.alert(summary, title="Place Annotation - Done")

except Exception:
    dump("TOP EXCEPTION:\n" + traceback.format_exc())
    try:
        from pyrevit import forms
        forms.alert(traceback.format_exc(), title="ERROR")
    except: pass
