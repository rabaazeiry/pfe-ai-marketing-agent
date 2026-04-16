"""Fingerprint-based deduplication across scraping methods."""

from __future__ import annotations

import hashlib
from typing import Iterable

from core.types import NormalizedPost


def _fingerprint(p: NormalizedPost) -> str:
    key = f"{p.platform}|{p.external_id or p.url}|{p.text[:120]}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()


def dedupe(posts: Iterable[NormalizedPost]) -> list[NormalizedPost]:
    """Return posts with duplicate fingerprints removed, preserving order."""
    seen: set[str] = set()
    out: list[NormalizedPost] = []
    for p in posts:
        fp = _fingerprint(p)
        if fp in seen:
            continue
        seen.add(fp)
        out.append(p)
    return out
