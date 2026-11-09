"""Every control the panel shows must change the holes; what params.no_effect hides (and the MCP reports) must not."""
import hashlib
from dataclasses import fields, is_dataclass
from typing import get_type_hints

import numpy as np
import pytest

pytest.importorskip("PySide6")
import shapely

from ventforge import gui, params
from ventforge.model import CHOICES, GRADS, MODES, SHAPES, Control, Design
from ventforge.pattern import generate

SKIP_NAMES = {"image", "color", "name", "version", "enabled", "mode"}  # enabled alone with defaults is a no-op on purpose


def leaves(obj, path=""):
    hints = get_type_hints(type(obj))
    for f in fields(obj):
        v, p = getattr(obj, f.name), f"{path}{f.name}"
        if is_dataclass(v):
            yield from leaves(v, p + ".")
        elif isinstance(v, (bool, int, float, str)) and f.name not in SKIP_NAMES:
            yield p, f.name, hints[f.name], v


def shown(d, path, hide):
    """On screen and changes the preview (the rest of NOT_IN_PREVIEW only changes exports and checks)."""
    return path not in params.NOT_IN_PREVIEW and not params.no_effect(d, path, hide)


def sig(d):
    """Exact holes, and what you see of them: a turned circle is a different polygon but looks the same."""
    holes = generate(d).holes
    exact = hashlib.md5(b"".join(shapely.to_wkb(shapely.set_precision(h, 0.001)) for h in holes)).hexdigest()
    seen = np.array([(c.x, c.y, h.area) for h, c in zip(holes, shapely.centroid(holes))]).reshape(-1, 3)
    return exact, seen


def looks_same(a, b):
    """Same holes in the same places, within 0.1 (mm, mm²), in any order."""
    return len(a) == len(b) and (len(a) == 0 or np.abs(a[:, None] - b[None]).max(-1).min(1).max() < 0.1)


def setp(d, path, v):
    *h, k = path.split(".")
    o = d
    for x in h:
        o = getattr(o, x)
    setattr(o, k, v)
    if g := params.grad_of(path):
        getattr(d.gradients, g).enabled = True  # what MainWindow.set_param does


def variants(path, name, t, v):
    if t is bool:
        return [not v]
    if t is str:
        return [c for c in (CHOICES.get(path) or CHOICES.get(name) or ()) if c != v]
    lo, hi, _, _ = gui.meta(name, t, path)
    vals = [v + 1, v * 2, v + 7, v - 1, v // 4] if t is int else [v * 1.5 + 0.7, v * 0.6 + 0.3, v - 0.9, v + 5]
    return [t(min(hi, max(lo, x))) for x in vals if min(hi, max(lo, x)) != v]


def state(mode, shape, grads):
    d = Design()
    d.pattern.mode = mode
    d.dot.shape = shape
    d.canvas.width = d.canvas.height = 60.0  # small plate, few holes: the test regenerates thousands of times
    # drawn layouts reach the plate edge, so the outline and margin have something to cut
    if mode == "custom_points":
        d.pattern.custom_points.points = [[x, y] for x in range(-25, 26, 5) for y in range(-25, 26, 5)] + [[29, 0]]
    if mode == "path":
        d.pattern.path.points = [[-29.0, -25.0], [0.0, 15.0], [29.0, -25.0]]
    if mode == "spiral":
        d.pattern.spiral.radius = 45.0  # just past the corners
    if mode == "fibonacci":
        d.pattern.fibonacci.count = 80  # reaches the edge but not the corners of this small plate
    if shape == "custom":
        d.dot.custom_points = [[0, 0], [1, 0], [0.5, 1]]
    if grads:
        for g in GRADS:
            gr = getattr(d.gradients, g)
            gr.enabled, gr.noise = True, 0.3
            gr.controls = [Control(points=[[10.0, 5.0]], value={"size": 1.6, "spacing": 1.5, "angle": 40,
                                                               "shape": 0.6}[g], radius=40)]
    return d


# every layout with round holes, with and without variations; every hole shape on the grid
CASES = [(m, "circle", g) for m in MODES for g in (False, True)] + [(m, "star", False) for m in MODES]
CASES += [("grid", s, g) for s in SHAPES if s != "circle" for g in (False, True)]


@pytest.mark.parametrize("mode,shape,grads", CASES)
def test_shown_controls_change_holes(mode, shape, grads):
    d0 = state(mode, shape, grads)
    s0, hide, dead, live = sig(d0), params.hidden(d0), [], []
    for path, name, t, v in leaves(d0):
        if path.startswith("gradients.target_") and not d0.gradients.shape.enabled:
            continue  # like the on/off switch: a target alone morphs nothing until there is an amount
        if path.startswith("pattern.") and not path.startswith(f"pattern.{mode}."):
            continue  # another layout's settings: not used, by construction
        off = params.no_effect(d0, path, hide)
        if off and shape == "circle" and ("rotation" in path or path.endswith(".align")):
            continue  # a turned circle polygon can tip one hole at the very edge in or out; not a real setting
        if off:  # hidden: must not change what you see
            ref = sig(_with(d0, path, v))[1] if params.grad_of(path) else s0[1]  # switching it on is not the edit
            if any(not looks_same(sig(_with(d0, path, nv))[1], ref) for nv in variants(path, name, t, v)[:2]):  # 2 keep it fast
                live.append(path)
        elif shown(d0, path, hide):  # shown: must change the holes
            if all(sig(_with(d0, path, nv))[0] == s0[0] for nv in variants(path, name, t, v)):
                dead.append(path)
    assert not dead, f"shown but no effect: {dead}"
    assert not live, f"hidden but has an effect: {live}"


def _with(d0, path, v):
    d = Design.from_dict(d0.to_dict())
    setp(d, path, v)
    return d


def test_count_slider_stops_near_full_plate():
    d = Design()
    d.pattern.mode = "fibonacci"
    _, hi = gui.fill_soft("pattern.fibonacci.count", d)
    d.pattern.fibonacci.count = hi
    full = len(generate(d).holes)
    d.pattern.fibonacci.count = hi * 2
    assert len(generate(d).holes) <= full * 1.1  # past the slider end almost nothing is added
