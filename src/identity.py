"""Who asked: Armory forwards the user in the tools/call `_meta.requester`."""

from __future__ import annotations


def owner_from_context(ctx) -> str:
    meta = ctx.request_context.meta
    requester = (meta.model_extra or {}).get("requester") if meta is not None else None
    username = requester.get("username") if isinstance(requester, dict) else None
    return username.strip() if isinstance(username, str) else ""
