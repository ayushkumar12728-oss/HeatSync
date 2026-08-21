// In development, API calls go through the Vite dev proxy (/api -> backend),
// which avoids CORS entirely. In production builds the absolute backend URL is
// used (VITE_BACKEND_API_URL, falling back to the local FastAPI default).
const DEFAULT_API_BASE = '/api';

function normalizeApiBase(rawUrl) {
  if (!rawUrl) return DEFAULT_API_BASE;

  let url = rawUrl.trim().replace(/\/+$/, '');

  if (url && !url.endsWith('/api')) {
    url = `${url}/api`;
  }

  return url;
}

export const API_BASE = normalizeApiBase(
  import.meta.env.VITE_BACKEND_API_URL
);



export async function fetchJson(path, options = {}) {
  const normalizedPath = path.startsWith('/') ? path : `/${path}`;
  const response = await fetch(`${API_BASE}${normalizedPath}`, options);
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  return response.json();
}

export async function fetchLayerGeoJson(layerName) {
  return fetchJson(`/data/layers/${layerName}`);
}

export async function fetchBoundary() {
  return fetchJson('/data/boundary');
}

export async function fetchLayerCatalogue() {
  return fetchJson('/data/layers');
}

export async function fetchModelInfo() {
  return fetchJson('/model/info');
}

export async function fetchScenarios() {
  return fetchJson('/simulation/scenarios');
}

export async function runScenario(payload) {
  return fetchJson('/simulation/run', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  });
}

export async function fetchScenarioCells(scenario, refresh = false) {
  return fetchJson(`/simulation/results/${scenario}/cells${refresh ? '?refresh=true' : ''}`);
}

export async function fetchScenarioGeoJson(scenario, refresh = false) {
  return fetchJson(`/simulation/results/${scenario}/geojson${refresh ? '?refresh=true' : ''}`);
}

export async function fetchAIStatus() {
  return fetchJson('/ai/status');
}

export async function askAI(question, context = {}) {
  return fetchJson('/ai/ask', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question, context })
  });
}

export async function fetchCurrentHeat() {
  return fetchJson('/prediction/heat/current');
}

export async function fetchCurrentHeatDebug() {
  return fetchJson('/prediction/heat/current/debug');
}

/**
 * Fetch current per-cell predicted LST predictions from /api/prediction/heat/current.
 *
 * This endpoint returns BOTH the single city-wide prediction AND the full
 * per-cell predictions array (53,802 cells).  The frontend merges the
 * per-cell predictions with static grid geometry to render the heat map.
 *
 * Normalised return shape:
 * {
 *   success: true,
 *   predictions: [ { grid_id: ..., predicted_lst: ... }, ... ],
 *   generated_at: "...",
 *   prediction_count: N,
 *   grid_summary: { mean_lst, min_lst, max_lst },
 *   ...other metadata
 * }
 */
export async function fetchCurrentHeatPredictions() {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 60000);
  try {
    const response = await fetch(`${API_BASE}/prediction/heat/current`, {
      signal: controller.signal,
    });
    if (!response.ok) {
      throw new Error(`${response.status} ${response.statusText}`);
    }
    return response.json();
  } finally {
    clearTimeout(timeoutId);
  }
}

/** @deprecated Use fetchCurrentHeatPredictions() — kept for backward compat. */
export async function fetchCurrentHeatGrid() {
  return fetchCurrentHeatPredictions();
}

export async function runCurrentScenario(payload) {
  return fetchJson('/simulation/run/current', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  });
}
