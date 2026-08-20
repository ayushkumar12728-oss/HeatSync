import React, { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  ChevronDown, Building2, Sprout, Map as MapIcon, Flame, Mountain,
  Wind, CloudSun, RotateCcw, MountainSnow, Thermometer, SunMedium
} from 'lucide-react';
import { getDataset, getCityLayer } from '../services/thematicData';
import { Legend } from './Legend';

// ---------------------------------------------------------------------------
// Layer registry — every layer the map can render, organised by UI group.
// Thematic layers are only interactive when their dataset is available
// (backend monitoring report); otherwise the row says UNAVAILABLE.
// ---------------------------------------------------------------------------
const THEMATIC_KEYS = {
  VEGETATION: ['ndvi', 'green_cover', 'vegetation_density'],
  'LAND COVER': ['land_cover'],
  HEAT: ['lst', 'predicted_lst', 'heat_class'],
  'AIR QUALITY': ['aqi', 'pm25', 'pm10', 'no2', 'so2', 'o3', 'co'],
  TERRAIN: ['elevation', 'slope', 'aspect', 'hillshade', 'terrain_3d']
};

const GROUP_ICONS = {
  CITY: Building2,
  VEGETATION: Sprout,
  'LAND COVER': MapIcon,
  HEAT: Flame,
  'AIR QUALITY': Wind,
  TERRAIN: Mountain,
  WEATHER: CloudSun
};

const CITY_KEYS = ['buildings', 'roads', 'water', 'green', 'trees', 'boundary'];

// Per-layer display metadata (units / legends come from the project config).
const EXTRA_META = {
  terrain_3d: {
    name: 'Terrain Elevation (3D)',
    icon: MountainSnow,
    color: '#8c510a',
    source: 'Copernicus DEM GLO-30 / SRTM (30 m)',
    note: 'Real DEM rendered with MapLibre terrain — no vertical exaggeration.',
    legend: { title: 'Terrain', stops: [{ color: '#74c476', label: 'Low (~20 m)' }, { color: '#fee08b', label: 'Mid (~50 m)' }, { color: '#8c510a', label: 'High (~90 m)' }], note: 'DEM source: data/processed/dem' }
  },
  weather: {
    name: 'Live Weather',
    icon: CloudSun,
    color: '#0284c7',
    source: 'OpenWeather (live)',
    note: 'Current air temperature, humidity, wind and pressure. Not LST.'
  }
};

const weatherLegend = {
  title: 'Weather',
  stops: [
    { color: '#0ea5e9', label: 'Cool (< 25 °C)' },
    { color: '#eab308', label: 'Warm (25–35 °C)' },
    { color: '#dc2626', label: 'Hot (> 35 °C)' }
  ],
  note: 'Live air temperature — OpenWeather'
};

const ThemeToggle = ({ checked, onChange, color = '#0284c7', disabled = false }) => (
  <label className={`layer-toggle ${disabled ? 'layer-toggle-disabled' : ''}`} style={{ '--toggle-accent': color }}>
    <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} disabled={disabled} />
    <span className="layer-toggle-track"><span className="layer-toggle-thumb" /></span>
  </label>
);

function layerLegend(layerKey, overlayMeta) {
  if (layerKey === 'terrain_3d') return EXTRA_META.terrain_3d.legend;
  if (layerKey === 'weather') return weatherLegend;
  const thematic = getDataset(layerKey);
  if (thematic?.legend) return thematic.legend;
  const city = getCityLayer(layerKey);
  if (city?.legend) return city.legend;
  const meta = overlayMeta?.[layerKey];
  if (meta?.stops) {
    return { title: meta.title, unit: meta.unit, stops: meta.stops, note: meta.source };
  }
  return null;
}

function layerSource(layerKey, overlayMeta) {
  const meta = overlayMeta?.[layerKey];
  if (meta?.source) return meta.source;
  const thematic = getDataset(layerKey);
  if (thematic?.source) return thematic.source;
  const city = getCityLayer(layerKey);
  if (city?.legend?.note) return city.legend.note;
  return EXTRA_META[layerKey]?.source || '—';
}

function layerResolution(layerKey) {
  const thematic = getDataset(layerKey);
  if (thematic?.resolution) return thematic.resolution;
  const resolutions = {
    buildings: 'OSM footprints', roads: 'OSM network', water: 'OSM polygons',
    green: 'OSM polygons', trees: 'OSM points', boundary: 'study area',
    terrain_3d: '30 m DEM', weather: 'live API'
  };
  return resolutions[layerKey] || '—';
}

