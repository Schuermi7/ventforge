import time
from pathlib import Path

import numpy as np
import pytest
import shapely

from ventforge.model import MODES, SHAPES, TARGET_SHAPES, Control, Design
from ventforge.pattern import generate, sample_gradient

PRESETS = sorted((Path(__file__).parent.parent / "ventforge" / "presets").glob("*.vent.json"))


def design(mode, **patch):
    d = Design().patched({"pattern": {"mode": mode}, **patch})
    if mode == "custom_points":
        d.pattern.custom_points.points = [[0, 0], [10, 10], [-20, 5], [80, 80]]
        d.pattern.custom_points.sizes = [1, 2]
        d.pattern.custom_points.angles = [0, 45]
    return d


def assert_inside(r, margin=0.0):
    region = r.outline.buffer(-margin + 1e-6)
    assert all(region.contains(h) for h in r.holes)


@pytest.mark.parametrize("boundary", ["none", "circle", "rounded_rectangle", "custom"])
@pytest.mark.parametrize("mode", MODES)
def test_every_mode_inside(mode, boundary):
    d = design(mode, boundary={"type": boundary, "margin": 3,
                               "points": [[-60, -40], [60, -50], [20, 60], [-50, 30]]})
    r = generate(d)
    assert len(r.holes) > 0
    assert_inside(r, 3)
    assert len(r.circles) == len(r.holes) == r.stats["count"]
    assert 0 < r.stats["open_area_ratio"] < 1


@pytest.mark.parametrize("shape", SHAPES)
def test_dot_shapes(shape):
    d = design("grid", dot={"shape": shape, "custom_points": [[0, 0], [1, 0], [0.5, 1]]})
    r = generate(d)
    assert len(r.holes) > 0 and all(h.is_valid for h in r.holes)
    assert all((c is not None) == (shape == "circle") for c in r.circles)


@pytest.mark.parametrize("mode", ["random", "voronoi", "flowlines"])
def test_seed_determinism(mode):
    a, b = generate(design(mode)), generate(design(mode))
    assert [h.wkb for h in a.holes] == [h.wkb for h in b.holes]
    c = design(mode)
    getattr(c.pattern, mode).seed = 99
    assert [h.wkb for h in generate(c).holes] != [h.wkb for h in a.holes]


def test_random_min_distance():
    r = generate(design("random", pattern={"mode": "random", "random": {"count": 200, "min_distance": 7, "seed": 3}}))
    xy = np.array([h.centroid.coords[0] for h in r.holes])
    dist = np.hypot(*(xy[:, None] - xy[None]).transpose(2, 0, 1))
    assert dist[~np.eye(len(xy), dtype=bool)].min() >= 7 - 1e-6


@pytest.mark.parametrize("margin", [0, 5, 12])
def test_margin_respected(margin):
    r = generate(design("grid", boundary={"type": "circle", "margin": margin}))
    assert_inside(r, margin)
    assert r.outline.buffer(-margin).buffer(-3).intersects(shapely.union_all(r.holes))


def test_clip():
    base = {"type": "circle", "margin": 2}
    drop = generate(design("grid", boundary={**base, "clip": False}))
    clip = generate(design("grid", boundary={**base, "clip": True}))
    assert len(clip.holes) > len(drop.holes)
    assert_inside(clip, 2)
    # clipped holes are no longer exact circles
    assert sum(c is None for c in clip.circles) == len(clip.holes) - len(drop.holes)
    assert all(c is not None for c in drop.circles)


def test_circles_match_holes():
    r = generate(design("grid"))
    for h, (cx, cy, rad) in zip(r.holes, r.circles):
        assert abs(h.centroid.x - cx) < 1e-6 and abs(h.centroid.y - cy) < 1e-6
        assert abs(rad - 2.0) < 1e-9


