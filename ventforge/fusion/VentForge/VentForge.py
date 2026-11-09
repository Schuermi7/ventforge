"""VentForge for Autodesk Fusion: Solid > Create > VentForge pattern.

Pick a planar face and press OK. Without a design, the add-in starts a new one shaped like the face. VentForge
(installed separately, outside Fusion's Python) writes the pattern as solids; the add-in places them on the face
(design origin on the face centre, x along the world X axis projected onto the face, plus your rotation) and adds
ONE Combine feature: cut for relief "through" / "deboss", join for "emboss". Then the VentForge editor opens, and
every save there (Ctrl+S) updates the pattern in Fusion: a live link, until Fusion or the add-in stops.

Installed by `ventforge install-fusion`, which also writes settings.json with the command that runs VentForge.
"""
import json
import math
import os
import subprocess
import sys
import tempfile
import threading
import traceback

import adsk.core
import adsk.fusion

CMD_ID = "ventforgePattern"
PANEL = "SolidCreatePanel"
HERE = os.path.dirname(os.path.abspath(__file__))
DESIGNS = os.path.join(os.path.expanduser("~"), "Documents", "VentForge", "Fusion")
STATE = os.path.join(HERE, "last.json")
EVENT_ID = "ventforgeDesignChanged"
handlers = []  # Fusion drops handlers that are not referenced
# shortcut: links live in memory only, so they end when Fusion restarts; store them as attributes to keep them
links = {}  # design path -> {"doc", "base", "combine" (entity tokens), "matrix", "depth", "op", "mtime"}
stop_watch = threading.Event()


def _ui():
    return adsk.core.Application.get().userInterface


def _command():
    with open(os.path.join(HERE, "settings.json"), encoding="utf-8") as f:
        return json.load(f)["command"]  # e.g. ["C:/.../python.exe", "-m", "ventforge"]


def _last_design():
    try:
        with open(STATE, encoding="utf-8") as f:
            p = json.load(f)["design"]
        return p if os.path.isfile(p) else ""
    except (OSError, ValueError, KeyError):
        return ""


def _remember(path):
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump({"design": path}, f)


def _no_window():
    return {"creationflags": 0x08000000} if sys.platform == "win32" else {}  # CREATE_NO_WINDOW


def _open_editor(path):
    subprocess.Popen(_command() + [path], **_no_window())


def _run_tool(design, out, depth_mm):
    p = subprocess.run(_command() + ["tool", design, out, "--depth", f"{depth_mm:.4f}"],
                       capture_output=True, text=True, **_no_window())
    if p.returncode:
        raise RuntimeError("VentForge failed:\n" + (p.stderr or p.stdout).strip()[-1500:])
    lines = [ln for ln in p.stdout.splitlines() if ln.strip().startswith("{")]  # OCC prints a banner first
    return json.loads(lines[-1])


def _native(face):
    return face.nativeObject or face  # work in the face's own component


def _frame(face, angle):
    """Origin (face centre), x, y, normal in the face's component coordinates (cm)."""
    ok, n = face.evaluator.getNormalAtPoint(face.pointOnFace)
    n.normalize()
    x = adsk.core.Vector3D.create(1, 0, 0)
    if abs(x.dotProduct(n)) > 0.99:
        x = adsk.core.Vector3D.create(0, 1, 0)
    k = x.dotProduct(n)
    x = adsk.core.Vector3D.create(x.x - k * n.x, x.y - k * n.y, x.z - k * n.z)
    x.normalize()
    side = n.crossProduct(x)
    c, s = math.cos(angle), math.sin(angle)
    x = adsk.core.Vector3D.create(x.x * c + side.x * s, x.y * c + side.y * s, x.z * c + side.z * s)
    return face.centroid, x, n.crossProduct(x), n


