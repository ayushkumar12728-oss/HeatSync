// systemHealth.js
// =============================================================================
// REAL system-health service (replaces the old "11 APIs" audit).
//
// The old audit counted external API-key connectors — most of which were
// placeholders that never made a request — producing a misleading "1/11 APIs
// active". This service instead checks ONLY meaningful backend capabilities:
//
//   CORE SYSTEM     backend · database · GIS catalogue
//   MODEL           XGBoost model + feature dataset
//   SCENARIO ENGINE intervention scenarios + cached results
//   LIVE DATA       weather · air quality · search (geocoding)
//   AI              Nemotron (configuration / availability)
//
// Every status comes from a real request to the backend or from verified
// backend state (GET /api/system/health). Never fabricated: a failed probe is
// reported as unavailable with a reason.
// =============================================================================

import { API_BASE } from './backendClient';

const DEFAULT_TIMEOUT_MS = 15000; // health runs several probes server-side

async function fetchWithTimeout(path, options = {}, timeoutMs = DEFAULT_TIMEOUT_MS) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(`${API_BASE}${path}`, { ...options, signal: controller.signal });
    if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
    return await response.json();
  } catch (error) {
    if (error.name === 'AbortError') {
      throw new Error(`Request timed out after ${timeoutMs / 1000}s`);
    }
    throw error;
  } finally {
    clearTimeout(timer);
  }
}

// ---------------------------------------------------------------------------
// Status helpers
// ---------------------------------------------------------------------------
// Tone used by the UI dots: ok | warn | down | config (neutral, not an error)
export function statusTone(value) {
  if (value === true || value === 'ok' || value === 'available' || value === 'online'
      || value === 'connected' || value === 'ready' || value === 'healthy'
      || value === 'live' || value === 'configured' || value === 'operational') {
    return 'ok';
  }
  if (value === 'configuration_required' || value === 'not_configured'
      || value === 'disabled') {
    return 'config';
  }
  if (value === 'partial' || value === 'degraded' || value === 'warn') {
    return 'warn';
  }
  return 'down';
}

// ---------------------------------------------------------------------------
// Main health check
// ---------------------------------------------------------------------------
export async function fetchSystemHealth() {
  const data = await fetchWithTimeout('/system/health');
  return data;
}

