"""VentForge desktop GUI (PySide6).  python -m ventforge.gui [file.vent.json]"""
from __future__ import annotations

import importlib
import json
import math
import random
import sys
import time
import traceback
from dataclasses import fields, is_dataclass
from pathlib import Path
from typing import get_type_hints

from PySide6.QtCore import QPointF, QRectF, QSettings, QSize, QSizeF, Qt, QThread, QTimer, QFileSystemWatcher, Signal
from PySide6.QtGui import (QAction, QBrush, QColor, QIcon, QKeySequence, QPainter, QPainterPath,
                           QPainterPathStroker, QPalette, QPen, QPixmap, QPolygonF, QTransform)
from PySide6.QtWidgets import (QAbstractSpinBox, QApplication, QButtonGroup, QCheckBox, QColorDialog, QComboBox,
                               QDialog, QDialogButtonBox, QDockWidget, QDoubleSpinBox, QFileDialog, QFormLayout,
                               QGraphicsEllipseItem, QGraphicsItem, QGraphicsPixmapItem, QGraphicsScene,
                               QGraphicsView, QGridLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMainWindow, QMessageBox, QProgressBar, QPushButton, QScrollArea,
                               QSizePolicy, QSlider, QSpinBox, QStackedWidget, QStyle, QTabWidget, QToolButton,
                               QVBoxLayout, QWidget)

from .model import (CHOICES, FANS, GRADS, MODES, SHAPES, Control, Design, DotStyle, Gradient, Keepout,
                    Machining, Pattern, fan_grille)

PRESETS = Path(__file__).resolve().parent / "presets"


def pattern():  # imported lazily so the GUI module loads even while pattern.py is missing
    return importlib.import_module("ventforge.pattern")


def exporter():
    return importlib.import_module("ventforge.export")


# ---------------------------------------------------------------- parameter metadata
META = {  # name: (min, max, step, suffix)
    "count": (1, 20000, 1, ""), "sides": (3, 64, 1, ""), "star_points": (3, 64, 1, ""),
    "target_sides": (3, 64, 1, ""), "layers": (1, 100, 1, ""), "irregularity": (0, 100, 5, " %"),
    "star_inner": (0.05, 0.95, 0.05, ""), "aspect": (0.05, 20, 0.05, ""), "noise": (0, 1, 0.05, ""),
    "opacity": (0, 1, 0.05, ""), "offset_x": (-500, 500, 0.5, " mm"), "offset_y": (-500, 500, 0.5, " mm"),
    "turns": (0.1, 200, 0.5, ""), "spread": (0.1, 50, 0.1, ""), "width": (1, 5000, 1, " mm"),
    "height": (1, 5000, 1, " mm"), "thickness": (0.1, 100, 0.1, " mm"), "diameter": (0.1, 500, 0.1, " mm"),
    "kerf": (0, 2, 0.01, " mm"), "tool_radius": (0, 20, 0.05, " mm"), "min_feature": (0, 20, 0.05, " mm"),
}
MM_WORDS = ("spacing", "radius", "diameter", "distance", "width", "margin", "size", "amplitude",
            "wavelength", "scale", "min_wall")
LABELS = {"rotate_by": "Rotate by", "min_wall": "Min wall", "star_inner": "Star inner ratio",
          "noise_seed": "Noise seed", "edge": "Edge value"}
DOT_VIS = {"circle": (), "hexagon": (), "custom": (), "rounded_rectangle": ("aspect", "corner_radius"),
           "polygon": ("sides",), "star": ("star_points", "star_inner")}
RAND = {"spacing_x": (4, 10), "spacing_y": (4, 10), "row_rotation": (0, 90), "rotation": (0, 90),
        "count": (100, 800), "min_distance": (3, 8), "turns": (2, 10), "ring_spacing": (4, 9),
        "dot_spacing": (4, 9), "spread": (1.5, 4), "left_angle": (30, 80), "right_angle": (100, 150),
        "left_spacing": (4, 10), "right_spacing": (4, 10), "cell_size": (5, 14), "irregularity": (0, 100),
        "crack_width": (0.8, 2.5), "line_spacing": (3, 8), "line_width": (1, 3), "amplitude": (0, 8),
        "wavelength": (10, 60), "seed": (1, 9999), "layer_spacing": (3, 8), "layers": (1, 4)}
CTRL_VALUE = {"size": 0.3, "spacing": 2.0, "angle": 45.0, "shape": 1.0}
# Slider ("comfortable") ranges; the number box still accepts anything inside META's hard range.
# Tuned with a sweep of pattern.generate over each slider (non-empty, <5% min-wall overlaps, <250 ms, visible
# change) on the 100 mm default canvas. Full-path entries win over the name-based SOFT fallback.
SOFT_PATH = {
    "canvas.width": (10, 500), "canvas.height": (10, 500), "canvas.thickness": (0.5, 10),
    "boundary.corner_radius": (0, 50), "dot.diameter": (0.3, 20), "dot.corner_radius": (0, 3),
    "pattern.grid.offset_x": (-10, 10), "pattern.grid.offset_y": (-10, 10), "pattern.grid.rotation": (-90, 90),
    "pattern.random.count": (5, 1000),
    "pattern.path.count": (3, 80), "pattern.path.layer_spacing": (2.5, 30),
    "pattern.spiral.radius": (5, 100), "pattern.spiral.turns": (1, 20), "pattern.spiral.inner_radius": (0, 40),
    "pattern.spiral.count": (10, 500),
    "pattern.concentric.inner_radius": (0, 60), "pattern.concentric.outer_radius": (0, 70),
    "pattern.fibonacci.count": (10, 700), "pattern.fibonacci.spread": (1, 10),
    "pattern.fibonacci.inner_radius": (0, 40), "pattern.crosslines.rotation": (-90, 90),
    "pattern.voronoi.corner_radius": (0, 5), "boundary.vent_diameter": (0, 300),
    "machining.kerf": (0, 0.5), "machining.tool_radius": (0, 3), "machining.min_feature": (0, 3), "pattern.flowlines.line_spacing": (2, 30),
}
SOFT = {"diameter": (0.3, 20), "thickness": (0.5, 10), "margin": (0, 20), "corner_radius": (0, 20),
        "aspect": (0.2, 5), "sides": (3, 12), "star_points": (3, 12), "star_inner": (0.1, 0.9),
        "target_sides": (3, 12), "count": (10, 1000), "layers": (1, 10), "turns": (1, 20), "spread": (1, 10),
        "irregularity": (0, 100), "noise": (0, 1), "opacity": (0, 1), "radius": (5, 150), "inner_radius": (0, 40),
        "outer_radius": (0, 80), "amplitude": (0, 10), "wavelength": (10, 200), "noise_scale": (2, 100),
        "min_wall": (0.2, 3), "cell_size": (2.5, 40), "crack_width": (0.4, 6), "line_width": (0.3, 10),
        "spacing_x": (2.5, 40), "spacing_y": (2.5, 40), "ring_spacing": (2.5, 40), "dot_spacing": (2.5, 40),
        "left_spacing": (2.5, 40), "right_spacing": (2.5, 40), "min_distance": (2.5, 40),
        "offset_x": (-20, 20), "offset_y": (-20, 20), "rotation": (-180, 180), "row_rotation": (0, 180),
        "left_angle": (0, 180), "right_angle": (0, 180), "seed": (1, 9999), "noise_seed": (1, 9999)}
GRAD_SOFT = {"size": (0, 2), "spacing": (0.3, 3), "angle": (-180, 180), "shape": (0, 1)}
GRAD_HARD = {"size": (0, 20), "spacing": (0, 20), "angle": (-360, 360), "shape": (0, 1)}
# Sliders mapped logarithmically (positive ranges spanning >~1 decade): finer control at small values.
LOG = {"canvas.width", "canvas.height", "canvas.thickness", "diameter", "aspect", "count", "spread", "cell_size",
       "crack_width", "line_width", "wavelength", "noise_scale", "spacing_x", "spacing_y", "ring_spacing",
       "dot_spacing", "left_spacing", "right_spacing", "min_distance", "layer_spacing", "line_spacing",
       "gradients.spacing.edge", "gradients.spacing.value", "gradients.spacing.image_min",
       "gradients.spacing.image_max", *(f"gradients.{g}.radius" for g in GRADS)}
# Ranges that follow the canvas: soft range * (sqrt(w*h) / 100 mm) ** exponent (counts fill an area or a path).
SCALE = {"boundary.corner_radius": 1, "pattern.random.count": 2, "pattern.path.count": 1,
         "pattern.spiral.radius": 1, "pattern.spiral.inner_radius": 1, "pattern.spiral.count": 2,
         "pattern.concentric.inner_radius": 1, "pattern.concentric.outer_radius": 1,
         "pattern.fibonacci.count": 2, "pattern.fibonacci.inner_radius": 1,
         **{f"gradients.{g}.radius": 1 for g in GRADS}}
ADVANCED = {"offset_x", "offset_y", "row_rotation", "rotate_by", "seed", "noise_seed", "noise_scale", "falloff",
            "image_min", "image_max", "invert_image", "closed", "smooth", "even_spacing", "layer_spacing",
            "stagger", "outer_radius", "inner_radius", "clip", "edge_style", "follow_boundary", "amplitude",
            "wavelength", "thickness"}
LABELS.update({"diameter": "Hole size", "spacing_x": "Spacing", "spacing_y": "Row spacing", "edge": "Far value",
               "count": "Number of holes", "line_width": "Slot width", "line_spacing": "Slot spacing",
               "cell_size": "Cell size", "crack_width": "Wall width", "noise": "Randomness",
               "enabled": "On", "type": "Shape", "star_inner": "Star depth", "aspect": "Stretch"})


