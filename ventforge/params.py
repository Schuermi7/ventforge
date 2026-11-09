"""What each design parameter is called, what it does, and when it matters. Shared by the editor (labels,
tooltips, hiding what does nothing) and the MCP server (describe_parameters, set_params' no_effect)."""
from __future__ import annotations

from .model import GRADS, Design


# ---------------------------------------------------------------- names shown to people
# Labels by full path first, then by field name. Model names stay as they are (files, MCP).
LABELS = {
    "canvas.relief": "Pattern is", "canvas.relief_depth": "Texture depth", "canvas.thickness": "Plate thickness",
    "boundary.type": "Outline", "boundary.margin": "Edge margin", "boundary.clip": "Cut holes off at the edge",
    "boundary.vent_diameter": "Fan opening Ø", "min_wall": "Thinnest wall allowed",
    "machining.tool_radius": "CNC tool radius", "machining.kerf": "Laser kerf",
    "machining.min_feature": "Smallest printable hole",
    "dot.shape": "Hole shape", "dot.diameter": "Hole size", "dot.aspect": "Height ÷ width",
    "dot.sides": "Corners", "dot.star_inner": "Inner size", "dot.rotation": "Turn holes",
    "pattern.mode": "Layout",
    "pattern.grid.spacing_x": "Spacing", "pattern.grid.spacing_y": "Row spacing",
    "pattern.grid.row_rotation": "Turn every other row by", "pattern.grid.rotate_by": "Every other",
    "pattern.crosslines.row_rotation": "Turn every other hole by", "pattern.crosslines.rotate_by": "Alternate along",
    "pattern.crosslines.left_angle": "First lines at", "pattern.crosslines.right_angle": "Second lines at",
    "pattern.crosslines.left_spacing": "First line spacing", "pattern.crosslines.right_spacing": "Second line spacing",
    "pattern.random.min_distance": "Min. centre distance",
    "pattern.path.count": "Holes on the path", "pattern.path.layers": "Rows", "pattern.path.layer_spacing": "Row spacing",
    "pattern.path.closed": "Closed loop", "pattern.path.smooth": "Smooth curve",
    "pattern.path.align": "Turn holes along the path",
    "pattern.spiral.radius": "Outer radius", "pattern.spiral.align": "Turn holes along the spiral",
    "pattern.spiral.even_spacing": "Even spacing along the spiral",
    "pattern.concentric.dot_spacing": "Hole spacing on a ring", "pattern.concentric.stagger": "Offset every other ring",
    "pattern.concentric.align": "Turn holes along the rings",
    "pattern.fibonacci.spread": "Spacing", "pattern.fibonacci.inner_radius": "Empty centre radius",
    "pattern.fibonacci.align": "Turn holes outward",
    "pattern.voronoi.crack_width": "Wall width", "pattern.voronoi.corner_radius": "Corner rounding",
    "pattern.flowlines.edge_style": "Slot ends", "pattern.flowlines.follow_boundary": "Follow the outline",
    "pattern.flowlines.invert": "Swap slots and bars", "pattern.flowlines.amplitude": "Wave height",
    "pattern.flowlines.wavelength": "Wave length",
    "gradients.target_shape": "Morph into", "gradients.target_sides": "Corners",
    "count": "Number of holes", "rotation": "Turn pattern", "inner_radius": "Inner radius",
    "outer_radius": "Outer radius", "seed": "Variant", "offset_x": "Shift X", "offset_y": "Shift Y",
    "line_width": "Slot width", "line_spacing": "Slot spacing", "falloff": "Blend", "noise": "Amount",
    "noise_scale": "Randomness size", "image_min": "Value at black", "image_max": "Value at white",
    "invert_image": "Invert the image", "width": "Width", "height": "Height", "radius": "Reach",
}
# text on choice buttons, by full path first, then by value
CHOICE_TEXT = {
    "boundary.type": {"none": "Rectangle", "rounded_rectangle": "Rounded", "custom": "Drawn"},
    "canvas.relief": {"through": "Cut through", "deboss": "Sunk in", "emboss": "Raised"},
    "pattern.grid.arrangement": {"diamond": "Offset rows", "hexagon": "Honeycomb"},
    "pattern.grid.rotate_by": {"row": "Row", "col": "Column", "both": "Chessboard"},
    "pattern.crosslines.rotate_by": {"left": "First lines", "right": "Second lines", "both": "Chessboard"},
    "pattern.flowlines.edge_style": {"flat": "Square", "round": "Round"},
    "pattern.mode": {"path": "Along a path", "concentric": "Rings", "fibonacci": "Sunflower",
                     "crosslines": "Crossing lines", "voronoi": "Cracks", "flowlines": "Slots",
                     "custom_points": "Your points"},
    "dot.shape": {"rounded_rectangle": "Rounded", "custom": "Drawn"},
    "gradients.target_shape": {},
}
TIPS = {
    "canvas.relief": "Through: holes go through the plate. Sunk in (deboss) or raised (emboss): the pattern is a "
                     "texture of the texture depth. Shows in 3D exports (STEP, STL) and the Fusion add-in.",
    "canvas.thickness": "Plate thickness of 3D exports (STEP, STL).",
    "boundary.margin": "Holes keep at least this distance from the plate edge.",
    "boundary.clip": "Off: holes that cross the edge margin are left out. On: they are cut off along it.",
    "boundary.vent_diameter": "Holes only inside a centred circle of this diameter (a fan's opening). 0 = off.",
    "min_wall": "Check: walls between holes thinner than this are counted and marked in red.",
    "machining.tool_radius": "CNC: inside corners get this radius, and holes the cutter cannot enter are left out.",
    "machining.kerf": "Laser / waterjet cut width. SVG and DXF paths are moved by half of it so parts come out true.",
    "machining.min_feature": "Check: holes narrower than this are counted (3D printing: about 2× the nozzle).",
    "dot.diameter": "Outer width of a hole.",
    "dot.star_inner": "Size of the inner corners of the star, compared with the outer ones.",
    "pattern.random.min_distance": "No two hole centres get closer than this.",
    "pattern.random.count": "Holes that do not fit at the minimum distance are left out.",
    "pattern.fibonacci.spread": "Distance between neighbouring holes (radius grows with spacing × √n).",
    "pattern.fibonacci.count": "More holes than fit on the plate add nothing; the slider stops where it is full.",
    "pattern.voronoi.irregularity": "0 % = regular hexagons, 100 % = fully random cells.",
    "pattern.flowlines.follow_boundary": "Slots run parallel to the plate outline instead of straight.",
    "pattern.concentric.outer_radius": "0 = fill the plate.",
    "seed": "Another random layout with the same settings.",
    "falloff": "How the value fades from the control to everywhere else.",
    "noise": "Varies the value randomly across the plate. 0 = off, 1 = up to ±100 % (Turn: ±90°, Morph: ±1).",
    "noise_scale": "Size of the random blotches.",
    "radius": "Distance over which the control fades out.",
}
MODE_INFO = {
    "grid": "Rows and columns of holes.",
    "random": "Holes scattered at random, never closer than a minimum distance.",
    "path": "Holes along a line you draw, in one or more rows.",
    "spiral": "Holes along a spiral.",
    "concentric": "Holes on rings around the centre.",
    "fibonacci": "The sunflower seed pattern: even density, no rows.",
    "crosslines": "Holes where two sets of parallel lines cross.",
    "voronoi": "Cell-shaped holes with walls between them, like cracked stone. Makes its own hole shapes.",
    "flowlines": "Long slots, straight, wavy or following the outline. Makes its own hole shapes.",
    "custom_points": "Holes exactly where you click.",
}
GRAD_INFO = {  # what a gradient does, and how its numbers read
    "size": ("Size", "Make holes bigger or smaller in places. 1 = as set, 0.5 = half size.",
             "Size at the control", "Size everywhere else"),
    "spacing": ("Spacing", "Pack holes tighter or looser in places. 1 = as set, 2 = twice as far apart.",
                "Spacing at the control", "Spacing everywhere else"),
    "angle": ("Turn", "Turn holes by different amounts across the plate (degrees).",
              "Turn at the control", "Turn everywhere else"),
    "shape": ("Morph", "Blend the hole shape into another shape in places. 0 = own shape, 1 = the target.",
              "Morph at the control", "Morph everywhere else"),
}
DRAW = {  # canvas drawing targets: fewest points, what to do
    "outline": (3, "Click the corners of the plate outline"), "path": (2, "Click along the path"),
    "points": (1, "Click where holes go"), "hole": (3, "Click the corners of the hole shape, at any size"),
}
OWN_SHAPES = ("voronoi", "flowlines")  # layouts that make their own hole outlines
SPACING_MODES = ("grid", "random", "spiral", "concentric", "fibonacci", "crosslines")  # follow the spacing gradient
# shown, but only change exports or the checks, never the holes in the preview
NOT_IN_PREVIEW = {"canvas.thickness", "canvas.relief", "canvas.relief_depth", "machining.kerf",
                  "machining.min_feature", "min_wall", "background.opacity"}


