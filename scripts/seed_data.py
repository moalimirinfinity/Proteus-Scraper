#!/usr/bin/env python3
"""Seed example schema + selectors for local development."""

from __future__ import annotations

import os
import sys

from sqlalchemy import select

CURRENT_DIR = os.path.dirname(__file__)
PROJECT_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, ".."))
SRC_ROOT = os.path.join(PROJECT_ROOT, "src")
if SRC_ROOT not in sys.path:
    sys.path.append(SRC_ROOT)

from core.db_sync import get_sync_session
from core.models import Schema, Selector


def main() -> None:
    schema_defs = [
        {
            "schema_id": "example",
            "name": "Example",
            "description": "Sample schema for https://example.com",
            "selectors": [
                {
                    "field": "title",
                    "selector": "h1",
                    "data_type": "string",
                    "required": True,
                    "active": True,
                },
                {
                    "field": "summary",
                    "selector": "p",
                    "data_type": "string",
                    "required": False,
                    "active": True,
                },
            ],
        },
        {
            "schema_id": "divar_real_estate",
            "name": "Divar Real Estate List",
            "description": "Reference list schema for https://divar.ir/s/tehran/real-estate",
            "selectors": [
                {
                    "group_name": "items",
                    "item_selector": "article.kt-post-card",
                    "field": "title",
                    "selector": "h2.kt-post-card__title",
                    "data_type": "string",
                    "required": True,
                    "active": True,
                },
                {
                    "group_name": "items",
                    "item_selector": "article.kt-post-card",
                    "field": "url",
                    "selector": "a.kt-post-card__action",
                    "attribute": "href",
                    "data_type": "string",
                    "required": False,
                    "active": True,
                },
                {
                    "group_name": "items",
                    "item_selector": "article.kt-post-card",
                    "field": "price_primary",
                    "selector": ".kt-post-card__description:nth-of-type(1)",
                    "data_type": "string",
                    "required": False,
                    "active": True,
                },
                {
                    "group_name": "items",
                    "item_selector": "article.kt-post-card",
                    "field": "price_secondary",
                    "selector": ".kt-post-card__description:nth-of-type(2)",
                    "data_type": "string",
                    "required": False,
                    "active": True,
                },
                {
                    "group_name": "items",
                    "item_selector": "article.kt-post-card",
                    "field": "location",
                    "selector": ".kt-post-card__bottom-description",
                    "data_type": "string",
                    "required": False,
                    "active": True,
                },
                {
                    "group_name": "items",
                    "item_selector": "article.kt-post-card",
                    "field": "badge",
                    "selector": ".kt-post-card__red-text",
                    "data_type": "string",
                    "required": False,
                    "active": True,
                },
            ],
        },
    ]

    created_schema = 0
    created_selectors = 0

    with get_sync_session() as session:
        for schema_def in schema_defs:
            schema_id = schema_def["schema_id"]
            schema = session.execute(
                select(Schema).where(Schema.id == schema_id)
            ).scalar_one_or_none()
            if schema is None:
                schema = Schema(
                    id=schema_id,
                    name=schema_def["name"],
                    description=schema_def.get("description"),
                )
                session.add(schema)
                created_schema += 1

            for selector in schema_def["selectors"]:
                existing = session.execute(
                    select(Selector)
                    .where(Selector.schema_id == schema_id)
                    .where(Selector.group_name == selector.get("group_name"))
                    .where(Selector.field == selector["field"])
                    .where(Selector.selector == selector["selector"])
                    .where(Selector.item_selector == selector.get("item_selector"))
                    .where(Selector.attribute == selector.get("attribute"))
                ).scalar_one_or_none()
                if existing is not None:
                    continue
                session.add(Selector(schema_id=schema_id, **selector))
                created_selectors += 1

    print(
        f"Seeded {created_schema} schemas and {created_selectors} selectors."
    )


if __name__ == "__main__":
    main()
