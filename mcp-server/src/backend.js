// Thin authenticated HTTP client for the EXISTING backend.
// Mirrors the n8n layer: log in once, cache the JWT in memory,
// transparently re-log in once on a 401. Native fetch (Node >=18) —
// no extra HTTP dependency. Nothing here touches backend code.

const BASE = (process.env.BACKEND_URL || 'http://localhost:5000/api').replace(/\/$/, '');
const EMAIL = process.env.MCP_BACKEND_EMAIL;
const PASSWORD = process.env.MCP_BACKEND_PASSWORD;

let token = null;

async function login() {
  if (!EMAIL || !PASSWORD) {
    throw new Error(
      'MCP_BACKEND_EMAIL / MCP_BACKEND_PASSWORD are not set — see mcp-server/.env.example'
    );
  }
  let res;
  try {
    res = await fetch(`${BASE}/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: EMAIL, password: PASSWORD }),
    });
  } catch (e) {
    throw new Error(`Cannot reach backend at ${BASE} (is it running?): ${e.message}`);
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok || !data.token) {
    throw new Error(`Login failed (${res.status}): ${data.message || 'no token returned'}`);
  }
  token = data.token;
  return token;
}

/**
 * Authenticated request against the backend.
 * @returns {Promise<{ ok: boolean, status: number, json: any }>}
 */
export async function apiFetch(path, { method = 'GET', body } = {}) {
  if (!token) await login();

  const doRequest = () =>
    fetch(`${BASE}${path}`, {
      method,
      headers: {
        Authorization: `Bearer ${token}`,
        ...(body ? { 'Content-Type': 'application/json' } : {}),
      },
      body: body ? JSON.stringify(body) : undefined,
    });

  let res;
  try {
    res = await doRequest();
    if (res.status === 401) {
      await login(); // token expired/invalid — refresh once and retry
      res = await doRequest();
    }
  } catch (e) {
    throw new Error(`Backend request failed (${method} ${path}): ${e.message}`);
  }

  const text = await res.text();
  let json;
  try {
    json = text ? JSON.parse(text) : {};
  } catch {
    json = { raw: text };
  }
  return { ok: res.ok, status: res.status, json };
}
