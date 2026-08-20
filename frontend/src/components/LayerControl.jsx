import React, { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { ChevronDown, Building2, Sprout, Map as MapIcon, Flame, Mountain, Wind, CloudSun, EyeOff, Loader2 } from 'lucide-react';
import { CITY_LAYER_DEFINITIONS, groupDefinitions, getDataset } from '../services/thematicData';
import { Legend } from './Legend';

// Grouped layer control (Session 3).
//  - CITY layers are real OSM toggles.
//  - Thematic layers (vegetation / land cover / heat / terrain / air quality)
//    only appear as interactive toggles when the backend reports the data
//    exists; otherwise the group shows an explicit "Unavailable" note.
const GROUP_ICONS = {
  CITY: Building2,
  VEGETATION: Sprout,
  'LAND COVER': MapIcon,
  HEAT: Flame,
  TERRAIN: Mountain,
  'AIR QUALITY': Wind,
  WEATHER: CloudSun
};

const ThemeToggle = ({ checked, onChange, color = '#0284c7' }) => (
  <label className="layer-toggle" style={{ '--toggle-accent': color }}>
    <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
    <span className="layer-toggle-track"><span className="layer-toggle-thumb" /></span>
  </label>
);

const LayerRow = ({ label, icon: Icon, color, checked, onChange, opacity, onOpacity, legend, active }) => (
  <div className={`layer-row ${active ? 'layer-row-active' : ''}`}>
    <div className="layer-row-main">
      <Icon size={14} color={color} />
      <span className="layer-row-label">{label}</span>
      <ThemeToggle checked={checked} onChange={onChange} color={color} />
    </div>
    {checked && onOpacity && (
      <div className="layer-opacity">
        <span>Opacity</span>
        <input
          type="range" min="10" max="100" value={opacity ?? 80}
          onChange={(e) => onOpacity(Number(e.target.value))}
        />
        <span>{opacity ?? 80}%</span>
      </div>
    )}
    <AnimatePresence>
      {checked && legend && active && (
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

export const LayerControl = ({
  showBuildings, setShowBuildings,
  showRoads, setShowRoads,
  showGreen, setShowGreen,
  showWater, setShowWater,
  showTrees, setShowTrees,
  availability = {},
  thematicToggles = {},
  setThematicToggle = () => {},
  opacities = {},
  setOpacity = () => {},
  showWeatherPanel = false,
  setShowWeatherPanel = () => {},
  monitoringLoading = false
}) => {
  const [openGroups, setOpenGroups] = useState({ CITY: true, VEGETATION: false, HEAT: false, WEATHER: false });

  const cityLayers = CITY_LAYER_DEFINITIONS;
  const cityState = {
    buildings: showBuildings,
    roads: showRoads,
    green: showGreen,
    water: showWater,
    trees: showTrees
  };
  const citySetters = {
    buildings: setShowBuildings,
    roads: setShowRoads,
    green: setShowGreen,
    water: setShowWater,
    trees: setShowTrees
  };

  // thematic definitions grouped; toggles only render when data exists
  const thematicDefinitions = groupDefinitions(
    ['ndvi', 'green_cover', 'vegetation_density', 'land_cover', 'lst', 'heat_class',
     'elevation', 'slope', 'aspect', 'hillshade', 'aqi', 'pm25', 'pm10', 'no2',
     'so2', 'o3', 'co'].map(getDataset).filter(Boolean)
  );

  const thematicGroupAvailable = (group) =>
    (thematicDefinitions[group] || []).some((d) => availability[d.key]);

  const toggleGroup = (group) => setOpenGroups((prev) => ({ ...prev, [group]: !prev[group] }));

  const renderGroup = (title, content, badge) => {
    const Icon = GROUP_ICONS[title] || MapIcon;
    const open = openGroups[title] !== false;
    return (
      <div className="layer-group" key={title}>
        <button className="layer-group-head" onClick={() => toggleGroup(title)}>
          <Icon size={14} color="var(--text-secondary)" />
          <span>{title}</span>
          {badge && <span className={`layer-badge ${badge.type}`}>{badge.text}</span>}
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
              {content}
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    );
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      className="light-panel layer-control-panel"
    >
      <div className="layer-control-head">
        <span className="layer-control-title">Map Layers</span>
        {monitoringLoading && <span className="layer-control-status"><Loader2 size={12} className="spin" /> checking data…</span>}
      </div>

      {/* CITY - always real OSM data */}
      {renderGroup('CITY', (
        <div className="layer-group-body">
          {cityLayers.map((layer) => (
            <LayerRow
              key={layer.key}
              label={layer.name}
              icon={MapIcon}
              color={layer.legend.stops[0]?.color || '#64748b'}
              checked={cityState[layer.key]}
              onChange={citySetters[layer.key]}
              opacity={opacities[layer.key]}
              onOpacity={(v) => setOpacity(layer.key, v)}
              legend={layer.legend}
              active
            />
          ))}
        </div>
      ))}

      {/* WEATHER monitoring toggle */}
      {renderGroup('WEATHER', (
        <div className="layer-group-body">
          <div className="layer-row">
            <div className="layer-row-main">
              <CloudSun size={14} color="#0284c7" />
              <span className="layer-row-label">Weather monitoring</span>
              <ThemeToggle checked={showWeatherPanel} onChange={setShowWeatherPanel} color="#0284c7" />
            </div>
          </div>
          <div className="layer-note">
            Live OpenWeather API observations (real). NASA POWER historical
            processing appears here once the pipeline has run.
          </div>
        </div>
      ))}

      {/* Thematic groups */}
      {Object.keys(thematicDefinitions).map((group) => {
        const available = thematicGroupAvailable(group);
        return renderGroup(group, (
          <div className="layer-group-body">
            {available ? (
              thematicDefinitions[group].map((defn) => (
                <LayerRow
                  key={defn.key}
                  label={defn.name}
                  icon={MapIcon}
                  color={defn.legend.stops[0]?.color || '#64748b'}
                  checked={Boolean(thematicToggles[defn.key])}
                  onChange={(v) => setThematicToggle(defn.key, v)}
                  opacity={opacities[defn.key]}
                  onOpacity={(v) => setOpacity(defn.key, v)}
                  legend={defn.legend}
                  active
                />
              ))
            ) : (
              <div className="layer-unavailable">
                <EyeOff size={13} />
                <span>Data not produced yet — run <code>gis-engine</code> pipeline ({group.toLowerCase().replace(' ', '-')})</span>
              </div>
            )}
          </div>
        ), available ? null : { text: 'Unavailable', type: 'warn' });
      })}
    </motion.div>
  );
};

export default LayerControl;
