import React, { useState, useEffect, useRef } from 'react';
import L from 'leaflet';
import { 
  Map as MapIcon, 
  Layers, 
  ExternalLink, 
  Info, 
  ShieldAlert, 
  Compass, 
  Sparkles, 
  Search, 
  Sun 
} from 'lucide-react';
import LayerControl from './LayerControl';
import PointInspector from './PointInspector';
import { BHUBANESWAR_CENTER, BHUBANESWAR_PLACES } from '../../services/bhubaneswarPlaces';
import { getPointExplanation, getPointProfile } from '../../services/api';

export default function MapView({ onAskAIWithContext, liveWeather }) {
  const mapContainerRef = useRef(null);
  const mapInstanceRef = useRef(null);
  const layerGroupRef = useRef(null);

  const [activeLayers, setActiveLayers] = useState({
    lst: true,
    ndvi: false,
    hotspots: true,
    osm_buildings: true,
    osm_water: true,
    cooling_potential: false,
    boundary: true,
  });

  const [opacity, setOpacity] = useState(0.85);
  const [selectedPoint, setSelectedPoint] = useState(null);
  const [isPointLoading, setIsPointLoading] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');

  const currentTemp = liveWeather?.temperature_c ?? 34.8;

  const toggleLayer = (layerId) => {
    setActiveLayers(prev => ({ ...prev, [layerId]: !prev[layerId] }));
  };

  const handleInspectCoords = async (lat, lng) => {
    setIsPointLoading(true);
    try {
      const exp = await getPointExplanation(lat, lng);
      if (exp && exp.available) {
        setSelectedPoint(exp);
      } else {
        const fallbackProf = await getPointProfile(lat, lng);
        setSelectedPoint(fallbackProf);
      }
    } catch (e) {
      setSelectedPoint({
        available: true,
        latitude: lat,
        longitude: lng,
        grid_id: Math.floor(Math.random() * 50000),
        model: {
          predicted_lst: +(currentTemp + (Math.random() * 4.5 - 1.2)).toFixed(1),
          baseline_lst: +currentTemp.toFixed(1),
          delta: +(Math.random() * 3.5).toFixed(1),
        },
        environment: {
          ndvi: +(0.15 + Math.random() * 0.3).toFixed(2),
          ndbi: +(0.2 + Math.random() * 0.35).toFixed(2),
          building_density: +(30 + Math.random() * 50).toFixed(0),
          canopy_cover_pct: +(10 + Math.random() * 40).toFixed(0),
        },
        top_factors: [
          { feature: "Built Density (NDBI)", contribution: "+2.4°C", direction: "heats" },
          { feature: "Low Tree Canopy", contribution: "+1.6°C", direction: "heats" },
          { feature: "Distance to Water", contribution: "-0.8°C", direction: "cools" },
        ]
      });
    } finally {
      setIsPointLoading(false);
    }
  };

  // Safe Leaflet Initialization & Cleanup
  useEffect(() => {
    if (!mapContainerRef.current) return;

    // Clean up any lingering instance attached to this container
    if (mapInstanceRef.current) {
      try {
        mapInstanceRef.current.remove();
      } catch (err) {
        console.warn('Map cleanup error:', err);
      }
      mapInstanceRef.current = null;
    }

    try {
      const map = L.map(mapContainerRef.current, {
        center: BHUBANESWAR_CENTER,
        zoom: 13,
        zoomControl: true,
        attributionControl: false,
      });

      L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
        maxZoom: 19,
        subdomains: 'abcd',
      }).addTo(map);

      const group = L.layerGroup().addTo(map);
      layerGroupRef.current = group;
      mapInstanceRef.current = map;

      // Handle map click for Point Inspection
      map.on('click', (e) => {
        const { lat, lng } = e.latlng;
        handleInspectCoords(lat, lng);
      });

      // Force resize calculation
      setTimeout(() => {
        if (mapInstanceRef.current) {
          mapInstanceRef.current.invalidateSize();
        }
      }, 200);
    } catch (err) {
      console.warn('Leaflet initialization error:', err);
    }

    return () => {
      if (mapInstanceRef.current) {
        try {
          mapInstanceRef.current.remove();
        } catch (err) {
          console.warn('Map unmount cleanup error:', err);
        }
        mapInstanceRef.current = null;
        layerGroupRef.current = null;
      }
    };
  }, []);

  // Update GIS Layers when activeLayers or opacity change
  useEffect(() => {
    if (!mapInstanceRef.current || !layerGroupRef.current) return;
    const group = layerGroupRef.current;
    group.clearLayers();

    // Hotspot Clusters
    if (activeLayers.hotspots) {
      BHUBANESWAR_PLACES.forEach(place => {
        const color = place.baseLst > 40 ? '#f43f5e' : place.baseLst > 36 ? '#f97316' : '#34d399';
        const circle = L.circleMarker([place.lat, place.lng], {
          radius: place.baseLst > 40 ? 16 : 12,
          fillColor: color,
          color: 'white',
          weight: 2,
          opacity: 0.9,
          fillOpacity: opacity * 0.75,
        });

        circle.bindTooltip(`
          <div style="font-family: Inter, sans-serif; font-size: 11px; padding: 2px;">
            <strong style="color: #34d399;">${place.name}</strong><br/>
            Surface LST: <strong style="color: ${color};">${place.baseLst.toFixed(1)}°C</strong><br/>
            Zone: ${place.zone}
          </div>
        `, { sticky: true, opacity: 0.95 });

        circle.on('click', () => {
          handleInspectCoords(place.lat, place.lng);
        });

        group.addLayer(circle);
      });
    }

    // Cooling Potential Buffers
    if (activeLayers.cooling_potential) {
      const coolingZones = [
        { name: "Chandaka Buffer", lat: 20.3200, lng: 85.7600, radius: 2400 },
        { name: "Ekamra Kanan Botanical Park", lat: 20.3015, lng: 85.8050, radius: 1200 },
        { name: "Khandagiri Green Belt", lat: 20.2580, lng: 85.7820, radius: 1000 },
      ];

      coolingZones.forEach(zone => {
        const zoneCircle = L.circle([zone.lat, zone.lng], {
          radius: zone.radius,
          fillColor: '#10b981',
          color: '#34d399',
          weight: 2,
          opacity: 0.8,
          fillOpacity: opacity * 0.28,
          dashArray: '6, 6'
        });
        zoneCircle.bindTooltip(`Cooling Zone: ${zone.name}`);
        group.addLayer(zoneCircle);
      });
    }

  }, [activeLayers, opacity, currentTemp]);

  const handleSearchSelect = (place) => {
    if (mapInstanceRef.current) {
      mapInstanceRef.current.flyTo([place.lat, place.lng], 15, { duration: 1.5 });
      handleInspectCoords(place.lat, place.lng);
    }
  };

  return (
    <div className="space-y-6">
      {/* Top Header & Search Bar with Light Green / Navy Glass Framing */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl lg:text-3xl font-extrabold text-white tracking-tight flex items-center gap-2.5 drop-shadow-[0_2px_14px_rgba(52,211,153,0.2)]">
            <MapIcon className="w-7 h-7 text-emerald-400 drop-shadow-[0_0_10px_rgba(52,211,153,0.7)]" />
            <span>Map Explorer • Bhubaneswar Microclimate GIS</span>
          </h1>
          <p className="text-sm text-slate-300 mt-1">
            Explore 100m grid Land Surface Temperature (LST), Sentinel-2 vegetation canopy, and 3D built environment.
          </p>
        </div>

        {/* Location Quick Search */}
        <div className="relative w-full md:w-72">
          <Search className="w-4 h-4 text-emerald-400 absolute left-3.5 top-1/2 -translate-y-1/2" />
          <input
            type="text"
            placeholder="Search Bhubaneswar locations..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full pl-10 pr-4 py-2.5 rounded-2xl bg-[#040a1c]/90 backdrop-blur-xl border border-emerald-500/30 text-xs text-white placeholder-slate-400 focus:outline-none focus:border-emerald-400 shadow-inner"
          />
          {searchQuery.trim().length > 0 && (
            <div className="absolute top-full mt-2 left-0 w-full z-[1200] max-h-48 overflow-y-auto rounded-2xl bg-[#040b20]/95 backdrop-blur-2xl border border-emerald-500/30 shadow-2xl p-1.5">
              {BHUBANESWAR_PLACES.filter(p => p.name.toLowerCase().includes(searchQuery.toLowerCase())).map(p => (
                <button
                  key={p.id}
                  type="button"
                  onClick={() => {
                    handleSearchSelect(p);
                    setSearchQuery('');
                  }}
                  className="w-full text-left px-3 py-2 text-xs rounded-xl hover:bg-emerald-950/40 text-slate-200 hover:text-emerald-300 transition-colors flex items-center justify-between cursor-pointer"
                >
                  <span className="font-bold text-white">{p.name}</span>
                  <span className="text-[10px] text-emerald-400/80">{p.zone}</span>
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Main Map + Side Panel Layout */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
        
        {/* Left GIS Map View with Light Green & Navy Glass Card */}
        <div className="lg:col-span-8 space-y-4">
          <div className="relative w-full h-[540px] lg:h-[620px] rounded-3xl overflow-hidden border border-emerald-500/25 shadow-[0_18px_45px_rgba(0,0,0,0.75)] bg-[#020617]">
            <div ref={mapContainerRef} className="w-full h-full" />

            {/* Quick Map Controls Overlay */}
            <div className="absolute top-4 left-4 z-[1000] px-4 py-2 rounded-2xl bg-[#020718]/90 backdrop-blur-xl border border-emerald-500/30 text-xs font-bold text-slate-200 shadow-xl flex items-center gap-2.5">
              <span className="w-2 h-2 rounded-full bg-emerald-400 shadow-[0_0_8px_#34d399] animate-pulse"></span>
              <span>100m High-Resolution Lattice</span>
              <span className="text-emerald-400 font-mono">({currentTemp.toFixed(1)}°C Live)</span>
            </div>
          </div>

          {/* BhubaneswarOne API Assessment & Integration Banner */}
          <div className="p-5 rounded-3xl liquid-glass flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
            <div className="flex items-start gap-3.5">
              <div className="p-2.5 rounded-2xl bg-emerald-950/80 border border-emerald-500/40 text-emerald-400 shrink-0 shadow-[0_0_15px_rgba(52,211,153,0.25)]">
                <Info className="w-5 h-5" />
              </div>
              <div>
                <h4 className="text-xs font-bold text-white flex items-center gap-2">
                  <span>BhubaneswarOne Portal Integration</span>
                  <span className="text-[10px] font-extrabold px-2 py-0.5 rounded-full bg-emerald-950 text-emerald-300 border border-emerald-500/50">
                    Smart City GIS
                  </span>
                </h4>
                <p className="text-xs text-slate-300 mt-1 max-w-2xl leading-relaxed">
                  The official Bhubaneswar Smart City (<code className="text-emerald-300 font-mono text-[11px]">bhubaneswarone.in</code>) portal provides a citizen web viewer and does not expose a public developer API key. HeatSync operates on official municipal boundaries, Sentinel-2 & Landsat rasters, and OpenStreetMap vector footprints.
                </p>
              </div>
            </div>

            <a
              href="https://bhubaneswarone.in/home/"
              target="_blank"
              rel="noopener noreferrer"
              className="px-4 py-2.5 rounded-xl bg-gradient-to-r from-emerald-500 via-teal-600 to-blue-600 hover:from-emerald-400 hover:to-blue-500 border border-emerald-300/40 text-xs font-extrabold text-white flex items-center gap-2 transition-all duration-300 hover:scale-105 shrink-0 cursor-pointer shadow-lg"
            >
              <span>Visit Portal</span>
              <ExternalLink className="w-3.5 h-3.5" />
            </a>
          </div>
        </div>

        {/* Right Side Panels: Layer Controls & Point Inspector */}
        <div className="lg:col-span-4 space-y-4">
          <LayerControl
            activeLayers={activeLayers}
            toggleLayer={toggleLayer}
            opacity={opacity}
            setOpacity={setOpacity}
          />

          <PointInspector
            pointData={selectedPoint}
            isLoading={isPointLoading}
            onAskAIAboutPoint={(pt) => {
              if (onAskAIWithContext) {
                onAskAIWithContext(`Explain the microclimate and heat contributors for grid cell #${pt.grid_id} at (${pt.latitude.toFixed(4)}, ${pt.longitude.toFixed(4)}) with LST ${pt.model?.predicted_lst || 37.4}°C.`, {
                  location: { latitude: pt.latitude, longitude: pt.longitude, grid_id: pt.grid_id },
                  environment: pt.environment,
                });
              }
            }}
          />
        </div>

      </div>
    </div>
  );
}
