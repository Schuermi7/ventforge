import math
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


def test_old_file_with_bad_choice_still_loads(tmp_path):
    # 0.1.0 advertised row/col for crosslines; such files must open, falling back to the default
    p = tmp_path / "old.vent.json"
    p.write_text('{"pattern": {"mode": "crosslines", "crosslines": {"rotate_by": "row"}}}')
    d = Design.load(p)
    assert d.pattern.crosslines.rotate_by == "both" and d.pattern.mode == "crosslines"


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


@pytest.mark.parametrize("patch", [
    {"canvas": {"width": 2000, "height": 2000}, "pattern": {"grid": {"spacing_x": 1, "spacing_y": 1}}},
    {"canvas": {"width": 3000, "height": 3000}, "pattern": {"mode": "voronoi", "voronoi": {"cell_size": 1}}},
    {"canvas": {"width": 3000, "height": 3000}, "pattern": {"mode": "concentric"}},
])
def test_huge_layouts_refused_fast(patch):
    t = time.perf_counter()
    with pytest.raises(ValueError, match="points"):
        generate(Design().patched(patch))
    assert time.perf_counter() - t < 2  # was minutes and gigabytes


def test_bad_types_rejected():
    with pytest.raises(ValueError, match="boundary.clip"):
        Design().patched({"boundary": {"clip": "false"}})  # bool("false") would switch clipping on
    with pytest.raises(ValueError, match="dot must be an object"):
        Design().patched({"dot": 5})


def test_fan_grille_holes_over_blades_and_screw_holes():
    from ventforge.model import FANS, fan_grille
    d = fan_grille(Design(), 120)
    r = generate(d)
    pitch, screw = FANS[120]
    screws = {(round(c[0], 2), round(c[1], 2)) for c in r.circles if c and abs(c[2] - screw / 2) < 1e-9}
    assert screws == {(sx * pitch / 2, sy * pitch / 2) for sx in (-1, 1) for sy in (-1, 1)}
    opening = shapely.Point(0, 0).buffer(d.boundary.vent_diameter / 2 + 1e-6)
    assert sum(opening.contains(h) for h in r.holes) == len(r.holes) - 4
    assert 0.2 < r.stats["fan_open_ratio"] < 0.8
    with pytest.raises(ValueError, match="fan size"):
        fan_grille(Design(), 77)


def test_keepout_stays_free():
    d = Design().patched({"keepouts": [{"shape": "rectangle", "x": 10, "y": -5, "width": 30, "height": 12,
                                        "clearance": 2}]})
    zone = shapely.box(10 - 17, -5 - 8, 10 + 17, -5 + 8).buffer(-1e-6)  # touching the edge is fine
    holes = generate(d).holes
    assert holes and not any(zone.intersects(h) for h in holes)


def test_tool_radius_rounds_corners_and_drops_too_small():
    d = Design().patched({"dot": {"shape": "rounded_rectangle", "corner_radius": 0, "diameter": 4}})
    sharp = generate(d)
    d.machining.tool_radius = 1.0
    r = generate(d)
    assert len(r.holes) == len(sharp.holes)
    assert r.holes[0].area == pytest.approx(16 - (4 - math.pi) * 1.0, rel=0.02)  # 4 corners lose (1 - pi/4) r^2
    d.machining.tool_radius = 2.5  # wider than the 4 mm holes
    assert generate(d).stats["dropped_by_tool"] == len(sharp.holes)


def test_kerf_offsets_cut_paths():
    from ventforge.export import cut_paths
    d = Design()
    d.machining.kerf = 0.2
    r = generate(d)
    c = cut_paths(r, d)
    assert c.circles[0][2] == pytest.approx(r.circles[0][2] - 0.1)
    assert c.outline.area > r.outline.area


def test_keepout_hole_is_cut_with_free_clearance_around_it():
    d = Design().patched({"keepouts": [{"shape": "rectangle", "x": 0, "y": 0, "width": 10, "height": 6,
                                        "hole": True}]})
    r = generate(d)
    assert any(h.equals_exact(shapely.box(-5, -3, 5, 3), 1e-6) or abs(h.area - 60) < 1e-6 for h in r.holes)
    assert not any(h.intersects(shapely.box(-6.4, -4.4, 6.4, 4.4)) for h in r.holes if abs(h.area - 60) > 1e-6)


def test_thinnest_wall_found_and_located():
    d = Design().patched({"pattern": {"mode": "custom_points", "custom_points": {"points": [[0, 0], [5, 0], [30, 30]]}},
                          "dot": {"diameter": 4}})
    s = generate(d).stats
    assert s["thinnest_wall"] == pytest.approx(1.0, abs=0.01)  # centres 5 apart, radius 2 each
    assert s["thinnest_wall_at"] == pytest.approx([2.5, 0], abs=0.05)


def test_airflow_loss_drops_as_open_area_grows():
    small = generate(Design().patched({"dot": {"diameter": 2}})).stats
    big = generate(Design().patched({"dot": {"diameter": 4}})).stats
    assert big["open_area_ratio"] > small["open_area_ratio"]
    assert 0 < big["pressure_drop_pa"] < small["pressure_drop_pa"]
    assert big["pressure_drop_pa"] == pytest.approx(big["loss_coefficient"] * 1.2 * 4 / 2)


def test_min_feature_flags_narrow_holes():
    d = Design().patched({"dot": {"diameter": 3}})
    assert "below_min_feature" not in generate(d).stats
    d.machining.min_feature = 3.5
    s = generate(d).stats
    assert s["below_min_feature"] == s["count"]


def test_face_design_from_fusion_avoids_what_sits_on_the_face(tmp_path):
    """The JSON the Fusion add-in writes: face outline as boundary, its inner loops as keep-outs."""
    import json
    tri = [[-6, -5], [6, -5], [0, 7]]  # a rib footprint, relative to its centre
    f = tmp_path / "face.vent.json"
    f.write_text(json.dumps({"canvas": {"width": 80, "height": 60},
                             "boundary": {"type": "custom", "points": [[-40, -30], [40, -30], [40, 30], [-40, 30]]},
                             "keepouts": [{"shape": "circle", "x": -25, "y": 15, "width": 8},
                                          {"shape": "polygon", "x": 15, "y": -5, "points": tri}]}))
    d = Design.load(f)
    holes = generate(d).holes
    rib = shapely.Polygon([(15 + x, -5 + y) for x, y in tri]).buffer(1.5 - 1e-6)
    boss = shapely.Point(-25, 15).buffer(4 + 1.5 - 1e-6)
    assert holes and not any(rib.intersects(h) or boss.intersects(h) for h in holes)
