from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass

import boto3

from core.config import settings


@dataclass(frozen=True)
class StoredArtifact:
    location: str
    checksum: str | None


class ArtifactStore:
    def __init__(self) -> None:
        self.s3_client = None
        if settings.s3_bucket and settings.s3_endpoint_url:
            self.s3_client = boto3.client(
                "s3",
                endpoint_url=settings.s3_endpoint_url,
                aws_access_key_id=settings.s3_access_key_id,
                aws_secret_access_key=settings.s3_secret_access_key,
                region_name=settings.s3_region,
            )
            self._ensure_bucket(settings.s3_bucket)

    def store_bytes(
        self,
        job_id: str,
        name: str,
        data: bytes,
        content_type: str | None = None,
    ) -> StoredArtifact:
        checksum = hashlib.sha256(data).hexdigest()
        if self.s3_client:
            key = f"jobs/{job_id}/{name}"
            extra = {"ContentType": content_type} if content_type else {}
            self.s3_client.put_object(
                Bucket=settings.s3_bucket,
                Key=key,
                Body=data,
                **extra,
            )
            return StoredArtifact(
                location=f"s3://{settings.s3_bucket}/{key}",
                checksum=checksum,
            )

        artifacts_dir = self._local_artifacts_dir()
        os.makedirs(artifacts_dir, exist_ok=True)
        path = os.path.join(artifacts_dir, f"{job_id}-{name}")
        with open(path, "wb") as handle:
            handle.write(data)
        return StoredArtifact(location=path, checksum=checksum)

    def store_text(
        self,
        job_id: str,
        name: str,
        text: str,
        content_type: str | None = "text/plain",
    ) -> StoredArtifact:
        return self.store_bytes(job_id, name, text.encode("utf-8"), content_type=content_type)

    def _ensure_bucket(self, bucket: str) -> None:
        try:
            self.s3_client.head_bucket(Bucket=bucket)
        except Exception:
            self.s3_client.create_bucket(Bucket=bucket)

    @staticmethod
    def _local_artifacts_dir() -> str:
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        return os.path.join(project_root, "artifacts")
