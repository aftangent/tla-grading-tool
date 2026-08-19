import re, os

LEVEL_PATTERN = re.compile(r'^([A-Z]+)\+([0-9]+\.?[0-9]*)$')

def read_attribs_from_dxf(dxf_path, target_layer="TLA-LEVEL TEXT", tag_filter="LEVEL1"):
    if not os.path.isfile(dxf_path):
        return [], ["DXF file not found: {}".format(dxf_path)], set()
    results = []
    errors = []
    all_layers = set()
    try:
        with open(dxf_path, "r") as f:
            lines = f.readlines()
    except Exception as e:
        return [], ["Could not open DXF: {}".format(str(e))], set()
    lines = [l.strip() for l in lines]
    total = len(lines)
    i = 0
    while i < total - 1:
        code = lines[i]
        value = lines[i + 1] if i + 1 < total else ""
        if code == "8":
            all_layers.add(value)
        if code == "0" and value == "ATTRIB":
            entity = {"layer": None, "text": None, "x": None, "y": None, "tag": None}
            j = i + 2
            while j < total - 1:
                c = lines[j]
                v = lines[j + 1] if j + 1 < total else ""
                if c == "0":
                    break
                if c == "8":
                    entity["layer"] = v
                elif c == "1":
                    entity["text"] = v
                elif c == "10":
                    try:
                        entity["x"] = float(v)
                    except ValueError:
                        pass
                elif c == "20":
                    try:
                        entity["y"] = float(v)
                    except ValueError:
                        pass
                elif c == "2":
                    entity["tag"] = v
                j += 2
            layer = entity.get("layer", "")
            tag = entity.get("tag", "") or ""
            text = entity.get("text", "") or ""
            x = entity.get("x")
            y = entity.get("y")
            if layer == target_layer and "LEVEL1" in tag.upper():
                if x is not None and y is not None:
                    parsed = _parse_level_string(text)
                    if parsed:
                        results.append({"prefix": parsed["prefix"], "value": parsed["value"], "raw": text, "x": x, "y": y, "confidence": "ok"})
                    elif text:
                        results.append({"prefix": "?", "value": None, "raw": text, "x": x, "y": y, "confidence": "parse_error"})
        i += 2
    return results, errors, all_layers

def _parse_level_string(raw):
    if not raw:
        return None
    match = LEVEL_PATTERN.match(raw.strip())
    if match:
        return {"prefix": match.group(1), "value": float(match.group(2))}
    return None

def get_unique_prefixes(results):
    counts = {}
    for pt in results:
        p = pt.get("prefix", "?")
        counts[p] = counts.get(p, 0) + 1
    return [{"prefix": k, "count": v} for k, v in sorted(counts.items())]

def filter_by_prefixes(results, selected_prefixes):
    return [pt for pt in results if pt.get("prefix") in selected_prefixes]