def test_size_gradient_monotonic():
    d = design("grid", canvas={"width": 150, "height": 150},
               dot={"diameter": 5}, pattern={"mode": "grid", "grid": {"arrangement": "square"}},
               gradients={"size": {"enabled": True, "edge": 1.0, "falloff": "linear",
                                   "controls": [{"kind": "point", "points": [[0, 0]], "value": 0.2, "radius": 60}]}})
    r = generate(d)
    dist = np.array([np.hypot(*h.centroid.coords[0]) for h in r.holes])
    area = np.array([h.area for h in r.holes])
    order = np.argsort(dist)
    near = dist[order] < 60
    assert np.all(np.diff(area[order][near]) >= -1e-6)
    assert area[order][0] < 0.1 * area.max()


def test_gradient_controls_and_noise():
    from ventforge.model import Canvas, Gradient
    g = Gradient(enabled=True, edge=1.0, controls=[
        Control(kind="line", points=[[-50, 0], [50, 0]], value=0.0, radius=10),
        Control(kind="curve", points=[[-50, 30], [0, 40], [50, 30]], value=2.0, radius=10)])
    v = sample_gradient(g, [[0, 0], [0, 100], [0, 40]], Canvas())
    assert v[0] == pytest.approx(0) and v[1] == pytest.approx(1) and v[2] == pytest.approx(2, abs=0.05)
    g.noise = 0.5
    n = sample_gradient(g, np.random.default_rng(0).uniform(-50, 50, (500, 2)), Canvas())
    assert n.std() > 0.01 and np.all(n >= 0)
    assert np.all(sample_gradient(Gradient(), [[1, 2]], Canvas(), 0.0) == 0)


def test_image_gradient(tmp_path):
    from PIL import Image
    a = np.tile(np.linspace(0, 255, 64, dtype=np.uint8), (64, 1))  # dark left, white right
    Image.fromarray(a).save(tmp_path / "g.png")
    d = design("grid", gradients={"size": {"enabled": True, "image": str(tmp_path / "g.png"),
                                           "image_min": 0.2, "image_max": 1.0}})
    r = generate(d)
    left = [h.area for h in r.holes if h.centroid.x < -30]
    right = [h.area for h in r.holes if h.centroid.x > 30]
    assert max(left) < min(right)


def test_spacing_gradient_increases_density():
    common = {"canvas": {"width": 150, "height": 150}, "dot": {"diameter": 2}}
    plain = generate(design("grid", **common))
    d = design("grid", **common, gradients={"spacing": {"enabled": True, "edge": 1.0,
               "controls": [{"points": [[0, 0]], "value": 0.5, "radius": 50}]}})
    dense = generate(d)

    def near(r):
        return sum(np.hypot(*h.centroid.coords[0]) < 15 for h in r.holes)
    assert near(dense) > 2 * near(plain)
    assert_inside(dense, 2)


@pytest.mark.parametrize("target", TARGET_SHAPES)
def test_shape_and_angle_gradient(target):
    d = design("grid", gradients={"target_shape": target,
               "shape": {"enabled": True, "edge": 1.0},
               "angle": {"enabled": True, "edge": 0.0, "controls": [{"points": [[0, 0]], "value": 45, "radius": 40}]}})
    r = generate(d)
    assert len(r.holes) > 0 and all(h.is_valid for h in r.holes)
    assert all(c is None for c in r.circles)


def test_mode_parameters():
    g = generate(design("grid", pattern={"mode": "grid", "grid": {"row_rotation": 30, "rotation": 15}}))
    assert len(g.holes) > 0
    p = generate(design("path", pattern={"mode": "path", "path": {
        "points": [[-30, -30], [30, -30], [0, 30]], "count": 20, "layers": 3, "closed": False}}))
    assert 50 <= len(p.holes) <= 70  # 20 on the base path, offsets scaled by their length
    c = generate(design("concentric", pattern={"mode": "concentric", "concentric": {"outer_radius": 20}}))
    assert max(np.hypot(*h.centroid.coords[0]) for h in c.holes) <= 20 + 1e-6
    f = design("flowlines")
    f.pattern.flowlines.invert = True
    assert len(generate(f).holes) > 0
    f.pattern.flowlines.invert = False
    f.pattern.flowlines.follow_boundary = True
    f.boundary.type = "circle"
    assert len(generate(f).holes) > 0


def _path_dots(**path):
    return generate(design("path", pattern={"mode": "path", "path": path}))


