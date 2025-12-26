from __future__ import annotations

from dataclasses import dataclass

from selectolax.parser import HTMLParser


@dataclass(frozen=True)
class SelectorSpec:
    field: str
    selector: str
    data_type: str
    required: bool = True


def parse_html(html: str, selectors: list[SelectorSpec]) -> tuple[dict, list[str]]:
    tree = HTMLParser(html)
    data: dict[str, object] = {}
    errors: list[str] = []

    for spec in selectors:
        node = tree.css_first(spec.selector)
        raw = node.text(strip=True) if node else None
        if raw is None or raw == "":
            if spec.required:
                errors.append(f"missing:{spec.field}")
            continue
        try:
            data[spec.field] = coerce_value(raw, spec.data_type)
        except ValueError:
            errors.append(f"type:{spec.field}")

    return data, errors


def coerce_value(value: str, data_type: str) -> object:
    if data_type == "string":
        return value
    if data_type == "int":
        return int(value.replace(",", ""))
    if data_type == "float":
        return float(value.replace(",", ""))
    if data_type == "bool":
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return value
