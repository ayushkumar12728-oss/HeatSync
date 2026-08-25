import React from 'react';
import { TrendingDown, Trees, Leaf, CheckCircle2, ShieldCheck, ThermometerSnowflake } from 'lucide-react';

export default function DeltaVisualizer({ data }) {
  const {
    baselineLST = 38.4,
    simulatedLST = 35.8,
    deltaLST = -2.6,
    pctCooler = 88.4,
    treesAdded = 14200,
    co2OffsetTons = 312.5,
    scenarioName = "Tree Canopy Expansion (+25%)"
  } = data || {};

  return (
    <div className="p-6 rounded-3xl liquid-glass space-y-6">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <span className="text-[10px] uppercase font-extrabold tracking-wider text-emerald-400 font-mono">
            Active Intervention Simulation
          </span>
          <h3 className="text-lg font-extrabold text-white">
            {scenarioName}
          </h3>
        </div>
        <div className="flex items-center gap-2 px-3.5 py-1.5 rounded-2xl bg-emerald-950/90 border border-emerald-400/50 text-emerald-300 text-xs font-extrabold shadow-[0_0_16px_rgba(52,211,153,0.3)]">
          <ShieldCheck className="w-4 h-4 text-emerald-400" />
          <span>{pctCooler}% Grid Cells Cooled</span>
        </div>
      </div>

      {/* Before / After Thermal Relief Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        
        {/* Baseline LST */}
        <div className="p-4 rounded-2xl liquid-card border-l-4 border-l-rose-500 space-y-1">
          <span className="text-xs text-slate-300 font-semibold">Baseline Mean LST</span>
          <div className="text-2xl font-extrabold text-rose-400 tracking-tight drop-shadow">
            {baselineLST.toFixed(1)} °C
          </div>
          <div className="text-[10px] text-slate-400">Current Urban Heat</div>
        </div>

        {/* Simulated LST */}
        <div className="p-4 rounded-2xl liquid-card border-l-4 border-l-emerald-400 space-y-1">
          <span className="text-xs text-slate-300 font-semibold">Simulated Post-Mitigation</span>
          <div className="text-2xl font-extrabold text-emerald-300 tracking-tight drop-shadow-[0_0_10px_rgba(52,211,153,0.3)]">
            {simulatedLST.toFixed(1)} °C
          </div>
          <div className="text-[10px] text-emerald-400/90 font-medium">Target Microclimate</div>
        </div>

        {/* Thermal Relief Delta */}
        <div className="p-4 rounded-2xl liquid-card border-l-4 border-l-teal-400 space-y-1">
          <span className="text-xs text-slate-300 font-semibold">Average Surface Relief</span>
          <div className="text-2xl font-extrabold text-teal-300 tracking-tight drop-shadow">
            {deltaLST < 0 ? `${deltaLST.toFixed(2)} °C` : `+${deltaLST.toFixed(2)} °C`}
          </div>
          <div className="text-[10px] text-teal-400/90 font-medium">Mean Citywide Delta</div>
        </div>

      </div>

      {/* Environmental & Carbon Co-Benefits Bar in High-Contrast Navy & Mint */}
      <div className="p-4 rounded-2xl bg-[#040a1c]/90 border border-emerald-500/20 backdrop-blur-xl grid grid-cols-2 gap-4">
        <div className="flex items-center gap-3">
          <div className="p-2.5 rounded-xl bg-emerald-950/90 border border-emerald-500/40 text-emerald-400 shadow-[0_0_10px_rgba(52,211,153,0.2)]">
            <Trees className="w-5 h-5" />
          </div>
          <div>
            <div className="text-xs text-slate-300 font-semibold">Modeled Green Canopy Added</div>
            <div className="text-base font-extrabold text-white font-mono">
              +{treesAdded.toLocaleString()} Trees Equiv.
            </div>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <div className="p-2.5 rounded-xl bg-teal-950/90 border border-teal-500/40 text-teal-300 shadow-[0_0_10px_rgba(45,212,191,0.2)]">
            <Leaf className="w-5 h-5" />
          </div>
          <div>
            <div className="text-xs text-slate-300 font-semibold">Annual CO₂ Sequestration</div>
            <div className="text-base font-extrabold text-white font-mono">
              ~{co2OffsetTons.toFixed(1)} Tons / yr
            </div>
          </div>
        </div>
      </div>

    </div>
  );
}
