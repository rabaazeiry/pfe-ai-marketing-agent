"""Turns RawPost into NormalizedPost. Drops noise-only content."""

from __future__ import annotations

from typing import Optional

from core.cleaner import is_noise, strip_html
from core.types import NormalizedPost, RawPost


def normalize(raw: RawPost) -> Optional[NormalizedPost]:
    """Return a NormalizedPost, or None when the raw post is noise.

    Full extraction per platform is delegated to methods; this function only
    produces the canonical shape consumers (mappers, dedupe) expect.
    """
    text = strip_html(raw) if raw.raw_html else (raw.raw_json or {}).get("text", "")
    if is_noise(text):
        return None

    data = raw.raw_json or {}
    return NormalizedPost(
        external_id=str(data.get("id") or raw.source_url),
        platform=raw.platform,
        url=raw.source_url,
        author_handle=data.get("author"),
        text=text,
        published_at=data.get("published_at"),
        likes=int(data.get("likes", 0)),
        comments=int(data.get("comments", 0)),
        shares=int(data.get("shares", 0)),
        media_urls=data.get("media", []) or [],
        language=data.get("language"),
    )
