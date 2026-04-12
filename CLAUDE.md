# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

AI Marketing Intelligence Agent — analyzes a business idea, discovers competitors, scrapes their social media, and generates marketing strategies / content plans. See `designDocs/00_inception/specification.md` for the full product scope (multi-step pipeline: input → market research → scraping → AI insights → campaign generator).

Only the **backend** is currently implemented. The root-level `package.json` is a stub; all real code lives under `backend/`.

## Commands

Run everything from `backend/`:

```bash
cd backend
npm install
npm run dev      # nodemon (development)
npm start        # node server.js (production)
```

Server starts on `PORT` from `.env` (default 5000). No test runner, linter, or build step is configured.

### Python scraper microservice

`backend/scraper/` is a separate FastAPI service, managed with [uv](https://docs.astral.sh/uv/). It is not started by `npm`:

```bash
cd backend/scraper
uv sync                          # base HTTP-only deps
uv run uvicorn scraper_service:app --reload --port 8000
# optional: real browser rendering
uv sync --extra browser
uv run playwright install chromium
SCRAPER_USE_BROWSER=true uv run uvicorn scraper_service:app --reload --port 8000
```

The Node backend talks to it over `SCRAPER_URL` (default `http://localhost:8000` / `http://scraper:8000` inside compose).

### Dev launcher scripts

`scripts/dev.ps1`, `scripts/dev.bat`, `scripts/dev.sh` boot the whole dev stack (backend + frontend + scraper) with one command. See `scripts/README.md` for flags.

## Architecture

### Layered Express app
Request flow: `server.js` → `src/app.js` (CORS, JSON, morgan) → `src/routes/index.js` (mounts every feature router under `/api`) → controllers → services → Mongoose models. Global `notFound` + `errorHandler` middleware are last in the chain.

- `src/config/env.js` — single source of truth for env vars (reads via `dotenv`).
- `src/config/database.js` — forces Google DNS (8.8.8.8) before `mongoose.connect` to work around an ECONNREFUSED issue with MongoDB Atlas SRV lookups. Keep this behavior when modifying DB setup.
- `src/models/index.js` — central model registry; `require('./models')` in `app.js` ensures all schemas register on boot.

### Domain entities
`User`, `Project`, `Competitor`, `SocialAnalysis`, `Insight`, `CampaignPlan`, `Report`, `MarketResearch`. A `Project` has a `pipelineStatus` (e.g. `step3_in_progress`, `step3_complete`) that gates which stage the agent is at.

### Feature routers (under `/api`)
`auth`, `projects`, `competitors`, `market-research`, `classification`, `scraping`, plus `/api/health`. Auth uses JWT (`utils/jwt.util.js`) and bcrypt (`utils/bcrypt.util.js`); `middlewares/auth.middleware.js` protects routes.

### Services (the pipeline)
The `src/services/` directory implements the multi-step agent described in the spec:

- **Discovery & research** — `search.service.js`, `valueserp.service.js`, `discover.service.js`, `enrichment.service.js`, `extraction.service.js`, `cleaning.service.js`, `classification.service.js`, `marketResearch.service.js`.
- **Scraping** — `scraping.unified.js` is the orchestrator and iterates competitors of a project, dispatching to `scraping.instagram.complete.js` and `scraping.facebook.js` (Graph API). `apify.service.js` is an alternative backend. `scraping.cron.js` runs daily at 02:00 via `node-cron` for active projects in step 3.
- **AI / RAG** — `rag.service.js` stores short-lived (7-day TTL) articles as the `RagArticle` Mongoose model; `chroma.service.js` integrates with Chroma for vector search. LLM calls go through `groq-sdk` (`GROQ_API_KEY`).

### External services / env vars
The pipeline depends on many API keys, all loaded from `backend/.env`: `MONGODB_URI`, `JWT_SECRET`, `VALUESERP_API_KEY`, `SERPER_API_KEY`, `TAVILY_API_KEY`, `GROQ_API_KEY`, `CHROMA_API_KEY` / `CHROMA_TENANT` / `CHROMA_DATABASE`, `APIFY_API_KEY`, Facebook session cookies (`FB_COOKIE_C_USER`, `FB_COOKIE_XS`), `FB_APP_ID` / `FB_APP_SECRET`. `env.js` currently only re-exports a subset — read from `process.env` directly for the others or extend `env.js`.

### Scraping stack
Multiple scraping libs are installed side-by-side: `playwright` + `playwright-extra` + stealth, `puppeteer` + `puppeteer-extra` + stealth + adblocker, plus the Python Crawl4AI microservice. Facebook flows rely on session cookies from `.env`; Instagram uses the "complete" custom scraper. Prefer the existing service boundary (`scraping.unified.js`) when adding a new platform.

## Conventions observed in the code

- Comments, log strings, and user-facing messages are mixed French/English; match the file you're editing.
- File naming: `<feature>.<layer>.js` (e.g. `auth.controller.js`, `scraping.unified.js`).
- Controllers return `{ success, message, data }` JSON shapes; errors go through `next(err)` into `errorHandler.middleware.js`.
- `models/index.js` must be updated when adding a new Mongoose model so `require('./models')` registers it.
