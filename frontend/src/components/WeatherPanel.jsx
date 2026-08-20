import React from 'react';
import {
  ThermometerSun, Droplets, Wind, Gauge, CloudRain, CloudSun,
  Sun, Activity, AlertTriangle, Clock, X
} from 'lucide-react';
import { useLiveData } from '../context/LiveDataContext';

const fmtTime = (iso) => {
  if (!iso) return '—';
  try {
    return new Date(iso).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  } catch {
    return '—';
  }
};

// OpenWeather condition text from the backend; a numeric code is only a fallback.
const conditionLabel = (description, code) => {
  if (description) return description;
  return code === null || code === undefined ? '—' : `Condition ${code}`;
};

/**
 * WeatherPanel — reads from LiveDataContext (single source of truth).
 * Never makes independent API calls. Always shows honest freshness status.
 */
export const WeatherPanel = ({ compact = false, onClose = null, initial = null }) => {
  const { weather: ctxWeather, weatherAge, getFreshnessStatus, formatAge } = useLiveData();

  const weather = ctxWeather || initial;

  if (!weather) {
    return (
      <div className="wp-panel theme-panel">
        <div className="wp-head">
          <CloudSun size={15} color="var(--primary-sky)" />
          <strong>Live Weather</strong>
          {onClose && <button className="wp-close" onClick={onClose} aria-label="Close weather"><X size={14} /></button>}
        </div>
        <div className="wp-unavailable">
          <AlertTriangle size={14} />
          <div>
            <strong>Unavailable</strong>
            <span>No live weather source configured.</span>
          </div>
        </div>
      </div>
    );
  }

  // Compute freshness
  const weatherStatus = getFreshnessStatus('weather', weatherAge);
  const isLive = weatherStatus === 'weather' && weatherAge != null && weatherAge < 600;
  const isStale = weatherStatus === 'STALE';
  const isCached = !isLive && !isStale && weather.observed_at;

  // Check if value is actually available
  const hasValue = (v) => v !== null && v !== undefined && !Number.isNaN(v);

  const metrics = [
    { label: 'Temperature', value: hasValue(weather.temperature) ? `${weather.temperature} °C` : null, icon: ThermometerSun, color: '#dc2626' },
    { label: 'Feels Like', value: hasValue(weather.feelsLike) ? `${weather.feelsLike} °C` : null, icon: Activity, color: '#b91c1c' },
    { label: 'Humidity', value: hasValue(weather.humidity) ? `${weather.humidity} %` : null, icon: Droplets, color: '#0284c7' },
    { label: 'Wind', value: hasValue(weather.windSpeed) ? `${weather.windSpeed} km/h` : null, icon: Wind, color: '#7c3aed' },
    { label: 'Pressure', value: hasValue(weather.pressure) ? `${weather.pressure} hPa` : null, icon: Gauge, color: '#64748b' },
    { label: 'Precipitation', value: hasValue(weather.precipitation) ? `${weather.precipitation} mm` : null, icon: CloudRain, color: '#0ea5e9' },
    { label: 'Cloud Cover', value: hasValue(weather.cloudCover) ? `${weather.cloudCover} %` : null, icon: CloudSun, color: '#475569' },
    { label: 'Visibility', value: hasValue(weather.visibility) ? `${(weather.visibility / 1000).toFixed(1)} km` : null, icon: Sun, color: '#d97706' },
  ];

  return (
    <div className="wp-panel theme-panel">
      <div className="wp-head">
        <CloudSun size={15} color="var(--primary-sky)" />
        <strong>Live Weather — Bhubaneswar</strong>
        {isLive ? (
          <span className="wp-fresh live">LIVE</span>
        ) : isStale ? (
          <span className="wp-fresh" style={{ color: '#d97706' }}>STALE</span>
        ) : isCached ? (
          <span className="wp-fresh" style={{ color: '#94a3b8' }}>CACHED</span>
        ) : (
          <span className="wp-fresh" style={{ color: '#94a3b8' }}>UPDATED</span>
        )}
        {onClose && <button className="wp-close" onClick={onClose} aria-label="Close weather"><X size={14} /></button>}
      </div>

      <div className="wp-condition">
        <div className="wp-temp">
          {hasValue(weather.temperature) ? `${weather.temperature} °C` : '—'}
        </div>
        <div className="wp-cond-detail">
          <strong>{conditionLabel(weather.weatherDescription, weather.weatherCode)}</strong>
          {hasValue(weather.feelsLike) && weather.feelsLike !== weather.temperature && (
            <span>Feels like {weather.feelsLike} °C</span>
          )}
        </div>
      </div>

      <div className={`wp-metrics ${compact ? 'wp-metrics-compact' : ''}`}>
        {metrics.map((m) => {
          const Icon = m.icon;
          return (
            <div className="wp-metric" key={m.label}>
              <span className="wp-metric-label"><Icon size={12} color={m.color} /> {m.label}</span>
              <strong>{m.value != null ? m.value : <span className="muted">—</span>}</strong>
            </div>
          );
        })}
      </div>

      <div className="wp-foot">
        <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
          <Clock size={11} />
          Source: OpenWeather · LIVE air temperature (not LST)
        </span>
        <span>Observed: {weatherAge != null ? formatAge(weatherAge) : '—'}</span>
      </div>
    </div>
  );
};

export default WeatherPanel;
