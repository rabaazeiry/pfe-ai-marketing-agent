// Entry point. Connects the MCP server over stdio — the transport Claude
// Desktop / Claude Code use to launch local MCP servers.
//
// IMPORTANT: with the stdio transport, stdout is the JSON-RPC channel.
// Never write diagnostics to stdout — use stderr (console.error) only,
// or the protocol stream gets corrupted.

import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import { buildServer } from './server.js';

async function main() {
  const server = buildServer();
  const transport = new StdioServerTransport();
  await server.connect(transport);
  console.error('[pfe-mcp] server connected over stdio — 3 tools registered');
}

main().catch((err) => {
  console.error('[pfe-mcp] fatal:', err.message);
  process.exit(1);
});
