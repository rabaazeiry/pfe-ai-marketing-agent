"""Plain HTTP scraping method (priority 2).

Sprint 11: first real implementation, scoped to Instagram only.

Strategy (no login, no browser):
  1. Fetch the public Instagram page with httpx + a real User-Agent.
  2. Parse the Open Graph metadata (og:title, og:description, og:image) that
     Instagram serves for link-preview crawlers. This is enough to prove
     the full pipeline end-to-end: method → cleaner → normalizer → dedupe → mapper.

We intentionally keep this minimal — no pagination, no JSON payload parsing,
no anti-bot tricks. Deeper scraping is planned for a later sprint.
"""

from __future__ import annotations

import logging
from typing import Iterable, Optional

import httpx
from bs4 import BeautifulSoup

from core.types import RawPost, ScrapeJob
from methods.base import ScrapingMethod

log = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


class HttpMethod(ScrapingMethod):
    name = "http"
    priority = 2

    def supports(self, job: ScrapeJob) -> bool:
        if job.platform != "instagram":
            return False
        return job.target.startswith("http://") or job.target.startswith("https://")

    async def run(self, job: ScrapeJob) -> Iterable[RawPost]:
        html = await _fetch(job.target)
        if not html:
            return []

        soup = BeautifulSoup(html, "html.parser")
        title = _og(soup, "og:title") or _page_title(soup)
        description = _og(soup, "og:description")
        image = _og(soup, "og:image")

        text = description or title
        if not text:
            log.info("instagram http: no og metadata for %s", job.target)
            return []

        handle = _extract_handle(job.target)

        post = RawPost(
            source_url=job.target,
            platform="instagram",
            raw_html=f"<p>{text}</p>",
            raw_json={
                "id": job.target,
                "author": handle,
                "text": text,
                "media": [image] if image else [],
            },
            method="http",
        )
        return [post]


# ─── helpers ────────────────────────────────────────────────────────────────


async def _fetch(url: str) -> Optional[str]:
    try:
        async with httpx.AsyncClient(
            timeout=15.0, follow_redirects=True, headers=_HEADERS
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.text
    except httpx.HTTPError as exc:
        log.warning("instagram http fetch failed for %s: %s", url, exc)
        return None


def _og(soup: BeautifulSoup, prop: str) -> Optional[str]:
    tag = soup.find("meta", attrs={"property": prop})
    if tag and tag.get("content"):
        return tag["content"].strip() or None
    return None


def _page_title(soup: BeautifulSoup) -> Optional[str]:
    if soup.title and soup.title.string:
        return soup.title.string.strip() or None
    return None


def _extract_handle(url: str) -> Optional[str]:
    """Extract the handle/slug from an Instagram URL.

    Example: https://www.instagram.com/natgeo/  →  "natgeo"
    """
    marker = "instagram.com/"
    if marker not in url:
        return None
    tail = url.split(marker, 1)[1]
    slug = tail.strip("/").split("/")[0]
    return slug or None
