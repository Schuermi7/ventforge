import json
import py_compile
import sys
from pathlib import Path

import pytest

from ventforge import __main__ as cli

ADDIN = Path(cli.__file__).with_name("fusion") / "VentForge"


def test_install_fusion_copies_addin_and_points_back_here(tmp_path, capsys):
    cli.install_fusion(["--to", str(tmp_path)])
    dest = tmp_path / "VentForge"
    assert {p.name for p in dest.iterdir()} == {"VentForge.py", "VentForge.manifest", "settings.json"}
    assert json.loads((dest / "settings.json").read_text())["command"] == [sys.executable, "-m", "ventforge"]
    manifest = json.loads((dest / "VentForge.manifest").read_text())
    assert manifest["type"] == "addin" and manifest["autodeskProduct"] == "Fusion360"
    py_compile.compile(str(dest / "VentForge.py"), doraise=True)  # adsk only exists inside Fusion
    assert "Solid > Create > VentForge pattern" in capsys.readouterr().out


def test_tool_cli_prints_json_last(tmp_path, capsys):
    pytest.importorskip("OCP")
    from ventforge.model import Design, fan_grille
    f = tmp_path / "fan.vent.json"
    fan_grille(Design(), 80).save(f)
    cli.tool([str(f), str(tmp_path / "t.step"), "--depth", "3"])
    info = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert info["operation"] == "cut" and info["bodies"] > 4 and (tmp_path / "t.step").stat().st_size > 1000
