"""Runs the MCP server over real stdio, the way Claude talks to it."""
import asyncio

from mcp_e2e import main


def test_mcp_server_end_to_end(tmp_path):
    asyncio.run(main(tmp_path))
    assert (tmp_path / "e2e_preview.png").stat().st_size > 0
    for ext in ("svg", "dxf", "step", "stl"):
        assert (tmp_path / f"e2e.{ext}").stat().st_size > 0
    assert (tmp_path / "e2e_tube.step").stat().st_size > 0
