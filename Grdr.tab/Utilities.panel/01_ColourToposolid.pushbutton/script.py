# -*- coding: utf-8 -*-
import traceback, math
import clr
clr.AddReference("System")
clr.AddReference("PresentationFramework")
clr.AddReference("PresentationCore")
clr.AddReference("WindowsBase")
from System.Collections.Generic import List
from System import Double
from System.Windows import Window, WindowStartupLocation, Thickness, HorizontalAlignment
from System.Windows.Controls import (
    Button, StackPanel, Orientation, TextBlock, TextBox, Label
)
from System.Windows.Media import SolidColorBrush, Color as WpfColor
import System

from pyrevit import forms as _forms
from Autodesk.Revit.DB import (
    Transaction, FilteredElementCollector,
    Floor, Toposolid, View3D, ViewDrafting,
    ViewFamilyType, ViewFamily,
    Options, Solid, Color,
    ViewDetailLevel, UV, XYZ,
    DisplayStyle, OverrideGraphicSettings,
    ElementId, ImportInstance,
    BuiltInParameter, FilledRegionType,
    FilledRegion, CurveLoop, Line,
    FillPatternElement, BasePoint
)
from Autodesk.Revit.DB.Analysis import (
    SpatialFieldManager,
    FieldDomainPointsByUV,
    FieldValues, ValueAtPoint,
    AnalysisDisplayStyle,
    AnalysisDisplayColoredSurfaceSettings,
    AnalysisDisplayColorSettings,
    AnalysisDisplayLegendSettings,
    AnalysisDisplayColorEntry,
    AnalysisResultSchema
)
from Autodesk.Revit.UI.Selection import ObjectType, ISelectionFilter

doc   = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument

VIEW_NAME   = "Colour Toposolids - edtrafc"
DRAFT_NAME  = "Colour Toposolids 2D- edtrafc"
SCHEME_NAME = "TLA Elevation"
M_TO_FT     = 3.28084
MM_TO_FT    = 1.0 / 304.8
GRID_FT     = 400.0 * MM_TO_FT   # 400mm sampling grid

C_YELLOW      = WpfColor.FromRgb(245, 168,   0)
C_YELLOW_DARK = WpfColor.FromRgb(220, 148,   0)
C_BLACK       = WpfColor.FromRgb(  0,   0,   0)
C_WHITE       = WpfColor.FromRgb(255, 255, 255)
C_ROW_ALT     = WpfColor.FromRgb(255, 237, 180)


# ---------------------------------------------------------------------------
# Selection filter
# ---------------------------------------------------------------------------
class FloorOrTopoFilter(ISelectionFilter):
    def AllowElement(self, e):
        return isinstance(e, Floor) or isinstance(e, Toposolid)
    def AllowReference(self, r, p):
        return False


# ---------------------------------------------------------------------------
# Project Base Point elevation (metres)
# ---------------------------------------------------------------------------
def get_project_base_z_m():
    """Return Project Base Point elevation in metres (Revit internal feet → m)."""
    try:
        for bp in FilteredElementCollector(doc).OfClass(BasePoint).ToElements():
            # IsSurveyPoint = False → this is the Project Base Point
            try:
                if not bp.IsSurveyPoint:
                    return bp.Position.Z / M_TO_FT
            except:
                try:
                    p = bp.get_Parameter(BuiltInParameter.BASEPOINT_ELEVATION_PARAM)
                    if p is not None:
                        return p.AsDouble() / M_TO_FT
                except:
                    pass
    except:
        pass
    return 0.0


