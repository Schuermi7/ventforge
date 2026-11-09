"""Geometry core: turn a Design into hole polygons.

    generate(design) -> Result         the whole pipeline
    outline_of(design) -> Polygon      plate outline (canvas rect or boundary shape)
    sample_gradient(g, xy, canvas, neutral, span) -> ndarray   evaluate one gradient field at points

Pipeline for dot modes: mode points (+angle, +size multiplier) -> spacing warp -> size/angle/shape
fields -> one template outline per dot, built vectorised with numpy + shapely.polygons ->
margin / clip filter -> stats. Voronoi and flowlines build their polygons directly.

Spacing gradient semantics (approximation): the point set is first scaled about the origin by
`edge`, then warped radially around each control in turn (points move along the direction away
from the nearest point of the control). A point at distance d moves to h(d) = integral_0^d of
value(s)/edge ds, so local spacing near a control is ~value/edge times the far spacing and density
scales by ~1/value. Beyond `radius` the offset is constant (far points are pulled/pushed by a fixed
amount). Noise and image fields are applied first as a smooth flow (see _field_warp): an image
replaces edge + controls, noise multiplies them. Applied to grid, concentric, crosslines, spiral and
fibonacci; random uses value as a local min_distance multiplier; path, custom_points, voronoi,
flowlines ignore spacing.
"""
from __future__ import annotations

import functools
import math
from pathlib import Path

import numpy as np
import shapely
from shapely.geometry import LineString, MultiPoint, Point, Polygon, box

from .model import MODES, Canvas, Design, DotStyle, Gradient, Result

CIRCLE_SEGS = 48
MIN_DOT = 0.05      # dots with diameter <= this (mm) are dropped
MIN_SPACING = 1.0   # mm; smaller lattice pitches take tens of seconds and are not printable anyway
MAX_COUNT = 20000   # cap for count parameters (also the GUI's hard max)
MAX_POINTS = 200_000  # lattice points a mode may lay out (big canvas x fine pitch hangs the app otherwise)
SLIVER = 0.4       # clipped pieces thinner than this (mm) are dropped
GOLDEN = math.pi * (3 - math.sqrt(5))
NEUTRAL = {"size": 1.0, "spacing": 1.0, "angle": 0.0, "shape": 0.0}
WARP_MODES = ("grid", "concentric", "crosslines", "spiral", "fibonacci")


# ---------------------------------------------------------------- small helpers
def _rot(xy, deg):
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    return np.c_[xy[:, 0] * c - xy[:, 1] * s, xy[:, 0] * s + xy[:, 1] * c]


def _frame(cover, deg):
    """Bounds of the cover box seen from a frame rotated by deg."""
    x0, y0, x1, y1 = cover
    c = _rot(np.array([[x0, y0], [x1, y0], [x1, y1], [x0, y1]]), -deg)
    return c[:, 0].min(), c[:, 1].min(), c[:, 0].max(), c[:, 1].max()


def _corner_dist(cover):
    x0, y0, x1, y1 = cover
    return max(math.hypot(x, y) for x in (x0, x1) for y in (y0, y1))


def _limit(n, hint):
    """Refuse layouts that would take minutes and gigabytes, before building them."""
    if n > MAX_POINTS:
        raise ValueError(f"this pattern needs about {int(n):,} points (max {MAX_POINTS:,}): {hint}")


def _arclen(line):
    return np.r_[0.0, np.cumsum(np.hypot(*np.diff(line, axis=0).T))]


def _at(line, cum, s):
    return np.c_[np.interp(s, cum, line[:, 0]), np.interp(s, cum, line[:, 1])]


def _catmull(pts, closed, k=16):
    """Uniform Catmull-Rom through pts; closed result repeats the first point at the end."""
    P = np.asarray(pts, float)
    if len(P) < 3:
        return np.vstack([P, P[:1]]) if closed else P
    if closed:
        ext, n = np.vstack([P[-1], P, P[0], P[1]]), len(P)
    else:
        ext, n = np.vstack([2 * P[0] - P[1], P, 2 * P[-1] - P[-2]]), len(P) - 1
    p0, p1, p2, p3 = (ext[i:i + n, None, :] for i in range(4))
    t = np.linspace(0, 1, k, endpoint=False)[None, :, None]
    c = 0.5 * (2 * p1 + (p2 - p0) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t ** 2
               + (3 * p1 - p0 - 3 * p2 + p3) * t ** 3)
    return np.vstack([c.reshape(-1, 2), P[:1] if closed else P[-1:]])


def _value_noise(xy, scale, seed):
    """Smooth seeded 2D value noise in [-1, 1] with feature size `scale`."""
    p = xy / max(scale, 1e-6)
    i = np.floor(p)
    f = p - i
    f = f * f * (3 - 2 * f)
    i = i.astype(np.int64)
    m = np.uint64(0xFFFFFFFF)

    def h(ix, iy):
        n = ((ix.astype(np.uint64) * np.uint64(0x9E3779B1)) ^ (iy.astype(np.uint64) * np.uint64(0x85EBCA77))
             ^ np.uint64((seed * 0xC2B2AE3D) & 0xFFFFFFFF)) & m
        n = ((n ^ (n >> np.uint64(15))) * np.uint64(0x2C1B3C6D)) & m
        n = ((n ^ (n >> np.uint64(12))) * np.uint64(0x297A2D39)) & m
        n ^= n >> np.uint64(15)
        return n.astype(np.float64) / 2147483647.5 - 1.0

    x, y = i[:, 0], i[:, 1]
    a, b = h(x, y), h(x + 1, y)
    c, d = h(x, y + 1), h(x + 1, y + 1)
    u, v = f[:, 0], f[:, 1]
    return (a + (b - a) * u) * (1 - v) + (c + (d - c) * u) * v


