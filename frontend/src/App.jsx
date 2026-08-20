import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import {
  Box, BarChart3, Layers, X, Clock, Activity, Flame, Wind, Sprout,
  BrainCircuit, Mountain, Bot
} from 'lucide-react';
import { LiveDataProvider, useLiveData } from './context/LiveDataContext';
import { Header } from './components/Header';
import { CitySearch } from './components/CitySearch';
import { DigitalTwinMap3D } from './components/DigitalTwinMap3D';
import { LayerManager } from './components/LayerManager';
import { LocationIntelligencePanel } from './components/LocationIntelligencePanel';
import { TimeMachine } from './components/TimeMachine';
import { BeforeAfterComparison } from './components/BeforeAfterComparison';
import { AnalyticsCharts } from './components/AnalyticsCharts';
import { AIAssistant } from './components/AIAssistant';
import { MonitoringPanel } from './components/MonitoringPanel';
import { SystemStatusBar } from './components/SystemStatusBar';
import { SystemStatusPanel } from './components/SystemStatusPanel';
import { EnvironmentPanel } from './components/EnvironmentPanel';
import { HelpModal } from './components/HelpModal';
import { fetchMonitoringStatus, fetchEnvironmentSummary, buildAvailability } from './services/thematicData';
import { fetchModelInfo, fetchAIStatus, fetchCurrentHeat } from './services/backendClient';
import {
  fetchSystemHealth, buildSystemStatus, fetchLiveWeather, fetchLiveAirQuality
} from './services/systemHealth';

const INITIAL_LAYERS = {
  CITY: { buildings: true, roads: true, water: true, green: true, trees: true, boundary: true },
  VEGETATION: { ndvi: false, green_cover: false, vegetation_density: false },
  'LAND COVER': { land_cover: false },
  HEAT: { lst: false, predicted_lst: true, heat_class: false },
  'AIR QUALITY': { aqi: false, pm25: false, pm10: false, no2: false, so2: false, o3: false, co: false },
  TERRAIN: { elevation: false, slope: false, aspect: false, hillshade: false, terrain_3d: false },
  WEATHER: {}
};

// Quick domain chips — one-click access to the most important overlays.
const DOMAIN_CHIPS = [
  { key: 'heat', label: 'Heat', layerKey: 'lst', group: 'HEAT', icon: Flame, color: '#dc2626' },
  { key: 'aqi', label: 'AQI', layerKey: 'aqi', group: 'AIR QUALITY', icon: Wind, color: '#d97706' },
  { key: 'veg', label: 'Vegetation', layerKey: 'ndvi', group: 'VEGETATION', icon: Sprout, color: '#16a34a' },
  { key: 'model', label: 'Model', layerKey: 'predicted_lst', group: 'HEAT', icon: BrainCircuit, color: '#9333ea' },
  { key: 'terrain', label: 'Terrain', layerKey: 'terrain_3d', group: 'TERRAIN', icon: Mountain, color: '#8c510a' }
];

// Four primary modes — the map is always the centre of the product.
const MODES = [
  { key: 'city', label: 'City', icon: Box, title: '3D city digital twin' },
  { key: 'environment', label: 'Environment', icon: Mountain, title: 'LST · AQI · NDVI · terrain · weather' },
  { key: 'decision', label: 'Decision', icon: Layers, title: 'Scenario simulator' }
];

const REFRESH_INTERVAL_MS = 5 * 60 * 1000; // weather + health refresh (Phase 20)

