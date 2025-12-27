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
    schema_id = "example"
    selectors = [
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
    ]

    created_schema = False
    created_selectors = 0

    with get_sync_session() as session:
        schema = session.execute(select(Schema).where(Schema.id == schema_id)).scalar_one_or_none()
        if schema is None:
            schema = Schema(
                id=schema_id,
                name="Example",
                description="Sample schema for https://example.com",
            )
            session.add(schema)
            created_schema = True

        for selector in selectors:
            existing = session.execute(
                select(Selector)
                .where(Selector.schema_id == schema_id)
                .where(Selector.field == selector["field"])
                .where(Selector.selector == selector["selector"])
            ).scalar_one_or_none()
            if existing is not None:
                continue
            session.add(Selector(schema_id=schema_id, **selector))
            created_selectors += 1

    print(
        f"Seeded schema '{schema_id}' (new={created_schema}) and {created_selectors} selectors."
    )


if __name__ == "__main__":
    main()
