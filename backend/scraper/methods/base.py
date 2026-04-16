"""Abstract base class shared by every scraping method."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterable

from core.types import MethodName, RawPost, ScrapeJob


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
