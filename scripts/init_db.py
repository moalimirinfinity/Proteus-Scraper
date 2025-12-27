#!/usr/bin/env python3
"""Initialize the database schema and core tables."""

from __future__ import annotations

import asyncio
import os
import sys

CURRENT_DIR = os.path.dirname(__file__)
PROJECT_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, ".."))
SRC_ROOT = os.path.join(PROJECT_ROOT, "src")
if SRC_ROOT not in sys.path:
    sys.path.append(SRC_ROOT)

from sqlalchemy import text

from core.db import engine
from core.models import Base


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(
            text("ALTER TABLE IF EXISTS selectors ADD COLUMN IF NOT EXISTS group_name VARCHAR(128)")
        )
        await conn.execute(
            text("ALTER TABLE IF EXISTS selectors ADD COLUMN IF NOT EXISTS item_selector TEXT")
        )
        await conn.execute(
            text("ALTER TABLE IF EXISTS selectors ADD COLUMN IF NOT EXISTS attribute VARCHAR(128)")
        )
        await conn.execute(
            text(
                "ALTER TABLE IF EXISTS selector_candidates "
                "ADD COLUMN IF NOT EXISTS group_name VARCHAR(128)"
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE IF EXISTS selector_candidates "
                "ADD COLUMN IF NOT EXISTS item_selector TEXT"
            )
        )
        await conn.execute(
            text(
                "ALTER TABLE IF EXISTS selector_candidates "
                "ADD COLUMN IF NOT EXISTS attribute VARCHAR(128)"
            )
        )


def main() -> None:
    asyncio.run(init_db())
    print("Database schema initialized.")


if __name__ == "__main__":
    main()
