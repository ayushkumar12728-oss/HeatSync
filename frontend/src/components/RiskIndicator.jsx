import React from 'react';
import { Flame, Gauge, Leaf, Building2, ShieldAlert } from 'lucide-react';
import { computeRiskData } from '../services/riskData';

// Risk indicators panel (floating map overlay).
// IMPORTANT: no scientific thresholds are invented here. Every value comes
// from the shared computeRiskData() service, which only reports real data
// (live OpenWeather, real OSM layers, backend availability) and marks the
// project's visualization thresholds explicitly.

const RiskCard = ({ risk }) => {
  const Icon = risk.icon;
  const tone = risk.level === 'High' ? 'high' : risk.level === 'Moderate' ? 'moderate' : 'low';
  return (
    <div className={`risk-card risk-${tone}`}>
      <div className="risk-card-head">
        <Icon size={15} />
        <strong>{risk.name}</strong>
        <span className="risk-level">{risk.level || '—'}</span>
      </div>
      <div className="risk-value">{risk.value || 'Insufficient data'}</div>
      {risk.threshold && <div className="risk-threshold">{risk.threshold}</div>}
      <div className="risk-basis">{risk.basis}</div>
    </div>
  );
};

const RISK_ICONS = {
  'Heat Risk': Flame,
  'Air Quality Risk': Gauge,
  'Vegetation Stress': Leaf,
  'Urban Density Risk': Building2,
  'Overall Urban Risk': ShieldAlert
};

export const RiskIndicator = (props) => {
  const risks = computeRiskData(props).map((risk) => ({
    ...risk,
    icon: RISK_ICONS[risk.name] || ShieldAlert
  }));
  return (
    <div className="risk-grid">
      {risks.map((risk) => <RiskCard key={risk.name} risk={risk} />)}
    </div>
  );
};

export default RiskIndicator;
