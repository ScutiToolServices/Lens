"""Real MCP initialization, requester forwarding, mode schema and progress notifications."""

import asyncio
import json
import socket
import threading
import time

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.shared._httpx_utils import create_mcp_http_client
import pytest
import uvicorn

from src.app import build_app
from src.config import Settings
from tests.test_core import FakeEngine, image_bytes

TOKEN = {"X-Internal-Token": "test-token"}


@pytest.fixture
def running_server(tmp_path):
    engine = FakeEngine()
    with socket.socket() as socket_probe:
        socket_probe.bind(("127.0.0.1", 0))
        port = socket_probe.getsockname()[1]
    app = build_app(Settings(data_dir=tmp_path, port=port, internal_token="test-token"), engine)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    try:
        while not server.started and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert server.started
        yield f"http://127.0.0.1:{port}", engine
    finally:
        server.should_exit = True
        thread.join(10)
        assert not thread.is_alive()


async def test_mcp_modes_default_fast_and_progress(running_server):
    url, engine = running_server
    async with httpx.AsyncClient() as client:
        uploaded = await client.post(url + "/api/files", content=image_bytes(),
                                    headers={**TOKEN, "X-Requester-Username": "ann"})
    file_id = uploaded.json()["file_id"]
    async with create_mcp_http_client(headers=TOKEN, timeout=httpx.Timeout(15)) as http:
        async with streamable_http_client(url + "/mcp", http_client=http) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = {tool.name: tool for tool in (await session.list_tools()).tools}
                assert set(tools) == {"tool_ocr_modes", "tool_ocr_extract"}
                assert tools["tool_ocr_extract"].inputSchema["properties"]["mode"]["default"] == "accurate"
                progress = []

                async def on_progress(value, total, message):
                    progress.append((value, total))

                arguments = {"file_id": file_id, "regions": [[0, 0, 20, 20], [20, 0, 40, 20]]}
                meta = {"requester": {"username": "ann"}}
                result = await session.call_tool("tool_ocr_extract", arguments, meta=meta,
                                                 progress_callback=on_progress)
                assert not result.isError
                assert json.loads(result.content[0].text)["mode"] == "accurate"
                assert progress == [(1.0, 2.0), (2.0, 2.0)]
                fast = await session.call_tool("tool_ocr_extract", {**arguments, "mode": "fast"}, meta=meta)
                assert not fast.isError and json.loads(fast.content[0].text)["mode"] == "fast"
                assert (await session.call_tool("tool_ocr_extract", {"file_id": file_id})).isError


async def test_sse_arrives_before_remaining_region_finishes(running_server):
    url, engine = running_server
    release = threading.Event()
    recognize = engine.recognize

    def controlled(crop, mode, timeout):
        if crop.getpixel((0, 0)) == (0, 0, 255):
            assert release.wait(5)
        return recognize(crop, mode, timeout)

    engine.recognize = controlled
    async with httpx.AsyncClient(timeout=10) as http:
        uploaded = await http.post(url + "/api/files", content=image_bytes(),
                                   headers={**TOKEN, "X-Requester-Username": "ann"})
        body = {"file_id": uploaded.json()["file_id"], "regions": [[0, 0, 20, 20], [20, 0, 40, 20]]}
        try:
            async with http.stream("POST", url + "/api/extract/stream", json=body,
                                   headers={**TOKEN, "X-Requester-Username": "ann"}) as response:
                events = response.aiter_lines()
                async with asyncio.timeout(3):
                    async for line in events:
                        if line.startswith("data: ") and json.loads(line[6:])["type"] == "region":
                            assert not release.is_set()
                            release.set()
                            break
                remainder = [line async for line in events]
                assert any('"type": "complete"' in line for line in remainder)
        finally:
            release.set()
