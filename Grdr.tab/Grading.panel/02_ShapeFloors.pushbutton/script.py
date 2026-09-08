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
    BuiltInParameter, ReferenceIntersector,
    FindReferenceTarget, View3D, Line, UV
)
from Autodesk.Revit.UI.Selection import ObjectType, ISelectionFilter

doc   = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument

MM_TO_FT  = 0.00328084
M_TO_FT   = 3.28084
SAFE_NODE_LIMIT = 2000
CURVE_SAMPLE_FT = 50.0 * MM_TO_FT   # sample curves every 50mm for pip test
BND_TOL_FT      = 1.0  * MM_TO_FT   # 1mm — on-boundary tolerance

BND_HALF_X_MM = 1500
BND_HALF_Y_MM = 1000

TESS_LEVELS = {
    1:  (1500, 1000),
    2:  (1400,  950),
    3:  (1300,  850),
    4:  (1200,  800),
    5:  (1050,  700),
    6:  ( 950,  650),
    7:  ( 850,  550),
    8:  ( 750,  500),
    9:  ( 650,  450),
    10: ( 600,  400),
}

def get_3d_view():
    view = doc.ActiveView
    if isinstance(view, View3D):
        return view
    from Autodesk.Revit.DB import FilteredElementCollector
    for v in FilteredElementCollector(doc).OfClass(View3D).ToElements():
        if not v.IsTemplate:
            return v
    return None

def get_family_type_name(element):
    try:
        type_id = element.GetTypeId()
        etype   = doc.GetElement(type_id)
        fam = etype.get_Parameter(
            BuiltInParameter.SYMBOL_FAMILY_NAME_PARAM).AsString()
        typ = etype.get_Parameter(
            BuiltInParameter.SYMBOL_NAME_PARAM).AsString()
        return "{}: {}".format(fam, typ)
    except:
        return "Unknown"

def is_floor(element):    return isinstance(element, Floor)
def is_toposolid(element): return isinstance(element, Toposolid)

def is_flat(element):
    if is_floor(element):
        try:
            sse = element.SlabShapeEditor
            return sse is None or sse.SlabShapeCreaseArray.Size == 0
        except:
            return True
    return True

def flatten_element(element):
    if is_floor(element):
        try:
            sse = element.SlabShapeEditor
            if sse:
                sse.ResetSlabShape()
        except:
            pass

def get_topo_z(intersector, x, y, search_z):
    try:
        results = intersector.Find(XYZ(x, y, search_z), XYZ(0, 0, -1))
        if results and results.Count > 0:
            return search_z - results[0].Proximity
    except:
        pass
    return None

def get_boundary_curves(element):
    """Return Revit Curve objects from sketch. Works for arcs/splines."""
    curves = []
    try:
        sketch = doc.GetElement(element.SketchId)
        if sketch:
            for curve_arr in sketch.Profile:
                for curve in curve_arr:
                    curves.append(curve)
            if curves:
                return curves
    except:
        pass
    bb = element.get_BoundingBox(None)
    if bb:
        corners = [
            XYZ(bb.Min.X, bb.Min.Y, 0),
            XYZ(bb.Max.X, bb.Min.Y, 0),
            XYZ(bb.Max.X, bb.Max.Y, 0),
            XYZ(bb.Min.X, bb.Max.Y, 0),
        ]
        for i in range(4):
            try:
                curves.append(Line.CreateBound(
                    corners[i], corners[(i + 1) % 4]))
            except:
                pass
    return curves

def sample_curve_points(curve, spacing_ft):
    """
    Sample points along a Revit curve at spacing_ft intervals.
    Works for lines, arcs, splines via Evaluate(parameter).
    Returns list of (x, y).
    """
    pts = []
    try:
        length = curve.Length
        if length < 1e-6:
            return pts
        steps = max(1, int(length / spacing_ft))
        for i in range(steps + 1):
            t   = float(i) / steps
            xyz = curve.Evaluate(t, True)  # True = normalised parameter
            pts.append((xyz.X, xyz.Y))
    except:
        try:
            p0 = curve.GetEndPoint(0)
            p1 = curve.GetEndPoint(1)
            pts = [(p0.X, p0.Y), (p1.X, p1.Y)]
        except:
            pass
    return pts

def build_polygon_from_curves(curves, sample_spacing_ft):
    """
    Build a dense 2D polygon from curves by sampling each one.
    Returns list of (x, y) in order.
    """
    poly = []
    seen = set()
    for curve in curves:
        for (x, y) in sample_curve_points(curve, sample_spacing_ft):
            key = (round(x / BND_TOL_FT), round(y / BND_TOL_FT))
            if key not in seen:
                seen.add(key)
                poly.append((x, y))
    return poly

