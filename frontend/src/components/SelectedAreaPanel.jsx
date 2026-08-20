import React, { useState } from 'react';
import { X, MapPin, ThermometerSun, Leaf, Building2, Route, Trees, Waves, Gauge, CloudSun, Bot, BrainCircuit, Sparkles, Loader2, AlertTriangle } from 'lucide-react';
import { askAI } from '../services/backendClient';

// Selected-area information panel.
// Shows ONLY values that exist:
//   - OSM-derived metrics (computed from the real OSM layers already loaded)
//   - live weather (OpenWeather)
// Everything else is displayed as "Data unavailable" with its source listed.
export const SelectedAreaPanel = ({ location, osm, liveWeather, availability, modelInfo, onClose }) => {
  const [aiState, setAiState] = useState({ loading: false, error: null, result: null });

  const explainArea = async () => {
    if (aiState.loading) return;
    setAiState({ loading: true, error: null, result: null });
    const km2 = Math.PI * ((osm?.radiusM ?? 150) / 1000) ** 2 || 1;
    const context = {
      location: { name: location.name, lat: location.lat, lng: location.lng },
      urban: {
        building_density: osm?.buildings != null ? Math.round(osm.buildings / km2) : null,
        road_density: osm?.roadLengthM != null ? Math.round((osm.roadLengthM / 1000 / km2) * 100) / 100 : null,
        tree_density: osm?.trees != null ? Math.round(osm.trees / km2) : null
      },
      weather: liveWeather?.temperature != null
        ? { temperature: liveWeather.temperature, humidity: liveWeather.humidity ?? null, wind_speed: liveWeather.windSpeed ?? null, source: liveWeather.source || 'OpenWeather' }
        : null
    };
    if (modelInfo) context.prediction = { available: modelInfo.available === true };
    try {
      const res = await askAI('Why is this area hot?', context);
      setAiState({ loading: false, error: res.success ? null : (res.message || 'AI explanation unavailable.'), result: res.success ? res : null });
    } catch {
      setAiState({ loading: false, error: 'AI explanation unavailable.', result: null });
    }
  };

  if (!location) return null;

  const lat = Number(location.lat).toFixed(5);
  const lng = Number(location.lng).toFixed(5);
  const radiusM = osm?.radiusM ?? 150;

  // density per km² within the circular buffer
  const km2 = Math.PI * (radiusM / 1000) ** 2 || 1;
  const buildingDensity = osm?.buildings != null ? (osm.buildings / km2) : null;
  const roadDensity = osm?.roadLengthM != null ? (osm.roadLengthM / 1000 / km2) : null;
  const treeDensity = osm?.trees != null ? (osm.trees / km2) : null;
  const greenAreaM2 = osm?.greenAreaM2 ?? 0;

  const rows = [
    {
      label: 'Location', icon: MapPin, color: '#0284c7',
      value: location.name || 'Selected point',
      meta: 'Map click'
    },
    {
      label: 'Coordinates', icon: MapPin, color: '#64748b',
      value: `${lat}° N, ${lng}° E`,
      meta: 'WGS84'
    },
    {
      label: 'Building Density', icon: Building2, color: '#2563eb',
      value: buildingDensity != null ? `${Math.round(buildingDensity)} /km²` : 'N/A',
      meta: `OSM buildings within ${radiusM} m (real)`
    },
    {
      label: 'Road Density', icon: Route, color: '#f97316',
      value: roadDensity != null ? `${roadDensity.toFixed(2)} km/km²` : 'N/A',
      meta: `OSM roads within ${radiusM} m (real)`
    },
    {
      label: 'Tree Density', icon: Trees, color: '#16a34a',
      value: treeDensity != null ? `${Math.round(treeDensity)} /km²` : 'N/A',
      meta: `OSM natural (tree/wood/scrub) within ${radiusM} m (real)`
    },
    {
      label: 'Green Cover', icon: Leaf, color: '#16a34a',
      value: osm?.greenCount ? `${Math.round(greenAreaM2 / 10000 * 10) / 10} ha nearby` : 'N/A',
      meta: 'OSM green/natural polygons (real, approximate)'
    },
    {
      label: 'Water', icon: Waves, color: '#0ea5e9',
      value: osm?.waterAreaM2 ? `${Math.round(osm.waterAreaM2 / 10000 * 10) / 10} ha nearby` : 'None nearby',
      meta: 'OSM water polygons (real)'
    },
    {
      label: 'LST', icon: ThermometerSun, color: '#dc2626',
      value: availability?.lst ? '—' : 'Data unavailable',
      meta: availability?.lst ? 'Landsat (30 m)' : 'Run gis-engine pipeline (Landsat LST)'
    },
    {
      label: 'Heat Class', icon: ThermometerSun, color: '#b91c1c',
      value: availability?.heat_class ? '—' : 'Data unavailable',
      meta: 'Requires heat-class raster'
    },
    {
      label: 'NDVI', icon: Leaf, color: '#16a34a',
      value: availability?.ndvi ? '—' : 'Data unavailable',
      meta: 'Requires Sentinel-2 NDVI raster'
    },
    {
      label: 'Vegetation Density', icon: Leaf, color: '#65a30d',
      value: availability?.vegetation_density ? '—' : 'Data unavailable',
      meta: 'Requires vegetation-density raster'
    },
    {
      label: 'Land Cover', icon: MapPin, color: '#d97706',
      value: availability?.land_cover ? '—' : 'Data unavailable',
      meta: 'Requires land-cover raster'
    },
    {
      label: 'Elevation', icon: MapPin, color: '#8c510a',
      value: availability?.elevation ? '—' : 'Data unavailable',
      meta: 'Requires DEM'
    },
    {
      label: 'Slope', icon: MapPin, color: '#4d004b',
      value: availability?.slope ? '—' : 'Data unavailable',
      meta: 'Requires slope raster'
    },
    {
      label: 'AQI', icon: Gauge, color: '#d97706',
      value: availability?.aqi ? '—' : 'Data unavailable',
      meta: 'Requires AQI interpolation raster'
    },
    {
      label: 'PM2.5', icon: Gauge, color: '#b45309',
      value: availability?.aqi ? '—' : 'Data unavailable',
      meta: 'Requires AQI pollutants raster'
    },
    {
      label: 'Weather', icon: CloudSun, color: '#0284c7',
      value: liveWeather?.temperature != null
        ? `${liveWeather.temperature} °C · ${liveWeather.humidity}% RH · ${liveWeather.windSpeed} km/h`
        : 'Unavailable',
      meta: liveWeather ? `LIVE ${liveWeather.source || 'OpenWeather'}` : 'OpenWeather API offline'
    },
    {
      label: 'Predicted LST (AI)', icon: Bot, color: '#9333ea',
      value: modelInfo?.available ? '—' : 'Prediction unavailable',
      meta: modelInfo?.available
        ? `XGBoost v${modelInfo.version || '?'} · requires cell feature data`
        : 'Requires trained model + cell feature data (models/best_model.pkl)'
    }
  ];

  return (
    <div className="area-panel theme-panel">
      <div className="area-panel-head">
        <div>
          <span className="area-panel-kicker">SELECTED AREA</span>
          <strong>{location.name || 'Selected point'}</strong>
        </div>
        <button className="area-panel-close" onClick={onClose} aria-label="Close">
          <X size={16} />
        </button>
      </div>

      <div className="area-rows">
        {rows.map((row) => {
          const Icon = row.icon;
          const unavailable = row.value === 'Data unavailable';
          return (
            <div className="area-row" key={row.label}>
              <span className="area-row-label"><Icon size={13} color={row.color} /> {row.label}</span>
              <span className={`area-row-value ${unavailable ? 'unavailable' : ''}`}>{row.value}</span>
              <small className="area-row-meta">{row.meta}</small>
            </div>
          );
        })}
      </div>

      {/* WHY THIS PREDICTION? - Nemotron explanation (Session 5) */}
      <div className="area-panel-why">
        <BrainCircuit size={13} color="#9333ea" />
        <span>
          <strong>WHY THIS PREDICTION?</strong>
        </span>
        <button className="ai-mini-btn" onClick={explainArea} disabled={aiState.loading} title="Ask Nemotron to explain this area">
          {aiState.loading ? <Loader2 size={12} className="spin" /> : <Sparkles size={12} />}
          {aiState.loading ? 'Analyzing…' : 'Explain this area (AI)'}
        </button>
      </div>

      {aiState.error && (
        <div className="ai-inline-error"><AlertTriangle size={12} /> {aiState.error}</div>
      )}
      {aiState.result?.answer && (
        <div className="ai-inline-answer">
          <p>{aiState.result.answer}</p>
          {aiState.result.data_used?.length > 0 && (
            <div className="ai-inline-used">
              {aiState.result.data_used.map((d) => <span key={d} className="ai-meta-chip ok">✓ {d}</span>)}
            </div>
          )}
        </div>
      )}

      <div className="area-panel-foot">
        Data source & resolution are listed per row. Density metrics are computed
        client-side from the real OSM layers loaded into the 3D map. AI prediction
        requires the trained model artifact and per-cell feature data.
      </div>
    </div>
  );
};

export default SelectedAreaPanel;
