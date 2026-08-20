// geocoding.js
// Abstracted city search. The backend proxies OpenStreetMap Nominatim
// (GET /api/search) so the browser never talks to the provider directly —
// provider internals (endpoint, query format) stay server-side. The provider
// interface is isolated so another service can be substituted without
// touching the UI.
//
// Good-citizen behaviour for the shared geocoder:
//   - debounced requests (no request per keystroke)
//   - minimum query length (2 chars)
//   - AbortController cancellation (stale results are never shown)
//   - a bounded in-memory cache (recent queries served instantly)
//   - result limit + graceful errors

import { API_BASE } from './backendClient';

const MIN_QUERY_LENGTH = 2;
const DEBOUNCE_MS = 400;
const RESULT_LIMIT = 6;
const CACHE_MAX = 100;

const cache = new Map();
let debounceTimer = null;
let activeController = null;

/**
 * Resolve a place query to locations via the backend search proxy.
 * Returns a promise of an array of
 * { id, name, shortName, lat, lng, type, boundingBox }.
 * Never throws — failures resolve to [] (callers show a graceful
 * "search unavailable" state).
 */
export function searchPlaces(query) {
  return new Promise((resolve) => {
    const q = String(query || '').trim();
    if (debounceTimer) clearTimeout(debounceTimer);
    if (activeController) activeController.abort();

    if (q.length < MIN_QUERY_LENGTH) {
      resolve([]);
      return;
    }

    if (cache.has(q)) {
      resolve(cache.get(q));
      return;
    }

    debounceTimer = setTimeout(() => {
      activeController = new AbortController();
      const params = new URLSearchParams({ q, limit: String(RESULT_LIMIT) });
      fetch(`${API_BASE}/search?${params.toString()}`, {
        signal: activeController.signal
      })
        .then((res) => {
          if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
          return res.json();
        })
        .then((body) => {
          if (body.status !== 'available') throw new Error(body.reason || 'search unavailable');
          const places = (body.results || []).map((r) => ({
            id: r.id,
            name: r.name,
            shortName: r.short_name || r.name,
            lat: Number(r.lat),
            lng: Number(r.lng),
            type: r.type || 'place',
            boundingBox: r.bounding_box
              ? [[Number(r.bounding_box[0][0]), Number(r.bounding_box[0][1])],
                [Number(r.bounding_box[1][0]), Number(r.bounding_box[1][1])]]
              : null
          }));
          if (cache.size >= CACHE_MAX) cache.delete(cache.keys().next().value);
          cache.set(q, places);
          resolve(places);
        })
        .catch((err) => {
          if (err.name === 'AbortError') return; // superseded query — ignore
          console.warn('[geocoding] search unavailable:', err.message);
          resolve([]);
        });
    }, DEBOUNCE_MS);
  });
}

export { MIN_QUERY_LENGTH };
