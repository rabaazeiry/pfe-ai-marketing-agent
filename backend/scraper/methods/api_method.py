"""Official-API scraping method (priority 1).

Targets platforms that expose a documented API — Facebook Graph, Instagram
Basic Display, LinkedIn, etc. Cheapest and most reliable, so the orchestrator
tries it first.
"""

from __future__ import annotations

from typing import Iterable

from core.types import RawPost, ScrapeJob
from methods.base import ScrapingMethod


class ApiMethod(ScrapingMethod):
    name = "api"
    priority = 1

    def supports(self, job: ScrapeJob) -> bool:
        # TODO: also check that required credentials are configured.
        return job.platform in {"facebook", "instagram", "linkedin"}

    async def run(self, job: ScrapeJob) -> Iterable[RawPost]:
        # TODO: call the platform's official API using credentials from env.
        # Returning no posts here makes the orchestrator fall back to HTTP.
        return []
