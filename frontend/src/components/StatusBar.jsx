import React from 'react';
import { Activity, Database, Bot, Clock, BrainCircuit } from 'lucide-react';

const fmtTime = (iso) => {
  if (!iso) return '—';
  try {
    return new Date(iso).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  } catch {
    return '—';
  }
};

// Thin bottom status strip. Everything is derived from real API state.
export const StatusBar = ({ monitoring, modelInfo, aiStatus, onOpenMonitoring }) => {
  const backendOk = monitoring?.backend_reachable !== false;
  const modelOk = modelInfo?.available === true;
  const aiConfigured = aiStatus?.status === 'configured';

  const systemOk = backendOk || (!backendOk && monitoring); // fallback mode is still operational
  const operational = systemOk ? 'Operational' : 'Degraded';

  const total = monitoring?.summary?.total;
  const available = monitoring?.summary?.available;
  const dataSources = total != null ? `${available ?? 0} / ${total}` : '—';

  const modelLabel = modelInfo ? (modelOk ? 'XGBoost' : 'XGBoost · unavailable') : 'Checking…';

  const aiLabel = !aiStatus
    ? 'Checking…'
    : aiConfigured
      ? 'Configured'
      : aiStatus.status === 'configuration_required'
        ? 'Configuration Required'
        : aiStatus.status || 'Offline';

  return (
    <div className="status-bar">
      <div className="status-inner">
        <span className="status-item" title="Backend reachability">
          <span className={`status-dot ${operational === 'Operational' ? 'ok' : 'warn'}`} />
          System Status: <strong>{operational}</strong>
          {!backendOk && monitoring && (
            <span className="tag-warn" style={{ fontSize: '0.56rem' }}>fallback</span>
          )}
        </span>

        <span className="status-sep" />

        <button
          className="status-item"
          onClick={onOpenMonitoring}
          title="Open data availability monitor"
          style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'inherit', font: 'inherit', padding: 0 }}
        >
          <Database size={13} />
          Data Sources: <strong>{dataSources}</strong>
          <span className="status-sep" style={{ width: 6, background: 'transparent' }} />
          <Bot size={13} />
          Model: <strong>{modelLabel}</strong>
        </button>

        <div className="status-right">
          <span className="status-item status-hide-sm">
            <Activity size={13} />
            Weather: <strong>{monitoring ? 'Live' : 'Checking…'}</strong>
          </span>
          <span className="status-item">
            <Clock size={13} />
            Last Sync: <strong>{fmtTime(monitoring?.generated_at)}</strong>
          </span>
          <span className="status-item">
            <BrainCircuit size={13} style={{ color: aiConfigured ? 'var(--success)' : 'var(--warning)' }} />
            AI: <strong style={{ color: aiConfigured ? 'var(--success)' : aiStatus ? 'var(--warning)' : 'inherit' }}>{aiLabel}</strong>
          </span>
        </div>
      </div>
    </div>
  );
};

export default StatusBar;
