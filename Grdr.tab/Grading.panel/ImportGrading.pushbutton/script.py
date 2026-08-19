# TLA Grading Tool - Import Grading - Stage 2
import sys, os
from pyrevit import forms, script

# Add lib folder to path
ext_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
lib_dir = os.path.join(ext_dir, "lib")
if lib_dir not in sys.path:
    sys.path.insert(0, lib_dir)

from tla_grading import cad_reader

doc = __revit__.ActiveUIDocument.Document

# Step 1: Find linked CAD files
linked_cads = cad_reader.get_linked_cad_instances(doc)
if not linked_cads:
    forms.alert("No linked CAD files found.\n\nPlease link a CAD file first using Insert > Link CAD.", title="TLA Grading", ok=True)
    script.exit()

# Pick CAD if multiple
if len(linked_cads) == 1:
    selected_cad = linked_cads[0]
else:
    cad_names = [c["name"] for c in linked_cads]
    chosen_name = forms.SelectFromList.show(cad_names, title="Select Linked CAD", message="Which linked CAD contains spot levels?", multiselect=False)
    if not chosen_name:
        script.exit()
    selected_cad = next(c for c in linked_cads if c["name"] == chosen_name)

# Step 2: Read spot levels
spot_levels, errors = cad_reader.read_spot_levels(doc, selected_cad["element"])

if not spot_levels:
    msg = "No TLA_SPOT LEVELS blocks found in the linked CAD.\n\n"
    if errors:
        msg += "Errors:\n" + "\n".join(errors[:5])
    forms.alert(msg, title="TLA Grading", ok=True)
    script.exit()

# Step 3: Prefix filter
prefixes = cad_reader.get_unique_prefixes(spot_levels)
prefix_options = ["{} ({} found)".format(p["prefix"], p["count"]) for p in prefixes]
chosen = forms.SelectFromList.show(prefix_options, title="Select Level Types", message="Choose which prefixes to import:", multiselect=True)
if not chosen:
    script.exit()

selected_prefixes = [c.split(" ")[0] for c in chosen]
filtered = cad_reader.filter_by_prefixes(spot_levels, selected_prefixes)

# Step 4: Show summary
lines = ["{} | X:{:.3f} Y:{:.3f}".format(pt["raw"], pt["x"], pt["y"]) for pt in filtered[:20]]
if len(filtered) > 20:
    lines.append("... and {} more.".format(len(filtered) - 20))
if errors:
    lines.append("\nWarnings: " + str(len(errors)) + " blocks had issues.")

forms.alert("Found {} points.\n\n{}".format(len(filtered), "\n".join(lines)), title="TLA Grading - Stage 2 Result", ok=True)