def test_path_layers_constant_spacing():
    # count 40 -> base step 5.5 mm; default count 60 (3.66 mm) already overlaps 4 mm dots on the base ring
    r = _path_dots(count=40, layers=12, layer_spacing=6)
    assert r.stats["min_wall_violations"] == 0
    c = np.array([h.centroid.coords[0] for h in r.holes])
    rad = np.round(np.hypot(*c.T), 1)
    for ring in np.unique(rad):
        pts = c[rad == ring]
        if len(pts) < 3 or ring > 45:  # outer rings are clipped by the 100 mm plate
            continue
        step = 2 * np.pi * ring / len(pts)
        assert 4.6 < step < 6.6, (ring, step)


def test_path_degenerate_layers_dropped():
    # small circle r=5: inward offsets beyond r collapse and must vanish, not flip outward
    pts = [[5 * np.cos(a), 5 * np.sin(a)] for a in np.linspace(0, 2 * np.pi, 24, endpoint=False)]
    r = _path_dots(points=pts, count=10, layers=5, layer_spacing=4)
    rad = np.hypot(*np.array([h.centroid.coords[0] for h in r.holes]).T)
    assert set(np.round(rad).astype(int)) <= {5, 9, 13}
    # open zig-zag custom path with layers works
    o = _path_dots(points=[[-40, 0], [-10, 20], [10, -20], [40, 0]], closed=False, layers=3, count=30)
    assert len(o.holes) > 60


def test_path_seam_not_duplicated():
    r = _path_dots(count=30, layers=1)
    c = np.array([h.centroid.coords[0] for h in r.holes])
    assert len(c) == 30
    dist = np.hypot(*(c[:, None] - c[None]).T)
    assert dist[~np.eye(len(c), dtype=bool)].min() > 0.9 * 2 * np.pi * 35 / 30
    a = _path_dots(count=30, smooth=False, points=[[-30, -30], [30, -30], [30, 30], [-30, 30]])
    assert len(a.holes) == 30
    assert len(_path_dots(count=30, align=False).holes) == 30


def test_min_wall_violations():
    tight = generate(design("grid", dot={"diameter": 5.6}, pattern={"mode": "grid", "grid": {"arrangement": "square"}}))
    assert tight.stats["min_wall_violations"] == tight.stats["count"]
    loose = generate(design("grid"))
    assert loose.stats["min_wall_violations"] == 0


@pytest.mark.parametrize("path", PRESETS, ids=lambda p: p.name)
def test_presets(path):
    r = generate(Design.load(path))
    assert len(r.holes) > 0
    assert_inside(r, 0)
    assert r.stats["min_wall_violations"] <= 0.01 * r.stats["count"]


def test_presets_exist():
    assert len(PRESETS) >= 6


def test_perf_2000_dots_with_gradient():
    d = design("grid", canvas={"width": 200, "height": 200}, dot={"diameter": 3},
               pattern={"mode": "grid", "grid": {"arrangement": "square", "spacing_x": 4.4, "spacing_y": 4.4}},
               gradients={"size": {"enabled": True, "edge": 1.0,
                                   "controls": [{"points": [[-100, -100]], "value": 0.3, "radius": 150}]}})
    generate(d)
    t = time.perf_counter()
    r = generate(d)
    dt = time.perf_counter() - t
    assert len(r.holes) > 1800
    assert dt < 0.3, dt


@pytest.mark.parametrize("mode", ["grid", "concentric", "crosslines", "spiral", "fibonacci"])
def test_spacing_noise_and_image_warp(mode, tmp_path):
    from PIL import Image
    import numpy as np
    base = Design()
    base.pattern.mode = mode
    c0 = sorted((round(h.centroid.x, 2), round(h.centroid.y, 2)) for h in generate(base).holes)
    noisy = generate(base.patched({"gradients": {"spacing": {"enabled": True, "noise": 0.6}}}))
    assert sorted((round(h.centroid.x, 2), round(h.centroid.y, 2)) for h in noisy.holes) != c0
    ramp = tmp_path / "ramp.png"
    Image.fromarray(np.tile(np.linspace(0, 255, 64), (64, 1)).astype("uint8")).save(ramp)
    r = generate(base.patched({"gradients": {"spacing": {"enabled": True, "image": str(ramp),
                                                         "image_min": 0.5, "image_max": 1.5}}}))
    xs = np.array([h.centroid.x for h in r.holes])
    assert (xs < 0).sum() > (xs > 0).sum()  # denser where the image is dark (small spacing)