// Builds the ordered, grouped status list used by the System Status UI.
// `health` is the raw /api/system/health payload; `fallbackError` is used when
// the whole request failed (backend unreachable).
export function buildSystemStatus(health, fallbackError = null) {
  const entries = [];

  const core = {
    key: 'backend',
    label: 'Backend',
    value: health?.backend?.status === 'online' ? 'Online' : 'Unreachable',
    tone: health?.backend?.status === 'online' ? 'ok' : 'down',
    detail: health?.backend ? `${health.backend.app} v${health.backend.version}` : 'API Gateway',
    source: 'GET /api/system/health'
  };
  if (fallbackError) {
    core.value = 'Offline';
    core.detail = fallbackError.message || 'Backend request failed';
  }
  entries.push(core);

  // Database — optional (artifact-first mode). Not configured is a neutral state.
  const db = health?.database;
  entries.push({
    key: 'database',
    label: 'Database',
    value: db?.enabled === true ? 'Connected' : 'Not configured',
    tone: db?.enabled === true ? 'ok' : 'config',
    detail: db?.enabled === true
      ? `${db.grid_cells ?? ''} grid cells (PostGIS)`.trim()
      : 'Artifact-first mode — PostGIS optional (UDT_DATABASE_URL)',
    source: 'GET /api/health/database'
  });

  // GIS — real dataset counts from the backend monitoring report.
  const gis = health?.gis;
  entries.push({
    key: 'gis',
    label: 'GIS',
    value: gis
      ? `${gis.datasets_available}/${gis.datasets_total} datasets`
      : 'Unavailable',
    tone: gis?.status === 'available' ? 'ok' : gis?.status === 'partial' ? 'warn' : 'down',
    detail: gis
      ? `Rasters + vectors on disk (${gis.status})`
      : 'No GIS report',
    source: 'Disk state (data/processed)'
  });

  // Model — real artifact status.
  const model = health?.model;
  const modelOk = model?.available === true;
  entries.push({
    key: 'model',
    label: 'Model',
    value: modelOk ? `${model.name || 'XGBoost'} ready` : 'Unavailable',
    tone: modelOk ? 'ok' : 'down',
    detail: modelOk
      ? `${model.feature_count} features · v${model.version || '—'}`
      : (model?.message || 'models/best_model.pkl not found'),
    source: 'GET /api/model/info'
  });

  // Scenario engine.
  const scenarios = health?.scenarios;
  const scenariosOk = scenarios?.ready === true;
  entries.push({
    key: 'scenarios',
    label: 'Scenarios',
    value: scenariosOk ? `${scenarios.count} interventions` : 'Unavailable',
    tone: scenariosOk ? 'ok' : 'down',
    detail: scenariosOk
      ? `Cached cell results: ${scenarios.cached_results ?? 0}`
      : 'Scenario engine not configured',
    source: 'GET /api/simulation/scenarios'
  });

  // Live data.
  const weather = health?.weather;
  entries.push({
    key: 'weather',
    label: 'Weather',
    value: weather?.status === 'available' ? 'Live' : 'Unavailable',
    tone: weather?.status === 'available' ? 'ok' : 'warn',
    detail: weather?.status === 'available'
      ? `${weather.temperature_c ?? '—'} °C · ${weather.source}`
      : (weather?.reason || 'OpenWeather request failed'),
    source: 'OpenWeather (backend proxy)'
  });

  const aq = health?.air_quality;
  entries.push({
    key: 'air_quality',
    label: 'Air Quality',
    value: aq?.status === 'available' ? `AQI ${aq.aqi ?? '—'}` : 'Unavailable',
    tone: aq?.status === 'available' ? 'ok' : 'warn',
    detail: aq?.status === 'available'
      ? `PM2.5 ${aq.pm2_5 ?? '—'} µg/m³ · ${aq.source}`
      : (aq?.reason || 'No live AQI source configured'),
    source: 'OpenWeather (backend proxy)'
  });

  const search = health?.search;
  entries.push({
    key: 'search',
    label: 'Search',
    value: search?.status === 'available' ? 'Ready' : 'Unavailable',
    tone: search?.status === 'available' ? 'ok' : 'warn',
    detail: search?.status === 'available'
      ? `${search.provider} reachable`
      : (search?.reason || 'Nominatim probe failed'),
    source: 'OpenStreetMap Nominatim'
  });

  // Satellite — latest observation availability from the live feature pipeline.
  const satProbe = health?.satellite || null;
  entries.push({
    key: 'satellite',
    label: 'Satellite',
    value: satProbe?.status === 'LATEST_OBSERVATION' ? 'Online' : satProbe?.status === 'UNAVAILABLE' ? 'Unavailable' : 'Checking…',
    tone: satProbe?.status === 'LATEST_OBSERVATION' ? 'ok' : satProbe?.status === 'UNAVAILABLE' ? 'warn' : 'config',
    detail: satProbe?.last_acquired ? `Last acquired: ${satProbe.last_acquired}` : 'Sentinel-2 NDVI / land cover',
    source: 'GET /api/prediction/heat/current/debug'
  });

  // Terrain — real DEM tile check.
  const terrain = health?.terrain || null;
  entries.push({
    key: 'terrain',
    label: 'Terrain',
    value: terrain?.status === 'AVAILABLE' ? 'Available' : terrain?.status === 'UNAVAILABLE' ? 'Unavailable' : 'Checking…',
    tone: terrain?.status === 'AVAILABLE' ? 'ok' : terrain?.status === 'UNAVAILABLE' ? 'warn' : 'config',
    detail: terrain?.status === 'AVAILABLE'
      ? `${terrain.source} · ${terrain.format} · ${terrain.tiles ?? '?'} tiles`
      : (terrain?.reason || 'DEM tiles not found'),
    source: 'GET /api/system/terrain'
  });

  // XGBoost model — real artifact status.
  const xgbOk = model?.available === true;
  entries.push({
    key: 'xgboost',
    label: 'XGBoost',
    value: xgbOk ? `${model.name || 'XGBRegressor'} ready` : 'Unavailable',
    tone: xgbOk ? 'ok' : 'down',
    detail: xgbOk
      ? `${model.feature_count} features · v${model.version || '—'}`
      : (model?.message || 'models/best_model.pkl not found'),
    source: 'GET /api/prediction/model'
  });

  // Scenario engine — from scenarios report.
  entries.push({
    key: 'scenario_engine',
    label: 'Scenario Engine',
    value: scenariosOk ? `${scenarios.count} interventions` : 'Unavailable',
    tone: scenariosOk ? 'ok' : 'down',
    detail: scenariosOk
      ? `Cached cell results: ${scenarios.cached_results ?? 0}`
      : 'Scenario engine not configured',
    source: 'GET /api/simulation/scenarios'
  });

  // AI — configuration is a neutral state, never an error.
  const ai = health?.ai;
  const aiConfigured = ai?.status === 'configured';
  entries.push({
    key: 'ai',
    label: 'Nemotron',
    value: aiConfigured ? 'Online' : ai?.status === 'configuration_required' ? 'Configuration Required' : 'Unavailable',
    tone: aiConfigured ? 'ok' : 'config',
    detail: aiConfigured
      ? ai.model || 'NVIDIA NIM (Nemotron)'
      : (ai?.message || 'NEMOTRON_API_KEY is not configured'),
    source: 'GET /api/ai/status'
  });

  return {
    generatedAt: health?.generated_at || null,
    overall: health?.status || (fallbackError ? 'degraded' : 'unknown'),
    liveProbesEnabled: health?.live_probes_enabled,
    groups: [
      { key: 'core', label: 'CORE SYSTEM', entries: entries.filter((e) => ['backend', 'database', 'gis'].includes(e.key)) },
      { key: 'model', label: 'MODEL', entries: entries.filter((e) => ['model', 'xgboost', 'scenarios', 'scenario_engine'].includes(e.key)) },
      { key: 'live', label: 'LIVE DATA', entries: entries.filter((e) => ['weather', 'air_quality', 'satellite', 'search'].includes(e.key)) },
      { key: 'ai', label: 'AI', entries: entries.filter((e) => ['ai'].includes(e.key)) }
    ]
  };
}

