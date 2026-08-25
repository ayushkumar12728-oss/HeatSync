import React, { useState, useEffect } from 'react';
import Navbar from './components/Navbar';
import RouteView from './components/HeatSafeRoute/RouteView';
import MapView from './components/MapExplorer/MapView';
import SimulatorView from './components/ScenarioSimulator/SimulatorView';
import IntelligenceView from './components/CityIntelligence/IntelligenceView';
import AIChatModal from './components/AIAssistant/AIChatModal';
import AISettingsModal from './components/AIAssistant/AISettingsModal';
import { getLiveWeather } from './services/api';
import { Sparkles, AlertCircle } from 'lucide-react';

class ViewErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }

  componentDidCatch(error, errorInfo) {
    console.error('View rendering error:', error, errorInfo);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="p-8 rounded-3xl liquid-glass text-center space-y-4 max-w-lg mx-auto my-12">
          <div className="w-12 h-12 rounded-2xl bg-rose-950/80 border border-rose-500/40 flex items-center justify-center mx-auto text-rose-400">
            <AlertCircle className="w-6 h-6" />
          </div>
          <h3 className="text-base font-bold text-white">Temporary View Loading Issue</h3>
          <p className="text-xs text-slate-300">
            {this.state.error?.message || 'An unexpected rendering error occurred in this view.'}
          </p>
          <button
            type="button"
            onClick={() => this.setState({ hasError: false, error: null })}
            className="px-4 py-2 rounded-xl bg-gradient-to-r from-emerald-400 to-teal-500 text-slate-950 font-bold text-xs"
          >
            Reload Component
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}

export default function App() {
  const getInitialTab = () => {
    const hash = window.location.hash.replace('#', '');
    if (['map', 'simulator', 'intelligence', 'route'].includes(hash)) {
      return hash;
    }
    return 'map'; // Default to Map Explorer for great first impression
  };

  const [activeTab, setActiveTab] = useState(getInitialTab);
  const [liveWeather, setLiveWeather] = useState({ 
    temperature_c: 34.8, 
    feels_like_c: 37.6, 
    humidity_pct: 65,
    aqi: 84,
    condition: 'Sunny'
  });
  const [isAIChatOpen, setIsAIChatOpen] = useState(false);
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const [aiQuestion, setAiQuestion] = useState(null);
  const [aiContext, setAiContext] = useState(null);

  // Sync tab with URL hash
  useEffect(() => {
    const handleHashChange = () => {
      const hash = window.location.hash.replace('#', '');
      if (['map', 'simulator', 'intelligence', 'route'].includes(hash)) {
        setActiveTab(hash);
      }
    };

    window.addEventListener('hashchange', handleHashChange);
    return () => window.removeEventListener('hashchange', handleHashChange);
  }, []);

  const handleTabChange = (tabId) => {
    setActiveTab(tabId);
    window.location.hash = tabId;
  };

  // Poll live real-time temperature & weather every 12 seconds
  useEffect(() => {
    const fetchWeather = async () => {
      try {
        const data = await getLiveWeather();
        if (data && data.temperature_c !== undefined) {
          setLiveWeather(data);
        }
      } catch (err) {
        console.warn('Weather sync error:', err);
      }
    };

    fetchWeather();
    const interval = setInterval(fetchWeather, 12000);
    return () => clearInterval(interval);
  }, []);

  const handleOpenAIChatWithContext = (question, context = null) => {
    setAiQuestion(question);
    setAiContext(context);
    setIsAIChatOpen(true);
  };

  return (
    <div className="relative min-h-screen bg-[#020617] text-slate-100 flex flex-col justify-between selection:bg-emerald-400 selection:text-slate-950 overflow-x-hidden">
      {/* Background Multi-Layered Light Green & Deep Navy Fluid Orbs */}
      <div className="fluid-blob-1" />
      <div className="fluid-blob-2" />
      <div className="fluid-blob-3" />
      <div className="fluid-blob-4" />

      {/* Top High-Contrast Navbar */}
      <Navbar
        activeTab={activeTab}
        setActiveTab={handleTabChange}
        liveWeather={liveWeather}
        onOpenAIChat={() => {
          setAiQuestion(null);
          setAiContext(null);
          setIsAIChatOpen(true);
        }}
        onOpenSettings={() => setIsSettingsOpen(true)}
      />

      {/* Main Dashboard Workspace */}
      <main className="relative z-10 flex-1 max-w-[1720px] w-full mx-auto p-4 lg:p-7">
        <ViewErrorBoundary key={activeTab}>
          {activeTab === 'map' && (
            <MapView onAskAIWithContext={handleOpenAIChatWithContext} liveWeather={liveWeather} />
          )}
          {activeTab === 'simulator' && (
            <SimulatorView onAskAIWithContext={handleOpenAIChatWithContext} />
          )}
          {activeTab === 'intelligence' && (
            <IntelligenceView onAskAIWithContext={handleOpenAIChatWithContext} liveWeather={liveWeather} />
          )}
          {activeTab === 'route' && (
            <RouteView liveWeather={liveWeather} />
          )}
        </ViewErrorBoundary>
      </main>

      {/* Floating Action Button for Nemotron AI with Mint/Navy Glass Effect */}
      <button
        type="button"
        onClick={() => {
          setAiQuestion(null);
          setAiContext(null);
          setIsAIChatOpen(true);
        }}
        className="fixed bottom-6 right-6 z-40 px-4 py-3 rounded-2xl bg-gradient-to-r from-emerald-500 via-teal-500 to-blue-600 hover:from-emerald-400 hover:to-blue-500 text-white shadow-[0_8px_32px_rgba(16,185,129,0.4)] border border-emerald-300/40 backdrop-blur-2xl flex items-center gap-2.5 font-bold text-xs transition-all duration-300 hover:scale-105 cursor-pointer group"
        title="Ask HeatSync AI"
      >
        <Sparkles className="w-5 h-5 text-emerald-200 animate-pulse drop-shadow-[0_0_8px_#34d399]" />
        <span className="hidden sm:inline font-bold tracking-wide">Ask Nemotron AI</span>
      </button>

      {/* AI Assistant Modal */}
      <AIChatModal
        isOpen={isAIChatOpen}
        onClose={() => setIsAIChatOpen(false)}
        initialQuestion={aiQuestion}
        initialContext={aiContext}
        onOpenSettings={() => {
          setIsAIChatOpen(false);
          setIsSettingsOpen(true);
        }}
      />

      {/* AI Settings Modal */}
      <AISettingsModal
        isOpen={isSettingsOpen}
        onClose={() => setIsSettingsOpen(false)}
      />

      {/* High-Contrast Footer */}
      <footer className="relative z-10 w-full bg-[#030818]/90 backdrop-blur-xl border-t border-emerald-500/15 px-6 py-4 mt-8">
        <div className="max-w-[1720px] mx-auto flex flex-col sm:flex-row items-center justify-between gap-2 text-xs text-slate-400">
          <div className="flex items-center gap-2">
            <span className="font-bold text-emerald-400">HeatSync Bhubaneswar</span>
            <span>•</span>
            <span className="text-slate-300">AI Microclimate & Urban Heat Island Digital Twin</span>
          </div>
          <div className="flex items-center gap-4 text-[11px] text-slate-400 font-mono">
            <span className="text-emerald-400 font-semibold">53,802 Grid Lattice</span>
            <span>•</span>
            <span>Sentinel-2 & Landsat 8/9</span>
            <span>•</span>
            <span className="text-sky-400 font-semibold">Real-Time Weather Sync</span>
          </div>
        </div>
      </footer>
    </div>
  );
}
