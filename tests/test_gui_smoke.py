"""Offscreen smoke test of the GUI: presets, edits, undo/redo, drawing, save, live reload, exports."""
import json
import os
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if os.name == "nt":  # offscreen platform finds no fonts on its own
    os.environ.setdefault("QT_QPA_FONTDIR", os.path.expandvars(r"%WINDIR%\Fonts"))

import pytest
from PySide6.QtWidgets import QApplication

from ventforge import gui
from ventforge.model import MODES, Design


def wait(cond, timeout=20.0):
    end = time.time() + timeout
    while time.time() < end:
        QApplication.processEvents()
        try:
            if cond():
                return True
        except (OSError, ValueError):  # file mid-replace on Windows: retry
            pass
        time.sleep(0.01)
    return False


@pytest.fixture
def win(tmp_path, monkeypatch):
    monkeypatch.setattr(gui.QSettings, "value", lambda self, k, default=None: str(tmp_path / "lib"))
    app = QApplication.instance() or QApplication([])
    gui.dark_theme(app)
    w = gui.MainWindow()
    w.show()
    yield w
    w.dirty = False
    w.close()
    w.deleteLater()
    QApplication.processEvents()


def settle(w):
    assert wait(w.idle), "regeneration did not finish"
    assert w.result is not None


def test_gui_smoke(win, tmp_path):
    w = win
    settle(w)
    assert w.result.stats["count"] > 0

    # every preset loads and generates
    presets = sorted(gui.PRESETS.glob("*.vent.json"))
    for p in presets:
        assert w.open_file(str(p), template=True)
        settle(w)
    assert w.lib_list.count() >= len(presets)

    # every mode generates
    w.set_design(Design())
    for m in MODES:
        w.set_param("pattern.mode", m)
        settle(w)
        assert [not p.isHidden() for p in w.mode_stack.pages] == [k == m for k in MODES]
        assert "Generate failed" not in w.statusBar().currentMessage(), m
    w.set_param("pattern.mode", "grid")
    w.commit()

    # param edits through widgets + undo/redo
    spin = next(wd for p, wd in w.bindings if p == "dot.diameter")
    spin.setValue(3.0)
    w.commit()
    w.set_param("pattern.grid.spacing_x", 8.0)
    w.commit()
    settle(w)
    assert w.design.pattern.grid.spacing_x == 8.0
    w.undo()
    assert w.design.pattern.grid.spacing_x == 6.0 and w.design.dot.diameter == 3.0
    w.undo()
    assert w.design.dot.diameter == 4.0
    w.redo()
    w.redo()
    assert w.design.pattern.grid.spacing_x == 8.0
    settle(w)

    # gradient control + dragging a handle
    w.add_control("size", "point")
    assert len(w.canvas.handles) == 1
    w.canvas.handles[0].setPos(gui.S(10, 5))
    assert w.design.gradients.size.controls[0].points[0] == [10.0, 5.0]
    w.randomize()
    settle(w)
    tri = [[-40, -40], [40, -40], [0, 45]]
    for target in ("outline", "path", "points", "hole"):  # what the draw buttons do once the clicks are in
        w.start_draw(target)
        w.finish_drawing(tri)
        w.set_tool(None)
    settle(w)
    d = w.design
    assert d.boundary.type == "custom" and d.boundary.points == tri and d.pattern.path.points == tri
    assert d.pattern.custom_points.points == tri and d.dot.shape == "custom" and d.dot.custom_points == tri
    w.start_draw("path")
    w.finish_drawing(tri[:1])  # too few points: nothing changes
    assert w.design.pattern.path.points == tri

    # picking "Drawn" with nothing drawn starts drawing; no toolbar button repeats a panel button
    w.set_design(Design())
    w.set_param("boundary.type", "custom")
    assert w.canvas.tool == "draw" and w.draw_target == "outline" and w.draw_act.isChecked()
    w.set_param("boundary.type", "circle")  # changed their mind: the drawing stops
    assert w.canvas.tool is None
    from PySide6.QtWidgets import QPushButton, QToolBar
    bar = {a.text() for tb in w.findChildren(QToolBar) for a in tb.actions() if a.text()}
    assert not bar & {b.text() for b in w.findChildren(QPushButton)}
    assert len(bar) == len([a for tb in w.findChildren(QToolBar) for a in tb.actions() if a.text()])
    w.set_design(Design())

    # save, then edit the file externally -> live reload, own write ignored
    f = tmp_path / "t.vent.json"
    assert w.save_to(str(f))
    wait(lambda: False, 0.5)  # let the watcher fire for our own write
    assert not w.dirty
    zoom = w.canvas.transform().m11()
    d = Design.load(f)
    d.dot.diameter = 2.5
    d.save(f)  # atomic replace, like the MCP server
    assert wait(lambda: w.design.dot.diameter == 2.5, 20), "live reload did not happen"
    assert w.canvas.transform().m11() == zoom
    settle(w)

    # json still valid on disk
    assert json.loads(f.read_text())["dot"]["diameter"] == 2.5

    # editor edits are autosaved, so an MCP edit never starts from a stale file
    w.set_param("dot.diameter", 3.5)
    assert wait(lambda: json.loads(f.read_text())["dot"]["diameter"] == 3.5, 20), "edit not autosaved"
    assert not w.dirty

    # only a manual save stamps <design>.saved, the Fusion add-in's cue to rebuild
    stamp = Path(str(f) + ".saved")
    t = stamp.stat().st_mtime_ns
    w.set_param("dot.diameter", 3.0)
    assert wait(lambda: json.loads(f.read_text())["dot"]["diameter"] == 3.0, 20)
    assert stamp.stat().st_mtime_ns == t, "autosave must not stamp"
    time.sleep(0.02)
    assert w.save()
    assert stamp.stat().st_mtime_ns > t

    # exports run in a worker
    for ext in (".svg", ".png", ".dxf"):
        out = tmp_path / f"e{ext}"
        w.run_export(lambda r, d, out=out: gui.exporter().export(r, d, out), str(out))
        assert wait(lambda: not w.tasks, 60) and out.stat().st_size > 0, ext
