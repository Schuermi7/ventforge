"""The MCP server: over real stdio the way Claude talks to it, then each tool's rules directly."""
import asyncio
import json
import sys
from pathlib import Path

import pytest


async def _over_stdio(out: Path):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    params = StdioServerParameters(command=sys.executable, args=["-m", "ventforge.mcp_server"],
                                   cwd=str(Path(__file__).resolve().parent.parent))
    async with stdio_client(params) as (r, w), ClientSession(r, w) as s:
        await s.initialize()
        assert "apply_to_fusion" in {t.name for t in (await s.list_tools()).tools}

        async def call(name, **args):
            res = await s.call_tool(name, args)
            assert not res.is_error, (name, res.content)
            return json.loads(next(c.text for c in res.content if c.type == "text"))

        await call("new_design", path=str(out / "e2e.vent.json"), preset="hex_honeycomb")
        await call("set_params", patch={"canvas": {"width": 150, "height": 80}})
        await call("add_control", target="size", kind="line", points=[[-75, 0], [75, 0]], value=0.3, radius=30)
        prev = await s.call_tool("preview", {"px": 300})
        assert any(c.type == "image" and c.data for c in prev.content)
        assert (await call("export", path=str(out / "e2e.svg")))["bytes"] > 0
        assert (await s.call_tool("set_params", {"patch": {"dot": {"nope": 1}}})).is_error
        assert (await s.call_tool("add_control", {"target": "sise"})).is_error


def test_mcp_server_over_stdio(tmp_path):
    asyncio.run(_over_stdio(tmp_path))


def test_bad_patch_leaves_file_untouched(tmp_path):
    import pytest
    from ventforge import mcp_server as m
    p = tmp_path / "d.vent.json"
    m.new_design(path=str(p))
    before = p.read_bytes()
    with pytest.raises(ValueError):
        m.set_params({"dot": {"shape": "blob"}})
    assert p.read_bytes() == before


def test_set_params_keeps_an_edit_saved_meanwhile(tmp_path, monkeypatch):
    """The editor saving while set_params generates must not be overwritten."""
    import os
    from ventforge import mcp_server as m
    from ventforge.model import Design
    p = tmp_path / "d.vent.json"
    m.new_design(path=str(p))
    real, calls = m._generate, []

    def generate_while_editor_saves(d):
        if not calls:
            e = Design.load(p)
            e.dot.diameter = 2.5
            e.save(p)
            os.utime(p, ns=(p.stat().st_atime_ns, p.stat().st_mtime_ns + 10**9))  # coarse clocks
        calls.append(1)
        return real(d)

    monkeypatch.setattr(m, "_generate", generate_while_editor_saves)
    m.set_params({"canvas": {"width": 140}})
    d = Design.load(p)
    assert d.dot.diameter == 2.5 and d.canvas.width == 140


def test_fit_open_area_hits_target(tmp_path):
    from ventforge import mcp_server as m
    m.new_design(path=str(tmp_path / "f.vent.json"))
    out = m.fit_open_area(0.3)
    assert abs(out["stats"]["open_area_ratio"] - 0.3) < 0.01
    assert m.get_design()["design"]["dot"]["diameter"] == out["dot.diameter"]
    m.new_design(path=str(tmp_path / "g.vent.json"))  # a switched-off variation is switched on, like set_params
    out = m.fit_open_area(0.3, param="gradients.size.edge", low=0.3, high=1.5)
    assert abs(out["stats"]["open_area_ratio"] - 0.3) < 0.01
    assert m.get_design()["design"]["gradients"]["size"]["enabled"]


def test_fit_open_area_refuses_unreachable_target(tmp_path):
    from ventforge import mcp_server as m
    m.new_design(path=str(tmp_path / "f.vent.json"))
    before = (tmp_path / "f.vent.json").read_text()
    with pytest.raises(ValueError, match="outside"):
        m.fit_open_area(0.3, low=0.5, high=0.6)
    with pytest.raises(ValueError, match="ratio"):
        m.fit_open_area(30)
    with pytest.raises(ValueError, match="unknown parameter"):
        m.fit_open_area(0.3, param="dot.nope")
    assert (tmp_path / "f.vent.json").read_text() == before


def test_fan_grille_tool_saves_and_reports_airflow(tmp_path):
    from ventforge import mcp_server as m
    m.new_design(path=str(tmp_path / "f.vent.json"))
    out = m.fan_grille(80)
    d = m.get_design()["design"]
    assert d["canvas"]["width"] == 80 and len(d["keepouts"]) == 4
    assert 0 < out["stats"]["fan_open_ratio"] < 1
    fit = m.fit_open_area(0.5)  # targets the fan opening now
    assert abs(fit["stats"]["fan_open_ratio"] - 0.5) < 0.01


def test_library_round_trip(tmp_path, monkeypatch):
    from ventforge import mcp_server as m
    monkeypatch.setattr(m, "_library", lambda: tmp_path)
    m.new_design(path=str(tmp_path / "work.vent.json"))
    m.fan_grille(92)
    m.save_to_library("92mm case X")
    assert "92mm case X" in m.list_presets()["library"]
    m.new_design(path=str(tmp_path / "other.vent.json"), preset="92mm case X")
    assert len(m.get_design()["design"]["keepouts"]) == 4
    for bad in ("../evil", "a/b", ""):
        with pytest.raises(ValueError):
            m.save_to_library(bad)


def test_set_params_reports_no_effect_and_switches_variations_on(tmp_path):
    from ventforge import mcp_server as m
    m.new_design(path=str(tmp_path / "d.vent.json"))  # round holes on a grid
    out = m.set_params({"dot": {"star_inner": 0.3, "diameter": 3}, "pattern": {"spiral": {"turns": 4}},
                        "gradients": {"size": {"noise": 0.4}}})
    assert sorted(out["no_effect"]) == ["dot.star_inner", "pattern.spiral.turns"]
    assert m.get_design()["design"]["gradients"]["size"]["enabled"]  # like the editor: touching it switches it on
    m.set_params({"gradients": {"spacing": {"noise": 0.4, "enabled": False}}})
    assert not m.get_design()["design"]["gradients"]["spacing"]["enabled"]  # an explicit off wins
    m.set_params({"gradients": {"angle": {"controls": []}}})
    assert not m.get_design()["design"]["gradients"]["angle"]["enabled"]  # clearing is not editing
    assert "no_effect" not in m.set_params({"dot": {"shape": "star", "star_inner": 0.3}})
    assert "Inner size" in m.describe_parameters()["help"]["dot.star_inner"]


def test_apply_to_fusion_marks_a_manual_save(tmp_path):
    from ventforge import mcp_server as m
    p = tmp_path / "d.vent.json"
    m.new_design(path=str(p))
    m.set_params({"dot": {"diameter": 3}})
    assert not (tmp_path / "d.vent.json.saved").exists()  # in-between saves do not rebuild Fusion parts
    m.apply_to_fusion()
    assert (tmp_path / "d.vent.json.saved").exists()
