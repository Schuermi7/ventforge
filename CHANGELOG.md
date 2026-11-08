# Changelog

All notable changes to VentForge. Versions follow [semantic versioning](https://semver.org);
while we are below 1.0, a minor version (0.x.0) may change how something behaves.

## 0.2.0 — 2026-11-09

This release turns VentForge from "a pattern on a plate" into a tool that knows about the part you
are making: the fan behind it, the screws next to it, and the machine that will cut or print it.

### New: fan grilles

- **One click for a standard fan.** Choose *Fan grille…* in the toolbar (or ask the AI assistant)
  and pick 40, 50, 60, 80, 92, 120 or 140 mm. You get a square plate with rounded corners, holes
  only over the fan blades, and the four screw holes at the standard spacing. Your hole pattern
  stays as it was.
- **Fan open area.** For a fan grille, the status bar shows how much of the fan opening is open,
  which is what matters for airflow, not the open share of the whole plate.

### New: keep-outs

- **Areas that stay free of holes**, for screw bosses, logos, labels or clips. A keep-out is a
  circle or a rectangle with its own clearance.
- **Draw them on the canvas** with the new *Keep-out* tool (key **K**): drag a rectangle, hold
  **Shift** to drag a circle from its centre, right-click a keep-out to remove it. Undo works.
- A keep-out can also be **cut as a hole itself**. The fan screw holes are made this way.

### New: machining and printing

- **CNC tool radius.** Set the radius of your end mill and every hole gets the rounded inside
  corners the cutter really makes. Holes too small for the cutter are left out, and the status bar
  tells you how many.
- **Laser kerf.** Set the cut width of your laser or waterjet and SVG/DXF exports are offset by
  half of it, so the parts come out at the size you drew. The preview and 3D files keep the true size.
- **Minimum feature.** Set the smallest hole your printer or cutter can make (for 3D printing about
  twice the nozzle width). Holes below it are counted and flagged.

### New: design checks

- **Thinnest wall.** VentForge now finds the narrowest strip of plate, between two holes or between
  a hole and the plate edge, and shows it in mm. A marker on the canvas shows where it is: red when
  it is thinner than your minimum wall, yellow otherwise.
- **Airflow estimate.** A pressure-loss figure for the grille (in Pa, at 2 m/s air speed, a typical
  case-fan speed), so you can compare two designs by airflow instead of by eye. It uses a standard
  formula for thin perforated plates: a good comparison number, not a flow simulation.

### New for the AI assistant (MCP server)

- `fan_grille(size)` makes a fan grille from the current design.
- `fit_open_area(target)` solves a parameter for an open-area target, for example "make it 45 %
  open by changing the hole size". It works with any number in the design (spacing, size, …) and
  aims at the fan opening for fan grilles.
- `save_to_library(name)` saves the current design as a reusable template in your library. It
  shows up in the editor's library and in `new_design(preset=name)`.
- `describe_parameters` now also describes keep-outs and gradient controls.

### Fixes

- **Huge layouts no longer freeze the app.** A pattern that would need more than 200,000 holes
  (for example a 2 m plate at 1 mm spacing) is refused at once with a hint on what to change,
  instead of running for minutes.
- **Wrong value types are caught.** `"clip": "false"` or `"dot": 5` in a design file or MCP patch
  now gives a clear error instead of being taken as something else.
- **Your edits are safe while the assistant works.** If you save in the editor while the MCP server
  is generating, the server starts again from your version instead of overwriting it.
- **Old designs open again.** Files from 0.1.0 with values that no longer exist open with the
  default for that value, instead of failing. New edits are still checked strictly.
- Two processes saving at the same time no longer share a temporary file.
- The image cache uses about a quarter of the memory it did.

### Changed (check if you script VentForge)

- `list_presets` now returns `{"built_in": [...], "library": [...]}` instead of a plain list.

## 0.1.1 — 2026-11-08

- Fibonacci layouts keep an even hole density when they have an inner radius.
- Text settings (shapes, modes, …) are checked against one shared list in the editor, the MCP
  server and the file format.
- Images inside the design folder are saved with relative paths, so a design folder can be moved;
  a missing image gives a clear error.
- *Cut into part* and *Wrap onto cylinder* no longer show seams between tiles on big patterns.
- The MCP server checks gradient targets and kinds, and *open in GUI* explains how to install the
  editor when it is missing.
- Releases fail early when the tag does not match the package version.

## 0.1.0 — 2026-11-08

First release.

- 10 layouts: grid (square, diamond, hexagon), random, path, spiral, concentric, fibonacci,
  crosslines, voronoi, flowlines and your own points.
- Hole shapes: circle, rounded rectangle, hexagon, polygon, star or your own outline.
- Gradients for size, spacing, angle and shape, driven by points, lines, curves or an image.
- Boundaries: none, circle, rounded rectangle or a drawn outline, with margin and clipping.
- Export to PNG, SVG, DXF, STEP and STL; wrap a pattern onto a tube or cut it into a STEP part.
- Desktop editor with live preview, undo/redo, presets and a personal library.
- MCP server so an AI assistant can design with you; the editor follows its changes live.
- GPL-3.0-or-later licence.
