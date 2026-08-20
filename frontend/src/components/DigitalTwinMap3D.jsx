import React, { useEffect, useMemo, useRef, useState } from 'react';
import * as maplibregl from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import {
  Building2, Layers, RotateCcw, Route, Trees, Waves,
  MapPin, Maximize, Minimize, Orbit, Home, Camera, Crosshair
} from 'lucide-react';
import { fetchBoundary, fetchLayerGeoJson, fetchCurrentHeat, fetchCurrentHeatGrid, fetchJson } from '../services/backendClient';
import { computeAreaStats, featureDisplayName } from '../services/areaStats';

const LOCAL_LAYER_BASE = '/3d-layers';
const EMPTY_COLLECTION = { type: 'FeatureCollection', features: [] };
const LAYER_FILES = {
  buildings: 'web_3d_buildings',
  roads: 'web_3d_roads',
  green: 'web_3d_green_spaces',
  natural: 'web_3d_natural_water_green',
  water: 'web_3d_water',
  trees: 'web_3d_trees'
};

const OSM_RASTER_STYLE = {
  version: 8,
  sources: {
    osm: {
      type: 'raster',
      tiles: [
        'https://a.tile.openstreetmap.org/{z}/{x}/{y}.png',
        'https://b.tile.openstreetmap.org/{z}/{x}/{y}.png',
        'https://c.tile.openstreetmap.org/{z}/{x}/{y}.png'
      ],
      tileSize: 256,
      attribution: 'OpenStreetMap contributors'
    }
  },
  layers: [
    {
      id: 'osm-base',
      type: 'raster',
      source: 'osm',
      paint: {
        'raster-saturation': -0.45,
        'raster-brightness-min': 0.12,
        'raster-brightness-max': 0.92
      }
    }
  ]
};

// Thematic layer key -> overlay asset key (overlays.json).
const OVERLAY_BY_KEY = {
  ndvi: 'ndvi', green_cover: 'green_cover', vegetation_density: 'vegetation_density',
  land_cover: 'landcover',
  lst: 'lst', predicted_lst: 'predicted_lst', heat_class: 'heat_classes',
  aqi: 'aqi', pm25: 'pm25', pm10: 'pm10', no2: 'no2', so2: 'so2', o3: 'o3', co: 'co',
  elevation: 'elevation', slope: 'slope', aspect: 'aspect', hillshade: 'hillshade'
};

const COOLING_CLASS_COLORS = {
  'VERY HIGH': '#1a9641', HIGH: '#66bd63', MODERATE: '#fee08b', LOW: '#d73027'
};

function boundsFromGeoJson(geojson) {
  const coords = [];
  const walk = (value) => {
    if (Array.isArray(value) && value.length >= 2 && typeof value[0] === 'number' && typeof value[1] === 'number') {
      coords.push(value);
      return;
    }
    if (Array.isArray(value)) value.forEach(walk);
  };
  geojson?.features?.forEach((feature) => walk(feature.geometry?.coordinates));
  if (!coords.length) return null;
  const lngs = coords.map((c) => c[0]);
  const lats = coords.map((c) => c[1]);
  return [[Math.min(...lngs), Math.min(...lats)], [Math.max(...lngs), Math.max(...lats)]];
}

async function fetchLocalGeoJson(fileName) {
  const response = await fetch(`${LOCAL_LAYER_BASE}/${fileName}.geojson`);
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
  return response.json();
}

async function loadGeoJson(layerName, localFile) {
  try {
    const data = await fetchLayerGeoJson(layerName);
    return { data, source: 'Backend layer catalogue' };
  } catch {
    try {
      const data = await fetchLocalGeoJson(localFile);
      return { data, source: 'Local real OSM web layer fallback' };
    } catch (err) {
      return { data: EMPTY_COLLECTION, source: `Unavailable: ${err.message}` };
    }
  }
}

async function loadBoundary() {
  try {
    const data = await fetchBoundary();
    return { data, source: 'Backend boundary API' };
  } catch {
    const data = await fetchLocalGeoJson('boundary');
    return { data, source: 'Local repository boundary fallback' };
  }
}

function addOrUpdateSource(map, id, data) {
  const source = map.getSource(id);
  if (source) {
    source.setData(data);
    return;
  }
  map.addSource(id, { type: 'geojson', data });
}

function addLayerIfMissing(map, layer, beforeId) {
  if (!map.getLayer(layer.id)) {
    if (beforeId && !map.getLayer(beforeId)) {
      map.addLayer(layer);
    } else if (beforeId && map.getLayer(beforeId)) {
      map.addLayer(layer, beforeId);
    } else {
      map.addLayer(layer);
    }
  }
}

function removeLayerIfPresent(map, id) {
  if (map.getLayer(id)) map.removeLayer(id);
}

function removeSourceIfPresent(map, id) {
  if (map.getSource(id)) map.removeSource(id);
}

function setVisibility(map, ids, visible) {
  ids.forEach((id) => {
    if (map.getLayer(id)) map.setLayoutProperty(id, 'visibility', visible ? 'visible' : 'none');
  });
}

function setThermalMapMode(mode) {
  setMapMode(mode);
  const map = mapRef.current;
  if (!map || !mapReady) return;

  // Only change visibility - never remove sources to prevent race conditions
  const modes = {
    current: {
      'current-prediction-layer': 'visible',
      'scenario-prediction-layer': 'none',
      'scenario-delta-layer': 'none'
    },
    scenario: {
      'current-prediction-layer': 'none',
      'scenario-prediction-layer': 'visible',
      'scenario-delta-layer': 'none'
    },
    difference: {
      'current-prediction-layer': 'none',
      'scenario-prediction-layer': 'none',
      'scenario-delta-layer': 'visible'
    }
  };

  const visibility = modes[mode];
  if (map.getLayer('current-prediction-layer')) {
    map.setLayoutProperty('current-prediction-layer', 'visibility', visibility.current);
  }
  if (map.getLayer('scenario-prediction-layer')) {
    map.setLayoutProperty('scenario-prediction-layer', 'visibility', visibility.scenario);
  }
  if (map.getLayer('scenario-delta-layer')) {
    map.setLayoutProperty('scenario-delta-layer', 'visibility', visibility.difference);
  }
}

function firstProperty(properties, keys, fallback = 'Unnamed feature') {
  for (const key of keys) {
    const value = properties?.[key];
    if (value !== undefined && value !== null && String(value).trim()) return value;
  }
  return fallback;
}

// ------------------------------------------------------------------ #
// Scenario overlay helpers (unchanged from the existing implementation)
// ------------------------------------------------------------------ #
function fieldDomain(features, key) {
  let min = Infinity;
  let max = -Infinity;
  for (const feature of features) {
    const value = feature.properties?.[key];
    if (value === null || value === undefined || Number.isNaN(value)) continue;
    if (value < min) min = value;
    if (value > max) max = value;
  }
  return { min, max };
}

