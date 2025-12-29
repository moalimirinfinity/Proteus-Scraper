from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urljoin

try:
    from parsel import Selector as ParselSelector
except ModuleNotFoundError:  # pragma: no cover - optional dependency
    ParselSelector = None

from selectolax.parser import HTMLParser


@dataclass(frozen=True)
class SelectorSpec:
    field: str
    selector: str
    data_type: str
    required: bool = True
    group_name: str | None = None
    item_selector: str | None = None
    attribute: str | None = None


def parse_html(html: str, selectors: list[SelectorSpec], base_url: str | None = None) -> tuple[dict, list[str]]:
    if _requires_parsel(selectors):
        if ParselSelector is None:
            return {}, ["parsel_unavailable"]
        return _parse_with_parsel(html, selectors, base_url)
    return _parse_with_selectolax(html, selectors, base_url)


def _parse_with_selectolax(
    html: str,
    selectors: list[SelectorSpec],
    base_url: str | None,
) -> tuple[dict, list[str]]:
    tree = HTMLParser(html)
    data: dict[str, object] = {}
    errors: list[str] = []

    flat, groups = _split_selectors(selectors)

    for spec in flat:
        selector = _strip_css_prefix(spec.selector)
        node = tree.css_first(selector)
        raw = _extract_raw(node, spec, base_url)
        if raw is None or raw == "":
            if spec.required:
                errors.append(f"missing:{spec.field}")
            continue
        try:
            data[spec.field] = coerce_value(raw, spec.data_type)
        except ValueError:
            errors.append(f"type:{spec.field}")

    for group_name, specs in groups.items():
        item_selector = _resolve_item_selector(specs)
        if not item_selector:
            if any(spec.required for spec in specs):
                errors.append(f"missing_group_selector:{group_name}")
            data[group_name] = []
            continue

        item_selector = _strip_css_prefix(item_selector)
        items = tree.css(item_selector)
        if not items:
            if any(spec.required for spec in specs):
                errors.append(f"missing:{group_name}")
            data[group_name] = []
            continue

        group_items: list[dict[str, object]] = []
        for idx, item in enumerate(items):
            item_data: dict[str, object] = {}
            for spec in specs:
                selector = _strip_css_prefix(spec.selector)
                node = item.css_first(selector)
                raw = _extract_raw(node, spec, base_url)
                if raw is None or raw == "":
                    if spec.required:
                        errors.append(f"missing:{group_name}.{spec.field}:{idx}")
                    continue
                try:
                    item_data[spec.field] = coerce_value(raw, spec.data_type)
                except ValueError:
                    errors.append(f"type:{group_name}.{spec.field}:{idx}")
            group_items.append(item_data)

        data[group_name] = group_items

    return data, errors


def _parse_with_parsel(
    html: str,
    selectors: list[SelectorSpec],
    base_url: str | None,
) -> tuple[dict, list[str]]:
    root = ParselSelector(text=html)
    data: dict[str, object] = {}
    errors: list[str] = []

    flat, groups = _split_selectors(selectors)

    for spec in flat:
        engine, selector = _split_selector(spec.selector)
        node = _select_first(root, engine, selector)
        raw = _extract_raw_parsel(node, spec, base_url)
        if raw is None or raw == "":
            if spec.required:
                errors.append(f"missing:{spec.field}")
            continue
        try:
            data[spec.field] = coerce_value(raw, spec.data_type)
        except ValueError:
            errors.append(f"type:{spec.field}")

    for group_name, specs in groups.items():
        item_selector = _resolve_item_selector(specs)
        if not item_selector:
            if any(spec.required for spec in specs):
                errors.append(f"missing_group_selector:{group_name}")
            data[group_name] = []
            continue

        engine, selector = _split_selector(item_selector)
        items = _select_all(root, engine, selector)
        if not items:
            if any(spec.required for spec in specs):
                errors.append(f"missing:{group_name}")
            data[group_name] = []
            continue

        group_items: list[dict[str, object]] = []
        for idx, item in enumerate(items):
            item_data: dict[str, object] = {}
            for spec in specs:
                engine, selector = _split_selector(spec.selector)
                node = _select_first(item, engine, selector)
                raw = _extract_raw_parsel(node, spec, base_url)
                if raw is None or raw == "":
                    if spec.required:
                        errors.append(f"missing:{group_name}.{spec.field}:{idx}")
                    continue
                try:
                    item_data[spec.field] = coerce_value(raw, spec.data_type)
                except ValueError:
                    errors.append(f"type:{group_name}.{spec.field}:{idx}")
            group_items.append(item_data)

        data[group_name] = group_items

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