def soft_range(path, name, lo, hi, canvas=None):
    g = path.split(".")[1] if path.startswith("gradients.") and path.count(".") == 2 else None
    if path in SOFT_PATH:
        a, b = SOFT_PATH[path]
    elif g in GRAD_SOFT and name in ("edge", "image_min", "image_max", "value"):
        a, b = GRAD_SOFT[g]
    elif name in SOFT:
        a, b = SOFT[name]
    elif any(w in name for w in MM_WORDS):
        a, b = (1, 30)
    else:
        a, b = (max(lo, -10), min(hi, 10))
    if canvas is not None and path in SCALE:
        k = (max(canvas.width * canvas.height, 1.0) ** 0.5 / 100) ** SCALE[path]
        a, b = a * k, b * k
    return max(lo, a), min(hi, b)


def is_log(path, name):
    return path in LOG or name in LOG


def meta(name, t, path=""):
    g = path.split(".")[1] if path.startswith("gradients.") and path.count(".") == 2 else None
    if g in GRAD_HARD and name in ("edge", "image_min", "image_max", "value"):
        return (*GRAD_HARD[g], 0.01 if g != "angle" else 1, " °" if g == "angle" else "")
    if name in META:
        return META[name]
    if t is int:
        return (0, 999999, 1, "")
    if "rotation" in name or "angle" in name:
        return (-360, 360, 1, " °")
    if name in ("wavelength", "noise_scale"):  # tiny values freeze the generator (fine sampling)
        return (2 if name == "wavelength" else 0.5, 2000, 0.5, " mm")
    if name != "layer_spacing" and ("spacing" in name or name in ("min_distance", "cell_size")):
        return (1, 2000, 0.1, " mm")  # below ~1 mm the hole count explodes (seconds per regenerate)
    if name == "min_wall":
        return (0, 20, 0.1, " mm")
    if any(w in name for w in MM_WORDS):
        return (0, 2000, 0.1, " mm")
    return (-1000, 1000, 0.05, "")


def slider_field(path, name, t, canvas=None):
    lo, hi, step, suf = meta(name, t, path)
    w = SliderField(lo, hi, step, suf, soft_range(path, name, lo, hi, canvas), t is int, is_log(path, name))
    w.path, w.name = path, name  # lets the window rescale canvas-relative ranges
    return w


def label_for(name):
    return LABELS.get(name, name.replace("_", " ").capitalize())


def getp(obj, path):
    for k in path.split("."):
        obj = obj[int(k)] if k.isdigit() else getattr(obj, k)
    return obj


def setp(obj, path, v):
    head, _, k = path.rpartition(".")
    o = getp(obj, head) if head else obj
    if k.isdigit():
        o[int(k)] = v
    else:
        setattr(o, k, v)


def clone(d: Design) -> Design:
    return Design.from_dict(json.loads(d.to_json()))


# ---------------------------------------------------------------- geometry -> Qt
def S(x, y):  # model (y up) -> scene (y down)
    return QPointF(x, -y)


def _add_geom(path, g):
    for p in getattr(g, "geoms", [g]):
        if p.is_empty or not hasattr(p, "exterior"):
            continue
        for ring in (p.exterior, *p.interiors):
            path.addPolygon(QPolygonF([QPointF(x, -y) for x, y in ring.coords]))
            path.closeSubpath()


def add_keepout_path(path, k):
    if k.shape == "rectangle":
        path.addRect(QRectF(S(k.x - k.width / 2, k.y + k.height / 2), QSizeF(k.width, k.height)))
    else:
        path.addEllipse(S(k.x, k.y), k.width / 2, k.width / 2)


def result_paths(r):
    holes = QPainterPath()
    holes.setFillRule(Qt.OddEvenFill)
    circles = r.circles if len(r.circles) == len(r.holes) else [None] * len(r.holes)
    for h, c in zip(r.holes, circles):
        if c:
            holes.addEllipse(S(c[0], c[1]), c[2], c[2])
        else:
            _add_geom(holes, h)
    outline = QPainterPath()
    outline.setFillRule(Qt.OddEvenFill)
    _add_geom(outline, r.outline)
    return holes, outline


def build(d: Design):
    t0 = time.perf_counter()
    r = pattern().generate(d)
    holes, outline = result_paths(r)
    return r, holes, outline, time.perf_counter() - t0


def paint_thumb(holes, outline, color, size=88):
    pm = QPixmap(size, size)
    pm.fill(QColor(40, 42, 46))
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    b = outline.boundingRect()
    if b.width() > 0 and b.height() > 0:
        k = (size - 8) / max(b.width(), b.height())
        p.translate(size / 2, size / 2)
        p.scale(k, k)
        p.translate(-b.center())
        p.fillPath(outline, QColor(70, 72, 80))
        p.fillPath(holes, QColor(color))
    p.end()
    return QIcon(pm)


_ICONS = {}


def choice_icons(path):
    """Picture tiles for the pattern-mode and hole-shape pickers, rendered with the real generator."""
    if path not in ("pattern.mode", "dot.shape"):
        return None
    if path not in _ICONS:
        icons = {}
        try:
            opts = MODES if path == "pattern.mode" else SHAPES
            for v in opts:
                d = Design()
                d.canvas.width = d.canvas.height = 60
                d.boundary.margin = 1
                if path == "pattern.mode":
                    d.pattern.mode, d.dot.diameter = v, 3.2
                    d.pattern.random.count, d.pattern.spiral.radius, d.pattern.spiral.count = 60, 28, 90
                    d.pattern.fibonacci.count, d.pattern.voronoi.cell_size = 110, 9
                    d.pattern.custom_points.points = [[math.cos(a) * 18, math.sin(a) * 18]
                                                      for a in (i * math.pi / 4 for i in range(8))] + [[0, 0]]
                    d.pattern.custom_points.sizes = [1.5] * 8 + [4]
                else:
                    d.dot.shape, d.dot.diameter, d.dot.sides = v, 44, 5
                    d.dot.custom_points = [[0, 1], [0.3, 0.2], [1, 0], [0.3, -0.2], [0, -1], [-0.3, -0.2],
                                           [-1, 0], [-0.3, 0.2]]
                    d.pattern.mode, d.pattern.custom_points.points = "custom_points", [[0, 0]]
                icons[v] = paint_thumb(*result_paths(pattern().generate(d)), "#2E7D4F", size=64)
        except Exception:
            traceback.print_exc()
            icons = {}
        _ICONS[path] = icons
    return _ICONS[path]


def catmull(pts):
    """Smooth path through scene points (Catmull-Rom as cubic Beziers)."""
    path = QPainterPath(pts[0])
    if len(pts) < 3:
        for q in pts[1:]:
            path.lineTo(q)
        return path
    ext = [pts[0], *pts, pts[-1]]
    for i in range(1, len(ext) - 2):
        p0, p1, p2, p3 = ext[i - 1:i + 3]
        path.cubicTo(p1 + (p2 - p0) / 6, p2 - (p3 - p1) / 6, p2)
    return path


# ---------------------------------------------------------------- helpers widgets
class Task(QThread):
    done = Signal(object)

    def __init__(self, fn, cb):
        super().__init__()
        self.fn, self.cb, self.value, self.error = fn, cb, None, None

    def run(self):
        try:
            self.value = self.fn()
        except Exception:
            self.error = traceback.format_exc()
        self.done.emit(self)


class Section(QWidget):
    """Collapsible group: clickable header + body."""

    def __init__(self, title, body, open_=True, small=False):
        super().__init__()
        btn = QToolButton(text=title, checkable=True, checked=open_)
        btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        btn.setProperty("section", "small" if small else "big")
        btn.setSizePolicy(btn.sizePolicy().Policy.Expanding, btn.sizePolicy().Policy.Fixed)
        arrow = lambda on: btn.setArrowType(Qt.DownArrow if on else Qt.RightArrow)
        arrow(open_)
        body.setVisible(open_)
        btn.toggled.connect(lambda on: (body.setVisible(on), arrow(on)))
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(btn)
        lay.addWidget(body)


class DragLabel(QLabel):
    """Form label that scrubs its spin box when dragged horizontally."""

    def __init__(self, text, spin):
        super().__init__(text)
        self.spin, self.x0, self.v0 = spin, None, 0
        if isinstance(spin, (QSpinBox, QDoubleSpinBox)):
            self.setCursor(Qt.SizeHorCursor)
            self.setToolTip("Drag left/right to adjust")

    def mousePressEvent(self, e):
        if isinstance(self.spin, (QSpinBox, QDoubleSpinBox)):
            self.x0, self.v0 = e.position().x(), self.spin.value()

    def mouseMoveEvent(self, e):
        if self.x0 is not None:
            steps = round((e.position().x() - self.x0) / 4)
            self.spin.setValue(type(self.v0)(self.v0 + steps * self.spin.singleStep()))

    def mouseReleaseEvent(self, e):
        self.x0 = None


def row(*ws):
    w = QWidget()
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 0, 0, 0)
    for x in ws:
        h.addWidget(x)
    return w


def button(text, slot, tip=""):
    b = QPushButton(text)
    b.clicked.connect(slot)
    b.setToolTip(tip)
    return b


class WheelSafeSlider(QSlider):
    def wheelEvent(self, e):  # scrolling the panel must not change values the mouse happens to pass over
        if self.hasFocus():
            super().wheelEvent(e)
        else:
            e.ignore()


