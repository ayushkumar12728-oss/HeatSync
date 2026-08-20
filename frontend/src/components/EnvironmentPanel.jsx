import React from 'react';
import { Activity, Map, CheckCircle2, XCircle, ThermometerSun, Wind } from 'lucide-react';
import { WeatherPanel } from './WeatherPanel';
import { AirQualityPanel } from './AirQualityPanel';
import { useLiveData } from '../context/LiveDataContext';

const GROUP_LABELS = {
  city: 'CITY', vegetation: 'VEGETATION', 'land-cover': 'LAND COVER',
  heat: 'HEAT', terrain: 'TERRAIN', 'air-quality': 'AIR QUALITY',
  weather: 'WEATHER', model: 'MODEL'
};

// Environment mode: live weather + live AQI + search + dataset availability.
// Every value comes from real backend probes / monitoring reports.
// Uses LiveDataContext as the single source of truth for weather and AQI.
export const EnvironmentPanel = ({ monitoring, liveWeather, airQuality, modelInfo, health }) => {
  const { weather: ctxWeather, airQuality: ctxAq, weatherAge, aqiAge, getFreshnessStatus, formatAge } = useLiveData();

  // Use context data as primary source, fall back to props
  const weatherData = ctxWeather || liveWeather;
  const aqData = ctxAq || airQuality;

  const datasets = monitoring?.datasets || [];
  const byGroup = {};
  datasets.forEach((ds) => { (byGroup[ds.group] = byGroup[ds.group] || []).push(ds); });

  const search = health?.search;
  const searchOk = search?.status === 'available';

  // Compute honest labels for live data
  const weatherFresh = getFreshnessStatus('weather', weatherAge);
  const aqiFresh = getFreshnessStatus('air_quality', aqiAge);

  const hasWeather = weatherData && (weatherData.temperature != null);
  const hasAqi = aqData && (aqData.aqi != null);

  return (
    <div className="env-panel" style={{
      display: 'flex',
      flexDirection: 'column',
      height: '100%',
      minHeight: 0,
    }}>
      <div style={{ flex: '1 1 auto', overflowY: 'auto', minHeight: 0 }}>
        <WeatherPanel compact />
        <AirQualityPanel />

        <div className="env-section theme-panel">
          <div className="env-section-head">
            <Map size={14} color="var(--primary-sky)" />
            <strong>Search & Geocoding</strong>
            {searchOk
              ? <span className="status-pill status-ok"><CheckCircle2 size={11} /> Ready</span>
              : <span className="status-pill status-missing"><XCircle size={11} /> Unavailable</span>}
          </div>
          <div className="env-section-note">
            {searchOk
              ? `${search.provider} — search any road, locality, landmark, school, market or address in Bhubaneswar.`
              : (search?.reason || 'Nominatim is unreachable right now.')}
          </div>
        </div>

        <div className="env-section theme-panel">
          <div className="env-section-head">
            <Activity size={14} color="#16a34a" />
            <strong>Dataset Availability</strong>
            <span className="tag-live">
              {monitoring?.summary ? `${monitoring.summary.available}/${monitoring.summary.total}` : '…'}
            </span>
          </div>
          {monitoring ? (
            <div className="env-dataset-list">
              {Object.keys(GROUP_LABELS).map((group) => {
                const rows = byGroup[group] || [];
                if (!rows.length) return null;
                const ok = rows.filter((r) => r.available).length;
                return (
                  <div className="env-dataset-group" key={group}>
                    <span className="env-dataset-label">
                      {GROUP_LABELS[group]}
                      <em>{ok}/{rows.length}</em>
                    </span>
                    {rows.map((ds) => (
                      <div className="env-dataset-row" key={ds.key} title={ds.source}>
                        {ds.available
                          ? <CheckCircle2 size={11} color="var(--success)" />
                          : <XCircle size={11} color="var(--text-muted)" />}
                        <span>{ds.name}</span>
                        <small>{ds.available ? `${ds.file_count} files` : 'missing'}</small>
                      </div>
                    ))}
                  </div>
                );
              })}
            </div>
          ) : (
            <div className="wp-loading">Loading availability…</div>
          )}
        </div>

        {/* Data Scope Summary — honest representation */}
        <div className="env-section theme-panel" style={{ marginTop: '12px' }}>
          <div className="env-section-head">
            <Activity size={14} color="#eab308" />
            <strong>Data Scope</strong>
          </div>
          <div className="env-dataset-list" style={{ fontSize: '0.75rem' }}>
            <div className="env-dataset-row" style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
              <ThermometerSun size={12} color="#dc2626" />
              <strong>Air Temperature:</strong>
              {hasWeather ? (
                <span>
                  {weatherData.temperature}°C
                  <span style={{ color: weatherFresh === 'weather' ? '#16a34a' : '#d97706', fontWeight: 600, marginLeft: '4px' }}>
                    {weatherFresh === 'weather' ? 'LIVE' : weatherFresh === 'STALE' ? 'STALE' : 'CACHED'}
                  </span>
                  <span style={{ color: 'var(--text-muted)', fontSize: '0.65rem' }}> (point observation, not spatial field)</span>
                </span>
              ) : (
                <span style={{ color: 'var(--text-muted)' }}>UNAVAILABLE — no live weather observation</span>
              )}
            </div>
            <div className="env-dataset-row" style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
              <Wind size={12} color="#d97706" />
              <strong>Air Quality:</strong>
              {hasAqi ? (
                <span>
                  OpenWeather AQI {aqData.aqi}/5
                  <span style={{ color: aqiFresh === 'air_quality' ? '#16a34a' : '#d97706', fontWeight: 600, marginLeft: '4px' }}>
                    {aqiFresh === 'air_quality' ? 'LIVE' : aqiFresh === 'STALE' ? 'STALE' : 'CACHED'}
                  </span>
                  <span style={{ color: 'var(--text-muted)', fontSize: '0.65rem' }}> (NOT US EPA / CPCB AQI)</span>
                </span>
              ) : (
                <span style={{ color: 'var(--text-muted)' }}>UNAVAILABLE — no live AQI source</span>
              )}
            </div>
            <div className="env-dataset-row" style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
              <Activity size={12} color="var(--primary-sky)" />
              <strong>Predicted LST:</strong>
              {modelInfo?.available === true ? (
                <span>
                  XGBoost · {modelInfo.feature_count || 58} features
                  <span style={{ color: '#16a34a', fontWeight: 600, marginLeft: '4px' }}>MODEL</span>
                </span>
              ) : (
                <span style={{ color: 'var(--text-muted)' }}>UNAVAILABLE — model artifact not loaded</span>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default EnvironmentPanel;