function buildScenarioStyle(geojson, mode) {
  const features = geojson?.features || [];
  if (mode === 'DIFFERENCE') {
    const { min, max } = fieldDomain(features, 'delta_lst');
    return {
      expression: ['interpolate', ['linear'], ['get', 'delta_lst'], min, '#2166ac', 0, '#f7f7f7', max, '#b2182b'],
      domain: { min, max, delta: true }
    };
  }
  const key = mode === 'CURRENT' ? 'baseline_lst' : 'scenario_lst';
  const { min, max } = fieldDomain(features, key);
  const mid = (min + max) / 2;
  return {
    expression: ['interpolate', ['linear'], ['get', key], min, '#2c7bb6', mid, '#fdae61', max, '#d7191c'],
    domain: { min, max, delta: false }
  };
}

function scenarioGradient(domain) {
  if (domain.delta) {
    const span = domain.max - domain.min || 1;
    const zeroPct = ((-domain.min) / span) * 100;
    return {
      css: `linear-gradient(to right, #2166ac 0%, #f7f7f7 ${zeroPct}%, #b2182b 100%)`,
      zeroPct
    };
  }
  return { css: 'linear-gradient(to right, #2c7bb6 0%, #fdae61 50%, #d7191c 100%)', zeroPct: null };
}

const fmtCellValue = (value, signed = false) => {
  if (value === null || value === undefined || Number.isNaN(value)) return '—';
  const rounded = Number(value).toFixed(2);
  return signed && value > 0 ? `+${rounded}` : rounded;
};

