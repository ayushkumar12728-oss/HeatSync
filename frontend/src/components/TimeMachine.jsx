import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Clock, Thermometer, AlertTriangle, ChevronLeft, ChevronRight,
  Play, Pause, Calendar, Satellite, Info, Loader2
} from 'lucide-react';
import {
  fetchTemporalDates,
  fetchTemporalDateMetadata,
  fetchTemporalSummary,
} from '../services/temporalClient';

// ---------------------------------------------------------------------------
// Time Machine — Historical Landsat LST
// ---------------------------------------------------------------------------
// Displays REAL Landsat-based historical Land Surface Temperature observations.
//
// Every value shown is:
//   - OBSERVED/DERIVED from Landsat Collection 2 Level-2
//   - NOT live air temperature
//   - NOT XGBoost model prediction
//   - NOT fabricated/interpolated
//
// The Time Machine operates on actual Landsat acquisition dates only.
// Landsat revisits ~every 16 days, so dates are spaced accordingly.
// ---------------------------------------------------------------------------

const fmt = (v, d = 1) =>
  v === null || v === undefined || Number.isNaN(v) ? '—' : Number(v).toFixed(d);

const formatDate = (dateStr) => {
  if (!dateStr) return '—';
  try {
    const d = new Date(dateStr + 'T00:00:00');
    return d.toLocaleDateString('en-IN', {
      day: 'numeric', month: 'short', year: 'numeric'
    });
  } catch {
    return dateStr;
  }
};

const formatDateShort = (dateStr) => {
  if (!dateStr) return '—';
  try {
    const d = new Date(dateStr + 'T00:00:00');
    return d.toLocaleDateString('en-IN', {
      day: 'numeric', month: 'short'
    });
  } catch {
    return dateStr;
  }
};

