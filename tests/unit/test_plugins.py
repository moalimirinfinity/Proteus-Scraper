from __future__ import annotations

from pathlib import Path

from scraper.plugins import (
    PluginManager,
    RequestContext,
    ResponseContext,
    apply_request_plugins,
    apply_response_plugins,
)


def test_reference_plugins_load_and_apply() -> None:
    manager = PluginManager(
        plugin_dir=Path("plugins"),
        allowlist=["custom_headers", "payload_transform"],
    )
    plugins, error = manager.load_many(["custom_headers", "payload_transform"])
    assert error is None
    names = {plugin.name for plugin in plugins}
    assert names == {"custom_headers", "payload_transform"}

    request_ctx = RequestContext(url="https://example.com")
    request_ctx, error = apply_request_plugins(request_ctx, plugins)
    assert error is None
    assert request_ctx.headers["X-Proteus-Plugin"] == "custom_headers"

    response_ctx = ResponseContext(
        url="https://example.com",
        status=200,
        headers={"content-type": "application/json"},
        body='{"html":"<h1>ok</h1>"}',
        content=b'{"html":"<h1>ok</h1>"}',
        content_type="application/json",
    )
    response_ctx, error = apply_response_plugins(response_ctx, plugins)
    assert error is None
    assert response_ctx.body == "<h1>ok</h1>"