// Inner App component that uses the LiveDataContext
function AppInner() {
  const {
    weather: liveWeather,
    airQuality,
    prediction: snapshotPrediction,
    snapshotId,
    generatedAt,
    snapshotLoading,
    connectionState,
    freshness,
    refreshNow: refreshSnapshot,
  } = useLiveData();
  const [theme, setTheme] = useState('light');
  const [mode, setMode] = useState('city'); // city | environment | decision

  // --- layer state ------------------------------------------------------ #
  const [layers, setLayers] = useState(INITIAL_LAYERS);
  const [opacities, setOpacities] = useState({});
  const [showCooling, setShowCooling] = useState(false);
  const [coolingGeoJson, setCoolingGeoJson] = useState(null);
  const [routeData, setRouteData] = useState(null);
  const [availability, setAvailability] = useState({ osm: true });
  const [overlayMeta, setOverlayMeta] = useState({});

  // --- other data (non-snapshot) ------------------------------------------ #
  const [monitoring, setMonitoring] = useState(null);
  const [environmentSummary, setEnvironmentSummary] = useState(null);
  const [modelInfo, setModelInfo] = useState(null);
  const [aiStatus, setAiStatus] = useState(null);
  const [currentPrediction, setCurrentPrediction] = useState(null);

  // --- system health (replaces the old "1/11 APIs" audit) ---------------- #
  const [health, setHealth] = useState(null);
  const [healthLoading, setHealthLoading] = useState(true);
  const [healthError, setHealthError] = useState(null);
  const systemStatus = useMemo(
    () => buildSystemStatus(health, healthError),
    [health, healthError]
  );

  // --- interactions ----------------------------------------------------- #
  const [selectedLocation, setSelectedLocation] = useState(null);
  const [flyTo, setFlyTo] = useState(null);
  const [scenarioOverlay, setScenarioOverlay] = useState(null);
  const [showAi, setShowAi] = useState(false);
  const [showTimeMachine, setShowTimeMachine] = useState(false);
  const [historicalDate, setHistoricalDate] = useState(null);
  const [historicalLayerData, setHistoricalLayerData] = useState(null);
  const [showMonitoringDrawer, setShowMonitoringDrawer] = useState(false);
  const [drawer, setDrawer] = useState(null); // 'layers' (mobile)
  const [showHelp, setShowHelp] = useState(false);
  const [showSystemStatus, setShowSystemStatus] = useState(false);

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
  }, [theme]);

  // --- system health + live data loaders ---------------------------------- #
  const loadSystemHealth = useCallback(() => {
    setHealthLoading(true);
    setHealthError(null);
    fetchSystemHealth()
      .then(setHealth)
      .catch((err) => { setHealth(null); setHealthError(err); })
      .finally(() => setHealthLoading(false));
  }, []);

  // Use snapshot-based refresh instead of individual API calls
  const handleRefresh = useCallback(() => {
    loadSystemHealth();
    refreshSnapshot();
    // Also refresh current heat prediction
    fetchCurrentHeat()
      .then((d) => { if (d?.success) setCurrentPrediction(d); })
      .catch(() => {});
  }, [loadSystemHealth, refreshSnapshot]);


  const handleRouteResult = (data) => {
  setRouteData(data);
  };  // --- boot -------------------------------------------------------------- #
useEffect(() => {
  fetch('/overlays/overlays.json')
    .then((r) => (r.ok ? r.json() : null))
    .then((manifest) => {
      if (manifest?.overlays) {
        setOverlayMeta(manifest.overlays);
      }
    })
    .catch(() => {});

  loadSystemHealth();
  // Snapshot is fetched by LiveDataProvider on mount

  fetchMonitoringStatus().then((status) => {
    setMonitoring(status);
    setAvailability(buildAvailability(status));
  });

  fetchEnvironmentSummary().then(setEnvironmentSummary);

  fetchModelInfo()
    .then(setModelInfo)
    .catch(() =>
      setModelInfo({
        available: false,
        status: 'model_unavailable',
        message: 'Model status API unreachable.',
      })
    );

  fetchAIStatus()
    .then(setAiStatus)
    .catch(() =>
      setAiStatus({
        available: false,
        status: 'offline',
        message: 'AI status API unreachable.',
      })
    );

  // Fetch current predicted LST from the live feature pipeline
  fetchCurrentHeat().then((d) => { if (d.success) setCurrentPrediction(d); })
    .catch(() => setCurrentPrediction(null));
}, [loadSystemHealth]);

