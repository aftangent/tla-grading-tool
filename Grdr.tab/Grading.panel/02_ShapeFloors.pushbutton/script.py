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
    BuiltInParameter, Options,
    ReferenceIntersector, FindReferenceTarget,
    View3D
)
from Autodesk.Revit.UI.Selection import ObjectType, ISelectionFilter

doc   = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument
M_TO_FT = 3.28084

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
        fam = etype.get_Parameter(BuiltInParameter.SYMBOL_FAMILY_NAME_PARAM).AsString()
        typ = etype.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM).AsString()
        return "{}: {}".format(fam, typ)
    except:
        return "Unknown"

def is_flat(element):
    try:
        sse = element.SlabShapeEditor
        if sse is None:
            return True
        return sse.SlabShapeCreaseArray.Size == 0
    except:
        return True

def flatten_element(element):
    try:
        sse = element.SlabShapeEditor
        if sse is not None:
            sse.ResetSlabShape()
    except:
        pass

def get_topo_z(intersector, x, y, search_z):
    """Shoot ray down from search_z, return Z of TOP face (first hit = highest Z)."""
    try:
        results = intersector.Find(XYZ(x, y, search_z), XYZ(0, 0, -1))
        if results and results.Count > 0:
            # FIRST hit is the top surface face (closest to ray origin = topmost)
            first = results[0]
            return search_z - first.Proximity
    except:
        pass
    return None

def shape_element(element, intersector, offset_m, match_method,
                  reset_first, grid_steps, search_z):
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

        steps  = max(2, grid_steps)
        x_vals = [bb.Min.X + (bb.Max.X - bb.Min.X) * i / float(steps - 1)
                  for i in range(steps)]
        y_vals = [bb.Min.Y + (bb.Max.Y - bb.Min.Y) * i / float(steps - 1)
                  for i in range(steps)]

        placed  = 0
        skipped = 0
        for x in x_vals:
            for y in y_vals:
                topo_z = get_topo_z(intersector, x, y, search_z)
                if topo_z is None:
                    skipped += 1
                    continue
                if match_method == "Submerged Half":
                    z = topo_z - offset_ft / 2.0
                else:
                    z = topo_z + offset_ft
                try:
                    sse.DrawPoint(XYZ(x, y, z))
                    placed += 1
                except:
                    skipped += 1

        if placed == 0:
            return False, "No points placed - floor may be outside Toposolid"
        return True, "Placed:{} Skipped:{}".format(placed, skipped)
    except Exception:
        return False, traceback.format_exc()