def test_tiny_values_clamped_fast():
    import time
    for patch in ({"pattern": {"grid": {"spacing_x": 0.01, "spacing_y": 0.01}}},
                  {"pattern": {"mode": "flowlines", "flowlines": {"wavelength": 0.01}}},
                  {"pattern": {"mode": "spiral", "spiral": {"count": 10**7}}}):
        t = time.perf_counter()
        generate(Design().patched(patch))
        assert time.perf_counter() - t < 25, patch  # was 30-100 s before the clamps (CI runners are slow)


@pytest.mark.parametrize("invert", [False, True])
@pytest.mark.parametrize("boundary", ["none", "circle", "rounded_rectangle"])
def test_follow_boundary_keeps_plate_in_one_piece(boundary, invert):
    d = Design().patched({"boundary": {"type": boundary}, "pattern": {
        "mode": "flowlines", "flowlines": {"follow_boundary": True, "invert": invert}}})
    r = generate(d)
    assert r.holes
    plate = r.outline.difference(shapely.union_all(r.holes))
    assert len(shapely.get_parts(plate)) == 1  # no loose rings falling out


def test_image_paths_resolve_against_design_file(tmp_path, monkeypatch):
    from PIL import Image
    Image.new("L", (8, 8), 128).save(tmp_path / "fade.png")
    d = Design()
    d.gradients.size.enabled = True
    d.gradients.size.image = "fade.png"
    d.background.image = "fade.png"
    d.save(tmp_path / "x.vent.json")
    monkeypatch.chdir(tmp_path.parent)  # a different working folder, like the MCP server's
    loaded = Design.load(tmp_path / "x.vent.json")
    assert loaded.gradients.size.image == str((tmp_path / "fade.png").resolve())
    assert loaded.background.image == loaded.gradients.size.image
    assert generate(loaded).holes
    loaded.save(tmp_path / "x.vent.json")  # saving again keeps the path relative (folder stays movable)
    assert '"image": "fade.png"' in (tmp_path / "x.vent.json").read_text()


def test_missing_image_is_a_clear_error(tmp_path):
    d = Design().patched({"gradients": {"size": {"enabled": True, "image": str(tmp_path / "gone.png")}}})
    with pytest.raises(FileNotFoundError, match="gone.png"):
        generate(d)


def test_unknown_choice_rejected():
    with pytest.raises(ValueError, match="dot.shape"):
        Design().patched({"dot": {"shape": "hexgon"}})
    with pytest.raises(ValueError, match="rotate_by"):
        Design().patched({"pattern": {"crosslines": {"rotate_by": "row"}}})


def test_fibonacci_even_density_with_hole():
    d = Design().patched({"canvas": {"width": 200, "height": 200}, "dot": {"diameter": 1},
                          "pattern": {"mode": "fibonacci", "fibonacci": {
                              "count": 1500, "spread": 2.0, "inner_radius": 30}}})
    r = np.hypot(*np.array([h.centroid.coords[0] for h in generate(d).holes]).T)
    assert r.min() >= 29
    inner = ((r >= 30) & (r < 45)).sum() / (np.pi * (45 ** 2 - 30 ** 2))
    outer = ((r >= 60) & (r < 75)).sum() / (np.pi * (75 ** 2 - 60 ** 2))
    assert inner == pytest.approx(outer, rel=0.15)


def test_huge_concentric_radius_and_path_layers_stay_fast():
    import time
    for patch in ({"pattern": {"mode": "concentric", "concentric": {
                      "outer_radius": 30000}}},  # ~80M points before the clamp
                  {"pattern": {"mode": "path", "path": {"layers": 5000}}}):
        t = time.perf_counter()
        assert generate(Design().patched(patch)).holes
        assert time.perf_counter() - t < 4, patch  # was out-of-memory / 5 s
