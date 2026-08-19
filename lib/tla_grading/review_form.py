import clr
clr.AddReference("PresentationFramework")
clr.AddReference("PresentationCore")
clr.AddReference("WindowsBase")
clr.AddReference("System")

from System.Collections.ObjectModel import ObservableCollection
from System.ComponentModel import INotifyPropertyChanged, PropertyChangedEventArgs
from System.Windows import Window, WindowStartupLocation, Thickness, HorizontalAlignment, GridLength, GridUnitType
from System.Windows.Controls import Grid, RowDefinition, DataGrid, DataGridTextColumn, DataGridCheckBoxColumn, Button, StackPanel, Label, Orientation, DataGridSelectionMode
from System.Windows.Data import Binding, BindingMode, UpdateSourceTrigger
from System.Windows.Media import SolidColorBrush, Color
import System.Windows.Controls as WpfControls
import System

class PointRow(INotifyPropertyChanged):
    def __init__(self, number, raw, prefix, elevation, x, y, include=True):
        self._number = number
        self._raw = raw
        self._prefix = prefix
        self._elevation = float(elevation)
        self._x = float(x)
        self._y = float(y)
        self._include = include
        self._handlers = []

    def add_PropertyChanged(self, handler):
        self._handlers.append(handler)

    def remove_PropertyChanged(self, handler):
        if handler in self._handlers:
            self._handlers.remove(handler)

    def _notify(self, name):
        args = PropertyChangedEventArgs(name)
        for h in self._handlers:
            h(self, args)

    @property
    def Number(self):
        return self._number

    @property
    def RawValue(self):
        return self._raw

    @property
    def Elevation(self):
        return str(self._elevation)

    @Elevation.setter
    def Elevation(self, value):
        try:
            self._elevation = float(str(value))
        except (ValueError, TypeError):
            pass
        self._notify("Elevation")

    @property
    def Position(self):
        return "{:.1f}  //  {:.1f}".format(self._x, self._y)

    @property
    def Include(self):
        return self._include

    @Include.setter
    def Include(self, value):
        self._include = bool(value)
        self._notify("Include")

    def to_dict(self):
        return {"prefix": self._prefix, "value": self._elevation, "raw": self._raw, "x": self._x, "y": self._y, "confidence": "ok"}


