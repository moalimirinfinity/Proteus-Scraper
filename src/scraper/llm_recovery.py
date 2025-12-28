from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import instructor
from instructor.function_calls import Mode
from openai import OpenAI
from pydantic import Field, create_model
from selectolax.parser import HTMLParser

from core.config import settings
from core.metrics import record_llm_usage
from scraper.parsing import SelectorSpec, normalize_data


@dataclass(frozen=True)
class LLMRecoveryResult:
    success: bool
    data: dict[str, Any] | None = None
    selectors: dict[str, str] | None = None
    error: str | None = None


def recover_with_llm(
    html: str,
    selectors: list[SelectorSpec],
    tenant: str | None = None,
) -> LLMRecoveryResult:
    if not settings.openai_api_key:
        return LLMRecoveryResult(success=False, error="llm_unavailable")

    html_snippet = _truncate_html(html)
    response_model = _build_response_model(selectors)

    try:
        client = instructor.patch(
            OpenAI(api_key=settings.openai_api_key, timeout=settings.llm_timeout_ms / 1000),
            mode=Mode.TOOLS,
        )
        response = client.chat.completions.create(
            model=settings.llm_model,
            temperature=settings.llm_temperature,
            max_tokens=settings.llm_max_tokens,
            response_model=response_model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You extract structured fields from HTML. "
                        "Return JSON with `data` and `selectors`."
                    ),
                },
                {
                    "role": "user",
                    "content": _build_prompt(selectors, html_snippet),
                },
            ],
        )
        _record_usage(response, tenant)
    except Exception:
        return LLMRecoveryResult(success=False, error="llm_failed")

    data = response.data.model_dump()
    normalized, errors = normalize_data(data, selectors)
    if errors:
        return LLMRecoveryResult(success=False, error="llm_validation_failed")

    selectors_out = dict(response.selectors or {})
    allowed_keys = _allowed_selector_keys(selectors)
    filtered = {k: v for k, v in selectors_out.items() if k in allowed_keys and v}
    if not filtered:
        filtered = _infer_selectors(html_snippet, normalized, selectors)

    return LLMRecoveryResult(success=True, data=normalized, selectors=filtered, error=None)


def _record_usage(response, tenant: str | None) -> None:
    usage = getattr(response, "usage", None)
    if usage is None:
        raw = getattr(response, "_raw_response", None)
        usage = getattr(raw, "usage", None) if raw is not None else None
    tokens = getattr(usage, "total_tokens", None) if usage is not None else None
    record_llm_usage(settings.llm_model, tokens, tenant)


def _build_response_model(selectors: list[SelectorSpec]):
    type_map = {
        "string": str,
        "int": int,
        "float": float,
        "bool": bool,
    }
    fields: dict[str, tuple[type, Field]] = {}
    flat, groups = _split_selectors(selectors)

    for spec in flat:
        field_type = type_map.get(spec.data_type, str)
        if not spec.required:
            field_type = field_type | None
            default = None
        else:
            default = ...
        fields[spec.field] = (field_type, Field(default))

    for group_name, specs in groups.items():
        item_fields: dict[str, tuple[type, Field]] = {}
        for spec in specs:
            field_type = type_map.get(spec.data_type, str)
            if not spec.required:
                field_type = field_type | None
                default = None
            else:
                default = ...
            item_fields[spec.field] = (field_type, Field(default))

        item_model = create_model(f"{_safe_model_name(group_name)}Item", **item_fields)
        list_type = list[item_model]
        if any(spec.required for spec in specs):
            fields[group_name] = (list_type, Field(...))
        else:
            fields[group_name] = (list_type, Field(default_factory=list))

    data_model = create_model("ExtractedData", **fields)
    response_model = create_model(
        "LLMRecoveryResponse",
        data=(data_model, ...),
        selectors=(dict[str, str], Field(default_factory=dict)),
    )
    return response_model


