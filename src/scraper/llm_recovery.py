from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import instructor
from instructor.function_calls import Mode
from openai import OpenAI
from pydantic import Field, create_model
from selectolax.parser import HTMLParser

from core.config import settings
from scraper.parsing import SelectorSpec, normalize_data


@dataclass(frozen=True)
class LLMRecoveryResult:
    success: bool
    data: dict[str, Any] | None = None
    selectors: dict[str, str] | None = None
    error: str | None = None


def recover_with_llm(html: str, selectors: list[SelectorSpec]) -> LLMRecoveryResult:
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
    except Exception:
        return LLMRecoveryResult(success=False, error="llm_failed")

    data = response.data.model_dump()
    normalized, errors = normalize_data(data, selectors)
    if errors:
        return LLMRecoveryResult(success=False, error="llm_validation_failed")

    selectors_out = dict(response.selectors or {})
    filtered = {k: v for k, v in selectors_out.items() if k in normalized and v}
    if not filtered:
        filtered = _infer_selectors(html_snippet, normalized, selectors)

    return LLMRecoveryResult(success=True, data=normalized, selectors=filtered, error=None)


def _build_response_model(selectors: list[SelectorSpec]):
    type_map = {
        "string": str,
        "int": int,
        "float": float,
        "bool": bool,
    }
    fields: dict[str, tuple[type, Field]] = {}
    for spec in selectors:
        field_type = type_map.get(spec.data_type, str)
        if not spec.required:
            field_type = field_type | None
            default = None
        else:
            default = ...
        fields[spec.field] = (field_type, Field(default))

    data_model = create_model("ExtractedData", **fields)
    response_model = create_model(
        "LLMRecoveryResponse",
        data=(data_model, ...),
        selectors=(dict[str, str], Field(default_factory=dict)),
    )
    return response_model


def _build_prompt(selectors: list[SelectorSpec], html: str) -> str:
    schema_lines = [
        f"- {spec.field}: {spec.data_type} ({'required' if spec.required else 'optional'})"
        for spec in selectors
    ]
    schema = "\n".join(schema_lines)
    return (
        "Extract the fields below from the HTML. Provide CSS selectors for each extracted field "
        "in `selectors`.\n\n"
        f"Schema:\n{schema}\n\n"
        f"HTML:\n{html}"
    )


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
    nodes = tree.css("body *")
    for spec in selectors:
        value = data.get(spec.field)
        if value is None:
            continue
        text = str(value).strip()
        if not text:
            continue
        for node in nodes:
            if node.text(strip=True) == text:
                inferred[spec.field] = node.tag
                break
    return inferred
