import React, { useEffect, useState } from 'react';
import {
  Bar, Line
} from 'react-chartjs-2';
import {
  Chart as ChartJS, CategoryScale, LinearScale, BarElement, PointElement,
  LineElement, Tooltip, Legend, Filler
} from 'chart.js';
import { Loader2, ThermometerSun, Wind, Leaf, Building2, Flame, Bot, Activity, Sprout, AlertTriangle } from 'lucide-react';
import { fetchJson } from '../services/backendClient';
import { fetchInterventions } from '../services/cityClient';

ChartJS.register(CategoryScale, LinearScale, BarElement, PointElement, LineElement, Tooltip, Legend, Filler);

const fmt = (v, d = 1) => (v === null || v === undefined || Number.isNaN(v) ? '—' : Number(v).toFixed(d));

const chartOpts = (title, yLabel) => ({
  responsive: true,
  maintainAspectRatio: false,
  plugins: {
    legend: { display: false },
    tooltip: {
      backgroundColor: 'rgba(15, 23, 42, 0.92)',
      titleColor: '#f8fafc',
      bodyColor: '#cbd5e1'
    }
  },
  scales: {
    x: { ticks: { color: 'var(--text-secondary)', font: { size: 10 } }, grid: { color: 'rgba(148,163,184,0.12)' }, title: { display: !!title, text: title, color: 'var(--text-muted)', font: { size: 10 } } },
    y: { ticks: { color: 'var(--text-secondary)', font: { size: 10 } }, grid: { color: 'rgba(148,163,184,0.12)' }, title: { display: !!yLabel, text: yLabel, color: 'var(--text-muted)', font: { size: 10 } } }
  }
});

const Panel = ({ title, icon: Icon, color, badge, children, height = 280 }) => (
  <div className="an-panel theme-panel">
    <div className="an-panel-head">
      <span className="an-panel-title"><Icon size={14} color={color} /> {title}</span>
      {badge && <span className={`real-data-badge ${badge.tone || ''}`}>{badge.text}</span>}
    </div>
    <div style={{ height, position: 'relative' }}>{children}</div>
  </div>
);

const SCOPE_LABELS = {
  city: 'CITY-WIDE',
  selected: 'SELECTED LOCATION'
};

