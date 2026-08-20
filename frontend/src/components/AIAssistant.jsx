import React, { useState } from 'react';
import { motion } from 'framer-motion';
import { Bot, Send, Loader2, Sparkles, CheckCircle2, AlertTriangle, Database, BrainCircuit } from 'lucide-react';
import { askAI } from '../services/backendClient';
import { useLiveData } from '../context/LiveDataContext';

const SUGGESTED_QUESTIONS = [
  'Which areas are hottest?',
  'Why is this area at high risk?',
  'What happens if green cover increases by 20%?',
  'Which intervention provides the most cooling?',
  'Which areas should be prioritized?',
  'What factors influence this prediction?'
];

// Builds the whitelisted context from what actually exists - missing data is
// left out so the backend marks it unavailable (never guessed).
function buildContext({ selectedLocation, areaOsm, environmentSummary, liveWeather, modelInfo, snapshotId }) {
  const context = {};
  if (selectedLocation) {
    context.location = {
      name: selectedLocation.name,
      lat: selectedLocation.lat,
      lng: selectedLocation.lng
    };
  }
  const env = {};
  if (environmentSummary?.derived?.green_cover_pct != null) {
    env.green_cover = environmentSummary.derived.green_cover_pct; // real OSM-derived
  }
  if (Object.keys(env).length) context.environment = env;

  const urban = {};
  if (areaOsm?.buildings != null) {
    const km2 = Math.PI * ((areaOsm.radiusM ?? 150) / 1000) ** 2 || 1;
    urban.building_density = Math.round(areaOsm.buildings / km2);
    urban.road_density = areaOsm.roadLengthM != null ? Math.round((areaOsm.roadLengthM / 1000 / km2) * 100) / 100 : undefined;
    urban.tree_density = areaOsm.trees != null ? Math.round(areaOsm.trees / km2) : undefined;
  }
  const cleanUrban = Object.fromEntries(Object.entries(urban).filter(([, v]) => v !== undefined));
  if (Object.keys(cleanUrban).length) context.urban = cleanUrban;

  if (liveWeather?.temperature != null) {
    context.weather = {
      temperature: liveWeather.temperature,
      humidity: liveWeather.humidity ?? null,
      wind_speed: liveWeather.windSpeed ?? null,
      source: liveWeather.source || 'OpenWeather'
    };
  }
  if (modelInfo) {
    context.prediction = { available: modelInfo.available === true };
  }
  if (snapshotId) {
    context.snapshot_id = snapshotId;
  }
  return context;
}

export const AIAssistant = ({
  modelInfo,
  aiStatus,
  selectedLocation,
  areaOsm,
  environmentSummary,
  liveWeather,
  onStatusChange = () => {}
}) => {
  const { snapshotId } = useLiveData();
  const [question, setQuestion] = useState('');
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);

  const configured = aiStatus?.status === 'configured';

  const handleAsk = async (text) => {
    const q = (text ?? question).trim();
    if (!q || loading) return;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const context = buildContext({ selectedLocation, areaOsm, environmentSummary, liveWeather, modelInfo, snapshotId });
      const res = await askAI(q, context);
      if (res.success) {
        setResult(res);
      } else {
        setError(res.message || 'AI explanation unavailable.');
        onStatusChange();
      }
    } catch {
      setError('AI explanation unavailable.');
      onStatusChange();
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="ai-panel theme-panel">
      <div className="ai-panel-head">
        <div style={{ display: 'flex', flexDirection: 'column', gap: 2, minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <Bot size={16} color="#9333ea" />
            <strong>Urban AI Assistant</strong>
          </div>
          <span style={{ fontSize: '0.64rem', color: 'var(--text-muted)', paddingLeft: 24, lineHeight: 1.4 }}>
            Ask questions about the city, heat, pollution and scenarios.
          </span>
        </div>
        <span className={`status-pill ${configured ? 'status-ok' : 'status-missing'}`}>
          {aiStatus ? (configured ? <><CheckCircle2 size={12} /> Nemotron ready</> : <><AlertTriangle size={12} /> Configuration required</>) : <><Loader2 size={12} className="spin" /> Checking…</>}
        </span>
      </div>

      <div className="ai-input-row">
        <input
          className="ai-input"
          placeholder="Ask about the city… (e.g. Why is this area hot?)"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter') handleAsk(); }}
          disabled={loading}
        />
        <button
          className="ai-ask-btn"
          onClick={() => handleAsk()}
          disabled={loading || !question.trim()}
          title="Ask AI"
        >
          {loading ? <Loader2 size={15} className="spin" /> : <Send size={15} />}
        </button>
      </div>

      {!configured && (
        <div className="ai-unavailable">
          <AlertTriangle size={13} />
          <span>
            Nemotron configuration required. Set <code>NEMOTRON_API_KEY</code> in{' '}
            <code>.env</code> (backend only — see <code>.env.example</code>).
          </span>
        </div>
      )}

      <div className="ai-suggested">
        <span className="ai-suggested-label"><Sparkles size={12} /> Suggested</span>
        <div className="ai-chips">
          {SUGGESTED_QUESTIONS.map((q) => (
            <button key={q} className="ai-chip" onClick={() => { setQuestion(q); handleAsk(q); }} disabled={loading}>
              {q}
            </button>
          ))}
        </div>
      </div>

      {loading && (
        <div className="ai-loading"><Loader2 size={15} className="spin" /> Analyzing city data…</div>
      )}

      {error && (
        <div className="ai-error">
          <AlertTriangle size={14} /> {error}
        </div>
      )}

      {result && result.answer && (
        <motion.div
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          className="ai-answer"
        >
          <p className="ai-answer-text">{result.answer}</p>

          <div className="ai-answer-meta">
            <div>
              <span className="ai-meta-title"><Database size={12} /> DATA USED</span>
              <div className="ai-meta-list">
                {(result.data_used || []).map((d) => <span key={d} className="ai-meta-chip ok">✓ {d}</span>)}
                {(result.data_used || []).length === 0 && <span className="ai-meta-chip">No project data supplied</span>}
              </div>
            </div>
            {result.key_factors && result.key_factors.length > 0 && (
              <div>
                <span className="ai-meta-title"><BrainCircuit size={12} /> KEY FACTORS</span>
                <div className="ai-meta-list">
                  {result.key_factors.map((f, i) => <span key={i} className="ai-meta-chip">{f}</span>)}
                </div>
              </div>
            )}
          </div>
        </motion.div>
      )}

      <div className="ai-panel-foot">
        Nemotron explains real project data only — XGBoost remains the numerical
        prediction engine. Answers never contain invented values.
      </div>
    </div>
  );
};

export default AIAssistant;
