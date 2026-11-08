"""One entry point for both programs, so a bundled app can also serve as the MCP server:
    ventforge [design.vent.json]   desktop editor
    ventforge --mcp                MCP server (stdio)
    ventforge tool design.vent.json out.step [--depth MM]
                                   pattern as loose solids for a CAD add-in (prints JSON)
    ventforge install-fusion [--to DIR]
                                   install the Autodesk Fusion add-in (Solid > Create > VentForge pattern)
"""
import sys


def tool(argv):
    import argparse
    import json

    from .export import pattern_tools
    from .model import Design
    from .pattern import generate

    ap = argparse.ArgumentParser(prog="ventforge tool", description="Write the pattern as solids for a CAD add-in.")
    ap.add_argument("design")
    ap.add_argument("out")
    ap.add_argument("--depth", type=float, default=None, help="cut depth in mm for relief 'through'")
    a = ap.parse_args(argv)
    d = Design.load(a.design)
    print(json.dumps(pattern_tools(generate(d), d, a.out, a.depth)))


def fusion_addins_dir():
    from pathlib import Path
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support/Autodesk/Autodesk Fusion 360/API/AddIns"
    import os
    return Path(os.environ.get("APPDATA", Path.home() / "AppData/Roaming")) / "Autodesk/Autodesk Fusion 360/API/AddIns"


def install_fusion(argv):
    import argparse
    import json
    import shutil
    from pathlib import Path

    ap = argparse.ArgumentParser(prog="ventforge install-fusion")
    ap.add_argument("--to", type=Path, default=None, help="Fusion AddIns folder (default: the standard one)")
    root = ap.parse_args(argv).to or fusion_addins_dir()
    dest = root / "VentForge"
    shutil.copytree(Path(__file__).with_name("fusion") / "VentForge", dest, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("__pycache__", "settings.json"))
    # Fusion's own Python has no shapely/OpenCascade, so the add-in calls back into this installation
    cmd = [sys.executable] if getattr(sys, "frozen", False) else [sys.executable, "-m", "ventforge"]
    (dest / "settings.json").write_text(json.dumps({"command": cmd}, indent=2), encoding="utf-8")
    print(f"Installed the Fusion add-in in {dest}\nIn Fusion: Utilities > Add-Ins > VentForge > Run "
          "(it then starts with Fusion). The command is under Solid > Create > VentForge pattern.")


def run():
    if sys.argv[1:2] == ["tool"]:
        return tool(sys.argv[2:])
    if sys.argv[1:2] == ["install-fusion"]:
        return install_fusion(sys.argv[2:])
    if "--mcp" in sys.argv[1:]:
        from .mcp_server import main
        return main()
    try:
        from .gui import main
    except ImportError as e:
        if not (e.name or "").startswith("PySide6"):
            raise
        raise SystemExit('The VentForge editor needs the GUI extra: pip install "ventforge[gui]"') from None
    return main()


if __name__ == "__main__":
    raise SystemExit(run())