export const TimeMachine = ({
  liveWeather,
  onDateSelect = () => {},
  onClose = null,
  onCompare = null,
}) => {
  // --- State ---
  const [dates, setDates] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [metadata, setMetadata] = useState(null);
  const [metadataLoading, setMetadataLoading] = useState(false);
  const [playing, setPlaying] = useState(false);
  const [summary, setSummary] = useState(null);
  const playRef = useRef(null);

  // --- Fetch available dates ---
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    fetchTemporalDates()
      .then((data) => {
        if (cancelled) return;
        if (data.status === 'available' && data.dates?.length > 0) {
          setDates(data.dates);
          setSelectedIndex(data.dates.length - 1); // latest date
        } else {
          setDates([]);
          setError('No historical Landsat observations available.');
        }
        setLoading(false);
      })
      .catch((err) => {
        if (cancelled) return;
        setError('Historical Landsat data unavailable.');
        setLoading(false);
      });

    return () => { cancelled = true; };
  }, []);

  // --- Fetch summary for analytics ---
  useEffect(() => {
    if (dates.length === 0) return;
    fetchTemporalSummary()
      .then(setSummary)
      .catch(() => {});
  }, [dates.length]);

  // --- Fetch metadata for selected date ---
  const selectedDate = dates[selectedIndex] || null;

  useEffect(() => {
    if (!selectedDate) {
      setMetadata(null);
      return;
    }
    setMetadataLoading(true);
    fetchTemporalDateMetadata(selectedDate)
      .then((data) => {
        setMetadata(data);
        setMetadataLoading(false);
      })
      .catch(() => {
        setMetadata(null);
        setMetadataLoading(false);
      });
  }, [selectedDate]);

  // --- Notify parent of date selection ---
  useEffect(() => {
    if (selectedDate) {
      onDateSelect(selectedDate);
    }
  }, [selectedDate]);

  // --- Play animation through real dates ---
  useEffect(() => {
    if (playing && dates.length > 1) {
      playRef.current = setInterval(() => {
        setSelectedIndex((prev) => {
          const next = prev + 1;
          if (next >= dates.length) {
            setPlaying(false);
            return dates.length - 1;
          }
          return next;
        });
      }, 2000);
    }
    return () => {
      if (playRef.current) clearInterval(playRef.current);
    };
  }, [playing, dates.length]);

  // --- Navigation ---
  const goPrev = useCallback(() => {
    setPlaying(false);
    setSelectedIndex((i) => Math.max(0, i - 1));
  }, []);

  const goNext = useCallback(() => {
    setPlaying(false);
    setSelectedIndex((i) => Math.min(dates.length - 1, i + 1));
  }, [dates.length]);

  const togglePlay = useCallback(() => {
    setPlaying((p) => !p);
  }, []);

  // --- Keyboard navigation ---
  useEffect(() => {
    const handler = (e) => {
      if (e.key === 'ArrowLeft') goPrev();
      else if (e.key === 'ArrowRight') goNext();
      else if (e.key === ' ') { e.preventDefault(); togglePlay(); }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [goPrev, goNext, togglePlay]);

  // --- No data state ---
  if (!loading && dates.length === 0) {
    return (
      <div className="tm-panel" style={{ width: '340px' }}>
        <div className="tm-head">
          <Clock size={13} /> Time Machine
          {onClose && (
            <button className="tm-close" onClick={onClose} aria-label="Close time machine">×</button>
          )}
        </div>
        <div className="tm-unavailable">
          <AlertTriangle size={14} />
          <span>
            Historical Landsat observations unavailable. The Time Machine requires
            processed Landsat Collection 2 Level-2 Surface Temperature data.
            Run the GIS pipeline to acquire data.
          </span>
        </div>
      </div>
    );
  }

  // --- Loading state ---
  if (loading) {
    return (
      <div className="tm-panel" style={{ width: '340px' }}>
        <div className="tm-head">
          <Clock size={13} /> Time Machine
          {onClose && (
            <button className="tm-close" onClick={onClose} aria-label="Close time machine">×</button>
          )}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '12px 0' }}>
          <Loader2 size={14} className="spin" style={{ color: 'var(--primary-sky)' }} />
          <span style={{ fontSize: '0.72rem', color: 'var(--text-secondary)' }}>
            Loading available dates…
          </span>
        </div>
      </div>
    );
  }

  // --- Error state ---
  if (error) {
    return (
      <div className="tm-panel" style={{ width: '340px' }}>
        <div className="tm-head">
          <Clock size={13} /> Time Machine
          {onClose && (
            <button className="tm-close" onClick={onClose} aria-label="Close time machine">×</button>
          )}
        </div>
        <div className="tm-unavailable">
          <AlertTriangle size={14} />
          <span>{error}</span>
        </div>
      </div>
    );
  }

  // --- Temperature color ---
  const tempColor = (temp) => {
    if (temp === null || temp === undefined) return 'var(--text-muted)';
    if (temp > 45) return '#dc2626';
    if (temp > 40) return '#f97316';
    if (temp > 35) return '#eab308';
    if (temp > 30) return '#0ea5e9';
    return '#22c55e';
  };

  // --- Main render ---
  return (
    <div className="tm-panel" style={{ width: '340px' }}>
      {/* Header */}
      <div className="tm-head">
        <Clock size={13} /> Time Machine
        <span className="real-data-badge ok" style={{ marginLeft: 'auto', fontSize: '0.52rem' }}>
          <Satellite size={10} /> LANDSAT
        </span>
        {onClose && (
          <button className="tm-close" onClick={onClose} aria-label="Close time machine">×</button>
        )}
      </div>

      {/* Current date display */}
      <div className="tm-current" style={{ flexWrap: 'wrap', gap: '6px' }}>
        <Calendar size={13} style={{ color: 'var(--primary-sky)' }} />
        <strong style={{ fontSize: '0.82rem' }}>{formatDate(selectedDate)}</strong>
        {metadata?.cloud_cover !== undefined && (
          <span style={{
            fontSize: '0.58rem',
            padding: '2px 6px',
            borderRadius: '8px',
            background: 'var(--bg-subtle)',
            border: '1px solid var(--border-light)',
          }}>
            ☁ {fmt(metadata.cloud_cover, 1)}%
          </span>
        )}
      </div>

      {/* LST display */}
      {metadata && !metadataLoading && (
        <div style={{
          display: 'flex',
          alignItems: 'center',
          gap: '12px',
          padding: '8px 0',
          borderTop: '1px solid var(--border-light)',
          borderBottom: '1px solid var(--border-light)',
        }}>
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '2px' }}>
            <Thermometer size={16} style={{ color: tempColor(metadata.mean_lst) }} />
            <strong style={{ fontSize: '1.3rem', fontWeight: 800, color: tempColor(metadata.mean_lst) }}>
              {fmt(metadata.mean_lst)}°
            </strong>
            <span style={{ fontSize: '0.52rem', color: 'var(--text-muted)' }}>MEAN</span>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', flex: 1 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.62rem' }}>
              <span style={{ color: 'var(--text-muted)' }}>Min</span>
              <span style={{ color: '#22c55e', fontWeight: 700 }}>{fmt(metadata.min_lst)}°C</span>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.62rem' }}>
              <span style={{ color: 'var(--text-muted)' }}>Max</span>
              <span style={{ color: '#dc2626', fontWeight: 700 }}>{fmt(metadata.max_lst)}°C</span>
            </div>
            {metadata.valid_pixel_fraction !== undefined && (
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.62rem' }}>
                <span style={{ color: 'var(--text-muted)' }}>Valid pixels</span>
                <span style={{ fontWeight: 700 }}>{fmt(metadata.valid_pixel_fraction * 100, 0)}%</span>
              </div>
            )}
          </div>
        </div>
      )}

      {metadataLoading && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '6px 0' }}>
          <Loader2 size={12} className="spin" style={{ color: 'var(--primary-sky)' }} />
          <span style={{ fontSize: '0.64rem', color: 'var(--text-secondary)' }}>Loading metadata…</span>
        </div>
      )}

      {/* Date slider */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
        <input
          type="range"
          min="0"
          max={Math.max(0, dates.length - 1)}
          value={selectedIndex}
          onChange={(e) => {
            setPlaying(false);
            setSelectedIndex(Number(e.target.value));
          }}
          aria-label="Historical date"
          className="tm-slider"
        />
        <div className="tm-scale">
          <span>{formatDateShort(dates[0])}</span>
          <span style={{ fontSize: '0.54rem', color: 'var(--primary-sky)' }}>
            {selectedIndex + 1} / {dates.length}
          </span>
          <span>{formatDateShort(dates[dates.length - 1])}</span>
        </div>
      </div>

      {/* Navigation controls */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
        <button
          onClick={goPrev}
          disabled={selectedIndex === 0}
          style={{
            flex: 1,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            gap: '4px',
            padding: '6px',
            border: '1px solid var(--border-light)',
            borderRadius: '8px',
            background: 'var(--bg-surface)',
            color: selectedIndex === 0 ? 'var(--text-muted)' : 'var(--text-secondary)',
            cursor: selectedIndex === 0 ? 'not-allowed' : 'pointer',
            fontSize: '0.64rem',
            fontWeight: 700,
            opacity: selectedIndex === 0 ? 0.5 : 1,
          }}
          aria-label="Previous date"
        >
          <ChevronLeft size={13} /> Prev
        </button>
        <button
          onClick={togglePlay}
          style={{
            padding: '6px 12px',
            border: '1px solid var(--border-light)',
            borderRadius: '8px',
            background: playing
              ? 'linear-gradient(135deg, #dc2626, #b91c1c)'
              : 'linear-gradient(135deg, #0284c7, #2563eb)',
            color: '#fff',
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            gap: '4px',
            fontSize: '0.64rem',
            fontWeight: 700,
          }}
          aria-label={playing ? 'Pause animation' : 'Play animation'}
        >
          {playing ? <Pause size={12} /> : <Play size={12} />}
          {playing ? 'Pause' : 'Play'}
        </button>
        <button
          onClick={goNext}
          disabled={selectedIndex === dates.length - 1}
          style={{
            flex: 1,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            gap: '4px',
            padding: '6px',
            border: '1px solid var(--border-light)',
            borderRadius: '8px',
            background: 'var(--bg-surface)',
            color: selectedIndex === dates.length - 1 ? 'var(--text-muted)' : 'var(--text-secondary)',
            cursor: selectedIndex === dates.length - 1 ? 'not-allowed' : 'pointer',
            fontSize: '0.64rem',
            fontWeight: 700,
            opacity: selectedIndex === dates.length - 1 ? 0.5 : 1,
          }}
          aria-label="Next date"
        >
          Next <ChevronRight size={13} />
        </button>
      </div>

      {/* Available dates chips */}
      {dates.length > 0 && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '3px', maxHeight: '60px', overflowY: 'auto' }}>
          {dates.map((date, i) => (
            <button
              key={date}
              onClick={() => { setPlaying(false); setSelectedIndex(i); }}
              style={{
                padding: '3px 6px',
                borderRadius: '6px',
                border: i === selectedIndex
                  ? '1.5px solid var(--primary-sky)'
                  : '1px solid var(--border-light)',
                background: i === selectedIndex
                  ? 'var(--primary-sky-light)'
                  : 'var(--bg-surface)',
                color: i === selectedIndex ? 'var(--primary-sky)' : 'var(--text-muted)',
                fontSize: '0.54rem',
                fontWeight: i === selectedIndex ? 800 : 600,
                cursor: 'pointer',
                fontFamily: 'var(--font-body)',
                whiteSpace: 'nowrap',
              }}
              title={formatDate(date)}
            >
              {formatDateShort(date)}
            </button>
          ))}
        </div>
      )}

      {/* Metadata footer */}
      <div className="tm-note" style={{ borderTop: '1px dashed var(--border-light)', paddingTop: '6px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
          <Satellite size={10} style={{ color: 'var(--primary-sky)' }} />
          <span style={{ fontWeight: 700, color: 'var(--text-secondary)' }}>
            HISTORICAL LAND SURFACE TEMPERATURE
          </span>
        </div>
        <span>
          Source: Landsat Collection 2 Level-2 · {metadata?.scene_id || '—'}
        </span>
        <span>
          Product: USGS ST_B10 · 30m resolution · QA_PIXEL cloud masking
        </span>
        <span style={{ color: '#b45309', fontWeight: 600 }}>
          This is satellite-observed LST — not air temperature, not model prediction.
        </span>
        {metadata?.source && (
          <span>Provider: {metadata.provider || 'Planetary Computer'}</span>
        )}
      </div>

      {/* Time series summary */}
      {summary && summary.observations?.length > 1 && (
        <div style={{
          display: 'flex',
          flexDirection: 'column',
          gap: '4px',
          padding: '6px 0 0',
          borderTop: '1px dashed var(--border-light)',
        }}>
          <span style={{ fontSize: '0.56rem', fontWeight: 700, color: 'var(--text-muted)', letterSpacing: '0.04em' }}>
            TIME SERIES ({summary.observations.length} observations)
          </span>
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.58rem' }}>
            <span style={{ color: 'var(--text-muted)' }}>
              Range: {summary.observations[0]?.date} → {summary.observations[summary.observations.length - 1]?.date}
            </span>
          </div>
        </div>
      )}
    </div>
  );
};

export default TimeMachine;
