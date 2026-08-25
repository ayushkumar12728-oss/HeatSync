import React from 'react';
import { Layers, Eye, EyeOff } from 'lucide-react';

export default function LayerControl({
  activeLayers,
  toggleLayer,
  opacity,
  setOpacity
}) {
  const layers = [
    { id: 'lst', label: 'Land Surface Temp (LST)', color: '#f43f5e', desc: '100m predicted thermal grid' },
    { id: 'ndvi', label: 'NDVI Vegetation Index', color: '#34d399', desc: 'Sentinel-2 canopy density' },
    { id: 'hotspots', label: 'UHI Hotspot Clusters', color: '#fbbf24', desc: 'Top 50 thermal anomalies' },
    { id: 'osm_buildings', label: 'OSM Building Footprints', color: '#60a5fa', desc: '3D urban built environment' },
    { id: 'osm_water', label: 'Water Bodies & Greenbelts', color: '#2dd4bf', desc: 'Lakes, canals & parks' },
    { id: 'cooling_potential', label: 'Intervention Potential', color: '#4ade80', desc: 'Modelled cooling zones' },
    { id: 'boundary', label: 'City Study Boundary', color: '#94a3b8', desc: 'Official BDA polygon boundary' },
  ];

  return (
    <div className="p-5 rounded-3xl liquid-glass space-y-4">
      <div className="flex items-center justify-between">
        <h4 className="text-xs font-extrabold text-white uppercase tracking-wider flex items-center gap-2">
          <Layers className="w-4 h-4 text-emerald-400 drop-shadow-[0_0_8px_rgba(52,211,153,0.7)]" />
          <span>GIS Microclimate Layers</span>
        </h4>
        <span className="text-[10px] text-emerald-300 font-mono font-bold px-2 py-0.5 rounded-full bg-emerald-950/90 border border-emerald-500/40">
          {Object.values(activeLayers).filter(Boolean).length} Active
        </span>
      </div>

      <div className="space-y-1.5 max-h-[300px] overflow-y-auto pr-1">
        {layers.map((layer) => {
          const isActive = activeLayers[layer.id];
          return (
            <button
              key={layer.id}
              onClick={() => toggleLayer(layer.id)}
              className={`w-full flex items-center justify-between p-2.5 rounded-2xl text-left text-xs font-medium transition-all duration-200 cursor-pointer ${
                isActive
                  ? 'bg-gradient-to-r from-emerald-950/50 via-[#071330] to-blue-950/40 border border-emerald-400/40 text-white shadow-[0_0_15px_rgba(52,211,153,0.15)]'
                  : 'bg-[#03091e]/60 border border-white/[0.04] text-slate-400 hover:text-slate-200 hover:bg-emerald-950/20'
              }`}
            >
              <div className="flex items-center gap-2.5">
                <span
                  className="w-2.5 h-2.5 rounded-full shrink-0 shadow-sm"
                  style={{ backgroundColor: layer.color }}
                />
                <div>
                  <div className="font-bold text-slate-200">{layer.label}</div>
                  <div className="text-[10px] text-slate-400">{layer.desc}</div>
                </div>
              </div>
              {isActive ? (
                <Eye className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
              ) : (
                <EyeOff className="w-3.5 h-3.5 text-slate-600 shrink-0" />
              )}
            </button>
          );
        })}
      </div>

      {/* Layer Opacity Slider */}
      <div className="pt-2 border-t border-emerald-500/15 space-y-1.5">
        <div className="flex items-center justify-between text-xs text-slate-300 font-medium">
          <span>Layer Thermal Opacity</span>
          <span className="font-mono text-emerald-400 font-extrabold">{Math.round(opacity * 100)}%</span>
        </div>
        <input
          type="range"
          min="0.2"
          max="1.0"
          step="0.05"
          value={opacity}
          onChange={(e) => setOpacity(parseFloat(e.target.value))}
          className="w-full accent-emerald-400 bg-white/[0.1] rounded-lg h-1.5 cursor-pointer"
        />
      </div>
    </div>
  );
}
