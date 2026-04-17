"""Abstract base class shared by every scraping method."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterable

import httpx
import structlog
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from core.types import MethodName, RawPost, ScrapeJob

log = structlog.get_logger(__name__)


class ScrapingMethod(ABC):
    """Contract every concrete method must implement.

    Attributes:
        name:     machine-readable identifier ("api" | "http" | "brute").
        priority: lower is preferred. Used by the orchestrator to order methods.
    """

    name: MethodName
    priority: int

    @abstractmethod
    def supports(self, job: ScrapeJob) -> bool:
        """Return True when this method can attempt the given job."""

    @abstractmethod
    async def run(self, job: ScrapeJob) -> Iterable[RawPost]:
        """Execute the scraping strategy and yield RawPost objects."""

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException)),
        reraise=True,
    )
    async def _fetch(self, url: str) -> str:
        """Fetch a URL with automatic retry on transient HTTP errors."""
        log.info("fetching", url=url, method=self.name)
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(url)
            response.raise_for_status()
            return response.text
