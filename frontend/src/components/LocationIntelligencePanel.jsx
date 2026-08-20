import React, { useEffect, useState } from 'react';
import {
  X, MapPin, ThermometerSun, Leaf, Gauge, Building2, Trees, Mountain,
  CloudSun, Bot, Loader2, AlertTriangle, Sparkles, Info, Crosshair, Droplets, Sun
} from 'lucide-react';
import { fetchCityPoint, fetchExplain } from '../services/cityClient';
import { askAI } from '../services/backendClient';

const fmt = (v, digits = 1) => (v === null || v === undefined || Number.isNaN(v) ? '—' : Number(v).toFixed(digits));

const LANDCOVER_NAMES = { 1: 'Water', 2: 'Vegetation', 3: 'Built-up', 4: 'Bare Land' };
const VEGDENSITY_NAMES = { 1: 'Very Low', 2: 'Low', 3: 'Moderate', 4: 'High', 5: 'Very High' };

const ENV_ROWS = [
  { key: 'MeanLST', label: 'Surface Temperature', icon: ThermometerSun, color: '#dc2626', unit: '°C', digits: 1 },
  { key: 'Predicted_LST', label: 'Predicted LST (AI)', icon: Bot, color: '#9333ea', unit: '°C', digits: 1 },
  { key: 'MeanAQI', label: 'AQI', icon: Gauge, color: '#d97706', unit: '', digits: 0 },
  { key: 'MeanPM25', label: 'PM2.5', icon: Gauge, color: '#b45309', unit: 'µg/m³', digits: 1 },
  { key: 'MeanNDVI', label: 'NDVI', icon: Leaf, color: '#16a34a', unit: '', digits: 2 },
  { key: 'GreenCover', label: 'Green Cover', icon: Leaf, color: '#65a30d', unit: '%', digits: 0 },
  { key: 'BuildingCoveragePct', label: 'Building Coverage', icon: Building2, color: '#2563eb', unit: '%', digits: 0 },
  { key: 'TreeDensity', label: 'Tree Density', icon: Trees, color: '#15803d', unit: '/km²', digits: 1 },
  { key: 'MeanElevation', label: 'Elevation', icon: Mountain, color: '#8c510a', unit: 'm', digits: 0 },
  { key: 'MeanSlope', label: 'Slope', icon: Mountain, color: '#4d004b', unit: '°', digits: 1 },
  { key: 'DistToPark', label: 'Distance to Green Space', icon: Leaf, color: '#22c55e', unit: 'm', digits: 0 },
  { key: 'MeanPM10', label: 'PM10', icon: Gauge, color: '#a16207', unit: 'µg/m³', digits: 1 },
  { key: 'MeanNO2', label: 'NO₂', icon: Gauge, color: '#a16207', unit: 'µg/m³', digits: 1 },
  { key: 'MeanSO2', label: 'SO₂', icon: Gauge, color: '#a16207', unit: 'µg/m³', digits: 1 },
  { key: 'MeanO3', label: 'O₃', icon: Gauge, color: '#a16207', unit: 'µg/m³', digits: 1 },
  { key: 'MeanCO', label: 'CO', icon: Gauge, color: '#a16207', unit: 'mg/m³', digits: 1 }
];

const RISK_LABELS = {
  heat: { label: 'Heat Risk', icon: Sun, color: '#dc2626' },
  air_quality: { label: 'Air Quality Risk', icon: Droplets, color: '#d97706' },
  vegetation: { label: 'Vegetation Stress', icon: Leaf, color: '#16a34a' },
  urban_density: { label: 'Urban Density', icon: Building2, color: '#2563eb' }
};

const riskTone = (tone) => (tone === 'high' ? 'risk-high' : tone === 'moderate' ? 'risk-moderate' : 'risk-low');

