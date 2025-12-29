from __future__ import annotations

import json

from scraper.plugins import BasePlugin, ResponseContext


class PayloadTransformPlugin(BasePlugin):
    name = "payload_transform"

    def on_response(self, ctx: ResponseContext) -> ResponseContext | None:
        content_type = (ctx.content_type or _header_value(ctx, "content-type") or "").lower()
        if "application/json" not in content_type:
            return ctx
        try:
            payload = json.loads(ctx.body)
        except ValueError:
            return ctx
        if not isinstance(payload, dict):
            return ctx
        for key in ("html", "content", "body"):
            value = payload.get(key)
            if isinstance(value, str) and value:
                ctx.body = value
                ctx.content = value.encode("utf-8", errors="ignore")
                ctx.content_type = "text/html"
                ctx.headers["content-type"] = "text/html"
                break
        return ctx


def _header_value(ctx: ResponseContext, key: str) -> str | None:
    for candidate in (key, key.lower(), key.upper(), key.title()):
        value = ctx.headers.get(candidate)
        if value:
            return str(value)
    return None


PLUGIN = PayloadTransformPlugin()