def _loop_mm(loop, o, x, y):
    """A face loop as [[x, y], ...] in mm in the placement frame (origin o, axes x, y)."""
    pts = []
    for ce in loop.coEdges:
        ev = ce.edge.evaluator
        ok, t0, t1 = ev.getParameterExtents()
        steps = 1 if ce.edge.geometry.curveType == adsk.core.Curve3DTypes.Line3DCurveType else 32
        ok, ps = ev.getPointsAtParameters([t0 + (t1 - t0) * i / steps for i in range(steps + 1)])
        ps = list(ps)[::-1] if ce.isOpposedToEdge else list(ps)
        for p in ps[:-1]:  # the last point starts the next edge
            v = o.vectorTo(p)
            pts.append([round(v.dotProduct(x) * 10, 4), round(v.dotProduct(y) * 10, 4)])
    return pts


def _keepout(loop, o, x, y):
    """What sits inside the face (a hole, or a boss / rib standing on it) as a VentForge keep-out."""
    edges = [ce.edge for ce in loop.coEdges]
    if len(edges) == 1 and edges[0].geometry.curveType == adsk.core.Curve3DTypes.Circle3DCurveType:
        c = edges[0].geometry
        v = o.vectorTo(c.center)
        return {"shape": "circle", "x": round(v.dotProduct(x) * 10, 4), "y": round(v.dotProduct(y) * 10, 4),
                "width": round(c.radius * 20, 4)}
    pts = _loop_mm(loop, o, x, y)
    cx = (min(p[0] for p in pts) + max(p[0] for p in pts)) / 2
    cy = (min(p[1] for p in pts) + max(p[1] for p in pts)) / 2
    return {"shape": "polygon", "x": round(cx, 4), "y": round(cy, 4),
            "points": [[round(px - cx, 4), round(py - cy, 4)] for px, py in pts]}


def _face_shape(face, angle):
    """The face's outer edge (VentForge boundary points) and what sits inside it (keep-outs)."""
    o, x, y, _ = _frame(face, angle)
    outline = next(_loop_mm(lp, o, x, y) for lp in face.loops if lp.isOuter)
    return outline, [_keepout(lp, o, x, y) for lp in face.loops if not lp.isOuter]


def new_design(face, angle):
    """A new VentForge design shaped like the face, opened in the editor. Holes in the face and anything standing
    on it become keep-outs, so the pattern avoids them and the editor shows them. Returns its path."""
    pts, keepouts = _face_shape(_native(face), angle)
    w = 2 * max(abs(p[0]) for p in pts)
    h = 2 * max(abs(p[1]) for p in pts)
    doc = adsk.core.Application.get().activeDocument.name
    safe = "".join(ch if ch.isalnum() or ch in " -_" else "_" for ch in doc).strip() or "part"
    os.makedirs(DESIGNS, exist_ok=True)
    i = 1
    while os.path.exists(path := os.path.join(DESIGNS, f"{safe} {i}.vent.json")):
        i += 1
    with open(path, "w", encoding="utf-8") as f:  # VentForge fills in every other setting with its default
        json.dump({"name": f"{doc} face {i}", "canvas": {"width": round(w, 3), "height": round(h, 3)},
                   "boundary": {"type": "custom", "points": pts}, "keepouts": keepouts}, f, indent=2)
    _remember(path)
    return path


def _load_tool(path):
    """The STEP file as one temporary body. Fusion's quick loader is tried first; some builds reject STEP
    there, so the fallback imports into a scratch document, copies the bodies and closes it."""
    app = adsk.core.Application.get()
    tbm = adsk.fusion.TemporaryBRepManager.get()
    try:
        parts = list(tbm.createFromFile(path))
    except Exception:
        parts = []
    if not parts:
        here = app.activeDocument
        scratch = app.importManager.importToNewDocument(app.importManager.createSTEPImportOptions(path))
        try:
            des = adsk.fusion.Design.cast(scratch.products.itemByProductType("DesignProductType"))
            parts = [tbm.copy(b) for c in des.allComponents for b in c.bRepBodies]
        finally:
            scratch.close(False)
            here.activate()
    if not parts:
        raise RuntimeError("Fusion could not read the pattern STEP file")
    tool = parts[0]
    for p in parts[1:]:
        tbm.booleanOperation(tool, p, adsk.fusion.BooleanTypes.UnionBooleanType)
    return tool


