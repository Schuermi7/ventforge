import math
import time

import pytest
import shapely
from shapely.geometry import Point, Polygon, box

from ventforge import export as ex
from ventforge.model import Design, Result


def _hex(cx, cy, d):
    return Polygon([(cx + d / 2 * math.cos(math.radians(30 + 60 * k)),
                     cy + d / 2 * math.sin(math.radians(30 + 60 * k))) for k in range(6)])


def _grid(n_side, pitch):
    off = (n_side - 1) * pitch / 2
    return [(i * pitch - off, j * pitch - off) for i in range(n_side) for j in range(n_side)]


def _result(holes, outline, circles=()):
    a = sum(h.area for h in holes)
    return Result(holes=holes, outline=outline, circles=list(circles),
                  stats={"count": len(holes), "hole_area": a, "plate_area": outline.area,
                         "open_area_ratio": a / outline.area, "min_wall_violations": 0})


def hex_result(n=2025):  # 45x45 hexes, 4 mm pitch, 3 mm across corners, on a 200x200 plate
    side = int(math.sqrt(n))
    return _result([_hex(x, y, 3.0) for x, y in _grid(side, 4.0)], box(-100, -100, 100, 100))


def circle_result(n=2025):
    side = int(math.sqrt(n))
    pts = _grid(side, 4.0)
    return _result([Point(x, y).buffer(1.5, 64) for x, y in pts], box(-100, -100, 100, 100),
                   [(x, y, 1.5) for x, y in pts])


def tricky_result():
    """Circular outline, holes clipped by the edge, overlapping holes, one hole with an island."""
    outline = Point(0, 0).buffer(50, 128)
    holes, circles = [], []
    for x, y in _grid(21, 5.0):
        c = Point(x, y).buffer(2.0, 64)
        if not outline.intersects(c):
            continue
        clipped = c.intersection(outline)
        exact = outline.buffer(-1e-6).contains(c)
        holes.append(clipped)
        circles.append((x, y, 2.0) if exact else None)
    # two overlapping circles marked exact: must be merged before building
    holes += [Point(2.5, 2.5).buffer(1.4, 64)]
    circles += [(2.5, 2.5, 1.4)]
    return _result(holes, outline, circles)


def design(t=2.0, w=200, h=200):
    d = Design()
    d.canvas.thickness, d.canvas.width, d.canvas.height = t, w, h
    return d


def expected_volume(res, t):
    return res.outline.difference(shapely.union_all(res.holes)).area * t


@pytest.fixture(scope="module")
def tmp(tmp_path_factory):
    return tmp_path_factory.mktemp("export")


@pytest.mark.parametrize("ext", ["svg", "png", "dxf", "step", "stl"])
def test_every_format_writes(tmp, ext):
    res = tricky_result()
    p = tmp / f"t.{ext}"
    ex.export(res, design(), p)
    assert p.stat().st_size > 100


def test_svg_content(tmp):
    res = circle_result(100)
    p = tmp / "c.svg"
    ex.to_svg(res, design(), p)
    s = p.read_text()
    assert 'width="200.0000mm"' in s and s.count("<circle") == 100


@pytest.mark.parametrize("make,t", [(hex_result, 2.0), (circle_result, 3.0), (tricky_result, 1.5)])
def test_step_roundtrip_volume(tmp, make, t):
    res = make()
    p = tmp / f"{make.__name__}.step"
    ex.to_step(res, design(t), p)
    shape = ex.read_step(p)
    sols = ex.solids(shape)
    assert len(sols) == 1
    ex._check(shape, "reimport")  # full BRepCheck when small, else volume/solid checks
    assert ex.volume(shape) == pytest.approx(expected_volume(res, t), rel=0.005)


def test_step_multipart(tmp):
    # a slot cutting the plate in two -> two solids
    res = _result([box(-1, -60, 1, 60)], box(-50, -50, 50, 50))
    p = tmp / "split.step"
    ex.to_step(res, design(2), p)
    shape = ex.read_step(p)
    assert len(ex.solids(shape)) == 2
    assert ex.volume(shape) == pytest.approx((100 * 100 - 2 * 100) * 2, rel=0.005)


