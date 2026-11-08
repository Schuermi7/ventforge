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
- **Fan grilles:** one click for a 40–140 mm fan: holes only over the blades, 4 screw holes, and the
  share of the fan opening left open (airflow).
- **Keep-outs:** circles or rectangles that stay free of holes (bosses, logos, screws), optionally cut as holes.
  Draw them on the canvas with the Keep-out tool (K; Shift for a circle, right-click to remove).
- **Machining:** CNC tool radius (rounds inside corners, drops holes the cutter cannot reach) and laser
  kerf compensation for SVG/DXF. Set a minimum feature (about 2× nozzle for 3D printing) to flag holes
  that would close up.
- **Textures:** instead of cutting through, sink the pattern into the top (deboss) or raise it (emboss) by
  a set depth, for grips, decorative panels and labels (Canvas → Relief).
- **Export:** PNG, SVG, DXF, STEP, STL. You can also wrap the pattern onto a tube or cut it into an
  existing STEP part.
- **Checks:** hole count, open area, the thinnest wall in mm (marked on the canvas), and warnings where walls
  get thinner than your minimum.
- **Airflow estimate:** pressure loss of the grille (Idelchik thin perforated plate) at 2 m/s, so two designs
  can be compared by airflow. A rough figure, not a flow simulation.
- Undo/redo, presets, and a personal library (also from the AI assistant: `save_to_library`).

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

**Tools the server offers:** `new_design`, `open_design`, `list_presets`, `save_to_library`, `get_design`,
`describe_parameters`, `set_params`, `add_control`, `clear_controls`, `fan_grille`,
`fit_open_area` (solve a parameter for a target open area), `preview`, `export`,
`wrap_cylinder`, `cut_into_part`, `open_in_gui`.

## Use it in Autodesk Fusion

VentForge comes with a Fusion add-in. It puts a pattern on any flat face of your part as **one Combine
feature**, instead of a sketch pattern with thousands of copies that slows Fusion down.

```bash
pip install "ventforge[cad]"
ventforge install-fusion
```

In Fusion, open *Utilities → Add-Ins*, pick **VentForge** and click *Run*. Tick *Run on Startup* to keep
it. Then use *Solid → Create → VentForge pattern*:

1. Pick a flat face of your part.
2. Pick a design. The default is the current design of the AI assistant
   (`~/Documents/VentForge/current.vent.json`). *Edit in VentForge* opens it in the editor.
3. Set a rotation if you want one, and press OK.

The pattern centre goes on the face centre, with x along the world X axis. *Canvas → Relief* in the
design decides what happens: **through** cuts through the body, **deboss** cuts the pattern in by the
relief depth, and **emboss** adds it on top. The add-in runs your VentForge installation, because
Fusion's own Python has no geometry libraries. Run `ventforge install-fusion` again after you update
VentForge or move its environment.

## Project layout

```
ventforge/
├── model.py         design file format: every parameter and its default
├── pattern.py       geometry: places and shapes the holes
├── export.py        PNG, SVG, DXF, STEP and STL output, tube wrap, cut into part
├── gui.py           desktop editor
├── mcp_server.py    MCP tools for AI assistants
├── __main__.py      `ventforge` command (editor, --mcp server, tool, install-fusion)
├── fusion/          Autodesk Fusion add-in, installed by `ventforge install-fusion`
└── presets/         example designs shipped with the package
tests/               pytest suite, including a real MCP client/server run
.github/workflows/   CI on Windows, macOS and Linux; publishes to PyPI on version tags
```

## Licence

GPL-3.0-or-later, see [LICENSE](LICENSE). You may use, change and sell VentForge. Versions you distribute
must stay open source under the same licence.
