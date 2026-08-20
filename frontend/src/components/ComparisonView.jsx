import React from 'react';
import { motion } from 'framer-motion';
import { DigitalTwinMap } from './DigitalTwinMap';
import { Flame, Sparkles } from 'lucide-react';

export const ComparisonView = ({
  baselineCells,
  simulatedCells,
  activeLayer,
  showStations,
  showBuildings = true,
  summary,
  onCellClick,
  theme = 'light'
}) => {
  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.98 }}
      animate={{ opacity: 1, scale: 1 }}
      style={{ width: '100%', height: '100%', display: 'flex', flexDirection: 'column', gap: '12px' }}
    >
      
      {/* Comparison Header Summary Banner */}
      <div className="theme-panel" style={{ padding: '12px 20px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', borderRadius: '12px', boxShadow: 'var(--shadow-sm)' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <div style={{ background: 'var(--primary-sky-light)', padding: '8px', borderRadius: '10px', border: '1px solid var(--border-light)' }}>
            <Sparkles size={20} color="var(--primary-sky)" />
          </div>
          <div>
            <strong style={{ fontSize: '0.98rem', color: 'var(--text-main)', display: 'block' }}>
              Split-Screen Microclimate Impact Comparison
            </strong>
            <span style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
              Live real-time comparison of baseline thermal/AQI footprint vs. simulated intervention state
            </span>
          </div>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '20px' }}>
          <div style={{ textAlign: 'right' }}>
            <span style={{ fontSize: '0.66rem', color: 'var(--text-muted)', fontWeight: 600, display: 'block' }}>Avg Surface Cooling</span>
            <strong style={{ fontSize: '1.05rem', color: '#16a34a' }}>
              -{summary.avgTempDrop}°C Drop
            </strong>
          </div>
          <div style={{ textAlign: 'right' }}>
            <span style={{ fontSize: '0.66rem', color: 'var(--text-muted)', fontWeight: 600, display: 'block' }}>Avg AQI Clean</span>
            <strong style={{ fontSize: '1.05rem', color: 'var(--primary-sky)' }}>
              -{summary.avgAQIDrop} Points
            </strong>
          </div>
        </div>
      </div>

      {/* Side-by-Side Dual Map Containers */}
      <div style={{ flex: 1, display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '14px', minHeight: '450px' }}>
        
        {/* Left Map: Baseline Current State Map */}
        <div style={{ position: 'relative', width: '100%', height: '100%', minHeight: '450px', borderRadius: '14px', overflow: 'hidden', border: '1px solid rgba(220, 38, 38, 0.3)', boxShadow: 'var(--shadow-sm)' }}>
          <div style={{
            position: 'absolute',
            top: '14px',
            left: '14px',
            zIndex: 999,
            background: 'var(--bg-surface)',
            backdropFilter: 'blur(8px)',
            padding: '6px 14px',
            borderRadius: '8px',
            border: '1px solid rgba(220, 38, 38, 0.3)',
            color: '#dc2626',
            fontWeight: 800,
            fontSize: '0.76rem',
            display: 'flex',
            alignItems: 'center',
            gap: '6px',
            boxShadow: 'var(--shadow-sm)'
          }}>
            <Flame size={14} /> BASELINE CURRENT STATE
          </div>
          <DigitalTwinMap
            gridCells={baselineCells}
            activeLayer={activeLayer}
            showStations={showStations}
            showBuildings={showBuildings}
            onCellClick={onCellClick}
            isSimulated={false}
            theme={theme}
          />
        </div>

        {/* Right Map: Simulated Future Intervention State Map */}
        <div style={{ position: 'relative', width: '100%', height: '100%', minHeight: '450px', borderRadius: '14px', overflow: 'hidden', border: '1px solid rgba(22, 163, 74, 0.4)', boxShadow: 'var(--shadow-sm)' }}>
          <div style={{
            position: 'absolute',
            top: '14px',
            left: '14px',
            zIndex: 999,
            background: 'var(--bg-surface)',
            backdropFilter: 'blur(8px)',
            padding: '6px 14px',
            borderRadius: '8px',
            border: '1px solid rgba(22, 163, 74, 0.4)',
            color: '#16a34a',
            fontWeight: 800,
            fontSize: '0.76rem',
            display: 'flex',
            alignItems: 'center',
            gap: '6px',
            boxShadow: 'var(--shadow-sm)'
          }}>
            <Sparkles size={14} /> SIMULATED INTERVENTION STATE
          </div>
          <DigitalTwinMap
            gridCells={simulatedCells}
            activeLayer={activeLayer === 'lst' ? 'delta' : activeLayer}
            showStations={showStations}
            showBuildings={showBuildings}
            onCellClick={onCellClick}
            isSimulated={true}
            theme={theme}
          />
        </div>

      </div>

    </motion.div>
  );
};
