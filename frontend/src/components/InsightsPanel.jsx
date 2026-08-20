import React, { useEffect, useState } from 'react';
import { Sprout, MapPin, Loader2, AlertTriangle, Navigation, Route } from 'lucide-react';
import { fetchInterventions, fetchHeatSafeRoute } from '../services/cityClient';
import { fetchCoolingPotential } from '../services/cityClient';
import { searchPlaces } from '../services/geocoding';

const fmt = (v, d = 1) => (v === null || v === undefined || Number.isNaN(v) ? '—' : Number(v).toFixed(d));

// ---------------------------------------------------------------------------
// Intervention finder — ranked cooling opportunities from real scenario deltas.
// ---------------------------------------------------------------------------
/* eslint-disable no-unused-vars */
function InterventionFinder({ onFlyTo, onSelect }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let stale = false;
    setLoading(true);
    fetchInterventions(5)
      .then((d) => { if (!stale) setData(d); })
      .catch(() => { if (!stale) setData({ available: false, message: 'Interventions unavailable.' }); })
      .finally(() => { if (!stale) setLoading(false); });
    return () => { stale = true; };
  }, []);

// Use onFlyTo and onSelect for flying to intervention zones and selecting locations.
  return (
    <div className="ins-tab">
      <div className="ins-tab-head">
        <Sprout size={14} color="#16a34a" />
        <strong>Where should we intervene?</strong>
      </div>
      {loading && <div className="ins-loading"><Loader2 size={14} className="spin" /> Ranking cooling opportunities…</div>}
      {!loading && data?.available === false && <div className="ins-error"><AlertTriangle size={13} /> {data.message}</div>}
      {!loading && data?.available !== false && (
        <>
          <div className="ins-note">
            Areas where the modelled interventions produce the strongest cooling
            (XGBoost scenario deltas — model-derived).
          </div>
          <div className="intervention-list">
            {items.map((item, i) => (
              <button
                className="intervention-item"
                key={`${item.scenario}-${item.grid_id}`}
                onClick={() => { onFlyTo?.(item.latitude, item.longitude, 15); onSelect?.({ name: `Zone ${item.grid_id} (${item.scenario})`, lat: item.latitude, lng: item.longitude }); }}
              >
                <span className="intervention-rank">{i + 1}</span>
                <span className="intervention-body">
                  <strong>{item.scenario.replace(/_/g, ' ')}</strong>
                  <span>Zone {item.grid_id}</span>
                </span>
                <span className="intervention-nums">
                  <span className="num-cur">{fmt(item.current_lst_c)} °C</span>
                  <span className="num-after">{fmt(item.after_lst_c)} °C</span>
                  <span className="num-cool">−{Math.abs(item.cooling_c).toFixed(1)} °C</span>
                </span>
              </button>
            ))}
          </div>
          <div className="ins-foot-note">
            Current → after · cooling = modelled Δ LST (scenario − baseline)
          </div>
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Heat-safe route — fastest vs lower-heat-exposure routing.
// ---------------------------------------------------------------------------
function RouteFinder({ onRouteResult, selectedLocation }) {
  const [start, setStart] = useState('');
  const [end, setEnd] = useState('');
  const [startSuggest, setStartSuggest] = useState([]);
  const [endSuggest, setEndSuggest] = useState([]);
  const [activeField, setActiveField] = useState(null);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const rootRef = useRef(null);

  useEffect(() => {
    const onDoc = (e) => {
      if (rootRef.current && !rootRef.current.contains(e.target)) {
        setStartSuggest([]);
setEndSuggest([]);
        setActiveField(null);
      }
    };
    document.addEventListener('mousedown', onDoc);
    return () => document.removeEventListener('mousedown', onDoc);
  }, []);

  const resolve = async (field, text) => {
    const places = await searchPlaces(text);
    return places[0] || null;
  };

  const calculate = async () => {
    if (!start.trim() || !end.trim()) {
      setError('Enter both a start and a destination.');
      return;
    }
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const s = await resolve('start', start);
      const e = await resolve('end', end);
      if (!s || !e) {
        setError('Could not geocode one of the places. Try a more specific name (e.g. "Patia, Bhubaneswar").');
        return;
      }
      const route = await fetchHeatSafeRoute({ lat: s.lat, lng: s.lng }, { lat: e.lat, lng: e.lng });
      setResult(route);
      onRouteResult?.(route);
    } catch {
      setError('Routing unavailable. Check that the backend is running.');
    } finally {
      setLoading(false);
    }
  };

  const applySelected = (field) => {
    if (!selectedLocation) return;
    if (field === 'start') {
      setStart(selectedLocation.name);
      setActiveField(null);
    } else {
      setEnd(selectedLocation.name);
      setActiveField(null);
    }
  };

  const fieldChange = (field, value) => {
    if (field === 'start') {
      setStart(value);
      setStartSuggest([]);
      if (value.trim().length >= 2) {
        searchPlaces(value).then(setStartSuggest);
      }
    } else {
      setEnd(value);
      setEndSuggest([]);
      if (value.trim().length >= 2) {
        searchPlaces(value).then(setEndSuggest);
      }
    }
  };

  const fieldPick = (field, place) => {
    if (field === 'start') {
      setStart(place.shortName || place.name);
      setStartSuggest([]);
    } else {
      setEnd(place.shortName || place.name);
      setEndSuggest([]);
    }
    setActiveField(null);
  };

  const r = (dir) => result?.[dir];
  const hasBoth = result?.fastest && result?.coolest;

  return (
    <div className="ins-tab" ref={rootRef}>
      <div className="ins-tab-head">
        <Route size={14} color="#0284c7" />
        <strong>Heat-safe route</strong>
      </div>
      <div className="ins-note">
        Compares the <strong>fastest</strong> route with a{' '}
        <strong>lower-heat-exposure</strong> route across the real 100 m model
        grid. Grid-level estimate — not a medical/safety claim.
      </div>

      <div className="route-field">
        <label>Start</label>
        <div className="route-input-wrap">
          <input
            type="text"
            value={start}
            onChange={(e) => fieldChange('start', e.target.value)}
            onFocus={() => setActiveField('start')}
            placeholder="e.g. Khandagiri"
            aria-label="Route start"
          />
          {selectedLocation && (
            <button className="route-use" onClick={() => applySelected('start')} title="Use selected location">use selected</button>
          )}
        </div>
        {activeField === 'start' && startSuggest.length > 0 && (
          <div className="route-suggest">
            {startSuggest.map((p) => (
              <button key={p.id} onClick={() => fieldPick('start', p)}>
                <MapPin size={11} /> {p.shortName}
              </button>
            ))}
          </div>
        )}
      </div>

      <div className="route-field">
        <label>Destination</label>
        <div className="route-input-wrap">
          <input
            type="text"
            value={end}
            onChange={(e) => fieldChange('end', e.target.value)}
            onFocus={() => setActiveField('end')}
            placeholder="e.g. Bhubaneswar Railway Station"
            aria-label="Route destination"
          />
          {selectedLocation && (
            <button className="route-use" onClick={() => applySelected('end')} title="Use selected location">use selected</button>
          )}
        </div>
        {activeField === 'end' && endSuggest.length > 0 && (
          <div className="route-suggest">
            {endSuggest.map((p) => (
              <button key={p.id} onClick={() => fieldPick('end', p)}>
                <MapPin size={11} /> {p.shortName}
              </button>
            ))}
          </div>
        )}
      </div>

      <button className="route-calc" onClick={calculate} disabled={loading}>
        {loading ? <Loader2 size={13} className="spin" /> : <Navigation size={13} />}
        {loading ? 'Calculating…' : 'Calculate routes'}
      </button>

      {error && <div className="ins-error"><AlertTriangle size={13} /> {error}</div>}

      {hasBoth && (
        <div className="route-compare">
          <div className="route-col fastest">
            <strong>⚡ FASTEST</strong>
            <span>{fmt(r('fastest').distance_km, 2)} km · {fmt(r('fastest').time_min, 0)} min walk</span>
            <span>Avg heat {fmt(r('fastest').avg_lst_c)} °C · Max {fmt(r('fastest').max_lst_c)} °C</span>
          </div>
          <div className="route-col coolest">
            <strong>🌿 LOWER-HEAT</strong>
            <span>{fmt(r('coolest').distance_km, 2)} km · {fmt(r('coolest').time_min, 0)} min walk</span>
            <span>Avg heat {fmt(r('coolest').avg_lst_c)} °C · Max {fmt(r('coolest').max_lst_c)} °C</span>
          </div>
          {result.note && <small className="route-note">{result.note}</small>}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Cooling opportunities — areas where interventions have high impact.
// ---------------------------------------------------------------------------
function CoolingOpportunities({ onFlyTo }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let stale = false;
    setLoading(true);
    fetchCoolingPotential()
      .then((d) => { if (!stale) setData(d); })
      .catch(() => { if (!stale) setData({ available: false, message: 'Cooling opportunities unavailable.' }); })
      .finally(() => { if (!stale) setLoading(false); });
    return () => { stale = true; };
  }, []);

  const opportunities = data?.cells || [];
  return (
    <div className="ins-tab">
      <div className="ins-tab-head">
        <Sprout size={14} color="#16a34a" />
        <strong>Cooling Opportunities</strong>
      </div>
      {loading && <div className="ins-loading"><Loader2 size={14} className="spin" /> Loading cooling opportunities…</div>}
      {!loading && data?.available === false && <div className="ins-error"><AlertTriangle size={13} /> {data.message}</div>}
      {!loading && data?.available !== false && (
        <div className="opportunity-list">
          {opportunities.slice(0, 10).map((o, i) => (
            <div className="opportunity-item" key={o.grid_id}>
              <strong>Opportunity {i + 1}</strong>
              <span>Grid {o.grid_id}: {fmt(o.max_cooling_c)}°C potential cooling</span>
              <span className="opportunity-scenario">{o.best_scenario}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Intervention ranker — automatically rank available interventions.
// ---------------------------------------------------------------------------
function InterventionRanker({ onSelect }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let stale = false;
    setLoading(true);
    fetchInterventions(5)
      .then((d) => { if (!stale) setData(d); })
      .catch(() => { if (!stale) setData({ available: false, message: 'Intervention ranking unavailable.' }); })
      .finally(() => { if (!stale) setLoading(false); });
    return () => { stale = true; };
  }, []);

  const items = data?.interventions || [];
  return (
    <div className="ins-tab">
      <div className="ins-tab-head">
        <Sprout size={14} color="#16a34a" />
        <strong>Intervention Ranker</strong>
      </div>
      {loading && <div className="ins-loading"><Loader2 size={14} className="spin" /> Ranking interventions…</div>}
      {!loading && data?.available === false && <div className="ins-error"><AlertTriangle size={13} /> {data.message}</div>}
      {!loading && data?.available !== false && (
        <ol className="ranking-list">
          {items.map((item, i) => {
            const cooling = Math.abs(item.cooling_c);
            return (
              <li key={`${item.scenario}-${item.grid_id}`} className="ranking-item">
                <span className="rank-number">{i + 1}</span>
                <span className="rank-scenario">{item.scenario.replace(/_/g, ' ')}</span>
                <span className="rank-cooling">−{cooling.toFixed(1)}°C</span>
                <span className="rank-grid">Zone {item.grid_id}</span>
              </li>
            );
          })}
        </ol>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Decision Centre panel — main component.
// ---------------------------------------------------------------------------
export const InsightsPanel = ({
  onFlyTo,
  onSelectLocation,
  selectedLocation,
  defaultTab = 'interventions'
}) => {
  const [tab, setTab] = useState(defaultTab);

  return (
    <div className="insights-panel">
      <div className="insights-tabs" role="tablist">
        <button
          key="interventions"
          role="tab"
          aria-selected={tab === 'interventions'}
          className={`insights-tab ${tab === 'interventions' ? 'active' : ''}`}
          onClick={() => setTab('interventions')}
          title="Interventions">
          <Sprout size={14} color="#16a34a" />
          <span>Interventions</span>
        </button>
        <button
          key="route"
          role="tab"
          aria-selected={tab === 'route'}
          className={`insights-tab ${tab === 'route' ? 'active' : ''}`}
          onClick={() => setTab('route')}
          title="Heat-safe Route">
          <Route size={14} color="#0284c7" />
          <span>Route</span>
        </button>
        <button
          key="cooling"
          role="tab"
          aria-selected={tab === 'cooling'}
          className={`insights-tab ${tab === 'cooling' ? 'active' : ''}`}
          onClick={() => setTab('cooling')}
          title="Cooling Opportunities">
          <Sprout size={14} color="#16a34a" />
          <span>Cooling</span>
        </button>
        <button
          key="rank"
          role="tab"
          aria-selected={tab === 'rank'}
          className={`insights-tab ${tab === 'rank' ? 'active' : ''}`}
          onClick={() => setTab('rank')}
          title="Intervention Ranker">
          <Sprout size={14} color="#16a34a" />
          <span>Ranker</span>
        </button>
      </div>
      <div className="insights-body">
        {tab === 'interventions' && (
          <InterventionFinder onFlyTo={onFlyTo} onSelect={onSelectLocation} />
        )}
        {tab === 'route' && (
          <RouteFinder onRouteResult={undefined} selectedLocation={selectedLocation} onSelect={onSelectLocation} />
        )}
        {tab === 'cooling' && (
          <CoolingOpportunities onFlyTo={onFlyTo} />
        )}
        {tab === 'rank' && (
          <InterventionRanker onSelect={onSelectLocation} />
        )}
      </div>
    </div>
  );
};

export default InsightsPanel;