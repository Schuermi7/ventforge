# VentForge

Design vent and perforation patterns for 3D printing, laser cutting and CNC, then export them as ready-to-use
files. Use the desktop editor, let an AI assistant such as Claude do the designing through the built-in
MCP server, or put the pattern straight onto your part in Autodesk Fusion. All of them work on the same
design file.

## Features

- **10 layouts:** grid (square, diamond, hexagon), random, path, spiral, concentric, fibonacci, crosslines,
  voronoi stone cracks, flow lines, and custom points.
- **Hole shapes:** circle, rounded rectangle, hexagon, polygon, star, or your own outline.
- **Gradients:** vary size, spacing, angle or shape across the plate. Drive them with points, lines or
  curves, with noise, or with a grayscale image.
- **Boundary:** none, circle, rounded rectangle, or a drawn outline, with margin and clipping.
- **Fan grilles:** one click for a 40–140 mm fan: holes only over the blades, 4 screw holes, and the
  share of the fan opening left open (airflow).
- **Keep-outs:** circles, rectangles or any outline that stay free of holes (bosses, logos, screws), optionally cut as holes.
  Draw them on the canvas with the Keep-out tool (K; Shift for a circle, right-click to remove).
- **Machining:** CNC tool radius (rounds inside corners, drops holes the cutter cannot reach) and laser
  kerf compensation for SVG/DXF. Set a minimum feature (about 2× nozzle for 3D printing) to flag holes
  that would close up.
- **Textures:** instead of cutting through, sink the pattern into the top (deboss) or raise it (emboss) by
  a set depth, for grips, decorative panels and labels (Plate → Making it).
- **Export:** PNG, SVG, DXF, STEP, STL. You can also wrap the pattern onto a tube or cut it into an
  existing STEP part.
- **Checks:** hole count, open area, the thinnest wall in mm (marked on the canvas), and warnings where walls
  get thinner than your minimum.
- **Airflow estimate:** pressure loss of the grille (Idelchik thin perforated plate) at 2 m/s, so two designs
  can be compared by airflow. A rough figure, not a flow simulation.
- **Autodesk Fusion add-in:** put the pattern on a face of your part as one timeline feature, with
  the face's holes and bosses as keep-outs, and a live link to the editor (see below).
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

1. Pick a design from the **Library**, or a layout under **Pattern → Layout**.
2. Drag the sliders. The preview updates as you go.
3. Pick a file type from the green **Export** button.

The panel only shows settings that change something for the current design. Pick *Star* holes and
the star settings appear; pick *Cracks* or *Slots* and the hole settings go away, because those
layouts make their own shapes. Hover over a setting for a short explanation.

| Panel | What you set there |
|-------|--------------------|
| **Plate → Size and outline** | Width, height, outline (rectangle, circle, rounded, or one you draw), edge margin, *Make it a fan grille…* |
| **Plate → Keep-out areas** | Areas without holes, for screws, labels or clips |
| **Plate → Making it** | Cut through, sunk in or raised; thickness; CNC tool radius and laser kerf; the checks for thin walls and small holes |
| **Plate → Reference image** | A photo or drawing under the plate, to trace or line up with |
| **Pattern → Layout** | How holes are placed: grid, random, along a path, spiral, rings, sunflower, crossing lines, cracks, slots, or your own points |
| **Pattern → Holes** | Hole shape and size |
| **Pattern → Variation** | Make holes bigger or smaller, closer or further apart, turned, or morphed into another shape in places. Place controls on the canvas, add randomness, or use a grayscale image |

Changing a setting in a Variation tab switches that variation on (the tab then shows a ●). Picking a
*Drawn* outline or hole shape, or the *Your points* layout, starts drawing on the canvas right away.

**Canvas controls**