class SliderField(QWidget):
    """Slider over a comfortable range + a small number box for exact / out-of-range values."""
    valueChanged = Signal(object)
    N = 1000

    def __init__(self, lo, hi, step, suffix, soft, is_int, log=False):
        super().__init__()
        self.step, self.is_int, (self.a, self.b) = step, is_int, soft
        self.log_wanted, self.log = log, log and 0 < self.a < self.b  # log needs a positive range
        self.sl = WheelSafeSlider(Qt.Horizontal)
        self.sl.setRange(0, self.N)
        self.sl.setFocusPolicy(Qt.StrongFocus)
        self.sp = QSpinBox() if is_int else QDoubleSpinBox(decimals=3 if step < 0.1 else 2)
        self.sp.setRange(lo, hi)
        self.sp.setSingleStep(step)
        self.sp.setSuffix(suffix)
        self.sp.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.sp.setKeyboardTracking(False)
        self.sp.setFixedWidth(80)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.sl, 1)
        lay.addWidget(self.sp)
        self.sl.valueChanged.connect(self._from_slider)
        self.sp.valueChanged.connect(self._from_spin)

    def _pos(self, v):
        if self.log:
            t = math.log(max(v, self.a) / self.a) / math.log(self.b / self.a)
        else:
            t = (v - self.a) / ((self.b - self.a) or 1)
        return round(min(1, max(0, t)) * self.N)

    def _from_slider(self, i):
        t = i / self.N
        v = self.a * (self.b / self.a) ** t if self.log else self.a + t * (self.b - self.a)
        if self.is_int:
            v = round(v)
        elif self.log:  # ~3 significant digits, never coarser than the spin step
            v = round(v, max(0, 2 - math.floor(math.log10(v)), -math.floor(math.log10(self.step))))
        else:
            v = round(round(v / self.step) * self.step, 4)
        self.sp.blockSignals(True)
        self.sp.setValue(v)
        self.sp.blockSignals(False)
        self.valueChanged.emit(self.sp.value())

    def _from_spin(self, v):
        self.sl.blockSignals(True)
        self.sl.setValue(self._pos(v))
        self.sl.blockSignals(False)
        self.valueChanged.emit(v)

    def value(self):
        return self.sp.value()

    def setValue(self, v):
        self.sp.setValue(v)
        self._from_spin(self.sp.value())  # keeps the slider in sync even when the value did not change

    def set_soft(self, soft):
        self.a, self.b = soft
        self.log = self.log_wanted and 0 < self.a < self.b
        self.sl.blockSignals(True)
        self.sl.setValue(self._pos(self.sp.value()))
        self.sl.blockSignals(False)


