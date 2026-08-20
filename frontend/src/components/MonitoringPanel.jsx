import React from 'react';
import { Activity, CloudSun, Database, ThermometerSun, Droplets, Wind, Gauge, Sun, CheckCircle2, XCircle, Loader2, Bot, BrainCircuit } from 'lucide-react';
import { heatIndexCelsius } from '../services/thematicData';

const GROUP_LABELS = {
  city: 'CITY',
  vegetation: 'VEGETATION',
  'land-cover': 'LAND COVER',
  heat: 'HEAT',
  terrain: 'TERRAIN',
  'air-quality': 'AIR QUALITY',
  weather: 'WEATHER',
  model: 'MODEL'
};

// Data-status pills: loading / available / unavailable
const StatusPill = ({ status }) => {
  if (status === 'loading') {
    return <span className="status-pill status-loading"><Loader2 size={12} className="spin" /> Loading…</span>;
  }
  if (status === 'available') {
    return <span className="status-pill status-ok"><CheckCircle2 size={12} /> Available</span>;
  }
  return <span className="status-pill status-missing"><XCircle size={12} /> Unavailable</span>;
};

const formatDate = (iso) => {
  if (!iso) return '—';
  try {
    return new Date(iso).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
  } catch {
    return '—';
  }
};

// Weather monitoring section - real OpenWeather current observations.
const WeatherMonitoring = ({ liveWeather, onRefresh }) => {
  const status = liveWeather === null
    ? 'loading'
    : liveWeather?.status === 'available'
      ? 'available'
      : 'unavailable';
  const heatIdx = heatIndexCelsius(liveWeather?.temperature ?? null, liveWeather?.humidity ?? null);
  const metrics = [
    { label: 'Temperature', value: liveWeather?.temperature != null ? `${liveWeather.temperature} °C` : null, icon: ThermometerSun, color: '#dc2626' },
    { label: 'Humidity', value: liveWeather?.humidity != null ? `${liveWeather.humidity} %` : null, icon: Droplets, color: '#0284c7' },
    { label: 'Wind Speed', value: liveWeather?.windSpeed != null ? `${liveWeather.windSpeed} km/h` : null, icon: Wind, color: '#7c3aed' },
    { label: 'Pressure', value: liveWeather?.pressure != null ? `${liveWeather.pressure} hPa` : null, icon: Gauge, color: '#64748b' },
    { label: 'Solar Irradiance', value: liveWeather?.solarIrradiance != null ? `${liveWeather.solarIrradiance} W/m²` : null, icon: Sun, color: '#d97706' },
    { label: 'Heat Index', value: heatIdx != null ? `${heatIdx} °C` : null, icon: Activity, color: '#b91c1c' }
  ];

  return (
    <div className="monitoring-section">
      <div className="monitoring-section-head">
        <CloudSun size={16} color="var(--primary-sky)" />
        <strong>Weather Monitoring</strong>
        {status === 'loading' && <StatusPill status="loading" />}
        {status === 'available' && <span className="tag-live">LATEST OBSERVATION</span>}
        {status === 'unavailable' && (
          <>
            <StatusPill status="unavailable" />
            {onRefresh && (
              <button className="monitoring-retry" onClick={onRefresh} type="button">Retry</button>
            )}
          </>
        )}
      </div>
      <div className="weather-metrics">
        {metrics.map((m) => {
          const Icon = m.icon;
          return (
            <div className="weather-metric" key={m.label}>
              <span className="weather-metric-label"><Icon size={13} color={m.color} /> {m.label}</span>
              <strong style={{ color: m.color }}>
                {m.value ?? <span className="muted">—</span>}
              </strong>
            </div>
          );
        })}
      </div>
      <div className="monitoring-meta">
        <span>Source: {liveWeather?.source || 'OpenWeather'}</span>
        <span>Type: LIVE API observation (not satellite-derived)</span>
        <span>Updated: {liveWeather?.fetchedAt ? new Date(liveWeather.fetchedAt).toLocaleTimeString() : '—'}</span>
        <span>Heat index: Rothfusz approximation when T ≥ 27 °C & RH ≥ 40%</span>
      </div>
    </div>
  );
};

// AI model status section - real info from /api/model/info (never claimed active).
const ModelStatusSection = ({ modelInfo }) => {
  const available = modelInfo?.available === true;
  return (
    <div className="monitoring-section">
      <div className="monitoring-section-head">
        <Bot size={16} color="#9333ea" />
        <strong>AI Model (XGBoost)</strong>
        <span className={`status-pill ${available ? 'status-ok' : 'status-missing'}`}>
          {modelInfo ? (available ? <><CheckCircle2 size={12} /> Available</> : <><XCircle size={12} /> Unavailable</>) : <><Loader2 size={12} className="spin" /> Checking…</>}
        </span>
      </div>
      {modelInfo && (
        <div className="dataset-status-list">
          <div className="dataset-row">
            <div className="dataset-name">
              <strong>Inference</strong>
              <small>{available ? 'Model loaded & ready for predictions' : 'Predictions disabled'}</small>
            </div>
            <div className="dataset-meta">
              <span>Status: {modelInfo.status}</span>
              <span>{available ? 'RUNNABLE' : 'model_unavailable'}</span>
            </div>
          </div>
          <div className="dataset-row">
            <div className="dataset-name">
              <strong>Model</strong>
              <small>Algorithm + version</small>
            </div>
            <div className="dataset-meta">
              <span>{modelInfo.model || '—'}</span>
              <span>v{modelInfo.version || '—'}</span>
            </div>
          </div>
          <div className="dataset-row">
            <div className="dataset-name">
              <strong>Feature set</strong>
              <small>Exact training-time feature list</small>
            </div>
            <div className="dataset-meta">
              <span>{modelInfo.feature_count != null ? `${modelInfo.feature_count} features` : '—'}</span>
              <span>source: leakage_report.json</span>
            </div>
          </div>
          <div className="dataset-row">
            <div className="dataset-name">
              <strong>Artifact</strong>
              <small>Required file on disk</small>
            </div>
            <div className="dataset-meta">
              <span>{available ? 'present' : 'missing'}</span>
              <span>models/best_model.pkl</span>
            </div>
          </div>
          {!available && modelInfo.missing_artifacts?.length > 0 && (
            <div className="layer-note" style={{ paddingLeft: 4 }}>
              Missing: {modelInfo.missing_artifacts.join(', ')} — run <code>python ai-engine/main.py</code>
            </div>
          )}
        </div>
      )}
    </div>
  );
};

