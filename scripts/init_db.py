#!/usr/bin/env python3
"""Initialize the database schema using Alembic migrations."""

from __future__ import annotations

import os
from alembic import command
from alembic.config import Config

CURRENT_DIR = os.path.dirname(__file__)
PROJECT_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, ".."))


def init_db() -> None:
    alembic_cfg = Config(os.path.join(PROJECT_ROOT, "alembic.ini"))
    alembic_cfg.set_main_option(
        "script_location",
        os.path.join(PROJECT_ROOT, "migrations"),
    )
    command.upgrade(alembic_cfg, "head")


def main() -> None:
    init_db()
    print("Database schema initialized via Alembic.")


if __name__ == "__main__":
    main()