def point_in_polygon_xy(x, y, poly):
    """Ray casting PiP test on 2D polygon list."""
    inside = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if ((y1 > y) != (y2 > y)) and \
           (x < (x2 - x1) * (y - y1) / (y2 - y1 + 1e-12) + x1):
            inside = not inside
    return inside

def dist_point_to_curve(pt_xyz, curve):
    try:
        result = curve.Project(pt_xyz)
        if result is not None:
            return result.Distance
    except:
        pass
    try:
        d1 = pt_xyz.DistanceTo(curve.GetEndPoint(0))
        d2 = pt_xyz.DistanceTo(curve.GetEndPoint(1))
        return min(d1, d2)
    except:
        return float('inf')

def is_on_boundary_curves(x, y, curves):
    pt = XYZ(x, y, 0)
    for curve in curves:
        if dist_point_to_curve(pt, curve) <= BND_TOL_FT:
            return True
    return False

def points_on_boundary_curves(curves, spacing_ft):
    """
    Sample points along each boundary curve at spacing_ft intervals.
    Handles arcs and splines correctly.
    """
    result = []
    seen   = set()
    tol    = spacing_ft * 0.05

    def add(x, y):
        key = (round(x / tol), round(y / tol))
        if key not in seen:
            seen.add(key)
            result.append((x, y))

    for curve in curves:
        for (x, y) in sample_curve_points(curve, spacing_ft):
            add(x, y)
    return result

def generate_interior_nodes(bb, curves, poly, half_x_ft, half_y_ft):
    """
    Generate rhombus mesh nodes strictly inside the polygon
    and not on any boundary curve.
    """
    nodes = []
    row   = 0
    y     = bb.Min.Y

    while y <= bb.Max.Y + half_y_ft:
        x_offset = (row % 2) * half_x_ft
        x = bb.Min.X + x_offset
        while x <= bb.Max.X + half_x_ft:
            if point_in_polygon_xy(x, y, poly):
                if not is_on_boundary_curves(x, y, curves):
                    nodes.append((x, y))
            x += 2.0 * half_x_ft
        row += 1
        y   += half_y_ft
    return nodes

def count_nodes_for_element(element, half_x_ft, half_y_ft):
    bb = element.get_BoundingBox(None)
    if bb is None:
        return 0, 0, 0
    curves      = get_boundary_curves(element)
    poly        = build_polygon_from_curves(curves, CURVE_SAMPLE_FT)
    bnd_spacing = min(BND_HALF_X_MM, BND_HALF_Y_MM) * MM_TO_FT
    bnd_pts     = points_on_boundary_curves(curves, bnd_spacing)
    int_pts     = generate_interior_nodes(bb, curves, poly,
                                          half_x_ft, half_y_ft)
    total       = len(bnd_pts) + len(int_pts)
    return len(bnd_pts), len(int_pts), total

def shape_floor(element, intersector, offset_m, match_method,
                reset_first, half_x_ft, half_y_ft, search_z):
    offset_ft = offset_m * M_TO_FT
    sse = element.SlabShapeEditor
    if sse is None:
        return False, "SlabShapeEditor not available"
    try:
        if reset_first:
            sse.ResetSlabShape()
        sse.Enable()

        bb = element.get_BoundingBox(None)
        if bb is None:
            return False, "No bounding box"

        curves      = get_boundary_curves(element)
        poly        = build_polygon_from_curves(curves, CURVE_SAMPLE_FT)
        bnd_spacing = min(BND_HALF_X_MM, BND_HALF_Y_MM) * MM_TO_FT
        bnd_pts     = points_on_boundary_curves(curves, bnd_spacing)
        int_pts     = generate_interior_nodes(bb, curves, poly,
                                              half_x_ft, half_y_ft)

        placed_bnd = placed_int = skipped = 0

        for (x, y) in bnd_pts:
            topo_z = get_topo_z(intersector, x, y, search_z)
            if topo_z is None:
                skipped += 1
                continue
            z = (topo_z - offset_ft / 2.0
                 if match_method == "Submerged Half"
                 else topo_z + offset_ft)
            try:
                sse.DrawPoint(XYZ(x, y, z))
                placed_bnd += 1
            except:
                skipped += 1

        for (x, y) in int_pts:
            topo_z = get_topo_z(intersector, x, y, search_z)
            if topo_z is None:
                skipped += 1
                continue
            z = (topo_z - offset_ft / 2.0
                 if match_method == "Submerged Half"
                 else topo_z + offset_ft)
            try:
                sse.DrawPoint(XYZ(x, y, z))
                placed_int += 1
            except:
                skipped += 1

        total = placed_bnd + placed_int
        if total == 0:
            return False, "No points placed - floor outside source"
        return True, "Boundary:{} Interior:{} Skipped:{}".format(
            placed_bnd, placed_int, skipped)
    except Exception:
        return False, traceback.format_exc()

