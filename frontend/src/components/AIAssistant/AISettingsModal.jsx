import React, { useState } from 'react';
import { Key, X, Check, ExternalLink, ShieldCheck, Cpu } from 'lucide-react';

export default function AISettingsModal({ isOpen, onClose }) {
  const [apiKey, setApiKey] = useState('');
  const [savedSuccess, setSavedSuccess] = useState(false);

  if (!isOpen) return null;

  const handleSaveKey = () => {
    if (apiKey.trim()) {
      localStorage.setItem('NEMOTRON_API_KEY', apiKey.trim());
      setSavedSuccess(true);
      setTimeout(() => {
        setSavedSuccess(false);
        onClose();
      }, 1000);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-md">
      <div className="relative w-full max-w-md rounded-3xl liquid-glass border border-emerald-500/30 shadow-[0_20px_50px_rgba(0,0,0,0.85)] p-6 space-y-5">
        
        {/* Header */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <div className="p-2 rounded-xl bg-gradient-to-br from-emerald-400 to-teal-600 text-slate-950 shadow-[0_0_12px_#34d399]">
              <Cpu className="w-5 h-5" />
            </div>
            <div>
              <h3 className="text-sm font-extrabold text-white">AI Engine Configuration</h3>
              <p className="text-xs text-slate-300">NVIDIA NIM Microservices</p>
            </div>
          </div>

          <button
            onClick={onClose}
            className="p-1.5 rounded-xl bg-[#040b20] hover:bg-rose-950/40 text-slate-300 hover:text-rose-400 border border-emerald-500/20 transition-colors cursor-pointer"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Info */}
        <div className="p-3.5 rounded-2xl bg-[#03091e]/90 border border-emerald-500/20 text-xs text-slate-300 leading-relaxed space-y-2">
          <p>
            HeatSync connects to <strong className="text-emerald-400">NVIDIA Nemotron-Mini-4B-Instruct</strong> via NVIDIA NIM to reason over GIS heat maps and scenario deltas.
          </p>
          <a
            href="https://build.nvidia.com/nvidia/nemotron-mini-4b-instruct"
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1 text-emerald-400 hover:text-emerald-300 font-semibold underline text-[11px]"
          >
            <span>Get your free NVIDIA NIM API key</span>
            <ExternalLink className="w-3 h-3" />
          </a>
        </div>

        {/* Key Input */}
        <div className="space-y-1.5">
          <label className="text-xs font-bold text-slate-200 flex items-center gap-1.5">
            <Key className="w-3.5 h-3.5 text-emerald-400" />
            <span>NEMOTRON_API_KEY</span>
          </label>
          <input
            type="password"
            placeholder="nvapi-..."
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            className="w-full px-4 py-2.5 rounded-2xl bg-[#020617] border border-emerald-500/30 text-xs text-white placeholder-slate-500 focus:outline-none focus:border-emerald-400 font-mono"
          />
        </div>

        {/* Buttons */}
        <div className="flex items-center gap-3 pt-2">
          <button
            onClick={handleSaveKey}
            className="flex-1 py-3 px-4 rounded-2xl bg-gradient-to-r from-emerald-400 via-teal-500 to-blue-600 hover:from-emerald-300 hover:to-blue-500 text-slate-950 font-extrabold text-xs shadow-lg shadow-emerald-500/25 flex items-center justify-center gap-2 transition-all cursor-pointer"
          >
            {savedSuccess ? <Check className="w-4 h-4 text-slate-950" /> : <ShieldCheck className="w-4 h-4 text-slate-950" />}
            <span>{savedSuccess ? 'Key Saved' : 'Save & Connect'}</span>
          </button>
        </div>

      </div>
    </div>
  );
}