class Picker(QWidget):
    """Exclusive button choice: picture tiles (icons given) or a segmented text bar."""
    valueChanged = Signal(object)

    def __init__(self, options, cols=None, icon=56):
        super().__init__()
        self.group, self.btns = QButtonGroup(self), {}
        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(4)
        cols = cols or len(options)
        for i, (val, text, ic) in enumerate(options):
            b = QToolButton(text=text, checkable=True)
            b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            if ic is not None:
                b.setIcon(ic)
                b.setIconSize(QSize(icon, icon))
                b.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
                b.setProperty("tile", True)
            else:
                b.setProperty("seg", True)
            self.group.addButton(b, i)
            self.btns[val] = b
            grid.addWidget(b, i // cols, i % cols)
        self.vals = [o[0] for o in options]
        self.group.idClicked.connect(lambda i: self.valueChanged.emit(self.vals[i]))

    def value(self):
        return self.vals[max(0, self.group.checkedId())]

    def setValue(self, v):
        if v in self.btns:
            self.btns[v].setChecked(True)


class ZoomBar(QWidget):
    """Floating zoom controls in the canvas corner."""

    def __init__(self, canvas):
        super().__init__(canvas.viewport())
        self.setObjectName("zoombar")
        self.setAttribute(Qt.WA_StyledBackground)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(2)
        self.pct = QLabel("100%")
        self.pct.setAlignment(Qt.AlignCenter)
        self.pct.setFixedWidth(52)
        for text, tip, slot in (("−", "Zoom out (-)", lambda: canvas.zoom_by(1 / 1.25)), (None, "", None),
                                ("+", "Zoom in (+)", lambda: canvas.zoom_by(1.25)),
                                ("Fit", "Fit plate to view (Z or double-click)", canvas.zoom_fit)):
            if text is None:
                lay.addWidget(self.pct)
                continue
            b = QToolButton(text=text)
            b.setToolTip(tip)
            b.clicked.connect(slot)
            b.setFixedHeight(28)
            b.setMinimumWidth(30)
            lay.addWidget(b)


# ---------------------------------------------------------------- canvas
class Handle(QGraphicsEllipseItem):
    def __init__(self, canvas, ci, pi):
        super().__init__(-6, -6, 12, 12)
        self.canvas, self.ci, self.pi = canvas, ci, pi
        self.setFlags(QGraphicsItem.ItemIsMovable | QGraphicsItem.ItemIgnoresTransformations
                      | QGraphicsItem.ItemSendsGeometryChanges)
        self.setZValue(10)
        self.setCursor(Qt.SizeAllCursor)

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionHasChanged and not self.canvas.syncing:
            self.canvas.win.move_point(self.ci, self.pi, value.x(), -value.y())
        return super().itemChange(change, value)

    def mousePressEvent(self, e):
        self.canvas.win.select_control(self.ci, from_canvas=True)
        super().mousePressEvent(e)


class Canvas(QGraphicsView):
    def __init__(self, win):
        super().__init__()
        self.win = win
        sc = QGraphicsScene(self)
        sc.setSceneRect(-20000, -20000, 40000, 40000)
        self.setScene(sc)
        self.setRenderHint(QPainter.Antialiasing)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setViewportUpdateMode(QGraphicsView.FullViewportUpdate)  # scale bar is drawn in viewport space
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setFocusPolicy(Qt.StrongFocus)
        self.plate = sc.addPath(QPainterPath(), QPen(QColor(170, 170, 180), 0), QBrush(QColor(62, 64, 72)))
        self.bg = QGraphicsPixmapItem()
        self.bg.setZValue(1)
        sc.addItem(self.bg)
        self.holes = sc.addPath(QPainterPath(), QPen(Qt.NoPen), QBrush(QColor("#2E7D4F")))
        self.holes.setZValue(2)
        dash = QPen(QColor(120, 200, 255), 0, Qt.DashLine)
        self.decor = sc.addPath(QPainterPath(), dash)
        self.decor.setZValue(3)
        self.draft = sc.addPath(QPainterPath(), QPen(QColor(255, 120, 120), 0))
        self.draft.setZValue(4)
        self.keep = sc.addPath(QPainterPath(), QPen(QColor(255, 170, 60), 0, Qt.DashLine))
        self.keep.setZValue(3)
        self.weak = sc.addEllipse(-7, -7, 14, 14, QPen(QColor(255, 80, 80), 2))  # thinnest wall marker, in px
        self.weak.setFlag(QGraphicsItem.ItemIgnoresTransformations)
        self.weak.setZValue(6)
        self.weak.setVisible(False)
        self.ruler = sc.addLine(0, 0, 0, 0, QPen(QColor(255, 255, 255), 0))
        self.ruler.setZValue(5)
        self.ruler_txt = sc.addSimpleText("")
        self.ruler_txt.setBrush(QColor("white"))
        self.ruler_txt.setFlag(QGraphicsItem.ItemIgnoresTransformations)
        self.ruler_txt.setZValue(6)
        self.handles, self.syncing, self.tool = [], False, None
        self.pan_pos, self.space, self.ruler_start, self.draft_pts = None, False, None, []
        self.scale(4, 4)
        self.fit_k, self.info = 4.0, ""
        self.zoombar = ZoomBar(self)
        self.viewport().setCursor(Qt.OpenHandCursor)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.zoombar.adjustSize()
        vp = self.viewport()
        self.zoombar.move(vp.width() - self.zoombar.width() - 12, vp.height() - self.zoombar.height() - 12)

    def zoom_by(self, f, anchor_mouse=False):
        k = self.transform().m11()
        f = min(max(f, 0.05 / k), 2000 / k)
        if not anchor_mouse:
            self.setTransformationAnchor(QGraphicsView.AnchorViewCenter)
        self.scale(f, f)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.zoombar.pct.setText(f"{100 * self.transform().m11() / self.fit_k:.0f}%")

    # --- content
    def set_result(self, holes, outline, color):
        self.holes.setPath(holes)
        self.holes.setBrush(QColor(color))
        self.plate.setPath(outline)

    def set_overlays(self, keepouts, weak, bad):
        path = QPainterPath()
        for k in keepouts:
            add_keepout_path(path, k)
        self.keep.setPath(path)
        self.weak.setVisible(weak is not None)
        if weak is not None:
            self.weak.setPos(S(*weak))
            self.weak.setPen(QPen(QColor(255, 80, 80) if bad else QColor(240, 210, 90), 2))

    def set_background(self, pm, w, h, opacity):
        self.bg.setVisible(pm is not None)
        if pm is not None:
            self.bg.setPixmap(pm)
            self.bg.setTransform(QTransform.fromScale(w / pm.width(), h / pm.height()))
            self.bg.setPos(-w / 2, -h / 2)
            self.bg.setOpacity(opacity)

    def set_handles(self, controls, sel):
        for h in self.handles:
            self.scene().removeItem(h)
        self.handles = []
        self.syncing = True
        for ci, c in enumerate(controls):
            for pi, (x, y) in enumerate(c.points):
                h = Handle(self, ci, pi)
                h.setPos(S(x, y))
                self.scene().addItem(h)
                self.handles.append(h)
        self.syncing = False
        self.update_decor(controls, sel)

    def update_decor(self, controls, sel):
        path = QPainterPath()
        for c in controls:
            pts = [S(x, y) for x, y in c.points]
            if not pts:
                continue
            if c.kind == "point" or len(pts) == 1:
                path.addEllipse(pts[0], c.radius, c.radius)
                continue
            spine = catmull(pts) if c.kind == "curve" else QPainterPath(pts[0])
            if c.kind != "curve":
                for q in pts[1:]:
                    spine.lineTo(q)
            st = QPainterPathStroker()
            st.setWidth(2 * c.radius)
            st.setCapStyle(Qt.RoundCap)
            path.addPath(spine)
            path.addPath(st.createStroke(spine).simplified())
        self.decor.setPath(path)
        for h in self.handles:
            on = h.ci == sel
            h.setBrush(QColor(120, 210, 150) if on else QColor(120, 200, 255))
            h.setPen(QPen(QColor("white" if on else "black"), 1.5))

    def zoom_fit(self):
        r = self.plate.path().boundingRect()
        if r.width() > 0:
            self.fitInView(r.adjusted(-r.width() * .06, -r.height() * .06, r.width() * .06, r.height() * .06),
                           Qt.KeepAspectRatio)
            self.fit_k = self.transform().m11()
            self.zoom_by(1)

    # --- painting
    def drawBackground(self, p, rect):
        p.fillRect(rect, QColor(30, 31, 34))
        k = self.transform().m11()
        for step, col in ((1, QColor(40, 41, 45)), (10, QColor(52, 54, 60))):
            if step * k < 6:
                continue
            p.setPen(QPen(col, 0))
            x = math.floor(rect.left() / step) * step
            while x < rect.right():
                p.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))
                x += step
            y = math.floor(rect.top() / step) * step
            while y < rect.bottom():
                p.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
                y += step

    def drawForeground(self, p, rect):
        k = self.transform().m11()  # px per mm
        mm = next((v for v in (0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 50, 100, 200, 500, 1000) if v * k >= 60), 1000)
        p.save()
        p.resetTransform()
        x0, y0 = 16, self.viewport().height() - 18
        p.setPen(QPen(QColor(230, 230, 230), 2))
        p.drawLine(x0, y0, x0 + mm * k, y0)
        p.drawLine(x0, y0 - 5, x0, y0 + 3)
        p.drawLine(int(x0 + mm * k), y0 - 5, int(x0 + mm * k), y0 + 3)
        p.drawText(x0, y0 - 7, f"{mm:g} mm")
        if self.info:  # headline stats, readable at a glance
            f = p.font()
            f.setPointSizeF(f.pointSizeF() * 1.35)
            f.setBold(True)
            p.setFont(f)
            p.setPen(QColor(235, 235, 235))
            p.drawText(16, 30, self.info)
        p.restore()

    # --- interaction
    def wheelEvent(self, e):
        self.zoom_by(1.15 ** (e.angleDelta().y() / 120), anchor_mouse=True)

    def set_tool(self, tool):
        self.tool = tool
        self.ruler.setVisible(tool == "ruler")
        self.ruler_txt.setVisible(tool == "ruler")
        self.draft_pts = []
        self.draft.setPath(QPainterPath())
        self.viewport().setCursor(Qt.CrossCursor if tool else Qt.OpenHandCursor)
        if tool:
            self.setFocus()

    def mousePressEvent(self, e):
        on_handle = isinstance(self.itemAt(e.position().toPoint()), Handle)
        b = e.button()
        # Drag empty space to pan (left or right without a tool, middle / space always)
        if (b == Qt.MiddleButton or (b == Qt.LeftButton and self.space)
                or (self.tool is None and b in (Qt.LeftButton, Qt.RightButton) and not on_handle)):
            self.pan_pos = e.position()
            self.viewport().setCursor(Qt.ClosedHandCursor)
            return
        pos = self.mapToScene(e.position().toPoint())
        if self.tool == "ruler" and e.button() == Qt.LeftButton:
            self.ruler_start = pos
            self._ruler(pos)
        elif self.tool == "keepout":
            if e.button() == Qt.RightButton:
                self.win.remove_keepout(pos.x(), -pos.y())
            elif e.button() == Qt.LeftButton:
                self.ruler_start = pos
        elif self.tool == "draw":
            if e.button() == Qt.RightButton:
                self.finish_draw()
            elif e.button() == Qt.LeftButton:
                self.draft_pts.append(pos)
                self._draft(pos)
        else:
            super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self.pan_pos is not None:
            d = e.position() - self.pan_pos
            self.pan_pos = e.position()
            k = self.transform().m11()
            self.setTransformationAnchor(QGraphicsView.NoAnchor)
            self.translate(d.x() / k, d.y() / k)
            self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
            return
        pos = self.mapToScene(e.position().toPoint())
        if self.tool == "ruler" and self.ruler_start is not None and e.buttons() & Qt.LeftButton:
            self._ruler(pos)
        elif self.tool == "draw" and self.draft_pts:
            self._draft(pos)
        elif self.tool == "keepout" and self.ruler_start is not None:
            path = QPainterPath()
            if k := self._keepout(pos, e.modifiers()):
                self.win.statusBar().showMessage(f"{k.shape} {k.width:.1f} × {k.height:.1f} mm at ({k.x:.1f}, {k.y:.1f})")
                add_keepout_path(path, k)
            self.draft.setPath(path)
        else:
            super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if self.pan_pos is not None:
            self.pan_pos = None
            self.viewport().setCursor(Qt.CrossCursor if self.tool else Qt.OpenHandCursor)
            return
        if self.tool == "keepout" and self.ruler_start is not None and e.button() == Qt.LeftButton:
            k = self._keepout(self.mapToScene(e.position().toPoint()), e.modifiers())
            self.ruler_start = None
            self.draft.setPath(QPainterPath())
            if k:
                self.win.add_keepout(k)
            return
        super().mouseReleaseEvent(e)
        if self.tool is None:
            self.win.commit()  # end of a handle drag

    def mouseDoubleClickEvent(self, e):
        if self.tool == "draw":
            self.finish_draw()
        elif self.tool is None and not isinstance(self.itemAt(e.position().toPoint()), Handle):
            self.zoom_fit()
        else:
            super().mouseDoubleClickEvent(e)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Space and not e.isAutoRepeat():
            self.space = True
        elif e.key() in (Qt.Key_Plus, Qt.Key_Equal, Qt.Key_Minus):
            self.zoom_by(1.25 if e.key() != Qt.Key_Minus else 1 / 1.25)
        elif self.tool == "draw" and e.key() in (Qt.Key_Return, Qt.Key_Enter):
            self.finish_draw()
        elif self.tool and e.key() == Qt.Key_Escape:
            self.win.set_tool(None)
        else:
            super().keyPressEvent(e)

    def keyReleaseEvent(self, e):
        if e.key() == Qt.Key_Space and not e.isAutoRepeat():
            self.space = False
        super().keyReleaseEvent(e)

    def _ruler(self, pos):
        a = self.ruler_start
        self.ruler.setLine(a.x(), a.y(), pos.x(), pos.y())
        d = math.hypot(pos.x() - a.x(), pos.y() - a.y())
        ang = math.degrees(math.atan2(a.y() - pos.y(), pos.x() - a.x()))
        self.ruler_txt.setText(f"{d:.2f} mm  {ang:.1f}°")
        self.ruler_txt.setPos(pos + QPointF(2 / self.transform().m11(), 0))
        self.win.statusBar().showMessage(f"Distance {d:.2f} mm, dx {pos.x() - a.x():.2f}, dy {a.y() - pos.y():.2f}")

    def _keepout(self, pos, mods):
        """Drag corner to corner for a rectangle; with Shift, from the centre for a circle."""
        a = self.ruler_start
        if mods & Qt.ShiftModifier:
            r = math.hypot(pos.x() - a.x(), pos.y() - a.y())
            return Keepout("circle", round(a.x(), 2), round(-a.y(), 2), round(2 * r, 2), round(2 * r, 2)) if r > .25 else None
        w, h = abs(pos.x() - a.x()), abs(pos.y() - a.y())
        if min(w, h) < .5:
            return None
        return Keepout("rectangle", round((a.x() + pos.x()) / 2, 2), round(-(a.y() + pos.y()) / 2, 2),
                       round(w, 2), round(h, 2))

    def _draft(self, cursor):
        path = QPainterPath(self.draft_pts[0])
        for q in self.draft_pts[1:] + [cursor]:
            path.lineTo(q)
        self.draft.setPath(path)

    def finish_draw(self):
        pts = [[round(p.x(), 3), round(-p.y(), 3)] for p in self.draft_pts]
        # a double-click also delivers a press: drop the duplicate final point
        while len(pts) > 1 and math.dist(pts[-1], pts[-2]) < 1e-6:
            pts.pop()
        self.win.set_tool(None)
        if len(pts) >= 3:
            self.win.set_custom_boundary(pts)


