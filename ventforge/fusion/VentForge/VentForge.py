"""VentForge for Autodesk Fusion: Solid > Create > VentForge pattern.

Pick a planar face and a .vent.json design. VentForge (installed separately, outside Fusion's Python) writes
the pattern as solids; this add-in places them on the face (pattern centre on the face centre, x along the
world X axis projected onto the face, plus your rotation) and adds ONE Combine feature: cut for relief
"through" / "deboss", join for "emboss". One boolean instead of thousands of sketch-pattern instances.

Installed by `ventforge install-fusion`, which also writes settings.json with the command that runs VentForge.
"""
import json
import math
import os
import subprocess
import sys
import tempfile
import traceback

import adsk.core
import adsk.fusion

CMD_ID = "ventforgePattern"
PANEL = "SolidCreatePanel"
HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DESIGN = os.path.join(os.path.expanduser("~"), "Documents", "VentForge", "current.vent.json")
handlers = []  # Fusion drops handlers that are not referenced


def _ui():
    return adsk.core.Application.get().userInterface


def _command():
    with open(os.path.join(HERE, "settings.json"), encoding="utf-8") as f:
        return json.load(f)["command"]  # e.g. ["C:/.../python.exe", "-m", "ventforge"]


def _no_window():
    return {"creationflags": 0x08000000} if sys.platform == "win32" else {}  # CREATE_NO_WINDOW


def _run_tool(design, out, depth_mm):
    p = subprocess.run(_command() + ["tool", design, out, "--depth", f"{depth_mm:.4f}"],
                       capture_output=True, text=True, **_no_window())
    if p.returncode:
        raise RuntimeError("VentForge failed:\n" + (p.stderr or p.stdout).strip()[-1500:])
    lines = [ln for ln in p.stdout.splitlines() if ln.strip().startswith("{")]  # OCC prints a banner first
    return json.loads(lines[-1])


def _frame(face, angle):
    """Origin (face centre), x, y, normal in the face's component coordinates."""
    ok, n = face.evaluator.getNormalAtPoint(face.pointOnFace)
    n.normalize()
    x = adsk.core.Vector3D.create(1, 0, 0)
    if abs(x.dotProduct(n)) > 0.99:
        x = adsk.core.Vector3D.create(0, 1, 0)
    k = x.dotProduct(n)
    x = adsk.core.Vector3D.create(x.x - k * n.x, x.y - k * n.y, x.z - k * n.z)
    x.normalize()
    side = n.crossProduct(x)
    x = adsk.core.Vector3D.create(x.x * math.cos(angle) + side.x * math.sin(angle),
                                  x.y * math.cos(angle) + side.y * math.sin(angle),
                                  x.z * math.cos(angle) + side.z * math.sin(angle))
    return face.centroid, x, n.crossProduct(x), n


def insert(face, design_file, angle):
    app = adsk.core.Application.get()
    design = adsk.fusion.Design.cast(app.activeProduct)
    face = face.nativeObject or face  # work in the face's own component
    body = face.body
    comp = body.parentComponent
    bb = body.boundingBox
    depth_mm = bb.minPoint.distanceTo(bb.maxPoint) * 10 + 1  # Fusion works in cm; "through" = past the body

    out = os.path.join(tempfile.gettempdir(), "ventforge_fusion_tool.step")
    info = _run_tool(design_file, out, depth_mm)

    tbm = adsk.fusion.TemporaryBRepManager.get()
    parts = tbm.createFromFile(out)
    if parts is None or parts.count == 0:
        raise RuntimeError("Fusion could not read the pattern STEP file")
    tool = parts.item(0)
    for i in range(1, parts.count):
        tbm.booleanOperation(tool, parts.item(i), adsk.fusion.BooleanTypes.UnionBooleanType)

    # the STEP is in mm; check what the import made of it before placing it
    tb = tool.boundingBox
    size_mm = max(tb.maxPoint.x - tb.minPoint.x, tb.maxPoint.y - tb.minPoint.y) * 10
    if size_mm > 0 and abs(size_mm / info["size_mm"] - 1) > 0.01:
        s = adsk.core.Matrix3D.create()
        k = info["size_mm"] / size_mm
        for i in range(3):
            s.setCell(i, i, k)
        tbm.transform(tool, s)

    origin, x, y, n = _frame(face, angle)
    m = adsk.core.Matrix3D.create()
    m.setWithCoordinateSystem(origin, x, y, n)
    tbm.transform(tool, m)

    if design.designType == adsk.fusion.DesignTypes.ParametricDesignType:
        base = comp.features.baseFeatures.add()
        base.startEdit()
        comp.bRepBodies.add(tool, base)
        base.finishEdit()
        base.name = "VentForge pattern"
        tool_body = base.bodies.item(0)
    else:
        tool_body = comp.bRepBodies.add(tool)

    tools = adsk.core.ObjectCollection.create()
    tools.add(tool_body)
    ci = comp.features.combineFeatures.createInput(body, tools)
    ci.operation = (adsk.fusion.FeatureOperations.JoinFeatureOperation if info["operation"] == "join"
                    else adsk.fusion.FeatureOperations.CutFeatureOperation)
    ci.isKeepToolBodies = False
    comp.features.combineFeatures.add(ci)
    return info


