// thematicData.js
// Session 3 data adapter: bridges backend/GIS outputs and the React UI.
// All dataset definitions (units, legends, thresholds) come from the project's
// GIS pipeline configuration (gis-engine/config.py) - nothing is invented here.
// The frontend only ever renders a dataset when the backend reports the actual
// file exists on disk (or when local OSM fallback files are present).

import { API_BASE } from './backendClient';

// ---------------------------------------------------------------------------
// Dataset definitions - mirrors gis-engine/config.py thresholds
// ---------------------------------------------------------------------------

// Heat classes (gis-engine/config.py HeatClassConfig + process_landsat.py colors)
const HEAT_CLASS_COLORS = ['#2166ac', '#67a9cf', '#fdae61', '#f46d43', '#d73027', '#67001f'];

// Vegetation density classes (ThresholdsConfig.veg_density_breaks)
const VEG_DENSITY_STOPS = [
  { color: '#fee08b', label: 'Very Low', value: '< 0.10' },
  { color: '#d9ef8b', label: 'Low', value: '0.10–0.20' },
  { color: '#a6d96a', label: 'Moderate', value: '0.20–0.40' },
  { color: '#66bd63', label: 'High', value: '0.40–0.60' },
  { color: '#1a9850', label: 'Very High', value: '≥ 0.60' }
];

// Land cover classes (ThresholdsConfig.landcover_*_ndvi)
const LAND_COVER_STOPS = [
  { color: '#38bdf8', label: 'Water', value: 'NDVI < 0.05' },
  { color: '#c2410c', label: 'Built-up', value: '0.05–0.15' },
  { color: '#d6b85c', label: 'Bare Land', value: '0.15–0.30' },
  { color: '#22c55e', label: 'Vegetation', value: '≥ 0.30' }
];

// Indian CPCB AQI categories (config.py AQI_CATEGORIES)
const AQI_STOPS = [
  { color: '#16a34a', label: 'Good', value: '0–50' },
  { color: '#65a30d', label: 'Satisfactory', value: '51–100' },
  { color: '#eab308', label: 'Moderate', value: '101–200' },
  { color: '#f97316', label: 'Poor', value: '201–300' },
  { color: '#dc2626', label: 'Very Poor', value: '301–400' },
  { color: '#7e22ce', label: 'Severe', value: '401–500' }
];

