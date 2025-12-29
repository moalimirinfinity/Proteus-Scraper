from __future__ import annotations

import importlib.util
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.db import async_session
from core.models import Schema, TenantPluginConfig

logger = logging.getLogger(__name__)

_PLUGIN_NAME_RE = re.compile(r"^[a-zA-Z0-9_]+$")


@dataclass
class RequestContext:
    url: str
    headers: dict[str, str] = field(default_factory=dict)
    cookies: list[dict[str, Any]] = field(default_factory=list)
    proxy_url: str | None = None
    engine: str | None = None
    tenant: str | None = None
    schema_id: str | None = None
    job_id: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class ResponseContext:
    url: str
    status: int | None
    headers: dict[str, str] = field(default_factory=dict)
    body: str = ""
    content: bytes | None = None
    content_type: str | None = None
    cookies: list[dict[str, Any]] = field(default_factory=list)
    truncated: bool = False
    engine: str | None = None
    tenant: str | None = None
    schema_id: str | None = None
    job_id: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class ParseContext:
    data: dict
    errors: list[str]
    engine: str | None = None
    tenant: str | None = None
    schema_id: str | None = None
    job_id: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)


class BasePlugin:
    name: str = ""

    def on_request(self, ctx: RequestContext) -> RequestContext | None:  # pragma: no cover - default
        return None

    def on_response(self, ctx: ResponseContext) -> ResponseContext | None:  # pragma: no cover - default
        return None

    def on_parse(self, ctx: ParseContext) -> ParseContext | None:  # pragma: no cover - default
        return None


class PluginLoadError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class PluginManager:
    def __init__(
        self,
        plugin_dir: Path | None = None,
        allowlist: Iterable[str] | None = None,
    ) -> None:
        self._plugin_dir = (plugin_dir or Path(settings.plugins_dir or "plugins")).resolve()
        allow = _parse_csv(settings.plugins_allowlist) if allowlist is None else list(allowlist)
        self._allowlist = {name for name in _normalize_names(allow)} if allow else set()
        self._cache: dict[str, BasePlugin] = {}

    def load_many(self, names: Iterable[str]) -> tuple[list[BasePlugin], str | None]:
        plugins: list[BasePlugin] = []
        for name in _normalize_names(names):
            try:
                plugin = self.load(name)
            except PluginLoadError as exc:
                return [], f"{exc.code}:{name}"
            plugins.append(plugin)
        return plugins, None

    def load(self, name: str) -> BasePlugin:
        normalized = _normalize_name(name)
        if not normalized or not _PLUGIN_NAME_RE.match(normalized):
            raise PluginLoadError("plugin_invalid")
        if self._allowlist and normalized not in self._allowlist:
            raise PluginLoadError("plugin_not_allowed")
        cached = self._cache.get(normalized)
        if cached is not None:
            return cached
        path = self._plugin_dir / f"{normalized}.py"
        if not path.exists():
            raise PluginLoadError("plugin_missing")
        if not _is_within_dir(path, self._plugin_dir):
            raise PluginLoadError("plugin_invalid")
        plugin = _load_plugin_module(normalized, path)
        self._cache[normalized] = plugin
        return plugin


_PLUGIN_MANAGER: PluginManager | None = None


def load_plugins(names: Iterable[str]) -> tuple[list[BasePlugin], str | None]:
    global _PLUGIN_MANAGER
    if _PLUGIN_MANAGER is None:
        _PLUGIN_MANAGER = PluginManager()
    return _PLUGIN_MANAGER.load_many(names)


def apply_request_plugins(
    ctx: RequestContext,
    plugins: Iterable[BasePlugin],
) -> tuple[RequestContext, str | None]:
    return _apply_plugins("on_request", RequestContext, ctx, plugins)


def apply_response_plugins(
    ctx: ResponseContext,
    plugins: Iterable[BasePlugin],
) -> tuple[ResponseContext, str | None]:
    return _apply_plugins("on_response", ResponseContext, ctx, plugins)


def apply_parse_plugins(
    ctx: ParseContext,
    plugins: Iterable[BasePlugin],
) -> tuple[ParseContext, str | None]:
    return _apply_plugins("on_parse", ParseContext, ctx, plugins)


def _apply_plugins(
    hook_name: str,
    expected_type: type,
    ctx,
    plugins: Iterable[BasePlugin],
) -> tuple[Any, str | None]:
    for plugin in plugins:
        hook = getattr(plugin, hook_name, None)
        if not callable(hook):
            continue
        try:
            result = hook(ctx)
        except Exception:
            logger.exception("plugin_%s_failed: %s", hook_name, _plugin_name(plugin))
            return ctx, f"plugin_{hook_name}_failed:{_plugin_name(plugin)}"
        if result is None:
            continue
        if not isinstance(result, expected_type):
            return ctx, f"plugin_{hook_name}_invalid:{_plugin_name(plugin)}"
        ctx = result
    return ctx, None


async def resolve_plugin_names(
    session: AsyncSession,
    schema_id: str | None,
    tenant: str | None,
) -> list[str]:
    names: list[str] = []
    names.extend(_parse_csv(settings.plugins_default))

    if tenant:
        result = await session.execute(
            select(TenantPluginConfig).where(TenantPluginConfig.tenant == tenant)
        )
        config = result.scalar_one_or_none()
        if config and config.plugins:
            names.extend(_coerce_plugin_list(config.plugins))

    if schema_id:
        result = await session.execute(select(Schema.plugins).where(Schema.id == schema_id))
        plugins = result.scalar_one_or_none()
        if plugins:
            names.extend(_coerce_plugin_list(plugins))

    return _normalize_names(names)


async def resolve_plugin_names_async(
    schema_id: str | None,
    tenant: str | None,
) -> list[str]:
    async with async_session() as session:
        return await resolve_plugin_names(session, schema_id, tenant)


def _load_plugin_module(name: str, path: Path) -> BasePlugin:
    module_name = f"plugins.{name}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise PluginLoadError("plugin_invalid")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # pragma: no cover - import error
        logger.exception("plugin_load_error: %s", name)
        raise PluginLoadError("plugin_load_failed") from exc

    plugin = getattr(module, "PLUGIN", None)
    if plugin is None and hasattr(module, "get_plugin"):
        plugin = module.get_plugin()
    if plugin is None and hasattr(module, "plugin"):
        plugin = module.plugin
    if plugin is None:
        raise PluginLoadError("plugin_invalid")
    if isinstance(plugin, type):
        plugin = plugin()
    if not hasattr(plugin, "name"):
        raise PluginLoadError("plugin_invalid")
    if not getattr(plugin, "name"):
        try:
            setattr(plugin, "name", name)
        except Exception:  # pragma: no cover - defensive
            raise PluginLoadError("plugin_invalid")
    return plugin


def _parse_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [entry.strip() for entry in value.split(",") if entry.strip()]


def _coerce_plugin_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if isinstance(value, str):
        return _parse_csv(value)
    return []


def _normalize_name(name: str | None) -> str:
    if not name:
        return ""
    return str(name).strip().lower()


def _normalize_names(names: Iterable[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for name in names:
        value = _normalize_name(name)
        if not value or value in seen:
            continue
        normalized.append(value)
        seen.add(value)
    return normalized


def _plugin_name(plugin: BasePlugin) -> str:
    name = getattr(plugin, "name", None)
    if isinstance(name, str) and name:
        return name
    return plugin.__class__.__name__


def _is_within_dir(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False
