"""MCP server for VentForge. Works on one "current" design file; the GUI watches that file,
so every change made here shows up live in an open editor window."""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from dataclasses import fields, is_dataclass
from pathlib import Path

from mcp.server.mcpserver import Image, MCPServer

from . import model
from .model import Design

PRESETS = Path(__file__).resolve().parent / "presets"
HOME = Path.home() / "Documents" / "VentForge"

mcp = MCPServer("ventforge", instructions=(
    "Design vent hole patterns for 3D parts. Units mm, canvas centred at origin, y up, angles in degrees. "
    "Workflow: new_design (or open_design) -> describe_parameters -> set_params / add_control -> preview "
    "(look at the image and stats: open_area_ratio, min_wall_violations, thinnest_wall, pressure_drop_pa) -> iterate -> export. "
    "The current design is a .vent.json file; call open_in_gui to let the user watch it live."))

_current: Path | None = None


def _path() -> Path:
    global _current
    if _current is None:
        HOME.mkdir(parents=True, exist_ok=True)
        _current = HOME / "current.vent.json"
        if not _current.exists():
            Design().save(_current)
    return _current


def _load() -> Design:
    return Design.load(_path())


def _generate(d: Design):
    from .pattern import generate
    return generate(d)


def _update(change):
    """Load, change, generate, save. If the editor saved the file meanwhile (generating can take seconds),
    start again from its version so the user's edit is not overwritten.
    shortcut: the check-then-save window is microseconds, not zero; a file lock would close it."""
    p = _path()
    for _ in range(3):
        stamp = p.stat().st_mtime_ns
        d = change(_load())
        r = _generate(d)  # before saving, so a bad change never lands in the file
        if p.stat().st_mtime_ns == stamp:
            d.save(p)
            return d, r
    raise RuntimeError("the design file keeps changing (is the editor saving?); try again")


def _stats(r) -> dict:
    return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in r.stats.items()}


@mcp.tool()
def new_design(path: str = "", preset: str = "", name: str = "") -> dict:
    """Start a design (default file ~/Documents/VentForge/current.vent.json), optionally from a preset name
    (see list_presets). Returns the file path and stats."""
    global _current
    d = Design.load(_preset(preset)) if preset else Design()
    if name:
        d.name = name
    _current = Path(path).expanduser().resolve() if path else _path()
    _current.parent.mkdir(parents=True, exist_ok=True)
    d.save(_current)
    return {"path": str(_current), "stats": _stats(_generate(d))}


@mcp.tool()
def open_design(path: str) -> dict:
    """Make an existing .vent.json file the current design."""
    global _current
    p = Path(path).expanduser().resolve()
    d = Design.load(p)
    _current = p
    return {"path": str(p), "name": d.name, "stats": _stats(_generate(d))}


def _preset(name: str) -> Path:
    for folder in (PRESETS, HOME):  # built-ins first, then the user library (the editor's default folder)
        if (f := folder / f"{_safe(name)}.vent.json").exists():
            return f
    raise ValueError(f"no preset or library design named {name!r}; see list_presets")


def _safe(name: str) -> str:
    if not name or Path(name).name != name or name in (".", ".."):
        raise ValueError(f"a library name is a plain file name without folders; got {name!r}")
    return name


@mcp.tool()
def list_presets() -> dict:
    """Names usable with new_design(preset=...): built-in presets, and your library (save_to_library)."""
    names = lambda f: sorted(p.name.removesuffix(".vent.json") for p in f.glob("*.vent.json"))
    return {"built_in": names(PRESETS), "library": [n for n in names(HOME) if n != "current"]}


@mcp.tool()
def save_to_library(name: str) -> dict:
    """Save the current design (pattern, fan grille, keep-outs, machining) as a reusable library template,
    e.g. "92mm grille case X". It shows in the editor's library and in new_design(preset=name)."""
    out = HOME / f"{_safe(name)}.vent.json"
    if out == _path():
        raise ValueError("that is the current working file; pick another name")
    HOME.mkdir(parents=True, exist_ok=True)
    d = _load()
    if d.name == "Untitled":
        d.name = name
    d.save(out)
    return {"path": str(out)}


@mcp.tool()
def get_design() -> dict:
    """The full current design as a dict (same shape as the .vent.json file)."""
    return {"path": str(_path()), "design": _load().to_dict()}


