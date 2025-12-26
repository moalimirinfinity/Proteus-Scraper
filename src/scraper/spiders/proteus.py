from __future__ import annotations

import uuid

from scrapy import Request, Spider
from scrapy.exceptions import CloseSpider
from sqlalchemy import select

from core.db_sync import get_sync_session
from core.models import Job, Selector
from scraper.parsing import SelectorSpec, parse_html


class ProteusSpider(Spider):
    name = "proteus"

    def __init__(self, job_id: str, url: str, schema_id: str, **kwargs):
        super().__init__(**kwargs)
        self.job_id = job_id
        self.start_url = url
        self.schema_id = schema_id
        self.selectors = self._load_selectors()
        if not self.selectors:
            self._mark_job_failed("no_selectors")
            raise CloseSpider("no_selectors")

    async def start(self):
        yield Request(self.start_url, callback=self.parse, meta={"job_id": self.job_id})

    def parse(self, response):
        data, errors = parse_html(response.text, self.selectors)
        yield {
            "job_id": self.job_id,
            "url": response.url,
            "html": response.text,
            "data": data,
            "errors": errors,
        }

    def _load_selectors(self) -> list[SelectorSpec]:
        with get_sync_session() as session:
            result = session.execute(
                select(Selector)
                .where(Selector.schema_id == self.schema_id)
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

    def _mark_job_failed(self, reason: str) -> None:
        with get_sync_session() as session:
            job_uuid = uuid.UUID(self.job_id)
            result = session.execute(select(Job).where(Job.id == job_uuid))
            job = result.scalar_one_or_none()
            if job is None:
                return
            job.state = "failed"
            job.error = reason
