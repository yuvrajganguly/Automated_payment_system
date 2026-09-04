"""Document store — where rider KYC files live.

Two backends behind one tiny interface (``put`` / ``get`` / ``delete``):

* **Local disk** (default): ``PAYOUT_DOCS_DIR`` (defaults to ``data/documents``
  under the project root; the Docker image mounts a volume there). Included
  in the nightly backup alongside the database.
* **S3-compatible bucket** (Cloudflare R2, AWS S3, MinIO…): set
  ``PAYOUT_DOCS_S3_BUCKET`` and, for anything but AWS, ``PAYOUT_DOCS_S3_ENDPOINT``;
  credentials come from the usual ``AWS_ACCESS_KEY_ID`` / ``AWS_SECRET_ACCESS_KEY``
  (or ``PAYOUT_DOCS_S3_KEY`` / ``PAYOUT_DOCS_S3_SECRET``). Needs ``boto3``
  (``pip install .[docs]``). R2's free tier (10 GB) is more than this fleet
  will ever upload, so the switch costs nothing but the bucket.

Keys are ``persons/<person_id>/<uuid>.<ext>`` — opaque, never the uploaded
filename, so a name like ``../../etc/passwd`` can't do anything.
"""

from __future__ import annotations

import contextlib
import os
import re
import uuid
from pathlib import Path

from payout.config import PROJECT_ROOT

# What a recruiter may upload. Images and PDFs only — no archives, no office
# files (macro risk), no arbitrary binaries.
ALLOWED_CONTENT_TYPES: dict[str, str] = {
    "application/pdf": "pdf",
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
}
MAX_DOCUMENT_BYTES: int = int(os.environ.get("PAYOUT_DOCS_MAX_MB", "15")) * 1024 * 1024

DOC_TYPES: tuple[str, ...] = (
    "aadhaar",
    "pan",
    "driving_licence",
    "bank_proof",
    "photo",
    "agreement",
    "other",
)

_SAFE_KEY = re.compile(r"^persons/\d+/[0-9a-f]{32}\.[a-z0-9]{1,5}$")


def make_key(person_id: int, content_type: str) -> str:
    ext = ALLOWED_CONTENT_TYPES[content_type]
    return f"persons/{int(person_id)}/{uuid.uuid4().hex}.{ext}"


class LocalStorage:
    """Files under one directory, mirroring the key path."""

    name = "local"

    def __init__(self, root: Path):
        self.root = Path(root)

    def _path(self, key: str) -> Path:
        if not _SAFE_KEY.match(key):
            raise ValueError(f"bad storage key {key!r}")
        return self.root / key

    def put(self, key: str, data: bytes, content_type: str) -> None:  # noqa: ARG002
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + ".part")
        tmp.write_bytes(data)
        os.replace(tmp, p)

    def get(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def delete(self, key: str) -> None:
        with contextlib.suppress(FileNotFoundError):
            self._path(key).unlink()


class S3Storage:
    """Any S3-compatible bucket via boto3 (R2, S3, MinIO)."""

    name = "s3"

    def __init__(self, bucket: str, endpoint: str | None, key: str | None, secret: str | None):
        import boto3  # optional dependency

        kwargs: dict = {}
        if endpoint:
            kwargs["endpoint_url"] = endpoint
        if key and secret:
            kwargs["aws_access_key_id"] = key
            kwargs["aws_secret_access_key"] = secret
        region = os.environ.get("PAYOUT_DOCS_S3_REGION") or os.environ.get("AWS_DEFAULT_REGION")
        if region:
            kwargs["region_name"] = region
        self.bucket = bucket
        self.client = boto3.client("s3", **kwargs)

    def put(self, key: str, data: bytes, content_type: str) -> None:
        if not _SAFE_KEY.match(key):
            raise ValueError(f"bad storage key {key!r}")
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType=content_type)

    def get(self, key: str) -> bytes:
        obj = self.client.get_object(Bucket=self.bucket, Key=key)
        return obj["Body"].read()

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=key)


_store: LocalStorage | S3Storage | None = None


def get_storage() -> LocalStorage | S3Storage:
    """The configured backend, built once per process."""
    global _store
    if _store is None:
        bucket = os.environ.get("PAYOUT_DOCS_S3_BUCKET")
        if bucket:
            _store = S3Storage(
                bucket,
                os.environ.get("PAYOUT_DOCS_S3_ENDPOINT") or None,
                os.environ.get("PAYOUT_DOCS_S3_KEY") or os.environ.get("AWS_ACCESS_KEY_ID"),
                os.environ.get("PAYOUT_DOCS_S3_SECRET") or os.environ.get("AWS_SECRET_ACCESS_KEY"),
            )
        else:
            root = Path(os.environ.get("PAYOUT_DOCS_DIR") or PROJECT_ROOT / "data" / "documents")
            _store = LocalStorage(root)
    return _store


def reset_storage() -> None:
    """Tests: forget the cached backend so a changed env takes effect."""
    global _store
    _store = None


__all__ = [
    "ALLOWED_CONTENT_TYPES",
    "DOC_TYPES",
    "MAX_DOCUMENT_BYTES",
    "LocalStorage",
    "S3Storage",
    "get_storage",
    "make_key",
    "reset_storage",
]