// Every thematic dataset the UI knows about. `available` is filled in from the
// backend monitoring report; nothing here claims a dataset exists.
export const DATASET_DEFINITIONS = [
  {
    key: 'ndvi', name: 'NDVI', group: 'VEGETATION', unit: 'index (-1 to 1)',
    source: 'Sentinel-2 Level-2A', resolution: '10 m', type: 'continuous',
    legend: {
      title: 'NDVI', unit: 'index',
      min: -0.5, max: 1.0,
      stops: [
        { color: '#d73027', label: 'Low', value: '≤ 0.10' },
        { color: '#fee08b', label: 'Moderate', value: '0.20–0.40' },
        { color: '#1a9850', label: 'High', value: '≥ 0.60' }
      ],
      note: 'Green cover threshold: NDVI ≥ 0.30 (project config)'
    }
  },
  {
    key: 'green_cover', name: 'Green Cover', group: 'VEGETATION', unit: '%',
    source: 'Sentinel-2 Level-2A', resolution: '10 m', type: 'continuous',
    legend: {
      title: 'Green Cover', unit: '%', min: 0, max: 100,
      stops: [
        { color: '#f7fcf5', label: 'Low', value: '0%' },
        { color: '#74c476', label: 'Moderate', value: '50%' },
        { color: '#00441b', label: 'High', value: '100%' }
      ],
      note: 'Vegetation where NDVI > 0.30 (project config)'
    }
  },
  {
    key: 'vegetation_density', name: 'Vegetation Density', group: 'VEGETATION',
    unit: 'class', source: 'Sentinel-2 Level-2A', resolution: '10 m',
    type: 'categorical',
    legend: { title: 'Vegetation Density', stops: VEG_DENSITY_STOPS }
  },
  {
    key: 'land_cover', name: 'Land Cover', group: 'LAND COVER', unit: 'class',
    source: 'Sentinel-2 Level-2A', resolution: '10 m', type: 'categorical',
    legend: { title: 'Land Cover', stops: LAND_COVER_STOPS }
  },
  {
    key: 'lst', name: 'Land Surface Temp', group: 'HEAT', unit: '°C',
    source: 'Landsat 8/9 Collection-2 Level-2 (ST_B10)', resolution: '30 m',
    type: 'continuous', observed: true,
    legend: {
      title: 'LST', unit: '°C', min: 15, max: 50,
      stops: [
        { color: '#2c7bb6', label: 'Cool', value: '≈ 20 °C' },
        { color: '#ffffbf', label: 'Moderate', value: '≈ 33 °C' },
        { color: '#d7191c', label: 'Hot', value: '≈ 45 °C' }
      ],
      note: 'Historical satellite observation - not live'
    }
  },
  {
    key: 'heat_class', name: 'Heat Class', group: 'HEAT', unit: 'class',
    source: 'Landsat LST classification', resolution: '30 m', type: 'categorical',
    legend: {
      title: 'Heat Classification',
      stops: HEAT_CLASS_COLORS.map((color, i) => ({
        color,
        label: ['Very Cool', 'Cool', 'Moderate', 'Warm', 'Hot', 'Very Hot'][i],
        value: ['< 20', '20–25', '25–30', '30–35', '35–40', '> 40'][i] + ' °C'
      })),
      note: 'Fixed breaks 20/25/30/35/40 °C (project config, visualization thresholds)'
    }
  },
  {
    key: 'elevation', name: 'Elevation', group: 'TERRAIN', unit: 'm',
    source: 'Copernicus DEM GLO-30 / SRTM', resolution: '30 m', type: 'continuous',
    legend: {
      title: 'Elevation', unit: 'm', min: 0, max: 90,
      stops: [
        { color: '#74c476', label: 'Low', value: '≈ 20 m' },
        { color: '#fee08b', label: 'Mid', value: '≈ 50 m' },
        { color: '#8c510a', label: 'High', value: '≈ 90 m' }
      ]
    }
  },
  {
    key: 'slope', name: 'Slope', group: 'TERRAIN', unit: '°',
    source: 'DEM derivative (Horn 1981)', resolution: '30 m', type: 'continuous',
    legend: {
      title: 'Slope', unit: '°', min: 0, max: 45,
      stops: [
        { color: '#f7fcfd', label: 'Flat', value: '0°' },
        { color: '#4d004b', label: 'Steep', value: '> 20°' }
      ]
    }
  },
  {
    key: 'aspect', name: 'Aspect', group: 'TERRAIN', unit: 'direction',
    source: 'DEM derivative', resolution: '30 m', type: 'categorical',
    legend: {
      title: 'Aspect',
      stops: [
        { color: '#fbbf24', label: 'N', value: '337.5–22.5°' },
        { color: '#fb923c', label: 'NE', value: '22.5–67.5°' },
        { color: '#f87171', label: 'E', value: '67.5–112.5°' },
        { color: '#e879f9', label: 'SE', value: '112.5–157.5°' },
        { color: '#a78bfa', label: 'S', value: '157.5–202.5°' },
        { color: '#818cf8', label: 'SW', value: '202.5–247.5°' },
        { color: '#38bdf8', label: 'W', value: '247.5–292.5°' },
        { color: '#34d399', label: 'NW', value: '292.5–337.5°' }
      ]
    }
  },
  {
    key: 'hillshade', name: 'Hillshade', group: 'TERRAIN', unit: 'shade',
    source: 'DEM derivative', resolution: '30 m', type: 'continuous',
    legend: {
      title: 'Hillshade', unit: 'illumination', min: 0, max: 255,
      stops: [
        { color: '#000000', label: 'Shadow', value: '0' },
        { color: '#ffffff', label: 'Lit', value: '255' }
      ]
    }
  },
  {
    key: 'aqi', name: 'AQI', group: 'AIR QUALITY', unit: 'index',
    source: 'CPCB / OpenAQ / Sentinel-5P interpolation', resolution: '1 km',
    type: 'categorical',
    legend: { title: 'AQI (CPCB)', stops: AQI_STOPS }
  },
  {
    key: 'pm25', name: 'PM2.5', group: 'AIR QUALITY', unit: 'µg/m³',
    source: 'CPCB / OpenAQ', resolution: '1 km', type: 'continuous',
    legend: {
      title: 'PM2.5', unit: 'µg/m³', min: 0, max: 250,
      stops: [
        { color: '#16a34a', label: 'Good', value: '≤ 30' },
        { color: '#eab308', label: 'Moderate', value: '61–90' },
        { color: '#dc2626', label: 'Very Poor', value: '> 121' }
      ],
      note: 'CPCB breakpoints (project config)'
    }
  },
  {
    key: 'pm10', name: 'PM10', group: 'AIR QUALITY', unit: 'µg/m³',
    source: 'CPCB / OpenAQ', resolution: '1 km', type: 'continuous',
    legend: {
      title: 'PM10', unit: 'µg/m³', min: 0, max: 430,
      stops: [
        { color: '#16a34a', label: 'Good', value: '≤ 50' },
        { color: '#eab308', label: 'Moderate', value: '101–250' },
        { color: '#dc2626', label: 'Very Poor', value: '> 351' }
      ],
      note: 'CPCB breakpoints (project config)'
    }
  },
  {
    key: 'no2', name: 'NO₂', group: 'AIR QUALITY', unit: 'µg/m³',
    source: 'CPCB / Sentinel-5P', resolution: '1 km', type: 'continuous',
    legend: {
      title: 'NO₂', unit: 'µg/m³', min: 0, max: 400,
      stops: [
        { color: '#16a34a', label: 'Good', value: '≤ 40' },
        { color: '#eab308', label: 'Moderate', value: '81–180' },
        { color: '#dc2626', label: 'Very Poor', value: '> 281' }
      ],
      note: 'CPCB breakpoints (project config)'
    }
  },
  {
    key: 'so2', name: 'SO₂', group: 'AIR QUALITY', unit: 'µg/m³',
    source: 'CPCB / Sentinel-5P', resolution: '1 km', type: 'continuous',
    legend: {
      title: 'SO₂', unit: 'µg/m³', min: 0, max: 1600,
      stops: [
        { color: '#16a34a', label: 'Good', value: '≤ 40' },
        { color: '#eab308', label: 'Moderate', value: '81–380' },
        { color: '#dc2626', label: 'Very Poor', value: '> 801' }
      ],
      note: 'CPCB breakpoints (project config)'
    }
  },
  {
    key: 'o3', name: 'O₃', group: 'AIR QUALITY', unit: 'µg/m³',
    source: 'CPCB / Sentinel-5P', resolution: '1 km', type: 'continuous',
    legend: {
      title: 'O₃', unit: 'µg/m³', min: 0, max: 748,
      stops: [
        { color: '#16a34a', label: 'Good', value: '≤ 50' },
        { color: '#eab308', label: 'Moderate', value: '101–168' },
        { color: '#dc2626', label: 'Very Poor', value: '> 209' }
      ],
      note: 'CPCB breakpoints (project config)'
    }
  },
  {
    key: 'co', name: 'CO', group: 'AIR QUALITY', unit: 'mg/m³',
    source: 'CPCB / Sentinel-5P', resolution: '1 km', type: 'continuous',
    legend: {
      title: 'CO', unit: 'mg/m³', min: 0, max: 34,
      stops: [
        { color: '#16a34a', label: 'Good', value: '≤ 1.0' },
        { color: '#eab308', label: 'Moderate', value: '2.1–10.0' },
        { color: '#dc2626', label: 'Very Poor', value: '> 17.1' }
      ],
      note: 'CPCB breakpoints, CO in mg/m³ (project config)'
    }
  }
];

