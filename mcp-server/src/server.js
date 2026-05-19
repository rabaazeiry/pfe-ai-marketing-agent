// MCP server definition: 3 minimal tools mapping to existing pipeline
// endpoints. No business logic here — every tool is a thin call into the
// backend via the shared authenticated client.

import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { z } from 'zod';
import { apiFetch } from './backend.js';

// Steps 4 & 5 artifacts are industry-scoped (not project-scoped) — same
// architectural reality as the n8n layer. These are the supported values
// (backend: insights.controller.js / campaign.controller.js).
const INDUSTRIES = ['hotels', 'restaurants', 'beauty', 'fashion', 'patisserie'];

const text = (value) => ({
  content: [
    { type: 'text', text: typeof value === 'string' ? value : JSON.stringify(value, null, 2) },
  ],
});
const fail = (message) => ({
  content: [{ type: 'text', text: `❌ ${message}` }],
  isError: true,
});

export function buildServer() {
  const server = new McpServer({ name: 'pfe-marketing-agent', version: '0.1.0' });

  // ── Tool 1 — create a project (pipeline Step 1) ──────────────────────────
  server.tool(
    'create_project',
    'Create a new marketing-analysis project from a business idea (pipeline Step 1). ' +
      'Returns the project id and the AI-detected industry. Does NOT run the rest of ' +
      'the pipeline (discovery/scraping/insights/campaign).',
    {
      businessIdea: z.string().min(10).describe('The business idea — at least 10 characters.'),
      marketCategory: z
        .string()
        .min(2)
        .describe('Industry / market category, e.g. "Hotels", "Fashion", "Patisserie".'),
      targetCountry: z
        .string()
        .optional()
        .describe('Target country. Defaults to "Tunisie" when omitted.'),
    },
    async ({ businessIdea, marketCategory, targetCountry }) => {
      const { ok, status, json } = await apiFetch('/projects', {
        method: 'POST',
        body: { businessIdea, marketCategory, targetCountry: targetCountry || 'Tunisie' },
      });
      if (!ok) return fail(`create_project failed (${status}): ${json.message || 'unknown error'}`);
      const p = (json && json.data && json.data.project) || {};
      return text({
        projectId: p._id,
        name: p.name,
        detectedIndustry: p.industry,
        marketCategory: p.marketCategory,
        country: p.country,
        pipelineStatus: p.pipelineStatus,
      });
    }
  );

  // ── Tool 2 — get insights for an industry (pipeline Step 4) ──────────────
  server.tool(
    'get_insights',
    'Get the AI marketing insights (pipeline Step 4) for one of the supported ' +
      'industries. Industry-scoped artifact, not project-scoped.',
    {
      industry: z
        .enum(INDUSTRIES)
        .describe(`One of: ${INDUSTRIES.join(', ')}.`),
    },
    async ({ industry }) => {
      const { ok, status, json } = await apiFetch(`/insights/${industry}`);
      if (status === 404) {
        return fail(
          `No insights generated yet for "${industry}". Generate them first ` +
            `(Step 4 / the n8n workflow in "full" mode).`
        );
      }
      if (!ok) return fail(`get_insights failed (${status}): ${json.message || 'unknown error'}`);
      return text(json.data ?? json);
    }
  );

  // ── Tool 3 — get the campaign for an industry (pipeline Step 5) ──────────
  server.tool(
    'get_campaign',
    'Get the generated content campaign / calendar (pipeline Step 5) for one of ' +
      'the supported industries. Industry-scoped artifact.',
    {
      industry: z
        .enum(INDUSTRIES)
        .describe(`One of: ${INDUSTRIES.join(', ')}.`),
    },
    async ({ industry }) => {
      const { ok, status, json } = await apiFetch(`/campaign/${industry}`);
      if (status === 404) {
        return fail(
          `No campaign generated yet for "${industry}". Generate it first ` +
            `(Step 5 / the n8n workflow in "full" mode).`
        );
      }
      if (!ok) return fail(`get_campaign failed (${status}): ${json.message || 'unknown error'}`);
      return text(json.data ?? json);
    }
  );

  return server;
}