def normalize_data(data: dict, selectors: list[SelectorSpec]) -> tuple[dict, list[str]]:
    normalized: dict[str, object] = {}
    errors: list[str] = []

    flat, groups = _split_selectors(selectors)

    for spec in flat:
        if spec.field not in data or data[spec.field] is None:
            if spec.required:
                errors.append(f"missing:{spec.field}")
            continue
        value = data[spec.field]
        try:
            normalized[spec.field] = _normalize_value(value, spec.data_type)
        except ValueError:
            errors.append(f"type:{spec.field}")

    for group_name, specs in groups.items():
        raw_items = data.get(group_name)
        if raw_items is None:
            if any(spec.required for spec in specs):
                errors.append(f"missing:{group_name}")
            continue
        if not isinstance(raw_items, list):
            errors.append(f"type:{group_name}")
            continue

        normalized_items: list[dict[str, object]] = []
        for idx, item in enumerate(raw_items):
            if not isinstance(item, dict):
                errors.append(f"type:{group_name}:{idx}")
                continue
            normalized_item: dict[str, object] = {}
            for spec in specs:
                if spec.field not in item or item[spec.field] is None:
                    if spec.required:
                        errors.append(f"missing:{group_name}.{spec.field}:{idx}")
                    continue
                try:
                    normalized_item[spec.field] = _normalize_value(item[spec.field], spec.data_type)
                except ValueError:
                    errors.append(f"type:{group_name}.{spec.field}:{idx}")
            normalized_items.append(normalized_item)
        normalized[group_name] = normalized_items

    return normalized, errors


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


def _extract_raw(node, spec: SelectorSpec, base_url: str | None) -> str | None:
    if node is None:
        return None
    if spec.attribute:
        value = node.attributes.get(spec.attribute)
        if value is None:
            return None
        return _normalize_attribute(value, spec.attribute, base_url)
    return node.text(strip=True)


def _extract_raw_parsel(node, spec: SelectorSpec, base_url: str | None) -> str | None:
    if node is None:
        return None
    if spec.attribute:
        value = node.attrib.get(spec.attribute)
        if value is None:
            return None
        return _normalize_attribute(value, spec.attribute, base_url)
    value = node.xpath("string(.)").get()
    if value is None:
        return None
    return value.strip()


def _normalize_attribute(value: str, attribute: str, base_url: str | None) -> str:
    if not base_url:
        return value
    cleaned = value.strip()
    if not cleaned:
        return value
    if cleaned.startswith(("#", "javascript:", "mailto:", "tel:")):
        return value
    if attribute in {"href", "src", "data-href", "data-url", "data-src"} or cleaned.startswith(
        ("/", "http://", "https://", "//")
    ):
        return urljoin(base_url, cleaned)
    return value


def _normalize_value(value: object, data_type: str) -> object:
    if data_type == "string":
        return value if isinstance(value, str) else str(value)
    if isinstance(value, str):
        return coerce_value(value, data_type)
    if data_type == "int":
        if isinstance(value, bool):
            raise ValueError("bool is not int")
        return int(value)
    if data_type == "float":
        if isinstance(value, bool):
            raise ValueError("bool is not float")
        return float(value)
    if data_type == "bool":
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value != 0
        raise ValueError("invalid bool")
    return value


def _requires_parsel(selectors: list[SelectorSpec]) -> bool:
    for spec in selectors:
        if spec.selector.startswith("xpath:"):
            return True
        if spec.item_selector and spec.item_selector.startswith("xpath:"):
            return True
    return False


def _split_selector(selector: str) -> tuple[str, str]:
    if selector.startswith("xpath:"):
        return "xpath", selector[len("xpath:") :]
    if selector.startswith("css:"):
        return "css", selector[len("css:") :]
    return "css", selector


def _strip_css_prefix(selector: str) -> str:
    if selector.startswith("css:"):
        return selector[len("css:") :]
    return selector


def _select_first(node, engine: str, selector: str):
    results = _select_all(node, engine, selector)
    return results[0] if results else None


def _select_all(node, engine: str, selector: str):
    if engine == "xpath":
        return node.xpath(selector)
    return node.css(selector)
