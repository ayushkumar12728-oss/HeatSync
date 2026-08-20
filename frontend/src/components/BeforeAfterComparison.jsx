import React, { useEffect, useState } from 'react';
import { motion } from 'framer-motion';
import { Play, Bot, BrainCircuit, TrendingDown, TrendingUp, AlertTriangle, Map as MapIcon, Loader2, BarChart3, Sparkles, Database, Layers, Activity } from 'lucide-react';
import { Bar } from 'react-chartjs-2';
import { fetchModelInfo, fetchScenarios, runCurrentScenario, fetchScenarioCells, fetchScenarioGeoJson, askAI, fetchCurrentHeat } from '../services/backendClient';

// Before / After scenario comparison (Session 4).
// All numbers come from the backend scenario API, which perturbs the real
// model features and predicts with XGBoost. When the trained model artifact is
// missing, the panel reports "Scenario prediction unavailable" - nothing is
// fabricated.
const heatClass = (c) => {
  if (c === null || c === undefined || Number.isNaN(c)) return null;
  if (c < 20) return 'Very Cool';
  if (c < 25) return 'Cool';
  if (c < 30) return 'Moderate';
  if (c < 35) return 'Warm';
  if (c < 40) return 'Hot';
  return 'Very Hot';
};

const riskFromClass = (cls) => {
  if (!cls) return { level: '—', tone: '' };
  if (['Very Cool', 'Cool'].includes(cls)) return { level: 'Low', tone: 'risk-low' };
  if (['Moderate', 'Warm'].includes(cls)) return { level: 'Moderate', tone: 'risk-moderate' };
  return { level: 'High', tone: 'risk-high' };
};

const fmt = (v, digits = 2) => (v === null || v === undefined || Number.isNaN(v) ? '—' : Number(v).toFixed(digits));

