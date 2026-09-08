# -*- coding: utf-8 -*-
import traceback
import clr
clr.AddReference("PresentationFramework")
clr.AddReference("PresentationCore")
clr.AddReference("WindowsBase")
clr.AddReference("System.Xml")

from pyrevit import forms, script
from Autodesk.Revit.DB import (
    Transaction, XYZ, Floor, Toposolid
)
from Autodesk.Revit.UI.Selection import ObjectType, ISelectionFilter

doc   = __revit__.ActiveUIDocument.Document
uidoc = __revit__.ActiveUIDocument

MM_TO_FT        = 0.00328084
BOUNDARY_TOL_FT = 50.0 * MM_TO_FT


def get_sketch_curves(element):
    curves = []
    try:
        sketch = doc.GetElement(element.SketchId)
        if sketch:
            for curve_arr in sketch.Profile:
                for curve in curve_arr:
                    curves.append(curve)
    except:
        pass
    return curves


def build_boundary_segments(curves):
    SAMPLE_STEP_FT = 50.0 * MM_TO_FT
    segs = []
    for curve in curves:
        try:
            length = curve.Length
            if length < 1e-9:
                continue
            steps = max(1, int(length / SAMPLE_STEP_FT))
            pts = []
            for i in range(steps + 1):
                t  = i / float(steps)
                pt = curve.Evaluate(t, True)
                pts.append((pt.X, pt.Y))
            for i in range(len(pts) - 1):
                segs.append((pts[i], pts[i + 1]))
        except:
            try:
                p0 = curve.GetEndPoint(0)
                p1 = curve.GetEndPoint(1)
                segs.append(((p0.X, p0.Y), (p1.X, p1.Y)))
            except:
                pass
    return segs


def dist_point_to_segment_2d(px, py, x1, y1, x2, y2):
    dx = x2 - x1
    dy = y2 - y1
    seg_len_sq = dx * dx + dy * dy
    if seg_len_sq < 1e-18:
        return ((px - x1) ** 2 + (py - y1) ** 2) ** 0.5
    t      = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / seg_len_sq))
    proj_x = x1 + t * dx
    proj_y = y1 + t * dy
    return ((px - proj_x) ** 2 + (py - proj_y) ** 2) ** 0.5


def is_on_boundary(pt_xyz, segments, tol_ft):
    px, py = pt_xyz.X, pt_xyz.Y
    for (x1, y1), (x2, y2) in segments:
        if dist_point_to_segment_2d(px, py, x1, y1, x2, y2) <= tol_ft:
            return True
    return False


def simplify_floor(element, segments):
    sse = element.SlabShapeEditor
    if sse is None:
        return 0, 0
    try:
        verts = list(sse.SlabShapeVertices)
    except:
        return 0, 0
    to_remove = []
    kept      = 0
    for v in verts:
        try:
            pt = v.Position
            if is_on_boundary(pt, segments, BOUNDARY_TOL_FT):
                kept += 1
            else:
                to_remove.append(v)
        except:
            kept += 1
    for v in to_remove:
        try:
            sse.RemovePoint(v)
        except:
            pass
    return len(to_remove), kept


def simplify_toposolid(element, segments):
    try:
        pts = list(element.GetPoints())
    except:
        return 0, 0
    to_remove = []
    kept      = 0
    for pt in pts:
        if is_on_boundary(pt, segments, BOUNDARY_TOL_FT):
            kept += 1
        else:
            to_remove.append(pt)
    if to_remove:
        try:
            element.DeletePoints(to_remove)
        except:
            pass
    return len(to_remove), kept


def simplify_element(element):
    curves = get_sketch_curves(element)
    if not curves:
        return 0, 0
    segments = build_boundary_segments(curves)
    if not segments:
        return 0, 0
    if isinstance(element, Toposolid):
        return simplify_toposolid(element, segments)
    else:
        return simplify_floor(element, segments)


XAML = """<Window
    xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
    xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
    Title="Simplify Grading" Height="220" Width="420"
    WindowStartupLocation="CenterScreen"
    Background="#F5C842" ResizeMode="NoResize">
  <Window.Resources>
    <Style TargetType="TextBlock">
      <Setter Property="Foreground" Value="#111111"/>
      <Setter Property="FontFamily" Value="Segoe UI"/>
      <Setter Property="FontSize" Value="12"/>
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
  </Window.Resources>
  <Grid Margin="16">
    <Grid.RowDefinitions>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="Auto"/>
      <RowDefinition Height="*"/>
      <RowDefinition Height="Auto"/>
    </Grid.RowDefinitions>
    <TextBlock Grid.Row="0" Text="SIMPLIFY GRADING" FontSize="18"
               FontWeight="Bold" Margin="0,0,0,16"/>
    <TextBlock Grid.Row="1" TextWrapping="Wrap" Margin="0,0,0,12"
               Text="Removes all interior ShapeFloors points. Only points within 50mm of the sketch boundary edge are kept."/>
    <StackPanel Grid.Row="3" Orientation="Horizontal" HorizontalAlignment="Right">
      <Button x:Name="btnCancel" Content="Cancel" Margin="0,0,8,0"
              Background="White" Foreground="#111111"/>
      <Button x:Name="btnOk" Content="OK"/>
    </StackPanel>
  </Grid>
</Window>"""


class SimplifyDialog(object):
    def __init__(self):
        self.result = None
        self._build()

    def _build(self):
        from System.Xml import XmlReader
        from System.IO import StringReader
        from System.Windows.Markup import XamlReader
        reader   = XmlReader.Create(StringReader(XAML))
        self.win = XamlReader.Load(reader)
        btn_ok     = self.win.FindName("btnOk")
        btn_cancel = self.win.FindName("btnCancel")
        btn_ok.Click     += self._on_ok
        btn_cancel.Click += self._on_cancel

    def _on_ok(self, s, e):
        self.result = True
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
    forms.alert("Select floors/toposolids to simplify.\nHold Ctrl for multiple.",
                title="Simplify Grading", ok=True)
    try:
        target_refs  = uidoc.Selection.PickObjects(ObjectType.Element,
                                                   FloorOrTopoFilter(),
                                                   "Select elements to simplify")
        target_elems = [doc.GetElement(r.ElementId) for r in target_refs]
    except:
        script.exit()

    if not target_elems:
        forms.alert("No elements selected.", ok=True)
        script.exit()

    dlg = SimplifyDialog()
    if dlg.show() is None:
        script.exit()

    log_lines = [
        "Simplify Grading Log",
        "Boundary tolerance: 50mm",
        ""
    ]
    total_removed = 0
    total_kept    = 0

    with Transaction(doc, "TLA Grading - Simplify") as t:
        t.Start()
        for elem in target_elems:
            try:
                removed, kept = simplify_element(elem)
                total_removed += removed
                total_kept    += kept
                etype = "Toposolid" if isinstance(elem, Toposolid) else "Floor"
                log_lines.append("  Element {} ({}): removed={} kept={} | OK".format(
                    elem.Id.IntegerValue, etype, removed, kept))
            except Exception:
                log_lines.append("  Element {}: ERROR\n{}".format(
                    elem.Id.IntegerValue, traceback.format_exc()))
        t.Commit()

    log_lines.append("\nTotal removed: {} | Total kept: {}".format(
        total_removed, total_kept))
    forms.alert("\n".join(log_lines), title="Simplify Grading - Done", ok=True)

except Exception:
    forms.alert(traceback.format_exc(), title="ERROR", ok=True)
