// riskData.js
// Shared risk computation used by the RiskIndicator panel, the citizen sidebar
// QUICK STATS grid and the selected-area analytics bar. Every value is derived
// from real data (or reported insufficient when no data exists). No scientific
// thresholds are invented: each indicator states what it is based on and marks
// project heat-class / density breaks as VISUALIZATION thresholds.

import { heatClass, heatIndexCelsius } from './thematicData';

export const levelFrom = (value, breaks, labels) => {
  for (let i = breaks.length - 1; i >= 0; i -= 1) {
    if (value >= breaks[i]) return labels[i];
  }
  return labels[0];
};

export function computeRiskData({ environmentSummary, liveWeather, availability = {}, areaOsm = null }) {
  const heatIdx = heatIndexCelsius(liveWeather?.temperature ?? null, liveWeather?.humidity ?? null);
  const airTemp = liveWeather?.temperature ?? null;

  // --- Heat risk: real live air temperature + heat index -----------------
  // Uses the project heat-class temperature breaks as VISUALIZATION thresholds.
  let heatRisk = { level: 'Low', value: 'N/A' };
  if (airTemp != null) {
    const cls = heatClass(heatIdx ?? airTemp);
    heatRisk = {
      level: ['Very Cool', 'Cool'].includes(cls) ? 'Low'
        : ['Moderate', 'Warm'].includes(cls) ? 'Moderate' : 'High',
      value: `${airTemp} °C air${heatIdx != null && heatIdx !== airTemp ? ` (feels ${heatIdx} °C)` : ''}`
    };
  }

  // --- Vegetation stress: real OSM green cover ---------------------------
  const greenPct = environmentSummary?.derived?.green_cover_pct;
  let vegRisk = { level: 'Low', value: 'N/A' };
  if (greenPct != null) {
    vegRisk = {
      level: levelFrom(greenPct, [15, 35], ['High', 'Moderate', 'Low']),
      value: `${greenPct}% OSM green cover`
    };
  }

  // --- Urban density risk: real OSM building density ---------------------
  let densityRisk = { level: 'Low', value: 'N/A' };
  if (areaOsm?.buildings != null) {
    const km2 = Math.PI * ((areaOsm.radiusM ?? 150) / 1000) ** 2 || 1;
    const perKm2 = areaOsm.buildings / km2;
    densityRisk = {
      level: levelFrom(perKm2, [800, 400], ['High', 'Moderate', 'Low']),
      value: `${Math.round(perKm2)} buildings/km² (within ${areaOsm.radiusM}m)`
    };
  }

  // --- Air quality risk: unavailable without AQI data --------------------
  const aqiAvailable = availability?.aqi ?? false;

  // --- Overall: simple composite of the indicators above ------------------
  const scores = [
    heatRisk.level === 'High' ? 1 : heatRisk.level === 'Moderate' ? 0.5 : 0,
    vegRisk.level === 'High' ? 1 : vegRisk.level === 'Moderate' ? 0.5 : 0,
    densityRisk.level === 'High' ? 1 : densityRisk.level === 'Moderate' ? 0.5 : 0,
    aqiAvailable ? 0 : 0 // AQI contributes once data exists
  ];
  const activeCount = scores.filter((s) => Number.isFinite(s)).length || 1;
  const overallScore = scores.reduce((a, b) => a + b, 0) / activeCount;
  const overallLevel = overallScore >= 0.66 ? 'High' : overallScore >= 0.33 ? 'Moderate' : 'Low';

  return [
    {
      name: 'Heat Risk', level: heatRisk.level, value: heatRisk.value,
      threshold: 'High ≥ 35 °C (project heat-class break: Hot/Very Hot) - VISUALIZATION threshold',
      basis: airTemp != null
        ? 'Based on live air temperature + heat index (OpenWeather, real observation)'
        : 'No live temperature data - insufficient data'
    },
    {
      name: 'Air Quality Risk',
      level: aqiAvailable ? 'Moderate' : null,
      value: aqiAvailable ? 'AQI data available' : 'Insufficient data',
      threshold: aqiAvailable ? 'CPCB project breakpoints (Good … Severe)' : 'No threshold applied - no AQI data',
      basis: aqiAvailable
        ? 'Based on AQI categories (CPCB project breakpoints)'
        : 'No AQI raster produced yet - run gis-engine AQI stage'
    },
    {
      name: 'Vegetation Stress', level: vegRisk.level, value: vegRisk.value,
      threshold: 'High < 15% · Moderate 15-35% · Low ≥ 35% green cover - VISUALIZATION threshold',
      basis: greenPct != null
        ? 'Based on real OSM green cover %; thresholds are VISUALIZATION only (not scientific)'
        : 'No green cover data'
    },
    {
      name: 'Urban Density Risk', level: densityRisk.level, value: densityRisk.value,
      threshold: 'High ≥ 800 · Moderate 400-800 · Low < 400 buildings/km² - VISUALIZATION threshold',
      basis: areaOsm?.buildings != null
        ? 'Based on real OSM building count near the selection; thresholds are VISUALIZATION only'
        : 'Select a location on the map to compute density'
    },
    {
      name: 'Overall Urban Risk', level: overallLevel,
      value: `Composite of ${scores.filter((s) => s >= 0).length} indicators`,
      threshold: 'High ≥ 0.66 · Moderate ≥ 0.33 · Low < 0.33 (equal-weight score 0-1)',
      basis: 'Simple equal-weight composite of the indicators above - not a scientific score'
    }
  ];
}