# ---------------------------------------------------------------- outline
def outline_of(design: Design) -> Polygon:
    w, h = design.canvas.width, design.canvas.height
    b = design.boundary
    if b.type == "circle":
        return Point(0, 0).buffer(min(w, h) / 2, quad_segs=32)
    if b.type == "rounded_rectangle":
        r = max(0.0, min(b.corner_radius, min(w, h) / 2 - 1e-6))
        rect = box(-w / 2 + r, -h / 2 + r, w / 2 - r, h / 2 - r)
        return rect.buffer(r, quad_segs=8) if r > 0 else rect
    if b.type == "custom" and len(b.points) >= 3:
        poly = Polygon(b.points)
        if not poly.is_valid:
            parts = [g for g in shapely.get_parts(shapely.make_valid(poly)) if g.geom_type == "Polygon"]
            poly = max(parts, key=lambda g: g.area) if parts else box(-w / 2, -h / 2, w / 2, h / 2)
        return poly
    return box(-w / 2, -h / 2, w / 2, h / 2)


# ---------------------------------------------------------------- gradients
def _control_geom(c):
    pts = [tuple(p) for p in c.points] or [(0.0, 0.0)]
    if c.kind == "point" or len(pts) < 2:
        return Point(pts[0])
    if c.kind == "curve" and len(pts) >= 3:
        return LineString(_catmull(pts, closed=False))
    return LineString(pts)


def _falloff(t, kind):
    t = np.clip(t, 0, 1)
    return t if kind == "linear" else t * t * (3 - 2 * t)


@functools.lru_cache(maxsize=4)
def _gray(path: str, mtime: float):
    """Decoded grayscale image 0..1; cached so slider drags don't re-decode big photos."""
    from PIL import Image
    with Image.open(path) as im:
        return np.asarray(im.convert("L"), dtype=np.float32) / np.float32(255)


def _image_field(g: Gradient, xy, canvas: Canvas):
    p = Path(g.image)
    if not p.is_file():
        raise FileNotFoundError(f"gradient image not found: {p}")
    a = _gray(str(p), p.stat().st_mtime)
    H, W = a.shape
    col = np.clip(((xy[:, 0] / canvas.width + 0.5) * (W - 1)).round().astype(int), 0, W - 1)
    row = np.clip(((0.5 - xy[:, 1] / canvas.height) * (H - 1)).round().astype(int), 0, H - 1)
    v = a[row, col]
    if g.invert_image:
        v = 1 - v
    return g.image_min + (g.image_max - g.image_min) * v


def sample_gradient(g: Gradient, xy, canvas: Canvas, neutral: float = 1.0, span: float = 0.0) -> np.ndarray:
    """Field value at points xy (N,2). Disabled -> `neutral` everywhere. Noise scales the value, or with
    `span` (for fields that are 0 when neutral, like angle) adds up to ±noise·span."""
    xy = np.asarray(xy, float).reshape(-1, 2)
    if not g.enabled:
        return np.full(len(xy), float(neutral))
    if g.image:
        v = _image_field(g, xy, canvas)
    else:
        v = np.full(len(xy), float(g.edge))
        best = np.zeros(len(xy))
        for c in g.controls:
            geom = _control_geom(c)
            if geom.geom_type == "Point":
                d = np.hypot(xy[:, 0] - geom.x, xy[:, 1] - geom.y)
            else:
                d = shapely.distance(geom, shapely.points(xy))
            w = 1 - _falloff(d / max(c.radius, 1e-9), g.falloff)
            upd = w > best
            v[upd] = g.edge + (c.value - g.edge) * w[upd]
            best = np.maximum(best, w)
    if g.noise:
        n = g.noise * _value_noise(xy, g.noise_scale, g.noise_seed)
        v = v + n * span if span else v * (1 + n)
    return v


def _gmax(g: Gradient, neutral):
    if not g.enabled:
        return neutral
    vals = [g.image_min, g.image_max] if g.image else [g.edge] + [c.value for c in g.controls]
    return max(vals) * (1 + abs(g.noise))


def _warp_profile(c, g):
    e = max(g.edge, 0.05)
    R = max(c.radius, 1e-6)
    s = np.linspace(0, R, 257)
    ratio = np.maximum(g.edge + (c.value - g.edge) * (1 - _falloff(s / R, g.falloff)), 0.05) / e
    h = np.r_[0.0, np.cumsum((ratio[1:] + ratio[:-1]) / 2 * np.diff(s))]
    return s, h


def _warp_pad(g: Gradient):
    """How far compression pulls the far field in (so the generator must cover more)."""
    return sum(max(0.0, c.radius - _warp_profile(c, g)[1][-1]) for c in g.controls)


def _warp_min(g: Gradient):
    """Smallest spacing multiplier the field can reach (how much the cover must grow)."""
    lo = min(g.image_min, g.image_max) if g.image else g.edge
    return max(lo * (1 - min(abs(g.noise), 0.9)), 0.05)


def _bilerp(Z, gx, gy, p):
    fx = np.interp(p[:, 0], gx, np.arange(len(gx)))
    fy = np.interp(p[:, 1], gy, np.arange(len(gy)))
    i = np.clip(fx.astype(int), 0, len(gx) - 2)
    j = np.clip(fy.astype(int), 0, len(gy) - 2)
    u, v = fx - i, fy - j
    return (Z[j, i] * (1 - u) * (1 - v) + Z[j, i + 1] * u * (1 - v)
            + Z[j + 1, i] * (1 - u) * v + Z[j + 1, i + 1] * u * v)