def _schema(obj) -> dict:
    return {f.name: _schema(getattr(obj, f.name)) if is_dataclass(getattr(obj, f.name))
            else f"{type(getattr(obj, f.name)).__name__} = {getattr(obj, f.name)!r}" for f in fields(obj)}


@mcp.tool()
def describe_parameters() -> dict:
    """Every parameter with its type and default, plus the allowed enum values. Parameter meanings are
    documented in ventforge/model.py; pattern.<mode> holds the settings of each layout mode."""
    return {"enums": model.CHOICES,  # keys: full path, or field name anywhere
            "gradient_semantics": "size/spacing are multipliers (edge 1 = neutral), angle adds degrees, "
                                  "shape morphs 0..1 towards target_shape. A control has `value` at its "
                                  "location blending to the gradient's `edge` value at distance `radius`.",
            "list_items": {"keepouts": _schema(model.Keepout()), "controls": _schema(model.Control())},
            "defaults": _schema(Design())}


@mcp.tool()
def set_params(patch: dict) -> dict:
    """Deep-merge a partial design, e.g. {"dot": {"shape": "hexagon", "diameter": 3},
    "pattern": {"mode": "grid", "grid": {"spacing_x": 4.5}}}. Lists (points, controls) are replaced whole.
    Saves the file (live-updates the GUI) and returns stats."""
    _, r = _update(lambda d: d.patched(patch).resolve_images(_path().parent))
    return {"stats": _stats(r)}


@mcp.tool()
def add_control(target: str, kind: str = "point", points: list[list[float]] | None = None,
                value: float = 0.2, radius: float = 50.0, enable: bool = True) -> dict:
    """Add a gradient control to target size|spacing|angle|shape. kind point (1 point), line (2), curve (>=3)."""
    if target not in model.GRADS:
        raise ValueError(f"target must be one of {', '.join(model.GRADS)}; got {target!r}")
    if kind not in model.CHOICES["kind"]:
        raise ValueError(f"kind must be point, line or curve; got {kind!r}")
    def change(d):
        g = getattr(d.gradients, target)
        g.controls.append(model.Control(kind=kind, points=points or [[0.0, 0.0]], value=value, radius=radius))
        g.enabled = g.enabled or enable
        return d

    d, r = _update(change)
    return {"controls": len(getattr(d.gradients, target).controls), "stats": _stats(r)}


@mcp.tool()
def clear_controls(target: str) -> dict:
    """Remove all controls of gradient target size|spacing|angle|shape."""
    if target not in model.GRADS:
        raise ValueError(f"target must be one of {', '.join(model.GRADS)}; got {target!r}")
    _, r = _update(lambda d: getattr(d.gradients, target).controls.clear() or d)
    return {"stats": _stats(r)}


@mcp.tool()
def fan_grille(size: int) -> dict:
    """Turn the current design into a grille for a standard fan (40, 50, 60, 80, 92, 120 or 140 mm): square
    plate with rounded corners, holes only over the blades (boundary.vent_diameter), 4 screw holes as
    keep-outs. The hole pattern stays. stats.fan_open_ratio = open share of the fan opening (airflow)."""
    _, r = _update(lambda d: model.fan_grille(d, size))
    return {"stats": _stats(r)}


def _nested(param: str, v) -> dict:
    out: dict = {}
    cur = out
    *head, last = param.split(".")
    for k in head:
        cur = cur.setdefault(k, {})
    cur[last] = v
    return out


