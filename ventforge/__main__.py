"""One entry point for both programs, so a bundled app can also serve as the MCP server:
    ventforge [design.vent.json]   desktop editor
    ventforge --mcp                MCP server (stdio)
"""
import sys


def run():
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
