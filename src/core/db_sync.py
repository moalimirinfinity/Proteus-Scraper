from __future__ import annotations

from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from core.config import settings


def _sync_database_url() -> str:
    url = settings.database_url
    if url.startswith("postgresql+asyncpg"):
        return url.replace("postgresql+asyncpg", "postgresql+psycopg2", 1)
    return url


engine = create_engine(_sync_database_url(), pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


@contextmanager
def get_sync_session() -> Session:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