// ------------------------------------------------------------------ #
export function DigitalTwinMap3D({
  layers = {},
  opacities = {},
  availability = {},
  overlayMeta = {},
  scenarioOverlay = null,
  currentPrediction = null,
  historicalLayerData = null,
  historicalDate = null,
  onScenarioModeChange = () => {},
  onSelectLocation = () => {},
  hotspots = null,
  showHotspots = false,
  coolingGeoJson = null,
  showCooling = false,
  routeData = null,
  flyTo = null,
  selectedPoint = null,
  theme = 'light',
  liveWeather = null,
  onMapClick = null
}) {
  const containerRef = useRef(null);
  const mapRef = useRef(null);
  const popupRef = useRef(null);
  const boundaryRef = useRef(null);
  const collectionsRef = useRef({});
  const scenarioRef = useRef(scenarioOverlay);
  scenarioRef.current = scenarioOverlay;
  const historicalRef = useRef(historicalLayerData);
  historicalRef.current = historicalLayerData;
  const cellHandlersBoundRef = useRef(false);
  const lastScenarioDataRef = useRef(null);
  const markerRef = useRef(null);
  const currentHeatGridRef = useRef(null);
  const [mapReady, setMapReady] = useState(false);
  const [mapMode, setMapMode] = useState('current');
  const [counts, setCounts] = useState({ buildings: 0, roads: 0, green: 0, water: 0, trees: 0 });
  const [status, setStatus] = useState({ loading: true, message: 'Loading 3D city layers', source: '' });
  const [cursorLngLat, setCursorLngLat] = useState(null);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [orbiting, setOrbiting] = useState(false);
  const orbitRef = useRef(null);

  // ------------------------------------------------------------------ #
  // Map bootstrap
  // ------------------------------------------------------------------ #
  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;

    const map = new maplibregl.Map({
      container: containerRef.current,
      style: OSM_RASTER_STYLE,
      center: [85.8275, 20.2636],
      zoom: 11.3,
      pitch: 58,
      bearing: -22,
      maxPitch: 75,
      antialias: true
    });

    map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), 'top-right');
    map.addControl(new maplibregl.ScaleControl({ maxWidth: 140, unit: 'metric' }), 'bottom-left');

    // Keep the canvas sized to its container: the map can mount while the
    // layout is still settling (zero-height container -> MapLibre's 300 px
    // default), and the panel resizes on tablet/mobile breakpoints.
    const containerEl = containerRef.current;
    let resizeObserver = null;
    if (typeof ResizeObserver !== 'undefined') {
      resizeObserver = new ResizeObserver(() => {
        if (mapRef.current) mapRef.current.resize();
      });
      resizeObserver.observe(containerEl);
    }
    const onWindowResize = () => { if (mapRef.current) mapRef.current.resize(); };
    window.addEventListener('resize', onWindowResize);

    map.on('mousemove', (e) => setCursorLngLat([Number(e.lngLat.lng.toFixed(5)), Number(e.lngLat.lat.toFixed(5))]));
    map.on('mouseout', () => setCursorLngLat(null));

    map.on('load', async () => {
      setMapReady(true);
      setStatus({ loading: true, message: 'Loading boundary and real OSM layers', source: '' });

      try {
        const [boundaryResult, buildingsResult, roadsResult, greenResult, naturalResult, waterResult, treesResult] = await Promise.all([
          loadBoundary(),
          loadGeoJson(LAYER_FILES.buildings, LAYER_FILES.buildings),
          loadGeoJson(LAYER_FILES.roads, LAYER_FILES.roads),
          loadGeoJson(LAYER_FILES.green, LAYER_FILES.green),
          loadGeoJson(LAYER_FILES.natural, LAYER_FILES.natural),
          loadGeoJson(LAYER_FILES.water, LAYER_FILES.water),
          loadGeoJson(LAYER_FILES.trees, LAYER_FILES.trees)
        ]);

        boundaryRef.current = boundaryResult.data;
        collectionsRef.current = {
          buildings: buildingsResult.data,
          roads: roadsResult.data,
          green: greenResult.data,
          natural: naturalResult.data,
          water: waterResult.data
        };

        // Terrain source (real DEM tiles, terrarium encoding) — added once.
        addOrUpdateSource(map, 'dem-tiles', {
          type: 'raster-dem',
          tiles: ['/terrain/{z}/{x}/{y}.png'],
          tileSize: 256,
          encoding: 'terrarium',
          maxzoom: 14,
          attribution: 'Copernicus DEM GLO-30 / SRTM'
        });

        const addGeo = (id, data) => {
          addOrUpdateSource(map, id, data);
        };
        addGeo('boundary', boundaryResult.data);
        addGeo('buildings', buildingsResult.data);
        addGeo('roads', roadsResult.data);
        addGeo('green-spaces', greenResult.data);
        addGeo('natural-water-green', naturalResult.data);
        addGeo('water', waterResult.data);
        addGeo('trees', treesResult.data);

        // Boundary
        addLayerIfMissing(map, {
          id: 'boundary-fill', type: 'fill', source: 'boundary',
          paint: { 'fill-color': theme === 'dark' ? '#0f172a' : '#dbeafe', 'fill-opacity': 0.1 }
        });
        addLayerIfMissing(map, {
          id: 'boundary-line', type: 'line', source: 'boundary',
          paint: { 'line-color': '#38bdf8', 'line-width': 2.4, 'line-opacity': 0.9 }
        });

        // Water + green (under overlays so heat can sit on the ground)
        addLayerIfMissing(map, {
          id: 'water-fill', type: 'fill', source: 'water',
          paint: { 'fill-color': '#0ea5e9', 'fill-opacity': 0.62 }
        });
        addLayerIfMissing(map, {
          id: 'natural-water-fill', type: 'fill', source: 'natural-water-green',
          filter: ['in', ['get', 'natural'], ['literal', ['water', 'wetland']]],
          paint: { 'fill-color': '#38bdf8', 'fill-opacity': 0.45 }
        });
        addLayerIfMissing(map, {
          id: 'green-fill', type: 'fill', source: 'green-spaces',
          paint: { 'fill-color': '#22c55e', 'fill-opacity': 0.45 }
        });
        addLayerIfMissing(map, {
          id: 'natural-green-fill', type: 'fill', source: 'natural-water-green',
          filter: ['in', ['get', 'natural'], ['literal', ['wood', 'tree', 'tree_row', 'scrub', 'grassland']]],
          paint: { 'fill-color': '#16a34a', 'fill-opacity': 0.4 }
        });

        // Roads
        addLayerIfMissing(map, {
          id: 'roads-major', type: 'line', source: 'roads',
          filter: ['in', ['get', 'highway'], ['literal', ['motorway', 'trunk', 'primary', 'secondary', 'tertiary']]],
          paint: { 'line-color': '#f97316', 'line-width': ['interpolate', ['linear'], ['zoom'], 10, 1.5, 15, 5], 'line-opacity': 0.92 }
        });
        addLayerIfMissing(map, {
          id: 'roads-local', type: 'line', source: 'roads',
          filter: ['!', ['in', ['get', 'highway'], ['literal', ['motorway', 'trunk', 'primary', 'secondary', 'tertiary']]]],
          paint: { 'line-color': '#e2e8f0', 'line-width': ['interpolate', ['linear'], ['zoom'], 10, 0.4, 15, 2], 'line-opacity': 0.6 }
        });

        // Buildings (3D extrusion, real heights with honest default fallback)
        // Height hierarchy: measured > GIS > OSM levels × 3.2m > estimated 6m
        // Buildings with estimated heights are colored differently (purple)
        addLayerIfMissing(map, {
          id: 'building-extrusion', type: 'fill-extrusion', source: 'buildings',
          paint: {
            'fill-extrusion-color': [
              'case',
              ['==', ['get', 'height_source'], 'visual_default_not_measured'], ['literal', '#7c3aed'],
              ['==', ['get', 'height_source'], 'OSM_LEVELS_ESTIMATED'], ['literal', '#8b5cf6'],
              ['literal', '#2563eb']
            ],
            'fill-extrusion-height': [
              'case',
              ['>', ['to-number', ['get', 'render_height_m'], 0], 0], ['to-number', ['get', 'render_height_m']],
              ['>', ['to-number', ['get', 'height_m'], 0], 0], ['to-number', ['get', 'height_m']],
              ['>', ['to-number', ['get', 'levels'], 0], 0], ['*', ['to-number', ['get', 'levels']], 3.2],
              6
            ],
            'fill-extrusion-base': 0,
            'fill-extrusion-opacity': 0.74,
            'fill-extrusion-vertical-gradient': true
          }
        });

        // Trees — real OSM records, clustered at low zoom, individual at high zoom.
        addLayerIfMissing(map, {
          id: 'trees-cluster',
          type: 'circle',
          source: 'trees',
          filter: ['has', 'point_count'],
          paint: {
            'circle-color': '#15803d',
            'circle-radius': ['step', ['get', 'point_count'], 14, 10, 18, 30, 22],
            'circle-opacity': 0.85,
            'circle-stroke-width': 2,
            'circle-stroke-color': '#dcfce7'
          }
        });
        addLayerIfMissing(map, {
          id: 'trees-cluster-count',
          type: 'symbol',
          source: 'trees',
          filter: ['has', 'point_count'],
          layout: {
            'text-field': ['get', 'point_count_abbreviated'],
            'text-size': 11,
            'text-font': ['Open Sans Bold', 'Arial Unicode MS Bold']
          },
          paint: { 'text-color': '#ffffff' }
        });
        addLayerIfMissing(map, {
          id: 'trees-point',
          type: 'circle',
          source: 'trees',
          filter: ['!', ['has', 'point_count']],
          paint: {
            'circle-color': '#16a34a',
            'circle-radius': ['interpolate', ['linear'], ['zoom'], 12, 3, 17, 6],
            'circle-opacity': 0.9,
            'circle-stroke-width': 1,
            'circle-stroke-color': '#f0fdf4'
          },
          minzoom: 12
        });

        // Interactive hover popups
        const interactiveIds = ['building-extrusion', 'roads-major', 'roads-local', 'green-fill', 'natural-green-fill', 'water-fill', 'natural-water-fill', 'trees-point', 'trees-cluster'];
        interactiveIds.forEach((id) => {
          map.on('mousemove', id, (e) => showHoverPopup(map, popupRef, e, liveWeather));
          map.on('mouseenter', id, () => { map.getCanvas().style.cursor = 'pointer'; });
          map.on('mouseleave', id, () => {
            map.getCanvas().style.cursor = '';
            if (popupRef.current) popupRef.current.remove();
          });
        });

        // Click anywhere -> nearest real data (scenario cell clicks handled separately)
        map.on('click', (e) => {
          let cellHits = [];
          if (map.getLayer('scenario-cells-fill')) {
            cellHits = map.queryRenderedFeatures(e.point, { layers: ['scenario-cells-fill'] });
          }
          if (cellHits.length) return;
          const feature = map.queryRenderedFeatures(e.point)[0] || null;
          const name = feature ? featureDisplayName(feature) : 'Selected point';
          const stats = computeAreaStats(collectionsRef.current, e.lngLat.lng, e.lngLat.lat, 150);
          onSelectLocation({ name, lat: e.lngLat.lat, lng: e.lngLat.lng, stats });
          onMapClick?.(e.lngLat);
        });

        const bounds = boundsFromGeoJson(boundaryResult.data);
        if (bounds) {
          map.fitBounds(bounds, { padding: 50, pitch: 58, bearing: -22, duration: 1000 });
        }

        setCounts({
          buildings: buildingsResult.data.features?.length || 0,
          roads: roadsResult.data.features?.length || 0,
          green: (greenResult.data.features?.length || 0) + (naturalResult.data.features?.length || 0),
          water: waterResult.data.features?.length || 0,
          trees: treesResult.data.features?.length || 0
        });

        setStatus({
          loading: false,
          message: 'Full Bhubaneswar 3D city — real OSM geometry + real DEM terrain',
          source: `Boundary: ${boundaryResult.source}. Buildings: ${buildingsResult.source}. Roads: ${roadsResult.source}.`
        });
      } catch (error) {
        setStatus({ loading: false, message: '3D map loaded, but city layers are unavailable', source: error.message });
      }
    });

    mapRef.current = map;
    return () => {
      if (resizeObserver) resizeObserver.disconnect();
      window.removeEventListener('resize', onWindowResize);
      if (popupRef.current) popupRef.current.remove();
      map.remove();
      mapRef.current = null;
      popupRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [theme]);

  // ------------------------------------------------------------------ #
  // City layer visibility
  // ------------------------------------------------------------------ #
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady) return;
    setVisibility(map, ['building-extrusion'], layers.CITY?.buildings !== false);
    setVisibility(map, ['roads-major', 'roads-local'], layers.CITY?.roads !== false);
    setVisibility(map, ['green-fill', 'natural-green-fill'], layers.CITY?.green !== false);
    setVisibility(map, ['water-fill', 'natural-water-fill'], layers.CITY?.water !== false);
    setVisibility(map, ['trees-point', 'trees-cluster', 'trees-cluster-count'], layers.CITY?.trees !== false);
    setVisibility(map, ['boundary-fill', 'boundary-line'], layers.CITY?.boundary !== false);
  }, [mapReady, layers]);

  // ------------------------------------------------------------------ #
  // Thermal map mode synchronization (CURRENT / SCENARIO / DIFFERENCE)
  // ------------------------------------------------------------------ #
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady) return;

    const applyMode = () => {
      const modes = {
        current: { current: 'visible', scenario: 'none', difference: 'none' },
        scenario: { current: 'none', scenario: 'visible', difference: 'none' },
        difference: { current: 'none', scenario: 'none', difference: 'visible' }
      };
      const vis = modes[mapMode];
      if (map.getLayer('current-prediction-layer')) {
        map.setLayoutProperty('current-prediction-layer', 'visibility', vis.current);
      }
      if (map.getLayer('scenario-prediction-layer')) {
        map.setLayoutProperty('scenario-prediction-layer', 'visibility', vis.scenario);
      }
      if (map.getLayer('scenario-delta-layer')) {
        map.setLayoutProperty('scenario-delta-layer', 'visibility', vis.difference);
      }
    };

    applyMode();
  }, [mapMode, mapReady]);

  // ------------------------------------------------------------------ #
  // Terrain 3D toggle (with health check)
  // ------------------------------------------------------------------ #
  const [terrainStatus, setTerrainStatus] = useState('unchecked'); // unchecked | loading | available | unavailable | error
  
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady) return;
    const enabled = layers.TERRAIN?.terrain_3d === true && availability.terrain_3d !== false;
    if (enabled) {
      setTerrainStatus('loading');
      try {
        map.setTerrain({ source: 'dem-tiles', exaggeration: 1 });
        // Check if terrain actually loaded by waiting for terrain event
        const onTerrainLoaded = () => {
          setTerrainStatus('available');
          map.off('terrain', onTerrainLoaded);
        };
        const onTerrainError = (e) => {
          console.warn('Terrain loading failed:', e.error?.message || e);
          setTerrainStatus('unavailable');
          map.off('error', onTerrainError);
        };
        map.on('terrain', onTerrainLoaded);
        map.on('error', onTerrainError);
        // Fallback timeout
        setTimeout(() => {
          if (terrainStatus === 'loading') setTerrainStatus('available');
        }, 5000);
      } catch (e) {
        console.warn('setTerrain failed:', e);
        setTerrainStatus('error');
      }
    } else {
      map.setTerrain(null);
      setTerrainStatus('unchecked');
    }
  }, [mapReady, layers, availability]);

  // ------------------------------------------------------------------ #
  // Raster overlays (image sources from the real GeoTIFF renderings)
  // ------------------------------------------------------------------ #
  const overlayEntries = useMemo(
    () => Object.entries(OVERLAY_BY_KEY).filter(([, asset]) => overlayMeta[asset]),
    [overlayMeta]
  );

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady) return;
    overlayEntries.forEach(([key, asset]) => {
      const meta = overlayMeta[asset];
      const group = Object.keys(layers).find((g) => layers[g] && layers[g][key] === true);
      const visible = Boolean(group) && availability[key] !== false;
      const layerId = `overlay-${key}`;
      const sourceId = `overlay-src-${key}`;
      if (visible) {
        if (!map.getSource(sourceId)) {
          map.addSource(sourceId, {
            type: 'image',
            url: meta.url,
            coordinates: meta.bounds_wgs84
          });
        }
        if (!map.getLayer(layerId)) {
          addLayerIfMissing(map, {
            id: layerId,
            type: 'raster',
            source: sourceId,
            paint: {
              'raster-opacity': (opacities[key] ?? 80) / 100,
              'raster-fade-duration': 0
            },
            layout: { visibility: 'visible' }
          }, 'roads-major'); // below roads so the 3D city stays visible
        } else {
          map.setPaintProperty(layerId, 'raster-opacity', (opacities[key] ?? 80) / 100);
          map.setLayoutProperty(layerId, 'visibility', 'visible');
        }
      } else {
        removeLayerIfPresent(map, layerId);
        removeSourceIfPresent(map, sourceId);
      }
    });
  }, [mapReady, overlayEntries, overlayMeta, layers, availability, opacities]);

  // ------------------------------------------------------------------ #
  // Current predicted LST heat grid overlay
  // Loads the real 53,802-cell prediction grid from /api/prediction/heat/current/grid
  // and merges with authoritative grid geometry from Predicted_LST.geojson.
  // ------------------------------------------------------------------ #
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady) return;

    const predLstVisible = layers.HEAT?.predicted_lst === true;
    if (!predLstVisible) {
      removeLayerIfPresent(map, 'current-heat-fill');
      removeSourceIfPresent(map, 'current-heat-grid');
      currentHeatGridRef.current = null;
      return;
    }

    // Don't reload if we already have the data
    if (currentHeatGridRef.current) {
      if (map.getLayer('current-heat-fill')) {
        map.setLayoutProperty('current-heat-fill', 'visibility', 'visible');
      }
      return;
    }

