"""Require the shared internal token on /mcp and /api. Only enforced when a token is configured."""

from __future__ import annotations

import hmac
import json

TOKEN_HEADER = b"x-internal-token"


def _protected(path: str) -> bool:
    return path == "/mcp" or path.startswith("/mcp/") or path.startswith("/api/")


class InternalTokenMiddleware:
    def __init__(self, app, token: str) -> None:
        self.app = app
        self._token = token.encode("utf-8")

    async def __call__(self, scope, receive, send):
        if self._token and scope["type"] in {"http", "websocket"} and _protected(scope.get("path", "")):
            provided = dict(scope.get("headers") or []).get(TOKEN_HEADER, b"")
            if not hmac.compare_digest(self._token, provided):
                if scope["type"] == "websocket":
                    await send({"type": "websocket.close", "code": 1008})
                    return
                body = json.dumps({"error": "Invalid or missing internal API token"}).encode("utf-8")
                await send({
                    "type": "http.response.start",
                    "status": 401,
                    "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())],
                })
                await send({"type": "http.response.body", "body": body})
                return
        await self.app(scope, receive, send)
