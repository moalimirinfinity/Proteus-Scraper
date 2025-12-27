from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from core.config import settings
from core.db import async_session
from core.db_sync import get_sync_session
from core.models import Selector, SelectorCandidate
from scraper.parsing import SelectorSpec


def load_selectors_sync(schema_id: str) -> list[SelectorSpec]:
    with get_sync_session() as session:
        result = session.execute(
            select(Selector)
            .where(Selector.schema_id == schema_id)
            .where(Selector.active.is_(True))
        )
        return [
            SelectorSpec(
                field=row.field,
                selector=row.selector,
                data_type=row.data_type,
                required=row.required,
            )
            for row in result.scalars().all()
        ]


async def load_selectors_async(schema_id: str) -> list[SelectorSpec]:
    async with async_session() as session:
        result = await session.execute(
            select(Selector)
            .where(Selector.schema_id == schema_id)
            .where(Selector.active.is_(True))
        )
        return [
            SelectorSpec(
                field=row.field,
                selector=row.selector,
                data_type=row.data_type,
                required=row.required,
            )
            for row in result.scalars().all()
        ]


def record_candidates_sync(schema_id: str, selectors: list[SelectorSpec], candidates: dict[str, str]) -> None:
    if not candidates:
        return

    candidate_map = {spec.field: spec for spec in selectors}
    now = datetime.now(timezone.utc)

    with get_sync_session() as session:
        for field, selector in candidates.items():
            spec = candidate_map.get(field)
            if spec is None:
                continue
            existing = session.execute(
                select(SelectorCandidate)
                .where(SelectorCandidate.schema_id == schema_id)
                .where(SelectorCandidate.field == field)
                .where(SelectorCandidate.selector == selector)
                .where(SelectorCandidate.promoted_at.is_(None))
            ).scalar_one_or_none()
            if existing:
                existing.success_count += 1
                existing.updated_at = now
                continue

            session.add(
                SelectorCandidate(
                    schema_id=schema_id,
                    field=field,
                    selector=selector,
                    data_type=spec.data_type,
                    required=spec.required,
                    success_count=1,
                )
            )

        _promote_candidates_sync(session, now)


async def record_candidates_async(schema_id: str, selectors: list[SelectorSpec], candidates: dict[str, str]) -> None:
    if not candidates:
        return

    candidate_map = {spec.field: spec for spec in selectors}
    now = datetime.now(timezone.utc)

    async with async_session() as session:
        for field, selector in candidates.items():
            spec = candidate_map.get(field)
            if spec is None:
                continue
            existing = await session.execute(
                select(SelectorCandidate)
                .where(SelectorCandidate.schema_id == schema_id)
                .where(SelectorCandidate.field == field)
                .where(SelectorCandidate.selector == selector)
                .where(SelectorCandidate.promoted_at.is_(None))
            )
            row = existing.scalar_one_or_none()
            if row:
                row.success_count += 1
                row.updated_at = now
                continue

            session.add(
                SelectorCandidate(
                    schema_id=schema_id,
                    field=field,
                    selector=selector,
                    data_type=spec.data_type,
                    required=spec.required,
                    success_count=1,
                )
            )

        await _promote_candidates_async(session, now)
        await session.commit()


def _promote_candidates_sync(session, now: datetime) -> None:
    threshold = settings.selector_promotion_threshold
    result = session.execute(
        select(SelectorCandidate)
        .where(SelectorCandidate.success_count >= threshold)
        .where(SelectorCandidate.promoted_at.is_(None))
    )
    for candidate in result.scalars().all():
        existing = session.execute(
            select(Selector)
            .where(Selector.schema_id == candidate.schema_id)
            .where(Selector.field == candidate.field)
            .where(Selector.selector == candidate.selector)
            .where(Selector.active.is_(True))
        ).scalar_one_or_none()
        if existing is None:
            session.add(
                Selector(
                    schema_id=candidate.schema_id,
                    field=candidate.field,
                    selector=candidate.selector,
                    data_type=candidate.data_type,
                    required=candidate.required,
                    active=True,
                )
            )
        candidate.promoted_at = now
        candidate.updated_at = now


async def _promote_candidates_async(session, now: datetime) -> None:
    threshold = settings.selector_promotion_threshold
    result = await session.execute(
        select(SelectorCandidate)
        .where(SelectorCandidate.success_count >= threshold)
        .where(SelectorCandidate.promoted_at.is_(None))
    )
    for candidate in result.scalars().all():
        existing = await session.execute(
            select(Selector)
            .where(Selector.schema_id == candidate.schema_id)
            .where(Selector.field == candidate.field)
            .where(Selector.selector == candidate.selector)
            .where(Selector.active.is_(True))
        )
        if existing.scalar_one_or_none() is None:
            session.add(
                Selector(
                    schema_id=candidate.schema_id,
                    field=candidate.field,
                    selector=candidate.selector,
                    data_type=candidate.data_type,
                    required=candidate.required,
                    active=True,
                )
            )
        candidate.promoted_at = now
        candidate.updated_at = now