def shape_toposolid(element, intersector, offset_m, match_method,
                    half_x_ft, half_y_ft, search_z):
    offset_ft = offset_m * M_TO_FT
    try:
        bb = element.get_BoundingBox(None)
        if bb is None:
            return False, "No bounding box"

        curves      = get_boundary_curves(element)
        poly        = build_polygon_from_curves(curves, CURVE_SAMPLE_FT)
        bnd_spacing = min(BND_HALF_X_MM, BND_HALF_Y_MM) * MM_TO_FT
        bnd_pts     = points_on_boundary_curves(curves, bnd_spacing)
        int_pts     = generate_interior_nodes(bb, curves, poly,
                                              half_x_ft, half_y_ft)
        all_pts     = list(bnd_pts) + list(int_pts)
        placed = skipped = 0

        for (x, y) in all_pts:
            topo_z = get_topo_z(intersector, x, y, search_z)
            if topo_z is None:
                skipped += 1
                continue
            z = (topo_z - offset_ft / 2.0
                 if match_method == "Submerged Half"
                 else topo_z + offset_ft)
            try:
                element.AddPoint(XYZ(x, y, z))
                placed += 1
            except:
                skipped += 1

        if placed == 0:
            return False, "No points placed - outside source"
        return True, "Placed:{} Skipped:{}".format(placed, skipped)
    except Exception:
        return False, traceback.format_exc()

def shape_element(element, intersector, offset_m, match_method,
                  reset_first, half_x_ft, half_y_ft, search_z):
    if is_toposolid(element):
        return shape_toposolid(element, intersector, offset_m,
                               match_method, half_x_ft, half_y_ft, search_z)
    return shape_floor(element, intersector, offset_m, match_method,
                       reset_first, half_x_ft, half_y_ft, search_z)

