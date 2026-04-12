# Env reference

Authoritative list of every environment variable the system reads. Grouped by owner and flagged for dev vs. prod differences.

## Resolution order

1. Shell (`export FOO=bar`) — highest priority
2. `.env.local` (gitignored) — local dev secrets
3. Defaults baked into `src/config/env.js` (backend) or compose `${VAR:-default}`

If a var isn't here, it shouldn't be referenced anywhere in the stack. CI check: `docker compose config` must succeed for both overlays without `WARN: variable not set`.

## Variables

| Variable | Consumer | Local dev | Production |
|---|---|---|---|
| `NODE_ENV` | backend · frontend build | `development` | `production` |
| `LOG_LEVEL` | backend | `info` | `info` or `warn` |
| `PORT` | backend | `5000` | `5000` |
| `FRONTEND_URL` | backend (CORS, Socket.IO origin) | `http://localhost:5173` | `https://app.example.com` |
| `MONGODB_URI` | backend | `mongodb://mongo:27017/pfe_marketing` | Atlas SRV URI |
| `JWT_SECRET` | backend | dev string | 64-byte vault-managed secret |
| `JWT_EXPIRES_IN` | backend | `24h` | `24h` |
| `SCRAPER_URL` | backend → scraper | `http://scraper:8000` | `http://scraper:8000` (internal) |
| `N8N_WEBHOOK_URL` | backend → n8n | `http://n8n:5678` | `http://n8n:5678` (internal) |
| `N8N_WEBHOOK_SECRET` | backend + n8n | `change_me` | 32-byte vault-managed |
| `GROQ_API_KEY` | backend (LLM) | real key | real key |
| `OPENAI_API_KEY` | backend (LLM) | optional | optional |
| `VALUESERP_API_KEY` | backend (search) | real key | real key |
| `SERPER_API_KEY` | backend (search fallback) | real key | real key |
| `TAVILY_API_KEY` | backend (research) | real key | real key |
| `CHROMA_API_KEY` · `CHROMA_TENANT` · `CHROMA_DATABASE` | backend (RAG) | real values | real values |
| `APIFY_API_KEY` | backend (scraping alt) | real key | real key |
| `FB_COOKIE_C_USER` · `FB_COOKIE_XS` · `FB_APP_ID` · `FB_APP_SECRET` · `FACEBOOK_EMAIL` · `FACEBOOK_PASSWORD` | backend + scraper (FB flows) | per-dev account | dedicated prod account |
| `VITE_API_URL` | frontend (build-time) | `/api` | `/api` (served by nginx) |
| `VITE_WS_URL` | frontend (build-time) | `/` | `/` |
| `BACKEND_URL` | frontend dev (Vite proxy target, compose only) | `http://backend:5000` | n/a |
| `SCRAPER_USE_BROWSER` | scraper | `false` | `false` (flip when needed) |
| `SCRAPER_HOST` · `SCRAPER_PORT` · `SCRAPER_RELOAD` | scraper | defaults | defaults |
| `N8N_BASIC_AUTH_USER` · `N8N_BASIC_AUTH_PASSWORD` | n8n | `admin` / `change_me` | vault-managed |
| `N8N_ENCRYPTION_KEY` | n8n | 64-byte generated once | vault-managed; rotate annually |
| `N8N_HOST` · `N8N_PORT` · `N8N_PROTOCOL` · `WEBHOOK_URL` | n8n | localhost/http | public hostname + https |
| `TZ` | n8n | `Africa/Tunis` | deployment tz |

## Rules

- **Never** reference a secret in `compose.yml` that isn't in `.env.example`.
- **Never** commit `.env.local` or any `.env` with real secrets.
- Rotate `JWT_SECRET`, `N8N_ENCRYPTION_KEY`, and `N8N_WEBHOOK_SECRET` at least once a year.
- In production, inject env vars via the hosting platform's secret manager (never via an `.env` file on disk).

## Generating a secret

```bash
# 64-byte base64
openssl rand -base64 64
# 32-byte hex
openssl rand -hex 32
```