def hidden(d: Design) -> set:
    """Parameter paths that cannot change anything in this design, so the panel hides them. Whole groups:
    "dot" (the layout makes its own hole shapes) and "gradients.<name>" (that gradient has no effect)."""
    m, dot, gr, h = d.pattern.mode, d.dot, d.gradients, set()
    own = m in OWN_SHAPES
    morph = gr.shape.enabled and not own
    turns = not own and (dot.shape != "circle" or morph)  # a circle looks the same however it is turned
    if d.boundary.type != "rounded_rectangle":
        h.add("boundary.corner_radius")
    if d.boundary.type != "custom":
        h.add("boundary.points")
    if m == "flowlines" or m == "random" and not gr.size.enabled:  # random keeps same-size holes inside; slots are always cut
        h.add("boundary.clip")
    if d.canvas.relief == "through":
        h.add("canvas.relief_depth")
    if own:
        h.add("dot")
    if dot.shape != "rounded_rectangle":
        h |= {"dot.aspect", "dot.corner_radius"}
    if dot.shape != "polygon":
        h.add("dot.sides")
    if dot.shape != "custom":
        h.add("dot.custom_points")
    if dot.shape != "star" and not (morph and gr.target_shape == "star"):
        h |= {"dot.star_points", "dot.star_inner"}
    if not turns:
        h |= {"dot.rotation", "pattern.path.align", "pattern.spiral.align", "pattern.concentric.align",
              "pattern.fibonacci.align", "gradients.angle"}
    for lay in ("grid", "crosslines"):
        p = getattr(d.pattern, lay)
        if not turns:
            h |= {f"pattern.{lay}.row_rotation", f"pattern.{lay}.rotate_by"}
        elif p.row_rotation % 360 == 0:
            h.add(f"pattern.{lay}.rotate_by")
    if d.pattern.grid.arrangement == "hexagon":
        h.add("pattern.grid.spacing_y")  # the honeycomb pitch follows the spacing
    pa = d.pattern.path
    if len(pa.points) < 2:
        h |= {"pattern.path.closed", "pattern.path.smooth"}  # the default path is a circle
    elif len(pa.points) < 3:
        h.add("pattern.path.smooth")
    if pa.layers <= 1:
        h.add("pattern.path.layer_spacing")
    fl = d.pattern.flowlines
    if fl.follow_boundary or fl.amplitude == 0:
        h |= {"pattern.flowlines.wavelength", "pattern.flowlines.seed"}
    if fl.follow_boundary:
        h.add("pattern.flowlines.amplitude")
    if fl.follow_boundary or fl.invert:
        h.add("pattern.flowlines.edge_style")
    if m not in SPACING_MODES:
        h.add("gradients.spacing")
    if own:
        h |= {"gradients.angle", "gradients.shape"}
    for g in GRADS:
        x, p = getattr(gr, g), f"gradients.{g}."
        if x.image:  # an image replaces the far value and the controls
            h |= {p + "edge", p + "controls", p + "falloff"}
        else:
            h |= {p + "image_min", p + "image_max", p + "invert_image"}
        if not x.controls:
            h.add(p + "falloff")
        if x.noise == 0:
            h |= {p + "noise_scale", p + "noise_seed"}
    if own:
        h |= {"gradients.target_shape", "gradients.target_sides"}
    elif gr.target_shape != "polygon":
        h.add("gradients.target_sides")
    if gr.target_shape == dot.shape and (dot.shape != "polygon" or gr.target_sides == dot.sides):
        h.add("gradients.shape.body")  # morphing into the shape the holes already have changes nothing
    else:
        h.add("gradients.shape.same")
    return h


