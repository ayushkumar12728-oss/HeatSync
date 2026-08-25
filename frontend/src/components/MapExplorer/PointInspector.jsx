import React from 'react';
import { MousePointerClick, Flame, Trees, Building2, Droplets, Sparkles, TrendingUp, TrendingDown, HelpCircle } from 'lucide-react';

export default function PointInspector({
  pointData,
  isLoading,
  onAskAIAboutPoint
}) {
  if (!pointData) {
    return (
      <div className="p-6 rounded-3xl liquid-glass text-center space-y-3">
        <div className="w-12 h-12 rounded-2xl bg-emerald-950/40 border border-emerald-500/25 flex items-center justify-center mx-auto text-emerald-400 shadow-[0_0_15px_rgba(52,211,153,0.2)]">
          <MousePointerClick className="w-6 h-6 animate-bounce" />
        </div>
        <h4 className="text-sm font-bold text-white">Click Any Point on the Map</h4>
        <p className="text-xs text-slate-300 max-w-xs mx-auto leading-relaxed">
          Inspect 100m grid cell surface temperature, vegetation canopy, built density, and XGBoost SHAP heat attribution.
        </p>
      </div>
    );
  }

  const { latitude, longitude, grid_id, model, environment, top_factors } = pointData;
  const lst = model?.predicted_lst ?? 37.4;
  const delta = model?.delta ?? (lst - 34.8);

  return (
    <div className="p-5 rounded-3xl liquid-glass space-y-4">
      {/* Top Header */}
      <div className="flex items-center justify-between">
        <div>
          <span className="text-[10px] uppercase tracking-wider font-extrabold text-emerald-400 font-mono">
            Grid Cell #{grid_id || 1042}
          </span>
          <div className="text-xs text-slate-300 font-mono">
            {latitude?.toFixed(4)}°N, {longitude?.toFixed(4)}°E
          </div>
        </div>

        <button
          type="button"
          onClick={() => onAskAIAboutPoint && onAskAIAboutPoint(pointData)}
          className="px-3 py-1.5 rounded-xl bg-gradient-to-r from-emerald-400 via-teal-500 to-blue-600 hover:from-emerald-300 hover:to-blue-500 text-slate-950 font-extrabold text-[11px] flex items-center gap-1.5 transition-all duration-300 hover:scale-105 shadow-[0_0_15px_rgba(52,211,153,0.3)] cursor-pointer"
        >
          <Sparkles className="w-3.5 h-3.5 text-slate-950" />
          <span>Ask AI</span>
        </button>
      </div>

      {/* Surface LST Main Gauge with Liquid Card */}
      <div className="p-4 rounded-2xl liquid-card border-l-4 border-l-rose-500 flex items-center justify-between">
        <div>
          <span className="text-xs text-slate-300 font-semibold">Model Predicted LST</span>
          <div className="text-2xl font-extrabold text-rose-400 tracking-tight drop-shadow">
            {typeof lst === 'number' ? lst.toFixed(1) : lst} °C
          </div>
        </div>
        <div className="text-right">
          <span className="text-[10px] text-slate-400">Baseline Diff</span>
          <div className="text-xs font-bold text-amber-300">
            {delta > 0 ? `+${delta.toFixed(1)}°C` : `${delta.toFixed(1)}°C`}
          </div>
        </div>
      </div>

      {/* Microclimate Environmental Variables Grid */}
      <div className="grid grid-cols-2 gap-2.5 text-xs">
        <div className="p-3 rounded-2xl bg-[#040a1c]/90 border border-emerald-500/20 space-y-1">
          <div className="flex items-center gap-1 text-emerald-300 font-semibold">
            <Trees className="w-3.5 h-3.5 text-emerald-400" />
            <span>NDVI Canopy</span>
          </div>
          <div className="font-bold text-white font-mono text-sm">
            {environment?.ndvi ?? 0.24}
          </div>
        </div>

        <div className="p-3 rounded-2xl bg-[#040a1c]/90 border border-emerald-500/20 space-y-1">
          <div className="flex items-center gap-1 text-blue-300 font-semibold">
            <Building2 className="w-3.5 h-3.5 text-blue-400" />
            <span>Built Density</span>
          </div>
          <div className="font-bold text-white font-mono text-sm">
            {environment?.building_density ?? '62'}%
          </div>
        </div>
      </div>

      {/* Why is this point hot? XGBoost SHAP Attribution */}
      <div className="space-y-2 pt-2 border-t border-emerald-500/15">
        <div className="flex items-center gap-1.5 text-xs font-extrabold text-slate-200">
          <Flame className="w-3.5 h-3.5 text-rose-400 drop-shadow-[0_0_6px_rgba(244,63,94,0.6)]" />
          <span>Why is this point hot? (SHAP Factors)</span>
        </div>

        <div className="space-y-1.5">
          {(top_factors || [
            { feature: "Built Density (NDBI)", contribution: "+2.4°C", direction: "heats" },
            { feature: "Low Tree Canopy Cover", contribution: "+1.6°C", direction: "heats" },
            { feature: "Distance to Water Bodies", contribution: "-0.8°C", direction: "cools" },
          ]).map((factor, idx) => (
            <div key={idx} className="flex items-center justify-between p-2.5 rounded-xl bg-[#030818]/90 border border-white/[0.05] text-xs">
              <span className="text-slate-200 font-medium">{factor.feature}</span>
              <span className={`font-mono font-extrabold ${factor.direction === 'cools' ? 'text-emerald-400 drop-shadow-[0_0_6px_rgba(52,211,153,0.4)]' : 'text-rose-400'}`}>
                {factor.contribution}
              </span>
            </div>
          ))}
        </div>
      </div>

    </div>
  );
}