# ---------------------------------------------------------------------------
# UI — interval picker
# ---------------------------------------------------------------------------
def ask_interval_mm():
    """
    TLA-styled dialog — user enters elevation interval per colour band in mm.
    Returns float mm, or None if cancelled.
    """
    result = [None]
    win = Window()
    win.Title  = "TLA Grading - Colour Interval"
    win.Width  = 380
    win.WindowStartupLocation = WindowStartupLocation.CenterScreen
    win.Background = SolidColorBrush(C_YELLOW)
    win.SizeToContent = System.Windows.SizeToContent.Height
    win.ResizeMode = System.Windows.ResizeMode.NoResize

    root = StackPanel()
    root.Orientation = Orientation.Vertical
    root.Margin = Thickness(14, 14, 14, 14)
    win.Content = root

    hdr = TextBlock()
    hdr.Text = "ELEVATION INTERVAL PER COLOUR BAND"
    hdr.FontSize = 13
    hdr.FontWeight = System.Windows.FontWeights.Bold
    hdr.Foreground = SolidColorBrush(C_BLACK)
    hdr.Margin = Thickness(0, 0, 0, 8)
    root.Children.Add(hdr)

    sub = TextBlock()
    sub.Text = ("Enter the elevation interval (mm) that each colour band represents.\n"
                "Example: 100 mm means each shade covers 100 mm of elevation.\n"
                "Smaller interval = more bands = finer detail.")
    sub.FontSize = 11
    sub.Foreground = SolidColorBrush(C_BLACK)
    sub.Margin = Thickness(0, 0, 0, 12)
    sub.TextWrapping = System.Windows.TextWrapping.Wrap
    root.Children.Add(sub)

    lbl = TextBlock()
    lbl.Text = "Interval (mm):"
    lbl.FontSize = 12
    lbl.FontWeight = System.Windows.FontWeights.Bold
    lbl.Foreground = SolidColorBrush(C_BLACK)
    lbl.Margin = Thickness(0, 0, 0, 4)
    root.Children.Add(lbl)

    tb = TextBox()
    tb.Text = "100"
    tb.FontSize = 13
    tb.Height = 32
    tb.Margin = Thickness(0, 0, 0, 6)
    tb.Padding = Thickness(6, 4, 6, 4)
    root.Children.Add(tb)

    err = TextBlock()
    err.Text = ""
    err.FontSize = 11
    err.Foreground = SolidColorBrush(WpfColor.FromRgb(180, 0, 0))
    err.Margin = Thickness(0, 0, 0, 8)
    root.Children.Add(err)

    footer = StackPanel()
    footer.Orientation = Orientation.Horizontal
    footer.HorizontalAlignment = HorizontalAlignment.Right

    cancel = Button()
    cancel.Content = "Cancel"; cancel.Width = 80; cancel.Height = 30
    cancel.Margin = Thickness(0, 0, 8, 0)
    cancel.Background = SolidColorBrush(C_YELLOW_DARK)
    cancel.Foreground = SolidColorBrush(C_BLACK)
    cancel.FontWeight = System.Windows.FontWeights.Bold
    def on_cancel(s, e): result[0] = None; win.Close()
    cancel.Click += on_cancel
    footer.Children.Add(cancel)

    ok = Button()
    ok.Content = "OK"; ok.Width = 90; ok.Height = 30
    ok.Background = SolidColorBrush(C_BLACK)
    ok.Foreground = SolidColorBrush(C_WHITE)
    ok.FontWeight = System.Windows.FontWeights.Bold
    def on_ok(s, e):
        try:
            v = float(tb.Text.strip())
        except:
            err.Text = "Enter a valid number (e.g. 100)."
            return
        # Floor to nearest 50 mm, clamp to 50-1000 mm
        v_floor = int(v // 50) * 50          # floor to nearest 50
        v_norm  = max(50, min(1000, v_floor)) # clamp 50-1000
        if v_norm != int(round(v)):
            err.Text = "Normalised to {} mm (floor to nearest 50, range 50-1000).".format(v_norm)
        result[0] = float(v_norm)
        win.Close()
    ok.Click += on_ok
    footer.Children.Add(ok)
    root.Children.Add(footer)

    win.ShowDialog()
    return result[0]


# ---------------------------------------------------------------------------
# Output mode selector
# ---------------------------------------------------------------------------
def ask_output_mode():
    """
    Ask user what to generate: 3D only / 2D only / Both.
    Returns '3d', '2d', or 'both', or None if cancelled.
    """
    result = [None]
    win = Window()
    win.Title  = "TLA Grading - Output Mode"
    win.Width  = 360
    win.WindowStartupLocation = WindowStartupLocation.CenterScreen
    win.Background = SolidColorBrush(C_YELLOW)
    win.SizeToContent = System.Windows.SizeToContent.Height
    win.ResizeMode = System.Windows.ResizeMode.NoResize

    root = StackPanel()
    root.Orientation = Orientation.Vertical
    root.Margin = Thickness(14, 14, 14, 14)
    win.Content = root

    hdr = TextBlock()
    hdr.Text = "SELECT OUTPUT"
    hdr.FontSize = 13
    hdr.FontWeight = System.Windows.FontWeights.Bold
    hdr.Foreground = SolidColorBrush(C_BLACK)
    hdr.Margin = Thickness(0, 0, 0, 10)
    root.Children.Add(hdr)

    options = [
        ("3D only  — Colour the Toposolid in the 3D view", "3d"),
        ("2D only  — Create flat colour mesh in Drafting View", "2d"),
        ("Both     — 3D colouring + 2D Drafting View mesh", "both"),
    ]
    selected_btn = [None]
    for label, value in options:
        b = Button()
        b.Content = label; b.Height = 34
        b.Margin = Thickness(0, 3, 0, 3)
        b.Background = SolidColorBrush(C_ROW_ALT)
        b.Foreground = SolidColorBrush(C_BLACK)
        b.FontWeight = System.Windows.FontWeights.Normal
        b.HorizontalContentAlignment = HorizontalAlignment.Left
        b.Padding = Thickness(10, 0, 0, 0)
        def on_click(s, e, v=value, btn=b):
            result[0] = v
            if selected_btn[0]:
                selected_btn[0].Background = SolidColorBrush(C_ROW_ALT)
                selected_btn[0].FontWeight = System.Windows.FontWeights.Normal
            btn.Background = SolidColorBrush(C_YELLOW_DARK)
            btn.FontWeight = System.Windows.FontWeights.Bold
            selected_btn[0] = btn
        b.Click += on_click
        root.Children.Add(b)

    footer = StackPanel()
    footer.Orientation = Orientation.Horizontal
    footer.HorizontalAlignment = HorizontalAlignment.Right
    footer.Margin = Thickness(0, 12, 0, 0)

    cancel = Button()
    cancel.Content = "Cancel"; cancel.Width = 80; cancel.Height = 30
    cancel.Margin = Thickness(0, 0, 8, 0)
    cancel.Background = SolidColorBrush(C_YELLOW_DARK)
    cancel.Foreground = SolidColorBrush(C_BLACK)
    cancel.FontWeight = System.Windows.FontWeights.Bold
    def on_cancel(s, e): result[0] = None; win.Close()
    cancel.Click += on_cancel
    footer.Children.Add(cancel)

    ok = Button()
    ok.Content = "Create"; ok.Width = 90; ok.Height = 30
    ok.Background = SolidColorBrush(C_BLACK)
    ok.Foreground = SolidColorBrush(C_WHITE)
    ok.FontWeight = System.Windows.FontWeights.Bold
    def on_ok(s, e):
        if result[0] is None:
            return   # nothing selected yet
        win.Close()
    ok.Click += on_ok
    footer.Children.Add(ok)
    root.Children.Add(footer)

    win.ShowDialog()
    return result[0]


# ---------------------------------------------------------------------------
# Colour ramp: Yellow (highest) → Orange shades → Red (lowest)
# index 0 = Yellow = highest elevation band
# index N-1 = Red   = lowest elevation band
# ---------------------------------------------------------------------------
def build_color_ramp(n):
    """
    Warm spectrum: Yellow(255,220,0) → Orange(255,120,0) → Red(220,0,0)
    Compressed across n steps.
    index 0 = highest elevation = Yellow
    index n-1 = lowest elevation = Red
    """
    colors = []
    for i in range(n):
        t = i / float(max(n - 1, 1))   # 0.0=Yellow, 1.0=Red
        if t <= 0.5:
            # Yellow(255,220,0) → Orange(255,120,0)
            s = t / 0.5
            r = 255
            g = int(220 - s * 100)   # 220 → 120
            b = 0
        else:
            # Orange(255,120,0) → Red(220,0,0)
            s = (t - 0.5) / 0.5
            r = int(255 - s * 35)    # 255 → 220
            g = int(120 - s * 120)   # 120 → 0
            b = 0
        colors.append(Color(r, g, b))
    return colors


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------
def get_or_create_3d_view():
    for v in FilteredElementCollector(doc).OfClass(View3D).ToElements():
        if not v.IsTemplate and v.Name == VIEW_NAME:
            return v
    vft = None
    for vt in FilteredElementCollector(doc).OfClass(ViewFamilyType).ToElements():
        if vt.ViewFamily == ViewFamily.ThreeDimensional:
            vft = vt; break
    if vft is None: return None
    v = View3D.CreateIsometric(doc, vft.Id)
    v.Name = VIEW_NAME
    return v


def get_or_create_drafting_view():
    for v in FilteredElementCollector(doc).OfClass(ViewDrafting).ToElements():
        if v.Name == DRAFT_NAME:
            return v
    vft = None
    for vt in FilteredElementCollector(doc).OfClass(ViewFamilyType).ToElements():
        if vt.ViewFamily == ViewFamily.Drafting:
            vft = vt; break
    if vft is None: return None
    v = ViewDrafting.Create(doc, vft.Id)
    v.Name  = DRAFT_NAME
    v.Scale = 200
    return v


# ---------------------------------------------------------------------------
# Analysis Display Style — reuse TLA Elevation if it exists
# Only create if missing. Colours: Yellow=Max, Red=Min
# ---------------------------------------------------------------------------
def ensure_display_style(n_bands, ramp):
    for s in FilteredElementCollector(doc).OfClass(AnalysisDisplayStyle).ToElements():
        if s.Name == SCHEME_NAME:
            return s   # reuse — user manually sets Ranges in UI

    surf = AnalysisDisplayColoredSurfaceSettings()
    surf.ShowGridLines    = False
    surf.ShowContourLines = True

    color_sett = AnalysisDisplayColorSettings()
    color_sett.MaxColor = ramp[0]     # Yellow = highest
    color_sett.MinColor = ramp[-1]    # Red    = lowest
    entries = List[AnalysisDisplayColorEntry]()
    for c in ramp:
        entries.Add(AnalysisDisplayColorEntry(c))
    try: color_sett.SetIntermediateColors(entries)
    except: pass

    legend = AnalysisDisplayLegendSettings()
    legend.ShowLegend    = True
    legend.NumberOfSteps = min(n_bands, 128)

    return AnalysisDisplayStyle.CreateAnalysisDisplayStyle(
        doc, SCHEME_NAME, surf, color_sett, legend)


# ---------------------------------------------------------------------------
# Apply style to view
# ---------------------------------------------------------------------------
def set_view_analysis_style(view, style_id):
    try: view.SetAnalysisDisplayStyle(style_id); return
    except: pass
    try:
        p = view.get_Parameter(BuiltInParameter.VIEW_ANALYSIS_DISPLAY_STYLE)
        if p and not p.IsReadOnly: p.Set(style_id)
    except: pass


# ---------------------------------------------------------------------------
# View settings
# ---------------------------------------------------------------------------
def apply_view_settings(view, style_id, selected_ids):
    try: view.Scale = 500
    except: pass
    try: view.DetailLevel = ViewDetailLevel.Fine
    except: pass
    try:
        from Autodesk.Revit.DB import ViewDiscipline
        view.Discipline = ViewDiscipline.Coordination
    except: pass
    try: view.DisplayStyle = DisplayStyle.Shading
    except: pass
    try:
        for cat in doc.Settings.Categories:
            try:
                if cat.CategoryType.ToString() == "Model":
                    view.SetCategoryOverrides(cat.Id, OverrideGraphicSettings())
                    view.SetVisibility(cat.Id, True)
                    for sub in cat.SubCategories:
                        try: view.SetVisibility(sub.Id, True)
                        except: pass
            except: pass
    except: pass
    try:
        for imp in FilteredElementCollector(doc).OfClass(ImportInstance).ToElements():
            try: view.SetVisibility(imp.Id, False)
            except: pass
    except: pass
    try:
        id_list = List[ElementId]()
        for eid in selected_ids: id_list.Add(eid)
        view.IsolateElementsTemporary(id_list)
    except: pass
    if style_id is not None:
        set_view_analysis_style(view, style_id)


# ---------------------------------------------------------------------------
# SFM
# ---------------------------------------------------------------------------
def get_sfm(view):
    sfm = SpatialFieldManager.GetSpatialFieldManager(view)
    if sfm: return sfm
    try:
        sfm = SpatialFieldManager.CreateSpatialFieldManager(view, 1)
        if sfm: return sfm
    except: pass
    try: sfm = SpatialFieldManager(view, 1)
    except: sfm = None
    return sfm


# ---------------------------------------------------------------------------
# AVF scheme — values stored as normalized 0.0-1.0
# 0.0 = lowest elevation band = Red (MinColor)
# 1.0 = highest elevation band = Yellow (MaxColor)
# ---------------------------------------------------------------------------
def get_or_create_scheme(sfm):
    schema = AnalysisResultSchema(SCHEME_NAME, "Elevation (m)")
    for rid in sfm.GetRegisteredResults():
        try:
            if sfm.GetResultSchema(rid).Name == SCHEME_NAME:
                return rid
        except: pass
    return sfm.RegisterResult(schema)


def make_value(v):
    vals = List[Double]()
    vals.Add(Double(float(v)))
    return ValueAtPoint(vals)


# ---------------------------------------------------------------------------
# Geometry — Fine detail for accurate terrain Z
# ---------------------------------------------------------------------------
def collect_elem_data(elems):
    opts = Options()
    opts.ComputeReferences        = True
    opts.IncludeNonVisibleObjects = False
    opts.DetailLevel              = ViewDetailLevel.Fine

    elem_data = {}
    for elem in elems:
        faces = []
        bb_elem = elem.get_BoundingBox(None)
        bb_min  = bb_elem.Min if bb_elem else XYZ(0, 0, 0)
        bb_max  = bb_elem.Max if bb_elem else XYZ(1, 1, 1)

        # --- Collect faces for AVF colouring (unchanged) ---
        try:
            for obj in elem.get_Geometry(opts):
                if not isinstance(obj, Solid): continue
                for face in obj.Faces:
                    try:
                        if face.FaceNormal.Z <= 0.1 or face.Reference is None:
                            continue
                        faces.append(face)
                    except: pass
        except: pass

        # --- Z range from SlabShapeVertices (finished top surface only) ---
        # Do NOT use face-sampled Z or bounding box — those include
        # base/side geometry and produce incorrect ranges (e.g. -18m to +18m).
        z_min = None
        z_max = None
        slab_vertex_count = 0
        slab_error = None
        try:
            editor = elem.GetSlabShapeEditor()
            if editor is None:
                slab_error = "GetSlabShapeEditor() returned None"
            else:
                verts = editor.SlabShapeVertices
                z_lo =  1e18
                z_hi = -1e18
                for v in verts:
                    try:
                        z_m = v.Position.Z / M_TO_FT
                        z_lo = min(z_lo, z_m)
                        z_hi = max(z_hi, z_m)
                        slab_vertex_count += 1
                    except: pass
                if slab_vertex_count >= 2 and z_lo < z_hi:
                    z_min = z_lo
                    z_max = z_hi
                elif slab_vertex_count >= 1:
                    # All vertices at same elevation — flat surface
                    z_min = z_lo
                    z_max = z_lo + 0.001
                else:
                    slab_error = "SlabShapeVertices returned 0 usable vertices"
        except Exception as ex:
            slab_error = str(ex)

        if z_min is None:
            # No valid surface vertices — skip this element, log clearly
            elem_data[elem.Id.IntegerValue] = {
                "faces": [], "z_min": None, "z_max": None,
                "bb_min": bb_min, "bb_max": bb_max,
                "terrain_pts": [],
                "skip": True,
                "skip_reason": "Unable to obtain finished surface vertices: " + str(slab_error),
                "vertex_count": slab_vertex_count,
            }
            continue

        # Collect terrain points for 2D mesh Z lookup
        terrain_pts = []
        try:
            pts = elem.GetPoints()
            for p in pts:
                terrain_pts.append((p.X, p.Y, p.Z / M_TO_FT))
        except:
            pass

        elem_data[elem.Id.IntegerValue] = {
            "faces": faces, "z_min": z_min, "z_max": z_max,
            "bb_min": bb_min, "bb_max": bb_max,
            "terrain_pts": terrain_pts,
            "skip": False,
            "vertex_count": slab_vertex_count,
        }
    return elem_data


# ---------------------------------------------------------------------------
# Band calculation
#
# Uses SHARED datum range across all elements.
# datum_z   = Project Base Point elevation (metres)
# interval  = user-entered mm converted to metres
# n_bands   = ceil((global_z_max - global_z_min) / interval_m)
# band_idx  = floor((z_m - global_z_min) / interval_m), clamped 0..n-1
# AVF value = band_idx / (n_bands-1)  →  0.0=lowest/Red, 1.0=highest/Yellow
# ---------------------------------------------------------------------------
def z_to_band(z_m, global_z_min, interval_m, n_bands):
    """Return band index (0=lowest, n_bands-1=highest) for elevation z_m."""
    raw = (z_m - global_z_min) / interval_m
    idx = int(math.floor(raw))
    return max(0, min(idx, n_bands - 1))


def band_to_avf(band_idx, n_bands):
    """Normalize band index to 0.0-1.0 for AVF storage."""
    if n_bands <= 1: return 1.0
    return band_idx / float(n_bands - 1)


# ---------------------------------------------------------------------------
# Colour element — Fine faces, 400mm grid
# ---------------------------------------------------------------------------
def colour_element_fast(faces, sfm, scheme_id,
                        global_z_min, interval_m, n_bands, grid_ft):
    """
    grid_ft = interval_m * M_TO_FT  (dynamic grid = interval size)
    Larger interval → larger cells → less dense.
    Smaller interval → smaller cells → denser.
    """
    if not faces: return 0
    processed = 0

    for face in faces:
        try:
            ref = face.Reference
            if ref is None: continue
            prim_idx = sfm.AddSpatialFieldPrimitive(ref)
            bb = face.GetBoundingBox()
            u0, u1 = bb.Min.U, bb.Max.U
            v0, v1 = bb.Min.V, bb.Max.V
            u_span = u1 - u0; v_span = v1 - v0
            if u_span < 1e-9 or v_span < 1e-9: continue

            # Adaptive sampling: need ~2 samples per band interval
            # to catch every colour transition. Cap at 50 per dimension.
            half_interval_ft = grid_ft * 0.5
            u_steps = max(4, min(50, int(u_span / half_interval_ft) + 1))
            v_steps = max(4, min(50, int(v_span / half_interval_ft) + 1))
            du = u_span / float(u_steps - 1)
            dv = v_span / float(v_steps - 1)

            uvs  = List[UV]()
            vals = List[ValueAtPoint]()

            for i in range(u_steps):
                u = u0 + i * du
                for j in range(v_steps):
                    v = v0 + j * dv
                    try:
                        pt      = face.Evaluate(UV(u, v))
                        z_m     = pt.Z / M_TO_FT
                        b_idx   = z_to_band(z_m, global_z_min, interval_m, n_bands)
                        avf_val = band_to_avf(b_idx, n_bands)
                        uvs.Add(UV(u, v))
                        vals.Add(make_value(avf_val))
                    except: pass

            if uvs.Count > 0:
                sfm.UpdateSpatialFieldPrimitive(
                    prim_idx,
                    FieldDomainPointsByUV(uvs),
                    FieldValues(vals),
                    scheme_id)
                processed += 1
        except: pass
    return processed


# ---------------------------------------------------------------------------
# Solid fill pattern
# ---------------------------------------------------------------------------
def get_solid_fill_id():
    for fp in FilteredElementCollector(doc).OfClass(FillPatternElement).ToElements():
        try:
            if fp.GetFillPattern().IsSolidFill:
                return fp.Id
        except: pass
    return ElementId.InvalidElementId


# ---------------------------------------------------------------------------
# 2D surface Z lookup — triangle-exact method
# ---------------------------------------------------------------------------

def _sign(ax, ay, bx, by, cx, cy):
    """Sign of the cross product (B-A) x (C-A) in 2D."""
    return (ax - cx) * (by - cy) - (bx - cx) * (ay - cy)


def _point_in_triangle_xy(px, py, ax, ay, bx, by, cx, cy):
    """
    Return True if world point (px,py) lies inside triangle
    (ax,ay)-(bx,by)-(cx,cy) in the XY plane.
    Uses barycentric sign test — exact, no tolerance.
    """
    d1 = _sign(px, py, ax, ay, bx, by)
    d2 = _sign(px, py, bx, by, cx, cy)
    d3 = _sign(px, py, cx, cy, ax, ay)
    has_neg = (d1 < 0) or (d2 < 0) or (d3 < 0)
    has_pos = (d1 > 0) or (d2 > 0) or (d3 > 0)
    return not (has_neg and has_pos)


def _build_face_index(faces):
    """
    Build a spatial index of top faces for fast XY lookup.
    Returns list of (xmin, xmax, ymin, ymax, face, tri_verts_xy) tuples.
    tri_verts_xy: list of triangles, each triangle = ((ax,ay,az),(bx,by,bz),(cx,cy,cz))
    Only triangular faces (Toposolid Fine detail) are supported.
    """
    index = []
    opts = Options()
    opts.ComputeReferences = True
    opts.DetailLevel       = ViewDetailLevel.Fine

    for face in faces:
        try:
            # Get world-space triangulation of this face
            mesh = face.Triangulate()
            if mesh is None or mesh.NumTriangles == 0:
                continue

            # Bounding box for this face in world XY
            f_xmin = f_ymin =  1e18
            f_xmax = f_ymax = -1e18
            triangles = []

            for ti in range(mesh.NumTriangles):
                tri = mesh.get_Triangle(ti)
                verts = []
                for vi in range(3):
                    pt = tri.get_Vertex(vi)
                    verts.append((pt.X, pt.Y, pt.Z))
                    f_xmin = min(f_xmin, pt.X)
                    f_xmax = max(f_xmax, pt.X)
                    f_ymin = min(f_ymin, pt.Y)
                    f_ymax = max(f_ymax, pt.Y)
                triangles.append(tuple(verts))

            index.append((f_xmin, f_xmax, f_ymin, f_ymax, face, triangles))
        except:
            pass
    return index


def _z_at_xy(face_index, wx, wy):
    """
    Return surface Z (in Revit internal feet) at world XY (wx, wy).
    Uses the face spatial index to find candidate faces quickly,
    then performs exact point-in-triangle test.
    Returns (z_ft, True) if found, or (None, False) if no face contains the point.
    """
    for (f_xmin, f_xmax, f_ymin, f_ymax, face, triangles) in face_index:
        # Fast bounding-box reject
        if wx < f_xmin or wx > f_xmax or wy < f_ymin or wy > f_ymax:
            continue
        # Exact point-in-triangle test for each triangle in this face
        for (ax, ay, az), (bx, by, bz), (cx, cy, cz) in triangles:
            if _point_in_triangle_xy(wx, wy, ax, ay, bx, by, cx, cy):
                # Barycentric interpolation of Z from the three vertices
                # Compute barycentric coords (u, v, w) for (wx, wy) in triangle
                denom = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
                if abs(denom) < 1e-12:
                    continue
                u = ((by - cy) * (wx - cx) + (cx - bx) * (wy - cy)) / denom
                v = ((cy - ay) * (wx - cx) + (ax - cx) * (wy - cy)) / denom
                w = 1.0 - u - v
                z_ft = u * az + v * bz + w * cz
                return z_ft, True
    return None, False


def _build_z_lookup(data, sample_u, sample_v):
    """
    Build Z grid using triangle rasterization — O(triangles + cells_covered).

    Replaces the per-cell _z_at_xy search (O(cells x faces)) with a
    triangle-first approach:
      For each triangle in the face index:
        1. Compute which grid rows it spans (Y bounding box)
        2. For each row, scanline-intersect the triangle edges to get col range
        3. For each cell in that col range whose centre is inside the triangle:
           - run exact point-in-triangle test (same as _point_in_triangle_xy)
           - compute barycentric Z (same formula as _z_at_xy)
           - assign to z_grid[row][col]

    Z values are identical to what _z_at_xy would produce — same triangles,
    same barycentric interpolation, same None for uncovered cells.
    No approximation, no centroid, no nearest-face fallback.

    Returns (z_grid, miss_log) — same interface as the old implementation.
    """
    bb_min = data["bb_min"]; bb_max = data["bb_max"]
    faces  = data["faces"]
    wx0 = bb_min.X; wx1 = bb_max.X
    wy0 = bb_min.Y; wy1 = bb_max.Y
    w = wx1 - wx0; h = wy1 - wy0

    if sample_u < 1 or sample_v < 1 or w < 1e-9 or h < 1e-9:
        return [[None] * sample_u for _ in range(sample_v)], []

    cw = w / sample_u   # cell width  (Revit internal feet)
    ch = h / sample_v   # cell height (Revit internal feet)

    # Initialise z_grid as flat list of lists — all None
    z_grid = [[None] * sample_u for _ in range(sample_v)]

    # Build face/triangle index (unchanged — same data as _z_at_xy uses)
    face_index = _build_face_index(faces)

    for (f_xmin, f_xmax, f_ymin, f_ymax, face, triangles) in face_index:
        for (ax, ay, az), (bx, by, bz), (cx, cy, cz) in triangles:

            # --- Triangle XY bounding box → grid cell range ---
            tri_xmin = min(ax, bx, cx)
            tri_xmax = max(ax, bx, cx)
            tri_ymin = min(ay, by, cy)
            tri_ymax = max(ay, by, cy)

            # Column range: cells whose centres fall in [tri_xmin, tri_xmax]
            # Cell col centre = wx0 + (col + 0.5) * cw
            col_min = int((tri_xmin - wx0) / cw - 0.5)
            col_max = int((tri_xmax - wx0) / cw - 0.5) + 1
            col_min = max(0, col_min)
            col_max = min(sample_u - 1, col_max)

            # Row range: cells whose centres fall in [tri_ymin, tri_ymax]
            row_min = int((tri_ymin - wy0) / ch - 0.5)
            row_max = int((tri_ymax - wy0) / ch - 0.5) + 1
            row_min = max(0, row_min)
            row_max = min(sample_v - 1, row_max)

            # Pre-compute barycentric denominator (same as _z_at_xy)
            denom = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
            if abs(denom) < 1e-12:
                continue   # degenerate triangle — skip

            # --- Rasterize: test each candidate cell centre ---
            for row in range(row_min, row_max + 1):
                wy = wy0 + (row + 0.5) * ch   # cell centre Y

                for col in range(col_min, col_max + 1):
                    if z_grid[row][col] is not None:
                        continue   # already filled by an earlier triangle

                    wx = wx0 + (col + 0.5) * cw   # cell centre X

                    # Exact point-in-triangle (same as _point_in_triangle_xy)
                    d1 = (ax - cx) * (wy - cy) - (ay - cy) * (wx - cx)  # _sign rewritten inline
                    # _sign(px,py, ax,ay, bx,by) = (ax-bx)*(py-by)-(ay-by)*(px-bx)
                    d1 = _sign(wx, wy, ax, ay, bx, by)
                    d2 = _sign(wx, wy, bx, by, cx, cy)
                    d3 = _sign(wx, wy, cx, cy, ax, ay)
                    has_neg = (d1 < 0) or (d2 < 0) or (d3 < 0)
                    has_pos = (d1 > 0) or (d2 > 0) or (d3 > 0)
                    if has_neg and has_pos:
                        continue   # outside triangle

                    # Barycentric Z interpolation (same formula as _z_at_xy)
                    u = ((by - cy) * (wx - cx) + (cx - bx) * (wy - cy)) / denom
                    v = ((cy - ay) * (wx - cx) + (ax - cx) * (wy - cy)) / denom
                    wt = 1.0 - u - v
                    z_ft = u * az + v * bz + wt * cz
                    z_grid[row][col] = z_ft / M_TO_FT   # feet → metres

    # Build miss_log for cells still None
    miss_log = [
        (col, row, wx0 + (col + 0.5) * cw, wy0 + (row + 0.5) * ch)
        for row in range(sample_v)
        for col in range(sample_u)
        if z_grid[row][col] is None
    ]

    return z_grid, miss_log


def create_drafting_mesh(draft_view, elem_data_list,
                         global_z_min, interval_m, n_bands, n_bands_display,
                         ramp, solid_fill_id, grid_ft):
    """
    2D drafting mesh — performance-safe version.
    grid_ft drives cell size (= interval size, links density to band size).
    n_bands used for correct AVF normalization.
    n_bands_display used for ramp index mapping.
    Capped at MAX_CELLS to prevent explosion on small intervals.
    """
    MAX_TOTAL_CELLS = 50000  # safety limit — warn and skip 2D if exceeded

    try:
        frt = None
        for t in FilteredElementCollector(doc)\
                .OfClass(FilledRegionType).ToElements():
            frt = t; break
        if frt is None: return

        # Delete existing FilledRegion elements in this drafting view only
        # so re-running with a different interval replaces the old grid
        existing_fr_ids = [
            e.Id for e in
            FilteredElementCollector(doc, draft_view.Id)
            .OfClass(FilledRegion)
            .ToElements()
        ]
        for eid in existing_fr_ids:
            try: doc.Delete(eid)
            except: pass

        for data in elem_data_list:
            bb_min = data["bb_min"]; bb_max = data["bb_max"]
            wx0 = bb_min.X; wx1 = bb_max.X
            wy0 = bb_min.Y; wy1 = bb_max.Y
            w = wx1 - wx0; h = wy1 - wy0

            # Per-element Z range from SlabShapeVertices
            elem_z_min = data["z_min"]
            elem_z_max = data["z_max"]
            elem_n_bands = max(2, int(math.ceil((elem_z_max - elem_z_min) / interval_m)))
            elem_n_ramp  = min(elem_n_bands, len(ramp))

            # Cell size = requested interval exactly (1:1 relationship)
            n_cols = max(2, int(round(w / grid_ft)))
            n_rows = max(2, int(round(h / grid_ft)))
            total  = n_cols * n_rows

            # Upfront safety check — warn user, do not silently rescale
            if total > MAX_TOTAL_CELLS:
                interval_mm = int(round(interval_m * 1000))
                w_m  = w / M_TO_FT
                h_m  = h / M_TO_FT
                suggest_mm = int(math.ceil(interval_mm * math.sqrt(total / MAX_TOTAL_CELLS)))
                msg = "Selected interval (" + str(interval_mm) + " mm) would create " + str(total) + " cells (" + str(n_cols) + " cols x " + str(n_rows) + " rows) for a " + "{:.1f}".format(w_m) + " m x " + "{:.1f}".format(h_m) + " m area. Maximum allowed: " + str(MAX_TOTAL_CELLS) + " cells. Please use a larger interval (e.g. " + str(suggest_mm) + " mm) or split the Toposolid into smaller areas."
                _forms.alert(msg, title="Too many cells - 2D mesh not created", ok=True)
                continue   # skip 2D for this element only — 3D unaffected

            cw = w / n_cols
            ch = h / n_rows

            # Surface Z lookup — triangle-exact from actual face geometry
            # _build_z_lookup, _build_face_index, _z_at_xy unchanged
            z_grid, miss_log = _build_z_lookup(data, n_cols, n_rows)

            # Build band index grid using per-element Z range
            band_grid  = []
            all_z      = []
            all_b_idx  = []
            sample_log = []
            n_miss     = len(miss_log)

            for row in range(n_rows):
                row_bands = []
                for col in range(n_cols):
                    z_m = z_grid[row][col]
                    if z_m is None:
                        row_bands.append(None)   # no surface — skip, no Z invented
                    else:
                        b_idx = z_to_band(z_m, elem_z_min, interval_m, elem_n_bands)
                        row_bands.append(b_idx)
                        all_z.append(z_m)
                        all_b_idx.append(b_idx)
                        if len(sample_log) < 5:
                            ri = int(round(b_idx * (elem_n_ramp - 1)
                                           / float(max(elem_n_bands - 1, 1))))
                            ri = max(0, min(elem_n_ramp - 1 - ri, len(ramp) - 1))
                            rc = ramp[ri]
                            sample_log.append(
                                "  cell({},{}) z={:.4f}m b_idx={} "
                                "ramp_idx={} RGB=({},{},{})".format(
                                    col, row, z_m, b_idx,
                                    ri, rc.Red, rc.Green, rc.Blue))
                band_grid.append(row_bands)

            # Diagnostic log
            try:
                from pyrevit import script as _sc
                _out = _sc.get_output()
                _out.print_md("### 2D Mesh Diagnostic")
                _out.print_md(
                    "Interval: {:.0f} mm  |  Cell: {:.1f} mm x {:.1f} mm  |  "
                    "Grid: {} cols x {} rows = {} cells".format(
                        interval_m * 1000,
                        (cw / M_TO_FT) * 1000, (ch / M_TO_FT) * 1000,
                        n_cols, n_rows, total))
                _out.print_md(
                    "elem_z_min={:.4f}m  elem_z_max={:.4f}m  |  "
                    "interval={}m  |  elem_n_bands={}  |  elem_n_ramp={}".format(
                        elem_z_min, elem_z_max, interval_m,
                        elem_n_bands, elem_n_ramp))
                if all_z:
                    _out.print_md(
                        "Z range in cells: min={:.4f}m  max={:.4f}m  "
                        "unique Z={} / {} cells  |  "
                        "b_idx range: {}-{}  unique={}  |  "
                        "No-surface cells: {}".format(
                            min(all_z), max(all_z),
                            len(set(round(z, 4) for z in all_z)), len(all_z),
                            min(all_b_idx), max(all_b_idx),
                            len(set(all_b_idx)),
                            n_miss))
                else:
                    _out.print_md(
                        "WARNING: no valid Z values found. "
                        "No-surface cells: {}".format(n_miss))
                _out.print_md("Sample cells (first 5 with valid Z):")
                for s in sample_log:
                    _out.print_md(s)
                if miss_log[:3]:
                    for col, row, wx, wy in miss_log[:3]:
                        _out.print_md(
                            "  No surface at cell({},{}) wx={:.3f}ft wy={:.3f}ft".format(
                                col, row, wx, wy))
            except: pass

            # ------------------------------------------------------------------
            # Scanline merge: collapse same-band adjacent cells into rectangles.
            # One FilledRegion per merged rectangle, not per cell.
            # Never merges across different bands, None cells, or row gaps.
            # ------------------------------------------------------------------

            # Step 1: build row runs — list of (col_start, col_end, band) per row
            # A run is a maximal horizontal sequence of identical non-None band values.
            row_runs = []
            for row in range(n_rows):
                runs = []
                col = 0
                while col < n_cols:
                    b = band_grid[row][col]
                    if b is None:
                        col += 1
                        continue
                    # extend run while same band and not None
                    start = col
                    while col < n_cols and band_grid[row][col] == b:
                        col += 1
                    runs.append((start, col, b))   # col_end is exclusive
                row_runs.append(runs)

            # Step 2: vertical merge — accumulate rectangles
            # rect_list: list of (col_start, col_end, row_start, row_end, band)
            # active: dict mapping (col_start, col_end, band) -> row_start
            rect_list = []
            active = {}   # key=(col_start, col_end, band), value=row_start

            for row in range(n_rows):
                current_keys = set()
                for (cs, ce, b) in row_runs[row]:
                    key = (cs, ce, b)
                    current_keys.add(key)
                    if key not in active:
                        active[key] = row   # start a new rectangle

                # Close any active rectangles whose run did not continue this row
                closed = [k for k in active if k not in current_keys]
                for key in closed:
                    cs, ce, b = key
                    rs = active.pop(key)
                    rect_list.append((cs, ce, rs, row, b))

            # Close remaining active rectangles at end of grid
            for key, rs in active.items():
                cs, ce, b = key
                rect_list.append((cs, ce, rs, n_rows, b))

            # Step 3: create one FilledRegion per merged rectangle
            n_created = 0
            for (cs, ce, rs, re, b) in rect_list:
                ri = int(round(b * (elem_n_ramp - 1)
                               / float(max(elem_n_bands - 1, 1))))
                ri = max(0, min(elem_n_ramp - 1 - ri, len(ramp) - 1))
                c  = ramp[ri]

                x0 = wx0 + cs * cw;  x1 = wx0 + ce * cw
                y0 = wy0 + rs * ch;  y1 = wy0 + re * ch

                loop = CurveLoop()
                loop.Append(Line.CreateBound(XYZ(x0, y0, 0), XYZ(x1, y0, 0)))
                loop.Append(Line.CreateBound(XYZ(x1, y0, 0), XYZ(x1, y1, 0)))
                loop.Append(Line.CreateBound(XYZ(x1, y1, 0), XYZ(x0, y1, 0)))
                loop.Append(Line.CreateBound(XYZ(x0, y1, 0), XYZ(x0, y0, 0)))
                loops = List[CurveLoop](); loops.Add(loop)
                try:
                    fr  = FilledRegion.Create(doc, frt.Id, draft_view.Id, loops)
                    ogs = OverrideGraphicSettings()
                    ogs.SetSurfaceForegroundPatternColor(c)
                    ogs.SetSurfaceBackgroundPatternColor(c)
                    if solid_fill_id != ElementId.InvalidElementId:
                        ogs.SetSurfaceForegroundPatternId(solid_fill_id)
                        ogs.SetSurfaceBackgroundPatternId(solid_fill_id)
                    draft_view.SetElementOverrides(fr.Id, ogs)
                    n_created += 1
                except: pass

            # Diagnostic: reduction summary
            n_cells = sum(1 for row in range(n_rows)
                          for col in range(n_cols)
                          if band_grid[row][col] is not None)
            reduction = (1.0 - n_created / float(max(n_cells, 1))) * 100
            try:
                from pyrevit import script as _sc
                _out = _sc.get_output()
                _out.print_md("### 2D Mesh Complete")
                _out.print_md(
                    "Cells: {:,}  |  Merged FilledRegions: {:,}  |  "
                    "Reduction: {:.1f}%".format(n_cells, n_created, reduction))
            except: pass

    except: pass


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------
try:
    # Step 1 — interval
    interval_mm = ask_interval_mm()
    if interval_mm is None:
        import sys; sys.exit(0)
    interval_m = interval_mm / 1000.0

    # Step 1b — output mode
    output_mode = ask_output_mode()
    if output_mode is None:
        import sys; sys.exit(0)
    do_3d = output_mode in ("3d", "both")
    do_2d = output_mode in ("2d", "both")

    # Step 2 — select elements
    _forms.alert(
        "Select Floors / Toposolids to colour.\nHold Ctrl for multiple.",
        title="Colour Toposolids", ok=True)
    try:
        refs  = uidoc.Selection.PickObjects(
            ObjectType.Element, FloorOrTopoFilter(),
            "Select elements to colour")
        elems = [doc.GetElement(r.ElementId) for r in refs]
    except:
        import sys; sys.exit(0)

    if not elems:
        _forms.alert("No elements selected.", ok=True)
        import sys; sys.exit(0)

    selected_ids = [e.Id for e in elems]

    # Step 3 — geometry (Fine detail)
    elem_data = collect_elem_data(elems)

    # Step 4 — project base point datum
    datum_z = get_project_base_z_m()

    # Step 5 — shared global range across all elements
    global_z_min =  1e18
    global_z_max = -1e18
    for data in elem_data.values():
        global_z_min = min(global_z_min, data["z_min"])
        global_z_max = max(global_z_max, data["z_max"])

    if global_z_min > global_z_max:
        global_z_min, global_z_max = 0.0, 1.0

    # Snap global_z_min DOWN to nearest interval boundary from datum
    # so colour bands align cleanly to project datum
    offset_from_datum = global_z_min - datum_z
    bands_below = math.floor(offset_from_datum / interval_m)
    snapped_z_min = datum_z + bands_below * interval_m

    # Number of bands to cover full range
    z_span  = global_z_max - snapped_z_min
    n_bands = max(2, int(math.ceil(z_span / interval_m)))

    # n_bands_display capped at 128 only for display style colour entries
    # AVF normalization uses full n_bands so values spread correctly 0.0-1.0
    n_bands_display = min(n_bands, 128)
    ramp = build_color_ramp(n_bands_display)

    # Dynamic grid size = interval size (larger interval = coarser grid)
    # This links tessellation density to the selected band size
    grid_ft = interval_m * M_TO_FT
    solid_fill_id = get_solid_fill_id()

    # Step 6 — create views
    with Transaction(doc, "TLA - Create Views") as t:
        t.Start()
        view       = get_or_create_3d_view() if do_3d else None
        draft_view = get_or_create_drafting_view() if do_2d else None
        t.Commit()

    if do_3d:
        if view is None:
            _forms.alert("Could not find or create a 3D view.", ok=True)
            import sys; sys.exit(0)
        uidoc.ActiveView = view

    sfm = None
    if do_3d:
        # Apply display style + view settings
        with Transaction(doc, "TLA - Apply View Settings") as t:
            t.Start()
            style    = ensure_display_style(n_bands_display, ramp)
            style_id = style.Id if style is not None else None
            apply_view_settings(view, style_id, selected_ids)
            t.Commit()

        sfm = get_sfm(view)
        if sfm is None:
            _forms.alert(
                "Could not create SpatialFieldManager.\n"
                "Open the 3D view manually and try again.",
                title="Colour Toposolids", ok=True)
            import sys; sys.exit(0)

    # Step 8 — AVF colouring + 2D drafting mesh
    with Transaction(doc, "TLA Grading - Colour Toposolids") as t:
        t.Start()
        scheme_id   = get_or_create_scheme(sfm) if do_3d and sfm else None
        total_faces = 0
        log_lines   = [
            "Colour Toposolids Log",
            "Interval: {} mm | Bands: {} | Range: {:.3f}m – {:.3f}m".format(
                int(interval_mm), n_bands,
                snapped_z_min, snapped_z_min + n_bands * interval_m),
            "Project Base Point Z: {:.3f} m".format(datum_z),
            ""
        ]

        elem_data_list = []
        for elem in elems:
            try:
                data  = elem_data.get(elem.Id.IntegerValue, {})

                # Skip elements where finished surface vertices unavailable
                if data.get("skip", False):
                    etype = "Toposolid" if isinstance(elem, Toposolid) else "Floor"
                    log_lines.append(
                        "  SKIPPED {} {} — {}  (vertices found: {})".format(
                            etype, elem.Id.IntegerValue,
                            data.get("skip_reason", "unknown"),
                            data.get("vertex_count", 0)))
                    continue

                faces = data.get("faces", [])
                z_min = data.get("z_min", global_z_min)
                z_max = data.get("z_max", global_z_max)
                vcount = data.get("vertex_count", 0)

                # Per-element band calculation using actual surface Z range
                elem_n_bands = max(2, int(math.ceil((z_max - z_min) / interval_m)))
                elem_n_bands_display = min(elem_n_bands, 128)

                # 3D AVF colouring — use per-element Z range, not snapped global
                if do_3d and sfm is not None:
                    n = colour_element_fast(
                        faces, sfm, scheme_id,
                        z_min, interval_m, elem_n_bands, grid_ft)
                    total_faces += n

                elem_data_list.append(data)
                etype = "Toposolid" if isinstance(elem, Toposolid) else "Floor"
                log_lines.append(
                    "  {} {} | surface Z: {:.3f}m – {:.3f}m | "
                    "range: {:.0f}mm | bands: {} | vertices: {}".format(
                        etype, elem.Id.IntegerValue,
                        z_min, z_max,
                        (z_max - z_min) * 1000,
                        elem_n_bands, vcount))
            except Exception:
                log_lines.append("  Element {}: ERROR\n{}".format(
                    elem.Id.IntegerValue, traceback.format_exc()))

        # 2D drafting mesh — only when requested
        if do_2d and draft_view is not None:
            create_drafting_mesh(
                draft_view, elem_data_list,
                snapped_z_min, interval_m, n_bands, n_bands_display,
                ramp, solid_fill_id, grid_ft)

        t.Commit()

    log_lines.append("\nTotal faces coloured: {}".format(total_faces))
    if draft_view is not None:
        log_lines.append("2D mesh created: '{}'".format(DRAFT_NAME))

    # Summary dialog
    win = Window()
    win.Title = "TLA Grading — Colour Toposolids"
    win.Width = 460
    win.WindowStartupLocation = WindowStartupLocation.CenterScreen
    win.Background = SolidColorBrush(C_YELLOW)
    win.SizeToContent = System.Windows.SizeToContent.Height
    win.ResizeMode = System.Windows.ResizeMode.NoResize

    sp = StackPanel()
    sp.Orientation = Orientation.Vertical
    sp.Margin = Thickness(14, 14, 14, 14)
    win.Content = sp

    hdr = TextBlock()
    hdr.Text = "COLOUR TOPOSOLIDS — DONE"
    hdr.FontSize = 13
    hdr.FontWeight = System.Windows.FontWeights.Bold
    hdr.Foreground = SolidColorBrush(C_BLACK)
    hdr.Margin = Thickness(0, 0, 0, 8)
    sp.Children.Add(hdr)

    for line in log_lines:
        if not line.strip(): continue
        tb = TextBlock()
        tb.Text = line.strip(); tb.FontSize = 11
        tb.Foreground = SolidColorBrush(C_BLACK)
        tb.Margin = Thickness(0, 1, 0, 1)
        tb.TextWrapping = System.Windows.TextWrapping.Wrap
        sp.Children.Add(tb)

    footer = StackPanel()
    footer.Orientation = Orientation.Horizontal
    footer.HorizontalAlignment = HorizontalAlignment.Right
    footer.Margin = Thickness(0, 10, 0, 0)

    ok_btn = Button()
    ok_btn.Content = "OK"; ok_btn.Width = 90; ok_btn.Height = 30
    ok_btn.Background = SolidColorBrush(C_BLACK)
    ok_btn.Foreground = SolidColorBrush(C_WHITE)
    ok_btn.FontWeight = System.Windows.FontWeights.Bold
    ok_btn.Click += lambda s, e: win.Close()
    footer.Children.Add(ok_btn)
    sp.Children.Add(footer)
    win.ShowDialog()

except Exception:
    _forms.alert(traceback.format_exc(), title="ERROR", ok=True)