def _field_warp(xy, g: Gradient, canvas: Canvas):
    """Image / noise spacing field f: move points along the flow of grad(phi), with
    laplace(phi) = 2 log(f / s) solved by FFT. A smooth flow never folds, and its
    divergence sets the local area ratio, so the local pitch scales by about f/s;
    s (the mean scale) is applied as a uniform zoom. Controls are handled radially by _warp."""
    if not (g.image or g.noise) or not len(xy):
        return xy
    n = 128
    lo, hi = xy.min(0), xy.max(0)
    c = (lo + hi) / 2
    h = 2 * ((hi - lo).max() + 2) / n          # domain = 2x the points' extent (padding vs FFT wrap)
    gx, gy = c[0] + (np.arange(n) - n / 2) * h, c[1] + (np.arange(n) - n / 2) * h
    X, Y = np.meshgrid(gx, gy)
    P = np.c_[X.ravel(), Y.ravel()]
    f = _image_field(g, P, canvas) if g.image else np.ones(len(P))
    if g.noise:
        f = f * (1 + min(abs(g.noise), 0.9) * _value_noise(P, max(g.noise_scale, 0.5), g.noise_seed))
    lf = np.log(np.maximum(f, 0.05)).reshape(n, n)
    inside = (np.abs(X - c[0]) <= (hi - lo)[0] / 2 + 1) & (np.abs(Y - c[1]) <= (hi - lo)[1] / 2 + 1)
    ls = lf[inside].mean()
    rhs = 2 * (lf - ls)
    rhs -= rhs.mean()
    k = 2 * np.pi * np.fft.fftfreq(n, d=h)
    KX, KY = np.meshgrid(k, k)
    K2 = KX ** 2 + KY ** 2
    K2[0, 0] = 1.0
    ph = -np.fft.fft2(rhs) / K2
    ph[0, 0] = 0
    vx, vy = np.fft.ifft2(1j * KX * ph).real, np.fft.ifft2(1j * KY * ph).real
    for _ in range(8):
        xy = xy + np.c_[_bilerp(vx, gx, gy, xy), _bilerp(vy, gx, gy, xy)] / 8
    return xy * np.exp(ls)


def _warp(xy, g: Gradient, canvas: Canvas):
    if g.image:  # image replaces edge + controls, as in sample_gradient
        return _field_warp(xy, g, canvas)
    xy = _field_warp(xy * max(g.edge, 0.05), g, canvas)
    for c in g.controls:
        geom = _control_geom(c)
        if geom.geom_type == "Point":
            foot = np.broadcast_to([geom.x, geom.y], xy.shape)
        else:
            pts = shapely.points(xy)
            foot = shapely.get_coordinates(shapely.line_interpolate_point(geom, shapely.line_locate_point(geom, pts)))
        v = xy - foot
        d = np.hypot(v[:, 0], v[:, 1])
        s, h = _warp_profile(c, g)
        hd = np.where(d < s[-1], np.interp(d, s, h), h[-1] + d - s[-1])
        k = np.divide(hd, d, out=np.ones_like(d), where=d > 1e-12)
        xy = foot + v * k[:, None]
    return xy


# ---------------------------------------------------------------- dot templates
def _regular(n, r, start=90.0):
    a = np.radians(start + np.arange(n) * 360.0 / n)
    return np.c_[r * np.cos(a), r * np.sin(a)]


def _star(n, R, inner):
    k = np.arange(2 * n)
    a = np.radians(90 + k * 180.0 / n)
    r = np.where(k % 2 == 0, R, R * inner)
    return np.c_[r * np.cos(a), r * np.sin(a)]


def _rrect(w, h, r, segs=8):
    r = max(0.0, min(r, w / 2, h / 2))
    if r <= 1e-9:
        return np.array([[w / 2, h / 2], [-w / 2, h / 2], [-w / 2, -h / 2], [w / 2, -h / 2]])
    out = []
    for (sx, sy), a0 in (((1, 1), 0), ((-1, 1), 90), ((-1, -1), 180), ((1, -1), 270)):
        a = np.radians(a0 + np.linspace(0, 90, segs + 1))
        out.append(np.c_[sx * (w / 2 - r) + r * np.cos(a), sy * (h / 2 - r) + r * np.sin(a)])
    return np.vstack(out)


def _template(shape, dot: DotStyle, d):
    """Outline (M,2), CCW, centred at the origin, for diameter d."""
    if shape == "rounded_rectangle":
        return _rrect(d, d * dot.aspect, dot.corner_radius)
    if shape == "rectangle":
        return _rrect(d, d, 0)
    if shape == "hexagon":
        return _regular(6, d / 2)
    if shape == "polygon":
        return _regular(max(3, int(dot.sides)), d / 2)
    if shape == "star":
        return _star(max(2, int(dot.star_points)), d / 2, dot.star_inner)
    if shape == "custom" and len(dot.custom_points) >= 3:
        p = np.asarray(dot.custom_points, float)
        lo, hi = p.min(0), p.max(0)
        p = (p - (lo + hi) / 2) * (d / max((hi - lo).max(), 1e-9))
        area = np.sum(p[:, 0] * np.roll(p[:, 1], -1) - np.roll(p[:, 0], -1) * p[:, 1])
        return p if area >= 0 else p[::-1]
    return _regular(CIRCLE_SEGS, d / 2)


def _radial(ring, ang):
    """Radius of the outline along rays at angles ang (rad) from the origin (outermost hit)."""
    A, E = ring, np.roll(ring, -1, 0) - ring
    u = np.c_[np.cos(ang), np.sin(ang)]
    with np.errstate(divide="ignore", invalid="ignore"):
        den = u[:, None, 0] * E[None, :, 1] - u[:, None, 1] * E[None, :, 0]
        s = (A[None, :, 0] * E[None, :, 1] - A[None, :, 1] * E[None, :, 0]) / den
        t = (A[None, :, 0] * u[:, None, 1] - A[None, :, 1] * u[:, None, 0]) / den
    ok = np.isfinite(s) & (s > 0) & (t >= -1e-9) & (t <= 1 + 1e-9)
    return np.where(ok, s, 0).max(1)