export const LocationIntelligencePanel = ({ location, liveWeather, onClose }) => {
  const [profile, setProfile] = useState(null);
  const [loading, setLoading] = useState(true);
  const [explain, setExplain] = useState(null);
  const [explainLoading, setExplainLoading] = useState(false);
  const [aiState, setAiState] = useState({ loading: false, error: null, result: null });

  useEffect(() => {
    let stale = false;
    setLoading(true);
    setProfile(null);
    setExplain(null);
    fetchCityPoint(location.lat, location.lng)
      .then((data) => { if (!stale) setProfile(data); })
      .catch(() => { if (!stale) setProfile({ available: false, message: 'City data service unavailable.' }); })
      .finally(() => { if (!stale) setLoading(false); });
    return () => { stale = true; };
  }, [location.lat, location.lng]);

  if (!location) return null;

  const loadExplain = async () => {
    if (explainLoading) return;
    setExplainLoading(true);
    setExplain(null);
    try {
      const data = await fetchExplain(location.lat, location.lng);
      setExplain(data.explanation || null);
    } catch {
      setExplain({ error: 'Explanation unavailable.' });
    } finally {
      setExplainLoading(false);
    }
  };

  const explainWithAI = async () => {
    if (aiState.loading) return;
    setAiState({ loading: true, error: null, result: null });
    const env = profile?.environment || {};
    const context = {
      location: { name: location.name, lat: location.lat, lng: location.lng },
      environment: {
        lst: env.MeanLST,
        ndvi: env.MeanNDVI,
        green_cover: env.GreenCover,
        aqi: env.MeanAQI,
        predicted_lst: env.Predicted_LST
      },
      urban: {
        building_coverage_pct: env.BuildingCoveragePct,
        tree_density: env.TreeDensity
      },
      weather: liveWeather?.temperature != null ? { temperature: liveWeather.temperature } : null
    };
    try {
      const res = await askAI('Why is this area hot?', context);
      setAiState({
        loading: false,
        error: res.success ? null : (res.message || 'AI explanation unavailable.'),
        result: res.success ? res : null
      });
    } catch {
      setAiState({ loading: false, error: 'AI explanation unavailable.', result: null });
    }
  };

  const env = profile?.environment || {};
  const risk = profile?.risk || {};

  return (
    <div className="loc-panel">
      <div className="loc-panel-head">
        <div>
          <span className="loc-panel-kicker"><Crosshair size={11} /> LOCATION INTELLIGENCE</span>
          <strong className="loc-panel-name">{location.name || 'Selected point'}</strong>
        </div>
        <button className="loc-panel-close" onClick={onClose} aria-label="Close location panel">
          <X size={15} />
        </button>
      </div>

      {loading ? (
        <div className="loc-loading"><Loader2 size={16} className="spin" /> Reading nearest grid cell…</div>
      ) : profile?.available === false ? (
        <div className="loc-error"><AlertTriangle size={14} /> {profile.message || 'Data unavailable at this point.'}</div>
      ) : (
        <>
          {/* Coordinates + nearest cell */}
          <div className="loc-coords">
            <span><MapPin size={12} /> {Number(location.lat).toFixed(5)}° N, {Number(location.lng).toFixed(5)}° E</span>
            <span className="loc-cell">Grid cell {profile.grid_id} · {fmt(profile.distance_m, 0)} m away</span>
          </div>

          {/* Environment */}
          <div className="loc-section">
            <div className="loc-section-title">ENVIRONMENT</div>
            <div className="loc-grid">
              {ENV_ROWS.map((row) => {
                const value = env[row.key];
                const present = value !== null && value !== undefined && !Number.isNaN(value);
                return (
                  <div className="loc-cell-item" key={row.key}>
                    <span className="loc-cell-label"><row.icon size={11} color={row.color} /> {row.label}</span>
                    <strong className={present ? '' : 'loc-na'}>
                      {present ? `${fmt(value, row.digits)}${row.unit ? ` ${row.unit}` : ''}` : 'Unavailable'}
                    </strong>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Classification chips */}
          <div className="loc-chips">
            {profile.uhi_class && <span className="loc-chip heat">UHI: {profile.uhi_class}</span>}
            {profile.aqi_category && <span className="loc-chip aqi">AQI: {profile.aqi_category}</span>}
            {env.LandCoverClass != null && <span className="loc-chip lc">Land: {LANDCOVER_NAMES[env.LandCoverClass] || env.LandCoverClass}</span>}
            {env.VegetationDensity != null && <span className="loc-chip veg">Veg: {VEGDENSITY_NAMES[env.VegetationDensity] || env.VegetationDensity}</span>}
          </div>

          {/* Risk */}
          <div className="loc-section">
            <div className="loc-section-title">RISK</div>
            <div className="loc-risk-grid">
              {Object.entries(RISK_LABELS).map(([key, def]) => {
                const r = risk[key] || {};
                return (
                  <div className={`loc-risk-item ${riskTone(r.tone)}`} key={key}>
                    <span className="loc-risk-label"><def.icon size={12} color={def.color} /> {def.label}</span>
                    <strong>{r.level || 'Unavailable'}</strong>
                    <small>{r.label || '—'}</small>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Data source */}
          <div className="loc-source">
            <Info size={12} />
            <span>
              <strong>Data source:</strong> {profile.source?.dataset || '100 m feature grid'}
              {' '}· {profile.source?.resolution || '—'} · {profile.source?.method || '—'}
            </span>
          </div>

          {/* Why is this area hot? */}
          <div className="loc-why">
            <button className="loc-why-btn" onClick={loadExplain} disabled={explainLoading}>
              {explainLoading ? <Loader2 size={13} className="spin" /> : <Sparkles size={13} />}
              WHY IS THIS AREA HOT?
            </button>
            {explain?.error && <div className="loc-error"><AlertTriangle size={13} /> {explain.error}</div>}
            {explain && !explain.error && (
              <div className="loc-factors">
                {explain.factors?.map((f) => (
                  <div className="loc-factor" key={f.column}>
                    <span className="loc-factor-name">{f.feature}</span>
                    <span className="loc-factor-value">
                      {fmt(f.value, 2)} vs city mean {fmt(f.city_mean, 2)}
                      <small>{f.direction === 'above' ? '↑ above' : '↓ below'} city mean</small>
                    </span>
                    <span className="loc-factor-shap">SHAP {f.shap_importance.toFixed(3)}</span>
                  </div>
                ))}
                {explain.notes?.map((note) => (
                  <small className="loc-factors-note" key={note}>ℹ {note}</small>
                ))}
              </div>
            )}
            <button className="loc-ai-btn" onClick={explainWithAI} disabled={aiState.loading}>
              {aiState.loading ? <Loader2 size={12} className="spin" /> : <Bot size={12} />}
              {aiState.loading ? 'Analyzing…' : 'Ask AI to explain this area'}
            </button>
            {aiState.error && <div className="loc-error"><AlertTriangle size={12} /> {aiState.error}</div>}
            {aiState.result?.answer && (
              <div className="loc-ai-answer"><p>{aiState.result.answer}</p></div>
            )}
          </div>
        </>
      )}

      {liveWeather?.temperature != null && (
        <div className="loc-weather">
          <CloudSun size={13} color="#0284c7" />
          <span>Live air: {liveWeather.temperature} °C · {liveWeather.humidity ?? '—'}% RH · {liveWeather.windSpeed ?? '—'} km/h</span>
          <small>{liveWeather.source || 'OpenWeather'} (air, not LST)</small>
        </div>
      )}
    </div>
  );
};

export default LocationIntelligencePanel;