XAML = """<Window
    xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
    xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
    Title="Shape Floors" Height="600" Width="560"
    WindowStartupLocation="CenterScreen"
    Background="#F5C842" ResizeMode="NoResize">
  <Window.Resources>
    <Style TargetType="TextBlock">
      <Setter Property="Foreground" Value="#111111"/>
      <Setter Property="FontFamily" Value="Segoe UI"/>
      <Setter Property="FontSize" Value="12"/>
    </Style>
    <Style TargetType="CheckBox">
      <Setter Property="Foreground" Value="#111111"/>
      <Setter Property="FontFamily" Value="Segoe UI"/>
    </Style>
    <Style TargetType="ComboBox">
      <Setter Property="Background" Value="White"/>
      <Setter Property="Foreground" Value="#111111"/>
      <Setter Property="BorderBrush" Value="#111111"/>
    </Style>
    <Style TargetType="Button">
      <Setter Property="Background" Value="#111111"/>
      <Setter Property="Foreground" Value="White"/>
      <Setter Property="BorderThickness" Value="0"/>
      <Setter Property="Padding" Value="16,6"/>
      <Setter Property="FontFamily" Value="Segoe UI"/>
      <Setter Property="FontWeight" Value="Bold"/>
      <Setter Property="Cursor" Value="Hand"/>
    </Style>
    <Style TargetType="DataGrid">
      <Setter Property="Background" Value="White"/>
      <Setter Property="Foreground" Value="#111111"/>
      <Setter Property="BorderBrush" Value="#111111"/>
      <Setter Property="GridLinesVisibility" Value="Horizontal"/>
      <Setter Property="HorizontalGridLinesBrush" Value="#CCCCCC"/>
      <Setter Property="RowBackground" Value="White"/>
      <Setter Property="AlternatingRowBackground" Value="#FFF8DC"/>
    </Style>
    <Style TargetType="Slider">
      <Setter Property="Foreground" Value="#111111"/>
    </Style>
  </Window.Resources>
  <Grid Margin="16">
    <Grid.RowDefinitions>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="*"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
    </Grid.RowDefinitions>
    <TextBlock Grid.Row="0" Text="SHAPE FLOORS" FontSize="18"
               FontWeight="Bold" Margin="0,0,0,16"/>
    <Grid Grid.Row="1" Margin="0,0,0,10">
      <Grid.ColumnDefinitions>
        <ColumnDefinition Width="200"/>
        <ColumnDefinition Width="*"/>
      </Grid.ColumnDefinitions>
      <TextBlock Text="Reset Existing Shape" VerticalAlignment="Center"/>
      <CheckBox x:Name="chkReset" Grid.Column="1"
                IsChecked="True" VerticalAlignment="Center"/>
    </Grid>
    <Grid Grid.Row="2" Margin="0,0,0,10">
      <Grid.ColumnDefinitions>
        <ColumnDefinition Width="200"/>
        <ColumnDefinition Width="*"/>
      </Grid.ColumnDefinitions>
      <TextBlock Text="Matching Methodology" VerticalAlignment="Center"/>
      <ComboBox x:Name="cmbMethod" Grid.Column="1">
        <ComboBoxItem Content="Top To Top" IsSelected="True"/>
        <ComboBoxItem Content="Bottom To Top"/>
        <ComboBoxItem Content="Submerged Half"/>
      </ComboBox>
    </Grid>
    <Border Grid.Row="3" Background="#E8B800" CornerRadius="4"
            Padding="10,8" Margin="0,0,0,4">
      <Grid>
        <Grid.RowDefinitions>
          <RowDefinition Height="Auto"/>
          <RowDefinition Height="Auto"/>
          <RowDefinition Height="Auto"/>
        </Grid.RowDefinitions>
        <Grid Grid.Row="0">
          <Grid.ColumnDefinitions>
            <ColumnDefinition Width="200"/>
            <ColumnDefinition Width="*"/>
            <ColumnDefinition Width="30"/>
          </Grid.ColumnDefinitions>
          <TextBlock Text="Level of Tessellation" FontWeight="Bold"
                     VerticalAlignment="Center"/>
          <Slider x:Name="sldTess" Grid.Column="1"
                  Minimum="1" Maximum="10" Value="5"
                  TickFrequency="1" IsSnapToTickEnabled="True"
                  VerticalAlignment="Center"/>
          <TextBlock x:Name="lblTessVal" Grid.Column="2"
                     VerticalAlignment="Center" Margin="6,0,0,0"
                     FontWeight="Bold"/>
        </Grid>
        <TextBlock x:Name="lblSpacing" Grid.Row="1"
                   Margin="0,4,0,2" Foreground="#333333"/>
        <StackPanel Grid.Row="2">
          <TextBlock x:Name="lblGreen" Foreground="#1a7a1a"/>
          <TextBlock x:Name="lblBlue"  Foreground="#1a3a9a"/>
          <TextBlock x:Name="lblTotal" FontWeight="Bold" Margin="0,2,0,0"/>
          <TextBlock x:Name="lblWarning" Foreground="#cc0000"
                     FontWeight="Bold" TextWrapping="Wrap"
                     Visibility="Collapsed"/>
        </StackPanel>
      </Grid>
    </Border>
    <Border Grid.Row="4" Background="#FFF8DC" CornerRadius="4"
            Padding="8,4" Margin="0,0,0,10">
      <StackPanel>
        <TextBlock FontSize="10" Foreground="#1a7a1a"
          Text="● Green nodes: boundary edges — always at Level 1 spacing (fixed)"/>
        <TextBlock FontSize="10" Foreground="#1a3a9a"
          Text="● Blue nodes: interior — spacing set by tessellation level"/>
        <TextBlock FontSize="10" Foreground="#cc0000"
          Text="⚠ Safe limit: 2000 nodes. Divide large floors if limit exceeded."/>
      </StackPanel>
    </Border>
    <TextBlock Grid.Row="5" Text="OFFSET PER FAMILY TYPE (metres)"
               FontWeight="Bold" Margin="0,0,0,6" VerticalAlignment="Top"/>
    <DataGrid x:Name="dgFloors" Grid.Row="5"
              AutoGenerateColumns="False" CanUserAddRows="False"
              CanUserDeleteRows="False" HeadersVisibility="Column"
              Margin="0,22,0,12" VerticalAlignment="Stretch">
      <DataGrid.Columns>
        <DataGridTextColumn Header="Family Type" Binding="{Binding FamilyType}"
                            Width="*" IsReadOnly="True"/>
        <DataGridTextColumn Header="Offset (m)" Binding="{Binding Offset}"
                            Width="100"/>
      </DataGrid.Columns>
    </DataGrid>
    <StackPanel Grid.Row="7" Orientation="Horizontal"
                HorizontalAlignment="Right" Margin="0,4,0,0">
      <Button x:Name="btnCancel" Content="Cancel" Margin="0,0,8,0"
              Background="White" Foreground="#111111"/>
      <Button x:Name="btnOk" Content="OK"/>
    </StackPanel>
  </Grid>
</Window>"""

