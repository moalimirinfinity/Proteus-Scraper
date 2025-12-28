from __future__ import annotations

import uuid
from http.cookies import SimpleCookie
from urllib.parse import urlparse

from scrapy import Request, Spider
from scrapy.exceptions import CloseSpider
from sqlalchemy import select

from core.db_sync import get_sync_session
from core.governance import extract_domain, guard_request_sync, record_failure_sync
from core.identities import (
    acquire_identity_sync,
    record_identity_failure_sync,
    store_identity_cookies_sync,
)
from core.redis_sync import get_sync_redis
from core.models import Job
from scraper.parsing import parse_html
from scraper.selector_registry import load_selectors_sync


class ProteusSpider(Spider):
    name = "proteus"

    def __init__(self, job_id: str, url: str, schema_id: str, **kwargs):
        super().__init__(**kwargs)
        self.job_id = job_id
        self.start_url = url
        self.schema_id = schema_id
        self.identity = None
        self.identity_cookies: list[dict] = []
        self.identity_headers: dict[str, str] = {}
        with get_sync_session() as session:
            job_uuid = uuid.UUID(self.job_id)
            job = session.execute(select(Job).where(Job.id == job_uuid)).scalar_one_or_none()
            if job is not None:
                self.identity = acquire_identity_sync(job.tenant)
        if self.identity:
            self.identity_cookies = list(self.identity.cookies or [])
            self.identity_headers = _identity_headers(self.identity.fingerprint)
        self.selectors = load_selectors_sync(self.schema_id)
        if not self.selectors:
            self._mark_job_failed("no_selectors")
            raise CloseSpider("no_selectors")

    async def start(self):
        redis = get_sync_redis()
        error = guard_request_sync(redis, self.start_url)
        if error:
            self._mark_job_failed(error)
            raise CloseSpider(error)
        cookies = _cookies_for_request(self.identity_cookies)
        yield Request(
            self.start_url,
            callback=self.parse,
            meta={"job_id": self.job_id},
            headers=self.identity_headers or None,
            cookies=cookies or None,
        )

    def parse(self, response):
        if response.status in {403, 429}:
            redis = get_sync_redis()
            domain = extract_domain(response.url)
            if domain:
                record_failure_sync(redis, domain, response.status)
            if self.identity:
                record_identity_failure_sync(self.identity.id, f"http_{response.status}")
            self._mark_job_failed(f"http_{response.status}")
            raise CloseSpider(f"http_{response.status}")
        if self.identity:
            updated = _merge_cookies(self.identity_cookies, response)
            if updated != self.identity_cookies:
                self.identity_cookies = updated
                store_identity_cookies_sync(self.identity.id, self.identity_cookies)
        data, errors = parse_html(response.text, self.selectors, base_url=response.url)
        yield {
            "job_id": self.job_id,
            "url": response.url,
            "html": response.text,
            "data": data,
            "errors": errors,
        }

    def _mark_job_failed(self, reason: str) -> None:
        with get_sync_session() as session:
            job_uuid = uuid.UUID(self.job_id)
            result = session.execute(select(Job).where(Job.id == job_uuid))
            job = result.scalar_one_or_none()
            if job is None:
                return
            job.state = "failed"
            job.error = reason


def _cookies_for_request(cookies: list[dict]) -> list[dict]:
    return [
        cookie
        for cookie in cookies
        if cookie.get("name") and cookie.get("value") is not None
    ]


def _merge_cookies(existing: list[dict], response) -> list[dict]:
    cookie_map = {cookie.get("name"): cookie for cookie in existing if cookie.get("name")}
    host = urlparse(response.url).hostname
    for header in response.headers.getlist("Set-Cookie"):
        if isinstance(header, bytes):
            header = header.decode("utf-8", errors="ignore")
        simple = SimpleCookie()
        simple.load(header)
        for name, morsel in simple.items():
            domain = morsel["domain"] or host
            path = morsel["path"] or "/"
            cookie = {"name": name, "value": morsel.value}
            if domain:
                cookie["domain"] = domain
            if path:
                cookie["path"] = path
            if morsel["secure"]:
                cookie["secure"] = True
            if morsel["httponly"]:
                cookie["httpOnly"] = True
            cookie_map[name] = cookie
    return list(cookie_map.values())


def _identity_headers(fingerprint: dict | None) -> dict[str, str]:
    if not fingerprint or not isinstance(fingerprint, dict):
        return {}
    headers = {}
    user_agent = fingerprint.get("user_agent")
    if user_agent:
        headers["User-Agent"] = user_agent
    extra = fingerprint.get("headers") or fingerprint.get("extra_http_headers")
    if isinstance(extra, dict):
        for key, value in extra.items():
            if key and value is not None:
                headers[str(key)] = str(value)
    return headers