// Fetch current predictions AND authoritative grid geometry in parallel
    // Using a Promise chain to avoid parser issues with function declarations in useEffect
    Promise.all([
      fetchCurrentHeatGrid(),
      fetchJson('/data/layers/predicted-lst')
    ])
      .then(([predResult, gridGeojson]) => {
        if (!predResult?.success || !predResult?.predictions?.length) return;
        if (!gridGeojson?.features?.length) {
          console.warn('Heat grid: No grid geometry available from Predicted_LST.geojson');
          return;
        }

        const predictions = predResult.predictions;
        const predMap = {};
        for (const p of predictions) {
          predMap[String(p.grid_id)] = p.predicted_lst;
        }

        // Merge current predictions with authoritative grid geometry
        const features = [];
        const gridFeatures = gridGeojson.features;
        for (let i = 0; i < gridFeatures.length; i++) {
          const f = gridFeatures[i];
          const gid = String(f.properties?.grid_id ?? f.properties?.Grid_ID);
          features.push({
            type: 'Feature',
            properties: {
              grid_id: gid,
              predicted_lst: predMap[gid] ?? f.properties?.Predicted_LST ?? null,
              source: 'XGBoost (current)',
              generated_at: predResult.generated_at,
            },
            geometry: f.geometry,
          });
        }

        const fc = { type: 'FeatureCollection', features };
        addOrUpdateSource(map, 'current-heat-grid', fc);

        if (!map.getLayer('current-heat-fill')) {
          // Calculate LST domain for color ramp
          let minLst = Infinity, maxLst = -Infinity;
          for (const f of features) {
            const v = f.properties.predicted_lst;
            if (v != null && !Number.isNaN(v)) {
              if (v < minLst) minLst = v;
              if (v > maxLst) maxLst = v;
            }
          }
          if (minLst === Infinity) return;
          const mid = (minLst + maxLst) / 2;
          addLayerIfMissing(map, {
            id: 'current-heat-fill',
            type: 'fill',
            source: 'current-heat-grid',
            paint: {
              'fill-color': ['interpolate', ['linear'], ['get', 'predicted_lst'],
                minLst, '#2c7bb6', mid, '#fdae61', maxLst, '#d7191c'],
              'fill-opacity': 0.55,
            },
            layout: { visibility: 'visible' },
          }, 'roads-major');

          // Add click handler
          map.on('click', 'current-heat-fill', (e) => {
            const p = e.features?.[0]?.properties || {};
            if (popupRef.current) popupRef.current.remove();
            popupRef.current = new maplibregl.Popup({ closeButton: false, offset: 12, maxWidth: '240px' })
              .setLngLat(e.lngLat)
              .setHTML(`<div style="font-family:Inter,sans-serif;font-size:12px;line-height:1.55">
                <strong style="font-size:12.5px">Grid ${p.grid_id}</strong>
                <div style="color:#94a3b8;font-size:11px">CURRENT PREDICTED LST</div>
                <div style="margin-top:6px;display:grid;grid-template-columns:auto auto;gap:2px 12px">
                  <span style="color:#94a3b8">Predicted LST</span>
                  <span style="font-weight:700;color:#dc2626">${p.predicted_lst != null ? Number(p.predicted_lst).toFixed(1) + ' °C' : '—'}</span>
                  <span style="color:#94a3b8">Source</span>
                  <span style="font-weight:600">XGBoost (current data)</span>
                </div>
              </div>`)
              .addTo(map);
          });
          map.on('mousemove', 'current-heat-fill', () => { map.getCanvas().style.cursor = 'pointer'; });
          map.on('mouseleave', 'current-heat-fill', () => {
            map.getCanvas().style.cursor = '';
            if (popupRef.current) popupRef.current.remove();
          });
        }
        currentHeatGridRef.current = fc;
      })
      .catch((err) => {
        console.warn('Heat grid: Failed to load current predictions or grid geometry', err);
      });
  }, [mapReady, layers.HEAT?.predicted_lst]);

  // REMOVED: fetchScenarioCellsForGeometry - no longer needed
  // REMOVED: renderHeatAsPoints fallback - we now use authoritative Predicted_LST.geojson geometry

  // ------------------------------------------------------------------ #
  // Scenario cell overlay (CURRENT / SCENARIO / DIFFERENCE)
  // ------------------------------------------------------------------ #
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady) return;

    const overlay = scenarioOverlay;
    const hasData = overlay?.geojson?.features?.length > 0;

    if (!hasData) {
      // Hide scenario layers when no data - never remove sources
      if (map.getLayer('scenario-prediction-layer')) {
        map.setLayoutProperty('scenario-prediction-layer', 'visibility', 'none');
      }
      if (map.getLayer('scenario-delta-layer')) {
        map.setLayoutProperty('scenario-delta-layer', 'visibility', 'none');
      }
      return;
    }

    const data = overlay.geojson;
    const mode = overlay.mode || 'DIFFERENCE';

    // === Build scenario prediction source ===
    // The geojson features have properties: grid_id, baseline_lst, scenario_lst, delta_lst
    if (!map.getSource('scenario-prediction-source')) {
      map.addSource('scenario-prediction-source', { type: 'geojson', data });
    } else {
      map.getSource('scenario-prediction-source').setData(data);
    }

    // === Build scenario delta source ===
    // Ensure all features have delta_lst (compute if not present)
    const deltaFeatures = data.features.map((f) => ({
      type: 'Feature',
      geometry: f.geometry,
      properties: {
        grid_id: f.properties.grid_id,
        baseline_lst: f.properties.baseline_lst,
        scenario_lst: f.properties.scenario_lst,
        delta_lst: f.properties.delta_lst !== undefined
          ? f.properties.delta_lst
          : f.properties.scenario_lst != null && f.properties.baseline_lst != null
            ? f.properties.scenario_lst - f.properties.baseline_lst
            : null
      }
    }));
    const deltaFC = { type: 'FeatureCollection', features: deltaFeatures };

    if (!map.getSource('scenario-delta-source')) {
      map.addSource('scenario-delta-source', deltaFC);
    } else {
      map.getSource('scenario-delta-source').setData(deltaFC);
    }

    // === Scenario prediction layer ===
    // Color based on scenario_lst
    const scenarioColorExpr = [
      'interpolate', ['linear'], ['get', 'scenario_lst'],
      0, '#2c7bb6',
      25, '#fdae61',
      50, '#d7191c'
    ];

    if (!map.getLayer('scenario-prediction-layer')) {
      map.addLayer({
        id: 'scenario-prediction-layer',
        type: 'fill',
        source: 'scenario-prediction-source',
        paint: { 'fill-color': scenarioColorExpr },
        layout: { visibility: mapMode === 'scenario' ? 'visible' : 'none' }
      }, 'roads-major');
    } else {
      map.setPaintProperty('scenario-prediction-layer', 'fill-color', scenarioColorExpr);
      map.setLayoutProperty('scenario-prediction-layer', 'visibility', mapMode === 'scenario' ? 'visible' : 'none');
    }

    // === Scenario delta layer ===
    // Color based on delta_lst (negative = cooling, positive = warming)
    const deltaColorExpr = [
      'interpolate', ['linear'], ['get', 'delta_lst'],
      -5, '#2166ac',
      0, '#f7f7f7',
      5, '#b2182b'
    ];

    if (!map.getLayer('scenario-delta-layer')) {
      map.addLayer({
        id: 'scenario-delta-layer',
        type: 'fill',
        source: 'scenario-delta-source',
        paint: { 'fill-color': deltaColorExpr },
        layout: { visibility: mapMode === 'difference' ? 'visible' : 'none' }
      }, 'roads-major');
    } else {
      map.setPaintProperty('scenario-delta-layer', 'fill-color', deltaColorExpr);
      map.setLayoutProperty('scenario-delta-layer', 'visibility', mapMode === 'difference' ? 'visible' : 'none');
    }
  }, [mapReady, scenarioOverlay, mapMode]);

  // ------------------------------------------------------------------ #
  // Hotspots layer
  // ------------------------------------------------------------------ #
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady) return;
    const visible = showHotspots && hotspots?.length > 0;
    const sourceId = 'hotspots-src';
    if (visible) {
      const fc = {
        type: 'FeatureCollection',
        features: hotspots.map((h, i) => ({
          type: 'Feature',
          properties: { rank: i + 1, lst: h.predicted_lst, grid_id: h.grid_id },
          geometry: { type: 'Point', coordinates: [h.longitude, h.latitude] }
        }))
      };
      if (!map.getSource(sourceId)) {
        map.addSource(sourceId, { type: 'geojson', data: fc });
      } else {
        map.getSource(sourceId).setData(fc);
      }
      if (!map.getLayer('hotspots-layer')) {
        map.addLayer({
          id: 'hotspots-layer', type: 'circle', source: sourceId,
          paint: {
            'circle-color': '#dc2626',
            'circle-radius': ['interpolate', ['linear'], ['zoom'], 10, 6, 16, 13],
            'circle-opacity': 0.85,
            'circle-stroke-width': 1.5,
            'circle-stroke-color': '#ffffff'
          }
        });
        map.on('click', 'hotspots-layer', (e) => {
          const p = e.features[0].properties;
          onSelectLocation({ name: `Hotspot #${p.rank} — Grid ${p.grid_id}`, lat: e.lngLat.lat, lng: e.lngLat.lng });
        });
        map.on('mousemove', 'hotspots-layer', (e) => {
          const p = e.features[0].properties;
          map.getCanvas().style.cursor = 'pointer';
          if (popupRef.current) popupRef.current.remove();
          popupRef.current = new maplibregl.Popup({ closeButton: false, offset: 10, maxWidth: '200px' })
            .setLngLat(e.lngLat)
            .setHTML(`<div style="font-family:Inter,sans-serif;font-size:12px"><strong>#${p.rank} hotspot</strong><br/>Grid ${p.grid_id} · ${Number(p.lst).toFixed(1)} °C predicted LST</div>`)
            .addTo(map);
        });
        map.on('mouseleave', 'hotspots-layer', () => {
          map.getCanvas().style.cursor = '';
          if (popupRef.current) popupRef.current.remove();
        });
      }
    } else {
      removeLayerIfPresent(map, 'hotspots-layer');
      removeSourceIfPresent(map, sourceId);
    }
  }, [mapReady, showHotspots, hotspots, onSelectLocation]);

  // ------------------------------------------------------------------ #
  // Cooling potential layer
  // ------------------------------------------------------------------ #
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady) return;
    const visible = showCooling && coolingGeoJson?.features?.length > 0;
    if (visible) {
      if (!map.getSource('cooling-src')) {
        map.addSource('cooling-src', { type: 'geojson', data: coolingGeoJson });
      } else {
        map.getSource('cooling-src').setData(coolingGeoJson);
      }
      if (!map.getLayer('cooling-layer')) {
        addLayerIfMissing(map, {
          id: 'cooling-layer', type: 'fill', source: 'cooling-src',
          paint: {
            'fill-color': ['match', ['get', 'cooling_class'],
              'VERY HIGH', COOLING_CLASS_COLORS['VERY HIGH'],
              'HIGH', COOLING_CLASS_COLORS.HIGH,
              'MODERATE', COOLING_CLASS_COLORS.MODERATE,
              'LOW', COOLING_CLASS_COLORS.LOW,
              '#94a3b8'],
            'fill-opacity': 0.5
          }
        }, 'roads-major');
        map.on('mousemove', 'cooling-layer', (e) => {
          const p = e.features[0].properties;
          map.getCanvas().style.cursor = 'pointer';
          if (popupRef.current) popupRef.current.remove();
          popupRef.current = new maplibregl.Popup({ closeButton: false, offset: 10, maxWidth: '220px' })
            .setLngLat(e.lngLat)
            .setHTML(`<div style="font-family:Inter,sans-serif;font-size:12px">
              <strong>${p.cooling_class} cooling potential</strong><br/>
              Zone ${p.grid_id} · up to −${Math.abs(Number(p.max_cooling_c)).toFixed(1)} °C (${p.best_scenario})</div>`)
            .addTo(map);
        });
        map.on('mouseleave', 'cooling-layer', () => {
          map.getCanvas().style.cursor = '';
          if (popupRef.current) popupRef.current.remove();
        });
      }
    } else {
      removeLayerIfPresent(map, 'cooling-layer');
      removeSourceIfPresent(map, 'cooling-src');
    }
  }, [mapReady, showCooling, coolingGeoJson]);

  // ------------------------------------------------------------------ #
  // Historical thermal layer (Landsat LST from Time Machine)
  // ------------------------------------------------------------------ #
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady) return;

    const data = historicalLayerData;
    const hasData = data?.features?.features?.length > 0;

    if (!hasData) {
      removeLayerIfPresent(map, 'historical-thermal-fill');
      removeSourceIfPresent(map, 'historical-thermal');
      return;
    }

    // Add or update the historical thermal source
    if (!map.getSource('historical-thermal')) {
      map.addSource('historical-thermal', { type: 'geojson', data: data.features });
    } else {
      map.getSource('historical-thermal').setData(data.features);
    }

    // Calculate the LST domain for color mapping
    const features = data.features.features || [];
    let minLst = Infinity;
    let maxLst = -Infinity;
    for (const f of features) {
      const lst = f.properties?.lst;
      if (lst !== null && lst !== undefined && !Number.isNaN(lst)) {
        if (lst < minLst) minLst = lst;
        if (lst > maxLst) maxLst = lst;
      }
    }

    if (minLst === Infinity || maxLst === -Infinity) return;

    const mid = (minLst + maxLst) / 2;
    const expression = [
      'interpolate', ['linear'], ['get', 'lst'],
      minLst, '#2c7bb6',
      mid, '#fdae61',
      maxLst, '#d7191c'
    ];

    // Add or update the historical thermal layer
    if (map.getLayer('historical-thermal-fill')) {
      map.setPaintProperty('historical-thermal-fill', 'fill-color', expression);
      map.setPaintProperty('historical-thermal-fill', 'fill-opacity', 0.55);
      map.setLayoutProperty('historical-thermal-fill', 'visibility', 'visible');
    } else {
      addLayerIfMissing(map, {
        id: 'historical-thermal-fill',
        type: 'fill',
        source: 'historical-thermal',
        paint: {
          'fill-color': expression,
          'fill-opacity': 0.55
        }
      }, 'roads-major'); // below roads so the 3D city stays visible
    }

    // Add click handler for historical cells
    const onHistoricalClick = (e) => {
      const props = e.features?.[0]?.properties || {};
      const lst = props.lst;
      const cellId = props.cell_id;
      const valid = props.valid;

      if (popupRef.current) popupRef.current.remove();
      popupRef.current = new maplibregl.Popup({ closeButton: false, offset: 12, maxWidth: '220px' })
        .setLngLat(e.lngLat)
        .setHTML(
          `<div style="font-family:Inter,sans-serif;font-size:12px;line-height:1.55">
            <strong style="font-size:12.5px">Cell ${cellId}</strong>
            <div style="color:#94a3b8;font-size:11px">HISTORICAL OBSERVED LST</div>
            <div style="margin-top:6px;display:grid;grid-template-columns:auto auto;gap:2px 12px">
              <span style="color:#94a3b8">LST</span>
              <span style="font-weight:700;color:#dc2626">${valid && lst != null ? Number(lst).toFixed(1) + ' °C' : 'No data'}</span>
              <span style="color:#94a3b8">Source</span>
              <span style="font-weight:600">Landsat</span>
              <span style="color:#94a3b8">Date</span>
              <span style="font-weight:600">${historicalRef.current?.date || '—'}</span>
            </div>
            <div style="margin-top:6px;color:#b45309;font-size:10px;font-weight:600">
              Satellite-observed LST — not model prediction
            </div>
          </div>`
        )
        .addTo(map);
    };

    if (!cellHandlersBoundRef.current) {
      map.on('click', 'historical-thermal-fill', onHistoricalClick);
      map.on('mousemove', 'historical-thermal-fill', () => {
        map.getCanvas().style.cursor = 'pointer';
      });
      map.on('mouseleave', 'historical-thermal-fill', () => {
        map.getCanvas().style.cursor = '';
      });
    }
  }, [mapReady, historicalLayerData, historicalDate]);

  // ------------------------------------------------------------------ #
  // Route layers (fastest + lower-heat)
  // ------------------------------------------------------------------ #
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady) return;
    const f = routeData?.fastest;
    const c = routeData?.coolest;
    const addRoute = (id, geometry, color) => {
      const sourceId = `route-${id}`;
      if (!geometry) {
        removeLayerIfPresent(map, `route-line-${id}`);
        removeSourceIfPresent(map, sourceId);
        return;
      }
      if (!map.getSource(sourceId)) {
        map.addSource(sourceId, { type: 'geojson', data: { type: 'FeatureCollection', features: [{ type: 'Feature', properties: {}, geometry }] } });
      } else {
        map.getSource(sourceId).setData({ type: 'FeatureCollection', features: [{ type: 'Feature', properties: {}, geometry }] });
      }
      if (!map.getLayer(`route-line-${id}`)) {
        map.addLayer({
          id: `route-line-${id}`, type: 'line', source: sourceId,
          layout: { 'line-cap': 'round', 'line-join': 'round' },
          paint: { 'line-color': color, 'line-width': 4.5, 'line-opacity': 0.95, 'line-dasharray': [1, 0.6] }
        });
      }
    };
    addRoute('fastest', f?.geometry, '#0284c7');
    addRoute('coolest', c?.geometry, '#16a34a');
    if (f?.geometry && c?.geometry) {
      const bounds = new maplibregl.LngLatBounds();
      [...f.geometry.coordinates, ...c.geometry.coordinates].forEach(([lng, lat]) => bounds.extend([lng, lat]));
      map.fitBounds(bounds, { padding: 80, pitch: 55, duration: 900 });
    }
  }, [mapReady, routeData]);

  // ------------------------------------------------------------------ #
  // Fly-to (search results, hotspots, interventions)
  // ------------------------------------------------------------------ #
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady || !flyTo) return;
    map.flyTo({ center: [flyTo.lng, flyTo.lat], zoom: flyTo.zoom ?? 14, pitch: 58, duration: 1400 });
  }, [mapReady, flyTo]);

  // ------------------------------------------------------------------ #
  // Selected-point marker
  // ------------------------------------------------------------------ #
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady) return;
    if (markerRef.current) {
      markerRef.current.remove();
      markerRef.current = null;
    }
    if (selectedPoint) {
      const el = document.createElement('div');
      el.className = 'map-selected-marker';
      el.innerHTML = '<span class="marker-pin"></span>';
      markerRef.current = new maplibregl.Marker({ element: el })
        .setLngLat([selectedPoint.lng, selectedPoint.lat])
        .addTo(map);
    }
  }, [mapReady, selectedPoint]);

  // ------------------------------------------------------------------ #
  // Orbit control
  // ------------------------------------------------------------------ #
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady) return;
    if (orbiting) {
      let raf;
      const spin = () => {
        map.easeTo({ bearing: map.getBearing() + 0.35, duration: 40 });
        orbitRef.current = raf = requestAnimationFrame(spin);
      };
      raf = requestAnimationFrame(spin);
      return () => cancelAnimationFrame(raf);
    }
    return undefined;
  }, [mapReady, orbiting]);

  // ------------------------------------------------------------------ #
  // City-layer opacity
  // ------------------------------------------------------------------ #
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady) return;
    const apply = (ids, paint, pct) => {
      ids.forEach((id) => { if (map.getLayer(id)) map.setPaintProperty(id, paint, (pct ?? 80) / 100); });
    };
    apply(['building-extrusion'], 'fill-extrusion-opacity', opacities.buildings);
    apply(['roads-major', 'roads-local'], 'line-opacity', opacities.roads);
    apply(['green-fill', 'natural-green-fill'], 'fill-opacity', opacities.green);
    apply(['water-fill', 'natural-water-fill'], 'fill-opacity', opacities.water);
    apply(['trees-point', 'trees-cluster'], 'circle-opacity', opacities.trees);
  }, [mapReady, opacities]);

  // ------------------------------------------------------------------ #
  // Camera presets
  // ------------------------------------------------------------------ #
  const resetCamera = (preset = 'city') => {
    const map = mapRef.current;
    if (!map) return;
    if (preset === 'city') {
      const bounds = boundsFromGeoJson(boundaryRef.current);
      if (bounds) map.fitBounds(bounds, { padding: 50, pitch: 58, bearing: -22, duration: 1100 });
      return;
    }
    const target = selectedPoint || { lat: 20.2636, lng: 85.8275 };
    const zoom = preset === 'street' ? 16 : 14;
    const pitch = preset === 'street' ? 68 : 58;
    map.flyTo({ center: [target.lng, target.lat], zoom, pitch, duration: 1100 });
  };

  const toggleFullscreen = () => {
    const el = containerRef.current?.closest('.map-stage') || containerRef.current;
    if (!el) return;
    if (document.fullscreenElement) {
      document.exitFullscreen().catch(() => {});
      setIsFullscreen(false);
    } else {
      el.requestFullscreen?.().then(() => setIsFullscreen(true)).catch(() => setIsFullscreen(false));
    }
  };

  const overlayHasData = scenarioOverlay?.geojson?.features?.length > 0;
  const overlayStyle = overlayHasData ? buildScenarioStyle(scenarioOverlay.geojson, scenarioOverlay.mode || 'DIFFERENCE') : null;
  const overlayLegend = overlayStyle ? scenarioGradient(overlayStyle.domain) : null;

  return (
    <div className="maplibre-shell">
      <div ref={containerRef} className="maplibre-container" />

      {/* Top-left: compact title */}
      <div className="maplibre-top-card">
        <div className="maplibre-kicker"><Layers size={13} /> Bhubaneswar 3D Digital Twin</div>
        <strong>OSM / GIS-based city</strong>
        <span>{status.message}</span>
      </div>

      {/* Layer counts */}
      <div className="maplibre-stats-card" aria-label="Loaded 3D city layer counts">
        <span><Building2 size={13} /> {counts.buildings.toLocaleString()} buildings</span>
        <span><Route size={13} /> {counts.roads.toLocaleString()} roads</span>
        <span><Trees size={13} /> {counts.trees.toLocaleString()} OSM trees</span>
        <span><Waves size={13} /> {counts.water.toLocaleString()} water</span>
      </div>

      {/* Camera presets */}
      <div className="maplibre-camera" role="toolbar" aria-label="Camera controls">
        <button type="button" onClick={() => resetCamera('city')} title="City view — full Bhubaneswar" className="cam-btn active">
          <Home size={15} /> City
        </button>
        <button type="button" onClick={() => resetCamera('neighborhood')} title="Neighborhood view" className="cam-btn">
          <Camera size={15} /> District
        </button>
        <button type="button" onClick={() => resetCamera('street')} title="Street view" className="cam-btn">
          <Building2 size={15} /> Street
        </button>
        <button
          type="button"
          className={`cam-btn ${orbiting ? 'orbiting' : ''}`}
          onClick={() => setOrbiting((v) => !v)}
          title={orbiting ? 'Stop orbit' : 'Orbit around the city'}
        >
          <Orbit size={15} /> {orbiting ? 'Stop' : 'Orbit'}
        </button>
        <button type="button" onClick={() => resetCamera('city')} title="Reset camera" className="cam-btn">
          <RotateCcw size={15} /> Reset
        </button>
        <button
          type="button"
          className="cam-btn"
          onClick={toggleFullscreen}
          title={isFullscreen ? 'Exit fullscreen' : 'Fullscreen map'}
        >
          {isFullscreen ? <Minimize size={15} /> : <Maximize size={15} />}
          {isFullscreen ? 'Exit' : 'Full'}
        </button>
      </div>

      {/* Scenario overlay legend */}
      {overlayHasData && overlayLegend && (
        <div className="maplibre-scenario-card" aria-label="Cell-level scenario overlay">
          <div className="maplibre-kicker" style={{ marginBottom: '5px' }}><MapPin size={13} /> Scenario cells</div>
          <strong title={scenarioOverlay.scenario} style={{ fontSize: '0.8rem', display: 'block', marginBottom: '7px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {scenarioOverlay.scenario}
          </strong>
          <div style={{ display: 'flex', gap: '4px', marginBottom: '9px' }}>
            {['CURRENT', 'SCENARIO', 'DIFFERENCE'].map((mode) => (
              <button key={mode} type="button" className={`overlay-tab ${scenarioOverlay.mode === mode ? 'active' : ''}`}
                onClick={() => onScenarioModeChange(mode)} style={{ fontSize: '0.62rem', padding: '3px 7px' }}>
                {mode}
              </button>
            ))}
          </div>
          <div className="scenario-gradient" style={{ background: overlayLegend.css }} />
          <div className="scenario-legend-labels">
            <span>{fmtCellValue(overlayStyle.domain.min)}</span>
            <span>{fmtCellValue(overlayStyle.domain.max)}</span>
          </div>
          <div className="scenario-end-labels">
            <span style={{ color: overlayStyle.domain.delta ? '#2166ac' : 'inherit' }}>{overlayStyle.domain.delta ? 'Cooler' : '°C'}</span>
            <span style={{ color: overlayStyle.domain.delta ? '#b2182b' : 'inherit' }}>{overlayStyle.domain.delta ? 'Warmer' : '°C'}</span>
          </div>
        </div>
      )}

      {/* Current prediction provenance box */}
      {currentPrediction && (
        <div className="maplibre-source-card" style={{
          position: 'absolute',
          bottom: '80px',
          left: '20px',
          zIndex: 998,
          padding: '8px 12px',
          borderRadius: '8px',
          background: 'var(--bg-subtle)',
          border: '1px solid var(--border-light)',
          fontSize: '0.62rem',
          color: 'var(--text-secondary)'
        }}>
          <span style={{ fontWeight: 700, color: 'var(--text-main)', marginRight: '4px' }}>
            MODELLED LST
          </span>
          <span>{currentPrediction.model_version ? 'V' + currentPrediction.model_version : 'V1'} · {currentPrediction.features_used} features</span>
          <span style={{ fontSize: '0.54rem', color: 'var(--text-muted)' }}>{currentPrediction.pipeline_status}</span>
        </div>
      )}

      {/* Live weather context — NOT used by V1 model */}
      {currentPrediction && (
        <div className="maplibre-source-card" style={{
          position: 'absolute',
          bottom: '56px',
          left: '20px',
          zIndex: 998,
          padding: '8px 12px',
          borderRadius: '8px',
          background: 'var(--bg-subtle)',
          border: '1px solid var(--border-light)',
          fontSize: '0.62rem',
          color: 'var(--text-secondary)'
        }}>
          <span style={{ fontWeight: 700, color: 'var(--text-main)', marginRight: '4px' }}>
            LIVE WEATHER CONTEXT
          </span>
          <span style={{ fontSize: '0.56rem', color: 'var(--text-muted)' }}>
            — Not used by V1 model · OpenWeather air temperature displayed separately
          </span>
        </div>
      )}

      {/* Coordinates chip */}
      {cursorLngLat && (
        <div className="map-coords-chip">{cursorLngLat[0].toFixed(5)}, {cursorLngLat[1].toFixed(5)}</div>
      )}

      {/* Data source footer */}
      <div className="maplibre-source-card">
        <Crosshair size={13} />
        <span>{status.loading ? 'Loading…' : `${status.source} · Click anywhere for location intelligence`}</span>
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ #
// Hover + cell popups (unchanged behaviour)
// ------------------------------------------------------------------ #
function showHoverPopup(map, popupRef, event, liveWeather) {
  const feature = event.features?.[0];
  const props = feature?.properties || {};
  const title = firstProperty(props, ['name', 'building', 'highway', 'leisure', 'natural', 'water', 'kind']);
  const details = [
    props.highway ? `Road class: ${props.highway}` : null,
    props.building ? `Building: ${props.building}` : null,
    props.render_height_m ? `Height: ${Number(props.render_height_m).toFixed(1)} m` : null,
    props.leisure ? `Green: ${props.leisure}` : null,
    props.natural ? `Natural: ${props.natural}` : null,
    props.water ? `Water: ${props.water}` : null,
    props.kind === 'tree' ? 'OSM tree (real record)' : null
  ].filter(Boolean);
  const tempLine = liveWeather?.temperature != null
    ? `<span style="color:#dc2626;font-weight:700">Live air: ${liveWeather.temperature} °C</span>`
    : '';
  if (popupRef.current) popupRef.current.remove();
  popupRef.current = new maplibregl.Popup({ closeButton: false, offset: 12, maxWidth: '260px' })
    .setLngLat(event.lngLat)
    .setHTML(
      `<div style="font-family:Inter,sans-serif;font-size:12px;line-height:1.5">
        <strong style="font-size:12.5px">${title}</strong>
        ${details.map((line) => `<div style="color:#475569">${line}</div>`).join('')}
        <div style="color:#94a3b8">${Number(event.lngLat.lat).toFixed(5)}° N, ${Number(event.lngLat.lng).toFixed(5)}° E</div>
        ${tempLine}
        <div style="margin-top:4px;color:#0284c7;font-weight:700">Click for details →</div>
      </div>`
    )
    .addTo(map);
}

function showCellPopup(map, popupRef, event, scenarioRef) {
  const props = event.features?.[0]?.properties || {};
  const scenarioName = scenarioRef.current?.scenario || '';
  const delta = props.delta_lst;
  const deltaColor = delta < 0 ? '#10b981' : delta > 0 ? '#dc2626' : '#94a3b8';
  if (popupRef.current) popupRef.current.remove();
  popupRef.current = new maplibregl.Popup({ closeButton: false, offset: 12, maxWidth: '240px' })
    .setLngLat(event.lngLat)
    .setHTML(
      `<div style="font-family:Inter,sans-serif;font-size:12px;line-height:1.55">
        <strong style="font-size:12.5px">Grid ${props.grid_id}</strong>
        ${scenarioName ? `<div style="color:#94a3b8;font-size:11px">${scenarioName}</div>` : ''}
        <div style="display:grid;grid-template-columns:auto auto;gap:2px 12px;margin-top:6px">
          <span style="color:#94a3b8">Baseline LST</span><span style="font-weight:700;color:#dc2626">${fmtCellValue(props.baseline_lst)} °C</span>
          <span style="color:#94a3b8">Scenario LST</span><span style="font-weight:700;color:#16a34a">${fmtCellValue(props.scenario_lst)} °C</span>
          <span style="color:#94a3b8">Δ LST</span><span style="font-weight:700;color:${deltaColor}">${fmtCellValue(delta, true)} °C</span>
        </div>
      </div>`
    )
    .addTo(map);
}

export default DigitalTwinMap3D;
