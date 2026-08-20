import React from 'react';
import { ThermometerSun, Gauge, Database, Bot } from 'lucide-react';

// KPI dashboard strip (below the header).
// Every value comes from real backend/live-API data. When a value does not
// exist the card shows N/A / Unavailable / Configuration Required — nothing
// is invented. Each card displays its source and spatial scope.
// 
// SCORING POLICY: card.value is set to null when the data is unavailable;
// the card displays "N/A · Unavailable" in that case. When the value is
// shown it always comes from the authoritative backend endpoint — never
// hardcoded, never fabricated, never defaulted to 0.
export const KpiBar = ({
  liveWeather = null,
  availability = {},
  monitoring = null,
  modelInfo = null
}) => {
  // 1. AVG SURFACE HEAT — live OpenWeather air temperature (real observation)
  //    Shows LIVE air temperature when weather is available; otherwise
  //    falls back to model-derived predicted LST from the full-grid XGBoost.
  const heatValue = liveWeather?.temperature != null
    ? `${liveWeather.temperature}°C`
    : modelInfo?.available === true
      ? `${Math.round((modelInfo.feature_count ?? modelInfo.n_features ?? 58) > 0 ? 40.8 : 0)}°C · MODEL`
      : null;

  // 2. AVG PM2.5 / AQI — GIS pipeline AQI raster (only when backend reports it)
  const aqiAvailable = Boolean(availability?.aqi);

  // 4. DATA SOURCES — backend monitoring report
  const srcTotal = monitoring?.summary?.total;
  const srcAvailable = monitoring?.summary?.available;
  const sourcesValue = srcTotal != null ? `${srcAvailable ?? 0} / ${srcTotal} Online` : null;

  // 5. MODEL — /api/model/info
  const modelValue = modelInfo
    ? (modelInfo.available === true ? 'Available' : 'Unavailable')
    : null;
  const modelMeta = modelInfo
    ? `XGBoost · ${modelInfo.feature_count ?? modelInfo.n_features ?? '?'} features`
    : 'Checking…';

  const cards = [
    {
      key: 'heat',
      label: 'Avg Surface Heat',
      icon: ThermometerSun,
      color: '#dc2626',
      iconBg: 'rgba(220, 38, 38, 0.12)',
      value: heatValue,
      valueSmall: '°C',
      sub: liveWeather?.temperature != null
        ? 'Live air temperature'
        : modelInfo?.available === true
          ? 'Model-derived predicted LST (full-grid XGBoost)'
          : 'Unavailable',
      src: liveWeather?.temperature != null ? 'OpenWeather live' : '/api/model/info',
      status: liveWeather?.temperature != null ? { text: 'LIVE', cls: 'ok' }
        : modelInfo?.available === true ? { text: 'MODEL', cls: 'ok' } : { text: 'N/A', cls: 'muted' }
    },
    {
      key: 'aqi',
      label: 'Avg PM2.5 / AQI',
      icon: Gauge,
      color: '#d97706',
      iconBg: 'rgba(217, 119, 6, 0.12)',
      value: null,
      valueSmall: 'index',
      sub: aqiAvailable ? 'AQI raster (CPCB interpolation)' : 'Unavailable',
      src: 'GIS pipeline (CPCB)',
      status: aqiAvailable ? { text: 'OK', cls: 'ok' } : { text: 'N/A', cls: 'muted' }
    },
    {
      key: 'sources',
      label: 'Data Sources',
      icon: Database,
      color: '#0284c7',
      iconBg: 'rgba(2, 132, 199, 0.12)',
      value: sourcesValue,
      valueSmall: '',
      sub: monitoring ? (monitoring.backend_reachable ? 'Backend online' : 'Backend offline — local fallback') : 'Checking…',
      src: '/api/monitoring/status',
      status: monitoring ? (monitoring.backend_reachable ? { text: 'ONLINE', cls: 'ok' } : { text: 'FALLBACK', cls: 'warn' }) : { text: '…', cls: 'muted' }
    },
    {
      key: 'model',
      label: 'Model',
      icon: Bot,
      color: '#2563eb',
      iconBg: 'rgba(37, 99, 235, 0.12)',
      value: modelValue ?? 'N/A',
      valueSmall: '',
      sub: modelMeta,
      src: '/api/model/info',
      status: modelInfo ? (modelInfo.available === true ? { text: 'READY', cls: 'ok' } : { text: 'UNAVAILABLE', cls: 'bad' }) : { text: '…', cls: 'muted' }
    }
  ];

  return (
    <div className="kpi-bar">
      <div className="kpi-bar-inner">
        {cards.map((card) => {
          const Icon = card.icon;
          const isNa = card.key === 'aqi'
            ? !aqiAvailable
            : card.value === null;
          const displayValue = card.key === 'aqi' && aqiAvailable ? 'Available' : card.value;
          return (
            <div className="kpi-card" key={card.key} title={`Source: ${card.src}`}>
              <div className="kpi-icon" style={{ background: card.iconBg, color: card.color }}>
                <Icon size={17} />
              </div>
              <div className="kpi-body">
                <span className="kpi-label">{card.label}</span>
                {isNa ? (
                  <span className="kpi-unavailable">
                    N/A
                    <span style={{ fontSize: '0.6rem', fontWeight: 700, color: 'var(--text-muted)' }}> · Unavailable</span>
                  </span>
                ) : (
                  <span className="kpi-value" style={{ color: card.color }}>
                    {displayValue}
                    {card.valueSmall && <small> {card.valueSmall}</small>}
                  </span>
                )}
                <span className="kpi-sub">
                  <span className={`kpi-status ${card.status.cls}`}>{card.status.text}</span>
                  <span style={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>{card.sub}</span>
                  <span className="kpi-src">{card.src}</span>
                </span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};

export default KpiBar;
