import React, { useState } from 'react';
import { HeartPulse, ChevronDown, ThermometerSun, SlidersHorizontal, Eye } from 'lucide-react';
import { computeRiskData } from '../services/riskData';
import { SimulationPanel } from './SimulationPanel';
import { heatClass } from '../services/thematicData';

const QUICK_STATS = [
  { key: 'Heat Risk', src: 'OpenWeather live + heat-class breaks' },
  { key: 'AQI Risk', src: 'CPCB project breakpoints' },
  { key: 'Vegetation', src: 'OSM green cover (real)' },
  { key: 'Urban Density', src: 'OSM buildings near selection' }
];

// Public heat guidance uses the project's fixed heat-class temperature breaks
// (gis-engine config, 20/25/30/35/40 °C) applied to the LIVE air temperature.
// These are visualization thresholds — no medical advice is invented.
function guidanceFor(airTemp, heatIdx) {
  const t = airTemp ?? heatIdx ?? null;
  if (t === null) {
    return {
      level: 'Unknown',
      cls: 'na',
      guidance: 'No live temperature available — guidance unavailable.',
      action: 'N/A',
      source: 'Requires live OpenWeather data'
    };
  }
  const cls = heatClass(heatIdx ?? t);
  const base = `Live air ${airTemp != null ? `${airTemp}°C` : `feels ${heatIdx}°C`}`;
  switch (cls) {
    case 'Very Cool':
    case 'Cool':
      return { level: 'Cool', cls: 'low', guidance: `${base} — comfortable heat level.`, action: 'Normal outdoor activity', source: 'Project heat-class break (< 25 °C)' };
    case 'Moderate':
      return { level: 'Moderate', cls: 'moderate', guidance: `${base} — moderate heat.`, action: 'Stay hydrated, limit midday exertion', source: 'Project heat-class break (25–30 °C)' };
    case 'Warm':
      return { level: 'Warm', cls: 'moderate', guidance: `${base} — warm conditions.`, action: 'Take breaks in shade, avoid peak hours', source: 'Project heat-class break (30–35 °C)' };
    case 'Hot':
      return { level: 'Hot', cls: 'high', guidance: `${base} — high heat.`, action: 'Minimize outdoor activity, seek shade', source: 'Project heat-class break (35–40 °C)' };
    default:
      return { level: 'Very Hot', cls: 'high', guidance: `${base} — extreme heat.`, action: 'Avoid outdoor activity, stay cool', source: 'Project heat-class break (> 40 °C)' };
  }
}

