// =============================================================================
// Temporal Data Service
// =============================================================================
// Client-side service for fetching historical Landsat LST data from the
// backend temporal API.  Every response is clearly labelled:
//
// - HISTORICAL OBSERVED/DERIVED LST — from Landsat Collection 2 Level-2
// - NOT live air temperature
// - NOT XGBoost model predictions
// - NOT fabricated/interpolated values
//
// Usage:
//   import { fetchTemporalDates, fetchTemporalSummary, ... } from './temporalClient';
//
// The Time Machine and historical thermal layers use these functions.
// =============================================================================

import { fetchJson } from './backendClient';

// --- Available dates -------------------------------------------------------
/**
 * Fetch available historical Landsat LST observation dates.
 * Returns ONLY actual Landsat acquisition dates — never fabricated daily dates.
 * Landsat revisits ~every 16 days, so dates are spaced accordingly.
 *
 * @returns {Promise<Object>} { status, dates[], source, metric, unit }
 */
export async function fetchTemporalDates() {
  return fetchJson('/temporal/thermal/dates');
}

// --- Time series summary ---------------------------------------------------
/**
 * Fetch the historical LST time series.
 * Each observation is a real Landsat acquisition.
 *
 * @param {Object} params - Optional filters
 * @param {string} params.startDate - Filter start date (YYYY-MM-DD)
 * @param {string} params.endDate - Filter end date (YYYY-MM-DD)
 * @returns {Promise<Object>} { status, observations[] }
 */
export async function fetchTemporalSummary(params = {}) {
  const searchParams = new URLSearchParams();
  if (params.startDate) searchParams.set('start_date', params.startDate);
  if (params.endDate) searchParams.set('end_date', params.endDate);
  const qs = searchParams.toString();
  return fetchJson(`/temporal/thermal${qs ? `?${qs}` : ''}`);
}

// --- Date-specific metadata ------------------------------------------------
/**
 * Fetch metadata for a specific historical LST observation.
 * Includes acquisition date, scene ID, cloud cover, valid pixel percentage.
 *
 * @param {string} date - Observation date (YYYY-MM-DD)
 * @returns {Promise<Object>} { status, date, scene_id, cloud_cover, mean_lst, ... }
 */
export async function fetchTemporalDateMetadata(date) {
  return fetchJson(`/temporal/thermal/${date}`);
}

// --- Date-specific grid data -----------------------------------------------
/**
 * Fetch per-cell LST data for a specific date.
 * Returns GeoJSON with the prediction grid geometry and Landsat-derived LST.
 * Cells without valid satellite data are marked as unavailable.
 *
 * @param {string} date - Observation date (YYYY-MM-DD)
 * @returns {Promise<Object>} { status, date, features: FeatureCollection }
 */
export async function fetchTemporalGrid(date) {
  return fetchJson(`/temporal/thermal/${date}/grid`);
}

// --- Date comparison -------------------------------------------------------
/**
 * Compare LST between two historical dates.
 * Returns aggregate statistics and per-cell differences.
 *
 * @param {string} dateA - First date (YYYY-MM-DD)
 * @param {string} dateB - Second date (YYYY-MM-DD)
 * @returns {Promise<Object>} { status, date_a, date_b, mean_a, mean_b, difference, ... }
 */
export async function fetchTemporalComparison(dateA, dateB) {
  return fetchJson(`/temporal/thermal/compare?date_a=${dateA}&date_b=${dateB}`);
}

// --- Historical analytics --------------------------------------------------
/**
 * Fetch historical thermal analytics.
 * Includes trend data, observation count, hottest/coolest dates.
 *
 * @returns {Promise<Object>} { status, observation_count, mean_historical_lst, ... }
 */
export async function fetchTemporalAnalytics() {
  return fetchJson('/temporal/thermal/analytics');
}

// --- Pipeline status -------------------------------------------------------
/**
 * Fetch the status of the historical LST pipeline.
 *
 * @returns {Promise<Object>} { status, source, product, observation_count, ... }
 */
export async function fetchTemporalStatus() {
  return fetchJson('/temporal/status');
}
