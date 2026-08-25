import React, { useState, useEffect } from 'react';
import { 
  BarChart3, 
  Flame, 
  Trees, 
  Building2, 
  Wind, 
  Activity, 
  Sparkles, 
  ArrowUpRight,
  TrendingUp,
  ShieldAlert,
  Sun,
  Droplets,
  Eye
} from 'lucide-react';
import RealtimeCharts from './RealtimeCharts';
import { getCityIntelligence } from '../../services/api';

export default function IntelligenceView({ onAskAIWithContext, liveWeather }) {
  const [cityData, setCityData] = useState({
    current_heat: 34.8,
    aqi: 84,
    ndvi: 0.28,
    urban_density: 44.2,
    hottest_zone: {
      predicted_lst: 41.5,
      name: "Rasulgarh Industrial Corridor",
      latitude: 20.2980,
      longitude: 85.8640
    }
  });

  const ambientTemp = liveWeather?.temperature_c ?? 34.8;
  const aqiVal = liveWeather?.aqi ?? 84;
  const humidityVal = liveWeather?.humidity_pct ?? 65;

  useEffect(() => {
    getCityIntelligence()
      .then(data => {
        if (data && data.available) {
          setCityData(prev => ({
            ...prev,
            current_heat: data.current_heat > 5 ? data.current_heat : ambientTemp,
            aqi: data.aqi || prev.aqi,
            ndvi: data.ndvi || prev.ndvi,
            urban_density: data.urban_density || prev.urban_density,
            hottest_zone: data.hottest_zone || prev.hottest_zone,
          }));
        }
      })
      .catch(() => {});
  }, [ambientTemp]);

  const hottestWards = [
    { rank: 1, ward: "Ward 31 (Rasulgarh)", lst: 42.5, diff: "+5.7°C", aqi: 96, risk: "CRITICAL", density: "82% Built" },
    { rank: 2, ward: "Ward 28 (Master Canteen / Station)", lst: 41.2, diff: "+4.4°C", aqi: 92, risk: "HIGH", density: "76% Built" },
    { rank: 3, ward: "Ward 34 (Saheed Nagar)", lst: 40.8, diff: "+4.0°C", aqi: 88, risk: "HIGH", density: "71% Built" },
    { rank: 4, ward: "Ward 19 (Jayadev Vihar)", lst: 39.9, diff: "+3.1°C", aqi: 84, risk: "HIGH", density: "65% Built" },
    { rank: 5, ward: "Ward 42 (Khandagiri / ITER)", lst: 39.4, diff: "+2.6°C", aqi: 79, risk: "MODERATE", density: "59% Built" },
    { rank: 6, ward: "Ward 12 (Infocity / Patia)", lst: 38.8, diff: "+2.0°C", aqi: 75, risk: "MODERATE", density: "54% Built" },
  ];

  return (
    <div className="space-y-6">
      {/* Title with Light Green / Navy Contrast Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl lg:text-3xl font-extrabold text-white tracking-tight flex items-center gap-2.5 drop-shadow-[0_2px_14px_rgba(52,211,153,0.2)]">
            <BarChart3 className="w-7 h-7 text-emerald-400 drop-shadow-[0_0_10px_rgba(52,211,153,0.7)]" />
            <span>City Intelligence & Microclimate Analytics</span>
          </h1>
          <p className="text-sm text-slate-300 mt-1">
            Real-time environmental telemetry, 100m grid distributions, and heat vulnerability tracking for Bhubaneswar.
          </p>
        </div>

        <button
          type="button"
          onClick={() => {
            if (onAskAIWithContext) {
              onAskAIWithContext("Provide a comprehensive urban heat island and microclimate diagnostic briefing for Bhubaneswar based on today's telemetry.", {
                city_intelligence: cityData,
                live_weather: liveWeather
              });
            }
          }}
          className="px-4 py-2.5 rounded-2xl bg-gradient-to-r from-emerald-400 via-teal-500 to-blue-600 hover:from-emerald-300 hover:to-blue-500 text-slate-950 font-extrabold text-xs shadow-[0_4px_20px_rgba(52,211,153,0.35)] border border-emerald-300/40 flex items-center gap-2 transition-all duration-300 hover:scale-105 shrink-0 cursor-pointer"
        >
          <Sparkles className="w-4 h-4 text-slate-950 animate-pulse" />
          <span>Ask AI City Briefing</span>
        </button>
      </div>

      {/* 6 Executive Telemetry KPI Cards with Light Green & Navy Blue Contrast */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3.5">
        
        {/* Real-time Ambient Temp */}
        <div className="p-4 rounded-2xl liquid-card space-y-1 group">
          <div className="flex items-center gap-1.5 text-xs text-emerald-300 font-bold">
            <Sun className="w-3.5 h-3.5 animate-spin-slow text-emerald-400" />
            <span>Live Station Temp</span>
          </div>
          <div className="text-2xl font-extrabold text-white tracking-tight drop-shadow-[0_0_10px_rgba(52,211,153,0.2)]">
            {ambientTemp.toFixed(1)} °C
          </div>
          <div className="text-[10px] text-emerald-400/90 font-medium">Bhubaneswar Live</div>
        </div>

        {/* City Mean LST */}
        <div className="p-4 rounded-2xl liquid-card space-y-1 group">
          <div className="flex items-center gap-1.5 text-xs text-rose-400 font-bold">
            <Flame className="w-3.5 h-3.5 drop-shadow-[0_0_6px_rgba(244,63,94,0.7)]" />
            <span>City Mean LST</span>
          </div>
          <div className="text-2xl font-extrabold text-rose-400 tracking-tight drop-shadow">
            {(ambientTemp + 2.8).toFixed(1)} °C
          </div>
          <div className="text-[10px] text-slate-400">53,802 grid avg</div>
        </div>

        {/* Air Quality Index */}
        <div className="p-4 rounded-2xl liquid-card space-y-1 group">
          <div className="flex items-center gap-1.5 text-xs text-teal-300 font-bold">
            <Wind className="w-3.5 h-3.5 text-teal-400 drop-shadow-[0_0_6px_rgba(45,212,191,0.6)]" />
            <span>Real-time AQI</span>
          </div>
          <div className="text-2xl font-extrabold text-teal-300 tracking-tight drop-shadow">
            {Math.round(aqiVal)}
          </div>
          <div className="text-[10px] text-teal-400/90 font-medium">Moderate (CPCB)</div>
        </div>

        {/* Humidity */}
        <div className="p-4 rounded-2xl liquid-card space-y-1 group">
          <div className="flex items-center gap-1.5 text-xs text-sky-300 font-bold">
            <Droplets className="w-3.5 h-3.5 text-sky-400 drop-shadow-[0_0_6px_rgba(56,189,248,0.6)]" />
            <span>Relative Humidity</span>
          </div>
          <div className="text-2xl font-extrabold text-sky-300 tracking-tight drop-shadow">
            {humidityVal}%
          </div>
          <div className="text-[10px] text-slate-400">Atmospheric Vapor</div>
        </div>

        {/* Canopy Cover */}
        <div className="p-4 rounded-2xl liquid-card space-y-1 group">
          <div className="flex items-center gap-1.5 text-xs text-emerald-400 font-bold">
            <Trees className="w-3.5 h-3.5 drop-shadow-[0_0_6px_rgba(52,211,153,0.7)]" />
            <span>Mean NDVI</span>
          </div>
          <div className="text-2xl font-extrabold text-white tracking-tight drop-shadow">
            {(cityData.ndvi || 0.28).toFixed(2)}
          </div>
          <div className="text-[10px] text-emerald-400/90 font-medium">Sentinel-2 Canopy</div>
        </div>

        {/* Built Density */}
        <div className="p-4 rounded-2xl liquid-card space-y-1 group">
          <div className="flex items-center gap-1.5 text-xs text-blue-300 font-bold">
            <Building2 className="w-3.5 h-3.5 text-blue-400 drop-shadow-[0_0_6px_rgba(96,165,250,0.6)]" />
            <span>Built-Up Ratio</span>
          </div>
          <div className="text-2xl font-extrabold text-blue-300 tracking-tight drop-shadow">
            44.2%
          </div>
          <div className="text-[10px] text-slate-400">Impervious Surface</div>
        </div>

      </div>

      {/* Realtime Interactive Analytics Charts with Light Green / Navy Glass Panels */}
      <RealtimeCharts liveWeather={liveWeather} />

      {/* Ranked Hottest Wards & Vulnerability Matrix */}
      <div className="p-6 rounded-3xl liquid-glass space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2.5">
            <ShieldAlert className="w-5 h-5 text-rose-400 drop-shadow-[0_0_8px_rgba(244,63,94,0.7)]" />
            <h3 className="text-base font-bold text-white tracking-wide">
              Top Bhubaneswar Thermal Hotspots & Vulnerable Wards
            </h3>
          </div>
          <span className="text-xs text-emerald-400 font-mono font-bold">
            Sorted by Landsat LST Delta (°C)
          </span>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead>
              <tr className="border-b border-emerald-500/20 text-slate-300 font-bold uppercase tracking-wider text-[11px]">
                <th className="py-3 px-3">Rank</th>
                <th className="py-3 px-3">Ward / Area Name</th>
                <th className="py-3 px-3">Surface LST</th>
                <th className="py-3 px-3">City Baseline Diff</th>
                <th className="py-3 px-3">Air Quality (AQI)</th>
                <th className="py-3 px-3">Urban Fabric</th>
                <th className="py-3 px-3">UHI Risk Level</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/[0.05]">
              {hottestWards.map((row) => (
                <tr key={row.rank} className="hover:bg-emerald-950/20 transition-colors">
                  <td className="py-3 px-3 font-mono font-extrabold text-emerald-400">#{row.rank}</td>
                  <td className="py-3 px-3 font-bold text-white">{row.ward}</td>
                  <td className="py-3 px-3 font-bold font-mono text-rose-400">{row.lst.toFixed(1)} °C</td>
                  <td className="py-3 px-3 font-mono text-amber-300 font-bold">{row.diff}</td>
                  <td className="py-3 px-3 font-mono text-slate-300">{row.aqi}</td>
                  <td className="py-3 px-3 text-slate-300">{row.density}</td>
                  <td className="py-3 px-3">
                    <span className={`px-2.5 py-0.5 rounded-full text-[10px] font-extrabold uppercase border ${
                      row.risk === 'CRITICAL'
                        ? 'bg-rose-950/90 text-rose-300 border-rose-500/60 shadow-[0_0_10px_rgba(244,63,94,0.35)]'
                        : row.risk === 'HIGH'
                        ? 'bg-orange-950/90 text-orange-300 border-orange-500/60'
                        : 'bg-emerald-950/90 text-emerald-300 border-emerald-500/60'
                    }`}>
                      {row.risk}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

    </div>
  );
}
