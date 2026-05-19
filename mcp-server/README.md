# pfe-mcp-server — MCP layer for the marketing agent

A small, **parallel** MCP (Model Context Protocol) server. It exposes a few
pipeline capabilities as MCP tools an AI client (Claude Desktop / Claude Code)
can call. It does **not** contain business logic and does **not** modify the
backend — every tool is a thin authenticated HTTP call into the existing API,
exactly like the n8n orchestration layer.

## Tools

| Tool | Input | Backend call | Returns |
|---|---|---|---|
| `create_project` | `businessIdea` (≥10 chars), `marketCategory` (≥2), `targetCountry` (optional, default `Tunisie`) | `POST /api/projects` | project id, name, AI-detected industry, pipeline status |
| `get_insights` | `industry` (`hotels`\|`restaurants`\|`beauty`\|`fashion`\|`patisserie`) | `GET /api/insights/:industry` | Step-4 insights JSON (or a clear "not generated yet" message) |
| `get_campaign` | `industry` (same enum) | `GET /api/campaign/:industry` | Step-5 campaign JSON (or "not generated yet") |

## Architecture

```
Claude (MCP client)  --stdio-->  mcp-server (this)  --HTTP+JWT-->  existing backend (:5000)
```

- **SDK:** `@modelcontextprotocol/sdk` + `zod` (2 runtime deps). Plain ESM JS, no build step.
- **Transport:** stdio — the client launches this process; stdout is the JSON-RPC
  channel, so all logs go to **stderr** only.
- **Auth:** logs in via `POST /api/auth/login`, caches the JWT in memory,
  re-logs in once on a 401. Credentials come from env vars — never hardcoded in source.

## Prerequisites

- The backend running on `:5000` (`cd backend && npm run dev`).
- An existing app account (any active user — admin not required).
- Node ≥ 22 (uses the built-in `--env-file-if-exists` flag; no `dotenv` dependency).

## Install & configure

```bash
cd mcp-server
npm install
cp .env.example .env      # then edit credentials in .env
```

## Run standalone

```bash
npm start
# stderr: "[pfe-mcp] server connected over stdio — 3 tools registered"
```

It then waits for an MCP client on stdio (this is expected — it is not an HTTP server).

## Test with the MCP Inspector

Interactive UI:

```bash
npm run inspect          # opens the Inspector; explore + call the 3 tools
```

Non-interactive smoke test (CLI mode):

```bash
npx @modelcontextprotocol/inspector --cli node src/index.js --method tools/list
npx @modelcontextprotocol/inspector --cli node src/index.js \
  --method tools/call --tool-name get_insights \
  --tool-arg industry=hotels
```

## Register with Claude

**Claude Code (this repo):** the root `.mcp.json` already registers it as
`pfe-marketing-agent`. Open the project in Claude Code and approve the server
when prompted. (`.mcp.json` carries a local **test** credential for convenience
— do not commit real credentials; use a throwaway account or override via env.)

**Claude Desktop:** add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "pfe-marketing-agent": {
      "command": "node",
      "args": ["C:\\Users\\Client\\Desktop\\pfe_marketing_agent11\\mcp-server\\src\\index.js"],
      "env": {
        "BACKEND_URL": "http://localhost:5000/api",
        "MCP_BACKEND_EMAIL": "you@example.com",
        "MCP_BACKEND_PASSWORD": "your-password"
      }
    }
  }
}
```

## Honest scope / caveats

- **Minimal by design.** It exposes the *fast, clean* capabilities only:
  create a project + read the Step-4/5 artifacts.
- **It does not run the full pipeline.** Scraping is fire-and-forget and
  regeneration is 10–15 min; a synchronous "run everything" tool would be
  fragile. Use the n8n workflow for end-to-end orchestration; this layer is a
  focused MCP demonstration.
- **`get_insights` / `get_campaign` are industry-scoped, not project-scoped** —
  the same architectural reality flagged for n8n. `create_project` returns the
  detected industry to bridge the two.
- No backend code is modified. The only files outside `mcp-server/` are the
  additive root `.mcp.json`.
