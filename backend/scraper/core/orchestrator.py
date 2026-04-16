"""Intelligent method selector: API → HTTP → brute with fallback."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from core.dedupe import dedupe
from core.normalizer import normalize
from core.types import MethodName, NormalizedPost, ScrapeJob
from methods.api_method import ApiMethod
from methods.base import ScrapingMethod
from methods.brute_method import BruteMethod
from methods.http_method import HttpMethod

log = logging.getLogger("orchestrator")


@dataclass
class OrchestratorResult:
    """Outcome of a single orchestrated scrape."""

    method_used: Optional[MethodName]  # "api" | "http" | "brute" | None
    posts: list[NormalizedPost]


class Orchestrator:
    """Chooses the best scraping method per job.

    Priority order is enforced by each method's `priority` attribute:
    API (1) → HTTP (2) → brute (3). Falls back to the next method whenever
    the current one raises or yields nothing.
    """

    def __init__(self, methods: Optional[list[ScrapingMethod]] = None) -> None:
        self.methods = sorted(
            methods or [ApiMethod(), HttpMethod(), BruteMethod()],
            key=lambda m: m.priority,
        )

    def _pick_chain(self, job: ScrapeJob) -> list[ScrapingMethod]:
        if job.force_method:
            return [m for m in self.methods if m.name == job.force_method]
        return [m for m in self.methods if m.supports(job)]

    async def run(self, job: ScrapeJob) -> OrchestratorResult:
        chain = self._pick_chain(job)
        if not chain:
            log.warning("No method supports job %s", job)
            return OrchestratorResult(method_used=None, posts=[])

        for method in chain:
            try:
                raws = await method.run(job)
            except Exception as exc:  # noqa: BLE001
                log.warning("method=%s failed: %s", method.name, exc)
                continue
            normalized = [n for n in (normalize(r) for r in raws) if n]
            if normalized:
                log.info("method=%s ok count=%d", method.name, len(normalized))
                return OrchestratorResult(
                    method_used=method.name,
                    posts=dedupe(normalized),
                )

        return OrchestratorResult(method_used=None, posts=[])
