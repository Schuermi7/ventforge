"""Exporters: SVG, PNG, DXF, STEP, STL, plus wrap-onto-cylinder and cut-into-existing-part.

All inputs are a pattern `Result` (shapely polygons in mm, y-up) and the `Design`.
3D plates are built by direct construction (one face with inner wires, then a prism),
never by boolean cuts: ~100x faster for thousands of holes.
"""
from __future__ import annotations

import io
import math
import time
from pathlib import Path

import shapely
from shapely.geometry import Polygon
from shapely.geometry.polygon import orient
from shapely.strtree import STRtree

from .model import Design, Result


def _circle(result: Result, i: int):
    return result.circles[i] if i < len(result.circles) else None


def _parts(geom) -> list[Polygon]:
    if geom.is_empty:
        return []
    if isinstance(geom, Polygon):
        return [geom]
    return [g for g in getattr(geom, "geoms", []) if isinstance(g, Polygon) and not g.is_empty]


def _ring_xy(ring) -> list[tuple[float, float]]:
    return list(ring.coords)[:-1]


# --------------------------------------------------------------------------- SVG
def to_svg(result: Result, design: Design, path) -> None:
    minx, miny, maxx, maxy = result.outline.bounds
    w, h = maxx - minx, maxy - miny

    def d(poly: Polygon) -> str:
        out = []
        for ring in [poly.exterior, *poly.interiors]:
            pts = _ring_xy(ring)
            out.append("M" + " L".join(f"{x:.4f},{-y:.4f}" for x, y in pts) + " Z")
        return " ".join(out)

    color = design.dot.color
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w:.4f}mm" height="{h:.4f}mm" '
        f'viewBox="{minx:.4f} {-maxy:.4f} {w:.4f} {h:.4f}">',
        f'<title>{_xml(design.name)}</title>',
        f'<path id="outline" d="{d(orient(result.outline))}" fill="none" stroke="#000000" '
        f'stroke-width="{max(w, h) / 1000:.4f}"/>',
        f'<g id="holes" fill="{_xml(color)}" stroke="none" fill-rule="evenodd">',
    ]
    for i, hole in enumerate(result.holes):
        c = _circle(result, i)
        if c:
            lines.append(f'<circle cx="{c[0]:.4f}" cy="{-c[1]:.4f}" r="{c[2]:.4f}"/>')
        else:
            for p in _parts(hole):
                lines.append(f'<path d="{d(p)}"/>')
    lines += ["</g>", "</svg>"]
    Path(path).write_text("\n".join(lines), encoding="utf-8")


def _xml(s: str) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


# --------------------------------------------------------------------------- PNG
def to_png(result: Result, design: Design, path=None, px: int = 1200,
           transparent: bool = True, show_outline: bool = True) -> bytes:
    from PIL import Image, ImageDraw

    ss = 3  # supersample factor
    minx, miny, maxx, maxy = result.outline.bounds
    pad = 0.01 * max(maxx - minx, maxy - miny)
    minx, miny, maxx, maxy = minx - pad, miny - pad, maxx + pad, maxy + pad
    s = px / max(maxx - minx, maxy - miny)
    W, H = max(1, round((maxx - minx) * s)), max(1, round((maxy - miny) * s))
    k = s * ss

    def tr(pts):
        return [((x - minx) * k, (maxy - y) * k) for x, y in pts]

    img = Image.new("RGBA", (W * ss, H * ss), (0, 0, 0, 0) if transparent else (255, 255, 255, 255))
    dr = ImageDraw.Draw(img)
    color = design.dot.color
    for i, hole in enumerate(result.holes):
        c = _circle(result, i)
        if c:
            cx, cy = (c[0] - minx) * k, (maxy - c[1]) * k
            r = c[2] * k
            dr.ellipse((cx - r, cy - r, cx + r, cy + r), fill=color)
            continue
        for p in _parts(hole):
            dr.polygon(tr(_ring_xy(p.exterior)), fill=color)
            for ring in p.interiors:  # islands inside a hole: punch back to background
                dr.polygon(tr(_ring_xy(ring)), fill=img.getpixel((0, 0)))
    if show_outline:
        lw = max(1, round(ss * px / 600))
        for p in _parts(result.outline):
            for ring in [p.exterior, *p.interiors]:
                pts = tr(ring.coords)
                dr.line(pts, fill="#333333", width=lw, joint="curve")
    img = img.resize((W, H), Image.Resampling.BOX)
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=False, compress_level=1)
    data = buf.getvalue()
    if path:
        Path(path).write_bytes(data)
    return data


