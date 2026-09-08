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
            if v <= 0:
                err.Text = "Must be greater than 0."
                return
            if v < 1:
                err.Text = "Minimum interval is 1 mm."
                return
            result[0] = v
            win.Close()
        except:
            err.Text = "Enter a valid number (e.g. 100)."
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
        z_min =  1e18
        z_max = -1e18
        bb_elem = elem.get_BoundingBox(None)
        bb_min  = bb_elem.Min if bb_elem else XYZ(0, 0, 0)
        bb_max  = bb_elem.Max if bb_elem else XYZ(1, 1, 1)

        # Bounding box Z as fallback range
        z_min_bb = bb_min.Z / M_TO_FT
        z_max_bb = bb_max.Z / M_TO_FT

        try:
            for obj in elem.get_Geometry(opts):
                if not isinstance(obj, Solid): continue
                for face in obj.Faces:
                    try:
                        if face.FaceNormal.Z <= 0.3 or face.Reference is None:
                            continue
                        bb = face.GetBoundingBox()
                        for uf in [bb.Min.U, (bb.Min.U+bb.Max.U)*0.5, bb.Max.U]:
                            for vf in [bb.Min.V, (bb.Min.V+bb.Max.V)*0.5, bb.Max.V]:
                                try:
                                    z_m   = face.Evaluate(UV(uf, vf)).Z / M_TO_FT
                                    z_min = min(z_min, z_m)
                                    z_max = max(z_max, z_m)
                                except: pass
                        faces.append(face)
                    except: pass
        except: pass

        if z_min > z_max or abs(z_max - z_min) < 0.001:
            z_min = z_min_bb; z_max = z_max_bb
        if abs(z_max - z_min) < 0.001:
            z_max = z_min + 0.001

        elem_data[elem.Id.IntegerValue] = {
            "faces": faces, "z_min": z_min, "z_max": z_max,
            "bb_min": bb_min, "bb_max": bb_max,
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
                        global_z_min, interval_m, n_bands):
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

            u_steps = max(2, int(u_span / GRID_FT) + 1)
            v_steps = max(2, int(v_span / GRID_FT) + 1)
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
# 2D Drafting View mesh
# Same shared band logic as 3D AVF — exact colour match
# ---------------------------------------------------------------------------
def _build_z_lookup(data, sample_u, sample_v):
    """
    Pre-sample Z values on a sample_u x sample_v grid over the element
    bounding box using face.Evaluate() — called ONCE per element.
    Returns a 2D list z_grid[row][col] in metres.
    No face.Project() calls — eliminates the ray-cast bottleneck.
    """
    bb_min = data["bb_min"]; bb_max = data["bb_max"]
    faces  = data["faces"]
    z_mid  = (data["z_min"] + data["z_max"]) / 2.0
    wx0 = bb_min.X; wx1 = bb_max.X
    wy0 = bb_min.Y; wy1 = bb_max.Y
    w = wx1 - wx0; h = wy1 - wy0

    z_grid = []
    for row in range(sample_v):
        wy = wy0 + (row + 0.5) * (h / sample_v)
        row_z = []
        for col in range(sample_u):
            wx  = wx0 + (col + 0.5) * (w / sample_u)
            z_m = z_mid
            for face in faces:
                try:
                    bb  = face.GetBoundingBox()
                    # Map world XY roughly to face UV via bounding box
                    # (fast approximation — no ray-cast needed)
                    u_frac = (wx - wx0) / w if w > 1e-9 else 0.5
                    v_frac = (wy - wy0) / h if h > 1e-9 else 0.5
                    u = bb.Min.U + u_frac * (bb.Max.U - bb.Min.U)
                    v = bb.Min.V + v_frac * (bb.Max.V - bb.Min.V)
                    pt  = face.Evaluate(UV(u, v))
                    z_m = pt.Z / M_TO_FT
                    break
                except:
                    pass
            row_z.append(z_m)
        z_grid.append(row_z)
    return z_grid


