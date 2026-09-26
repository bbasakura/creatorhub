"""Publishing API request/response contract helpers.

This module is intentionally side-effect free so the large FastAPI entrypoint can
shed schema/serialization responsibilities without moving platform execution yet.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone

from pydantic import BaseModel, Field

from ..models import PublishTask


class PublishIn(BaseModel):
    account_id: int
    media_type: str = "images"
    title: str = ""
    desc: str = ""
    topics: str = ""
    location: str = ""
    media_paths: list[str] = []
    visibility: str = "public"
    allow_duplicate: bool = False
    youtube_category: str = "22"
    made_for_kids: bool = False
    thumbnail_path: str = ""
    collection_name: str = ""
    operation: str = "publish"
    allow_save: bool = True
    scheduled_at: str | None = None
    intent_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,100}$")


class PublishUpdate(BaseModel):
    account_id: int | None = None
    title: str | None = None
    desc: str | None = None
    topics: str | None = None
    location: str | None = None
    collection_name: str | None = None
    visibility: str | None = None
    allow_save: bool | None = None
    scheduled_at: str | None = None


def publish_dict(task: PublishTask) -> dict:
    return {
        "id": task.id,
        "platform": task.platform,
        "account_id": task.account_id,
        "media_type": task.media_type,
        "title": task.title,
        "desc": task.desc,
        "topics": task.topics,
        "location": task.location,
        "collection_name": getattr(task, "collection_name", "") or "",
        "operation": "draft" if task.platform == "wechat_mp" else task.operation,
        "platform_result_id": task.platform_result_id,
        "status": task.status,
        "result_url": task.result_url,
        "visibility": task.visibility,
        "allow_save": task.allow_save,
        "error": task.error,
        "media_count": len(json.loads(task.media_json or "[]")),
        "source_platform": task.source_platform,
        "source_content_id": task.source_content_id,
        "scheduled_at": task.scheduled_at.isoformat() + "Z" if task.scheduled_at else None,
        "created_at": task.created_at.isoformat() + "Z" if task.created_at else None,
    }


def parse_when(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        if value.endswith("Z"):
            return datetime.fromisoformat(value[:-1])
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is not None:
            return parsed.astimezone(timezone.utc).replace(tzinfo=None)
        # Existing API contract treats naive input as UTC+8 local time.
        return parsed - timedelta(hours=8)
    except Exception:
        return None


def publish_fingerprint(body: PublishIn, *, platform: str, visibility: str,
                        operation: str, scheduled_at: datetime | None) -> str:
    """Stable semantic fingerprint for direct publish intent deduplication."""
    payload = {
        "account_id": body.account_id,
        "platform": str(platform or "").strip().lower(),
        "media_type": str(body.media_type or "").strip().lower(),
        "title": body.title.strip(),
        "desc": body.desc,
        "topics": body.topics.strip(),
        "location": body.location.strip(),
        "media_paths": [str(path or "").strip().replace("\\", "/")
                        for path in body.media_paths],
        "visibility": str(visibility or "").strip().lower(),
        "operation": str(operation or "").strip().lower(),
        "allow_save": bool(body.allow_save),
        "scheduled_at": scheduled_at.isoformat(timespec="seconds") if scheduled_at else None,
        "youtube_category": body.youtube_category.strip(),
        "made_for_kids": bool(body.made_for_kids),
        "thumbnail_path": body.thumbnail_path.strip().replace("\\", "/"),
        "collection_name": body.collection_name.strip(),
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                     separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def publish_intent_key(body: PublishIn, fingerprint: str) -> str | None:
    """Return a unique DB key unless the caller explicitly allows duplicates."""
    if body.allow_duplicate:
        return None
    if body.intent_id:
        return f"publish:{body.account_id}:client:{body.intent_id}"
    return f"publish:{body.account_id}:fp:{fingerprint}"
