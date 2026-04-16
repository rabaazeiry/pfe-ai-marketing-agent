"""Pydantic schemas used by the /v2/scrape route shared with the Node backend."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class OrchestratedScrapeRequest(BaseModel):
    """Request body posted by the Node backend to /v2/scrape."""

    project_id: str
    competitor_id: str
    platform: Literal["instagram", "facebook", "linkedin", "tiktok", "web"]
    target: str = Field(..., description="URL or handle to scrape")
    force_method: Optional[Literal["api", "http", "brute"]] = None


class OrchestratedScrapeResponse(BaseModel):
    """Response returned to the Node backend after one orchestrated scrape."""

    competitor_id: str
    method_used: Optional[Literal["api", "http", "brute"]]
    posts_count: int
    social_analysis: dict  # mapper output — shape matches SocialAnalysis model
    competitor_update: dict  # mapper output — shape matches Competitor.socialMedia