def test_dxf_counts(tmp):
    import ezdxf
    res = tricky_result()
    p = tmp / "t.dxf"
    ex.to_dxf(res, p)
    msp = ezdxf.readfile(p).modelspace()
    n_circ = sum(1 for c in res.circles if c)
    assert len(msp.query("CIRCLE[layer=='HOLES']")) == n_circ
    assert len(msp.query("LWPOLYLINE[layer=='HOLES']")) == len(res.holes) - n_circ
    assert len(msp.query("LWPOLYLINE[layer=='OUTLINE']")) == 1


def test_png_size_and_speed(tmp):
    from PIL import Image
    res = hex_result()
    t0 = time.perf_counter()
    data = ex.to_png(res, design(), tmp / "h.png", px=1200)
    dt = time.perf_counter() - t0
    im = Image.open(tmp / "h.png")
    assert max(im.size) == 1200 and im.mode == "RGBA"
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    assert dt < 0.5, dt


@pytest.mark.parametrize("make,limit", [(circle_result, 3.0), (hex_result, 10.0)])
def test_flat_step_perf(tmp, make, limit):
    # hexes: ~1.5 s build + ~5.5 s OCC STEP writer (linear floor, 12k side faces)
    res = make()
    t0 = time.perf_counter()
    ex.to_step(res, design(), tmp / "perf.step")
    assert time.perf_counter() - t0 < limit


def test_wrap_cylinder(tmp):
    # 100 x 40 canvas, 10x4 circles + some hexes
    pts = [(x, y) for x in range(-45, 50, 10) for y in (-15, -5, 5, 15)]
    holes = [Point(x, y).buffer(1.5, 64) for x, y in pts] + [_hex(0, 0, 3)]
    circles = [(x, y, 1.5) for x, y in pts] + [None]
    res = _result(holes, box(-50, -20, 50, 20), circles)
    d = design(2.0, 100, 40)
    info = ex.wrap_cylinder(res, d, tmp / "wrap.step")
    assert info["holes"] == len(holes)
    shape = ex.read_step(tmp / "wrap.step")
    assert len(ex.solids(shape)) == 1
    R = 100 / (2 * math.pi)
    tube = math.pi * (R ** 2 - (R - 2) ** 2) * 40
    holes_vol = sum(h.area for h in holes) * 2  # approx: hole area x wall
    assert ex.volume(shape) == pytest.approx(tube - holes_vol, rel=0.02)
    ex.wrap_cylinder(res, d, tmp / "wrap.stl")
    assert (tmp / "wrap.stl").stat().st_size > 1000


def _box_step(path, lx, ly, lz):
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.gp import gp_Pnt
    ex._write(BRepPrimAPI_MakeBox(gp_Pnt(-lx / 2, -ly / 2, 0), lx, ly, lz).Shape(), path)


def test_cut_into_part(tmp):
    _box_step(tmp / "box.step", 120, 120, 10)
    pts = _grid(10, 8.0)
    res = _result([Point(x, y).buffer(2, 64) for x, y in pts] + [_hex(0, 0, 3)],
                  box(-50, -50, 50, 50), [(x, y, 2) for x, y in pts] + [None])
    info = ex.cut_into_part(res, design(), tmp / "box.step", tmp / "cut.step",
                            origin=(0, 0, 10), normal=(0, 0, 1))
    assert info["holes"] == len(res.holes)
    shape = ex.read_step(tmp / "cut.step")
    assert len(ex.solids(shape)) == 1
    holes_area = shapely.union_all(res.holes).area
    assert ex.volume(shape) == pytest.approx((120 * 120 - holes_area) * 10, rel=0.005)
    # side face, blind 3 mm
    info = ex.cut_into_part(res, design(), tmp / "box.step", tmp / "side.stl",
                            origin=(60, 0, 5), normal=(1, 0, 0), x_dir=(0, 1, 0), depth=3)
    assert (tmp / "side.stl").stat().st_size > 1000


def test_export_rejects_unknown(tmp):
    with pytest.raises(ValueError):
        ex.export(hex_result(4), design(), tmp / "x.obj")
