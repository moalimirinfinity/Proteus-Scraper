from __future__ import annotations

import io
import html as html_lib

from scraper.plugins import BasePlugin, ResponseContext


class PdfParserPlugin(BasePlugin):
    name = "pdf_parser"

    def on_response(self, ctx: ResponseContext) -> ResponseContext | None:
        content_type = (ctx.content_type or _header_value(ctx, "content-type") or "").lower()
        if "application/pdf" not in content_type and not _looks_like_pdf(ctx.content):
            return ctx
        try:
            from pypdf import PdfReader
        except Exception:
            return ctx
        payload = ctx.content or ctx.body.encode("utf-8", errors="ignore")
        try:
            reader = PdfReader(io.BytesIO(payload))
        except Exception:
            return ctx
        chunks: list[str] = []
        for page in reader.pages:
            text = page.extract_text() or ""
            if text:
                chunks.append(text)
        text = "\n".join(chunks)
        if not text:
            return ctx
        escaped = html_lib.escape(text)
        ctx.body = f"<pre>{escaped}</pre>"
        ctx.content = ctx.body.encode("utf-8", errors="ignore")
        ctx.content_type = "text/html"
        ctx.headers["content-type"] = "text/html"
        return ctx


def _looks_like_pdf(content: bytes | None) -> bool:
    if not content:
        return False
    return content.startswith(b"%PDF")


def _header_value(ctx: ResponseContext, key: str) -> str | None:
    for candidate in (key, key.lower(), key.upper(), key.title()):
        value = ctx.headers.get(candidate)
        if value:
            return str(value)
    return None


PLUGIN = PdfParserPlugin()
