import React, { useState, useRef, useEffect } from 'react';
import { 
  Sparkles, 
  Send, 
  X, 
  Bot, 
  User, 
  Key, 
  HelpCircle, 
  Database,
  ArrowRight,
  RefreshCw,
  Sliders,
  Settings
} from 'lucide-react';
import { askAI } from '../../services/api';

export default function AIChatModal({
  isOpen,
  onClose,
  initialQuestion = null,
  initialContext = null,
  onOpenSettings
}) {
  const [messages, setMessages] = useState([
    {
      role: 'assistant',
      content: "Hello! I am HeatSync AI, powered by NVIDIA Nemotron and the 100m Bhubaneswar microclimate lattice. How can I assist you with heat maps, cooling corridors, or intervention simulations today?",
      dataUsed: ['100m Lattice', 'XGBoost Baseline']
    }
  ]);
  const [inputQuery, setInputQuery] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [activeContext, setActiveContext] = useState(null);
  const messagesEndRef = useRef(null);

  useEffect(() => {
    if (initialQuestion) {
      setInputQuery(initialQuestion);
      setActiveContext(initialContext);
    }
  }, [initialQuestion, initialContext]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isLoading]);

  const quickPrompts = [
    "Why is Master Canteen area hotter than Chandrasekharpur?",
    "Which intervention gives maximum cooling in Rasulgarh?",
    "How do green corridors lower walking heat stress?",
    "Explain today's predicted LST and health risks."
  ];

  const handleSend = async (textToSend) => {
    const query = textToSend || inputQuery;
    if (!query || !query.trim()) return;

    const userMessage = { role: 'user', content: query.trim() };
    setMessages(prev => [...prev, userMessage]);
    setInputQuery('');
    setIsLoading(true);

    try {
      const res = await askAI(query.trim(), activeContext);
      if (res && res.answer) {
        setMessages(prev => [
          ...prev,
          {
            role: 'assistant',
            content: res.answer,
            dataUsed: res.data_used || ['100m Lattice', 'Live Telemetry'],
            confidence: res.confidence || 'High'
          }
        ]);
      } else {
        setMessages(prev => [
          ...prev,
          {
            role: 'assistant',
            content: res.message || "NVIDIA Nemotron is currently waiting for your API key. You can easily configure your `NEMOTRON_API_KEY` in the settings menu to enable live reasoning.",
            showSettingsBtn: true
          }
        ]);
      }
    } catch (err) {
      setMessages(prev => [
        ...prev,
        {
          role: 'assistant',
          content: "I am ready to answer your heat mapping questions. Please make sure `NEMOTRON_API_KEY` is configured in your settings or `.env` file.",
          showSettingsBtn: true
        }
      ]);
    } finally {
      setIsLoading(false);
    }
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-md">
      <div className="relative w-full max-w-2xl h-[620px] rounded-3xl liquid-glass flex flex-col overflow-hidden border border-emerald-500/30 shadow-[0_20px_50px_rgba(0,0,0,0.85)]">
        
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 bg-[#03091e]/90 border-b border-emerald-500/20">
          <div className="flex items-center gap-3">
            <div className="p-2 rounded-xl bg-gradient-to-br from-emerald-400 to-teal-600 text-slate-950 shadow-[0_0_12px_#34d399]">
              <Sparkles className="w-5 h-5" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h3 className="text-sm font-extrabold text-white">NVIDIA Nemotron AI</h3>
                <span className="px-2 py-0.5 rounded-full text-[10px] font-extrabold bg-emerald-950/90 text-emerald-300 border border-emerald-500/40">
                  nemotron-mini-4b
                </span>
              </div>
              <p className="text-[11px] text-slate-300">
                Grounded in 53,802-cell Bhubaneswar Microclimate Twin
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={onOpenSettings}
              className="p-2 rounded-xl bg-[#040b20] hover:bg-emerald-950/40 text-slate-300 hover:text-emerald-300 border border-emerald-500/20 transition-colors cursor-pointer"
              title="API Key Settings"
            >
              <Settings className="w-4 h-4" />
            </button>
            <button
              onClick={onClose}
              className="p-2 rounded-xl bg-[#040b20] hover:bg-rose-950/40 text-slate-300 hover:text-rose-400 border border-emerald-500/20 transition-colors cursor-pointer"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* Quick Context Pill if active */}
        {activeContext && (
          <div className="px-5 py-2 bg-[#020718]/90 border-b border-emerald-500/20 text-[11px] text-emerald-300 flex items-center justify-between">
            <span className="truncate font-semibold">Active Context: Selected Map Point / Scenario</span>
            <button 
              onClick={() => setActiveContext(null)}
              className="text-slate-400 hover:text-white underline text-[10px] cursor-pointer"
            >
              Clear Context
            </button>
          </div>
        )}

        {/* Message Thread */}
        <div className="flex-1 overflow-y-auto p-5 space-y-4">
          {messages.map((msg, i) => {
            const isUser = msg.role === 'user';
            return (
              <div
                key={i}
                className={`flex gap-3 ${isUser ? 'justify-end' : 'justify-start'}`}
              >
                {!isUser && (
                  <div className="w-8 h-8 rounded-xl bg-emerald-950/90 border border-emerald-500/40 text-emerald-400 flex items-center justify-center shrink-0 mt-0.5 shadow-[0_0_10px_rgba(52,211,153,0.2)]">
                    <Bot className="w-4 h-4" />
                  </div>
                )}

                <div className={`max-w-[85%] rounded-3xl p-4 text-xs leading-relaxed ${
                  isUser
                    ? 'bg-gradient-to-r from-emerald-500 via-teal-600 to-blue-600 text-white rounded-br-none shadow-lg shadow-emerald-500/20 font-medium'
                    : 'bg-[#040b20]/95 text-slate-200 border border-emerald-500/25 rounded-bl-none shadow-xl'
                }`}>
                  <p className="whitespace-pre-wrap">{msg.content}</p>

                  {/* Provenance Tags */}
                  {msg.dataUsed && (
                    <div className="mt-3 pt-2.5 border-t border-emerald-500/15 flex flex-wrap items-center gap-1.5 text-[10px] text-slate-400">
                      <span className="text-emerald-400 font-bold">Data Grounding:</span>
                      {msg.dataUsed.map((tag, tIdx) => (
                        <span key={tIdx} className="px-2 py-0.5 rounded-full bg-[#020617] border border-emerald-500/30 text-emerald-300 font-mono font-semibold">
                          {tag}
                        </span>
                      ))}
                    </div>
                  )}

                  {/* Show Settings Button if key required */}
                  {msg.showSettingsBtn && (
                    <button
                      onClick={onOpenSettings}
                      className="mt-3 px-3.5 py-2 rounded-xl bg-gradient-to-r from-emerald-400 to-teal-500 hover:from-emerald-300 hover:to-teal-400 text-slate-950 font-extrabold text-xs flex items-center gap-1.5 cursor-pointer shadow-md"
                    >
                      <Key className="w-3.5 h-3.5" />
                      <span>Configure NEMOTRON_API_KEY</span>
                    </button>
                  )}
                </div>

                {isUser && (
                  <div className="w-8 h-8 rounded-xl bg-[#061230] border border-emerald-500/30 text-slate-300 flex items-center justify-center shrink-0 mt-0.5">
                    <User className="w-4 h-4" />
                  </div>
                )}
              </div>
            );
          })}

          {isLoading && (
            <div className="flex gap-3 justify-start items-center text-xs text-slate-400">
              <div className="w-8 h-8 rounded-xl bg-emerald-950/90 border border-emerald-500/40 text-emerald-400 flex items-center justify-center shrink-0">
                <Bot className="w-4 h-4 animate-spin" />
              </div>
              <div className="p-3.5 rounded-2xl bg-[#040b20] border border-emerald-500/25 flex items-center gap-2">
                <span className="w-2 h-2 rounded-full bg-emerald-400 animate-ping"></span>
                <span>Nemotron is reasoning over Bhubaneswar microclimate layers...</span>
              </div>
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>

        {/* Suggested Prompts */}
        <div className="p-3.5 bg-[#030818]/90 border-t border-emerald-500/20 space-y-1.5">
          <div className="text-[10px] text-emerald-300 font-extrabold uppercase tracking-wider flex items-center gap-1">
            <HelpCircle className="w-3 h-3 text-emerald-400" />
            <span>Suggested Inquiries</span>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {quickPrompts.map((prompt, idx) => (
              <button
                key={idx}
                onClick={() => handleSend(prompt)}
                className="px-3 py-1 rounded-xl bg-[#040b20] hover:bg-emerald-950/40 text-[11px] text-slate-300 hover:text-emerald-300 border border-emerald-500/20 transition-colors text-left cursor-pointer"
              >
                {prompt}
              </button>
            ))}
          </div>
        </div>

        {/* Input Bar */}
        <div className="p-4 bg-[#03091e] border-t border-emerald-500/20">
          <form
            onSubmit={(e) => {
              e.preventDefault();
              handleSend();
            }}
            className="flex items-center gap-2.5"
          >
            <input
              type="text"
              placeholder="Ask Nemotron about heat maps, corridors, cooling..."
              value={inputQuery}
              onChange={(e) => setInputQuery(e.target.value)}
              className="flex-1 px-4 py-2.5 rounded-2xl bg-[#020617] border border-emerald-500/30 text-xs text-white placeholder-slate-400 focus:outline-none focus:border-emerald-400"
            />
            <button
              type="submit"
              disabled={!inputQuery.trim() || isLoading}
              className="p-2.5 rounded-2xl bg-gradient-to-r from-emerald-400 via-teal-500 to-blue-600 hover:from-emerald-300 hover:to-blue-500 disabled:opacity-50 text-slate-950 font-extrabold shadow-lg shadow-emerald-500/25 transition-all cursor-pointer"
            >
              <Send className="w-4 h-4" />
            </button>
          </form>
        </div>

      </div>
    </div>
  );
}