// City (OSM) layers - these are real and always shown when the OSM fallback
// files exist in the frontend /3d-layers folder.
export const CITY_LAYER_DEFINITIONS = [
  {
    key: 'buildings', name: 'Buildings', group: 'CITY', type: 'categorical',
    legend: {
      title: 'Buildings',
      stops: [
        { color: '#2563eb', label: 'Measured height' },
        { color: '#7c3aed', label: 'Default height' }
      ],
      note: 'Real OSM footprints, extruded 3D'
    }
  },
  {
    key: 'roads', name: 'Roads', group: 'CITY', type: 'categorical',
    legend: {
      title: 'Roads',
      stops: [
        { color: '#f97316', label: 'Major (motorway–tertiary)' },
        { color: '#e2e8f0', label: 'Local streets' }
      ],
      note: 'Real OSM road network'
    }
  },
  {
    key: 'green', name: 'Green Spaces', group: 'CITY', type: 'categorical',
    legend: {
      title: 'Green Spaces',
      stops: [{ color: '#22c55e', label: 'OSM leisure/green' }],
      note: 'Real OSM polygons'
    }
  },
  {
    key: 'trees', name: 'Trees', group: 'CITY', type: 'categorical',
    legend: {
      title: 'Trees / Natural',
      stops: [{ color: '#16a34a', label: 'wood · tree · tree_row · scrub' }],
      note: 'Real OSM natural polygons'
    }
  },
  {
    key: 'water', name: 'Water', group: 'CITY', type: 'categorical',
    legend: {
      title: 'Water',
      stops: [{ color: '#0ea5e9', label: 'OSM water bodies' }],
      note: 'Real OSM polygons'
    }
  }
];