def grad_of(path):
    """The variation a parameter belongs to, if editing it should switch that variation on."""
    parts = path.split(".")
    if path.startswith("gradients.target_"):
        return "shape"
    return parts[1] if len(parts) == 3 and parts[0] == "gradients" and parts[2] != "enabled" else None


def label_for(name, path=""):
    return LABELS.get(path) or LABELS.get(name) or name.replace("_", " ").capitalize()


def choice_text(path, value):
    return CHOICE_TEXT.get(path, {}).get(value) or value.replace("_", " ").capitalize()


def switch_on(d: Design, path: str, v) -> bool:
    """Editing a switched-off variation would do nothing, so it switches that variation on (not for Clear).
    Returns True when it did."""
    g = grad_of(path)
    if g is None or v == "" or getattr(d.gradients, g).enabled:
        return False
    getattr(d.gradients, g).enabled = True
    return True


def no_effect(d: Design, path: str, hide: set | None = None) -> bool:
    """True when changing this parameter cannot change the holes or exports of this design."""
    hide = hidden(d) if hide is None else hide
    parts = path.split(".")
    if parts[0] == "pattern" and len(parts) > 2 and parts[1] != d.pattern.mode:
        return True  # another layout's setting
    if parts[0] == "gradients" and len(parts) == 3 and parts[2] != "enabled" and f"gradients.{parts[1]}.body" in hide:
        return True
    return any(".".join(parts[:i]) in hide for i in range(1, len(parts) + 1))


def help_text(path: str) -> str:
    """The editor's label for a parameter, plus its tooltip."""
    name = path.rsplit(".", 1)[-1]
    tip = TIPS.get(path) or TIPS.get(name)
    return label_for(name, path) + (f": {tip}" if tip else "")
