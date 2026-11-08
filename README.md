# VentForge

Parametric vent-pattern designer: native desktop editor (PySide6) + MCP server, sharing one geometry core
(shapely) and OpenCascade exports.

## Install

```
uv tool install "ventforge[all]"       # or: pipx install "ventforge[all]"
```

Extras: core (no extra) = MCP server + SVG/DXF/PNG export; `gui` = desktop editor; `cad` = STEP/STL export,
tube wrap and cut into a STEP part (OpenCascade); `all` = both.

## Run

```
ventforge [design.vent.json]     # desktop editor
ventforge --mcp                  # MCP server (stdio); `ventforge-mcp` does the same
```

Register with Claude Code (without installing first, uv fetches it on demand):

```
claude mcp add ventforge -- uvx --from "ventforge[all]" ventforge --mcp
```

For Claude Desktop, add the same command to `claude_desktop_config.json` under `mcpServers`.

The MCP server edits a `.vent.json` file (default `~/Documents/VentForge/current.vent.json`); an editor window
with that file open reloads live, so you can watch the AI design. `open_in_gui` opens it.

## Features

- 10 layout modes: grid (square/diamond/hexagon), random, path, spiral, concentric, fibonacci, crosslines,
  voronoi stone cracks, flow lines, custom points (AI-written arrangements).
- Dot shapes: circle, rounded rectangle, hexagon, polygon, star, custom outline.
- Gradients for size / spacing / angle / shape-morph, driven by point, line and curve controls, noise,
  or a grayscale image.
- Boundary: none, circle, rounded rectangle, custom drawn outline; margin, clip.
- Exports: PNG, SVG, DXF, STEP, STL; wrap onto a cylinder; cut into an existing STEP part.
- Stats: dot count, open-area ratio, min-wall violations. Undo/redo, presets, user library.

## Layout

`ventforge/model.py` design schema (all parameters) · `pattern.py` geometry · `export.py` file output ·
`gui.py` editor · `mcp_server.py` MCP tools · `presets/` (shipped in the package) · `tests/` (`pytest`, 109 tests, including the MCP server over real stdio;
GUI test needs `QT_QPA_PLATFORM=offscreen`). Development: `pip install -e ".[dev]"`.
CI (`.github/workflows/ci.yml`) tests Windows/macOS/Linux and publishes to PyPI on a `v*` tag.

## Licence

GPL-3.0-or-later, see `LICENSE`. You may use, change and sell VentForge; versions you distribute must stay open source under the same licence.