export const CitizenSidebar = ({
  environmentSummary,
  liveWeather,
  availability,
  areaOsm,
  userRole,
  // planner simulator passthrough
  scenario,
  setScenario,
  onRunSimulation,
  onResetSimulation,
  selectedCellCount,
  onClearSelectedCells
}) => {
  const [openSections, setOpenSections] = useState({
    adviser: true,
    guidance: true,
    stats: true,
    simulator: true
  });
  const toggle = (key) => setOpenSections((prev) => ({ ...prev, [key]: !prev[key] }));

  const risks = computeRiskData({ environmentSummary, liveWeather, availability, areaOsm });
  const riskByKey = Object.fromEntries(risks.map((r) => [r.name, r]));
  const heatIdx = (() => {
    if (liveWeather?.temperature == null || liveWeather?.humidity == null) return null;
    // Rothfusz approximation (same helper as thematicData.heatIndexCelsius)
    const t = liveWeather.temperature;
    const rh = liveWeather.humidity;
    if (t < 27 || rh < 40) return t;
    const hi = -8.78469475556 + 1.61139411 * t + 2.33854883889 * rh
      - 0.14611605 * t * rh - 0.012308094 * t * t
      - 0.0164248277778 * rh * rh + 0.002211732 * t * t * rh
      + 0.00072546 * t * rh * rh - 0.000003582 * t * t * rh * rh;
    return Math.round(hi * 10) / 10;
  })();
  const guidance = guidanceFor(liveWeather?.temperature ?? null, heatIdx);

  const statCards = QUICK_STATS.map((item) => {
    const r = riskByKey[item.key] || {};
    return {
      label: item.key,
      level: r.level || 'N/A',
      value: r.value || 'Insufficient data',
      threshold: r.threshold || '',
      cls: r.level === 'High' ? 'high' : r.level === 'Moderate' ? 'moderate' : r.level === 'Low' ? 'low' : 'na'
    };
  });

  return (
    <>
      {/* Section 1 — Citizen Health Adviser */}
      <div className="side-section">
        <div className="side-section-head" onClick={() => toggle('adviser')}>
          <HeartPulse size={15} color="#9333ea" />
          <strong>Citizen Health Adviser</strong>
          <ChevronDown size={14} className={`chevron ${openSections.adviser ? 'open' : ''}`} />
        </div>
        {openSections.adviser && (
          <div className="side-section-body">
            <p>
              Explore real-time street-level heat exposure and particulate risks
              near your residence or workplace using live weather and real OSM
              city data.
            </p>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, color: 'var(--text-muted)', fontSize: '0.66rem' }}>
              <Eye size={12} />
              Data: OpenWeather live · OSM layers
            </div>
          </div>
        )}
      </div>

      {/* Section 2 — Public Heat Guidance */}
      <div className="side-section">
        <div className="side-section-head" onClick={() => toggle('guidance')}>
          <ThermometerSun size={15} color="#dc2626" />
          <strong>Public Heat Guidance</strong>
          <ChevronDown size={14} className={`chevron ${openSections.guidance ? 'open' : ''}`} />
        </div>
        {openSections.guidance && (
          <div className="side-section-body">
            <div className="risk-card" style={{ background: 'var(--bg-subtle)' }}>
              <div className="risk-card-head">
                <span>Heat level</span>
                <span className={`risk-level ${guidance.cls}`} style={{ textTransform: 'uppercase' }}>{guidance.level}</span>
              </div>
              <div className="risk-value">{guidance.guidance}</div>
              <div className="risk-threshold">
                <strong>Recommended action:</strong> {guidance.action}
              </div>
              <div className="risk-basis">Source: {guidance.source} — visualization threshold, not medical advice</div>
            </div>
          </div>
        )}
      </div>

      {/* Section 3 — Quick Stats */}
      <div className="side-section">
        <div className="side-section-head" onClick={() => toggle('stats')}>
          <SlidersHorizontal size={15} color="#0284c7" />
          <strong>Quick Stats</strong>
          <ChevronDown size={14} className={`chevron ${openSections.stats ? 'open' : ''}`} />
        </div>
        {openSections.stats && (
          <div className="side-section-body" style={{ paddingBottom: 12 }}>
            <div className="quick-stats">
              {statCards.map((card) => (
                <div className="qs-card" key={card.label} title={card.threshold}>
                  <span className="qs-head">{card.label}</span>
                  <span className={`qs-level ${card.cls}`}>{card.level}</span>
                  <span className="qs-value">{card.value}</span>
                  <span className="qs-threshold">{card.threshold || 'Insufficient data'}</span>
                </div>
              ))}
            </div>
            <p style={{ fontSize: '0.6rem', color: 'var(--text-muted)', marginTop: 8, marginBottom: 0 }}>
              Levels use the project's visualization thresholds; never claim a
              dataset that the backend reports unavailable.
            </p>
          </div>
        )}
      </div>

      {/* Section 4 — Planner intervention simulator */}
      {userRole === 'planner' && (
        <div className="side-section">
          <div className="side-section-head" onClick={() => toggle('simulator')}>
            <SlidersHorizontal size={15} color="#16a34a" />
            <strong>Intervention Simulator</strong>
            <ChevronDown size={14} className={`chevron ${openSections.simulator ? 'open' : ''}`} />
          </div>
          {openSections.simulator && (
            <div className="side-section-body" style={{ padding: 0 }}>
              <SimulationPanel
                scenario={scenario}
                setScenario={setScenario}
                onRunSimulation={onRunSimulation}
                onResetSimulation={onResetSimulation}
                selectedCellCount={selectedCellCount}
                onClearSelectedCells={onClearSelectedCells}
                liveWeatherData={liveWeather}
              />
            </div>
          )}
        </div>
      )}
    </>
  );
};

export default CitizenSidebar;
