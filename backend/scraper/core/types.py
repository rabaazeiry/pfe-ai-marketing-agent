"""Shared dataclasses and type aliases used across the scraper subpackages."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Optional

Platform = Literal["instagram", "facebook", "linkedin", "tiktok", "web"]
MethodName = Literal["api", "http", "brute"]


@dataclass
class ScrapeJob:
    """One scraping job requested by the Node backend."""

    project_id: str
    competitor_id: str
    platform: Platform
    target: str  # URL or handle
    force_method: Optional[MethodName] = None


@dataclass
class RawPost:
    """Unprocessed output of a scraping method before cleaning/normalization."""

    source_url: str
    platform: Platform
    raw_html: Optional[str] = None
    raw_json: Optional[dict] = None
    fetched_at: datetime = field(default_factory=datetime.utcnow)
    method: MethodName = "http"


@dataclass
class NormalizedPost:
    """Canonical post representation used by mappers and dedupe."""

    external_id: str
    platform: Platform
    url: str
    author_handle: Optional[str]
    text: str
    published_at: Optional[datetime]
    likes: int = 0
    comments: int = 0
    shares: int = 0
    media_urls: list[str] = field(default_factory=list)
    language: Optional[str] = None