// ---------------------------------------------------------------------------
// Backend calls with graceful fallbacks
// ---------------------------------------------------------------------------

// When the backend is unreachable we still know the OSM fallback files ship
// with the frontend, so OSM is genuinely available; every other thematic
// dataset availability is determined by the backend monitoring report.
const LOCAL_FALLBACK_STATUS = {
  generated_at: new Date().toISOString(),
  backend_reachable: false,
  datasets: [
    { key: 'osm', name: 'OSM City Layers', group: 'city', available: true,
      status: 'available', source: 'Local frontend /3d-layers fallback',
      file_count: 5, files: [], last_modified: null }
  ].concat(
    DATASET_DEFINITIONS.map((defn) => ({
      key: defn.key, name: defn.name, group: defn.group.toLowerCase(),
      available: false, status: 'unavailable', source: defn.source,
      file_count: 0, files: [], last_modified: null
    }))
  )
};

export async function fetchMonitoringStatus() {
  try {
    const response = await fetch(`${API_BASE}/monitoring/status`);
    if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
    const data = await response.json();
    return { ...data, backend_reachable: true };
  } catch (error) {
    return { ...LOCAL_FALLBACK_STATUS, error: error.message };
  }
}

export async function fetchEnvironmentSummary() {
  try {
    const response = await fetch(`${API_BASE}/environment/summary`);
    if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
    return await response.json();
  } catch {
    return null;
  }
}

// Builds a { key: boolean } map from the monitoring report.
// City (OSM) layers are considered available whenever the OSM dataset is
// available, because the map renders them from the real OSM web layers
// (backend catalogue or the local /3d-layers fallback).
const CITY_AVAILABILITY_KEYS = ['buildings', 'roads', 'green', 'trees', 'water', 'boundary'];

export function buildAvailability(monitoring) {
  const map = { osm: true };
  (monitoring?.datasets || []).forEach((ds) => {
    map[ds.key] = Boolean(ds.available);
  });
  if (map.osm) {
    CITY_AVAILABILITY_KEYS.forEach((k) => { map[k] = true; });
  }
  return map;
}

export function getDataset(key) {
  return DATASET_DEFINITIONS.find((d) => d.key === key) || null;
}

export function getCityLayer(key) {
  return CITY_LAYER_DEFINITIONS.find((d) => d.key === key) || null;
}

// Groups definitions by their UI group name.
export function groupDefinitions(definitions) {
  const groups = {};
  definitions.forEach((defn) => {
    (groups[defn.group] = groups[defn.group] || []).push(defn);
  });
  return groups;
}

// AQI category for a numeric AQI value (CPCB project breakpoints).
export function aqiCategory(aqi) {
  if (aqi === null || aqi === undefined || Number.isNaN(aqi)) return null;
  if (aqi <= 50) return 'Good';
  if (aqi <= 100) return 'Satisfactory';
  if (aqi <= 200) return 'Moderate';
  if (aqi <= 300) return 'Poor';
  if (aqi <= 400) return 'Very Poor';
  return 'Severe';
}

// Heat class for a temperature in °C (project fixed breaks - visualization).
export function heatClass(celsius) {
  if (celsius === null || celsius === undefined || Number.isNaN(celsius)) return null;
  if (celsius < 20) return 'Very Cool';
  if (celsius < 25) return 'Cool';
  if (celsius < 30) return 'Moderate';
  if (celsius < 35) return 'Warm';
  if (celsius < 40) return 'Hot';
  return 'Very Hot';
}

// Simple heat-index approximation (Rothfusz) used ONLY when both temperature
// and humidity are real observed values - labelled as an approximation.
export function heatIndexCelsius(tempC, humidityPct) {
  if (tempC === null || humidityPct === null) return null;
  const t = tempC;
  const rh = humidityPct;
  // Rothfusz regression (valid for t >= 27 °C and rh >= 40%)
  if (t < 27 || rh < 40) return t;
  const hi = -8.78469475556 + 1.61139411 * t + 2.33854883889 * rh
    - 0.14611605 * t * rh - 0.012308094 * t * t
    - 0.0164248277778 * rh * rh + 0.002211732 * t * t * rh
    + 0.00072546 * t * rh * rh - 0.000003582 * t * t * rh * rh;
  return Math.round(hi * 10) / 10;
}
