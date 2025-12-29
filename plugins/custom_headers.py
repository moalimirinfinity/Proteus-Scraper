from __future__ import annotations

from scraper.plugins import BasePlugin, RequestContext


class CustomHeadersPlugin(BasePlugin):
    name = "custom_headers"

    def on_request(self, ctx: RequestContext) -> RequestContext | None:
        ctx.headers.setdefault("X-Proteus-Plugin", "custom_headers")
        ctx.headers.setdefault("X-Requested-With", "Proteus")
        return ctx


PLUGIN = CustomHeadersPlugin()
