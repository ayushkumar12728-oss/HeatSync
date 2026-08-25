import React from 'react';
import { Award, ArrowRight, Zap, Target } from 'lucide-react';

export default function PriorityMatrix() {
  const rankedInterventions = [
    { rank: 1, name: "Dense Street Trees (20% Cover)", delta: "-1.23°C", coverage: "94.8%", cost: "Low-Med", feasibility: "High", priority: "IMMEDIATE" },
    { rank: 2, name: "Cool Roof High-Albedo Coatings", delta: "-0.97°C", coverage: "86.2%", cost: "Low", feasibility: "High", priority: "HIGH" },
    { rank: 3, name: "Biju Patnaik - Ekamra Green Corridor", delta: "-1.85°C", coverage: "Corridor (12km)", cost: "Medium", feasibility: "Med-High", priority: "HIGH" },
    { rank: 4, name: "Industrial Zone Buffer (Rasulgarh)", delta: "-1.45°C", coverage: "Hotspot Cluster", cost: "High", feasibility: "Medium", priority: "PLANNED" },
    { rank: 5, name: "Water Body Permeable Edge Buffers", delta: "-0.45°C", coverage: "54 Water Tanks", cost: "Med-High", feasibility: "Medium", priority: "PLANNED" },
  ];

  return (
    <div className="p-6 rounded-3xl liquid-glass space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Award className="w-5 h-5 text-emerald-400 drop-shadow-[0_0_8px_rgba(52,211,153,0.7)]" />
          <h3 className="text-sm font-extrabold text-white uppercase tracking-wider">
            UHI Mitigation Priority & ROI Ranking
          </h3>
        </div>
        <span className="text-xs text-emerald-300 font-mono font-bold">
          Bhubaneswar Urban Planning Matrix
        </span>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-left text-xs">
          <thead>
            <tr className="border-b border-emerald-500/20 text-slate-300 font-bold uppercase tracking-wider text-[11px]">
              <th className="py-2.5 px-3">Rank</th>
              <th className="py-2.5 px-3">Intervention Action</th>
              <th className="py-2.5 px-3">Cooling Delta</th>
              <th className="py-2.5 px-3">Cells Benefited</th>
              <th className="py-2.5 px-3">Capex ROI</th>
              <th className="py-2.5 px-3">Priority</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-white/[0.05]">
            {rankedInterventions.map((item) => (
              <tr key={item.rank} className="hover:bg-emerald-950/20 transition-colors">
                <td className="py-3 px-3 font-mono font-extrabold text-emerald-400">#{item.rank}</td>
                <td className="py-3 px-3 font-bold text-white">{item.name}</td>
                <td className="py-3 px-3 font-extrabold font-mono text-emerald-300">{item.delta}</td>
                <td className="py-3 px-3 text-slate-300">{item.coverage}</td>
                <td className="py-3 px-3 text-slate-400">{item.cost}</td>
                <td className="py-3 px-3">
                  <span className={`px-2.5 py-0.5 rounded-full text-[10px] font-extrabold uppercase border ${
                    item.priority === 'IMMEDIATE'
                      ? 'bg-emerald-950/90 text-emerald-300 border-emerald-500/60 shadow-[0_0_10px_rgba(52,211,153,0.35)]'
                      : item.priority === 'HIGH'
                      ? 'bg-teal-950/90 text-teal-300 border-teal-500/60'
                      : 'bg-[#03091e] text-slate-400 border-slate-700'
                  }`}>
                    {item.priority}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
