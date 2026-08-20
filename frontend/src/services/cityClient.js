// cityClient.js
// Client for the city-wide digital-twin endpoints added in the 3D upgrade:
// location intelligence, cooling potential, interventions,
// heat-safe routing.

import { fetchJson } from './backendClient';

// Location intelligence for any lat/lng (nearest real grid cell).
export function fetchCityPoint(lat, lng) {
  return fetchJson(`/city/point?lat=${lat}&lng=${lng}`);
}

// Model-derived intervention potential (per cell) + GeoJSON for the map.
export function fetchCoolingPotential() {
  return fetchJson('/city/cooling-potential');
}

export function fetchCoolingPotentialGeoJson() {
  return fetchJson('/city/cooling-potential/geojson');
}

// Ranked "where should we intervene?" opportunities.
export function fetchInterventions(perScenario = 5) {
  return fetchJson(`/city/interventions?per_scenario=${perScenario}`);
}

// Data-backed "why is this area hot?" factors.
export function fetchExplain(lat, lng) {
  return fetchJson(`/city/explain?lat=${lat}&lng=${lng}`);
}

// Heat-safe route — fastest vs lower-heat-exposure routing.
export function fetchHeatSafeRoute(start, end) {
  const params = [
    `start_lat=${start.lat}`,
    `start_lng=${start.lng}`,
    `end_lat=${end.lat}`,
    `end_lng=${end.lng}`
  ].join('&');
  return fetchJson(`/routing/heat-safe?${params}`);
}