# --------------------------------------------------------------------------- DXF
def to_dxf(result: Result, path) -> None:
    import ezdxf
    from ezdxf import units

    doc = ezdxf.new("R2010", setup=False)
    doc.units = units.MM
    doc.layers.add("OUTLINE", color=7)
    doc.layers.add("HOLES", color=1)
    msp = doc.modelspace()

    def poly(p: Polygon, layer: str):
        for ring in [p.exterior, *p.interiors]:
            msp.add_lwpolyline(_ring_xy(ring), close=True, dxfattribs={"layer": layer})

    for p in _parts(result.outline):
        poly(p, "OUTLINE")
    for i, hole in enumerate(result.holes):
        c = _circle(result, i)
        if c:
            msp.add_circle((c[0], c[1]), c[2], dxfattribs={"layer": "HOLES"})
        else:
            for p in _parts(hole):
                poly(p, "HOLES")
    doc.saveas(str(path))


# --------------------------------------------------------------------------- OCC helpers
def _occ_wire_poly(pts, z=0.0, frame=None):
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakePolygon
    from OCP.gp import gp_Pnt

    mp = BRepBuilderAPI_MakePolygon()
    for x, y in pts:
        mp.Add(frame(x, y) if frame else gp_Pnt(x, y, z))
    mp.Close()
    return mp.Wire()


def _occ_wire_circle(cx, cy, r, ccw: bool, ax=None):
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeWire
    from OCP.gp import gp_Ax2, gp_Circ, gp_Dir, gp_Pnt

    if ax is None:
        ax = gp_Ax2(gp_Pnt(cx, cy, 0), gp_Dir(0, 0, 1 if ccw else -1))
    return BRepBuilderAPI_MakeWire(BRepBuilderAPI_MakeEdge(gp_Circ(ax, r)).Edge()).Wire()


def _clean(p: Polygon) -> Polygon:
    # drop micro-segments from shapely booleans; OCC rejects near-degenerate edges
    q = p.simplify(1e-4, preserve_topology=True)
    return orient(q if q.is_valid and not q.is_empty else p, 1.0)


def _split(result: Result):
    """-> (simple, complex): simple = [(hole, (cx,cy,r))] exact circles with clearance from the
    outline edge and every other hole; complex = all other hole polygons (to be unioned in 2D)."""
    holes = result.holes
    if not holes:
        return [], []
    tree = STRtree(holes)
    edge = result.outline.boundary
    simple, complex_ = [], []
    for i, h in enumerate(holes):
        c = _circle(result, i)
        eps = 0.005 + 0.01 * c[2] if c else 0  # polygon vs exact arc bulge + slack
        if (c and result.outline.contains(shapely.Point(c[0], c[1]))
                and edge.distance(shapely.Point(c[0], c[1])) > c[2] + eps
                and len(tree.query(h, predicate="dwithin", distance=eps)) == 1):
            simple.append((h, c))
        else:
            complex_.append(h)
    return simple, complex_