@mcp.tool()
def fit_open_area(target: float, param: str = "dot.diameter", low: float | None = None,
                  high: float | None = None) -> dict:
    """Solve one numeric parameter so the design reaches open_area_ratio `target` (0..1, or fan_open_ratio for
    a fan grille), e.g. param "pattern.grid.spacing_x". Searches low..high (default: a quarter to 4x the
    current value), saves the result and returns it with stats; check min_wall_violations afterwards."""
    if not 0 < target < 1:
        raise ValueError("target is a ratio between 0 and 1, e.g. 0.45")
    d0 = _load()
    v0 = _get(d0, param)
    lo, hi = low if low is not None else v0 / 4, high if high is not None else v0 * 4
    key = "fan_open_ratio" if d0.boundary.vent_diameter > 0 else "open_area_ratio"

    def err(v):
        return _generate(d0.patched(_nested(param, v))).stats.get(key, 0.0) - target

    e_lo, e_hi = err(lo), err(hi)
    if e_lo * e_hi > 0:
        raise ValueError(f"{key} goes from {e_lo + target:.3f} to {e_hi + target:.3f} over {param} {lo:g}..{hi:g}; "
                         f"{target} is outside, widen low/high or change another parameter")
    for _ in range(24):  # bisection: open area changes monotonically with size or spacing
        mid = (lo + hi) / 2
        e = err(mid)
        if (e < 0) == (e_lo < 0):
            lo, e_lo = mid, e
        else:
            hi = mid
    v = round((lo + hi) / 2, 3)
    _, r = _update(lambda d: d.patched(_nested(param, v)))
    return {param: v, "stats": _stats(r)}


def _get(d: Design, param: str) -> float:
    obj = d
    for k in param.split("."):
        if not hasattr(obj, k):
            raise ValueError(f"unknown parameter: {param}")
        obj = getattr(obj, k)
    if isinstance(obj, bool) or not isinstance(obj, (int, float)):
        raise ValueError(f"{param} is not a number")
    return float(obj)


@mcp.tool()
def preview(px: int = 900) -> list:
    """Render the current design as a PNG (holes on the plate outline) plus stats. Look at it before exporting."""
    from .export import to_png
    d = _load()
    r = _generate(d)
    return [Image(data=to_png(r, d, px=px, transparent=False), format="png"), {"stats": _stats(r)}]


@mcp.tool()
def export(path: str) -> dict:
    """Export the current design; format from the extension: .svg .png .dxf .step/.stp .stl (3D plate of
    canvas.thickness)."""
    from .export import export as do_export
    d = _load()
    r = _generate(d)
    out = Path(path).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    do_export(r, d, str(out))
    return {"path": str(out), "bytes": out.stat().st_size, "stats": _stats(r)}


@mcp.tool()
def wrap_cylinder(path: str, radius: float | None = None, wall: float | None = None,
                  height: float | None = None) -> dict:
    """Wrap the pattern around a tube (canvas width = arc length) and cut it through the wall.
    Defaults: radius = width/2π (wraps once), wall = thickness, height = canvas height. Writes .step or .stl."""
    from .export import wrap_cylinder as wrap
    d = _load()
    out = Path(path).expanduser().resolve()
    wrap(_generate(d), d, str(out), radius=radius, wall=wall, height=height)
    return {"path": str(out), "bytes": out.stat().st_size}


@mcp.tool()
def cut_into_part(part_path: str, out_path: str, origin: list[float] = [0, 0, 0],
                  normal: list[float] = [0, 0, 1], x_dir: list[float] = [1, 0, 0],
                  depth: float | None = None) -> dict:
    """Cut the vent pattern into an existing STEP part. The pattern plane sits at `origin` facing `normal`
    (holes are cut along -normal), canvas x along `x_dir`. depth None = through the whole part."""
    from .export import cut_into_part as cut
    d = _load()
    out = Path(out_path).expanduser().resolve()
    cut(_generate(d), d, str(Path(part_path).expanduser().resolve()), str(out),
        origin=tuple(origin), normal=tuple(normal), x_dir=tuple(x_dir), depth=depth)
    return {"path": str(out), "bytes": out.stat().st_size}


@mcp.tool()
def open_in_gui() -> str:
    """Open the current design in the VentForge desktop editor (it live-reloads when this server edits it)."""
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    if not getattr(sys, "frozen", False) and importlib.util.find_spec("PySide6") is None:
        return 'The editor is not installed. Run: pip install "ventforge[gui]"'
    if getattr(sys, "frozen", False):  # bundled app: the executable itself is the editor
        cmd = [sys.executable, str(_path())]
    else:
        exe = Path(sys.executable)
        gui_exe = exe.with_name("pythonw.exe") if exe.with_name("pythonw.exe").exists() else exe
        cmd = [str(gui_exe), "-m", "ventforge", str(_path())]
    subprocess.Popen(cmd, creationflags=flags)
    return f"opened {_path()}"


def main():
    mcp.run()


if __name__ == "__main__":
    main()
