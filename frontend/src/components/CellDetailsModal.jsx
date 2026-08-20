import React from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { X, Flame, Wind, ShieldAlert, Check } from 'lucide-react';

export const CellDetailsModal = ({
  cell,
  onClose,
  isSimulated
}) => {
  if (!cell) return null;

  return (
    <AnimatePresence>
      <div style={{
        position: 'fixed',
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        background: 'rgba(15, 23, 42, 0.4)',
        backdropFilter: 'blur(8px)',
        zIndex: 2000,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '20px'
      }}>
        <motion.div
          initial={{ opacity: 0, scale: 0.92, y: 20 }}
          animate={{ opacity: 1, scale: 1, y: 0 }}
          exit={{ opacity: 0, scale: 0.92, y: 20 }}
          transition={{ duration: 0.3, ease: [0.16, 1, 0.3, 1] }}
          className="light-panel"
          style={{
            width: '100%',
            maxWidth: '640px',
            padding: '28px',
            borderRadius: '18px',
            background: '#ffffff',
            border: '1px solid #e2e8f0',
            boxShadow: '0 25px 50px -12px rgba(0, 0, 0, 0.15)'
          }}
        >
          
          {/* Header */}
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', borderBottom: '1px solid #e2e8f0', paddingBottom: '14px', marginBottom: '20px' }}>
            <div>
              <span style={{ fontSize: '0.7rem', fontWeight: 700, color: '#0284c7', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                Grid Cell Microclimate Diagnostic ({cell.code})
              </span>
              <h2 style={{ fontSize: '1.3rem', fontWeight: 800, color: '#0f172a', margin: '2px 0 0 0' }}>
                {cell.streetName}
              </h2>
            </div>
            <button
              onClick={onClose}
              style={{ background: '#f1f5f9', border: 'none', borderRadius: '50%', padding: '8px', cursor: 'pointer', color: '#64748b' }}
            >
              <X size={18} />
            </button>
          </div>

          {/* Diagnostic Grid Cards */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '14px', marginBottom: '20px' }}>
            
            {/* LST Temperature Card */}
            <div style={{ padding: '16px', background: '#fee2e2', borderRadius: '12px', border: '1px solid #fca5a5' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: '#b91c1c', fontSize: '0.82rem', fontWeight: 700, marginBottom: '6px' }}>
                <Flame size={18} /> Surface Temp (LST)
              </div>
              <div style={{ fontSize: '1.75rem', fontWeight: 800, color: '#0f172a' }}>
                {isSimulated ? cell.simulatedLST : cell.baselineLST}°C
                {isSimulated && cell.tempDelta > 0 && (
                  <span style={{ fontSize: '0.95rem', color: '#16a34a', marginLeft: '6px', fontWeight: 800 }}>
                    (-{cell.tempDelta}°C)
                  </span>
                )}
              </div>
              <div style={{ fontSize: '0.72rem', color: '#475569', marginTop: '4px' }}>
                95% Confidence Bounds: <strong>{cell.confidenceLowerLST}°C – {cell.confidenceUpperLST}°C</strong>
              </div>
            </div>

            {/* Air Quality AQI Card */}
            <div style={{ padding: '16px', background: '#fef3c7', borderRadius: '12px', border: '1px solid #fcd34d' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: '#b45309', fontSize: '0.82rem', fontWeight: 700, marginBottom: '6px' }}>
                <Wind size={18} /> Air Quality (PM2.5)
              </div>
              <div style={{ fontSize: '1.75rem', fontWeight: 800, color: '#0f172a' }}>
                {isSimulated ? cell.simulatedAQI : cell.baselineAQI} AQI
                {isSimulated && cell.aqiDelta > 0 && (
                  <span style={{ fontSize: '0.95rem', color: '#16a34a', marginLeft: '6px', fontWeight: 800 }}>
                    (-{cell.aqiDelta})
                  </span>
                )}
              </div>
              <div style={{ fontSize: '0.72rem', color: '#475569', marginTop: '4px' }}>
                95% Confidence Bounds: <strong>{cell.confidenceLowerAQI} – {cell.confidenceUpperAQI} AQI</strong>
              </div>
            </div>

          </div>

          {/* Spatial Microclimate Indicators */}
          <div style={{ background: '#f8fafc', padding: '16px', borderRadius: '12px', border: '1px solid #e2e8f0', marginBottom: '20px' }}>
            <h4 style={{ fontSize: '0.88rem', fontWeight: 800, color: '#0f172a', marginBottom: '12px' }}>
              Spatial Microclimate Indicators
            </h4>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '12px', fontSize: '0.78rem' }}>
              <div>
                <span style={{ color: '#64748b', display: 'block', fontWeight: 500 }}>Tree Canopy</span>
                <strong style={{ color: '#16a34a', fontSize: '0.9rem' }}>{cell.treeCanopyPct}% Cover</strong>
              </div>
              <div>
                <span style={{ color: '#64748b', display: 'block', fontWeight: 500 }}>Cool Roof Albedo</span>
                <strong style={{ color: '#0284c7', fontSize: '0.9rem' }}>{cell.coolRoofPct}% Reflective</strong>
              </div>
              <div>
                <span style={{ color: '#64748b', display: 'block', fontWeight: 500 }}>Sky View Factor</span>
                <strong style={{ color: '#9333ea', fontSize: '0.9rem' }}>{cell.svf} SVF</strong>
              </div>
              <div>
                <span style={{ color: '#64748b', display: 'block', fontWeight: 500 }}>Outdoor Workers</span>
                <strong style={{ color: '#d97706', fontSize: '0.9rem' }}>~{cell.outdoorWorkerCount} people</strong>
              </div>
              <div>
                <span style={{ color: '#64748b', display: 'block', fontWeight: 500 }}>Station Distance</span>
                <strong style={{ color: '#475569', fontSize: '0.9rem' }}>{cell.distanceToStation}m ({cell.nearestStation})</strong>
              </div>
            </div>
          </div>

          {/* Vulnerability & Uncertainty Summary */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px', fontSize: '0.78rem' }}>
            <div style={{ padding: '12px 14px', background: '#f3e8ff', borderRadius: '10px', border: '1px solid #d8b4fe' }}>
              <span style={{ color: '#7e22ce', fontWeight: 700, display: 'flex', alignItems: 'center', gap: '6px' }}>
                <ShieldAlert size={15} /> Vulnerability Index
              </span>
              <div style={{ fontSize: '1.2rem', fontWeight: 800, color: '#0f172a', marginTop: '2px' }}>
                {cell.vulnerabilityScore} / 100
              </div>
              <span style={{ fontSize: '0.7rem', color: '#6b21a8', fontWeight: 600 }}>{cell.vulnerabilityType}</span>
            </div>

            <div style={{ padding: '12px 14px', background: '#dcfce7', borderRadius: '10px', border: '1px solid #86efac' }}>
              <span style={{ color: '#15803d', fontWeight: 700, display: 'flex', alignItems: 'center', gap: '6px' }}>
                <Check size={15} /> Prediction Confidence
              </span>
              <div style={{ fontSize: '1.2rem', fontWeight: 800, color: '#0f172a', marginTop: '2px' }}>
                {100 - cell.uncertaintyScore}% Confidence
              </div>
              <span style={{ fontSize: '0.7rem', color: '#166534', fontWeight: 600 }}>Calibrated within {cell.distanceToStation}m of CPCB node</span>
            </div>
          </div>

        </motion.div>
      </div>
    </AnimatePresence>
  );
};
