# VentForge

Design vent and perforation patterns for 3D printing, laser cutting and CNC, then export them as ready-to-use
files. Use the desktop editor, or let an AI assistant such as Claude do the designing through the built-in
MCP server. Both work on the same design file.

## Features

- **10 layouts:** grid (square, diamond, hexagon), random, path, spiral, concentric, fibonacci, crosslines,
  voronoi stone cracks, flow lines, and custom points.
- **Hole shapes:** circle, rounded rectangle, hexagon, polygon, star, or your own outline.
- **Gradients:** vary size, spacing, angle or shape across the plate. Drive them with points, lines or
  curves, with noise, or with a grayscale image.
- **Boundary:** none, circle, rounded rectangle, or a drawn outline, with margin and clipping.
- **Export:** PNG, SVG, DXF, STEP, STL. You can also wrap the pattern onto a tube or cut it into an
  existing STEP part.
- **Checks:** hole count, open area, and warnings where walls get thinner than your minimum.
- Undo/redo, presets, and a personal library.

## Install

You need Python 3.11 or newer. Install the full app with [uv](https://docs.astral.sh/uv/) (recommended)
or pipx:

```bash
uv tool install "ventforge[all]"
```

```bash
pipx install "ventforge[all]"
```

Pick a smaller install if you don't need everything:

| You want                                                  | Install                       |
|-----------------------------------------------------------|-------------------------------|
| Everything                                                | `ventforge[all]`              |
| Desktop editor                                            | `ventforge[gui]`              |
| STEP/STL export, tube wrap, cut into part (OpenCascade)   | `ventforge[cad]`              |
| Only the MCP server with SVG, DXF and PNG export          | `ventforge`                   |

## Use the desktop editor

```bash
ventforge
```

To open a saved design, pass its file: `ventforge my_vent.vent.json`.

1. Pick a preset or a layout mode in the side panel.
2. Drag the sliders. The preview updates as you go.
3. Pick a file type from the **Export** menu.

**Canvas controls**

| Action            | How                                                           |
|-------------------|---------------------------------------------------------------|
| Zoom              | Mouse wheel, or `+` / `-`                                     |
| Pan               | Drag empty space, middle-drag, or hold `Space` and drag       |
| Zoom to fit       | `Z`, or double-click empty space                              |
| Measure           | `R` (ruler)                                                   |
| Draw an outline   | `B`, click the points, `Enter` to finish, `Esc` to cancel     |
| Undo / redo       | `Ctrl+Z` / `Ctrl+Y`                                           |

Your design saves itself shortly after each change.

## Use it with an AI assistant (MCP)

You don't need to install anything first, because uv downloads VentForge on demand.

**Claude Code:**

```bash
claude mcp add ventforge -- uvx --from "ventforge[all]" ventforge --mcp
```

**Claude Desktop:** add this to `claude_desktop_config.json`, then restart the app:

```json
{
  "mcpServers": {
    "ventforge": {
      "command": "uvx",
      "args": ["--from", "ventforge[all]", "ventforge", "--mcp"]
    }
  }
}
```

Then ask, for example: *"Make a 120 × 80 mm hexagon vent with 4 mm holes that get smaller toward the
edges, and export it as STEP."*

The assistant works on `~/Documents/VentForge/current.vent.json`. If you open that file in the editor
(or ask the assistant to "open it in the GUI"), you can watch the design change live.

**Tools the server offers:** `new_design`, `open_design`, `list_presets`, `get_design`,
`describe_parameters`, `set_params`, `add_control`, `clear_controls`, `preview`, `export`,
`wrap_cylinder`, `cut_into_part`, `open_in_gui`.

## Project layout

```
ventforge/
├── model.py         design file format: every parameter and its default
├── pattern.py       geometry: places and shapes the holes
├── export.py        PNG, SVG, DXF, STEP and STL output, tube wrap, cut into part
├── gui.py           desktop editor
├── mcp_server.py    MCP tools for AI assistants
├── __main__.py      `ventforge` command (editor, or MCP server with --mcp)
└── presets/         example designs shipped with the package
tests/               pytest suite, including a real MCP client/server run
.github/workflows/   CI on Windows, macOS and Linux; publishes to PyPI on version tags
```

## Licence

GPL-3.0-or-later, see [LICENSE](LICENSE). You may use, change and sell VentForge. Versions you distribute
must stay open source under the same licence.
