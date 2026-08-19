import re
import clr
clr.AddReference("RevitAPI")
from Autodesk.Revit.DB import FilteredElementCollector, ImportInstance

BLOCK_NAME = "TLA_SPOT LEVELS"
LEVEL_PATTERN = re.compile(r'^([A-Z]+)\+([0-9]+\.[0-9]+)$')

def get_linked_cad_instances(doc):
    collector = FilteredElementCollector(doc).OfClass(ImportInstance)
    results = []
    for inst in collector:
        try:
            if True:
                link_type = doc.GetElement(inst.GetTypeId())
                name = "Unknown"
                if link_type:
                    p = link_type.get_Parameter(Autodesk.Revit.DB.BuiltInParameter.SYMBOL_NAME_PARAM)
                    if p:
                        name = p.AsString()
                results.append({"name": name, "element": inst})
        except Exception:
            pass
    return results

def read_spot_levels(doc, import_instance):
    results = []
    errors = []
    options = Autodesk.Revit.DB.Options()
    options.ComputeReferences = False
    options.DetailLevel = Autodesk.Revit.DB.ViewDetailLevel.Fine
    geom_elem = import_instance.get_Geometry(options)
    if geom_elem is None:
        return results, ["Could not read geometry from linked CAD."]
    top_instance = None
    for obj in geom_elem:
        if isinstance(obj, Autodesk.Revit.DB.GeometryInstance):
            top_instance = obj
            break
    if top_instance is None:
        return results, ["No geometry instance found in linked CAD."]
    transform = top_instance.Transform
    for obj in top_instance.GetInstanceGeometry():
        if not isinstance(obj, Autodesk.Revit.DB.GeometryInstance):
            continue
        style_id = obj.GraphicsStyleId
        style = doc.GetElement(style_id)
        block_name = ""
        if style:
            block_name = style.GraphicsStyleCategory.Name if style.GraphicsStyleCategory else ""
        if BLOCK_NAME.upper() not in block_name.upper():
            continue
        insertion_pt = transform.OfPoint(obj.Transform.Origin)
        attr_text = None
        for inner in obj.GetInstanceGeometry():
            type_name = inner.GetType().Name
            if "Text" in type_name:
                if hasattr(inner, "TextString"):
                    attr_text = inner.TextString
                    break
        if attr_text is None:
            errors.append("Block at ({:.2f},{:.2f}): no text found.".format(insertion_pt.X, insertion_pt.Y))
            continue
        parsed = _parse_level_string(attr_text)
        if parsed is None:
            results.append({"prefix": "?", "value": None, "raw": attr_text, "x": insertion_pt.X, "y": insertion_pt.Y, "confidence": "parse_error"})
        else:
            results.append({"prefix": parsed["prefix"], "value": parsed["value"], "raw": attr_text, "x": insertion_pt.X, "y": insertion_pt.Y, "confidence": "ok"})
    return results, errors

def _parse_level_string(raw):
    if not raw:
        return None
    match = LEVEL_PATTERN.match(raw.strip())
    if match:
        return {"prefix": match.group(1), "value": float(match.group(2))}
    return None

def get_unique_prefixes(spot_levels):
    counts = {}
    for pt in spot_levels:
        p = pt.get("prefix", "?")
        counts[p] = counts.get(p, 0) + 1
    return [{"prefix": k, "count": v} for k, v in sorted(counts.items())]

def filter_by_prefixes(spot_levels, selected_prefixes):
    return [pt for pt in spot_levels if pt.get("prefix") in selected_prefixes]