// Nemotron AI status - configuration only, never claims active without a key.
const NemotronStatusRow = ({ aiStatus }) => {
  const configured = aiStatus?.status === 'configured';
  const status = !aiStatus ? 'loading' : configured ? 'available' : aiStatus.status === 'configuration_required' ? 'config' : 'offline';
  return (
    <div className="dataset-row">
      <div className="dataset-name">
        <strong style={{ display: 'flex', alignItems: 'center', gap: '5px' }}><BrainCircuit size={13} color="#9333ea" /> Nemotron AI</strong>
        <small>{aiStatus ? `${aiStatus.provider} · ${aiStatus.model}` : 'Checking…'}</small>
      </div>
      {status === 'loading' && <StatusPill status="loading" />}
      {status === 'available' && <span className="status-pill status-ok"><CheckCircle2 size={12} /> Available</span>}
      {status === 'config' && <span className="status-pill status-missing"><XCircle size={12} /> Configuration required</span>}
      {status === 'offline' && <span className="status-pill status-missing"><XCircle size={12} /> Offline</span>}
      <div className="dataset-meta">
        <span>{configured ? 'configured' : aiStatus?.status || '—'}</span>
        <span>{aiStatus?.available ? 'API ready' : 'not configured'}</span>
      </div>
    </div>
  );
};

// Data-status grid - one row per thematic dataset with real availability.
export const MonitoringPanel = ({ monitoring, liveWeather, loading, modelInfo, aiStatus, onRefresh }) => {
  const datasets = monitoring?.datasets || [];
  const byGroup = {};
  datasets.forEach((ds) => {
    (byGroup[ds.group] = byGroup[ds.group] || []).push(ds);
  });

  // weather processed status: backend reports it; the live API is separate.
  const weatherDs = datasets.find((ds) => ds.key === 'weather');
  const modelDs = datasets.find((ds) => ds.key === 'model');

  return (
    <div className="monitoring-panel theme-panel">
      <div className="monitoring-head">
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <Database size={16} color="var(--primary-sky)" />
          <strong>Monitoring & Data Status</strong>
        </div>
        {!monitoring?.backend_reachable && (
          <span className="tag-warn">Backend offline – local fallback used</span>
        )}
      </div>

      {loading ? (
        <div className="monitoring-loading"><Loader2 size={18} className="spin" /> Checking data availability…</div>
      ) : (
        <>
          <WeatherMonitoring liveWeather={liveWeather} onRefresh={onRefresh} />

          <ModelStatusSection modelInfo={modelInfo} />

          <div className="monitoring-section">
            <div className="monitoring-section-head">
              <Activity size={16} color="#16a34a" />
              <strong>Dataset Availability</strong>
              <span className="tag-live">BACKEND REPORT</span>
            </div>

            <div className="dataset-status-list">
              <NemotronStatusRow aiStatus={aiStatus} />
              {Object.keys(GROUP_LABELS).map((group) => {
                const groupDatasets = byGroup[group] || [];
                if (groupDatasets.length === 0) return null;
                return (
                  <div className="dataset-group" key={group}>
                    <span className="dataset-group-label">{GROUP_LABELS[group]}</span>
                    {groupDatasets.map((ds) => (
                      <div className="dataset-row" key={ds.key}>
                        <div className="dataset-name">
                          <strong>{ds.name}</strong>
                          <small>{ds.source}</small>
                        </div>
                        <StatusPill status={ds.status} />
                        <div className="dataset-meta">
                          <span>Files: {ds.file_count}</span>
                          <span>Latest: {formatDate(ds.last_modified)}</span>
                        </div>
                      </div>
                    ))}
                  </div>
                );
              })}
            </div>

            <div className="monitoring-meta">
              <span>Generated: {monitoring?.generated_at ? formatDate(monitoring.generated_at) : '—'}</span>
              <span>Summary: {monitoring?.summary?.available ?? 0} available / {monitoring?.summary?.unavailable ?? 0} unavailable</span>
              {weatherDs && <span>NASA POWER processed: {weatherDs.available ? 'available' : 'not processed'}</span>}
              {modelDs && <span>UHI model: {modelDs.available ? 'available' : 'not trained'}</span>}
            </div>
          </div>
        </>
      )}
    </div>
  );
};

export default MonitoringPanel;
