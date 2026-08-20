import React from 'react';
import { motion } from 'framer-motion';
import { X, Activity, RefreshCw, Database, ShieldCheck, AlertTriangle, Loader2 } from 'lucide-react';

const fmtTime = (iso) => {
  if (!iso) return '—';
  try {
    return new Date(iso).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  } catch {
    return '—';
  }
};

// Full System Status panel — grouped by capability with real, per-item detail.
export const SystemStatusPanel = ({ onClose, status, loading, onRefresh }) => {
  const overall = status?.overall || (loading ? 'checking' : 'offline');
  const overallOk = overall === 'healthy';

  return (
    <div
      style={{
        position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
        background: 'rgba(15, 23, 42, 0.6)', backdropFilter: 'blur(10px)',
        zIndex: 3500, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '20px'
      }}
      role="dialog"
      aria-modal="true"
      aria-label="System Status"
    >
      <motion.div
        initial={{ opacity: 0, scale: 0.93, y: 20 }}
        animate={{ opacity: 1, scale: 1, y: 0 }}
        exit={{ opacity: 0, scale: 0.93, y: 20 }}
        className="theme-panel card-3d"
        style={{
          width: '100%', maxWidth: '680px', maxHeight: '85vh', overflowY: 'auto',
          padding: '24px', borderRadius: '18px', background: 'var(--bg-surface)'
        }}
      >
        {/* Header */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', borderBottom: '1px solid var(--border-light)', paddingBottom: '12px', marginBottom: '16px' }}>
          <div>
            <span style={{ fontSize: '0.7rem', fontWeight: 800, color: 'var(--primary-sky)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
              HeatSync · System Health
            </span>
            <h2 style={{ fontSize: '1.2rem', fontWeight: 800, color: 'var(--text-main)', margin: '2px 0 0 0', display: 'flex', alignItems: 'center', gap: '8px' }}>
              <Activity size={19} color="var(--primary-sky)" />
              System Status
              <span className={`sys-overall ${overallOk ? 'ok' : 'warn'}`}>{overall}</span>
            </h2>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
            <button
              onClick={onRefresh}
              disabled={loading}
              className="sys-refresh-btn"
              title="Refresh system status"
            >
              <RefreshCw size={14} className={loading ? 'spin' : ''} /> Refresh
            </button>
            <button onClick={onClose} className="sys-close-btn" aria-label="Close system status">
              <X size={18} />
            </button>
          </div>
        </div>

        {loading && !status ? (
          <div className="wp-loading" style={{ padding: '40px 0' }}>
            <Loader2 size={18} className="spin" /> Checking system status…
          </div>
        ) : (
          <>
            {/* Groups */}
            {(status?.groups || []).map((group) => (
              <div className="sys-group" key={group.key}>
                <div className="sys-group-label">{group.label}</div>
                {group.entries.map((entry) => (
                  <div className="sys-row" key={entry.key}>
                    <span className={`status-dot ${entry.tone}`} />
                    <div className="sys-row-main">
                      <strong>{entry.label}</strong>
                      <span>{entry.detail}</span>
                    </div>
                    <span className={`sys-value tone-${entry.tone}`}>{entry.value}</span>
                  </div>
                ))}
              </div>
            ))}

            {/* Footer */}
            <div className="sys-foot">
              <ShieldCheck size={12} color="var(--primary-sky)" />
              <span>
                Every status comes from a real backend request or verified disk
                state — never fabricated. Live probes (weather / AQI / search)
                run keyless OpenWeather + Nominatim with server-side caching.
                {status?.liveProbesEnabled === false && ' Live probes are currently disabled on the backend (UDT_ENABLE_LIVE_PROBES=false).'}
              </span>
            </div>
            {status?.generatedAt && (
              <div className="sys-meta">
                <Database size={11} />
                Last checked: {fmtTime(status.generatedAt)}
              </div>
            )}
          </>
        )}

        {!loading && !status && (
          <div className="wp-unavailable">
            <AlertTriangle size={14} />
            <div>
              <strong>Backend unreachable</strong>
              <span>Could not reach the API. Start the backend (uvicorn backend.main:app) and refresh.</span>
            </div>
          </div>
        )}
      </motion.div>
    </div>
  );
};

export default SystemStatusPanel;
