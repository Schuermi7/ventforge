"""Design model: every parameter of a vent design, stored as JSON (*.vent.json).

Coordinates are millimetres, origin at the canvas centre, x right, y UP (CAD convention).
The GUI flips y for display. All angles are degrees, counter-clockwise.
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import get_type_hints

Pt = list[float]  # [x, y]

SHAPES = ("circle", "rounded_rectangle", "hexagon", "polygon", "star", "custom")
MODES = ("grid", "random", "path", "spiral", "concentric", "fibonacci",
         "crosslines", "voronoi", "flowlines", "custom_points")
BOUNDARIES = ("none", "circle", "rounded_rectangle", "custom")
TARGET_SHAPES = ("circle", "rectangle", "polygon", "star")
# allowed values of text fields, by full path or (fallback) field name; used by the GUI, the MCP
# server and _build, which rejects anything else
CHOICES = {
    "arrangement": ("square", "diamond", "hexagon"), "edge_style": ("flat", "round"),
    "falloff": ("linear", "smooth"), "shape": SHAPES, "type": BOUNDARIES, "target_shape": TARGET_SHAPES,
    "mode": MODES, "kind": ("point", "line", "curve"),
    "pattern.grid.rotate_by": ("row", "col", "both"),
    "pattern.crosslines.rotate_by": ("left", "right", "both"),
}


@dataclass
class Canvas:
    width: float = 100.0
    height: float = 100.0
    thickness: float = 2.0  # plate thickness for 3D exports


@dataclass
class Boundary:
    type: str = "none"            # BOUNDARIES; "none" = the canvas rectangle
    corner_radius: float = 10.0   # rounded_rectangle
    margin: float = 2.0           # min distance from holes to the boundary edge
    points: list[Pt] = field(default_factory=list)  # custom outline polygon
    clip: bool = False            # False: drop holes crossing the edge; True: clip them


@dataclass
class DotStyle:
    shape: str = "circle"         # SHAPES
    diameter: float = 4.0         # outer size (circumscribed width)
    aspect: float = 1.0           # rounded_rectangle height / width
    corner_radius: float = 0.5    # rounded_rectangle
    sides: int = 6                # polygon
    star_points: int = 5
    star_inner: float = 0.5       # inner radius ratio of star
    rotation: float = 0.0
    custom_points: list[Pt] = field(default_factory=list)  # unit shape, scaled to diameter
    color: str = "#2E7D4F"        # display only


@dataclass
class Grid:
    arrangement: str = "diamond"  # square | diamond (staggered rows) | hexagon (honeycomb pitch)
    spacing_x: float = 6.0
    spacing_y: float = 6.0
    offset_x: float = 0.0
    offset_y: float = 0.0
    rotation: float = 0.0          # whole grid
    row_rotation: float = 0.0      # extra dot rotation applied to alternate rows/cols
    rotate_by: str = "row"         # row | col | both (chessboard)


@dataclass
class RandomP:
    count: int = 300
    min_distance: float = 5.0      # Poisson-disc style rejection
    seed: int = 1


@dataclass
class PathP:
    points: list[Pt] = field(default_factory=list)  # empty = default circle
    closed: bool = True
    smooth: bool = True            # Catmull-Rom through points
    count: int = 40                # dots on the base path; other layers scale by length
    layers: int = 1                # parallel offset copies of the path
    layer_spacing: float = 6.0
    align: bool = True             # rotate dots to path tangent


@dataclass
class Spiral:
    radius: float = 45.0
    turns: float = 5.0
    inner_radius: float = 3.0
    count: int = 120
    rotation: float = 0.0
    even_spacing: bool = True      # equal arc length between dots
    align: bool = True


@dataclass
class Concentric:
    ring_spacing: float = 6.0
    dot_spacing: float = 6.0       # arc distance between dots on a ring
    inner_radius: float = 0.0      # 0 = a dot in the centre
    outer_radius: float = 0.0      # 0 = fill the boundary
    rotation: float = 0.0
    stagger: bool = True           # offset alternate rings by half a step
    align: bool = True


@dataclass
class Fibonacci:
    count: int = 400
    spread: float = 3.5            # c in r = c * sqrt(n)
    inner_radius: float = 0.0
    rotation: float = 0.0
    align: bool = False


@dataclass
class Crosslines:
    left_angle: float = 60.0
    right_angle: float = 120.0
    left_spacing: float = 6.0
    right_spacing: float = 6.0
    rotation: float = 0.0
    row_rotation: float = 0.0
    rotate_by: str = "both"        # left | right | both — dots sit at line intersections


@dataclass
class Voronoi:
    cell_size: float = 8.0
    irregularity: float = 60.0     # percent jitter
    crack_width: float = 1.2       # wall width between cells (holes are shrunken cells)
    corner_radius: float = 0.5
    rotation: float = 0.0
    seed: int = 1


@dataclass
class Flowlines:
    line_spacing: float = 5.0
    line_width: float = 2.0        # slot width
    rotation: float = 0.0
    edge_style: str = "round"      # flat | round slot ends
    follow_boundary: bool = False  # lines are offsets of the boundary instead of straight
    invert: bool = False           # swap lines and gaps
    amplitude: float = 3.0         # waviness
    wavelength: float = 30.0
    seed: int = 1


@dataclass
class CustomPoints:
    """Explicit dots, e.g. written by an AI through MCP. size/angle optional per dot."""
    points: list[Pt] = field(default_factory=list)
    sizes: list[float] = field(default_factory=list)   # multipliers of DotStyle.diameter
    angles: list[float] = field(default_factory=list)  # added to DotStyle.rotation


@dataclass
class Pattern:
    mode: str = "grid"             # MODES
    grid: Grid = field(default_factory=Grid)
    random: RandomP = field(default_factory=RandomP)
    path: PathP = field(default_factory=PathP)
    spiral: Spiral = field(default_factory=Spiral)
    concentric: Concentric = field(default_factory=Concentric)
    fibonacci: Fibonacci = field(default_factory=Fibonacci)
    crosslines: Crosslines = field(default_factory=Crosslines)
    voronoi: Voronoi = field(default_factory=Voronoi)
    flowlines: Flowlines = field(default_factory=Flowlines)
    custom_points: CustomPoints = field(default_factory=CustomPoints)


@dataclass
class Control:
    kind: str = "point"            # point | line | curve (smooth polyline)
    points: list[Pt] = field(default_factory=lambda: [[0.0, 0.0]])
    value: float = 0.2             # field value AT the control
    radius: float = 50.0           # falloff distance to the edge value


@dataclass
class Gradient:
    """A scalar field over the canvas. Far from all controls it equals `edge`."""
    enabled: bool = False
    controls: list[Control] = field(default_factory=list)
    edge: float = 1.0              # value far away (neutral: 1 for size/spacing, 0 for angle/shape)
    falloff: str = "smooth"        # linear | smooth
    noise: float = 0.0             # 0..1 amplitude, relative
    noise_scale: float = 20.0      # mm feature size
    noise_seed: int = 1
    image: str = ""                # grayscale image path used as the field (fit to canvas)
    image_min: float = 0.2         # value at black
    image_max: float = 1.0         # value at white
    invert_image: bool = False


@dataclass
class Gradients:
    size: Gradient = field(default_factory=Gradient)           # multiplier on diameter
    spacing: Gradient = field(default_factory=Gradient)        # local spacing multiplier
    angle: Gradient = field(default_factory=lambda: Gradient(edge=0.0))   # degrees added
    shape: Gradient = field(default_factory=lambda: Gradient(edge=0.0))   # 0..1 morph to target
    target_shape: str = "star"     # TARGET_SHAPES
    target_sides: int = 4          # for target polygon


@dataclass
class Background:
    image: str = ""                # reference image shown under the pattern (GUI only)
    opacity: float = 0.5


@dataclass
class Design:
    name: str = "Untitled"
    canvas: Canvas = field(default_factory=Canvas)
    boundary: Boundary = field(default_factory=Boundary)
    dot: DotStyle = field(default_factory=DotStyle)
    pattern: Pattern = field(default_factory=Pattern)
    gradients: Gradients = field(default_factory=Gradients)
    background: Background = field(default_factory=Background)
    min_wall: float = 0.8          # holes closer than this are flagged in stats
    version: int = 1

    # ---- (de)serialisation -------------------------------------------------
    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Design":
        return _build(cls, d)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def load(cls, path: str | Path) -> "Design":
        d = cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))
        return d.resolve_images(Path(path).resolve().parent)

    def resolve_images(self, base: str | Path) -> "Design":
        """Make relative image paths absolute against `base` (the design file's folder), so the GUI
        and the MCP server, which run from different working folders, find the same files."""
        for g in (self.gradients.size, self.gradients.spacing, self.gradients.angle, self.gradients.shape,
                  self.background):
            if g.image and not Path(g.image).is_absolute():
                g.image = str((Path(base) / g.image).resolve())
        return self

    def save(self, path: str | Path) -> None:
        p = Path(path)
        d = self.to_dict()
        base = p.resolve().parent
        for g in [*d["gradients"].values(), d["background"]]:  # images next to the file stay relative,
            if isinstance(g, dict) and g["image"]:            # so the folder can be moved or shared
                img = Path(g["image"])
                if img.is_absolute() and img.resolve().is_relative_to(base):
                    g["image"] = img.resolve().relative_to(base).as_posix()
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_text(json.dumps(d, indent=2), encoding="utf-8")
        for i in range(6):  # atomic replace, so a watching GUI never reads half a file
            try:
                return tmp.replace(p)
            except PermissionError:  # Windows: AV/indexer/a reader briefly holds the target
                if i == 5:
                    raise
                time.sleep(0.05 * (i + 1))

    def patched(self, patch: dict) -> "Design":
        """Deep-merge a partial dict, e.g. {"dot": {"diameter": 3}}. Unknown keys raise."""
        return Design.from_dict(_merge(self.to_dict(), patch))


def _merge(base: dict, patch: dict, path: str = "") -> dict:
    out = dict(base)
    for k, v in patch.items():
        if k not in base:
            raise KeyError(f"unknown parameter: {path}{k}")
        out[k] = _merge(base[k], v, f"{path}{k}.") if isinstance(v, dict) and isinstance(base[k], dict) else v
    return out


def _build(cls, d: dict, path: str = ""):
    hints = get_type_hints(cls)
    kw = {}
    for f in fields(cls):
        if f.name not in d:
            continue
        t, v, p = hints[f.name], d[f.name], path + f.name
        if is_dataclass(t):
            kw[f.name] = _build(t, v or {}, p + ".")
        elif getattr(t, "__origin__", None) is list and t.__args__[0] is Control:
            kw[f.name] = [_build(Control, c, p + ".") for c in v]
        elif t is float:
            kw[f.name] = float(v)
        elif t is int:
            kw[f.name] = int(v)
        else:
            opts = CHOICES.get(p) or (CHOICES.get(f.name) if t is str else None)
            if opts and v not in opts:
                raise ValueError(f"{p} must be one of {', '.join(opts)}; got {v!r}")
            kw[f.name] = v
    return cls(**kw)


@dataclass
class Result:
    """Output of pattern.generate(design). Shared by exporters, GUI and MCP."""
    holes: list            # shapely Polygons, mm, y-up, already clipped/filtered to the outline
    outline: object        # shapely Polygon: the plate outline (canvas rect or boundary shape)
    stats: dict            # count, open_area_ratio (0..1), hole_area, plate_area, min_wall_violations
    circles: list = field(default_factory=list)  # per hole: (cx, cy, r) if it is an exact unclipped circle, else None
    # (lets SVG/DXF/STEP write true circles instead of polygons; same length as holes, or empty)
