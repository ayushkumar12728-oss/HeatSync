import React from 'react';
import { Activity, RefreshCw, Clock, ChevronUp, Wifi, WifiOff, Loader2 } from 'lucide-react';

const fmtTime = (iso) => {
  if (!iso) return '—';
  try {
    return new Date(iso).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  } catch {
    return '—';
  }
};

const DOT_LABEL = {
  backend: 'Backend', database: 'DB', gis: 'GIS', model: 'Model',
  scenarios: 'Scenarios', weather: 'Weather', air_quality: 'AQI', search: 'Search', ai: 'AI',
  terrain: 'Terrain', satellite: 'Sat'
};

const CONNECTION_LABEL = {
  connected: { text: 'LIVE CONNECTION\nCONNECTED', icon: Wifi, color: '#16a34a' },
  reconnecting: { text: 'LIVE CONNECTION\nRECONNECTING', icon: Loader2, color: '#d97706' },
  offline: { text: 'LIVE CONNECTION\nOFFLINE', icon: WifiOff, color: '#dc2626' },
  polling: { text: 'LIVE CONNECTION\nPOLLING', icon: RefreshCw, color: '#0284c7' },
  initial: { text: 'LIVE CONNECTION\nCONNECTING', icon: Loader2, color: '#94a3b8' },
};

// Format freshness for a data source
function formatFreshness(freshnessMap, sourceKey) {
  const f = freshnessMap?.[sourceKey];
  if (!f) return null;
  const observed = f.observed_at || f.acquired || f.last_updated;
  if (!observed) return null;
  try {
    const ageSec = (Date.now() - new Date(observed).getTime()) / 1000;
    if (ageSec < 60) return `${Math.round(ageSec)} sec`;
    if (ageSec < 3600) return `${Math.round(ageSec / 60)} min`;
    return `${Math.round(ageSec / 3600)} hr`;
  } catch {
    return null;
  }
}

// Thin bottom status strip: real capability dots + live connection indicator.
export const SystemStatusBar = ({ status, loading, onRefresh, onOpenPanel, connectionState = 'initial', freshness = {} }) => {
  const entries = status?.groups?.flatMap((g) => g.entries) || [];
  const overall = status?.overall || (loading ? 'checking' : 'offline');
  const overallLabel = overall === 'healthy' ? 'All systems operational'
    : overall === 'degraded' ? 'Degraded' : 'Offline';

  const conn = CONNECTION_LABEL[connectionState] || CONNECTION_LABEL.initial;
  const ConnIcon = conn.icon;

  return (
    <div className="status-bar">
      <div className="status-inner">
        {/* Connection status indicator */}
        <button
          className="status-item status-item-btn"
          onClick={onOpenPanel}
          title={`${conn.text.replace('\n', ' — ')}`}
          style={{ display: 'flex', alignItems: 'center', gap: '6px' }}
        >
          <span className={`status-dot ${connectionState === 'connected' ? 'ok' : connectionState === 'reconnecting' ? 'warn' : 'down'}`} />
          <ConnIcon size={12} className={connectionState === 'reconnecting' || connectionState === 'initial' ? 'spin' : ''} style={{ color: conn.color }} />
          <span style={{ whiteSpace: 'pre-line', fontSize: '0.6rem', lineHeight: '1.1', textAlign: 'center' }}>{conn.text}</span>
        </button>

        <span className="status-sep" />

        {/* System capability dots */}
        {entries.map((entry) => (
          <span
            className="status-item status-item-dot"
            key={entry.key}
            title={`${entry.label}: ${entry.value} — ${entry.detail || ''}`}
          >
            <span className={`status-dot ${entry.tone}`} />
            {DOT_LABEL[entry.key] || entry.label}
          </span>
        ))}

        <div className="status-right">
          {/* Live data freshness indicators */}
          <span className="status-item status-hide-sm" title="Weather data freshness">
            {formatFreshness(freshness, 'weather') ? (
              <span style={{ display: 'flex', alignItems: 'center', gap: '3px' }}>
                <span className={`status-dot ${freshness.weather?.status === 'LIVE' ? 'ok' : 'warn'}`} />
                Weather {formatFreshness(freshness, 'weather')}
              </span>
            ) : (
              <span style={{ display: 'flex', alignItems: 'center', gap: '3px', opacity: 0.5 }}>
                <span className="status-dot down" />
                Weather —
              </span>
            )}
          </span>
          <span className="status-item status-hide-sm" title="AQI data freshness">
            {formatFreshness(freshness, 'air_quality') ? (
              <span style={{ display: 'flex', alignItems: 'center', gap: '3px' }}>
                <span className={`status-dot ${freshness.air_quality?.status === 'LIVE' ? 'ok' : 'warn'}`} />
                AQI {formatFreshness(freshness, 'air_quality')}
              </span>
            ) : (
              <span style={{ display: 'flex', alignItems: 'center', gap: '3px', opacity: 0.5 }}>
                <span className="status-dot down" />
                AQI —
              </span>
            )}
          </span>
          <span className="status-item status-hide-sm" title="Prediction freshness">
            <span style={{ display: 'flex', alignItems: 'center', gap: '3px', opacity: 0.7 }}>
              <span className="status-dot ok" />
              GIS Static
            </span>
          </span>

          <span className="status-sep" />

          <span className="status-item status-hide-sm">
            <Clock size={12} />
            Updated: <strong>{fmtTime(status?.generatedAt)}</strong>
          </span>
          <button
            className="status-item status-item-btn"
            onClick={onRefresh}
            disabled={loading}
            title="Refresh system status"
          >
            <RefreshCw size={12} className={loading ? 'spin' : ''} />
            Refresh
          </button>
          <button
            className="status-item status-item-btn status-hide-sm"
            onClick={onOpenPanel}
            title="System Status details"
          >
            <Activity size={12} />
            Status <ChevronUp size={11} />
          </button>
        </div>
      </div>
    </div>
  );
};

export default SystemStatusBar;
