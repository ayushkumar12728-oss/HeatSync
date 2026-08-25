import React from 'react';
import { MapContainer, TileLayer, Polyline, Marker, Popup } from 'react-leaflet';
import L from 'leaflet';
import { ShieldCheck, Flame, Layers } from 'lucide-react';

// Custom Map Markers
const createLiquidIcon = (color, label, glowColor) => {
  return L.divIcon({
    className: 'custom-liquid-marker',
    html: `
      <div style="
        background: ${color};
        width: 24px;
        height: 24px;
        border-radius: 50%;
        border: 2px solid white;
        box-shadow: 0 0 18px ${glowColor || color}, inset 0 1px 2px rgba(255,255,255,0.7);
        display: flex;
        align-items: center;
        justify-content: center;
        color: white;
        font-weight: 800;
        font-size: 11px;
        font-family: sans-serif;
      ">
        ${label}
      </div>
    `,
    iconSize: [24, 24],
    iconAnchor: [12, 12],
  });
};

const startIcon = createLiquidIcon('#34d399', 'A', '#10b981');
const endIcon = createLiquidIcon('#38bdf8', 'B', '#0284c7');

export default function RouteMap({ origin, destination, directRoute, coolRoute }) {
  const defaultCenter = [20.2700, 85.8150];

  // Convert GeoJSON [lng, lat] to Leaflet [lat, lng]
  const parsePolyline = (routeObj) => {
    if (!routeObj?.geometry?.coordinates) return [];
    return routeObj.geometry.coordinates.map(coord => [coord[1], coord[0]]);
  };

  const directPositions = parsePolyline(directRoute);
  const coolPositions = parsePolyline(coolRoute);

  return (
    <div className="relative rounded-3xl overflow-hidden liquid-card border border-emerald-500/25 shadow-[0_18px_45px_rgba(0,0,0,0.75)]">
      
      {/* Top Glass Header Bar in Deep Navy & Mint */}
      <div className="flex flex-wrap items-center justify-between gap-3 px-5 py-3.5 bg-[#03091e]/90 backdrop-blur-xl border-b border-emerald-500/20 z-20 relative">
        <div className="flex items-center gap-2">
          <Layers className="w-4 h-4 text-emerald-400 drop-shadow-[0_0_8px_rgba(52,211,153,0.7)]" />
          <span className="text-xs font-extrabold text-white tracking-wide uppercase">
            Bhubaneswar Thermal Path Simulator
          </span>
        </div>

        {/* Legend */}
        <div className="flex items-center gap-4 text-xs font-bold">
          <div className="flex items-center gap-1.5 text-rose-400">
            <span className="w-3.5 h-1.5 rounded-full bg-rose-500 shadow-[0_0_8px_#f43f5e]"></span>
            <span>Direct (High Heat)</span>
          </div>
          <div className="flex items-center gap-1.5 text-emerald-400">
            <span className="w-3.5 h-1.5 rounded-full bg-emerald-400 shadow-[0_0_10px_#34d399]"></span>
            <span>Cool Corridor (Shaded)</span>
          </div>
        </div>
      </div>

      {/* Map Container */}
      <div className="h-[460px] w-full relative z-10">
        <MapContainer
          center={origin ? [origin.lat, origin.lng] : defaultCenter}
          zoom={13}
          scrollWheelZoom={true}
          className="h-full w-full"
        >
          {/* Dark Matter CartoDB Basemap */}
          <TileLayer
            attribution='&copy; <a href="https://carto.com/">CARTO</a>'
            url="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
            maxZoom={19}
          />

          {/* Direct Route (Warm Rose/Coral Dash) */}
          {directPositions.length > 0 && (
            <Polyline
              positions={directPositions}
              pathOptions={{
                color: '#f43f5e',
                weight: 5,
                opacity: 0.85,
                dashArray: '8, 6',
                lineCap: 'round',
                lineJoin: 'round',
              }}
            />
          )}

          {/* Cool Corridor Route (Radiant Mint Green Glow) */}
          {coolPositions.length > 0 && (
            <Polyline
              positions={coolPositions}
              pathOptions={{
                color: '#34d399',
                weight: 6,
                opacity: 0.95,
                lineCap: 'round',
                lineJoin: 'round',
              }}
            />
          )}

          {/* Origin Marker */}
          {origin && (
            <Marker position={[origin.lat, origin.lng]} icon={startIcon}>
              <Popup>
                <div className="p-1 text-slate-100 font-sans">
                  <div className="text-xs font-bold text-emerald-400">ORIGIN (A)</div>
                  <div className="text-sm font-semibold">{origin.name}</div>
                </div>
              </Popup>
            </Marker>
          )}

          {/* Destination Marker */}
          {destination && (
            <Marker position={[destination.lat, destination.lng]} icon={endIcon}>
              <Popup>
                <div className="p-1 text-slate-100 font-sans">
                  <div className="text-xs font-bold text-sky-400">DESTINATION (B)</div>
                  <div className="text-sm font-semibold">{destination.name}</div>
                </div>
              </Popup>
            </Marker>
          )}
        </MapContainer>
      </div>

      {/* Floating Bottom Status Pill */}
      <div className="absolute bottom-4 left-4 z-20 px-3.5 py-1.5 rounded-xl bg-[#020718]/85 backdrop-blur-xl border border-emerald-500/30 text-[11px] font-bold text-emerald-300 flex items-center gap-2 shadow-xl">
        <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse shadow-[0_0_6px_#34d399]"></span>
        <span>A* Dynamic Lower-Thermal routing active</span>
      </div>

    </div>
  );
}
