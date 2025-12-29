from __future__ import annotations

import json
from pathlib import Path

import pytest

from scraper.parsing import SelectorSpec, parse_html

BASE_DIR = Path(__file__).resolve().parents[1]
JSON_DIR = BASE_DIR / "fixtures" / "json"


def _load_expected(name: str) -> dict:
    return json.loads((JSON_DIR / name).read_text(encoding="utf-8"))


@pytest.mark.asyncio
async def test_parse_product_fixture(mock_client) -> None:
    response = await mock_client.get("/product")
    response.raise_for_status()
    selectors = [
        SelectorSpec(field="title", selector="h1.title", data_type="string", required=True),
        SelectorSpec(field="price", selector=".price", data_type="float", required=True),
        SelectorSpec(
            field="buy_url",
            selector="a.buy",
            attribute="href",
            data_type="string",
            required=True,
        ),
        SelectorSpec(
            field="sku",
            selector=".sku",
            attribute="data-sku",
            data_type="string",
            required=False,
        ),
    ]
    data, errors = parse_html(response.text, selectors, base_url=str(response.url))
    assert errors == []
    assert data == _load_expected("product.json")


@pytest.mark.asyncio
async def test_parse_list_fixture(mock_client) -> None:
    response = await mock_client.get("/list")
    response.raise_for_status()
    selectors = [
        SelectorSpec(
            field="name",
            selector=".item-link",
            data_type="string",
            required=True,
            group_name="items",
            item_selector=".card",
        ),
        SelectorSpec(
            field="url",
            selector=".item-link",
            attribute="href",
            data_type="string",
            required=True,
            group_name="items",
            item_selector=".card",
        ),
        SelectorSpec(
            field="price",
            selector=".price",
            data_type="float",
            required=True,
            group_name="items",
            item_selector=".card",
        ),
    ]
    data, errors = parse_html(response.text, selectors, base_url=str(response.url))
    assert errors == []
    assert data == _load_expected("list.json")
