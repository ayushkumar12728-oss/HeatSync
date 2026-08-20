import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Search, MapPin, Loader2, X, Building, Landmark, Clock } from 'lucide-react';
import { searchPlaces, MIN_QUERY_LENGTH } from '../services/geocoding';

const RECENT_KEY = 'heatsync.recentSearches';
const RECENT_MAX = 5;

function loadRecent() {
  try {
    const raw = localStorage.getItem(RECENT_KEY);
    const list = raw ? JSON.parse(raw) : [];
    return Array.isArray(list) ? list.slice(0, RECENT_MAX) : [];
  } catch {
    return [];
  }
}

function saveRecent(place) {
  try {
    const list = loadRecent().filter((p) => !(p.name === place.name && p.lat === place.lat));
    list.unshift({ name: place.shortName || place.name, lat: place.lat, lng: place.lng, at: Date.now() });
    localStorage.setItem(RECENT_KEY, JSON.stringify(list.slice(0, RECENT_MAX)));
  } catch {
    /* storage unavailable — recent searches simply don't persist */
  }
}

// Prominent global search: "Search Bhubaneswar…".
// All results come from OpenStreetMap Nominatim (debounced, cached,
// bounded) — no example locations are hardcoded. Includes keyboard
// navigation, recent searches, loading/error states and a clear button.
export const CitySearch = ({ onSelect, placeholder = 'Search any place in Bhubaneswar…', autoFocus = false }) => {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState([]);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [highlight, setHighlight] = useState(-1);
  const [recent, setRecent] = useState(loadRecent());
  const rootRef = useRef(null);
  const inputRef = useRef(null);

  const showRecent = useMemo(() => open && query.trim().length < MIN_QUERY_LENGTH && recent.length > 0, [open, query, recent]);

  useEffect(() => {
    const onDocClick = (e) => {
      if (rootRef.current && !rootRef.current.contains(e.target)) setOpen(false);
    };
    document.addEventListener('mousedown', onDocClick);
    return () => document.removeEventListener('mousedown', onDocClick);
  }, []);

  useEffect(() => {
    if (query.trim().length < MIN_QUERY_LENGTH) {
      setResults([]);
      setLoading(false);
      setError(null);
      setHighlight(-1);
      return;
    }
    setLoading(true);
    setError(null);
    let stale = false;
    searchPlaces(query).then((places) => {
      if (stale) return;
      setLoading(false);
      setResults(places);
      setHighlight(-1);
      setOpen(true);
      if (places.length === 0) setError('No results found nearby. Try a street, locality or landmark.');
    });
    return () => { stale = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [query]);

  const select = (place) => {
    setOpen(false);
    setQuery(place.shortName || place.name);
    setHighlight(-1);
    saveRecent(place);
    setRecent(loadRecent());
    onSelect?.(place);
  };

  const clear = () => {
    setQuery('');
    setResults([]);
    setOpen(false);
    setError(null);
    inputRef.current?.focus();
  };

  const list = showRecent ? recent.map((r) => ({ ...r, recent: true })) : results;

  const onKeyDown = (e) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      if (list.length) { setOpen(true); setHighlight((h) => (h + 1) % list.length); }
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      if (list.length) setHighlight((h) => (h - 1 + list.length) % list.length);
    } else if (e.key === 'Enter') {
      if (highlight >= 0 && list[highlight]) {
        e.preventDefault();
        select(list[highlight]);
      }
    } else if (e.key === 'Escape') {
      setOpen(false);
      setHighlight(-1);
    }
  };

  const typeIcon = (type) => {
    if (['city', 'town', 'village', 'suburb', 'neighbourhood'].includes(type)) return <Landmark size={14} />;
    return <Building size={14} />;
  };

  return (
    <div className="city-search" ref={rootRef}>
      <div className="city-search-box">
        <Search size={15} className="city-search-icon" aria-hidden />
        <input
          ref={inputRef}
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onFocus={() => { setOpen(true); }}
          onKeyDown={onKeyDown}
          placeholder={placeholder}
          aria-label="Search Bhubaneswar"
          role="combobox"
          aria-expanded={open}
          aria-autocomplete="list"
          autoComplete="off"
          autoFocus={autoFocus}
          className="city-search-input"
        />
        {loading ? (
          <Loader2 size={14} className="spin city-search-spinner" />
        ) : query ? (
          <button className="city-search-clear" onClick={clear} aria-label="Clear search">
            <X size={14} />
          </button>
        ) : null}
      </div>

      {open && (showRecent || results.length > 0 || error) && (
        <div className="city-search-dropdown" role="listbox" aria-label="Search results">
          {showRecent && (
            <>
              <div className="city-search-recent-label"><Clock size={11} /> Recent searches</div>
              {list.map((place, i) => (
                <button
                  key={`recent-${i}`}
                  className={`city-search-item ${highlight === i ? 'city-search-item-active' : ''}`}
                  onClick={() => select(place)}
                  onMouseEnter={() => setHighlight(i)}
                  role="option"
                  aria-selected={highlight === i}
                >
                  <span className="city-search-item-icon"><Clock size={13} /></span>
                  <span className="city-search-item-body">
                    <strong>{place.name}</strong>
                    <small>Recent search</small>
                  </span>
                </button>
              ))}
            </>
          )}
          {error && !loading && results.length === 0 && !showRecent && (
            <div className="city-search-error">{error}</div>
          )}
          {!showRecent && results.map((place, i) => (
            <button
              key={place.id}
              className={`city-search-item ${highlight === i ? 'city-search-item-active' : ''}`}
              onClick={() => select(place)}
              onMouseEnter={() => setHighlight(i)}
              role="option"
              aria-selected={highlight === i}
            >
              <span className="city-search-item-icon"><MapPin size={13} /></span>
              <span className="city-search-item-body">
                <strong>{place.shortName}</strong>
                <small>{place.name}</small>
              </span>
              <span className="city-search-item-type">{typeIcon(place.type)}</span>
            </button>
          ))}
          <div className="city-search-foot">
            Geocoding: OpenStreetMap Nominatim · debounced + cached · ↑↓ navigate · Enter select
          </div>
        </div>
      )}
    </div>
  );
};

export default CitySearch;