| Action            | How                                                           |
|-------------------|---------------------------------------------------------------|
| Zoom              | Mouse wheel, or `+` / `-`                                     |
| Pan               | Drag empty space, middle-drag, or hold `Space` and drag       |
| Zoom to fit       | `Z`, or double-click empty space                              |
| Measure           | `R` (ruler)                                                   |
| Draw an outline   | `B`, click the points, `Enter` to finish, `Esc` to cancel     |
| Keep-out area     | `K`, drag (`Shift`: circle), right-click one to remove it     |
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
`describe_parameters` (every setting with its editor name and what it does), `set_params` (also tells
the assistant which of its settings do nothing for this design), `add_control`, `clear_controls`,
`fan_grille`, `fit_open_area` (solve a parameter for a target open area), `preview`, `export`,
`wrap_cylinder`, `cut_into_part`, `apply_to_fusion` (update the Fusion parts that use this design),
`open_in_gui`. The library is the same folder the editor uses.

## Use it in Autodesk Fusion

VentForge comes with a Fusion add-in. It puts a pattern on any flat face of your part as **one Combine
feature** on the timeline, instead of a sketch pattern with thousands of copies. The pattern stays
linked to its VentForge design, so you can keep editing it.

### Set it up (once)

1. Install VentForge with the CAD extra (or `ventforge[all]`):

   ```bash
   uv tool install "ventforge[all]"
   ```

2. Copy the add-in into Fusion:

   ```bash
   ventforge install-fusion
   ```

3. In Fusion, open *Utilities → Add-Ins*, pick **VentForge** and click *Run*. Tick *Run on Startup* so
   it loads with Fusion from now on.

Run `ventforge install-fusion` again after you update VentForge or move its environment, then *Stop*
and *Run* the add-in in Fusion. The add-in calls your VentForge installation, because Fusion's own
Python has no geometry libraries.

### Put a pattern on a part

Open *Solid → Create → VentForge pattern*.

1. **Pick a flat face** of your part.
2. **Choose a design**, or leave *Design* empty for a new one:
   - **Empty:** VentForge makes a design shaped like the face, saved in
     `~/Documents/VentForge/Fusion`. Holes in the face and anything standing on it (bosses, ribs,
     standoffs) become keep-outs, so you see them in the editor and no hole lands on them.
   - ***Choose design…*** takes any saved design, for example one from your library or the AI
     assistant's `current.vent.json`.
3. **Set a rotation** if you want one and press **OK**.

The pattern goes onto the part right away and the VentForge editor opens next to Fusion.

### Edit it live

Change the pattern in the editor and press **Ctrl+S**. Fusion rebuilds the pattern in place, in the
same timeline feature. You don't need to close the editor or run the command again. Slider moves on
their own don't update Fusion, so you can try things out without waiting for a rebuild after each one.

- **Placement:** the pattern centre sits on the face centre, with x along the world X axis (turned by
  your rotation).
- **Cut or raise:** *Plate → Making it → Pattern is* decides what happens. **Cut through** cuts
  through the body, **Sunk in** cuts the pattern in by the depth, **Raised** adds it on top. Switching between
  them while linked switches the Combine between cut and join.
- **How long the link lasts:** until you close Fusion or stop the add-in. To link again later, run
  the command on the face once more.
- The live link needs a parametric design (with a timeline). In direct modelling the pattern is
  placed once.
- Each manual save also writes a small `<design>.vent.json.saved` file next to the design. That is
  how the add-in tells a real save from the editor's automatic saves. You can delete these files.

> [!WARNING]
> **Big patterns can be very slow in Fusion.** Every hole is a real cut in the solid. A few hundred
> holes take seconds. Several thousand small holes, curved hole shapes (stars, custom outlines),
> fine gradients or emboss on a large part can keep Fusion busy for minutes on every rebuild, and
> make the timeline slow afterwards. Get the pattern right in the editor first, watch the hole count
> in its status bar, and save (Ctrl+S) only when you want to see it on the part. For very large
> grilles, test on a small face first, or bigger holes with wider spacing.

### If something goes wrong

- **An error box after a save:** the update was skipped, and your part keeps the last good pattern.
  Fix the design (for example a relief depth thicker than the plate) and save again.
- **A document briefly opens and closes on each update:** some Fusion builds cannot read STEP
  files directly, so the add-in imports through a scratch document. This is expected.
- **The command is missing from *Solid → Create*:** check that VentForge is running under
  *Utilities → Add-Ins*.

## Project layout

```
ventforge/
├── model.py         design file format: every parameter and its default
├── params.py        what each parameter is called, does, and when it matters (editor + MCP)
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