export const AnalyticsCharts = ({ liveWeather, availability, modelInfo }) => {
  const [scenarioStats, setScenarioStats] = useState([]);
  const [shap, setShap] = useState([]);
  const [error, setError] = useState(null);
  const [scope, setScope] = useState('city'); // 'city' or 'selected'

  const toggleScope = () => setScope(prev => prev === 'city' ? 'selected' : 'city');

  useEffect(() => {
    let stale = false;
    fetchJson('/city/distribution')
      .then((d) => { if (!stale) setDist(d.distributions || {}); })
      .catch(() => { if (!stale) setError('City analytics unavailable.'); })
      .finally(() => { if (!stale) setDistLoading(false); });
    fetchInterventions(1).then((d) => { if (!stale) setScenarioStats(d.scenario_stats || []); }).catch(() => {});
    fetchJson('/explainability/top-features')
      .then((d) => { if (!stale) setShap(d.top_features || []); })
      .catch(() => { if (!stale) setError('Explainability unavailable.'); })
    return () => { stale = true; };
  }, [scope]);

  const histData = (h, color) => ({
    labels: h?.bins || [],
    datasets: [{
      label: h?.label || '',
      data: h?.counts || [],
      backgroundColor: color,
      borderRadius: 3
    }]
  });

  const hourly = liveWeather?.hourly;
  const weatherData = hourly?.time?.length
    ? {
        labels: hourly.time.map((t) => {
          try { return new Date(t).toLocaleTimeString([], { hour: '2-digit' }); } catch { return t; }
        }),
        datasets: [
          {
            label: 'Air temperature (°C)',
            data: hourly.temperature,
            borderColor: '#dc2626',
            backgroundColor: 'rgba(220, 38, 38, 0.08)',
            fill: true,
            tension: 0.35,
            pointRadius: 0
          },
          {
            label: 'Humidity (%)',
            data: hourly.humidity,
            borderColor: '#0284c7',
            backgroundColor: 'transparent',
            fill: false,
            tension: 0.35,
            pointRadius: 0,
            yAxisID: 'y2'
          }
        ]
      }
    : null;

  const perf = dist?.model_performance;
  const scenarioChart = scenarioStats.length
    ? {
        labels: scenarioStats.map((s) => s.scenario.replace(/_/g, ' ')),
        datasets: [{
          label: 'Mean Δ LST (°C)',
          data: scenarioStats.map((s) => s.mean_delta_lst),
          backgroundColor: scenarioStats.map((s) => (s.mean_delta_lst < 0 ? '#16a34a' : '#dc2626')),
          borderRadius: 4
        }]
      }
    : null;

  const shapData = shap.length
    ? {
        labels: shap.map((f) => f.feature.length > 24 ? `${f.feature.slice(0, 24)}…` : f.feature),
        datasets: [{
          label: 'Mean |SHAP|',
          data: shap.map((f) => f.mean_abs_shap),
          backgroundColor: '#9333ea',
          borderRadius: 3
        }]
      }
    : null;

  if (distLoading) {
    return <div className="analytics-loading"><Loader2 size={18} className="spin" /> Loading real city analytics…</div>;
  }

  const aqiAvailable = Boolean(availability?.aqi);
  const vegetationAvailable = Boolean(availability?.ndvi);

  const scopeLabel = SCOPE_LABELS[scope];

  return (
    <div className="analytics-grid">
      <div className="analytics-head">
        <div>
          <span className="an-kicker">CITY ANALYTICS · REAL DATA</span>
          <h2>Bhubaneswar Environmental Intelligence</h2>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span className="an-honesty">Every chart is labelled REAL DATA (grid features / XGBoost / satellite) or MODEL OUTPUT. No simulated values.</span>
          <button
            className="an-scope-btn"
            onClick={toggleScope}
            title={scope === 'city' ? 'Show selected location data' : 'Show city-wide data'}
          >
            {scope === 'city' ? 'City-Wide' : 'Selected'}
          </button>
        </div>
      </div>

      {error && <div className="an-error"><AlertTriangle size={14} /> {error}</div>}

      {/* 1. City heat distribution */}
      <Panel title={`City Heat Distribution — ${scopeLabel}`} icon={ThermometerSun} color="#dc2626" badge={{ text: 'REAL DATA', tone: 'ok' }}>
        {dist?.predicted_lst?.bins?.length ? (
          <Bar data={histData(dist.predicted_lst, 'rgba(220, 38, 38, 0.75)')} options={chartOpts('Predicted LST (°C)', 'Cells')} />
        ) : <NoData />}
      </Panel>

{/* 2. AQI distribution */}
      <Panel title={`AQI Distribution — ${scopeLabel}`} icon={Wind} color="#d97706" badge={{ text: aqiAvailable ? 'REAL DATA' : 'UNAVAILABLE', tone: aqiAvailable ? 'ok' : 'warn' }}>
        {dist?.MeanAQI?.bins?.length ? <Bar data={histData(dist.MeanAQI, 'rgba(217, 119, 6, 0.75)')} options={chartOpts('AQI', 'Cells')} /> : <NoData reason="AQI interpolation raster required" />}
      </Panel>

      {/* 4. Vegetation distribution */}
      <Panel title={`Vegetation (NDVI) Distribution — ${scopeLabel}`} icon={Leaf} color="#16a34a" badge={{ text: vegetationAvailable ? 'REAL DATA' : 'UNAVAILABLE', tone: vegetationAvailable ? 'ok' : 'warn' }}>
        {dist?.MeanNDVI?.bins?.length ? <Bar data={histData(dist.MeanNDVI, 'rgba(22, 163, 74, 0.75)')} options={chartOpts('NDVI', 'Cells')} /> : <NoData reason="NDVI raster required" />}
      </Panel>

      {/* 5. Urban density */}
      <Panel title={`Urban Density (Building Coverage) — ${scopeLabel}`} icon={Building2} color="#2563eb" badge={{ text: 'REAL DATA', tone: 'ok' }}>
        {dist?.BuildingCoveragePct?.bins?.length ? <Bar data={histData(dist.BuildingCoveragePct, 'rgba(37, 99, 235, 0.75)')} options={chartOpts('Building coverage (%)', 'Cells')} /> : <NoData />}
      </Panel>

      {/* 6. Weather */}
      <Panel title={`Weather — Next 24 h — ${scopeLabel}`} icon={Activity} color="#0284c7" badge={{ text: liveWeather ? 'LIVE' : 'OFFLINE', tone: liveWeather ? 'ok' : 'warn' }}>
        {weatherData ? (
          <Line data={weatherData} options={{
            ...chartOpts('Hour', ''),
            scales: {
              x: { ticks: { color: 'var(--text-secondary)', font: { size: 9 }, maxRotation: 0 }, grid: { color: 'rgba(148,163,184,0.12)' } },
              y: { ticks: { color: 'var(--text-secondary)', font: { size: 10 } }, grid: { color: 'rgba(148,163,184,0.12)' } },
              y2: { position: 'right', ticks: { color: '#0284c7', font: { size: 10 } }, grid: { drawOnChartArea: false } }
            },
            plugins: { legend: { labels: { color: 'var(--text-secondary)', font: { size: 10 } } } }
          }} />
        ) : <NoData reason="OpenWeather hourly forecast" />}
        {liveWeather && <div className="an-meta">Source: OpenWeather (live air temperature + humidity — not LST)</div>}
      </Panel>

      {/* 7. Scenario comparison */}
      <Panel title={`Scenario Comparison (mean Δ LST) — ${scopeLabel}`} icon={Sprout} color="#16a34a" badge={{ text: 'MODEL OUTPUT', tone: 'ai' }}>
        {scenarioChart ? <Bar data={scenarioChart} options={chartOpts('Scenario', 'Mean Δ LST (°C)')} /> : <NoData reason="Scenario engine results" />}
      </Panel>

      {/* 8. Model performance */}
      <Panel title={`Model Performance (Test-Set Residuals) — ${scopeLabel}`} icon={Bot} color="#9333ea" badge={{ text: perf ? 'REAL DATA' : 'UNAVAILABLE', tone: perf ? 'ok' : 'warn' }}>
        {perf?.bins?.length ? (
          <>
            <Bar data={histData(perf, 'rgba(147, 51, 234, 0.7)')} options={chartOpts('Residual (°C)', 'Cells')} />
            <div className="an-meta">
              MAE {fmt(perf.mae, 2)} °C · RMSE {fmt(perf.rmse, 2)} °C · n = {perf.n?.toLocaleString()} test cells · XGBoost {modelInfo?.version ? `v${modelInfo.version}` : ''}
            </div>
          </>
        ) : <NoData reason="predictions.csv (trained model test set)" />}
      </Panel>

      {/* 9. SHAP feature importance */}
      <Panel title={`What Drives Heat? (Global SHAP) — ${scopeLabel}`} icon={Flame} color="#7c3aed" badge={{ text: shap.length ? 'REAL DATA' : 'UNAVAILABLE', tone: shap.length ? 'ok' : 'warn' }}>
        {shapData ? <Bar data={shapData} options={{ ...chartOpts('Feature', 'Mean |SHAP|'), indexAxis: 'y' }} /> : <NoData reason="SHAP importance CSV (ai-engine output)" />}
      </Panel>
    </div>
  );
};

const NoData = ({ reason }) => (
  <div className="an-nodata">
    <AlertTriangle size={15} />
    <span>No real data available{reason ? ` — ${reason}` : ''}. Nothing is simulated.</span>
  </div>
);

export default AnalyticsCharts;
