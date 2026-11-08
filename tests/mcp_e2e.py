"""End-to-end check of the MCP server over real stdio. Run: python tests/mcp_e2e.py <out_dir>"""
import asyncio
import json
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def main(OUT: Path):
    params = StdioServerParameters(command=sys.executable, args=["-m", "ventforge.mcp_server"],
                                   cwd=str(Path(__file__).resolve().parent.parent))
    async with stdio_client(params) as (r, w), ClientSession(r, w) as s:
        await s.initialize()
        names = [t.name for t in (await s.list_tools()).tools]
        print("tools:", len(names))

        async def call(name, **args):
            res = await s.call_tool(name, args)
            assert not res.is_error, (name, res.content)
            return res

        def text(res):
            return json.loads(next(c.text for c in res.content if c.type == "text"))

        print("presets:", [c.text for c in (await call("list_presets")).content])
        print("new:", text(await call("new_design", path=str(OUT / "e2e.vent.json"), preset="hex_honeycomb")))
        print("set:", text(await call("set_params", patch={"canvas": {"width": 150, "height": 80},
                                                          "boundary": {"type": "rounded_rectangle"}})))
        print("ctl:", text(await call("add_control", target="size", kind="line",
                                      points=[[-75, 0], [75, 0]], value=0.3, radius=30)))
        prev = await call("preview", px=600)
        img = next(c for c in prev.content if c.type == "image")
        import base64
        (OUT / "e2e_preview.png").write_bytes(base64.b64decode(img.data))
        print("preview image ok,", len(img.data), "b64 chars")
        for ext in ("svg", "dxf", "step", "stl"):
            print(ext, text(await call("export", path=str(OUT / f"e2e.{ext}")))["bytes"])
        print("wrap:", text(await call("wrap_cylinder", path=str(OUT / "e2e_tube.step")))["bytes"])
        bad = await s.call_tool("set_params", {"patch": {"dot": {"nope": 1}}})
        print("bad patch rejected:", bad.is_error)
        assert bad.is_error
        bad = await s.call_tool("add_control", {"target": "sise"})
        assert bad.is_error
        enums = text(await call("describe_parameters"))["enums"]
        assert enums["pattern.crosslines.rotate_by"] == ["left", "right", "both"]


if __name__ == "__main__":
    asyncio.run(main(Path(sys.argv[1]).resolve()))