// ---------------------------------------------------------------------------
// Live weather (backend-cached OpenWeather probe)
 // ---------------------------------------------------------------------------
export async function fetchLiveWeather() {
  const data = await fetchWithTimeout('/system/weather', {}, 12000);
  if (data?.status === 'unavailable') {
    return {
      success: false,
      status: 'unavailable',
      source: 'OpenWeather',
      error: data?.reason || 'Weather unavailable'
    };
  }
  const c = data.current || {};
  const h = data.hourly || {};
  return {
    success: true,
    status: 'available',
    source: data.source || 'OpenWeather',
    fetchedAt: data.retrieved_at || data.fetched_at || null,
    observedAt: data.observed_at || null,
    cacheAgeSeconds: data.cache_age_seconds ?? null,
    // normalized fields used by the rest of the UI
    temperature: c.temperature ?? c.temperature_2m,
    feelsLike: c.feels_like ?? c.apparent_temperature,
    humidity: c.humidity ?? c.relative_humidity_2m,
    windSpeed: c.wind_speed_kmh ?? c.wind_speed_10m ?? (c.wind_speed != null ? Math.round(c.wind_speed * 3.6 * 10) / 10 : null),
    windDirection: c.wind_direction ?? c.wind_direction_10m,
    windGusts: c.wind_gusts_10m ?? null,
    pressure: c.pressure ?? c.surface_pressure ?? c.pressure_msl,
    visibility: c.visibility ?? null,
    precipitation: c.precipitation ?? c.rain ?? null,
    rain: c.rain ?? null,
    snow: c.snow ?? null,
    cloudCover: c.cloud_cover ?? null,
    uvIndex: c.uv_index ?? null,
    weatherCode: c.weather_code ?? null,
    weatherCondition: c.weather_condition ?? null,
    weatherDescription: c.weather_description ?? null,
    sunrise: c.sunrise ?? null,
    sunset: c.sunset ?? null,
    isDay: c.is_day ?? null,
    units: data.units || {},
    hourly: {
      time: h.time || [],
      temperature: h.temperature_2m || [],
      humidity: h.relative_humidity_2m || [],
      precipitation: h.precipitation || [],
      cloudCover: h.cloud_cover || [],
      windSpeed: h.wind_speed_10m || [],
      uvIndex: h.uv_index || [],
      pm25: [] // PM2.5 is not part of the weather API
    }
  };
}

// ---------------------------------------------------------------------------
// Live air quality (backend-cached OpenWeather AQ probe)
// ---------------------------------------------------------------------------
export async function fetchLiveAirQuality() {
  const data = await fetchWithTimeout('/system/air-quality', {}, 12000);
  if (!data?.available) {
    return {
      success: false,
      status: 'unavailable',
      source: 'OpenWeather',
      error: data?.reason || 'Air quality unavailable'
    };
  }
  const c = data.current || {};
  return {
    success: true,
    status: 'available',
    source: data.source || 'OpenWeather',
    fetchedAt: data.retrieved_at || data.fetched_at || null,
    observedAt: data.observed_at || null,
    cacheAgeSeconds: data.cache_age_seconds ?? null,
    // OpenWeather AQI is a 1-5 index (1=Good .. 5=Very Poor)
    aqi: c.aqi ?? null,
    aqiLabel: c.aqi_label ?? null,
    aqiScale: c.aqi_scale || 'OpenWeather 1-5 index',
    pm25: c.pm2_5,
    pm10: c.pm10,
    no2: c.no2 ?? c.nitrogen_dioxide,
    o3: c.o3 ?? c.ozone,
    so2: c.so2 ?? c.sulphur_dioxide,
    co: c.co ?? c.carbon_monoxide,
    nh3: c.nh3 ?? null,
    uvIndex: c.uv_index ?? null,
    units: data.units || {}
  };
}

// OpenWeather AQI (1-5) band label — the provider's own scale.
export function aqiCategoryOwm(aqi) {
  if (aqi === null || aqi === undefined || Number.isNaN(aqi)) return null;
  const bands = {
    1: { label: 'Good', color: '#16a34a' },
    2: { label: 'Fair', color: '#65a30d' },
    3: { label: 'Moderate', color: '#eab308' },
    4: { label: 'Poor', color: '#f97316' },
    5: { label: 'Very Poor', color: '#dc2626' }
  };
  return bands[aqi] || null;
}

// ---------------------------------------------------------------------------
// Search/geocoding status — derived from the health report (real probe).
// ---------------------------------------------------------------------------
export function searchStatusFrom(health) {
  const search = health?.search;
  return {
    available: search?.status === 'available',
    provider: search?.provider || 'OpenStreetMap Nominatim',
    reason: search?.reason || null,
    checkedAt: search?.checked_at || null
  };
}