def _plate_faces(result: Result):
    """Planar faces at z=0 = outline minus holes, plus the expected area (for validation)."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace

    simple, complex_ = _split(result)
    # grow holes by 1e-5 mm so edges that coincide with the outline (clipped holes) cut cleanly
    # instead of leaving zero-width slivers, which OCC sees as self-intersecting wires
    cut = shapely.union_all(complex_).buffer(1e-5, join_style="mitre") if complex_ else None
    plate = result.outline.difference(cut) if cut is not None else result.outline
    parts = [_clean(p) for p in _parts(plate) if p.area > 1e-9]
    area = sum(p.area for p in parts)

    builders = []
    for p in parts:
        mf = BRepBuilderAPI_MakeFace(_occ_wire_poly(_ring_xy(p.exterior)), True)
        for ring in p.interiors:
            mf.Add(_occ_wire_poly(_ring_xy(ring)))
        builders.append(mf)
    if simple:
        ptree = STRtree(parts)
        for _, (cx, cy, r) in simple:
            idx = ptree.query(shapely.Point(cx, cy), predicate="intersects")
            if len(idx):
                builders[int(idx[0])].Add(_occ_wire_circle(cx, cy, r, ccw=False))
                area -= math.pi * r * r
    faces = []
    for mf in builders:
        if not mf.IsDone():
            raise RuntimeError("VentForge export: could not build plate face")
        faces.append(mf.Face())
    return faces, area


def _compound(shapes):
    from OCP.BRep import BRep_Builder
    from OCP.TopoDS import TopoDS_Compound

    comp = TopoDS_Compound()
    b = BRep_Builder()
    b.MakeCompound(comp)
    for s in shapes:
        b.Add(comp, s)
    return comp


FULL_CHECK_EDGES = 3000


def _check(shape, what: str, expect_volume=None):
    """BRepCheck the result. Its face check is O(edges^2) (40 s for 2000 hexes), so above
    FULL_CHECK_EDGES we rely on the 2D validity guaranteed by shapely and check the volume.
    shortcut: big shapes skip BRepCheck, raise FULL_CHECK_EDGES if you need it always."""
    from OCP.BRepCheck import BRepCheck_Analyzer
    from OCP.TopAbs import TopAbs_EDGE
    from OCP.TopExp import TopExp_Explorer

    if not solids(shape):
        raise RuntimeError(f"VentForge export: {what} produced no solid")
    n, ex = 0, TopExp_Explorer(shape, TopAbs_EDGE)
    while ex.More() and n <= 2 * FULL_CHECK_EDGES:  # explorer visits shared edges twice
        n += 1
        ex.Next()
    if n <= 2 * FULL_CHECK_EDGES and not BRepCheck_Analyzer(shape, True, True).IsValid():
        raise RuntimeError(f"VentForge export: {what} produced an invalid solid (BRepCheck failed)")
    if expect_volume is not None:
        v = volume(shape)
        if abs(v - expect_volume) > 1e-3 * abs(expect_volume) + 1e-6:
            raise RuntimeError(f"VentForge export: {what} solid is invalid "
                               f"(volume {v:.3f} != expected {expect_volume:.3f} mm^3)")
    return shape


def _write(shape, path, tolerance: float = 0.05):
    path = Path(path)
    if path.suffix.lower() == ".stl":
        from OCP.BRepMesh import BRepMesh_IncrementalMesh
        from OCP.StlAPI import StlAPI_Writer

        BRepMesh_IncrementalMesh(shape, tolerance, False, 0.5, True).Perform()
        w = StlAPI_Writer()
        w.ASCIIMode = False
        if not w.Write(shape, str(path)):
            raise RuntimeError(f"STL write failed: {path}")
    else:
        from OCP.IFSelect import IFSelect_RetDone
        from OCP.Interface import Interface_Static
        from OCP.STEPControl import STEPControl_AsIs, STEPControl_Writer

        w = STEPControl_Writer()  # registers the write.step.* statics, so set them after this
        Interface_Static.SetCVal_s("write.step.unit", "MM")
        # body name in CAD; OCC's default is "Open CASCADE STEP translator 8.0 1"
        Interface_Static.SetCVal_s("write.step.product.name", path.stem)
        w.Transfer(shape, STEPControl_AsIs)
        if w.Write(str(path)) != IFSelect_RetDone:
            raise RuntimeError(f"STEP write failed: {path}")


def read_step(path):
    from OCP.IFSelect import IFSelect_RetDone
    from OCP.STEPControl import STEPControl_Reader

    r = STEPControl_Reader()
    if r.ReadFile(str(path)) != IFSelect_RetDone:
        raise RuntimeError(f"cannot read STEP: {path}")
    r.TransferRoots()
    return r.OneShape()


def solids(shape) -> list:
    from OCP.TopAbs import TopAbs_SOLID
    from OCP.TopExp import TopExp_Explorer

    out, ex = [], TopExp_Explorer(shape, TopAbs_SOLID)
    while ex.More():
        out.append(ex.Current())
        ex.Next()
    return out


def volume(shape) -> float:
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps

    g = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, g)
    return g.Mass()


# --------------------------------------------------------------------------- flat plate
TILE_EDGES = 400  # target edges per top face; OCC STEP write/read is ~O(wires^2) per face


def _count(shape, typ) -> int:
    from OCP.TopExp import TopExp_Explorer

    n, e = 0, TopExp_Explorer(shape, typ)
    while e.More():
        n += 1
        e.Next()
    return n


def _tiled_prism(face, t: float):
    """Prism of `face` as ONE solid whose top/bottom are split into tiles.

    A single face with thousands of inner wires makes the STEP writer (and CAD readers)
    quadratic: 41 s for 2000 hexes. Splitting the face with a line grid (exact circles stay
    exact arcs), extruding the connected faces into a compsolid and dissolving the shared
    internal walls gives the same solid at ~linear cost.
    """
    from OCP.BRep import BRep_Builder
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Splitter
    from OCP.BRepBndLib import BRepBndLib
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge
    from OCP.BRepLib import BRepLib_MakeSolid
    from OCP.BRepPrimAPI import BRepPrimAPI_MakePrism
    from OCP.collections import List_TopoDS_Shape
    from OCP.TopAbs import TopAbs_EDGE
    from OCP.TopoDS import TopoDS_CompSolid
    from OCP.gp import gp_Pnt, gp_Vec

    k = math.ceil(math.sqrt(_count(face, TopAbs_EDGE) / TILE_EDGES))
    if k <= 1:
        return BRepPrimAPI_MakePrism(face, gp_Vec(0, 0, t)).Shape()
    bb = Bnd_Box()
    BRepBndLib.Add_s(face, bb)
    lo, hi = bb.CornerMin(), bb.CornerMax()
    x0, y0, x1, y1 = lo.X(), lo.Y(), hi.X(), hi.Y()
    tools = List_TopoDS_Shape()
    for i in range(1, k):
        # irrational-ish offsets so cut lines rarely hit vertices or run along grid edges
        x = x0 + (i + 0.0137) * (x1 - x0) / k
        y = y0 + (i + 0.0291) * (y1 - y0) / k
        tools.Append(BRepBuilderAPI_MakeEdge(gp_Pnt(x, y0 - 1, 0), gp_Pnt(x, y1 + 1, 0)).Edge())
        tools.Append(BRepBuilderAPI_MakeEdge(gp_Pnt(x0 - 1, y, 0), gp_Pnt(x1 + 1, y, 0)).Edge())
    args = List_TopoDS_Shape()
    args.Append(face)
    sp = BRepAlgoAPI_Splitter()
    sp.SetArguments(args)
    sp.SetTools(tools)
    sp.SetRunParallel(True)
    sp.Build()
    if not sp.IsDone():
        return BRepPrimAPI_MakePrism(face, gp_Vec(0, 0, t)).Shape()  # slow but correct
    cells = solids(BRepPrimAPI_MakePrism(sp.Shape(), gp_Vec(0, 0, t)).Shape())
    cs = TopoDS_CompSolid()
    b = BRep_Builder()
    b.MakeCompSolid(cs)
    for c in cells:
        b.Add(cs, c)
    ms = BRepLib_MakeSolid(cs)
    if not ms.IsDone():
        raise RuntimeError("VentForge export: could not merge plate tiles into one solid")
    return ms.Solid()


def _need_cad():
    try:
        import OCP  # noqa: F401
    except ImportError:
        raise RuntimeError('STEP/STL export, tube wrap and cutting into parts need the CAD extra: '
                           'pip install "ventforge[cad]"') from None


def plate_shape(result: Result, design: Design):
    _need_cad()
    t = design.canvas.thickness
    faces, area = _plate_faces(result)
    if not faces:
        raise ValueError("VentForge export: holes cover the whole plate, nothing to build")
    sols = [_tiled_prism(f, t) for f in faces]
    shape = sols[0] if len(sols) == 1 else _compound(sols)
    return _check(shape, "flat plate", area * t)


def to_step(result: Result, design: Design, path) -> None:
    _write(plate_shape(result, design), path)


def to_stl(result: Result, design: Design, path, tolerance: float = 0.05) -> None:
    _write(plate_shape(result, design), path, tolerance)


# --------------------------------------------------------------------------- hole tools
def _hole_regions(result: Result):
    """Merged hole regions: list of (Polygon, circle-or-None)."""
    simple, complex_ = _split(result)
    if complex_:
        simple += [(_clean(p), None) for p in _parts(shapely.union_all(complex_)) if p.area > 1e-9]
    return simple


def _bop(kind, args_, tools_):
    from OCP.collections import List_TopoDS_Shape

    a, t = List_TopoDS_Shape(), List_TopoDS_Shape()
    for x in args_:
        a.Append(x)
    for x in tools_:
        t.Append(x)
    op = kind()
    op.SetArguments(a)
    op.SetTools(t)
    op.SetRunParallel(True)
    op.Build()
    return op


def _cut(base, tools, what: str, planes=()):
    """One boolean cut of `base` by all `tools`.

    With `planes` (gp_Pln list) and a single-solid base, the base is first split into cells
    so no face collects thousands of holes (OCC face building and STEP writing are ~quadratic
    in wires per face); the cut cells are then merged back into one solid.
    """
    from OCP.BRep import BRep_Builder
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut, BRepAlgoAPI_Splitter
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace
    from OCP.BRepLib import BRepLib_MakeSolid
    from OCP.TopoDS import TopoDS_CompSolid

    tiled = bool(planes) and len(solids(base)) == 1
    arg = base
    if tiled:
        L = 1e4
        sp = _bop(BRepAlgoAPI_Splitter, [base],
                  [BRepBuilderAPI_MakeFace(pl, -L, L, -L, L).Face() for pl in planes])
        tiled = sp.IsDone() and len(solids(sp.Shape())) > 1
        if tiled:
            arg = sp.Shape()
    op = _bop(BRepAlgoAPI_Cut, [arg], tools)
    if not op.IsDone():
        raise RuntimeError(f"VentForge export: boolean cut failed ({what})")
    shape = op.Shape()
    if tiled:
        cs = TopoDS_CompSolid()
        b = BRep_Builder()
        b.MakeCompSolid(cs)
        for c in solids(shape):
            b.Add(cs, c)
        expect = volume(shape)
        ms = BRepLib_MakeSolid(cs)
        if not ms.IsDone():
            raise RuntimeError(f"VentForge export: could not merge cut cells ({what})")
        return _check(ms.Solid(), what, expect)
    return _check(shape, what)


TOOLS_PER_CELL = 50
UNTILED_MAX = 600  # up to this many holes one cut is as fast as tiling, and leaves no seams on the part


def _grid_planes(n_tools, u_range, v_range, plane_u, plane_v):
    """k-1 cut planes along each axis, k chosen for ~TOOLS_PER_CELL tools per cell."""
    if n_tools <= UNTILED_MAX:
        return []
    k = math.ceil(math.sqrt(n_tools / TOOLS_PER_CELL))
    out = []
    for i in range(1, k):
        f = (i + 0.0137) / k  # offset so planes rarely pass through grid vertices
        out.append(plane_u(u_range[0] + f * (u_range[1] - u_range[0])))
        out.append(plane_v(v_range[0] + f * (v_range[1] - v_range[0])))
    return out


def wrap_cylinder(result: Result, design: Design, path, radius=None, wall=None, height=None) -> dict:
    """Wrap the pattern around a tube (outer radius `radius`, wall inward).

    Canvas x -> arc length on the outer surface, canvas y -> z (z = y + height/2).
    Each hole is cut by a straight prism along the radial direction through its centre,
    so it is exact at the outer surface; wide holes get slightly narrower inside.
    """
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace
    from OCP.BRepPrimAPI import BRepPrimAPI_MakePrism
    from OCP.gp import gp_Ax2, gp_Dir, gp_Pln, gp_Pnt, gp_Vec

    _need_cad()
    t0 = time.perf_counter()
    c = design.canvas
    R = radius or c.width / (2 * math.pi)
    wall = wall or c.thickness
    H = height or c.height
    if wall >= R:
        raise ValueError("wall must be smaller than radius")
    ri = R - wall

    mf = BRepBuilderAPI_MakeFace(_occ_wire_circle(0, 0, R, True), True)
    mf.Add(_occ_wire_circle(0, 0, ri, False))
    tube = BRepPrimAPI_MakePrism(mf.Face(), gp_Vec(0, 0, H)).Shape()

    tools = []
    for poly, circ in _hole_regions(result):
        xc = circ[0] if circ else poly.centroid.x
        th = xc / R
        n = (math.cos(th), math.sin(th))
        tg = (-math.sin(th), math.cos(th))
        minx, _, maxx, _ = poly.bounds
        hw = max(xc - minx, maxx - xc)
        d0 = math.sqrt(max((ri - 0.5) ** 2 - hw * hw, 0.0))  # start inside the bore
        length = R + 1.0 - d0

        def P(x, y, d0=d0, n=n, tg=tg, xc=xc):
            u, z = x - xc, y + H / 2
            return gp_Pnt(n[0] * d0 + tg[0] * u, n[1] * d0 + tg[1] * u, z)

        if circ:
            ax = gp_Ax2(P(circ[0], circ[1]), gp_Dir(n[0], n[1], 0), gp_Dir(tg[0], tg[1], 0))
            f = BRepBuilderAPI_MakeFace(_occ_wire_circle(0, 0, circ[2], True, ax=ax), True)
        else:
            f = BRepBuilderAPI_MakeFace(_occ_wire_poly(_ring_xy(poly.exterior), frame=P), True)
            for ring in poly.interiors:
                f.Add(_occ_wire_poly(_ring_xy(ring), frame=P))
        tools.append(BRepPrimAPI_MakePrism(f.Face(), gp_Vec(n[0] * length, n[1] * length, 0)).Shape())
    planes = _grid_planes(
        len(tools), (0, math.pi), (0, H),
        lambda a: gp_Pln(gp_Pnt(0, 0, 0), gp_Dir(-math.sin(a), math.cos(a), 0)),
        lambda z: gp_Pln(gp_Pnt(0, 0, z), gp_Dir(0, 0, 1)))
    shape = _cut(tube, tools, "wrap_cylinder", planes) if tools else tube
    t1 = time.perf_counter()
    _write(shape, path)
    return {"holes": len(tools), "radius": R, "wall": wall, "height": H,
            "seconds": round(time.perf_counter() - t0, 3), "write_seconds": round(time.perf_counter() - t1, 3)}


def cut_into_part(result: Result, design: Design, part_path, out_path, origin=(0, 0, 0),
                  normal=(0, 0, 1), x_dir=(1, 0, 0), depth=None) -> dict:
    """Cut the pattern into an existing STEP part.

    The pattern's (x, y) plane is placed at `origin` with +z = `normal` and +x = `x_dir`;
    hole tools start 1 mm above the plane and go along -normal by `depth` (default: through
    the whole part bounding box).
    """
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace
    from OCP.BRepPrimAPI import BRepPrimAPI_MakePrism
    from OCP.gp import gp_Ax2, gp_Dir, gp_Pln, gp_Pnt, gp_Vec

    _need_cad()
    t0 = time.perf_counter()
    part = read_step(part_path)
    ax = gp_Ax2(gp_Pnt(*origin), gp_Dir(*normal), gp_Dir(*x_dir))  # re-orthogonalises x_dir
    O, N, X, Y = ax.Location(), ax.Direction(), ax.XDirection(), ax.YDirection()
    lift = 1.0
    if depth is None:
        bb = Bnd_Box()
        BRepBndLib.Add_s(part, bb)
        lo, hi = bb.CornerMin(), bb.CornerMax()
        x0, y0, z0, x1, y1, z1 = lo.X(), lo.Y(), lo.Z(), hi.X(), hi.Y(), hi.Z()
        depth = max(-((px - O.X()) * N.X() + (py - O.Y()) * N.Y() + (pz - O.Z()) * N.Z())
                    for px in (x0, x1) for py in (y0, y1) for pz in (z0, z1)) + 1.0
    depth = max(depth, 0.0)

    def P(x, y):
        return gp_Pnt(O.X() + X.X() * x + Y.X() * y + N.X() * lift,
                      O.Y() + X.Y() * x + Y.Y() * y + N.Y() * lift,
                      O.Z() + X.Z() * x + Y.Z() * y + N.Z() * lift)

    vec = gp_Vec(-N.X() * (depth + lift), -N.Y() * (depth + lift), -N.Z() * (depth + lift))
    tools = []
    for poly, circ in _hole_regions(result):
        if circ:
            cax = gp_Ax2(P(circ[0], circ[1]), N, X)
            f = BRepBuilderAPI_MakeFace(_occ_wire_circle(0, 0, circ[2], True, ax=cax), True)
        else:
            f = BRepBuilderAPI_MakeFace(_occ_wire_poly(_ring_xy(poly.exterior), frame=P), True)
            for ring in poly.interiors:
                f.Add(_occ_wire_poly(_ring_xy(ring), frame=P))
        tools.append(BRepPrimAPI_MakePrism(f.Face(), vec).Shape())
    regions = [p for p, _ in _hole_regions(result)] or [result.outline]
    minx, miny, maxx, maxy = shapely.union_all(regions).bounds

    def at(x, y):
        return gp_Pnt(O.X() + X.X() * x + Y.X() * y, O.Y() + X.Y() * x + Y.Y() * y,
                      O.Z() + X.Z() * x + Y.Z() * y)
    planes = _grid_planes(len(tools), (minx, maxx), (miny, maxy),
                          lambda u: gp_Pln(at(u, 0), X), lambda v: gp_Pln(at(0, v), Y))
    shape = _cut(part, tools, "cut_into_part", planes) if tools else part
    t1 = time.perf_counter()
    _write(shape, out_path)
    return {"holes": len(tools), "depth": depth, "seconds": round(time.perf_counter() - t0, 3),
            "write_seconds": round(time.perf_counter() - t1, 3)}


# --------------------------------------------------------------------------- dispatch
def cut_paths(result: Result, design: Design) -> Result:
    """Laser/waterjet kerf: the beam centre runs kerf/2 inside each hole and outside the outline, so the cut
    part has the designed size. Holes narrower than the kerf are dropped."""
    k = design.machining.kerf / 2
    if k <= 0:
        return result
    holes, circles = [], []
    for i, h in enumerate(result.holes):
        c = _circle(result, i)
        if c:
            if c[2] > k:
                holes.append(h)
                circles.append((c[0], c[1], c[2] - k))
            continue
        for p in _parts(h.buffer(-k, join_style="mitre")):
            holes.append(p)
            circles.append(None)
    return Result(holes=holes, outline=result.outline.buffer(k, join_style="mitre"), stats=result.stats,
                  circles=circles)


def export(result: Result, design: Design, path) -> None:
    ext = Path(path).suffix.lower()
    if ext == ".svg":
        to_svg(cut_paths(result, design), design, path)
    elif ext == ".png":
        to_png(result, design, path)
    elif ext == ".dxf":
        to_dxf(cut_paths(result, design), path)
    elif ext in (".step", ".stp"):
        to_step(result, design, path)
    elif ext == ".stl":
        to_stl(result, design, path)
    else:
        raise ValueError(f"unsupported export format: {ext!r} (use .svg .png .dxf .step .stp .stl)")