def _morph_pair(a, b):
    """Resample two outlines on a shared set of ray angles (keeps both shapes' corners)."""
    ang = np.r_[np.arctan2(a[:, 1], a[:, 0]), np.arctan2(b[:, 1], b[:, 0]),
                np.linspace(-math.pi, math.pi, 96, endpoint=False)]
    ang = np.unique(np.round(np.mod(ang, 2 * math.pi), 6))
    u = np.c_[np.cos(ang), np.sin(ang)]
    return u * _radial(a, ang)[:, None], u * _radial(b, ang)[:, None]


def _build_dots(xy, scale, ang, base, target=None, t=None):
    """Vectorised: one polygon per dot from a template (optionally morphed toward target by t)."""
    tx, ty = base[None, :, 0], base[None, :, 1]
    if target is not None:
        tt = t[:, None]
        tx = tx + tt * (target[None, :, 0] - tx)
        ty = ty + tt * (target[None, :, 1] - ty)
    a = np.radians(ang)[:, None]
    c, s, k = np.cos(a), np.sin(a), scale[:, None]
    X = xy[:, 0:1] + k * (tx * c - ty * s)
    Y = xy[:, 1:2] + k * (tx * s + ty * c)
    return shapely.polygons(np.stack([X, Y], -1))


# ---------------------------------------------------------------- dot modes
# each returns xy (N,2), angle deg (N,), size multiplier (N,)
def _empty():
    return np.zeros((0, 2)), np.zeros(0), np.zeros(0)


def _grid(g, cover):
    sx = max(g.spacing_x, MIN_SPACING)
    sy = sx * math.sqrt(3) / 2 if g.arrangement == "hexagon" else max(g.spacing_y, MIN_SPACING)
    stagger = g.arrangement in ("diamond", "hexagon")
    x0, y0, x1, y1 = _frame(cover, g.rotation)
    x0, x1, y0, y1 = x0 - g.offset_x, x1 - g.offset_x, y0 - g.offset_y, y1 - g.offset_y
    _limit((x1 - x0) / sx * (y1 - y0) / sy, "raise the spacing or shrink the canvas")
    I, J = np.meshgrid(np.arange(math.floor(x0 / sx) - 2, math.ceil(x1 / sx) + 2),
                       np.arange(math.floor(y0 / sy) - 1, math.ceil(y1 / sy) + 2))
    I, J = I.ravel(), J.ravel()
    xy = np.c_[I * sx + (J % 2) * (sx / 2 if stagger else 0) + g.offset_x, J * sy + g.offset_y]
    alt = {"col": I % 2, "both": (I + J) % 2}.get(g.rotate_by, J % 2)
    return _rot(xy, g.rotation), g.rotation + alt * g.row_rotation, np.ones(len(xy))