class FloorRow(object):
    def __init__(self, family_type):
        self.FamilyType = family_type
        self.Offset     = "0.00"

class ShapeFloorsDialog(object):
    TESS = TESS_LEVELS

    def __init__(self, floor_types, elements):
        self.result   = None
        self.elements = elements
        self._build(floor_types)

    def _build(self, floor_types):
        from System.Xml import XmlReader
        from System.IO import StringReader
        from System.Windows.Markup import XamlReader
        reader   = XmlReader.Create(StringReader(XAML))
        self.win = XamlReader.Load(reader)

        self.chk_reset = self.win.FindName("chkReset")
        self.cmb       = self.win.FindName("cmbMethod")
        self.sld       = self.win.FindName("sldTess")
        self.lbl_val   = self.win.FindName("lblTessVal")
        self.lbl_sp    = self.win.FindName("lblSpacing")
        self.lbl_green = self.win.FindName("lblGreen")
        self.lbl_blue  = self.win.FindName("lblBlue")
        self.lbl_total = self.win.FindName("lblTotal")
        self.lbl_warn  = self.win.FindName("lblWarning")
        self.dg        = self.win.FindName("dgFloors")
        self.btn_ok    = self.win.FindName("btnOk")
        btn_cancel     = self.win.FindName("btnCancel")

        from System.Collections.ObjectModel import ObservableCollection
        self.items = ObservableCollection[object]()
        for ft in floor_types:
            self.items.Add(FloorRow(ft))
        self.dg.ItemsSource = self.items

        self.sld.ValueChanged += self._on_slider
        self.btn_ok.Click     += self._on_ok
        btn_cancel.Click      += self._on_cancel
        self._update_info(5)

    def _update_info(self, level):
        from System.Windows import Visibility
        hx_mm, hy_mm = self.TESS[level]
        hx_ft = hx_mm * MM_TO_FT
        hy_ft = hy_mm * MM_TO_FT

        self.lbl_val.Text = str(level)
        self.lbl_sp.Text  = "Interior: {}x{}mm  |  Boundary: fixed {}x{}mm".format(
            hx_mm * 2, hy_mm * 2,
            BND_HALF_X_MM * 2, BND_HALF_Y_MM * 2)

        total_g = total_b = total_n = 0
        for elem in self.elements:
            g, b, n = count_nodes_for_element(elem, hx_ft, hy_ft)
            total_g += g
            total_b += b
            total_n += n

        self.lbl_green.Text = "● Green nodes (boundary): ~{}".format(total_g)
        self.lbl_blue.Text  = "● Blue nodes (interior):  ~{}".format(total_b)

        if total_n > SAFE_NODE_LIMIT:
            self.lbl_total.Text = "Total: {} nodes".format(total_n)
            self.lbl_warn.Text  = (
                "⚠ Exceeds safe limit of {} nodes. "
                "This will take time — grab a coffee. "
                "Consider dividing large floors.".format(SAFE_NODE_LIMIT))
            self.lbl_warn.Visibility = Visibility.Visible
        else:
            self.lbl_total.Text      = "Total: {} nodes — Safe to proceed".format(
                total_n)
            self.lbl_warn.Visibility = Visibility.Collapsed

        self.sld.IsEnabled = self.cmb.IsEnabled = self.btn_ok.IsEnabled = True

    def _on_slider(self, s, e):
        self._update_info(int(self.sld.Value))

    def _on_ok(self, s, e):
        offsets = {}
        for item in self.items:
            try:
                val = float(str(item.Offset).strip() or "0")
            except:
                val = 0.0
            offsets[item.FamilyType] = val
        level    = int(self.sld.Value)
        hx_mm, hy_mm = self.TESS[level]
        self.result = {
            "reset":     bool(self.chk_reset.IsChecked),
            "method":    str(self.cmb.Text),
            "offsets":   offsets,
            "half_x_ft": hx_mm * MM_TO_FT,
            "half_y_ft": hy_mm * MM_TO_FT,
            "level":     level,
        }
        self.win.Close()

    def _on_cancel(self, s, e):
        self.result = None
        self.win.Close()

    def show(self):
        self.win.ShowDialog()
        return self.result