// --- periodic refresh (health + current prediction) ----------- #
// Weather/AQI refresh is handled by LiveDataProvider
useEffect(() => {
  const timer = setInterval(() => {
    loadSystemHealth();
    // Also refresh current heat prediction so the thermal map stays current
    fetchCurrentHeat()
      .then((d) => { if (d?.success) setCurrentPrediction(d); })
      .catch(() => {});
  }, REFRESH_INTERVAL_MS);

  return () => clearInterval(timer);
}, [loadSystemHealth]);

  // --- layer setters ------------------------------------------------------ #
  const setLayer = useCallback((group, key, value) => {
    setLayers((prev) => {
      const nextGroup = { ...prev[group] };
      if (value && group !== 'CITY') {
        Object.keys(nextGroup).forEach((k) => { nextGroup[k] = false; });
      }
      nextGroup[key] = value;
      return { ...prev, [group]: nextGroup };
    });
  }, []);

  const setOpacity = useCallback((key, value) => {
    setOpacities((prev) => ({ ...prev, [key]: value }));
  }, []);

  const resetAllLayers = useCallback(() => {
    setLayers(INITIAL_LAYERS);
    setOpacities({});
    setShowCooling(false);
    setRouteData(null);
  }, []);

  // --- lazy heavy data: cooling ------------------------------------------------ #
  const toggleCooling = (on) => {
    setShowCooling(on);
    if (on && !coolingGeoJson) fetchCoolingPotentialGeoJson().then(setCoolingGeoJson).catch(() => {});
  };

  // --- scenario overlay (shared with the Decision dock) -------------------- #
  const handleScenarioData = (data) => setScenarioOverlay(data);
  const handleScenarioModeChange = (modeChange) => {
    setScenarioOverlay((prev) => (prev ? { ...prev, mode: modeChange } : prev));
  };

  // --- search / navigation -------------------------------------------------- #
  const handleSearchSelect = (place) => {
    setFlyTo({ lat: place.lat, lng: place.lng, zoom: place.boundingBox ? 15 : 16 });
    setSelectedLocation({ name: place.shortName || place.name, lat: place.lat, lng: place.lng });
  };

  const handleSelectLocation = useCallback((loc) => {
    setSelectedLocation(loc);
  }, []);

  const handleFlyTo = useCallback((lat, lng, zoom = 14) => {
    setFlyTo({ lat, lng, zoom });
  }, []);

  const domainChipActive = (chip) => Boolean(layers[chip.group]?.[chip.layerKey]);

  const toggleDomainChip = (chip) => {
    setLayer(chip.group, chip.layerKey, !domainChipActive(chip));
  };

  // --- map props ------------------------------------------------------------- #
  const mapProps = {
    layers,
    opacities,
    availability,
    overlayMeta,
    scenarioOverlay,
    currentPrediction,
    historicalLayerData,
    historicalDate,
    onScenarioModeChange: handleScenarioModeChange,
    onSelectLocation: handleSelectLocation,
    routeData,
    flyTo,
    selectedPoint: selectedLocation ? { lat: selectedLocation.lat, lng: selectedLocation.lng } : null,
    theme,
    liveWeather
  };

  const leftPanelTitle = {
    city: 'City',
    environment: 'Environment',
    decision: 'Decision'
  }[mode];

  return (
    <div className="app-shell app-shell-3d">

      {/* ================= HEADER ================= */}
      <Header
        theme={theme}
        setTheme={setTheme}
        liveWeatherData={liveWeather}
        onOpenSystemStatus={() => setShowSystemStatus(true)}
        onOpenHelp={() => setShowHelp(true)}
        monitoring={monitoring}
        modelInfo={modelInfo}
        aiStatus={aiStatus}
      />

      {/* ================= SEARCH + DOMAIN CHIPS ================= */}
      <div className="search-strip">
        <div className="search-strip-inner">
          <CitySearch onSelect={handleSearchSelect} />
          <div className="domain-chips" role="toolbar" aria-label="Domain overlays">
            {DOMAIN_CHIPS.map((chip) => (
              <button
                key={chip.key}
                className={`domain-chip ${domainChipActive(chip) ? 'active' : ''}`}
                onClick={() => toggleDomainChip(chip)}
                style={domainChipActive(chip) ? { borderColor: chip.color, color: chip.color } : undefined}
                title={`Toggle ${chip.label} overlay`}
              >
                <chip.icon size={13} />
                {chip.label}
              </button>
            ))}
            <button
              className={`domain-chip ${showCooling ? 'active' : ''}`}
              onClick={() => toggleCooling(!showCooling)}
              style={showCooling ? { borderColor: '#16a34a', color: '#16a34a' } : undefined}
              title="Cooling potential — model-derived intervention map"
            >
              <Sprout size={13} /> Cooling
            </button>
          </div>
        </div>
      </div>

      {/* ================= MODE NAV ================= */}
      <div className="view-tabs mode-nav">
        <div className="view-tabs-inner" role="tablist" aria-label="Workspace modes">
          {MODES.map((tab) => (
            <button
              key={tab.key}
              role="tab"
              aria-selected={mode === tab.key}
              className={`view-tab ${mode === tab.key ? 'active' : ''}`}
              onClick={() => setMode(tab.key)}
              title={tab.title}
            >
              <tab.icon size={14} />
              {tab.label}
            </button>
          ))}
        </div>
      </div>

      {/* ================= WORKSPACE ================= */}
      <div className="dashboard dashboard-3d">
        {/* LEFT — mode content (map stays the product in the centre) */}
        <aside className="side-panel left-panel">
          <div className="side-panel-header">
            {mode === 'city' && <Activity size={14} color="var(--primary-sky)" />}
            {mode === 'environment' && <Mountain size={14} color="var(--primary-sky)" />}
            {mode === 'decision' && <Sprout size={14} color="#16a34a" />}
            {mode === 'insights' && <Flame size={14} color="#dc2626" />}
            <strong>{leftPanelTitle}</strong>
          </div>
          <div className="side-panel-body" style={{ padding: 0, gap: 0 }}>
            {mode === 'city' && (
              <EnvironmentPanel
                key="city"
                monitoring={monitoring}
                liveWeather={liveWeather}
                airQuality={airQuality}
                modelInfo={modelInfo}
                health={health}
              />
            )}
            {mode === 'environment' && (
              <EnvironmentPanel
                key="environment"
                monitoring={monitoring}
                liveWeather={liveWeather}
                airQuality={airQuality}
                health={health}
              />
            )}
            {mode === 'decision' && (
              <div className="decision-panel">
                <div className="decision-panel-head">
                  <Layers size={14} color="var(--primary-sky)" />
                  <strong>Decision Centre</strong>
                  <span className="decision-panel-sub">Select a location on the map</span>
                </div>
                <div className="decision-panel-body">
                  {selectedLocation && (
                    <div className="decision-panel-content">
                      <LocationIntelligencePanel
                        location={selectedLocation}
                        liveWeather={liveWeather}
                        onClose={() => setSelectedLocation(null)}
                      />
                    </div>
                  )}
                  {!selectedLocation && (
                    <div className="decision-panel-welcome">
                      <strong>Select a location</strong> on the map or search for a place to begin.
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
        </aside>

        {/* CENTER — the 3D map is ALWAYS the product */}
        <main className="center-panel">
          <div className="map-stage">
            <DigitalTwinMap3D {...mapProps} />

            {/* Floating toggles */}
            <div className="map-overlay-stack">
              <div className="map-overlay-tabs">
                <button
                  className={`overlay-tab ${showAi ? 'active' : ''}`}
                  onClick={() => setShowAi((v) => !v)}
                  title="Nemotron AI assistant (uses real backend data)"
                >
                  <Bot size={13} /> Ask AI
                </button>
                <button
                  className={`overlay-tab ${showTimeMachine ? 'active' : ''}`}
                  onClick={() => setShowTimeMachine((v) => !v)}
                  title="Time machine — historical Landsat LST"
                >
                  <Clock size={13} /> Time
                </button>
                <button
                  className="overlay-tab"
                  onClick={() => setShowMonitoringDrawer(true)}
                  title="Dataset availability + live weather"
                >
                  <Activity size={13} /> Data
                </button>
              </div>

              <AnimatePresence>
                {showAi && (
                  <motion.div key="ov-ai" initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -8 }}>
                    <AIAssistant
                      modelInfo={modelInfo}
                      aiStatus={aiStatus}
                      selectedLocation={selectedLocation}
                      areaOsm={selectedLocation?.stats}
                      environmentSummary={environmentSummary}
                      liveWeather={liveWeather}
                      onStatusChange={setAiStatus}
                    />
                  </motion.div>
                )}
                {showTimeMachine && (
                  <motion.div key="ov-tm" initial={{ opacity: 0, y: -8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -8 }}>
                    <TimeMachine
                      liveWeather={liveWeather}
                      onDateSelect={(date) => {
                        setHistoricalDate(date);
                        // Fetch the grid data for the selected date
                        import('./services/temporalClient').then(({ fetchTemporalGrid }) => {
                          fetchTemporalGrid(date)
                            .then((gridData) => {
                              setHistoricalLayerData(gridData);
                            })
                            .catch(() => setHistoricalLayerData(null));
                        });
                      }}
                      onClose={() => {
                        setShowTimeMachine(false);
                        setHistoricalDate(null);
                        setHistoricalLayerData(null);
                      }}
                    />
                  </motion.div>
                )}
              </AnimatePresence>
            </div>

            {/* Mode docks — slide over the right edge of the map, map stays visible */}
            {mode === 'decision' && (
              <div className="mode-dock">
                <div className="mode-dock-head">
                  <Layers size={14} color="var(--primary-sky)" />
                  <strong>Scenario Simulator</strong>
                  <span className="mode-dock-sub">CURRENT → SCENARIO → DIFFERENCE (XGBoost)</span>
                  <button className="mode-dock-close" onClick={() => setMode('city')} aria-label="Close scenario simulator">
                    <X size={14} />
                  </button>
                </div>
                <div className="mode-dock-body">
                  <BeforeAfterComparison
                    modelInfo={modelInfo}
                    onModelInfoChange={setModelInfo}
                    scenarioMode={scenarioOverlay?.mode}
                    onScenarioModeChange={handleScenarioModeChange}
                    onScenarioData={handleScenarioData}
                  />
                </div>
              </div>
            )}
            {mode === 'insights' && (
              <div className="mode-dock">
                <div className="mode-dock-head">
                  <BarChart3 size={14} color="#9333ea" />
                  <strong>Insights &amp; Analytics</strong>
                  <span className="mode-dock-sub">Real distributions · model residuals</span>
                  <button className="mode-dock-close" onClick={() => setMode('city')} aria-label="Close insights">
                    <X size={14} />
                  </button>
                </div>
                <div className="mode-dock-body">
                  <AnalyticsCharts
                    liveWeather={liveWeather}
                    availability={availability}
                    environmentSummary={environmentSummary}
                    modelInfo={modelInfo}
                    onFlyTo={handleFlyTo}
                  />
                </div>
              </div>
            )}

            {/* Selected location / environmental intelligence */}
            {selectedLocation && (
              <div className="loc-panel-wrap">
                <LocationIntelligencePanel
                  location={selectedLocation}
                  liveWeather={liveWeather}
                  onClose={() => setSelectedLocation(null)}
                />
              </div>
            )}
          </div>

          {/* Mobile floating buttons */}
          <button className="map-float-btn" style={{ left: 12, top: 12 }} onClick={() => setDrawer('layers')}>
            <Layers size={14} /> Layers
          </button>
        </main>

        {/* RIGHT — layers */}
        <aside className="side-panel right-panel">
          <div className="side-panel-header">
            <Layers size={14} color="var(--primary-sky)" />
            <strong>Layers</strong>
          </div>
          <div className="side-panel-body" style={{ padding: '10px', gap: 0 }}>
            <LayerManager
              layers={layers}
              setLayer={setLayer}
              opacities={opacities}
              setOpacity={setOpacity}
              availability={availability}
              overlayMeta={overlayMeta}
              liveWeather={liveWeather}
              onResetAll={resetAllLayers}
            />
          </div>
        </aside>
      </div>

      {/* ================= SYSTEM STATUS BAR ================= */}
      <SystemStatusBar
        status={systemStatus}
        loading={healthLoading}
        onRefresh={handleRefresh}
        onOpenPanel={() => setShowSystemStatus(true)}
        connectionState={connectionState}
        freshness={freshness}
      />

      {/* ================= DRAWERS (tablet/mobile) ================= */}
      {(drawer || showMonitoringDrawer) && (
        <div className="drawer-backdrop open" onClick={() => { setDrawer(null); setShowMonitoringDrawer(false); }} />
      )}
      {drawer === 'layers' && (
        <div className="drawer">
          <div className="drawer-head">
            <Layers size={15} color="var(--primary-sky)" />
            <strong>Layers</strong>
            <button className="drawer-close" onClick={() => setDrawer(null)} aria-label="Close layers"><X size={15} /></button>
          </div>
          <div className="drawer-body" style={{ padding: '10px' }}>
            <LayerManager
              layers={layers}
              setLayer={setLayer}
              opacities={opacities}
              setOpacity={setOpacity}
              availability={availability}
              overlayMeta={overlayMeta}
              liveWeather={liveWeather}
              onResetAll={resetAllLayers}
            />
          </div>
        </div>
      )}
      {showMonitoringDrawer && (
        <div className="drawer">
          <div className="drawer-head">
            <Activity size={15} color="var(--primary-sky)" />
            <strong>Monitoring & Data Status</strong>
            <button className="drawer-close" onClick={() => setShowMonitoringDrawer(false)} aria-label="Close monitoring"><X size={15} /></button>
          </div>
          <div className="drawer-body">
            <MonitoringPanel
              monitoring={monitoring}
              liveWeather={liveWeather}
              loading={!monitoring}
              onRefresh={handleRefresh}
              modelInfo={modelInfo}
              aiStatus={aiStatus}
            />
          </div>
        </div>
      )}
      {(drawer || showMonitoringDrawer) && (
        <div className="drawer-backdrop open" onClick={() => { setDrawer(null); setShowMonitoringDrawer(false); }} />
      )}
      {drawer === 'layers' && (
        <div className="drawer">
          <div className="drawer-head">
            <Activity size={15} color="var(--primary-sky)" />
            <strong>Monitoring &amp; Data Status</strong>
            <button className="drawer-close" onClick={() => setShowMonitoringDrawer(false)} aria-label="Close monitoring"><X size={15} /></button>
          </div>
          <div className="drawer-body">
            <MonitoringPanel
              monitoring={monitoring}
              liveWeather={liveWeather}
              loading={!monitoring}
              onRefresh={handleRefresh}
              modelInfo={modelInfo}
              aiStatus={aiStatus}
            />
          </div>
        </div>
      )}

      {/* ================= MODALS ================= */}
      {showHelp && <HelpModal onClose={() => setShowHelp(false)} />}
      {showSystemStatus && (
        <SystemStatusPanel
          onClose={() => setShowSystemStatus(false)}
          status={systemStatus}
          loading={healthLoading}
          onRefresh={handleRefresh}
        />
      )}
    </div>
  );
}

// Outer wrapper that provides the LiveDataContext
export function App() {
  return (
    <LiveDataProvider>
      <AppInner />
    </LiveDataProvider>
  );
}

export default App;
