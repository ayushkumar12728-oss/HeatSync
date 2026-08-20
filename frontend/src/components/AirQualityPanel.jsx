import React from 'react';
import { Wind, AlertTriangle, X, Clock } from 'lucide-react';
import { useLiveData } from '../context/LiveDataContext';

const fmtTime = (iso) => {
  if (!iso) return '—';
  try {
    return new Date(iso).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
  } catch {
    return '—';
  }
};

const fmt = (v, d = 1) => (v === null || v === undefined || Number.isNaN(v) ? null : Number(v).toFixed(d));

/**
 * AirQualityPanel — reads from LiveDataContext (single source of truth).
 * Never makes independent API calls. Always shows honest freshness status.
 */
export const AirQualityPanel = ({ onClose = null, initial = null }) => {
  const { airQuality: ctxAirQuality, aqiAge, getFreshnessStatus, formatAge, sourceStatus } = useLiveData();

  // Use context data, falling back to prop if provided
  const aqData = ctxAirQuality || initial;

  if (!aqData) {
    return (
      <div className="wp-panel theme-panel">
        <div className="wp-head">
          <Wind size={15} color="#d97706" />
          <strong>Air Quality</strong>
          {onClose && <button className="wp-close" onClick={onClose} aria-label="Close air quality"><X size={14} /></button>}
        </div>
        <div className="wp-unavailable">
          <AlertTriangle size={14} />
          <div>
            <strong>AQI unavailable</strong>
            <span>No live AQI source configured — nothing shown rather than fake values.</span>
          </div>
        </div>
      </div>
    );
  }

  // Compute freshness
  const aqiStatus = getFreshnessStatus('air_quality', aqiAge);
  const isLive = aqiStatus === 'air_quality' && aqiAge != null && aqiAge < 600;
  const isStale = aqiStatus === 'STALE';
  const isCached = !isLive && !isStale && aqData.observed_at;

  // AQI 1-5 scale — OpenWeather only
  const aqi = aqData.aqi;
  const aqiLabel = aqData.aqi_label;
  const aqiScale = aqData.aqi_scale || 'OpenWeather 1-5';

  const getAqiColor = (val) => {
    if (val === 1) return '#16a34a';
    if (val === 2) return '#65a30d';
    if (val === 3) return '#eab308';
    if (val === 4) return '#f97316';
    if (val === 5) return '#dc2626';
    return 'var(--text-secondary)';
  };

  const pollutants = [
    { label: 'PM2.5', value: aqData.pm25, unit: 'µg/m³' },
    { label: 'PM10', value: aqData.pm10, unit: 'µg/m³' },
    { label: 'NO₂', value: aqData.no2, unit: 'µg/m³' },
    { label: 'O₃', value: aqData.o3, unit: 'µg/m³' },
    { label: 'SO₂', value: aqData.so2, unit: 'µg/m³' },
    { label: 'CO', value: aqData.co, unit: 'mg/m³' },
  ];

  return (
    <div className="wp-panel theme-panel">
      <div className="wp-head">
        <Wind size={15} color="#d97706" />
        <strong>Air Quality — Bhubaneswar</strong>
        {isLive ? (
          <span className="wp-fresh live">LIVE</span>
        ) : isStale ? (
          <span className="wp-fresh" style={{ color: '#d97706' }}>STALE</span>
        ) : isCached ? (
          <span className="wp-fresh" style={{ color: '#94a3b8' }}>CACHED</span>
        ) : (
          <span className="wp-fresh" style={{ color: '#94a3b8' }}>UPDATED</span>
        )}
        {onClose && <button className="wp-close" onClick={onClose} aria-label="Close air quality"><X size={14} /></button>}
      </div>

      <div className="aq-main">
        <div className="aq-value" style={{ color: getAqiColor(aqi) }}>
          {aqi != null ? `${aqi} / 5` : '—'}
          <small>OpenWeather AQI</small>
        </div>
        <div className="aq-cat">
          <strong style={{ color: getAqiColor(aqi) }}>
            {aqiLabel || (aqi != null ? `Level ${aqi}` : 'No live value')}
          </strong>
          <span>{aqiScale}</span>
          <span style={{ fontSize: '0.58rem', color: 'var(--text-muted)' }}>NOT US EPA / Indian CPCB AQI</span>
        </div>
      </div>

      <div className="aq-pollutants">
        {pollutants.map((p) => (
          <div className="aq-pollutant" key={p.label}>
            <span>{p.label}</span>
            <strong>
              {p.value != null && !Number.isNaN(p.value)
                ? `${fmt(p.value)} ${p.unit}`
                : <span className="muted">—</span>
              }
            </strong>
          </div>
        ))}
      </div>

      <div className="wp-foot">
        <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
          <Clock size={11} />
          Source: OpenWeather · Scale: 1-5
        </span>
        <span>Updated: {aqiAge != null ? formatAge(aqiAge) : '—'}</span>
        <span style={{ fontSize: '0.56rem', color: 'var(--text-muted)' }}>
          * Pollutant concentrations in µg/m³ (CO in mg/m³)
        </span>
      </div>
    </div>
  );
};

export default AirQualityPanel;