export const BeforeAfterComparison = ({ modelInfo, onModelInfoChange, scenarioMode = 'DIFFERENCE', onScenarioModeChange = () => {}, onScenarioData = () => {} }) => {
  const [scenarios, setScenarios] = useState([]);
  const [selected, setSelected] = useState('');
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [scenariosLoading, setScenariosLoading] = useState(true);
  const [cellsLoading, setCellsLoading] = useState(false);
  const [cellsReady, setCellsReady] = useState(false);
  const [cellsData, setCellsData] = useState(null);
  const [aiState, setAiState] = useState({ loading: false, error: null, result: null });

  useEffect(() => {
    fetchScenarios()
      .then((list) => {
        setScenarios(list || []);
        if (list?.length) setSelected(list[0].name);
        setScenariosLoading(false);
      })
      .catch(() => {
        setScenarios([]);
        setScenariosLoading(false);
      });
  }, []);

  const refreshModelInfo = () => {
    fetchModelInfo()
      .then((info) => onModelInfoChange?.(info))
      .catch(() => {});
  };

  useEffect(() => {
    if (!modelInfo) refreshModelInfo();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const modelAvailable = modelInfo?.available === true;

  const handleRun = async () => {
    if (!selected) return;
    setLoading(true);
    setError(null);
    setResult(null);
    setCellsReady(false);
    try {
      // Run scenario on CURRENT feature grid (architecture-correct mode).
      // POST /api/simulation/run/current returns EVERYTHING in one response:
      // snapshot_id, cells, geojson, summary — all from the same snapshot.
      // DO NOT make additional separate requests for cells or geojson.
      const res = await runCurrentScenario({ scenario: selected });
      if (res.success === false) {
        setError(res.message || 'Scenario prediction unavailable.');
        refreshModelInfo();
      } else {
        // The response now contains cells and geojson directly
        const cellsFromResponse = res.cells || [];
        const geojsonFromResponse = res.geojson || null;

        // Normalize the response to match the expected result shape
        const normalized = {
          ...res,
          baseline_lst: res.baseline?.mean_lst ?? res.baseline_lst,
          mean_predicted_lst: res.after?.mean_lst ?? res.scenario_result?.mean_lst ?? res.mean_predicted_lst,
          mean_delta_lst: res.delta?.mean_change ?? res.delta?.mean ?? res.mean_delta_lst,
          min_delta: res.delta?.max_cooling ?? res.delta?.min ?? res.min_delta,
          max_delta: res.delta?.max_warming ?? res.delta?.max ?? res.max_delta,
          pct_cells_cooler: res.delta?.pct_cells_cooler ?? res.pct_cells_cooler,
          n_cells: res.delta?.affected_cells ?? res.cells?.length ?? res.n_cells,
          feature_freshness: res.data_sources || res.data_freshness,
          snapshot_id: res.snapshot_id,
          simulation_id: res.simulation_id,
        };
        setResult(normalized);

        // Set cells data from the same response (no separate fetch!)
        if (cellsFromResponse.length > 0) {
          setCellsData({ cells: cellsFromResponse, count: cellsFromResponse.length });
          setCellsReady(true);
        }

        // Pass geojson from the same response to the map
        if (geojsonFromResponse) {
          onScenarioData({
            scenario: selected,
            cells: { cells: cellsFromResponse, count: cellsFromResponse.length },
            geojson: geojsonFromResponse,
            mode: 'DIFFERENCE',
            snapshot_id: res.snapshot_id,
            simulation_id: res.simulation_id,
          });
        }
      }
    } catch {
      setError('Scenario prediction unavailable. Required: trained model artifact (models/best_model.pkl).');
      refreshModelInfo();
    } finally {
      setLoading(false);
    }
  };

  // Data provenance and freshness
  const featureFreshness = result?.feature_freshness || {};
  const weather_timestamp = featureFreshness.weather || 'never';
  const aqi_timestamp = featureFreshness.aqi || 'never';
  const satellite_timestamp = featureFreshness.satellite || 'never';

  const baselineClass = result ? heatClass(result.baseline_lst) : null;
  const scenarioClass = result ? heatClass(result.mean_predicted_lst) : null;
  const baselineRisk = riskFromClass(baselineClass);
  const scenarioRisk = riskFromClass(scenarioClass);
  const delta = result?.mean_delta_lst;
  const deltaClass = delta === undefined || delta === null ? '' : delta < 0 ? 'delta-cool' : delta > 0 ? 'delta-warm' : '';

  // Fetch current heat data for provenance display
  const [currentHeat] = useState(() => fetchCurrentHeat());

  const chartData = result
    ? {
        labels: ['Baseline LST', 'Scenario LST'],
        datasets: [
          {
            label: '°C (model prediction)',
            data: [Number(result.baseline_lst), Number(result.mean_predicted_lst)],
            backgroundColor: ['#dc2626', '#16a34a'],
            borderRadius: 6
          }
        ]
      }
    : null;

  const scenarioDef = scenarios.find((s) => s.name === selected);

  const topCoolingCells = (limit = 5) => {
    if (!cellsData?.cells?.length) return [];
    return [...cellsData.cells]
      .sort((a, b) => a.delta_lst - b.delta_lst)
      .slice(0, limit)
      .map((c) => ({ grid_id: c.grid_id, delta_lst: Number(c.delta_lst.toFixed(3)) }));
  };

  const cellsCooler = result ? Math.round((result.n_cells ?? 0) * (result.pct_cells_cooler ?? 0) / 100) : null;
  const scenarioName =
    typeof result?.scenario === 'object' && result.scenario !== null
      ? result.scenario.name
      : result?.scenario;
  return (
    <motion.div
      initial={{ opacity: 0, y: 15 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4 }}
      style={{ width: '100%', height: '100%', overflowY: 'auto', padding: '6px' }}
    >
      {/* Header */}
      <div className="theme-panel" style={{ padding: '16px 20px', borderRadius: '14px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '12px' }}>
        <div>
          <span style={{ fontSize: '0.68rem', fontWeight: 800, color: 'var(--primary-sky)', textTransform: 'uppercase', letterSpacing: '0.07em' }}>
            Scenario Analysis · XGBoost Scenario Engine
          </span>
          <h2 style={{ fontSize: '1.2rem', fontWeight: 800, color: 'var(--text-main)', margin: '2px 0 0 0', display: 'flex', alignItems: 'center', gap: '8px' }}>
            <Layers size={19} color="var(--primary-sky)" />
            Before / After Scenario Comparison
          </h2>
        </div>
        {!modelAvailable && (
          <span className="tag-warn">Model unavailable — predictions disabled</span>
        )}
      </div>

      {/* Scenario controls */}
      <div className="theme-panel" style={{ padding: '16px 18px', borderRadius: '14px', marginTop: '14px' }}>
        <div style={{ display: 'flex', alignItems: 'flex-end', gap: '12px', flexWrap: 'wrap' }}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', minWidth: '280px', flex: 1 }}>
            <span style={{ fontSize: '0.66rem', fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
              Intervention scenario
            </span>
            <select
              value={selected}
              onChange={(e) => setSelected(e.target.value)}
              disabled={scenariosLoading || !modelAvailable}
              style={{
                padding: '10px 12px', borderRadius: '9px', border: '1px solid var(--border-light)',
                background: 'var(--bg-surface)', color: 'var(--text-main)', fontSize: '0.82rem',
                fontWeight: 600, cursor: 'pointer'
              }}
            >
              {scenariosLoading && <option>Loading scenarios…</option>}
              {!scenariosLoading && scenarios.length === 0 && <option>No scenarios (backend offline)</option>}
              {scenarios.map((sc) => (
                <option key={sc.name} value={sc.name}>{sc.name}</option>
              ))}
            </select>
            {scenarioDef?.description && (
              <small
                style={{
                  fontSize: '0.7rem',
                  color: 'var(--text-secondary)',
                  lineHeight: 1.45
                }}
            >
              {typeof scenarioDef.description === 'string'
                ? scenarioDef.description
                : scenarioDef.description?.description ||
                  scenarioDef.description?.name ||
                  'Scenario description unavailable'}
            </small>
          )}
          </div>

          <motion.button
            whileHover={{ scale: 1.03 }}
            whileTap={{ scale: 0.97 }}
            onClick={handleRun}
            disabled={loading || !modelAvailable || !selected}
            className="btn-3d-primary"
            style={{ opacity: modelAvailable ? 1 : 0.5, cursor: modelAvailable ? 'pointer' : 'not-allowed' }}
          >
            {loading ? <Loader2 size={15} className="spin" /> : <Play size={15} />}
            {loading ? 'Running…' : 'Run Scenario'}
          </motion.button>
        </div>

        {scenarioDef && (
          <div style={{ marginTop: '12px', display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
            {Object.entries(scenarioDef.perturbations || {}).slice(0, 12).map(([feature, [kind, value]]) => (
              <span key={feature} className="perturb-chip">
                {feature} {kind === 'mul' ? '×' : kind === 'add' ? '+' : kind} {value}
              </span>
            ))}
            {Object.keys(scenarioDef.perturbations || {}).length > 12 && (
              <span className="perturb-chip muted">+{Object.keys(scenarioDef.perturbations).length - 12} more</span>
            )}
          </div>
        )}
      </div>

      {/* Errors / model-unavailable states */}
      {error && (
        <div className="theme-panel" style={{ marginTop: '14px', padding: '16px 18px', borderRadius: '12px', border: '1px solid rgba(220, 38, 38, 0.35)', background: 'rgba(220, 38, 38, 0.06)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: '#dc2626', fontWeight: 700, fontSize: '0.85rem' }}>
            <AlertTriangle size={16} /> Scenario prediction unavailable
          </div>
          <p style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', margin: '6px 0 0 0', lineHeight: 1.5 }}>
            {error}
          </p>
        </div>
      )}

      {!modelAvailable && !error && (
        <div className="theme-panel" style={{ marginTop: '14px', padding: '16px 18px', borderRadius: '12px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontWeight: 700, fontSize: '0.85rem', color: 'var(--text-main)' }}>
            <Bot size={16} color="var(--primary-sky)" /> Model status
          </div>
          <p style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', margin: '6px 0 0 0', lineHeight: 1.5 }}>
            {modelInfo?.message || 'Trained model artifact is not available.'} Required:
            {' '}<code>models/best_model.pkl</code> (generated by <code>python ai-engine/main.py</code>).
            Scenario predictions will appear here automatically once the artifact exists.
          </p>
        </div>
      )}

{/* Results */}
      {result && (
        <>
          {/* CURRENT / SCENARIO / DIFFERENCE with data provenance */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(210px, 1fr))', gap: '14px', marginTop: '14px' }}>
            <div className="theme-panel" style={{ padding: '16px', borderRadius: '12px', borderTop: '3px solid #dc2626' }}>
              <span style={{ fontSize: '0.62rem', fontWeight: 800, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
                CURRENT · Baseline
              </span>
              <div style={{ fontSize: '1.7rem', fontWeight: 800, color: '#dc2626', margin: '4px 0' }}>{fmt(result.baseline_lst)} °C</div>
              <div className={`risk-badge ${baselineRisk.tone}`}>Heat risk: {baselineRisk.level}</div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 3, marginTop: '8px', fontSize: '0.66rem', color: 'var(--text-muted)' }}>
                <span>Class: {baselineClass || '—'}</span>
                <span>Grid cells: {(result.n_cells ?? 0).toLocaleString()}</span>
                <small style={{ fontSize: '0.58rem', color: 'var(--text-secondary)' }}>
                  Baseline from current feature grid
                </small>
              </div>
            </div>

            <div className="theme-panel" style={{ padding: '16px', borderRadius: '12px', borderTop: '3px solid #16a34a' }}>
              <span style={{ fontSize: '0.62rem', fontWeight: 800, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
                SCENARIO · {scenarioName || 'Unknown scenario'}
              </span>
              <div style={{ fontSize: '1.7rem', fontWeight: 800, color: '#16a34a', margin: '4px 0' }}>{fmt(result.mean_predicted_lst)} °C</div>
              <div className={`risk-badge ${scenarioRisk.tone}`}>Heat risk: {scenarioRisk.level}</div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 3, marginTop: '8px', fontSize: '0.66rem', color: 'var(--text-muted)' }}>
                <span>Class: {scenarioClass || '—'}</span>
                <span>{(result.pct_cells_cooler ?? 0).toFixed(2)}% cells cooler</span>
                <small style={{ fontSize: '0.58rem', color: 'var(--text-secondary)' }}>
                  Scenario from current feature grid
                </small>
              </div>
            </div>

            <div className="theme-panel" style={{ padding: '16px', borderRadius: '12px', borderTop: `3px solid ${delta < 0 ? '#16a34a' : delta > 0 ? '#dc2626' : '#94a3b8'}` }}>
              <span style={{ fontSize: '0.62rem', fontWeight: 800, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
                DIFFERENCE · Scenario − Baseline
              </span>
              <div className={deltaClass} style={{ fontSize: '1.7rem', fontWeight: 800, margin: '4px 0' }}>
                {delta >= 0 ? '+' : ''}{fmt(delta)} °C
              </div>
              <div style={{ fontSize: '0.72rem', color: 'var(--text-secondary)', fontWeight: 600, display: 'flex', alignItems: 'center', gap: 5 }}>
                {delta < 0 ? <TrendingDown size={14} /> : <TrendingUp size={14} />}
                {delta < 0 ? 'Cooling' : delta > 0 ? 'Warming' : 'No change'}
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 3, marginTop: '8px', fontSize: '0.66rem', color: 'var(--text-muted)' }}>
                <span>Min change: {fmt(result.min_delta)} °C</span>
                <span>Max change: {fmt(result.max_delta)} °C</span>
                <span>{result.n_perturbed_features ?? 0} features perturbed</span>
                <small style={{ fontSize: '0.58rem', color: 'var(--text-secondary)' }}>
                  Δ calculated from current feature grid predictions
                </small>
              </div>
            </div>
          </div>

          {/* Data provenance & freshness strip — from the SAME snapshot */}
          {result && (
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: '10px', marginTop: '12px', padding: '10px 14px', borderRadius: '10px', background: 'var(--bg-subtle)', border: '1px solid var(--border-light)' }}>
              <div>
                <span style={{ fontSize: '0.58rem', fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase' }}>Data freshness (from snapshot)</span>
                <div style={{ fontSize: '0.66rem', color: 'var(--text-secondary)' }}>
                  Weather: {weather_timestamp?.observed_at || '—'}
                  {weather_timestamp?.status && ` · ${weather_timestamp.status}`}
                </div>

                <div style={{ fontSize: '0.66rem', color: 'var(--text-secondary)' }}>
                  AQI: {aqi_timestamp?.observed_at || '—'}
                  {aqi_timestamp?.status && ` · ${aqi_timestamp.status}`}
                </div>

                <div style={{ fontSize: '0.66rem', color: 'var(--text-secondary)' }}>
                  Satellite: {satellite_timestamp?.observed_at || '—'}
                  {satellite_timestamp?.status && ` · ${satellite_timestamp.status}`}
                </div>
              </div>
              <div>
                <span style={{ fontSize: '0.58rem', fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase' }}>Model</span>
                <div style={{ fontSize: '0.66rem', color: 'var(--text-secondary)' }}>{result?.model?.name || 'XGBoost'} v{result?.model?.version || '—'}</div>
                <div style={{ fontSize: '0.66rem', color: 'var(--text-secondary)' }}>{result?.model?.feature_count || '—'} features</div>
              </div>
              {result?.snapshot_id && (
                <div>
                  <span style={{ fontSize: '0.58rem', fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase' }}>Snapshot</span>
                  <div style={{ fontSize: '0.62rem', color: 'var(--text-secondary)', fontFamily: 'monospace' }}>{result.snapshot_id}</div>
                  {result?.simulation_id && (
                    <div style={{ fontSize: '0.62rem', color: 'var(--text-secondary)', fontFamily: 'monospace' }}>Sim: {result.simulation_id}</div>
                  )}
                </div>
              )}
            </div>
          )}

          {/* Aggregate stats strip */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: '10px', marginTop: '12px' }}>
            <div className="theme-panel" style={{ padding: '10px 14px', borderRadius: '10px', display: 'flex', flexDirection: 'column', gap: 2 }}>
              <span style={{ fontSize: '0.6rem', fontWeight: 800, color: 'var(--text-muted)', textTransform: 'uppercase' }}>Cells cooler</span>
              <strong style={{ fontSize: '1.05rem', color: '#16a34a' }}>{fmt(result.pct_cells_cooler, 2)}%</strong>
              <small style={{ fontSize: '0.62rem', color: 'var(--text-muted)' }}>{cellsCooler?.toLocaleString()} of {result.n_cells?.toLocaleString()} cells</small>
            </div>
            <div className="theme-panel" style={{ padding: '10px 14px', borderRadius: '10px', display: 'flex', flexDirection: 'column', gap: 2 }}>
              <span style={{ fontSize: '0.6rem', fontWeight: 800, color: 'var(--text-muted)', textTransform: 'uppercase' }}>Cells affected</span>
              <strong style={{ fontSize: '1.05rem', color: 'var(--text-main)' }}>{(result.n_cells ?? 0).toLocaleString()}</strong>
              <small style={{ fontSize: '0.62rem', color: 'var(--text-muted)' }}>Full grid simulated (XGBoost)</small>
            </div>
            <div className="theme-panel" style={{ padding: '10px 14px', borderRadius: '10px', display: 'flex', flexDirection: 'column', gap: 2 }}>
              <span style={{ fontSize: '0.6rem', fontWeight: 800, color: 'var(--text-muted)', textTransform: 'uppercase' }}>Scenario</span>
            <strong style={{ fontSize: '0.95rem', color: 'var(--text-main)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {typeof result.scenario === 'object'
                  ? result.scenario?.name
                  : result.scenario}
            </strong>
              <small style={{ fontSize: '0.62rem', color: 'var(--text-muted)' }}>
              {typeof result.description === 'string'
                ? result.description
                : result.description?.description ||
                  result.description?.name ||
                  (typeof scenarioDef?.description === 'string'
                    ? scenarioDef.description
                    : scenarioDef?.description?.description ||
                      scenarioDef?.description?.name) ||
                  'Backend scenario definition'}
              </small>
            </div>
          </div>

          {/* Cell-level status */}
          <div className="theme-panel" style={{ padding: '12px 18px', borderRadius: '12px', marginTop: '14px', border: '1px solid rgba(16, 185, 129, 0.35)', background: 'rgba(16, 185, 129, 0.05)' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontWeight: 700, fontSize: '0.8rem', color: 'var(--text-main)' }}>
              {cellsLoading ? <Loader2 size={14} className="spin" /> : `${(result.n_cells ?? 0).toLocaleString()} cells simulated (full grid)`}
            </div>
            {!cellsLoading && cellsReady && (
              <small style={{ fontSize: '0.7rem', color: 'var(--text-secondary)', display: 'block', marginTop: '4px' }}>
                Per-cell XGBoost predictions are ready for the 3D map — open the <strong>Map</strong> tab and use
                CURRENT / SCENARIO / DIFFERENCE.
              </small>
            )}
          </div>

          {/* Chart */}
          <div className="theme-panel" style={{ padding: '18px', borderRadius: '14px', marginTop: '14px', height: '300px', display: 'flex', flexDirection: 'column' }}>
            <h4 style={{ fontSize: '0.92rem', fontWeight: 700, color: 'var(--text-main)', margin: '0 0 12px 0', display: 'flex', alignItems: 'center', gap: '8px' }}>
              <BarChart3 size={16} color="var(--primary-sky)" /> Baseline vs Scenario <span className="real-data-badge" style={{ fontSize: '0.58rem' }}>Model output</span>
            </h4>
            <div style={{ flex: 1, position: 'relative' }}>
              {chartData && (
                <Bar
                  data={chartData}
                  options={{
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: { legend: { display: false } },
                    scales: {
                      x: { ticks: { color: 'var(--text-secondary)' }, grid: { color: 'var(--border-light)' } },
                      y: { ticks: { color: 'var(--text-secondary)' }, grid: { color: 'var(--border-light)' } }
                    }
                  }}
                />
              )}
            </div>
          </div>
        </>
      )}


      {/* Map mode toggle - drives the 3D map overlay */}
      <div className="theme-panel" style={{ padding: '16px 18px', borderRadius: '12px', marginTop: '14px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontWeight: 700, fontSize: '0.82rem', color: 'var(--text-main)', marginBottom: '10px' }}>
          <MapIcon size={15} color="var(--primary-sky)" /> Spatial map comparison
        </div>
        <div style={{ display: 'flex', gap: '8px', marginBottom: '10px', flexWrap: 'wrap' }}>
          {['CURRENT', 'SCENARIO', 'DIFFERENCE'].map((mode) => (
            <button
              key={mode}
              className={`overlay-tab ${scenarioMode === mode ? 'active' : ''}`}
              onClick={() => onScenarioModeChange(mode)}
              disabled={!result}
              style={{ cursor: result ? 'pointer' : 'not-allowed', opacity: result ? 1 : 0.5 }}
            >
              {mode}
            </button>
          ))}
        </div>
        {cellsReady ? (
          <p style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', margin: 0, lineHeight: 1.5 }}>
            <strong style={{ color: '#10b981' }}>
              {typeof result.scenario === 'object'
                ? result.scenario?.name || 'Unknown scenario'
                : result.scenario || 'Unknown scenario'}
            </strong> cell-level results are loaded.
            {' '}CURRENT shows baseline LST, SCENARIO shows the perturbed prediction, DIFFERENCE shows
            scenario − baseline — all colored from the real XGBoost output on the 3D map (Map tab).
            Click any grid cell on the map for its Grid ID, Baseline / Scenario LST and Δ LST.
          </p>
        ) : (
          <p style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', margin: 0, lineHeight: 1.5 }}>
            Run a scenario above to load per-cell predictions for the 3D map. Until then,
            the comparison shows the numerical model results only — no heatmap is fabricated.
          </p>
        )}
      </div>

      {/* WHY THIS PREDICTION? - Nemotron scenario explanation */}
      <div className="theme-panel" style={{ padding: '16px 18px', borderRadius: '12px', marginTop: '14px', borderStyle: 'dashed' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontWeight: 700, fontSize: '0.82rem', color: 'var(--text-main)', marginBottom: '6px' }}>
          <BrainCircuit size={15} color="#9333ea" /> WHY THIS SCENARIO?
        </div>
        {result && (
          <button
            className="ai-mini-btn"
            onClick={async () => {
              if (aiState.loading) return;
              setAiState({ loading: true, error: null, result: null });
              try {
                const res = await askAI('Explain this scenario result: why did the temperature change?', {
                  scenario: {
                    scenario:
                      typeof result.scenario === 'object'
                        ? result.scenario?.name
                        : result.scenario,
                    baseline_lst: result.baseline_lst,
                    mean_predicted_lst: result.mean_predicted_lst,
                    mean_delta_lst: result.mean_delta_lst,
                    pct_cells_cooler: result.pct_cells_cooler,
                    min_delta: result.min_delta,
                    max_delta: result.max_delta,
                    n_cells: result.n_cells,
                    changed_features: scenarioDef ? Object.keys(scenarioDef.perturbations || {}) : null,
                    top_cooling_cells: cellsData?.count ? topCoolingCells() : null
                  },
                  prediction: { available: modelAvailable }
                });
                setAiState({ loading: false, error: res.success ? null : (res.message || 'AI explanation unavailable.'), result: res.success ? res : null });
              } catch {
                setAiState({ loading: false, error: 'AI explanation unavailable.', result: null });
              }
            }}
            disabled={aiState.loading}
            style={{ marginBottom: '10px' }}
          >
            {aiState.loading ? <Loader2 size={12} className="spin" /> : <Sparkles size={12} />}
            {aiState.loading ? 'Analyzing…' : 'Explain result (AI)'}
          </button>
        )}
        {aiState.error && (
          <div className="ai-inline-error" style={{ marginBottom: '8px' }}><AlertTriangle size={12} /> {aiState.error}</div>
        )}
        {aiState.result?.answer && (
          <div className="ai-inline-answer" style={{ marginBottom: '8px' }}>
            <p>{aiState.result.answer}</p>
            {aiState.result.data_used?.length > 0 && (
              <div className="ai-inline-used">
                {aiState.result.data_used.map((d) => <span key={d} className="ai-meta-chip ok">✓ {d}</span>)}
              </div>
            )}
          </div>
        )}

        {/* Explanation structure: Data Used / Prediction / Scenario Changes / Limitations */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '10px', marginTop: '4px' }}>
          <div style={{ background: 'var(--bg-subtle)', border: '1px solid var(--border-light)', borderRadius: '10px', padding: '10px 12px' }}>
            <span className="ai-meta-title"><Database size={11} /> DATA USED</span>
            <div style={{ marginTop: 4, fontSize: '0.68rem', color: 'var(--text-secondary)', lineHeight: 1.5 }}>
              Scenario engine (XGBoost) · training grid · {result ? `${result.n_perturbed_features ?? 0} perturbed features` : '—'}
              <br /><small>SHAP: feature-level attribution unavailable in this build.</small>
            </div>
          </div>
          <div style={{ background: 'var(--bg-subtle)', border: '1px solid var(--border-light)', borderRadius: '10px', padding: '10px 12px' }}>
            <span className="ai-meta-title"><Activity size={11} /> PREDICTION</span>
            <div style={{ marginTop: 4, fontSize: '0.68rem', color: 'var(--text-secondary)', lineHeight: 1.5 }}>
              Baseline {result ? `${fmt(result.baseline_lst)} °C → ${fmt(result.mean_predicted_lst)} °C` : '—'}
              <br /><small>Δ {result ? `${fmt(result.mean_delta_lst, 2)} °C mean` : '—'} over {result ? result.n_cells?.toLocaleString() : '—'} cells</small>
            </div>
          </div>
          <div style={{ background: 'var(--bg-subtle)', border: '1px solid var(--border-light)', borderRadius: '10px', padding: '10px 12px' }}>
            <span className="ai-meta-title"><Layers size={11} /> SCENARIO CHANGES</span>
            <div style={{ marginTop: 4, fontSize: '0.68rem', color: 'var(--text-secondary)', lineHeight: 1.5 }}>
              {result && scenarioDef
                ? Object.entries(scenarioDef.perturbations || {}).slice(0, 4).map(([f, [k, v]]) => `${f} ${k} ${v}`).join(' · ')
                : '—'}
              <br /><small>Limitations: prediction quality depends on training data coverage.</small>
            </div>
          </div>
        </div>
      </div>
    </motion.div>
  );
};

export default BeforeAfterComparison;
