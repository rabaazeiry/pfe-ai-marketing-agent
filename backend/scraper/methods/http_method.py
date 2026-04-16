"""Plain HTTP scraping method (priority 2).

Uses httpx + BeautifulSoup to fetch and parse public pages. Faster and
lighter than the browser-based brute method, used when no official API
is available.
"""

from __future__ import annotations

from typing import Iterable

from core.types import RawPost, ScrapeJob
from methods.base import ScrapingMethod


class HttpMethod(ScrapingMethod):
    name = "http"
    priority = 2

    def supports(self, job: ScrapeJob) -> bool:
        return job.target.startswith("http://") or job.target.startswith("https://")

    async def run(self, job: ScrapeJob) -> Iterable[RawPost]:
        # TODO: fetch job.target with httpx, wrap the response body in RawPost.
        return []