# ---------------------------------------------------------------- main window
class MainWindow(QMainWindow):
    def __init__(self, path=None):
        super().__init__()
        self.resize(1500, 920)
        self.settings = QSettings("VentForge", "VentForge")
        self.design, self.path, self.dirty, self.syncing = Design(), None, False, False
        self.hist, self.hpos = [self.design.to_json()], 0
        self.bindings, self.tasks, self.gen_task, self.gen_pending = [], set(), None, False
        self.saved_json, self.result, self.bg_key, self.need_fit = None, None, None, True
        self.thumb_queue = []
        self.canvas = Canvas(self)
        self.setCentralWidget(self.canvas)
        self.regen_timer = QTimer(self, singleShot=True, interval=40, timeout=self.regen_now)
        self.commit_timer = QTimer(self, singleShot=True, interval=400, timeout=self.commit)
        self.disk_timer = QTimer(self, singleShot=True, interval=120, timeout=self.check_disk)
        self.watcher = QFileSystemWatcher(self)
        self.watcher.fileChanged.connect(lambda _: self.disk_timer.start())
        self.watcher.directoryChanged.connect(lambda _: self.disk_timer.start())
        self._toolbar()
        self._left_dock()
        self._right_dock()
        self._statusbar()
        self.set_design(Design(), record=False)
        if path:
            self.open_file(path)
        self.refresh_library()
        self.update_title()

    # ---------------- UI construction
    def _toolbar(self):
        tb = self.addToolBar("Main")
        tb.setObjectName("main")
        tb.setMovable(False)

        tb.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        tb.setIconSize(QSize(18, 18))
        icons = {"New": QStyle.SP_FileIcon, "Open": QStyle.SP_DialogOpenButton, "Save": QStyle.SP_DialogSaveButton,
                 "Undo": QStyle.SP_ArrowBack, "Redo": QStyle.SP_ArrowForward, "Reset": QStyle.SP_BrowserReload}

        def act(text, slot, key=None, checkable=False):
            a = QAction(text, self, checkable=checkable)
            if text in icons:
                a.setIcon(self.style().standardIcon(icons[text]))
            a.triggered.connect(slot)
            if key:
                a.setShortcut(QKeySequence(key))
                a.setToolTip(f"{text} ({QKeySequence(key).toString()})")
            tb.addAction(a)
            return a

        act("New", self.new, QKeySequence.New)
        act("Open", self.open_dialog, QKeySequence.Open)
        act("Save", self.save, QKeySequence.Save)
        act("Save As", self.save_as, "Ctrl+Shift+S")
        tb.addSeparator()
        self.undo_act = act("Undo", self.undo, QKeySequence.Undo)
        self.redo_act = act("Redo", self.redo, "Ctrl+Y")
        tb.addSeparator()
        act("Reset", self.reset, None).setToolTip("Reset all parameters to defaults")
        act("Randomize", self.randomize, None).setToolTip("Randomize the current mode's parameters")
        tb.addSeparator()
        self.ruler_act = act("Ruler", lambda on: self.set_tool("ruler" if on else None), "R", True)
        self.draw_act = act("Draw outline", lambda on: self.set_tool("draw" if on else None), "B", True)
        self.keep_act = act("Keep-out", lambda on: self.set_tool("keepout" if on else None), "K", True)
        act("Zoom to fit", self.canvas.zoom_fit, "Z")
        act("Fan grille…", self.fan_dialog).setToolTip("Plate for a standard fan: blade opening and 4 screw holes")
        tb.addSeparator()
        menu_btn = QToolButton(text="  Export  ", popupMode=QToolButton.InstantPopup)
        menu_btn.setObjectName("export")
        m = self.menuBar().addMenu("&Export")
        for ext in (".png", ".svg", ".dxf", ".step", ".stl"):
            m.addAction(ext[1:].upper() + "…", lambda e=ext: self.export_as(e))
        m.addSeparator()
        m.addAction("Wrap onto cylinder…", self.wrap_dialog)
        m.addAction("Cut into part…", self.cut_dialog)
        menu_btn.setMenu(m)
        tb.addWidget(menu_btn)

    def _dock(self, title, sections, area):
        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setContentsMargins(6, 6, 6, 6)
        for s in sections:
            lay.addWidget(s)
        lay.addStretch(1)
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        sa.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        sa.setWidget(body)
        d = QDockWidget(title, self)
        d.setObjectName(title)
        d.setWidget(sa)
        d.setMinimumWidth(380)
        self.addDockWidget(area, d)

    def bind(self, w, path):
        self.bindings.append((path, w))
        return w

    def field_widget(self, path, name, t):
        if t is bool:
            w = QCheckBox()
            w.toggled.connect(lambda v, p=path: self.set_param(p, bool(v)))
        elif t in (int, float):
            w = slider_field(path, name, t, self.design.canvas)
            w.valueChanged.connect(lambda v, p=path: self.set_param(p, v))
        elif t is str and (path in CHOICES or name in CHOICES):
            opts = CHOICES.get(path) or CHOICES[name]
            icons = choice_icons(path)
            if icons or len(opts) <= 4:
                w = Picker([(c, c.replace("_", " ").replace("rounded rectangle", "rounded").capitalize(),
                             icons.get(c) if icons else None) for c in opts],
                           cols=(5 if path == "pattern.mode" else 3) if icons else None)
                w.valueChanged.connect(lambda v, p=path: self.set_param(p, v))
            else:
                w = QComboBox()
                for c in opts:
                    w.addItem(c.replace("_", " "), c)
                w.currentIndexChanged.connect(lambda i, p=path, w=w: self.set_param(p, w.itemData(i)))
        elif t is str:
            w = QLineEdit()
            w.editingFinished.connect(lambda p=path, w=w: self.set_param(p, w.text()))
        else:  # point lists: edited on the canvas / via file or MCP
            w = QLabel()
        return self.bind(w, path)

    def form(self, path, cls, skip=(), only=None):
        """Basic fields in the returned form; rarely needed ones (ADVANCED) in a folded 'More options'."""
        def mk():
            f = QFormLayout()
            f.setContentsMargins(4, 2, 4, 2)
            f.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
            f.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            return f
        w = QWidget()
        outer = QVBoxLayout(w)
        outer.setContentsMargins(0, 0, 0, 0)
        f, adv = mk(), mk()
        outer.addLayout(f)
        hints = get_type_hints(cls)
        rows = {}
        for fl in fields(cls):
            if fl.name in skip or (only and fl.name not in only) or is_dataclass(hints[fl.name]):
                continue
            t = getattr(hints[fl.name], "__origin__", hints[fl.name])
            fw = self.field_widget(f"{path}.{fl.name}" if path else fl.name, fl.name, t)
            target = adv if fl.name in ADVANCED else f
            if isinstance(fw, Picker) and fw.btns and next(iter(fw.btns.values())).property("tile"):
                target.addRow(QLabel(label_for(fl.name)))
                target.addRow(fw)  # picture tiles get the full width
            else:
                target.addRow(QLabel(label_for(fl.name)), fw)
            rows[fl.name] = fw
        if adv.rowCount():
            body = QWidget()
            body.setLayout(adv)
            outer.addWidget(Section("More options", body, False, small=True))
        return w, f, rows

    def _left_dock(self):
        # library
        lib = QWidget()
        v = QVBoxLayout(lib)
        self.lib_list = QListWidget(viewMode=QListWidget.IconMode, movement=QListWidget.Static,
                                    resizeMode=QListWidget.Adjust, wordWrap=True)
        self.lib_list.setIconSize(QSize(88, 88))
        self.lib_list.setGridSize(QSize(104, 116))
        self.lib_list.setMinimumHeight(260)
        self.lib_list.itemClicked.connect(self.library_clicked)
        self.lib_folder = Path(self.settings.value("library", str(Path.home() / "Documents" / "VentForge")))
        self.lib_label = QLabel(wordWrap=True)
        v.addWidget(self.lib_list)
        v.addWidget(self.lib_label)
        v.addWidget(row(button("Save to library", self.save_to_library),
                        button("Folder…", self.pick_library_folder), button("↻", self.refresh_library, "Refresh")))
        # canvas
        cw, cf, _ = self.form("canvas", type(self.design.canvas))
        self.link_cb = QCheckBox("Link width/height (keep aspect)")
        cf.addRow(self.link_cb)
        name = self.field_widget("name", "name", str)
        cf.insertRow(0, "Name", name)
        mw = self.field_widget("min_wall", "min_wall", float)
        cf.addRow(DragLabel("Min wall", mw), mw)
        # boundary
        bw, bf, _ = self.form("boundary", type(self.design.boundary))
        bf.addRow(row(button("Draw outline", lambda: self.draw_act.trigger(),
                             "Click points on the canvas; double-click, Enter or right-click to finish"),
                      button("Clear outline", lambda: self.set_param("boundary.points", []))))
        bf.addRow("Keep-outs", self.field_widget("keepouts", "keepouts", list))
        bf.addRow(row(button("Clear keep-outs", lambda: self.set_param("keepouts", []),
                             "Screw holes and hole-free areas (set by Fan grille or the MCP server)")))
        mcw, _, _ = self.form("machining", Machining)
        # background
        gw = QWidget()
        gf = QFormLayout(gw)
        self.bg_label = QLabel(wordWrap=True)
        op = self.field_widget("background.opacity", "opacity", float)
        gf.addRow(self.bg_label)
        gf.addRow(DragLabel("Opacity", op), op)
        gf.addRow(row(button("Load image…", self.load_background),
                      button("Clear", lambda: self.set_param("background.image", ""))))
        self._dock("Design", [Section("Library", lib), Section("Canvas", cw), Section("Boundary", bw),
                              Section("Machining", mcw, False), Section("Background image", gw, False)], Qt.LeftDockWidgetArea)

    def _right_dock(self):
        self.grad_tabs = QTabWidget()
        self.gw = {}
        for g in GRADS:
            w, f, rows = self.form(f"gradients.{g}", Gradient, skip=("controls", "image"))
            gw = self.gw[g] = {}
            f.insertRow(4, "", button("Reseed noise", lambda _=0, g=g: self.set_param(
                f"gradients.{g}.noise_seed", random.randint(1, 99999))))
            gw["img"] = QLabel(wordWrap=True)
            f.addRow("Image", gw["img"])
            f.addRow(row(button("Load image…", lambda _=0, g=g: self.load_grad_image(g)),
                         button("Clear", lambda _=0, g=g: self.set_param(f"gradients.{g}.image", ""))))
            lst = gw["list"] = QListWidget()
            lst.setMaximumHeight(110)
            lst.currentRowChanged.connect(lambda i, g=g: self.select_control(i))
            f.addRow(QLabel("<b>Controls</b>"))
            f.addRow(lst)
            f.addRow(row(*(button(k.capitalize(), lambda _=0, g=g, k=k: self.add_control(g, k), f"Add {k}")
                           for k in ("point", "line", "curve")),
                         button("Delete", lambda _=0, g=g: self.delete_control(g))))
            for key, label in (("value", "Strength at control"), ("radius", "Reach")):
                sp = gw[key] = slider_field(f"gradients.{g}.{key}", key, float, self.design.canvas)
                sp.valueChanged.connect(lambda v, g=g, key=key: self.set_control_attr(g, key, v))
                f.addRow(QLabel(label), sp)
            if g == "shape":
                for n in ("target_shape", "target_sides"):
                    fw = self.field_widget(f"gradients.{n}", n, str if n == "target_shape" else int)
                    f.addRow(DragLabel(label_for(n), fw), fw)
            self.grad_tabs.addTab(w, g.capitalize())
        self.grad_tabs.currentChanged.connect(lambda _: self.refresh_handles())
        # dot style
        dw, self.dot_form, self.dot_rows = self.form("dot", DotStyle, skip=("custom_points", "color"))
        self.color_btn = button("", self.pick_color, "Hole display colour")
        self.dot_form.addRow("Color", self.color_btn)
        # pattern
        pw = QWidget()
        pv = QVBoxLayout(pw)
        mode = self.field_widget("pattern.mode", "mode", str)
        self.mode_stack = QStackedWidget()
        hints = get_type_hints(Pattern)
        for m in MODES:
            w, f, rows = self.form(f"pattern.{m}", hints[m])
            if m == "grid":
                self.grid_form, self.grid_rows = f, rows
            self.mode_stack.addWidget(w)
        pv.addWidget(mode)
        pv.addWidget(self.mode_stack)
        self._dock("Pattern", [Section("Pattern mode", pw), Section("Dot style", dw),
                               Section("Gradients", self.grad_tabs)], Qt.RightDockWidgetArea)

    def _statusbar(self):
        sb = self.statusBar()
        self.st = {k: QLabel() for k in ("count", "open", "viol", "time")}
        self.busy_bar = QProgressBar(maximum=0, maximumWidth=120, visible=False)
        sb.addPermanentWidget(self.busy_bar)
        for w in self.st.values():
            sb.addPermanentWidget(w)

    # ---------------- design state
    def sync_widgets(self):
        self.syncing = True
        for path, w in self.bindings:
            v = getp(self.design, path)
            w.blockSignals(True)
            if isinstance(w, QCheckBox):
                w.setChecked(bool(v))
            elif isinstance(w, QComboBox):
                w.setCurrentIndex(max(0, w.findData(v)))
            elif isinstance(w, (QSpinBox, QDoubleSpinBox, SliderField, Picker)):
                w.setValue(v)
            elif isinstance(w, QLineEdit):
                w.setText(str(v))
            elif isinstance(w, QLabel):
                w.setText(f"{len(v)} {'keep-out' if path == 'keepouts' else 'point'}(s)" + (" — draw with K, right-click to remove"
                          if path == 'keepouts' else " — edit via file / MCP")
                          if v else "none (default)")
            w.blockSignals(False)
        for w in self.findChildren(SliderField):  # canvas-relative slider ranges
            if getattr(w, "path", None) in SCALE:
                w.set_soft(soft_range(w.path, w.name, w.sp.minimum(), w.sp.maximum(), self.design.canvas))
        for g in GRADS:
            self.refresh_control_list(g)
        self.syncing = False
        self.refresh_aux()

    def refresh_aux(self):
        d = self.design
        for n, w in self.dot_rows.items():
            if n not in ("shape", "diameter", "rotation"):
                self.dot_form.setRowVisible(w, n in DOT_VIS.get(d.dot.shape, ()))
        self.color_btn.setText(d.dot.color)
        self.color_btn.setStyleSheet(f"background:{d.dot.color};color:white")
        self.mode_stack.setCurrentIndex(MODES.index(d.pattern.mode) if d.pattern.mode in MODES else 0)
        # hexagon pitch is derived from spacing_x alone
        self.grid_form.setRowVisible(self.grid_rows["spacing_y"], d.pattern.grid.arrangement != "hexagon")
        self.holes_color()
        for g in GRADS:
            img = getattr(d.gradients, g).image
            self.gw[g]["img"].setText(Path(img).name if img else "none")
        self.bg_label.setText(Path(d.background.image).name if d.background.image else "No image")
        key = (d.background.image, d.canvas.width, d.canvas.height, d.background.opacity)
        if key != self.bg_key:
            self.bg_key = key
            pm = QPixmap(self.resolve(d.background.image)) if d.background.image else None
            self.canvas.set_background(pm if pm and not pm.isNull() else None, d.canvas.width,
                                       d.canvas.height, d.background.opacity)

    def holes_color(self):
        self.canvas.holes.setBrush(QColor(self.design.dot.color))

    def resolve(self, p):
        q = Path(p)
        return str(q if q.is_absolute() or not self.path else Path(self.path).parent / q)

    def set_param(self, path, v):
        if self.syncing:
            return
        c = self.design.canvas
        linked = self.link_cb.isChecked() and path in ("canvas.width", "canvas.height") and c.width and c.height
        if linked:
            r = c.height / c.width
            if path == "canvas.width":
                c.height = round(v * r, 3)
            else:
                c.width = round(v / r, 3)
        setp(self.design, path, v)
        self.changed(sync=linked or path.startswith("canvas.") or path.endswith(("noise_seed", ".points")))

    def changed(self, sync=False):
        if sync:
            self.sync_widgets()
        else:
            self.refresh_aux()
        self.dirty = True
        self.update_title()
        self.regen_timer.start()
        self.commit_timer.start()
        g = self.cur_grad()
        self.canvas.update_decor(g.controls, self.gw[self.grad_name()]["list"].currentRow())

    def set_design(self, d, record=True):
        self.design = d
        self.sync_widgets()
        self.refresh_handles()
        self.regen_now()
        if record:
            self.commit_timer.stop()
            self.commit()

    def commit(self):
        j = self.design.to_json()
        if j != self.hist[self.hpos]:
            del self.hist[self.hpos + 1:]
            self.hist.append(j)
            self.hist = self.hist[-300:]
            self.hpos = len(self.hist) - 1
        self.autosave()

    def autosave(self):
        """An open file is kept in sync with the editor, so the MCP server (Claude) always reads
        the user's latest edits instead of overwriting them with a stale copy."""
        if not self.path:
            self.update_title()
            return
        j = self.design.to_json()
        if j != self.saved_json:
            try:
                self.design.save(self.path)
            except Exception as e:
                self.statusBar().showMessage(f"Autosave failed: {e}")
                return
            self.saved_json = j
        self.dirty = False
        self.update_title()

    def undo(self):
        self.commit()
        if self.hpos > 0:
            self.hpos -= 1
            self.set_design(Design.from_dict(json.loads(self.hist[self.hpos])), record=False)
            self.dirty = True
            self.autosave()

    def redo(self):
        self.commit()
        if self.hpos < len(self.hist) - 1:
            self.hpos += 1
            self.set_design(Design.from_dict(json.loads(self.hist[self.hpos])), record=False)
            self.dirty = True
            self.autosave()

    def reset(self):
        self.set_design(Design())
        self.dirty = True
        self.autosave()

    def randomize(self):
        d = clone(self.design)
        m = d.pattern.mode
        p = getattr(d.pattern, m)
        hints = get_type_hints(type(p))
        for f in fields(p):
            t = hints[f.name]
            if f.name in RAND:
                lo, hi = RAND[f.name]
                setattr(p, f.name, random.randint(lo, hi) if t is int else round(random.uniform(lo, hi), 2))
            elif t is bool:
                setattr(p, f.name, random.random() < 0.5)
            elif t is str and (f"pattern.{m}.{f.name}" in CHOICES or f.name in CHOICES):
                setattr(p, f.name, random.choice(CHOICES.get(f"pattern.{m}.{f.name}") or CHOICES[f.name]))
        spacings = [getattr(p, n) for n in ("spacing_x", "spacing_y", "min_distance", "ring_spacing",
                                            "dot_spacing", "left_spacing", "right_spacing", "layer_spacing")
                    if hasattr(p, n)]
        d.dot.shape = random.choice(("circle", "hexagon", "polygon", "star", "rounded_rectangle"))
        d.dot.diameter = round(min(spacings) * random.uniform(0.4, 0.75) if spacings else random.uniform(2, 5), 2)
        d.dot.rotation = round(random.uniform(0, 90), 1)
        d.dot.sides = random.randint(3, 8)
        d.dot.star_points = random.randint(4, 8)
        d.dot.star_inner = round(random.uniform(0.35, 0.7), 2)
        d.dot.aspect = round(random.uniform(0.4, 2.5), 2)
        self.set_design(d)
        self.dirty = True
        self.autosave()

    # ---------------- gradients / controls
    def grad_name(self):
        return GRADS[max(0, self.grad_tabs.currentIndex())]

    def cur_grad(self):
        return getattr(self.design.gradients, self.grad_name())

    def refresh_handles(self):
        self.canvas.set_handles(self.cur_grad().controls, self.gw[self.grad_name()]["list"].currentRow())

    def refresh_control_list(self, g):
        lst, ctrls = self.gw[g]["list"], getattr(self.design.gradients, g).controls
        cur = lst.currentRow()
        lst.blockSignals(True)
        lst.clear()
        for i, c in enumerate(ctrls):
            lst.addItem(f"{i + 1}. {c.kind}  value {c.value:g}  r {c.radius:g}")
        lst.setCurrentRow(min(cur, len(ctrls) - 1) if cur >= 0 else (0 if ctrls else -1))
        lst.blockSignals(False)
        self._control_spins(g)

    def _control_spins(self, g):
        ctrls, i = getattr(self.design.gradients, g).controls, self.gw[g]["list"].currentRow()
        for key in ("value", "radius"):
            sp = self.gw[g][key]
            sp.setEnabled(0 <= i < len(ctrls))
            if 0 <= i < len(ctrls):
                sp.blockSignals(True)
                sp.setValue(getattr(ctrls[i], key))
                sp.blockSignals(False)

    def select_control(self, i, from_canvas=False):
        g = self.grad_name()
        lst = self.gw[g]["list"]
        lst.blockSignals(True)
        lst.setCurrentRow(i)
        lst.blockSignals(False)
        self._control_spins(g)
        if from_canvas:  # the pressed handle must survive, so only restyle
            self.canvas.update_decor(self.cur_grad().controls, i)
        else:
            self.refresh_handles()

    def add_control(self, g, kind):
        w, h = self.design.canvas.width, self.design.canvas.height
        pts = {"point": [[0.0, 0.0]], "line": [[-w / 4, 0.0], [w / 4, 0.0]],
               "curve": [[-w * .35, -h * .15], [-w * .1, h * .15], [w * .1, -h * .15], [w * .35, h * .15]]}[kind]
        gr = getattr(self.design.gradients, g)
        gr.controls.append(Control(kind=kind, points=pts, value=CTRL_VALUE[g], radius=round(min(w, h) / 3, 1)))
        gr.enabled = True
        self.grad_tabs.setCurrentIndex(GRADS.index(g))
        self.changed(sync=True)
        self.select_control(len(gr.controls) - 1)

    def delete_control(self, g):
        i, ctrls = self.gw[g]["list"].currentRow(), getattr(self.design.gradients, g).controls
        if 0 <= i < len(ctrls):
            del ctrls[i]
            self.changed(sync=True)
            self.refresh_handles()

    def set_control_attr(self, g, key, v):
        i, ctrls = self.gw[g]["list"].currentRow(), getattr(self.design.gradients, g).controls
        if 0 <= i < len(ctrls):
            setattr(ctrls[i], key, v)
            self.gw[g]["list"].item(i).setText(f"{i + 1}. {ctrls[i].kind}  value {ctrls[i].value:g}"
                                               f"  r {ctrls[i].radius:g}")
            self.changed()

    def move_point(self, ci, pi, x, y):
        self.cur_grad().controls[ci].points[pi] = [round(x, 3), round(y, 3)]
        self.changed()

    # ---------------- canvas tools
    def set_tool(self, tool):
        self.ruler_act.setChecked(tool == "ruler")
        self.draw_act.setChecked(tool == "draw")
        self.keep_act.setChecked(tool == "keepout")
        self.canvas.set_tool(tool)
        if tool == "keepout":
            self.statusBar().showMessage("Drag a hole-free rectangle (Shift: circle from its centre); right-click one to"
                                         " remove it, Esc to finish")
        if tool == "draw":
            self.statusBar().showMessage("Click to add outline points; double-click / Enter / right-click to finish,"
                                         " Esc to cancel")

    def fan_dialog(self):
        sizes = [f"{s} mm" for s in FANS]
        s, ok = QInputDialog.getItem(self, "Fan grille", "Fan size (the hole pattern stays):", sizes, sizes.index("120 mm"),
                                     False)
        if ok:
            self.need_fit = True
            self.set_design(fan_grille(clone(self.design), int(s.split()[0])))
            self.dirty = True
            self.autosave()

    def add_keepout(self, k):
        self.design.keepouts.append(k)
        self.changed(sync=True)
        self.commit()

    def remove_keepout(self, x, y):
        from .pattern import _keepout_geom
        from shapely import Point
        hit = [i for i, k in enumerate(self.design.keepouts) if _keepout_geom(k).buffer(1).contains(Point(x, y))]
        if hit:
            del self.design.keepouts[hit[-1]]  # the topmost (last drawn)
            self.changed(sync=True)
            self.commit()

    def set_custom_boundary(self, pts):
        self.design.boundary.points = pts
        self.design.boundary.type = "custom"
        self.changed(sync=True)
        self.commit()

    # ---------------- regeneration
    def run_task(self, fn, cb):
        t = Task(fn, cb)
        self.tasks.add(t)
        t.done.connect(self._task_done)
        t.start()
        return t

    def _task_done(self, t):
        t.wait()
        self.tasks.discard(t)
        t.cb(t)

    def regen_now(self):
        self.regen_timer.stop()
        if self.gen_task:
            self.gen_pending = True
            return
        d = clone(self.design)
        self.gen_task = self.run_task(lambda: build(d), self._gen_done)

    def _gen_done(self, t):
        self.gen_task = None
        if self.gen_pending:  # latest request wins: skip showing the stale result
            self.gen_pending = False
            self.regen_now()
            return
        if t.error:
            self.statusBar().showMessage("Generate failed: " + t.error.strip().splitlines()[-1])
            print(t.error, file=sys.stderr)
            return
        r, holes, outline, dt = t.value
        self.result = r
        self.canvas.set_result(holes, outline, self.design.dot.color)
        s = r.stats
        self.st["count"].setText(f"{s.get('count', len(r.holes))} dots")
        self.st["open"].setText(f"open {100 * s.get('open_area_ratio', 0):.1f} %"
                                + (f"  ·  fan {100 * s['fan_open_ratio']:.0f} % open" if "fan_open_ratio" in s else "")
                                + (f"  ·  {s['dropped_by_tool']} too small for the tool" if s.get("dropped_by_tool") else ""))
        v = s.get("min_wall_violations", 0)
        tw = s.get("thinnest_wall")
        self.st["viol"].setText(f"min-wall violations {v}" + (f"  ·  thinnest wall {tw:.2f} mm" if tw else "")
                                + (f"  ·  {s['below_min_feature']} holes below min feature"
                                   if s.get("below_min_feature") else "")
                                + (f"  ·  airflow loss {s['pressure_drop_pa']:.0f} Pa @2 m/s"
                                   if "pressure_drop_pa" in s else ""))
        self.canvas.set_overlays(self.design.keepouts, s.get("thinnest_wall_at"), tw is not None and tw < self.design.min_wall)
        self.st["viol"].setStyleSheet("color:#ff7070" if v else "")
        self.st["time"].setText(f"{dt * 1000:.0f} ms")
        warn = f"   ⚠ {v} walls thinner than {self.design.min_wall:g} mm" if v else ""
        self.canvas.info = (f"{s.get('count', len(r.holes))} holes   ·   "
                            f"{100 * s.get('open_area_ratio', 0):.1f} % open{warn}")
        self.canvas.viewport().update()
        if self.need_fit:
            self.need_fit = False
            self.canvas.zoom_fit()

    def idle(self):
        return not (self.gen_task or self.gen_pending or self.regen_timer.isActive())

    # ---------------- files
    def update_title(self):
        n = Path(self.path).name if self.path else self.design.name
        self.setWindowTitle(f"{'*' if self.dirty else ''}{n} — VentForge")

    def watch(self, path):
        old = self.watcher.files() + self.watcher.directories()
        if old:
            self.watcher.removePaths(old)
        self.path = str(Path(path).resolve()) if path else None
        if self.path:
            self.watcher.addPaths([self.path, str(Path(self.path).parent)])

    def maybe_save(self):
        if not self.dirty:
            return True
        r = QMessageBox.question(self, "Unsaved changes", "Save changes to the current design?",
                                 QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
        return r == QMessageBox.Discard or (r == QMessageBox.Save and self.save())

    def new(self):
        if self.maybe_save():
            self.watch(None)
            self.need_fit = True
            self.set_design(Design())
            self.dirty = False
            self.update_title()

    def open_dialog(self):
        if self.maybe_save():
            p, _ = QFileDialog.getOpenFileName(self, "Open design", str(self.lib_folder),
                                               "Vent designs (*.vent.json *.json)")
            if p:
                self.open_file(p)

    def open_file(self, p, template=False):
        try:
            d = Design.load(p)
        except Exception as e:
            QMessageBox.critical(self, "Open failed", f"{p}\n\n{e}")
            return False
        self.watch(None if template else p)
        self.saved_json = d.to_json()
        self.need_fit = True
        self.set_design(d)
        self.dirty = False
        self.update_title()
        return True

    def save(self):
        return self.save_to(self.path) if self.path else self.save_as()

    def save_as(self):
        p, _ = QFileDialog.getSaveFileName(self, "Save design", str(self.lib_folder / f"{self.design.name}.vent.json"),
                                           "Vent designs (*.vent.json)")
        if not p:
            return False
        if not p.endswith(".json"):
            p += ".vent.json"
        return self.save_to(p)

    def save_to(self, p):
        self.commit()
        self.saved_json = self.design.to_json()
        try:
            self.design.save(p)
        except Exception as e:
            QMessageBox.critical(self, "Save failed", f"{p}\n\n{e}")
            return False
        self.watch(p)
        self.dirty = False
        self.update_title()
        self.statusBar().showMessage(f"Saved {p}", 4000)
        return True

    def check_disk(self):
        """Live sync: reload when another process (e.g. the MCP server) rewrote the open file."""
        if not self.path or not Path(self.path).exists():
            return
        if self.path not in self.watcher.files():  # atomic replace drops the watch
            self.watcher.addPath(self.path)
        try:
            d = Design.load(self.path)
        except Exception:
            return  # half-written or invalid; the next change event will retry
        j = d.to_json()
        if j in (self.saved_json, self.design.to_json()):
            return  # our own write, or nothing new
        if self.commit_timer.isActive():  # mid-edit: the pending autosave keeps the user's version
            self.statusBar().showMessage("File changed on disk while you were editing; kept your version", 6000)
            return
        self.saved_json = j
        self.set_design(d)
        self.dirty = False
        self.update_title()
        self.statusBar().showMessage("Reloaded from disk", 4000)

    # ---------------- library
    def refresh_library(self):
        self.lib_list.clear()
        self.lib_label.setText(f"User library: …/{self.lib_folder.name}")
        self.lib_label.setToolTip(str(self.lib_folder))
        files = sorted(PRESETS.glob("*.vent.json")) + (sorted(self.lib_folder.glob("*.vent.json"))
                                                      if self.lib_folder.is_dir() else [])
        self.thumb_queue = []
        for f in files:
            it = QListWidgetItem(f.name.removesuffix(".vent.json"))
            it.setData(Qt.UserRole, str(f))
            it.setToolTip(str(f))
            self.lib_list.addItem(it)
            self.thumb_queue.append(it)
        self._next_thumb()

    def _next_thumb(self):
        if not self.thumb_queue or any(getattr(t, "thumb", False) for t in self.tasks):
            return
        it = self.thumb_queue.pop(0)
        path = it.data(Qt.UserRole)

        def done(t):
            if not t.error:
                d, (_, holes, outline, _) = t.value
                try:
                    it.setIcon(paint_thumb(holes, outline, d.dot.color))
                except RuntimeError:
                    pass  # list was refreshed meanwhile
            self._next_thumb()

        t = self.run_task(lambda: (lambda d: (d, build(d)))(Design.load(path)), done)
        t.thumb = True

    def library_clicked(self, it):
        if self.maybe_save():
            self.open_file(it.data(Qt.UserRole), template=True)

    def save_to_library(self):
        self.lib_folder.mkdir(parents=True, exist_ok=True)
        name = "".join(c if c.isalnum() or c in " -_" else "_" for c in self.design.name).strip() or "design"
        p = self.lib_folder / f"{name}.vent.json"
        if p.exists() and QMessageBox.question(self, "Overwrite?", f"{p.name} exists. Overwrite?") != QMessageBox.Yes:
            return
        self.save_to(str(p))
        self.refresh_library()

    def pick_library_folder(self):
        p = QFileDialog.getExistingDirectory(self, "Library folder", str(self.lib_folder))
        if p:
            self.lib_folder = Path(p)
            self.settings.setValue("library", p)
            self.refresh_library()

    # ---------------- images / colour
    def _pick_image(self):
        return QFileDialog.getOpenFileName(self, "Image", "", "Images (*.png *.jpg *.jpeg *.bmp *.gif *.tif)")[0]

    def load_background(self):
        if p := self._pick_image():
            self.set_param("background.image", p)

    def load_grad_image(self, g):
        if p := self._pick_image():
            self.set_param(f"gradients.{g}.image", p)

    def pick_color(self):
        c = QColorDialog.getColor(QColor(self.design.dot.color), self, "Hole colour")
        if c.isValid():
            self.set_param("dot.color", c.name().upper())

    # ---------------- export
    def busy(self, on):
        self.busy_bar.setVisible(on)
        (QApplication.setOverrideCursor(Qt.WaitCursor) if on else QApplication.restoreOverrideCursor())

    def run_export(self, fn, what):
        self.busy(True)
        d = clone(self.design)

        def done(t):
            self.busy(False)
            if t.error:
                QMessageBox.critical(self, "Export failed", t.error[-2000:])
            else:
                self.statusBar().showMessage(f"Exported {what}", 6000)

        return self.run_task(lambda: fn(pattern().generate(d), d), done)

    def _save_name(self, title, ext, filt):
        stem = Path(self.path).name.removesuffix(".vent.json") if self.path else self.design.name
        p, _ = QFileDialog.getSaveFileName(self, title, str(Path(self.path or self.lib_folder / "x").parent /
                                                            (stem + ext)), filt)
        return p and (p if p.lower().endswith(ext) else p + ext)

    def export_as(self, ext):
        if p := self._save_name(f"Export {ext[1:].upper()}", ext, f"{ext[1:].upper()} (*{ext})"):
            self.run_export(lambda r, d: exporter().export(r, d, p), p)

    def _dialog(self, title, rows):
        dlg = QDialog(self)
        dlg.setWindowTitle(title)
        f = QFormLayout(dlg)
        for label, w in rows:
            f.addRow(label, w)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        f.addRow(bb)
        return dlg.exec() == QDialog.Accepted

    @staticmethod
    def _spin(v, lo=-10000, hi=10000, suffix=" mm", special=None):
        s = QDoubleSpinBox(decimals=3, minimum=lo, maximum=hi, value=v, suffix=suffix)
        if special:
            s.setSpecialValueText(special)
        return s

    def _xyz(self, v):
        spins = [self._spin(x, suffix="") for x in v]
        return row(*spins), spins

    def wrap_dialog(self):
        c = self.design.canvas
        rad = self._spin(c.width / (2 * math.pi), 0, 10000)
        wall = self._spin(c.thickness, 0.01, 1000)
        hgt = self._spin(c.height, 0, 10000)
        if not self._dialog("Wrap onto cylinder", [("Radius", rad), ("Wall", wall), ("Height", hgt)]):
            return
        if p := self._save_name("Save cylinder", ".step", "STEP (*.step);;STL (*.stl)"):
            a = dict(radius=rad.value(), wall=wall.value(), height=hgt.value())
            self.run_export(lambda r, d: exporter().wrap_cylinder(r, d, p, **a), p)

    def cut_dialog(self):
        part = QLineEdit()
        pick = button("…", lambda: part.setText(QFileDialog.getOpenFileName(
            self, "Part", "", "STEP (*.step *.stp)")[0] or part.text()))
        (ow, o), (nw, n), (xw, x) = self._xyz((0, 0, 0)), self._xyz((0, 0, 1)), self._xyz((1, 0, 0))
        depth = self._spin(0, 0, 1000, special="auto (through)")
        if not self._dialog("Cut into part", [("Part (STEP)", row(part, pick)), ("Origin", ow), ("Normal", nw),
                                              ("X direction", xw), ("Depth", depth)]):
            return
        if not part.text():
            return
        if p := self._save_name("Save cut part", ".step", "STEP (*.step)"):
            a = dict(origin=tuple(s.value() for s in o), normal=tuple(s.value() for s in n),
                     x_dir=tuple(s.value() for s in x), depth=depth.value() or None)
            src = part.text()
            self.run_export(lambda r, d: exporter().cut_into_part(r, d, src, p, **a), p)

    def closeEvent(self, e):
        if not self.maybe_save():
            e.ignore()
            return
        self.regen_timer.stop()
        self.thumb_queue = []
        for t in list(self.tasks):
            t.wait()
        e.accept()


def dark_theme(app):
    app.setStyle("Fusion")
    p = QPalette()
    for role, c in ((QPalette.Window, (45, 46, 50)), (QPalette.WindowText, (225, 225, 225)),
                    (QPalette.Base, (32, 33, 36)), (QPalette.AlternateBase, (45, 46, 50)),
                    (QPalette.Text, (225, 225, 225)), (QPalette.Button, (55, 56, 61)),
                    (QPalette.ButtonText, (225, 225, 225)), (QPalette.Highlight, (247, 187, 59)),
                    (QPalette.HighlightedText, (20, 20, 20)), (QPalette.ToolTipBase, (60, 60, 64)),
                    (QPalette.ToolTipText, (230, 230, 230)), (QPalette.PlaceholderText, (140, 140, 140))):
        p.setColor(role, QColor(*c))
    p.setColor(QPalette.Disabled, QPalette.Text, QColor(120, 120, 120))
    p.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(120, 120, 120))
    app.setPalette(p)
    app.setStyleSheet(QSS)