def _random(r, region, spacing, canvas):
    rng = np.random.default_rng(r.seed)
    n = min(max(int(r.count), 0), MAX_COUNT)
    if n == 0 or region.is_empty:
        return _empty()
    x0, y0, x1, y1 = region.bounds
    cand = rng.uniform((x0, y0), (x1, y1), size=(min(n * 30, 200_000), 2))
    cand = cand[shapely.contains_xy(region, cand[:, 0], cand[:, 1])]
    rad = max(r.min_distance, 0.2) * np.maximum(sample_gradient(spacing, cand, canvas, 1.0), 0.05)
    if len(cand) == 0:
        return _empty()
    cell = rad.max()
    cells: dict = {}
    keep = []
    for k, (x, y) in enumerate(cand):
        cx, cy = int(x // cell), int(y // cell)
        rk = rad[k]
        ok = True
        for i in (cx - 1, cx, cx + 1):
            for j in (cy - 1, cy, cy + 1):
                for q in cells.get((i, j), ()):
                    if (cand[q, 0] - x) ** 2 + (cand[q, 1] - y) ** 2 < ((rk + rad[q]) / 2) ** 2:
                        ok = False
                        break
                if not ok:
                    break
            if not ok:
                break
        if ok:
            cells.setdefault((cx, cy), []).append(k)
            keep.append(k)
            if len(keep) >= n:
                break
    xy = cand[keep]
    return xy, np.zeros(len(xy)), np.ones(len(xy))


def _path(p, canvas):
    """Dots along a path plus `layers` parallel offsets, centred on the base path (half outward,
    half inward). `count` is the dot count on the base path; each layer gets dots in proportion to
    its length so the along-path step stays constant. Closed paths are offset with buffer (exact,
    never self-intersecting), open ones with offset_curve; a layer that collapses, splits, or is
    shorter than two steps (three for rings) is dropped. Alternate closed layers are shifted half a step (brick)."""
    if len(p.points) >= 2:
        pts, closed = np.asarray(p.points, float), p.closed
        line = _catmull(pts, closed) if p.smooth else (np.vstack([pts, pts[:1]]) if closed else pts)
    else:
        a = np.linspace(0, 2 * math.pi, 129)
        rr = 0.35 * min(canvas.width, canvas.height)
        line, closed = np.c_[rr * np.cos(a), rr * np.sin(a)], True
    L0, n0 = _arclen(line)[-1], min(max(int(p.count), 0), MAX_COUNT)
    if n0 == 0 or L0 <= 0:
        return _empty()
    n0 = min(n0, int(2 * L0) + 1)  # <= 2 dots per mm of path; more only stacks them
    step = L0 / n0
    nl = max(int(p.layers), 1)
    reach = math.hypot(canvas.width, canvas.height) + float(np.abs(line).max())
    if closed:
        ring = shapely.LinearRing(line)
        poly, ccw = shapely.make_valid(Polygon(ring)), ring.is_ccw
    else:
        base = LineString(line)
    xs, angs = [], []
    for k in range(nl):
        o = (k - (nl - 1) / 2) * p.layer_spacing
        if abs(o) > reach:  # offset layer lies entirely off the plate
            continue
        if o == 0:
            ln = line
        elif closed:
            g = poly.buffer(o, quad_segs=16)
            if g.geom_type != "Polygon" or g.is_empty:
                continue  # collapsed or split inward offset
            ext = g.exterior if g.exterior.is_ccw == ccw else g.exterior.reverse()
            ln = np.asarray(ext.coords)
            # start the ring near the base start so layers line up
            i = int(np.argmin(np.hypot(*(ln[:-1] - line[0]).T)))
            ln = np.vstack([ln[i:-1], ln[:i + 1]])
        else:
            g = base.offset_curve(o, quad_segs=16)
            if g.geom_type != "LineString" or g.is_empty:
                continue
            ln = np.asarray(g.coords)
        cum = _arclen(ln)
        L = cum[-1]
        if L < (3 if closed else 2) * step:  # a ring needs >= 3 dots to read as a ring
            continue
        m = round(n0 * L / L0)
        if closed:  # no dot at the seam: s in [0, L)
            s = (np.arange(m) + (0.5 if k % 2 else 0.0)) * L / m
        else:
            s = np.linspace(0, L, m)
        eps = L * 1e-4
        pa, pb = (np.mod(s - eps, L), np.mod(s + eps, L)) if closed else (s - eps, s + eps)
        tan = _at(ln, cum, pb) - _at(ln, cum, pa)
        xs.append(_at(ln, cum, s))
        angs.append(np.degrees(np.arctan2(tan[:, 1], tan[:, 0])) if p.align else np.zeros(m))
    if not xs:
        return _empty()
    xy = np.vstack(xs)
    return xy, np.concatenate(angs), np.ones(len(xy))


def _spiral(sp):
    n = min(max(int(sp.count), 0), MAX_COUNT)
    if n == 0:
        return _empty()
    R, r0 = sp.radius, sp.inner_radius
    tmax = 2 * math.pi * max(sp.turns, 1e-3)
    n = min(n, int(tmax * (abs(R) + abs(r0))) + 1)  # <= ~2 dots per mm of spiral; more only stacks them
    if sp.even_spacing:
        th = np.linspace(0, tmax, max(2000, int(400 * sp.turns)))
        r = r0 + (R - r0) * th / tmax
        cum = _arclen(np.c_[r * np.cos(th), r * np.sin(th)])
        th = np.interp(np.linspace(0, cum[-1], n), cum, th)
    else:
        th = np.linspace(0, tmax, n)
    r = r0 + (R - r0) * th / tmax
    phi = th + math.radians(sp.rotation)
    dr = (R - r0) / tmax
    tang = np.degrees(np.arctan2(dr * np.sin(phi) + r * np.cos(phi), dr * np.cos(phi) - r * np.sin(phi)))
    return np.c_[r * np.cos(phi), r * np.sin(phi)], (tang if sp.align else np.zeros(n)), np.ones(n)


def _concentric(c, cover):
    outer = min(c.outer_radius, _corner_dist(cover)) if c.outer_radius > 0 else _corner_dist(cover)
    rs = max(c.ring_spacing, MIN_SPACING)
    _limit(math.pi * outer ** 2 / (rs * max(c.dot_spacing, MIN_SPACING)),
           "raise ring/dot spacing or set an outer radius")
    xs, angs = [], []
    k = 0
    while (r := c.inner_radius + k * rs) <= outer + 1e-9:
        if r < 1e-9:
            th = np.array([math.radians(c.rotation)])
        else:
            m = max(1, round(2 * math.pi * r / max(c.dot_spacing, MIN_SPACING)))
            th = np.radians(c.rotation) + (np.arange(m) + (0.5 if c.stagger and k % 2 else 0)) * 2 * math.pi / m
        xs.append(np.c_[r * np.cos(th), r * np.sin(th)])
        angs.append(np.degrees(th) + 90 if c.align else np.zeros(len(th)))
        k += 1
    if not xs:
        return _empty()
    xy = np.vstack(xs)
    return xy, np.concatenate(angs), np.ones(len(xy))


def _fibonacci(f):
    n = np.arange(min(max(int(f.count), 0), MAX_COUNT))
    r = np.sqrt(f.inner_radius ** 2 + f.spread ** 2 * n)  # same dot density everywhere, also with a hole
    th = n * GOLDEN + math.radians(f.rotation)
    return np.c_[r * np.cos(th), r * np.sin(th)], (np.degrees(th) if f.align else np.zeros(len(n))), np.ones(len(n))


def _crosslines(c, cover):
    a1, a2 = math.radians(c.left_angle + c.rotation), math.radians(c.right_angle + c.rotation)
    M = np.array([[-math.sin(a1), math.cos(a1)], [-math.sin(a2), math.cos(a2)]])  # line normals
    if abs(np.linalg.det(M)) < 1e-6:
        return _empty()
    s1, s2 = max(c.left_spacing, MIN_SPACING), max(c.right_spacing, MIN_SPACING)
    x0, y0, x1, y1 = cover
    corners = np.array([[x0, y0], [x1, y0], [x1, y1], [x0, y1]]) @ M.T
    i = np.arange(math.floor(corners[:, 0].min() / s1) - 1, math.ceil(corners[:, 0].max() / s1) + 2)
    j = np.arange(math.floor(corners[:, 1].min() / s2) - 1, math.ceil(corners[:, 1].max() / s2) + 2)
    _limit(len(i) * len(j), "raise the line spacings or shrink the canvas")
    I, J = (a.ravel() for a in np.meshgrid(i, j))
    xy = np.c_[I * s1, J * s2] @ np.linalg.inv(M).T
    inb = (xy[:, 0] >= x0) & (xy[:, 0] <= x1) & (xy[:, 1] >= y0) & (xy[:, 1] <= y1)
    xy, I, J = xy[inb], I[inb], J[inb]
    alt = {"left": I % 2, "right": J % 2}.get(c.rotate_by, (I + J) % 2)
    return xy, c.rotation + alt * c.row_rotation, np.ones(len(xy))


def _custom(c):
    xy = np.asarray(c.points, float).reshape(-1, 2)
    n = len(xy)
    sz = np.ones(n)
    an = np.zeros(n)
    sz[:min(n, len(c.sizes))] = c.sizes[:n]
    an[:min(n, len(c.angles))] = c.angles[:n]
    return xy, an, sz


# ---------------------------------------------------------------- polygon modes
def _scale_parts(geoms, k):
    """Scale each geometry about its centroid by its own factor (vectorised)."""
    cen = shapely.get_coordinates(shapely.centroid(geoms))
    xy, idx = shapely.get_coordinates(geoms, return_index=True)
    return shapely.set_coordinates(geoms.copy(), cen[idx] + (xy - cen[idx]) * k[idx, None])


def _voronoi(design, cover, inner):
    v = design.pattern.voronoi
    cs = max(v.cell_size, MIN_SPACING)
    rng = np.random.default_rng(v.seed)
    x0, y0, x1, y1 = _frame(cover, v.rotation)
    _limit((x1 - x0) * (y1 - y0) / cs ** 2, "raise the cell size or shrink the canvas")
    I, J = np.meshgrid(np.arange(math.floor(x0 / cs) - 2, math.ceil(x1 / cs) + 3),
                       np.arange(math.floor(y0 / cs) - 2, math.ceil(y1 / cs) + 3))
    seeds = np.c_[I.ravel(), J.ravel()] * cs
    seeds = _rot(seeds + rng.uniform(-0.5, 0.5, seeds.shape) * cs * v.irregularity / 100.0, v.rotation)
    ext = box(*cover).buffer(2 * cs)
    cells = shapely.get_parts(shapely.voronoi_polygons(MultiPoint(seeds), extend_to=ext, ordered=True))
    cells = cells[shapely.intersects(inner.envelope, cells)]
    r = max(v.corner_radius, 0.0)
    cells = shapely.buffer(cells, -(v.crack_width / 2 + r), join_style="mitre")
    if r > 0:
        cells = shapely.buffer(cells, r, quad_segs=4)
    cells = cells[~shapely.is_empty(cells)]
    g = design.gradients.size
    if g.enabled and len(cells):
        k = sample_gradient(g, shapely.get_coordinates(shapely.centroid(cells)), design.canvas, 1.0)
        cells = _scale_parts(cells[k > 0.02], k[k > 0.02])
    return cells


def _flowlines(design, cover, inner):
    f = design.pattern.flowlines
    w = max(f.line_width, 0.1)
    sp = max(f.line_spacing, MIN_SPACING)
    cap = "round" if f.edge_style == "round" else "flat"
    if f.follow_boundary:
        lines, k = [], 0
        while True:
            ring = inner.buffer(-(w / 2 + k * sp))
            if ring.is_empty or k > 10_000:
                break
            lines += list(shapely.get_parts(shapely.get_parts(ring.boundary)))
            k += 1
        lines = np.array(lines, dtype=object)
    else:
        R = _corner_dist(cover) + w + abs(f.amplitude)
        x = np.arange(-R, R + 0.5, min(0.5, max(f.wavelength, 2.0) / 32))
        ys = np.arange(-math.ceil(R / sp), math.ceil(R / sp) + 1) * sp
        _limit(len(x) * len(ys) / 10, "raise the slot spacing or shrink the canvas")  # /10: vertices, not holes
        X, Y = np.meshgrid(x, ys)
        wave = f.amplitude * np.sin(2 * math.pi * X / max(f.wavelength, 2.0))
        noise = 0.25 * f.amplitude * _value_noise(np.c_[X.ravel(), Y.ravel()], max(f.wavelength, 1.0), f.seed)
        Y = Y + wave + noise.reshape(X.shape)
        pts = _rot(np.c_[X.ravel(), Y.ravel()], f.rotation).reshape(X.shape + (2,))
        lines = shapely.linestrings(pts)
    if len(lines) == 0:
        return lines
    if f.invert:
        band = shapely.union_all(shapely.buffer(lines, w / 2, cap_style="flat"))
        return _bridged(shapely.get_parts(inner.difference(band)), f, inner, design.min_wall)
    if not f.follow_boundary:
        lines = shapely.get_parts(shapely.intersection(lines, inner.buffer(-w / 2 if cap == "round" else 0)))
        lines = lines[shapely.length(lines) > 1e-6]
    g = design.gradients.size
    width = np.full(len(lines), w)
    if g.enabled and len(lines):
        width = w * sample_gradient(g, shapely.get_coordinates(shapely.point_on_surface(lines)), design.canvas, 1.0)
        keep = width > MIN_DOT
        lines, width = lines[keep], width[keep]
    return _bridged(shapely.buffer(lines, width / 2, cap_style=cap, quad_segs=8), f, inner, design.min_wall)


def _bridged(holes, f, inner, min_wall):
    """Closed ring slots (follow_boundary) would cut loose islands out of the plate; cut 4 radial
    bridges through them. shortcut: bridges radiate from the outline centroid, so a ring that does
    not enclose it (strongly concave outline) may still get no bridge."""
    if not f.follow_boundary or len(holes) == 0:
        return holes
    c = inner.centroid
    R = _corner_dist(inner.bounds) + abs(c.x) + abs(c.y)
    bw = max(2 * min_wall, 1.0)
    rays = [LineString([(c.x, c.y), (c.x + R * math.cos(a), c.y + R * math.sin(a))])
            for a in np.radians(f.rotation + np.array([45, 135, 225, 315]))]
    cut = shapely.union_all(shapely.buffer(rays, bw / 2, cap_style="flat"))
    parts = shapely.get_parts(shapely.difference(holes, cut))
    return parts[~shapely.is_empty(parts) & (shapely.area(parts) > 1e-6)]


# ---------------------------------------------------------------- fit + stats
def _fit(holes, inner, clip):
    """Keep holes inside `inner`; clip=True also appends clipped pieces.
    Returns (kept holes, inside mask over the input): kept = holes[inside] followed by clipped parts."""
    inside = shapely.contains(inner, holes) if len(holes) else np.zeros(0, bool)
    kept = holes[inside]
    if not clip or len(holes) == 0:
        return kept, inside
    cross = holes[~inside & shapely.intersects(inner, holes)]
    parts = shapely.get_parts(shapely.intersection(cross, inner))
    parts = parts[shapely.get_type_id(parts) == 3]
    parts = parts[~shapely.is_empty(shapely.buffer(parts, -SLIVER / 2, quad_segs=2))]
    return np.r_[kept, parts], inside


def _stats(holes, outline, min_wall):
    plate = outline.area
    n = len(holes)
    if n == 0:
        return {"count": 0, "open_area_ratio": 0.0, "hole_area": 0.0, "plate_area": plate, "min_wall_violations": 0}
    tree = shapely.STRtree(holes)
    i, j = tree.query(holes, predicate="intersects")
    area = shapely.union_all(holes).area if np.any(i != j) else float(shapely.area(holes).sum())
    viol = 0
    if min_wall > 0:
        i, j = tree.query(holes, predicate="dwithin", distance=min_wall - 1e-6)
        viol = len(np.unique(i[i != j]))
    return {"count": n, "open_area_ratio": area / plate if plate else 0.0, "hole_area": area,
            "plate_area": plate, "min_wall_violations": viol, **_thinnest_wall(tree, holes, outline)}


def _thinnest_wall(tree, holes, outline):
    """Narrowest strip of plate between two holes or a hole and the plate edge, and where it is.
    Overlapping holes (distance 0) form one opening and are skipped."""
    holes = np.asarray(holes, dtype=object)
    w = np.inf
    pair = None
    D = 1.0
    x0, y0, x1, y1 = outline.bounds
    while pair is None and len(holes) > 1 and D < 2 * max(x1 - x0, y1 - y0):  # widen the search until a gap shows up
        i, j = tree.query(holes, predicate="dwithin", distance=D)
        i, j = i[i < j], j[i < j]
        dist = shapely.distance(holes[i], holes[j])
        ok = dist > 1e-9
        if ok.any():
            k = np.argmin(np.where(ok, dist, np.inf))
            w, pair = float(dist[k]), (holes[i[k]], holes[j[k]])
        D *= 4
    edge = shapely.distance(holes, outline.boundary)
    edge = np.where(edge > 1e-9, edge, np.inf)  # clipped holes touch the edge on purpose
    if len(edge) and edge.min() < w:
        k = int(np.argmin(edge))
        w, pair = float(edge[k]), (holes[k], outline.boundary)
    if pair is None:
        return {}
    mid = shapely.shortest_line(*pair).centroid
    return {"thinnest_wall": w, "thinnest_wall_at": [round(mid.x, 3), round(mid.y, 3)]}


def _airflow(open_ratio):
    """Pressure loss of a thin perforated plate (Idelchik): zeta = ((0.707 sqrt(1-f) + 1 - f) / f)^2.
    shortcut: thin plate, evenly spread holes; Pa figure at 2 m/s face velocity (typical case fan), not a CFD run."""
    if not 0 < open_ratio < 1:
        return {}
    zeta = ((0.707 * math.sqrt(1 - open_ratio) + 1 - open_ratio) / open_ratio) ** 2
    return {"loss_coefficient": zeta, "pressure_drop_pa": zeta * 1.2 * 2.0 ** 2 / 2}


# ---------------------------------------------------------------- keep-outs, machining
def _keepout_geom(k):
    if k.shape == "polygon" and len(k.points) >= 3:
        return shapely.make_valid(Polygon([(k.x + px, k.y + py) for px, py in k.points]))
    if k.shape == "rectangle":
        return box(k.x - k.width / 2, k.y - k.height / 2, k.x + k.width / 2, k.y + k.height / 2)
    return Point(k.x, k.y).buffer(k.width / 2, quad_segs=16)


def _vent_region(design: Design, inner):
    """The plate area holes may use: minus the fan opening's outside and the keep-outs."""
    vd = design.boundary.vent_diameter
    if vd > 0:
        inner = inner.intersection(Point(0, 0).buffer(vd / 2 - max(design.boundary.margin, 0), quad_segs=32))
    if design.keepouts:
        inner = inner.difference(shapely.union_all([_keepout_geom(k).buffer(max(k.clearance, 0))
                                                    for k in design.keepouts]))
    return inner


def _tool_radius(holes, circles, t):
    """An end mill of radius t cannot cut corners sharper than t: each hole becomes the area the tool reaches
    (opening = shrink then grow by t). Holes too narrow for the tool are dropped. Returns holes, circles, dropped."""
    if t <= 0 or not holes:
        return holes, circles, 0
    poly = [i for i, c in enumerate(circles) if not c]
    opened = shapely.buffer(shapely.buffer(np.asarray([holes[i] for i in poly], dtype=object), -t), t, quad_segs=8)
    out_h, out_c = [], []
    for h, c in zip(holes, circles):
        if c and c[2] >= t:
            out_h.append(h)
            out_c.append(c)
    for g in opened:
        for part in shapely.get_parts(g):
            if part.geom_type == "Polygon" and part.area > 1e-9:
                out_h.append(part)
                out_c.append(None)
    dropped = sum(1 for c in circles if c and c[2] < t) + int(shapely.is_empty(opened).sum())
    return out_h, out_c, dropped


def _finish(design: Design, outline, holes, circles) -> Result:
    """Machining, fan-opening stats and keep-out screw holes, shared by every mode."""
    holes, circles, dropped = _tool_radius(list(holes), list(circles), design.machining.tool_radius)
    extra = {}
    vd = design.boundary.vent_diameter
    if vd > 0:
        fan = Point(0, 0).buffer(vd / 2, quad_segs=32)
        extra["fan_open_ratio"] = shapely.union_all(holes).intersection(fan).area / fan.area if holes else 0.0
    if dropped:
        extra["dropped_by_tool"] = dropped
    mf = design.machining.min_feature
    if mf > 0 and holes:  # a hole narrower than this closes up when printed (about 2x nozzle) or cannot be cut
        thin = int(shapely.is_empty(shapely.buffer(np.asarray(holes, dtype=object), -mf / 2 + 1e-9)).sum())
        if thin:
            extra["below_min_feature"] = thin
    for k in design.keepouts:
        if k.hole:
            holes.append(_keepout_geom(k))
            circles.append((k.x, k.y, k.width / 2) if k.shape == "circle" else None)
    stats = {**_stats(holes, outline, design.min_wall), **extra}
    stats.update(_airflow(stats.get("fan_open_ratio", stats["open_area_ratio"])))
    return Result(holes=holes, outline=outline, stats=stats, circles=circles)


# ---------------------------------------------------------------- main
def generate(design: Design) -> Result:
    outline = outline_of(design)
    b, dot, gr, pat = design.boundary, design.dot, design.gradients, design.pattern
    mode = pat.mode
    if mode not in MODES:
        raise ValueError(f"unknown pattern mode: {mode!r}")
    inner = _vent_region(design, outline.buffer(-b.margin) if b.margin > 0 else outline)
    if inner.is_empty or dot.diameter <= 0 and mode not in ("voronoi", "flowlines"):
        return _finish(design, outline, [], [])
    shapely.prepare(inner)
    d = dot.diameter
    reach = d * (max(1.0, dot.aspect) if dot.shape == "rounded_rectangle" else 1.0) * _gmax(gr.size, 1.0)
    x0, y0, x1, y1 = outline.bounds
    pad = reach
    warp = gr.spacing.enabled and mode in WARP_MODES
    if warp:
        pad += _warp_pad(gr.spacing)
    cover = (x0 - pad, y0 - pad, x1 + pad, y1 + pad)
    if warp:
        cover = tuple(c / _warp_min(gr.spacing) for c in cover)

    if mode in ("voronoi", "flowlines"):
        polys = (_voronoi if mode == "voronoi" else _flowlines)(design, cover, inner)
        holes, _ = _fit(np.asarray(polys, dtype=object), inner, b.clip or mode == "flowlines")
        return _finish(design, outline, list(holes), [None] * len(holes))

    if mode == "grid":
        xy, ang, sz = _grid(pat.grid, cover)
    elif mode == "random":
        region = inner.buffer(-d / 2)
        xy, ang, sz = _random(pat.random, region if not region.is_empty else inner, gr.spacing, design.canvas)
    elif mode == "path":
        xy, ang, sz = _path(pat.path, design.canvas)
    elif mode == "spiral":
        xy, ang, sz = _spiral(pat.spiral)
    elif mode == "concentric":
        xy, ang, sz = _concentric(pat.concentric, cover)
    elif mode == "fibonacci":
        xy, ang, sz = _fibonacci(pat.fibonacci)
    elif mode == "crosslines":
        xy, ang, sz = _crosslines(pat.crosslines, cover)
    else:
        xy, ang, sz = _custom(pat.custom_points)
    if warp and len(xy):
        xy = _warp(xy, gr.spacing, design.canvas)

    # cheap bbox prefilter before evaluating fields / building polygons
    ix0, iy0, ix1, iy1 = inner.bounds
    m = (xy[:, 0] > ix0 - reach) & (xy[:, 0] < ix1 + reach) & (xy[:, 1] > iy0 - reach) & (xy[:, 1] < iy1 + reach)
    xy, ang, sz = xy[m], ang[m], sz[m]
    sz = sz * sample_gradient(gr.size, xy, design.canvas, 1.0)
    m = sz * d > MIN_DOT
    xy, ang, sz = xy[m], ang[m], sz[m]
    ang = ang + dot.rotation + sample_gradient(gr.angle, xy, design.canvas, 0.0, 90.0)

    base = _template(dot.shape, dot, d)
    if gr.shape.enabled:
        t = np.clip(sample_gradient(gr.shape, xy, design.canvas, 0.0, 1.0), 0, 1)
        a, tgt = _morph_pair(base, _template(gr.target_shape, DotStyle(
            sides=gr.target_sides, star_points=dot.star_points, star_inner=dot.star_inner), d))
        holes = _build_dots(xy, sz, ang, a, tgt, t)
        exact = (t <= 0) if dot.shape == "circle" else np.zeros(len(xy), bool)
    else:
        holes = _build_dots(xy, sz, ang, base)
        exact = np.full(len(xy), dot.shape == "circle")
    if dot.shape == "custom":
        holes = shapely.make_valid(holes)

    circ = [(float(x), float(y), float(s * d / 2)) if e else None for (x, y), s, e in zip(xy, sz, exact)]
    kept, inside = _fit(holes, inner, b.clip)
    circles = [c for c, k in zip(circ, inside) if k] + [None] * (len(kept) - int(inside.sum()))
    return _finish(design, outline, list(kept), circles)