def _build_prompt(selectors: list[SelectorSpec], html: str) -> str:
    flat, groups = _split_selectors(selectors)
    schema_lines = [
        _format_schema_line(spec.field, spec.data_type, spec.required, spec.attribute)
        for spec in flat
    ]
    for group_name, specs in groups.items():
        item_selector = _resolve_item_selector(specs) or "MISSING_ITEM_SELECTOR"
        schema_lines.append(f"- {group_name}: list (item selector: {item_selector})")
        for spec in specs:
            schema_lines.append(
                _format_schema_line(
                    spec.field,
                    spec.data_type,
                    spec.required,
                    spec.attribute,
                    indent="  ",
                )
            )
    schema = "\n".join(schema_lines)
    return (
        "Extract the fields below from the HTML. Provide CSS selectors for each extracted field "
        "in `selectors`. For list fields, use keys like `<group>.<field>`.\n\n"
        f"Schema:\n{schema}\n\n"
        f"HTML:\n{html}"
    )


def _format_schema_line(
    field: str,
    data_type: str,
    required: bool,
    attribute: str | None,
    indent: str = "",
) -> str:
    suffix = f", attr={attribute}" if attribute else ""
    return f"{indent}- {field}: {data_type} ({'required' if required else 'optional'}{suffix})"


def _truncate_html(html: str) -> str:
    max_chars = settings.llm_max_html_chars
    if len(html) <= max_chars:
        return html
    head = html[: max_chars // 2]
    tail = html[-max_chars // 2 :]
    return f"{head}\n<!-- truncated -->\n{tail}"


def _infer_selectors(html: str, data: dict[str, Any], selectors: list[SelectorSpec]) -> dict[str, str]:
    tree = HTMLParser(html)
    inferred: dict[str, str] = {}
    flat, groups = _split_selectors(selectors)
    nodes = tree.css("body *")

    for spec in flat:
        value = data.get(spec.field)
        if value is None:
            continue
        target = str(value).strip()
        if not target:
            continue
        for node in nodes:
            candidate = _node_value(node, spec)
            if candidate is None:
                continue
            if str(candidate).strip() == target:
                inferred[spec.field] = node.tag
                break

    for group_name, specs in groups.items():
        item_selector = _resolve_item_selector(specs)
        if not item_selector:
            continue
        data_items = data.get(group_name)
        if not isinstance(data_items, list):
            continue
        item_nodes = tree.css(item_selector)
        for idx, item_data in enumerate(data_items):
            if idx >= len(item_nodes) or not isinstance(item_data, dict):
                break
            node_pool = [item_nodes[idx], *item_nodes[idx].css("*")]
            for spec in specs:
                value = item_data.get(spec.field)
                if value is None:
                    continue
                target = str(value).strip()
                if not target:
                    continue
                key = f"{group_name}.{spec.field}"
                if key in inferred:
                    continue
                for node in node_pool:
                    candidate = _node_value(node, spec)
                    if candidate is None:
                        continue
                    if str(candidate).strip() == target:
                        inferred[key] = node.tag
                        break
    return inferred


def _node_value(node, spec: SelectorSpec) -> str | None:
    if spec.attribute:
        return node.attributes.get(spec.attribute)
    return node.text(strip=True)


def _split_selectors(
    selectors: list[SelectorSpec],
) -> tuple[list[SelectorSpec], dict[str, list[SelectorSpec]]]:
    flat: list[SelectorSpec] = []
    groups: dict[str, list[SelectorSpec]] = {}
    for spec in selectors:
        if spec.group_name:
            groups.setdefault(spec.group_name, []).append(spec)
        else:
            flat.append(spec)
    return flat, groups


def _resolve_item_selector(specs: list[SelectorSpec]) -> str | None:
    selectors = {spec.item_selector for spec in specs if spec.item_selector}
    if len(selectors) == 1:
        return selectors.pop()
    return None


def _safe_model_name(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() else "_" for ch in value)
    return cleaned[:48] or "Group"


def _allowed_selector_keys(selectors: list[SelectorSpec]) -> set[str]:
    flat, groups = _split_selectors(selectors)
    keys = {spec.field for spec in flat}
    for group_name, specs in groups.items():
        for spec in specs:
            keys.add(f"{group_name}.{spec.field}")
    return keys