def _tool_body(design_file, depth_mm, m):
    """The design's pattern as one temporary body, moved onto the face by matrix m."""
    out = os.path.join(tempfile.gettempdir(), "ventforge_fusion_tool.step")
    info = _run_tool(design_file, out, depth_mm)
    tool = _load_tool(out)
    tbm = adsk.fusion.TemporaryBRepManager.get()
    tb = tool.boundingBox  # the STEP is in mm: check what the import made of it before placing it
    size_mm = max(tb.maxPoint.x - tb.minPoint.x, tb.maxPoint.y - tb.minPoint.y) * 10
    if size_mm > 0 and abs(size_mm / info["size_mm"] - 1) > 0.01:
        s = adsk.core.Matrix3D.create()
        for i in range(3):
            s.setCell(i, i, info["size_mm"] / size_mm)
        tbm.transform(tool, s)
    tbm.transform(tool, m)
    return tool, info


def _op(info):
    return (adsk.fusion.FeatureOperations.JoinFeatureOperation if info["operation"] == "join"
            else adsk.fusion.FeatureOperations.CutFeatureOperation)


def insert(face, design_file, angle):
    """Place the pattern on the face as one Combine; in a parametric design it stays linked to the file."""
    app = adsk.core.Application.get()
    doc = app.activeDocument
    design = adsk.fusion.Design.cast(app.activeProduct)
    face = _native(face)
    token = face.entityToken  # the scratch import switches documents; find the face again afterwards
    bb = face.body.boundingBox
    depth_mm = bb.minPoint.distanceTo(bb.maxPoint) * 10 + 1  # Fusion works in cm; "through" = past the body
    m = adsk.core.Matrix3D.create()
    m.setWithCoordinateSystem(*_frame(face, angle))  # kept for updates: the cut moves the face's centre

    mtime = _saved(design_file)
    tool, info = _tool_body(design_file, depth_mm, m)
    body = design.findEntityByToken(token)[0].body
    comp = body.parentComponent

    parametric = design.designType == adsk.fusion.DesignTypes.ParametricDesignType
    if parametric:
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
    ci.operation = _op(info)
    ci.isKeepToolBodies = False
    combine = comp.features.combineFeatures.add(ci)
    _remember(design_file)
    if parametric:  # direct designs have no base feature to update
        links[_key(design_file)] = {"doc": doc, "base": base.entityToken, "combine": combine.entityToken,
                                    "matrix": m.asArray(), "depth": depth_mm, "op": info["operation"],
                                    "mtime": mtime}
    return info


def _key(path):
    return os.path.normcase(os.path.abspath(path))


def update(path):
    """Replace a linked pattern with the design file's current state."""
    ln = links.get(path)
    if not ln:
        return
    if not ln["doc"].isValid:
        links.pop(path)  # document closed
        return
    if adsk.core.Application.get().activeDocument != ln["doc"]:
        return  # retried until the user is back in that document
    ln["mtime"] = _saved(path)
    m = adsk.core.Matrix3D.create()
    m.setWithArray(ln["matrix"])
    tool, info = _tool_body(path, ln["depth"], m)
    ln["doc"].activate()
    design = adsk.fusion.Design.cast(ln["doc"].products.itemByProductType("DesignProductType"))
    found = design.findEntityByToken(ln["base"])
    if not found:
        links.pop(path)  # the user deleted the pattern
        return
    base = adsk.fusion.BaseFeature.cast(found[0])
    base.startEdit()
    try:
        base.updateBody(base.bodies.item(0), tool)
    finally:
        base.finishEdit()
    if info["operation"] != ln["op"]:  # relief switched between cut and emboss
        found = design.findEntityByToken(ln["combine"])
        if not found:
            raise RuntimeError("VentForge: the pattern's Combine feature is gone; run the command again")
        combine = adsk.fusion.CombineFeature.cast(found[0])
        combine.timelineObject.rollTo(False)  # a feature in the history only takes edits with the marker on it
        try:
            combine.operation = _op(info)
        finally:
            design.timeline.moveToEnd()
        if combine.operation != _op(info):
            raise RuntimeError("VentForge: Fusion did not switch the Combine between cut and join")
        ln["op"] = info["operation"]


