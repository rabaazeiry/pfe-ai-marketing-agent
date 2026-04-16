"""Headless-browser ("brute") scraping method (priority 3).

Last-resort strategy for JS-heavy pages or platforms with aggressive
anti-scraping. Gated behind SCRAPER_USE_BROWSER to keep the default
install lightweight.
"""

from __future__ import annotations

import os
from typing import Iterable

from core.types import RawPost, ScrapeJob
from methods.base import ScrapingMethod


class BruteMethod(ScrapingMethod):
    name = "brute"
    priority = 3

    def supports(self, job: ScrapeJob) -> bool:
        if os.getenv("SCRAPER_USE_BROWSER", "false").lower() not in {"1", "true", "yes"}:
            return False
        return job.target.startswith("http://") or job.target.startswith("https://")

    async def run(self, job: ScrapeJob) -> Iterable[RawPost]:
        # TODO: drive Playwright (stealth) to render job.target and collect posts.
        return []
