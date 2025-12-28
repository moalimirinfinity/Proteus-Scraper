from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select

from core.artifacts import ArtifactStore
from core.db_sync import get_sync_session
from core.config import settings
from core.governance import allow_llm_call_sync
from core.redis_sync import get_sync_redis
from core.models import Artifact, Job
from scraper.llm_recovery import recover_with_llm
from scraper.selector_registry import load_selectors_sync, record_candidates_sync


class StoragePipeline:
    def open_spider(self, spider):
        self.store = ArtifactStore()

    def process_item(self, item, spider):
        self._persist_item(item)
        return item

    def _persist_item(self, item):
        job_id = uuid.UUID(item["job_id"])
        html = item.get("html", "")
        data = item.get("data", {})
        errors = item.get("errors", [])

        artifact_location = None
        checksum = None
        if html:
            stored = self.store.store_text(str(job_id), "raw.html", html, content_type="text/html")
            artifact_location = stored.location
            checksum = stored.checksum

        with get_sync_session() as session:
            result = session.execute(select(Job).where(Job.id == job_id))
            job = result.scalar_one_or_none()
            if job is None:
                return item

            if errors:
                if not job.schema_id:
                    job.state = "failed"
                    job.error = "schema_missing"
                    job.result = None
                elif settings.openai_api_key:
                    selectors = load_selectors_sync(job.schema_id)
                    redis = get_sync_redis()
                    budget_allowed = allow_llm_call_sync(redis, str(job.id), job.tenant)
                    if not budget_allowed:
                        job.state = "failed"
                        job.error = "llm_budget_exceeded"
                        job.result = None
                    else:
                        llm_result = recover_with_llm(html, selectors, job.tenant)
                        if llm_result.success and llm_result.data is not None:
                            job.state = "succeeded"
                            job.error = None
                            job.result = llm_result.data
                            record_candidates_sync(job.schema_id, selectors, llm_result.selectors or {})
                        else:
                            job.state = "failed"
                            job.error = llm_result.error or "llm_failed"
                            job.result = None
                else:
                    job.state = "failed"
                    job.error = "llm_unavailable"
                    job.result = None
            else:
                job.state = "succeeded"
                job.error = None
                job.result = data

            job.updated_at = datetime.now(timezone.utc)
            if artifact_location:
                existing = session.execute(
                    select(Artifact)
                    .where(Artifact.job_id == job_id)
                    .where(Artifact.type == "html")
                ).scalars().all()
                for artifact in existing:
                    session.delete(artifact)
                artifact = Artifact(
                    job_id=job.id,
                    type="html",
                    location=artifact_location,
                    checksum=checksum,
                )
                session.add(artifact)

        return item
