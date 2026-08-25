import React from 'react';
import { ShieldCheck, Flame, Clock, MapPin, Trees, Sun, Sparkles } from 'lucide-react';

export default function RouteCard({
  type = 'direct', // 'direct' or 'cool'
  durationMin = 18,
  distanceKm = 4.2,
  diffMin = 0,
  avgHeatC = 39.6,
  heatReductionC = 0,
  canopyPct = 14,
  canopyLabel = 'Low',
  uvIndex = 'Very High (9.2)',
  corridorName = 'Via Biju Patnaik Park Greenway'
}) {
  const isCool = type === 'cool';

  if (!isCool) {
    return (
      <div className="relative p-5 rounded-3xl liquid-card border-l-4 border-l-rose-500 border border-rose-500/20 shadow-[0_12px_36px_rgba(0,0,0,0.65)] flex flex-col justify-between overflow-hidden group">
        {/* Subtle Liquid Top Reflection */}
        <div className="absolute top-0 left-0 right-0 h-[1.5px] bg-gradient-to-r from-transparent via-rose-400/50 to-transparent" />
        
        {/* Top Header */}
        <div className="flex items-center justify-between gap-2 mb-3">
          <div className="flex items-center gap-2">
            <Flame className="w-4 h-4 text-rose-400 drop-shadow-[0_0_8px_rgba(244,63,94,0.7)]" />
            <h4 className="text-xs font-extrabold tracking-wider text-rose-400 uppercase drop-shadow">
              DIRECT ROUTE (STANDARD)
            </h4>
          </div>
          <span className="px-2.5 py-0.5 text-[11px] font-extrabold rounded-full bg-rose-950/90 text-rose-300 border border-rose-600/50 shadow-[0_0_12px_rgba(244,63,94,0.25)]">
            High Heat Risk
          </span>
        </div>

        {/* Big Metrics */}
        <div className="mb-4">
          <div className="flex items-baseline gap-2">
            <span className="text-3xl font-extrabold text-white tracking-tight drop-shadow-[0_2px_10px_rgba(255,255,255,0.2)]">
              {Math.round(durationMin)} mins
            </span>
            <span className="text-xs text-slate-400 font-medium">
              ({distanceKm.toFixed(1)} km)
            </span>
          </div>
        </div>

        {/* Sub-metrics */}
        <div className="space-y-2.5 text-xs border-t border-white/[0.08] pt-3.5">
          <div className="flex items-center justify-between">
            <span className="text-slate-400">Avg Heat Exposure:</span>
            <span className="font-extrabold text-rose-400 drop-shadow-[0_0_6px_rgba(244,63,94,0.5)]">
              {avgHeatC.toFixed(1)} °C
            </span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-slate-400">Canopy Shade Coverage:</span>
            <span className="font-semibold text-slate-300">{canopyPct}% ({canopyLabel})</span>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-slate-400">UV / Glare Index:</span>
            <span className="font-semibold text-rose-300">{uvIndex}</span>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="relative p-5 rounded-3xl liquid-card border-l-4 border-l-emerald-400 border border-emerald-400/35 shadow-[0_12px_40px_rgba(16,185,129,0.2)] flex flex-col justify-between overflow-hidden group">
      {/* Radiant Mint Specular Top Reflection */}
      <div className="absolute top-0 left-0 right-0 h-[1.5px] bg-gradient-to-r from-transparent via-emerald-400/70 to-transparent" />

      {/* Top Header */}
      <div className="flex items-center justify-between gap-2 mb-3">
        <div className="flex items-center gap-2">
          <ShieldCheck className="w-4 h-4 text-emerald-400 drop-shadow-[0_0_8px_rgba(52,211,153,0.8)]" />
          <h4 className="text-xs font-extrabold tracking-wider text-emerald-400 uppercase drop-shadow">
            HEAT-SAFE COOLED ROUTE
          </h4>
        </div>
        <span className="px-2.5 py-0.5 text-[11px] font-extrabold rounded-full bg-emerald-950/90 text-emerald-300 border border-emerald-400/60 shadow-[0_0_16px_rgba(52,211,153,0.35)]">
          Recommended
        </span>
      </div>

      {/* Big Metrics */}
      <div className="mb-4">
        <div className="flex items-baseline gap-2">
          <span className="text-3xl font-extrabold text-emerald-300 tracking-tight drop-shadow-[0_0_18px_rgba(52,211,153,0.45)]">
            {Math.round(durationMin)} mins
          </span>
          <span className="text-xs text-slate-300 font-medium">
            ({distanceKm.toFixed(1)} km {diffMin > 0 ? `• +${Math.round(diffMin)} min` : ''})
          </span>
        </div>
      </div>

      {/* Sub-metrics */}
      <div className="space-y-2.5 text-xs border-t border-emerald-500/15 pt-3.5">
        <div className="flex items-center justify-between">
          <span className="text-slate-300">Avg Heat Exposure:</span>
          <span className="font-extrabold text-emerald-400 drop-shadow-[0_0_8px_rgba(52,211,153,0.5)]">
            {avgHeatC.toFixed(1)} °C {heatReductionC > 0 ? `(-${heatReductionC.toFixed(1)}°C)` : ''}
          </span>
        </div>
        <div className="flex items-center justify-between">
          <span className="text-slate-300">Canopy Shade Coverage:</span>
          <span className="font-extrabold text-emerald-300">
            {canopyPct}% ({canopyLabel})
          </span>
        </div>
        <div className="flex items-center justify-between">
          <span className="text-slate-300">Corridor Route:</span>
          <span className="font-semibold text-teal-300 truncate max-w-[210px]" title={corridorName}>
            {corridorName}
          </span>
        </div>
      </div>
    </div>
  );
}