class Created(adsk.core.CommandCreatedEventHandler):
    def notify(self, args):
        try:
            cmd = args.command
            inp = cmd.commandInputs
            sel = inp.addSelectionInput("face", "Face", "Pick the planar face for the pattern")
            sel.addSelectionFilter("PlanarFaces")
            sel.setSelectionLimits(1, 1)
            inp.addStringValueInput("file", "Design", DEFAULT_DESIGN)
            inp.addBoolValueInput("browse", "Choose design…", False, "", False)
            inp.addBoolValueInput("edit", "Edit in VentForge", False, "", False)
            inp.addValueInput("angle", "Rotation", "deg", adsk.core.ValueInput.createByReal(0))
            inp.addTextBoxCommandInput("help", "", "Relief <b>through</b> / <b>deboss</b> cuts, <b>emboss</b> "
                                       "joins (Canvas → Relief in VentForge). Pattern centre goes on the face centre.",
                                       3, True)
            for ev, h in ((cmd.inputChanged, Changed()), (cmd.execute, Execute())):
                ev.add(h)
                handlers.append(h)
        except Exception:
            _ui().messageBox("VentForge:\n" + traceback.format_exc())


class Changed(adsk.core.InputChangedEventHandler):
    def notify(self, args):
        try:
            inp = args.inputs
            f = inp.itemById("file")
            if args.input.id == "browse":
                dlg = _ui().createFileDialog()
                dlg.title = "VentForge design"
                dlg.filter = "VentForge design (*.vent.json);;All files (*.*)"
                if dlg.showOpen() == adsk.core.DialogResults.DialogOK:
                    f.value = dlg.filename
            elif args.input.id == "edit":
                subprocess.Popen(_command() + [f.value], **_no_window())
        except Exception:
            _ui().messageBox("VentForge:\n" + traceback.format_exc())


class Execute(adsk.core.CommandEventHandler):
    def notify(self, args):
        try:
            inp = args.command.commandInputs
            path = inp.itemById("file").value
            if not os.path.isfile(path):
                _ui().messageBox(f"No VentForge design at\n{path}")
                return
            insert(inp.itemById("face").selection(0).entity, path, inp.itemById("angle").value)
        except Exception:
            _ui().messageBox("VentForge:\n" + traceback.format_exc())


def run(context):
    try:
        ui = _ui()
        d = ui.commandDefinitions.itemById(CMD_ID) or ui.commandDefinitions.addButtonDefinition(
            CMD_ID, "VentForge pattern", "Cut, deboss or emboss a VentForge pattern on a face")
        h = Created()
        d.commandCreated.add(h)
        handlers.append(h)
        panel = ui.allToolbarPanels.itemById(PANEL)
        if panel and not panel.controls.itemById(CMD_ID):
            panel.controls.addCommand(d)
    except Exception:
        _ui().messageBox("VentForge add-in failed to start:\n" + traceback.format_exc())


def stop(context):
    ui = _ui()
    panel = ui.allToolbarPanels.itemById(PANEL)
    c = panel and panel.controls.itemById(CMD_ID)
    if c:
        c.deleteMe()
    d = ui.commandDefinitions.itemById(CMD_ID)
    if d:
        d.deleteMe()
