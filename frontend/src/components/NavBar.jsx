import React from 'react';
import { 
  Flame, 
  Map as MapIcon, 
  Sliders, 
  BarChart3, 
  Navigation, 
  Sun, 
  Wind, 
  Sparkles,
  Settings,
  Droplets
} from 'lucide-react';

export default function Navbar({ 
  activeTab, 
  setActiveTab, 
  liveWeather, 
  onOpenAIChat,
  onOpenSettings
}) {
  const temp = liveWeather?.temperature_c ?? 34.8;
  const feelsLike = liveWeather?.feels_like_c ?? (temp + 2.5);
  const aqi = liveWeather?.aqi ?? 84;
  const aqiLabel = aqi <= 50 ? 'Good' : aqi <= 100 ? 'Moderate' : aqi <= 200 ? 'Unhealthy' : 'Severe';

  const navItems = [
    { id: 'map', label: 'Map Explorer', icon: MapIcon },
    { id: 'simulator', label: 'Scenario Simulator', icon: Sliders },
    { id: 'intelligence', label: 'City Intelligence', icon: BarChart3 },
    { id: 'route', label: 'Heat-Safe Route', icon: Navigation },
  ];

  return (
    <header className="sticky top-0 z-50 w-full bg-[#030818]/80 backdrop-blur-2xl border-b border-emerald-500/20 px-4 lg:px-7 py-3.5 shadow-[0_4px_30px_rgba(2,6,23,0.7)]">
      <div className="max-w-[1720px] mx-auto flex flex-wrap items-center justify-between gap-4">
        
        {/* Brand / Logo with Light Green & Navy Blue Glow */}
        <button
          type="button"
          onClick={() => setActiveTab('map')}
          className="flex items-center gap-3.5 text-left cursor-pointer group bg-transparent border-none p-0"
        >
          <div className="relative flex items-center justify-center w-10 h-10 rounded-2xl bg-gradient-to-br from-emerald-400 via-teal-500 to-blue-700 shadow-[0_0_22px_rgba(52,211,153,0.45)] border border-emerald-300/40 text-white font-bold group-hover:scale-105 transition-transform">
            <Flame className="w-5 h-5 text-white drop-shadow-[0_0_8px_#34d399]" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span className="text-xl font-extrabold tracking-tight text-white drop-shadow-[0_2px_12px_rgba(52,211,153,0.25)]">
                Heat<span className="text-emerald-400">Sync</span>
              </span>
              <span className="text-[10px] uppercase font-extrabold tracking-wider px-2.5 py-0.5 rounded-full bg-emerald-950/90 text-emerald-300 border border-emerald-400/50 shadow-[0_0_14px_rgba(52,211,153,0.3)]">
                DIGITAL TWIN
              </span>
            </div>
            <p className="text-xs text-slate-300 font-medium tracking-wide">
              Bhubaneswar • 100m AI Microclimate Grid
            </p>
          </div>
        </button>

        {/* Center Nav Tabs with Light Green / Navy Contrast */}
        <nav className="flex items-center gap-1.5 p-1 rounded-2xl bg-[#050e26]/80 backdrop-blur-xl border border-emerald-500/20 shadow-inner">
          {navItems.map((item) => {
            const Icon = item.icon;
            const isActive = activeTab === item.id;
            return (
              <button
                key={item.id}
                type="button"
                onClick={() => setActiveTab(item.id)}
                className={`flex items-center gap-2 px-4 py-2 rounded-xl text-xs md:text-sm font-semibold transition-all duration-300 cursor-pointer relative ${
                  isActive
                    ? 'bg-gradient-to-r from-emerald-500 via-teal-600 to-blue-600 text-white shadow-[0_4px_22px_rgba(16,185,129,0.45)] border border-emerald-300/40 font-bold'
                    : 'text-slate-300 hover:text-emerald-300 hover:bg-emerald-950/40'
                }`}
              >
                <Icon className={`w-4 h-4 ${isActive ? 'text-white drop-shadow-[0_0_6px_#fff]' : 'text-slate-400'}`} />
                <span>{item.label}</span>
              </button>
            );
          })}
        </nav>

        {/* Right Status / Telemetry Widgets */}
        <div className="flex items-center gap-3">
          
          {/* Live Temperature Pill with Light Green / Amber accents */}
          <div 
            className="flex items-center gap-2 px-3.5 py-1.5 rounded-xl bg-gradient-to-br from-emerald-950/70 via-[#050e26] to-teal-950/70 backdrop-blur-xl border border-emerald-400/35 text-xs font-bold text-emerald-300 shadow-[0_0_18px_rgba(52,211,153,0.2)] group relative cursor-help"
            title={`Real-Time Bhubaneswar Temp: ${temp.toFixed(1)}°C (Feels like ${feelsLike.toFixed(1)}°C)`}
          >
            <div className="relative flex items-center justify-center">
              <Sun className="w-4 h-4 text-emerald-400 animate-spin-slow" />
              <span className="absolute -top-1 -right-1 w-2 h-2 rounded-full bg-emerald-400 animate-ping"></span>
            </div>
            <span className="font-mono text-sm tracking-tight text-white font-extrabold">{temp.toFixed(1)} °C</span>
            <span className="hidden sm:inline text-[10px] text-emerald-400/90 font-normal">
              (Feels {feelsLike.toFixed(1)}°)
            </span>
          </div>

          {/* AQI Mint Pill */}
          <div className="hidden sm:flex items-center gap-2 px-3.5 py-1.5 rounded-xl bg-gradient-to-br from-teal-950/70 to-blue-950/70 backdrop-blur-xl border border-teal-400/35 text-xs font-semibold text-teal-300 shadow-[0_0_16px_rgba(45,212,191,0.18)]">
            <Wind className="w-3.5 h-3.5 text-teal-400" />
            <span>AQI {aqi} ({aqiLabel})</span>
          </div>

          {/* AI Status Badge */}
          <div className="hidden md:flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-emerald-950/80 border border-emerald-500/30 text-emerald-300 text-xs font-semibold">
            <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span>
            <span>AI Live</span>
          </div>

          {/* Ask AI Top Action Button */}
          <button
            type="button"
            onClick={onOpenAIChat}
            className="px-3.5 py-1.5 rounded-xl bg-gradient-to-r from-emerald-400 via-teal-500 to-blue-600 hover:from-emerald-300 hover:to-blue-500 text-slate-950 font-extrabold text-xs shadow-[0_0_16px_rgba(52,211,153,0.35)] border border-emerald-300/40 flex items-center gap-1.5 transition-all duration-300 hover:scale-105 cursor-pointer"
          >
            <Sparkles className="w-3.5 h-3.5 text-slate-950" />
            <span>Ask AI</span>
          </button>

          {/* Settings Button */}
          <button
            type="button"
            onClick={onOpenSettings}
            className="p-2 rounded-xl bg-[#040a1c] hover:bg-emerald-950/40 text-slate-300 hover:text-emerald-300 border border-emerald-500/25 transition-colors cursor-pointer"
            title="Configure AI & API Keys"
          >
            <Settings className="w-4 h-4" />
          </button>

        </div>

      </div>
    </header>
  );
}