export const LayerManager = ({
  layers = {},
  setLayer = () => {},
  opacities = {},
  setOpacity = () => {},
  availability = {},
  overlayMeta = {},
  liveWeather = null,
  showWeatherPanel = true,
  setShowWeatherPanel = () => {},
  onResetAll = null
}) => {
  const [openGroups, setOpenGroups] = useState({
    CITY: true, VEGETATION: false, 'LAND COVER': false, HEAT: false,
    'AIR QUALITY': false, TERRAIN: false, WEATHER: false
  });

  const resetAll = onResetAll || (() => {});
  const toggleGroup = (group) => setOpenGroups((prev) => ({ ...prev, [group]: !prev[group] }));

  // Live weather is a live API (OpenWeather), not a file-based dataset: its
  // availability comes from the actual provider response, never from the
  // raster/monitoring report.
  const weatherAvailable = liveWeather?.status === 'available';

  const renderLayerRow = (group, key) => {
    const meta = EXTRA_META[key];
    const available = availability[key] === true;
    const checked = Boolean(layers[group]?.[key]);

    if (!available) {
      return (
        <div className="layer-row layer-row-unavailable" key={key}>
          <div className="layer-row-main">
            {meta ? <meta.icon size={14} color="var(--text-muted)" /> : <MapIcon size={14} color="var(--text-muted)" />}
            <span className="layer-row-label">{meta?.name || key}</span>
            <span className="layer-unavail-badge">UNAVAILABLE</span>
          </div>
          <small className="layer-row-meta">Source: {layerSource(key, overlayMeta)} · Resolution: {layerResolution(key)}</small>
        </div>
      );
    }

    const name = meta?.name || getDataset(key)?.name || getCityLayer(key)?.name || key;
    const color = meta?.color || getDataset(key)?.legend?.stops?.[0]?.color || '#64748b';
    const legend = checked ? layerLegend(key, overlayMeta) : null;
    const source = layerSource(key, overlayMeta);
    const resolution = layerResolution(key);

    return (
      <div className={`layer-row ${checked ? 'layer-row-active' : ''}`} key={key}>
        <div className="layer-row-main">
          {meta ? <meta.icon size={14} color={color} /> : <MapIcon size={14} color={color} />}
          <span className="layer-row-label">{name}</span>
          <ThemeToggle
            checked={checked}
            onChange={(v) => setLayer(group, key, v)}
            color={color}
          />
        </div>
        {checked && (
          <div className="layer-opacity">
            <span>Opacity</span>
            <input
              type="range" min="10" max="100" value={opacities[key] ?? 80}
              onChange={(e) => setOpacity(key, Number(e.target.value))}
              aria-label={`${name} opacity`}
            />
            <span>{opacities[key] ?? 80}%</span>
          </div>
        )}
        {checked && (
          <div className="layer-row-meta">
            <span>Source: {source}</span>
            <span>Resolution: {resolution}</span>
          </div>
        )}
        <AnimatePresence initial={false}>
          {checked && legend && (
            <motion.div
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: 'auto' }}
              exit={{ opacity: 0, height: 0 }}
              style={{ overflow: 'hidden' }}
            >
              <Legend {...legend} compact />
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    );
  };

  const renderGroup = (group) => {
    const Icon = GROUP_ICONS[group] || MapIcon;
    const open = openGroups[group] !== false;
    const keys = group === 'CITY' ? CITY_KEYS : THEMATIC_KEYS[group] || [];
    const availableCount = group === 'WEATHER'
      ? (weatherAvailable ? 1 : 0)
      : keys.filter((k) => availability[k] === true).length;
    const badge = availableCount === 0
      ? { text: 'UNAVAILABLE', cls: 'layer-badge warn' }
      : group === 'WEATHER'
        ? { text: 'LIVE', cls: 'layer-badge ok' }
        : { text: `${availableCount}/${keys.length}`, cls: 'layer-badge ok' };

    return (
      <div className="layer-group" key={group}>
        <button className="layer-group-head" onClick={() => toggleGroup(group)} aria-expanded={open}>
          <Icon size={14} />
          <span>{group}</span>
          <span className={badge.cls}>{badge.text}</span>
          <ChevronDown size={14} className={`layer-chevron ${open ? 'open' : ''}`} />
        </button>
        <AnimatePresence initial={false}>
          {open && (
            <motion.div
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: 'auto' }}
              exit={{ opacity: 0, height: 0 }}
              style={{ overflow: 'hidden' }}
            >
              <div className="layer-group-body">
                {group === 'WEATHER' ? (
                  <div className={`layer-row ${weatherAvailable ? 'layer-row-active' : 'layer-row-unavailable'}`}>
                    <div className="layer-row-main">
                      <CloudSun size={14} color={weatherAvailable ? '#0284c7' : 'var(--text-muted)'} />
                      <span className="layer-row-label">Weather monitoring</span>
                      {weatherAvailable
                        ? <span className="tag-live">LIVE</span>
                        : <span className="layer-unavail-badge">UNAVAILABLE</span>}
                      <ThemeToggle
                        checked={showWeatherPanel && weatherAvailable}
                        onChange={setShowWeatherPanel}
                        color="#0284c7"
                        disabled={!weatherAvailable}
                      />
                    </div>
                    <div className="layer-row-meta">
                      <span>Source: {liveWeather?.source || 'OpenWeather'} (live)</span>
                      <span>Type: live observation (not LST)</span>
                    </div>
                    {weatherAvailable && (
                      <div className="layer-row-meta">
                        <span>{liveWeather.temperature != null ? `${liveWeather.temperature} °C` : ''}{liveWeather.humidity != null ? ` · ${liveWeather.humidity}% RH` : ''}</span>
                        <span>Updated: {liveWeather.fetchedAt ? new Date(liveWeather.fetchedAt).toLocaleTimeString() : '—'}</span>
                      </div>
                    )}
                  </div>
                ) : (
                  keys.map((key) => renderLayerRow(group, key))
                )}
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    );
  };

  return (
    <div className="layer-manager">
      <div className="layer-manager-head">
        <span className="layer-control-title">Map Layers</span>
        <button className="layer-panel-reset" onClick={resetAll} title="Reset all layers">
          <RotateCcw size={11} /> Reset All
        </button>
      </div>
      <div className="layer-manager-legend-note">
        <Thermometer size={12} /> Heat overlays sit transparently ON the 3D city.
      </div>
      {Object.keys(GROUP_ICONS).map((group) => renderGroup(group))}
      <div className="layer-manager-foot">
        <SunMedium size={12} />
        <span>Only datasets that exist on disk are interactive. Missing data shows UNAVAILABLE — nothing is fabricated.</span>
      </div>
    </div>
  );
};

export default LayerManager;