def show_review_form(points):
    rows = ObservableCollection[PointRow]()
    for i, pt in enumerate(points):
        rows.Add(PointRow(i+1, pt.get("raw",""), pt.get("prefix",""), pt.get("value",0.0), pt.get("x",0.0), pt.get("y",0.0), True))

    result = {"confirmed": None}

    win = Window()
    win.Title = "TLA Grading - Review Spot Level Points"
    win.Width = 780
    win.Height = 560
    win.WindowStartupLocation = WindowStartupLocation.CenterScreen
    win.Background = SolidColorBrush(Color.FromRgb(245, 245, 245))

    root = Grid()
    r0 = RowDefinition()
    r0.Height = GridLength(1, GridUnitType.Auto)
    r1 = RowDefinition()
    r1.Height = GridLength(1, GridUnitType.Star)
    r2 = RowDefinition()
    r2.Height = GridLength(1, GridUnitType.Auto)
    root.RowDefinitions.Add(r0)
    root.RowDefinitions.Add(r1)
    root.RowDefinitions.Add(r2)
    win.Content = root

    header = Label()
    header.Content = "Review points. Edit elevations, untick to exclude, then click Confirm."
    header.Margin = Thickness(8, 8, 8, 4)
    Grid.SetRow(header, 0)
    root.Children.Add(header)

    dg = DataGrid()
    dg.Margin = Thickness(8, 4, 8, 4)
    dg.AutoGenerateColumns = False
    dg.CanUserAddRows = False
    dg.CanUserDeleteRows = False
    dg.SelectionMode = DataGridSelectionMode.Extended
    dg.ItemsSource = rows
    dg.AlternatingRowBackground = SolidColorBrush(Color.FromRgb(235, 242, 250))
    dg.RowBackground = SolidColorBrush(Color.FromRgb(255, 255, 255))
    dg.FontSize = 12
    Grid.SetRow(dg, 1)
    root.Children.Add(dg)

    col_no = DataGridTextColumn()
    col_no.Header = "No."
    col_no.Binding = Binding("Number")
    col_no.IsReadOnly = True
    col_no.Width = WpfControls.DataGridLength(45)
    dg.Columns.Add(col_no)

    col_raw = DataGridTextColumn()
    col_raw.Header = "Raw Value"
    col_raw.Binding = Binding("RawValue")
    col_raw.IsReadOnly = True
    col_raw.Width = WpfControls.DataGridLength(110)
    dg.Columns.Add(col_raw)

    col_elev = DataGridTextColumn()
    col_elev.Header = "Elevation (m)"
    b = Binding("Elevation")
    b.Mode = BindingMode.TwoWay
    b.UpdateSourceTrigger = UpdateSourceTrigger.LostFocus
    col_elev.Binding = b
    col_elev.Width = WpfControls.DataGridLength(100)
    dg.Columns.Add(col_elev)

    col_pos = DataGridTextColumn()
    col_pos.Header = "X (mm)  //  Y (mm)"
    col_pos.Binding = Binding("Position")
    col_pos.IsReadOnly = True
    col_pos.Width = WpfControls.DataGridLength(1, WpfControls.DataGridLengthUnitType.Star)
    dg.Columns.Add(col_pos)

    col_inc = DataGridCheckBoxColumn()
    col_inc.Header = "Include"
    b2 = Binding("Include")
    b2.Mode = BindingMode.TwoWay
    b2.UpdateSourceTrigger = UpdateSourceTrigger.PropertyChanged
    col_inc.Binding = b2
    col_inc.Width = WpfControls.DataGridLength(65)
    dg.Columns.Add(col_inc)

    btn_panel = StackPanel()
    btn_panel.Orientation = Orientation.Horizontal
    btn_panel.HorizontalAlignment = HorizontalAlignment.Right
    btn_panel.Margin = Thickness(8, 4, 8, 8)
    Grid.SetRow(btn_panel, 2)
    root.Children.Add(btn_panel)

    btn_all = Button()
    btn_all.Content = "Select All"
    btn_all.Width = 90
    btn_all.Margin = Thickness(0, 0, 6, 0)
    btn_panel.Children.Add(btn_all)

    btn_none = Button()
    btn_none.Content = "Deselect All"
    btn_none.Width = 90
    btn_none.Margin = Thickness(0, 0, 6, 0)
    btn_panel.Children.Add(btn_none)

    btn_toggle = Button()
    btn_toggle.Content = "Toggle Selected"
    btn_toggle.Width = 110
    btn_toggle.Margin = Thickness(0, 0, 6, 0)
    btn_panel.Children.Add(btn_toggle)

    btn_cancel = Button()
    btn_cancel.Content = "Cancel"
    btn_cancel.Width = 80
    btn_cancel.Margin = Thickness(0, 0, 6, 0)
    btn_panel.Children.Add(btn_cancel)

    btn_confirm = Button()
    btn_confirm.Content = "Confirm"
    btn_confirm.Width = 90
    btn_confirm.FontWeight = System.Windows.FontWeights.Bold
    btn_panel.Children.Add(btn_confirm)

    def on_select_all(sender, e):
        for row in rows:
            row.Include = True
        dg.Items.Refresh()

    def on_deselect_all(sender, e):
        for row in rows:
            row.Include = False
        dg.Items.Refresh()

    def on_toggle_selected(sender, e):
        selected = list(dg.SelectedItems)
        if not selected:
            return
        included = sum(1 for r in selected if r.Include)
        new_state = included < len(selected)
        for row in selected:
            row.Include = new_state
        dg.Items.Refresh()

    def on_cancel(sender, e):
        result["confirmed"] = None
        win.Close()

    def on_confirm(sender, e):
        dg.CommitEdit(WpfControls.DataGridEditingUnit.Row, True)
        result["confirmed"] = [row.to_dict() for row in rows if row.Include]
        win.Close()

    btn_all.Click += on_select_all
    btn_none.Click += on_deselect_all
    btn_toggle.Click += on_toggle_selected
    btn_cancel.Click += on_cancel
    btn_confirm.Click += on_confirm

    win.ShowDialog()
    return result["confirmed"]