def create_drafting_mesh(draft_view, elem_data_list,
                         global_z_min, interval_m, n_bands,
                         ramp, solid_fill_id):
    """
    2D drafting mesh — performance-safe version.
    Key optimisations:
    1. Z lookup pre-sampled ONCE per element (no face.Project per cell)
    2. Grid capped at MAX_CELLS x MAX_CELLS = 1024 cells max per element
    3. Colour grouped — consecutive same-colour cells merged into one rect
       (reduces FilledRegion count dramatically for near-flat toposolids)
    """
    MAX_CELLS = 32   # 32x32 = 1024 max filled regions per element

    try:
        frt = None
        for t in FilteredElementCollector(doc)\
                .OfClass(FilledRegionType).ToElements():
            frt = t; break
        if frt is None: return

        x_offset = 0.0
        gap_ft   = 1.0 / M_TO_FT

        for data in elem_data_list:
            bb_min = data["bb_min"]; bb_max = data["bb_max"]
            wx0 = bb_min.X; wx1 = bb_max.X
            wy0 = bb_min.Y; wy1 = bb_max.Y
            w = wx1 - wx0; h = wy1 - wy0

            n_cols = min(MAX_CELLS, max(4, int(round(w / GRID_FT))))
            n_rows = min(MAX_CELLS, max(4, int(round(h / GRID_FT))))
            cw = w / n_cols
            ch = h / n_rows

            # PRE-SAMPLE Z once — eliminates face.Project bottleneck
            z_grid = _build_z_lookup(data, n_cols, n_rows)

            # Build band index grid
            band_grid = []
            for row in range(n_rows):
                row_bands = []
                for col in range(n_cols):
                    z_m   = z_grid[row][col]
                    b_idx = z_to_band(z_m, global_z_min, interval_m, n_bands)
                    row_bands.append(b_idx)
                band_grid.append(row_bands)

            # Draw one FilledRegion per cell
            for col in range(n_cols):
                for row in range(n_rows):
                    b_idx    = band_grid[row][col]
                    ramp_idx = max(0, min(n_bands - 1 - b_idx, len(ramp) - 1))
                    c = ramp[ramp_idx]

                    x0 = x_offset + col * cw; x1 = x0 + cw
                    y0 = row * ch;             y1 = y0 + ch

                    loop = CurveLoop()
                    loop.Append(Line.CreateBound(XYZ(x0,y0,0), XYZ(x1,y0,0)))
                    loop.Append(Line.CreateBound(XYZ(x1,y0,0), XYZ(x1,y1,0)))
                    loop.Append(Line.CreateBound(XYZ(x1,y1,0), XYZ(x0,y1,0)))
                    loop.Append(Line.CreateBound(XYZ(x0,y1,0), XYZ(x0,y0,0)))
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
                    except: pass

            x_offset += w + gap_ft

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

    # Cap at 128 for display style
    n_bands_display = min(n_bands, 128)

    ramp         = build_color_ramp(n_bands_display)
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
                faces = data.get("faces", [])
                z_min = data.get("z_min", global_z_min)
                z_max = data.get("z_max", global_z_max)

                # 3D AVF colouring
                if do_3d and sfm is not None:
                    n = colour_element_fast(
                        faces, sfm, scheme_id,
                        snapped_z_min, interval_m, n_bands_display)
                    total_faces += n

                elem_data_list.append(data)
                etype = "Toposolid" if isinstance(elem, Toposolid) else "Floor"
                log_lines.append(
                    "  {} {} | {:.3f}m – {:.3f}m".format(
                        etype, elem.Id.IntegerValue, z_min, z_max))
            except Exception:
                log_lines.append("  Element {}: ERROR\n{}".format(
                    elem.Id.IntegerValue, traceback.format_exc()))

        # 2D drafting mesh — only when requested
        if do_2d and draft_view is not None:
            create_drafting_mesh(
                draft_view, elem_data_list,
                snapped_z_min, interval_m, n_bands_display,
                ramp, solid_fill_id)

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