ACCENT = "#2E7D4F"
QSS = f"""
QWidget {{ font-size: 10pt; }}
QDockWidget::title {{ background:#2a2b2f; padding:8px; font-weight:bold; }}
QScrollArea, QScrollArea > QWidget > QWidget {{ background:#2d2e32; border:none; }}
QToolButton[section="big"] {{ border:none; border-bottom:1px solid #3c3d43; font-weight:bold; font-size:11pt;
    padding:8px 2px; text-align:left; }}
QToolButton[section="small"] {{ border:none; color:#a8a8b0; padding:4px 2px; }}
QToolButton[tile="true"] {{ background:#36373c; border:1px solid #3f4046; border-radius:8px; padding:4px;
    font-size:8.5pt; }}
QToolButton[tile="true"]:hover {{ border-color:#6a6b72; }}
QToolButton[tile="true"]:checked {{ border:2px solid {ACCENT}; background:#33433a; }}
QToolButton[seg="true"] {{ background:#36373c; border:1px solid #45464c; border-radius:6px; padding:5px 8px; }}
QToolButton[seg="true"]:checked {{ background:{ACCENT}; color:white; font-weight:bold; border-color:{ACCENT}; }}
QToolButton#export {{ background:{ACCENT}; color:white; font-weight:bold; border-radius:6px; padding:5px 10px; }}
QPushButton {{ background:#3a3b40; border:1px solid #4a4b52; border-radius:6px; padding:5px 10px; }}
QPushButton:hover {{ background:#45464c; }}
QSlider::groove:horizontal {{ height:4px; background:#4a4b52; border-radius:2px; }}
QSlider::sub-page:horizontal {{ background:{ACCENT}; border-radius:2px; }}
QSlider::handle:horizontal {{ background:#f2f2f2; width:14px; height:14px; margin:-6px 0; border-radius:7px; }}
QSlider::handle:horizontal:hover {{ background:white; border:2px solid {ACCENT}; }}
QSlider:disabled::sub-page:horizontal {{ background:#5a5b62; }}
QLineEdit, QComboBox {{ background:#232428; border:1px solid #45464c; border-radius:5px; padding:3px 6px; }}
QAbstractSpinBox {{ background:#232428; border:1px solid #45464c; border-radius:5px; padding-right:4px; }}
QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {{ width:0; border:none; }}
QAbstractSpinBox:focus, QLineEdit:focus {{ border-color:{ACCENT}; }}
QTabBar::tab {{ background:#36373c; padding:6px 12px; border-top-left-radius:6px; border-top-right-radius:6px;
    margin-right:2px; }}
QTabBar::tab:selected {{ background:{ACCENT}; color:white; font-weight:bold; }}
QWidget#zoombar {{ background:rgba(40,41,45,220); border:1px solid #4a4b52; border-radius:8px; }}
QWidget#zoombar QToolButton {{ background:transparent; border:none; font-size:12pt; padding:0 6px; }}
QWidget#zoombar QToolButton:hover {{ background:#4a4b52; border-radius:5px; }}
QToolBar {{ spacing:4px; padding:4px; background:#26272b; border:none; }}
"""


def main(argv=None):
    argv = sys.argv if argv is None else argv
    app = QApplication.instance() or QApplication(argv)
    dark_theme(app)
    w = MainWindow(argv[1] if len(argv) > 1 else None)
    w.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