class FloorOrTopoFilter(ISelectionFilter):
    def AllowElement(self, e):
        return isinstance(e, Floor) or isinstance(e, Toposolid)
    def AllowReference(self, r, p):
        return False

try:
    view_3d = get_3d_view()
    if view_3d is None:
        forms.alert("No 3D view found.", title="Shape Floors", ok=True)
        script.exit()

    forms.alert("Select the SOURCE Floor or Toposolid (grading surface).",
                title="Shape Floors", ok=True)
    try:
        src_ref  = uidoc.Selection.PickObject(
            ObjectType.Element, FloorOrTopoFilter(), "Select source")
        src_elem = doc.GetElement(src_ref.ElementId)
    except:
        script.exit()

    forms.alert("Now select TARGET floors/toposolids to shape.\nHold Ctrl for multiple.",
                title="Shape Floors", ok=True)
    try:
        target_refs  = uidoc.Selection.PickObjects(
            ObjectType.Element, FloorOrTopoFilter(), "Select targets")
        target_elems = [doc.GetElement(r.ElementId) for r in target_refs
                        if r.ElementId != src_ref.ElementId]
    except:
        script.exit()

    if not target_elems:
        forms.alert("No elements selected.", ok=True)
        script.exit()

    intersector = ReferenceIntersector(
        src_elem.Id, FindReferenceTarget.Face, view_3d)
    intersector.FindReferencesInRevitLinks = False

    src_bb   = src_elem.get_BoundingBox(None)
    search_z = src_bb.Max.Z + 10.0 if src_bb else 100.0

    not_flat = [e for e in target_elems if is_floor(e) and not is_flat(e)]
    if not_flat:
        names    = "\n".join([get_family_type_name(e) for e in not_flat])
        response = forms.alert(
            "{} floor(s) already shaped:\n{}\n\nFlatten before shaping?".format(
                len(not_flat), names),
            title="Shape Floors", yes=True, no=True)
        if response:
            with Transaction(doc, "TLA - Flatten") as t:
                t.Start()
                for e in not_flat:
                    flatten_element(e)
                t.Commit()
        else:
            target_elems = [e for e in target_elems if e not in not_flat]
            if not target_elems:
                forms.alert("No elements remaining.", ok=True)
                script.exit()

    type_map = {}
    for e in target_elems:
        ft = get_family_type_name(e)
        if ft not in type_map:
            type_map[ft] = []
        type_map[ft].append(e)

    dlg    = ShapeFloorsDialog(sorted(type_map.keys()), target_elems)
    result = dlg.show()
    if result is None:
        script.exit()

    half_x_ft = result["half_x_ft"]
    half_y_ft = result["half_y_ft"]

    log_lines = [
        "Shape Floors Log",
        "Tessellation Level: {}".format(result["level"]),
        "Boundary: fixed Level 1 ({}x{}mm)".format(
            BND_HALF_X_MM * 2, BND_HALF_Y_MM * 2),
        "Search Z: {:.3f}ft".format(search_z), ""
    ]

    errors = []
    success = 0
    with Transaction(doc, "TLA Grading - Shape Floors") as t:
        t.Start()
        for ft, elements in type_map.items():
            offset_m = result["offsets"].get(ft, 0.0)
            for elem in elements:
                bb = elem.get_BoundingBox(None)
                cx = (bb.Min.X + bb.Max.X) / 2.0 if bb else 0
                cy = (bb.Min.Y + bb.Max.Y) / 2.0 if bb else 0
                sample_z = get_topo_z(intersector, cx, cy, search_z)
                log_lines.append(
                    "  {} | offset={}m | centre_z={}ft".format(
                        ft, offset_m,
                        "{:.4f}".format(sample_z) if sample_z is not None
                        else "NO HIT"))
                ok, msg = shape_element(
                    elem, intersector, offset_m,
                    result["method"], result["reset"],
                    half_x_ft, half_y_ft, search_z)
                log_lines.append("    -> {}".format(msg))
                if ok:
                    success += 1
                else:
                    errors.append("{}: {}".format(ft, msg))
        t.Commit()

    log_lines.append("\nShaped: {} | Errors: {}".format(success, len(errors)))
    forms.alert("\n".join(log_lines), title="Shape Floors - Done", ok=True)

except Exception:
    forms.alert(traceback.format_exc(), title="ERROR", ok=True)