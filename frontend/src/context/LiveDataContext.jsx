/**
 * LiveDataContext
 * ===============
 * Single source of truth for all live data in the frontend.
 *
 * Architecture:
 *   Backend owns the refresh cycle via SSE (/api/live/stream).
 *   Frontend subscribes to the SSE stream for real-time updates.
 *   If SSE fails, falls back to controlled polling (every 60 seconds).
 *
 * Connection states:
 *   CONNECTED    — SSE stream active, receiving events
 *   RECONNECTING — SSE lost, attempting to reconnect
 *   OFFLINE      — SSE + polling both failing
 *   POLLING      — SSE unavailable, using polling fallback
 *
 * Every component that needs weather, AQI, prediction or snapshot data
 * reads from this context. Components must NOT independently call APIs.
 */
import React, { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';
import { API_BASE } from '../services/backendClient';

const LiveDataContext = createContext(null);

// Staleness thresholds (ms)
const STALE_WEATHER_MS = 10 * 60 * 1000;  // 10 minutes
const STALE_AQI_MS = 10 * 60 * 1000;      // 10 minutes

// Polling fallback interval (used when SSE is unavailable)
const POLL_INTERVAL_MS = 60 * 1000;  // 60 seconds

// SSE reconnect backoff
const SSE_RECONNECT_BASE_MS = 2000;
const SSE_RECONNECT_MAX_MS = 30000;

/**
 * Format seconds into a human-readable age string
 */
function formatAge(seconds) {
  if (seconds == null) return '—';
  if (seconds < 60) return `${Math.round(seconds)} sec ago`;
  if (seconds < 3600) return `${Math.round(seconds / 60)} min ago`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)} hr ago`;
  return `${Math.round(seconds / 86400)} days ago`;
}

/**
 * Determine freshness status based on source and age
 */
function getFreshnessStatus(source, ageSeconds) {
  if (source === 'UNAVAILABLE') return 'UNAVAILABLE';
  if (source === 'STATIC') return 'STATIC';
  if (source === 'LATEST_OBSERVATION') return 'LATEST_OBSERVATION';
  if (source === 'MODELLED') return 'MODELLED';

  // For live sources, check staleness
  if (ageSeconds != null) {
    if (source === 'weather' && ageSeconds > STALE_WEATHER_MS / 1000) return 'STALE';
    if (source === 'air_quality' && ageSeconds > STALE_AQI_MS / 1000) return 'STALE';
  }

  return source || 'UNKNOWN';
}

/**
 * Determine if a freshness status should show as LIVE
 */
function isLiveStatus(status) {
  return status === 'LIVE' || status === 'weather' || status === 'air_quality';
}

export function LiveDataProvider({ children }) {
  // --- Snapshot state ---
  const [snapshot, setSnapshot] = useState(null);
  const [snapshotLoading, setSnapshotLoading] = useState(true);
  const [snapshotError, setSnapshotError] = useState(null);

  // --- Connection state ---
  // 'connected' | 'reconnecting' | 'offline' | 'polling' | 'initial'
  const [connectionState, setConnectionState] = useState('initial');

  // --- Simulation state ---
  const [simulation, setSimulation] = useState(null);
  const [simulationLoading, setSimulationLoading] = useState(false);

  // --- SSE state ---
  const eventSourceRef = useRef(null);
  const reconnectTimerRef = useRef(null);
  const reconnectAttemptRef = useRef(0);
  const pollTimerRef = useRef(null);

  // --- Derived state ---
  const weather = snapshot?.weather || null;
  const airQuality = snapshot?.air_quality || null;
  const prediction = snapshot?.prediction || null;
  const freshness = snapshot?.freshness || {};
  const sourceStatus = snapshot?.source_status || {};

  // Compute age for each source
  const now = Date.now();
  const weatherAge = freshness.weather?.observed_at
    ? (now - new Date(freshness.weather.observed_at).getTime()) / 1000
    : null;
  const aqiAge = freshness.air_quality?.observed_at
    ? (now - new Date(freshness.air_quality.observed_at).getTime()) / 1000
    : null;

  // --- Apply snapshot update (shared by SSE and polling) ---
  const applySnapshot = useCallback((data) => {
    if (data?.success) {
      setSnapshot(data);
      setSnapshotError(null);
    } else {
      setSnapshotError(data?.message || 'Snapshot unavailable');
    }
  }, []);

  // --- Fetch snapshot (for polling fallback and initial load) ---
  const fetchSnapshot = useCallback(async (force = false) => {
    try {
      const params = force ? '?force=true' : '';
      const response = await fetch(`${API_BASE}/live/snapshot${params}`);
      if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
      const data = await response.json();
      applySnapshot(data);
    } catch (err) {
      setSnapshotError(err.message);
    } finally {
      setSnapshotLoading(false);
    }
  }, [applySnapshot]);

  // --- SSE connection management ---
  const connectSSE = useCallback(() => {
    // Clean up any existing connection
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }
    if (reconnectTimerRef.current) {
      clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }

    try {
      const url = `${API_BASE}/live/stream`;
      const eventSource = new EventSource(url);
      eventSourceRef.current = eventSource;

      eventSource.addEventListener('snapshot_update', (event) => {
        try {
          const data = JSON.parse(event.data);
          // Build a snapshot-compatible response
          applySnapshot({
            success: true,
            snapshot_id: data.snapshot_id,
            generated_at: data.generated_at,
            weather: data.sources?.weather || null,
            air_quality: data.sources?.air_quality || null,
            prediction: null, // prediction comes from the full snapshot endpoint
            satellite: data.sources?.satellite || null,
            freshness: data.freshness || {},
            source_status: data.source_status || {},
          });
          setConnectionState('connected');
          reconnectAttemptRef.current = 0;
          setSnapshotLoading(false);

          // Also fetch prediction data separately (SSE doesn't include it)
          fetch(`${API_BASE}/live/snapshot`)
            .then(r => r.json())
            .then(fullData => {
              if (fullData?.success) {
                setSnapshot(prev => prev ? { ...prev, prediction: fullData.prediction } : prev);
              }
            })
            .catch(() => {});
        } catch (err) {
          console.warn('SSE parse error:', err);
        }
      });

      eventSource.addEventListener('error', (event) => {
        if (event.data) {
          try {
            const errorData = JSON.parse(event.data);
            console.warn('SSE error event:', errorData.message);
          } catch {
            // Non-JSON error
          }
        }
      });

      eventSource.onerror = () => {
        setConnectionState('reconnecting');
        eventSource.close();
        eventSourceRef.current = null;

        // Exponential backoff reconnect
        const attempt = reconnectAttemptRef.current;
        const delay = Math.min(SSE_RECONNECT_BASE_MS * Math.pow(2, attempt), SSE_RECONNECT_MAX_MS);
        reconnectAttemptRef.current = attempt + 1;

        reconnectTimerRef.current = setTimeout(() => {
          connectSSE();
        }, delay);
      };

      eventSource.onopen = () => {
        setConnectionState('connected');
        reconnectAttemptRef.current = 0;
        // Stop polling if SSE is working
        if (pollTimerRef.current) {
          clearInterval(pollTimerRef.current);
          pollTimerRef.current = null;
        }
      };
    } catch {
      // SSE not supported or connection failed — fall back to polling
      setConnectionState('polling');
      startPolling();
    }
  }, [applySnapshot, fetchSnapshot]);

  // --- Polling fallback ---
  const startPolling = useCallback(() => {
    if (pollTimerRef.current) return; // already polling
    setConnectionState('polling');
    pollTimerRef.current = setInterval(() => {
      fetchSnapshot(true);
    }, POLL_INTERVAL_MS);
  }, [fetchSnapshot]);

  // --- Cleanup SSE on unmount ---
  useEffect(() => {
    return () => {
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
      }
      if (reconnectTimerRef.current) {
        clearTimeout(reconnectTimerRef.current);
      }
      if (pollTimerRef.current) {
        clearInterval(pollTimerRef.current);
      }
    };
  }, []);

  // --- Initial connection: try SSE, fall back to polling ---
  useEffect(() => {
    // Initial fetch
    fetchSnapshot(true).then(() => {
      // After initial load, try SSE
      try {
        connectSSE();
      } catch {
        startPolling();
      }
    });

    // Safety timeout: if SSE hasn't connected after 5s, start polling
    const safetyTimer = setTimeout(() => {
      if (!eventSourceRef.current || eventSourceRef.current.readyState !== EventSource.OPEN) {
        startPolling();
      }
    }, 5000);

    return () => clearTimeout(safetyTimer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // --- Run simulation ---
  const runSimulation = useCallback(async (scenarioName) => {
    setSimulationLoading(true);
    try {
      const response = await fetch(`${API_BASE}/simulation/run/current`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ scenario: scenarioName }),
      });
      if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
      const data = await response.json();
      if (data.success) {
        setSimulation(data);
        return data;
      } else {
        throw new Error(data.message || 'Simulation failed');
      }
    } catch (err) {
      setSimulation(null);
      throw err;
    } finally {
      setSimulationLoading(false);
    }
  }, []);

  // --- Clear simulation ---
  const clearSimulation = useCallback(() => {
    setSimulation(null);
  }, []);

  // --- Manual refresh ---
  const refreshNow = useCallback(() => {
    fetchSnapshot(true);
  }, [fetchSnapshot]);

  // --- Context value ---
  const value = {
    // Snapshot
    snapshot,
    snapshotId: snapshot?.snapshot_id || null,
    generatedAt: snapshot?.generated_at || null,
    snapshotLoading,
    snapshotError,

    // Connection
    connectionState,
    isConnected: connectionState === 'connected',

    // Derived data
    weather,
    airQuality,
    prediction,
    freshness,
    sourceStatus,

    // Age tracking
    weatherAge,
    aqiAge,
    formatAge,

    // Freshness helpers
    getFreshnessStatus,
    isLiveStatus,

    // Simulation
    simulation,
    simulationLoading,
    runSimulation,
    clearSimulation,

    // Controls
    refreshNow,
  };

  return (
    <LiveDataContext.Provider value={value}>
      {children}
    </LiveDataContext.Provider>
  );
}

/**
 * Hook to access live data from any component.
 *
 * Usage:
 *   const { weather, airQuality, prediction, snapshotId } = useLiveData();
 */
export function useLiveData() {
  const context = useContext(LiveDataContext);
  if (!context) {
    throw new Error('useLiveData must be used within a LiveDataProvider');
  }
  return context;
}

export default LiveDataContext;
