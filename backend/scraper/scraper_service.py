"""FastAPI scraping microservice.

Runs independently of the Node backend and is reachable at http://scraper:8000
inside docker-compose, or http://localhost:8000 during local dev.

Launch:
    uv run uvicorn scraper_service:app --reload --port 8000

Heavy browser-automation deps (Playwright + Crawl4AI) are opt-in:
    uv sync --extra browser
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any

import httpx
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from adapters.node_contract import (
    OrchestratedScrapeRequest,
    OrchestratedScrapeResponse,
)
from core.orchestrator import Orchestrator
from core.types import ScrapeJob
from mappers.competitor_mapper import to_social_handle_updates
from mappers.social_analysis_mapper import to_social_analysis_payload

load_dotenv()

APP_NAME = "pfe-scraper"
APP_VERSION = "0.1.0"
USE_BROWSER = os.getenv("SCRAPER_USE_BROWSER", "false").lower() in {"1", "true", "yes"}

app = FastAPI(title=APP_NAME, version=APP_VERSION)
orchestrator = Orchestrator()


# ─── Models ──────────────────────────────────────────────────────────────────

class ScrapeRequest(BaseModel):
    url: str = Field(..., description="Fully-qualified URL to fetch")
    selectors: dict[str, str] | None = Field(
        default=None,
        description="Optional CSS selectors to extract fields keyed by name",
    )
    timeout_s: float = Field(default=15.0, ge=1.0, le=60.0)


class ScrapeResponse(BaseModel):
    url: str
    status_code: int
    title: str | None
    html_length: int
    extracted: dict[str, list[str]]
    fetched_at: str
    mode: str  # "http" or "browser"


# ─── Routes ──────────────────────────────────────────────────────────────────

@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": APP_NAME,
        "version": APP_VERSION,
        "browser_mode": USE_BROWSER,
        "time": datetime.utcnow().isoformat() + "Z",
    }


@app.post("/scrape", response_model=ScrapeResponse)
async def scrape(req: ScrapeRequest) -> ScrapeResponse:
    """Simple HTTP-first scraping: fetch the page, parse with BeautifulSoup,
    pull extracted fields with the caller's CSS selectors.

    Switch to headless-browser mode by setting SCRAPER_USE_BROWSER=true and
    running `uv sync --extra browser` first.
    """
    if USE_BROWSER:
        html, status = await _fetch_with_browser(req.url, req.timeout_s)
        mode = "browser"
    else:
        html, status = await _fetch_with_httpx(req.url, req.timeout_s)
        mode = "http"

    soup = BeautifulSoup(html, "lxml")
    title = soup.title.string.strip() if soup.title and soup.title.string else None

    extracted: dict[str, list[str]] = {}
    if req.selectors:
        for key, sel in req.selectors.items():
            nodes = soup.select(sel)
            extracted[key] = [n.get_text(strip=True) for n in nodes]

    return ScrapeResponse(
        url=req.url,
        status_code=status,
        title=title,
        html_length=len(html),
        extracted=extracted,
        fetched_at=datetime.utcnow().isoformat() + "Z",
        mode=mode,
    )


# ─── Sprint 10: orchestrated scrape ──────────────────────────────────────────

@app.post("/v2/scrape", response_model=OrchestratedScrapeResponse)
async def scrape_v2(req: OrchestratedScrapeRequest) -> OrchestratedScrapeResponse:
    """Orchestrated scrape: picks the best method (API → HTTP → brute),
    cleans and normalizes the output, and returns payloads shaped for the
    existing Competitor and SocialAnalysis models. No Mongo writes happen
    here — the Node backend persists the response.
    """
    job = ScrapeJob(
        project_id=req.project_id,
        competitor_id=req.competitor_id,
        platform=req.platform,
        target=req.target,
        force_method=req.force_method,
    )
    result = await orchestrator.run(job)
    return OrchestratedScrapeResponse(
        competitor_id=req.competitor_id,
        method_used=result.method_used,
        posts_count=len(result.posts),
        social_analysis=to_social_analysis_payload(req.competitor_id, result.posts),
        competitor_update=to_social_handle_updates(result.posts),
    )


# ─── Fetchers ────────────────────────────────────────────────────────────────

async def _fetch_with_httpx(url: str, timeout: float) -> tuple[str, int]:
    try:
        async with httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": "pfe-scraper/0.1 (+https://localhost)"},
        ) as client:
            r = await client.get(url)
            return r.text, r.status_code
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"fetch failed: {exc}") from exc


async def _fetch_with_browser(url: str, timeout: float) -> tuple[str, int]:
    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:
        raise HTTPException(
            status_code=500,
            detail="Browser mode requested but Playwright is not installed. "
                   "Run: uv sync --extra browser && uv run playwright install chromium",
        ) from exc

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            resp = await page.goto(url, timeout=int(timeout * 1000), wait_until="domcontentloaded")
            html = await page.content()
            status = resp.status if resp else 0
            return html, status
        finally:
            await browser.close()


# ─── Entry point for `python -m scraper_service` ─────────────────────────────

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "scraper_service:app",
        host=os.getenv("SCRAPER_HOST", "0.0.0.0"),
        port=int(os.getenv("SCRAPER_PORT", "8000")),
        reload=os.getenv("SCRAPER_RELOAD", "true").lower() == "true",
    )
