import React from 'react';
import { Flame, Wind, Leaf, Building2, Target, Sprout, Snowflake, MapPin, Loader2 } from 'lucide-react';

// City Intelligence — compact command centre. Every number comes from the
// backend /api/city/intelligence (real grid features + XGBoost predictions +
// cached scenario results). Nothing is invented.
export const CityIntelligencePanel = ({ intelligence, onFlyTo }) => {
  if (!intelligence) {
    return (
      <div className="ci-panel">
        <div className="ci-loading"><Loader2 size={15} className="spin" /> Building city command centre…</div>
      </div>
    );
  }
  if (intelligence.available === false) {
    return <div className="ci-panel"><div className="ci-error">City intelligence unavailable: {intelligence.message}</div></div>;
  }

  const items = [
    {
      key: 'heat', icon: Flame, color: '#dc2626',
      label: 'Current Heat (mean predicted LST)',
      value: intelligence.current_heat != null ? `${Number(intelligence.current_heat).toFixed(1)} °C` : '—',
      src: 'XGBoost full-grid prediction'
    },
    {
      key: 'aqi', icon: Wind, color: '#d97706',
      label: 'Mean AQI',
      value: intelligence.aqi != null ? `${Number(intelligence.aqi).toFixed(0)}` : '—',
      src: 'CPCB interpolation (1 km)'
    },
    {
      key: 'veg', icon: Leaf, color: '#16a34a',
      label: 'Mean NDVI',
      value: intelligence.ndvi != null ? `${Number(intelligence.ndvi).toFixed(2)}` : '—',
      src: 'Sentinel-2 (10 m)'
    },
    {
      key: 'density', icon: Building2, color: '#2563eb',
      label: 'Urban Density (building coverage)',
      value: intelligence.urban_density != null ? `${Number(intelligence.urban_density).toFixed(0)}%` : '—',
      src: 'OSM footprints (100 m grid)'
    }
  ];

  const hotspot = intelligence.hottest_zone;
  const intervention = intelligence.best_intervention;

  return (
    <div className="ci-panel">
      <div className="ci-grid">
        {items.map((item) => (
          <div className="ci-card" key={item.key} title={`Source: ${item.src}`}>
            <span className="ci-card-label"><item.icon size={12} color={item.color} /> {item.label}</span>
            <strong style={{ color: item.color }}>{item.value}</strong>
            <small>{item.src}</small>
          </div>
        ))}
      </div>

      <div className="ci-highlights">
        {hotspot && (
          <button
            className="ci-highlight"
            onClick={() => onFlyTo?.(hotspot.latitude, hotspot.longitude, 14)}
            title="Fly to the hottest modelled zone"
          >
            <span className="ci-highlight-icon hot"><Flame size={13} /></span>
            <span className="ci-highlight-body">
              <strong>🔥 Hottest Zone</strong>
              <span>{Number(hotspot.predicted_lst).toFixed(1)} °C · Zone {hotspot.grid_id}</span>
            </span>
            <MapPin size={12} className="ci-fly" />
          </button>
        )}
        {intervention?.scenario && (
          <div className="ci-highlight">
            <span className="ci-highlight-icon cool"><Sprout size={13} /></span>
            <span className="ci-highlight-body">
              <strong>🌱 Best Intervention</strong>
              <span>{intervention.scenario} · {Number(intervention.mean_delta_lst).toFixed(1)} °C mean cooling</span>
            </span>
          </div>
        )}
        {intervention && (
          <div className="ci-highlight">
            <span className="ci-highlight-icon snow"><Snowflake size={13} /></span>
            <span className="ci-highlight-body">
              <strong>❄ Cells Cooler</strong>
              <span>{Number(intervention.pct_cells_cooler).toFixed(0)}% of {intelligence.scenario_count} scenarios compared</span>
            </span>
          </div>
        )}
      </div>

      <div className="ci-foot">
        <Target size={11} />
        <span>Command centre values: real grid features + XGBoost predictions + cached scenario results (model-derived).</span>
      </div>
    </div>
  );
};

export default CityIntelligencePanel;