def _watch():
    """Poll the linked designs; after a manual save in the editor, update it on Fusion's main thread."""
    app = adsk.core.Application.get()
    while not stop_watch.wait(0.5):
        for path, ln in list(links.items()):
            if _saved(path) != ln["mtime"]:
                app.fireCustomEvent(EVENT_ID, path)


def _saved(path):
    """When the user last saved the design by hand. The editor also saves itself on every slider move;
    rebuilding the pattern that often is too slow, so it touches <design>.saved only on Ctrl+S."""
    try:
        return os.path.getmtime(path + ".saved")
    except OSError:
        return 0.0


class DesignChanged(adsk.core.CustomEventHandler):
    def notify(self, args):
        path = args.additionalInfo
        try:
            update(path)
        except Exception:
            if path in links:  # skip this version instead of retrying a broken one every half second
                links[path]["mtime"] = _saved(path)
            _ui().messageBox("VentForge update failed:\n" + traceback.format_exc())


def _face(inp):
    sel = inp.itemById("face")
    return sel.selection(0).entity if sel.selectionCount else None


class Created(adsk.core.CommandCreatedEventHandler):
    def notify(self, args):
        try:
            cmd = args.command
            inp = cmd.commandInputs
            sel = inp.addSelectionInput("face", "Face", "Pick the planar face for the pattern")
            sel.addSelectionFilter("PlanarFaces")
            sel.setSelectionLimits(1, 1)
            inp.addStringValueInput("file", "Design", _last_design())
            inp.addBoolValueInput("browse", "Choose design…", False, "", False)
            inp.addBoolValueInput("edit", "New / edit in VentForge", False, "", False)
            inp.addValueInput("angle", "Rotation", "deg", adsk.core.ValueInput.createByReal(0))
            inp.addTextBoxCommandInput("help", "", "Pick the face and press OK. No design yet? Leave it empty: "
                                       "VentForge starts one shaped like the face. The editor opens; each "
                                       "save there (Ctrl+S) updates the pattern here. Relief <b>through</b> / "
                                       "<b>deboss</b> cuts, <b>emboss</b> joins (Canvas → Relief).", 5, True)
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
                if os.path.isfile(f.value):
                    _open_editor(f.value)
                elif _face(inp):
                    f.value = new_design(_face(inp), inp.itemById("angle").value)
                    _open_editor(f.value)
                else:
                    _ui().messageBox("Pick a face first: the new design takes its shape.")
        except Exception:
            _ui().messageBox("VentForge:\n" + traceback.format_exc())


class Execute(adsk.core.CommandEventHandler):
    def notify(self, args):
        try:
            inp = args.command.commandInputs
            path = inp.itemById("file").value.strip()
            if not path:
                path = new_design(_face(inp), inp.itemById("angle").value)
            if not os.path.isfile(path):
                _ui().messageBox(f"No VentForge design at\n{path}")
                return
            insert(_face(inp), path, inp.itemById("angle").value)
            _open_editor(path)  # live link: each save (Ctrl+S) there updates the pattern
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
        app = adsk.core.Application.get()
        app.unregisterCustomEvent(EVENT_ID)  # left over from a crashed run
        h = DesignChanged()
        app.registerCustomEvent(EVENT_ID).add(h)
        handlers.append(h)
        stop_watch.clear()
        threading.Thread(target=_watch, daemon=True).start()
    except Exception:
        _ui().messageBox("VentForge add-in failed to start:\n" + traceback.format_exc())


def stop(context):
    stop_watch.set()
    links.clear()
    adsk.core.Application.get().unregisterCustomEvent(EVENT_ID)
    ui = _ui()
    panel = ui.allToolbarPanels.itemById(PANEL)
    c = panel and panel.controls.itemById(CMD_ID)
    if c:
        c.deleteMe()
    d = ui.commandDefinitions.itemById(CMD_ID)
    if d:
        d.deleteMe()