XAML = """<Window
    xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
    xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
    Title="Shape Floors" Height="540" Width="520"
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
      <RowDefinition Height="*"/>
      <RowDefinition Height="Auto"/>
    </Grid.RowDefinitions>
    <TextBlock Grid.Row="0" Text="SHAPE FLOORS" FontSize="18"
               FontWeight="Bold" Margin="0,0,0,16"/>
    <Grid Grid.Row="1" Margin="0,0,0,12">
      <Grid.ColumnDefinitions>
        <ColumnDefinition Width="180"/>
        <ColumnDefinition Width="*"/>
        <ColumnDefinition Width="30"/>
      </Grid.ColumnDefinitions>
      <Grid.RowDefinitions>
        <RowDefinition Height="Auto"/>
        <RowDefinition Height="Auto"/>
      </Grid.RowDefinitions>
      <TextBlock Grid.Row="0" Grid.Column="0" Text="Reset Existing Shape"
                 VerticalAlignment="Center" Margin="0,0,0,8"/>
      <CheckBox x:Name="chkReset" Grid.Row="0" Grid.Column="1"
                IsChecked="True" VerticalAlignment="Center" Margin="0,0,0,8"/>
      <TextBlock Grid.Row="1" Grid.Column="0" Text="Grid Density"
                 VerticalAlignment="Center"/>
      <Slider x:Name="sldAccuracy" Grid.Row="1" Grid.Column="1"
              Minimum="2" Maximum="20" Value="5"
              TickFrequency="1" IsSnapToTickEnabled="True"
              VerticalAlignment="Center"/>
      <TextBlock x:Name="lblAccuracy" Grid.Row="1" Grid.Column="2"
                 VerticalAlignment="Center" Margin="6,0,0,0"/>
    </Grid>
    <Grid Grid.Row="2" Margin="0,0,0,12">
      <Grid.ColumnDefinitions>
        <ColumnDefinition Width="180"/>
        <ColumnDefinition Width="*"/>
      </Grid.ColumnDefinitions>
      <TextBlock Text="Matching Methodology" VerticalAlignment="Center"/>
      <ComboBox x:Name="cmbMethod" Grid.Column="1">
        <ComboBoxItem Content="Top To Top" IsSelected="True"/>
        <ComboBoxItem Content="Bottom To Top"/>
        <ComboBoxItem Content="Submerged Half"/>
      </ComboBox>
    </Grid>
    <TextBlock Grid.Row="3" Text="OFFSET PER FAMILY TYPE (metres)"
               FontWeight="Bold" Margin="0,0,0,6"/>
    <DataGrid x:Name="dgFloors" Grid.Row="4"
              AutoGenerateColumns="False" CanUserAddRows="False"
              CanUserDeleteRows="False" HeadersVisibility="Column"
              Margin="0,0,0,12">
      <DataGrid.Columns>
        <DataGridTextColumn Header="Family Type" Binding="{Binding FamilyType}"
                            Width="*" IsReadOnly="True"/>
        <DataGridTextColumn Header="Offset (m)" Binding="{Binding Offset}"
                            Width="100"/>
      </DataGrid.Columns>
    </DataGrid>
    <StackPanel Grid.Row="5" Orientation="Horizontal" HorizontalAlignment="Right">
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
    def __init__(self, floor_types):
        self.result = None
        self._build(floor_types)

    def _build(self, floor_types):
        from System.Xml import XmlReader
        from System.IO import StringReader
        from System.Windows.Markup import XamlReader
        reader   = XmlReader.Create(StringReader(XAML))
        self.win = XamlReader.Load(reader)

        self.chk_reset = self.win.FindName("chkReset")
        self.sld       = self.win.FindName("sldAccuracy")
        self.lbl_acc   = self.win.FindName("lblAccuracy")
        self.cmb       = self.win.FindName("cmbMethod")
        self.dg        = self.win.FindName("dgFloors")
        btn_ok         = self.win.FindName("btnOk")
        btn_cancel     = self.win.FindName("btnCancel")

        self.lbl_acc.Text = "5"
        self.sld.ValueChanged += self._on_slider

        from System.Collections.ObjectModel import ObservableCollection
        self.items = ObservableCollection[object]()
        for ft in floor_types:
            self.items.Add(FloorRow(ft))
        self.dg.ItemsSource = self.items

        btn_ok.Click     += self._on_ok
        btn_cancel.Click += self._on_cancel

    def _on_slider(self, s, e):
        self.lbl_acc.Text = str(int(self.sld.Value))

    def _on_ok(self, s, e):
        offsets = {}
        for item in self.items:
            try:
                val = float(str(item.Offset).strip() or "0")
            except:
                val = 0.0
            offsets[item.FamilyType] = val
        self.result = {
            "reset":    bool(self.chk_reset.IsChecked),
            "accuracy": int(self.sld.Value),
            "method":   str(self.cmb.Text),
            "offsets":  offsets
        }
        self.win.Close()

    def _on_cancel(self, s, e):
        self.result = None
        self.win.Close()

    def show(self):
        self.win.ShowDialog()
        return self.result

class ToposolidFilter(ISelectionFilter):
    def AllowElement(self, e):
        return isinstance(e, Toposolid)
    def AllowReference(self, r, p):
        return False

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

    forms.alert("Select the SOURCE Toposolid (grading surface).",
                title="Shape Floors", ok=True)
    try:
        topo_ref  = uidoc.Selection.PickObject(ObjectType.Element,
                                               ToposolidFilter(),
                                               "Select source Toposolid")
        topo_elem = doc.GetElement(topo_ref.ElementId)
    except:
        script.exit()

    forms.alert("Now select TARGET floors to shape.\nHold Ctrl for multiple.",
                title="Shape Floors", ok=True)
    try:
        target_refs  = uidoc.Selection.PickObjects(ObjectType.Element,
                                                   FloorOrTopoFilter(),
                                                   "Select target floors")
        target_elems = [doc.GetElement(r.ElementId) for r in target_refs]
    except:
        script.exit()

    if not target_elems:
        forms.alert("No elements selected.", ok=True)
        script.exit()

    intersector = ReferenceIntersector(
        topo_elem.Id, FindReferenceTarget.Face, view_3d)
    intersector.FindReferencesInRevitLinks = False

    topo_bb  = topo_elem.get_BoundingBox(None)
    search_z = topo_bb.Max.Z + 10.0 if topo_bb else 100.0

    not_flat = [e for e in target_elems if not is_flat(e)]
    if not_flat:
        names    = "\n".join([get_family_type_name(e) for e in not_flat])
        response = forms.alert(
            "{} element(s) already shaped:\n{}\n\nFlatten before shaping?".format(
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
                forms.alert("No flat elements remaining.", ok=True)
                script.exit()

    type_map = {}
    for e in target_elems:
        ft = get_family_type_name(e)
        if ft not in type_map:
            type_map[ft] = []
        type_map[ft].append(e)

    dlg    = ShapeFloorsDialog(sorted(type_map.keys()))
    result = dlg.show()
    if result is None:
        script.exit()

    grid_steps = result["accuracy"]
    log_lines  = [
        "Shape Floors Log",
        "Method: ReferenceIntersector (first hit = top face)",
        "Search Z: {:.3f}ft".format(search_z),
        "Grid density: {}x{}".format(grid_steps, grid_steps),
        ""
    ]

    errors  = []
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
                        "{:.4f}".format(sample_z) if sample_z is not None else "NO HIT"))
                ok, msg = shape_element(
                    elem, intersector, offset_m,
                    result["method"], result["reset"],
                    grid_steps, search_z)
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