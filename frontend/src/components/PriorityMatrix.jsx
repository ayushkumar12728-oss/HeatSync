import React from 'react';
import { motion } from 'framer-motion';
import { Award, ShieldAlert, ChevronRight } from 'lucide-react';

export const PriorityMatrix = ({
  rankedPriorityCells,
  onSelectCell,
  isSimulated
}) => {
  const containerVariants = {
    hidden: { opacity: 0 },
    show: {
      opacity: 1,
      transition: {
        staggerChildren: 0.05
      }
    }
  };

  const itemVariants = {
    hidden: { opacity: 0, y: 8 },
    show: { opacity: 1, y: 0 }
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 15 }}
      animate={{ opacity: 1, y: 0 }}
      className="theme-panel"
      style={{
        padding: '16px 20px',
        borderRadius: '14px',
        display: 'flex',
        flexDirection: 'column',
        gap: '12px'
      }}
    >
      
      {/* Matrix Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div>
          <h3 style={{ fontSize: '1.05rem', fontWeight: 800, color: 'var(--text-main)', margin: 0, display: 'flex', alignItems: 'center', gap: '8px' }}>
            <Award size={18} color="#d97706" />
            Priority Intervention Action Matrix
          </h3>
          <p style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', margin: '2px 0 0 0' }}>
            Ranked by Vulnerability-Weighted Equity Benefit Ratio
          </p>
        </div>

        <span className="badge" style={{ fontSize: '0.7rem', background: 'var(--primary-sky-light)', color: 'var(--primary-sky)', border: '1px solid var(--border-light)' }}>
          {isSimulated ? 'Simulation Output Active' : 'Baseline Priority Scan'}
        </span>
      </div>

      {/* Priority List with Framer Motion Stagger Animation */}
      <motion.div
        variants={containerVariants}
        initial="hidden"
        animate="show"
        style={{ display: 'flex', flexDirection: 'column', gap: '8px', maxHeight: '280px', overflowY: 'auto' }}
      >
        {rankedPriorityCells.map((cell, index) => (
          <motion.div
            key={cell.id}
            variants={itemVariants}
            onClick={() => onSelectCell(cell)}
            className="card-3d"
            style={{
              padding: '10px 16px',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              gap: '14px'
            }}
          >
            {/* Rank Badge & Street Info */}
            <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
              <div style={{
                width: '28px',
                height: '28px',
                borderRadius: '50%',
                background: index === 0 ? 'linear-gradient(135deg, #d97706, #f59e0b)' : 'var(--primary-sky-light)',
                color: index === 0 ? '#ffffff' : 'var(--primary-sky)',
                fontWeight: 800,
                fontSize: '0.82rem',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                boxShadow: index === 0 ? '0 3px 10px rgba(217, 119, 6, 0.35)' : 'none'
              }}>
                #{index + 1}
              </div>

              <div>
                <strong style={{ fontSize: '0.88rem', color: 'var(--text-main)', display: 'block' }}>
                  {cell.streetName}
                </strong>
                <span style={{ fontSize: '0.72rem', color: '#9333ea', display: 'flex', alignItems: 'center', gap: '4px', fontWeight: 600 }}>
                  <ShieldAlert size={12} /> {cell.vulnerabilityType}
                </span>
              </div>
            </div>

            {/* Impact Metrics & Deltas */}
            <div style={{ display: 'flex', alignItems: 'center', gap: '18px' }}>
              
              <div style={{ textAlign: 'right' }}>
                <span style={{ fontSize: '0.66rem', color: 'var(--text-muted)', fontWeight: 600, display: 'block' }}>LST Temp</span>
                <strong style={{ fontSize: '0.9rem', color: isSimulated && cell.tempDelta > 0 ? '#16a34a' : '#dc2626' }}>
                  {isSimulated && cell.tempDelta > 0 ? `-${cell.tempDelta}°C` : `${cell.baselineLST}°C`}
                </strong>
              </div>

              <div style={{ textAlign: 'right' }}>
                <span style={{ fontSize: '0.66rem', color: 'var(--text-muted)', fontWeight: 600, display: 'block' }}>AQI Clean</span>
                <strong style={{ fontSize: '0.9rem', color: isSimulated && cell.aqiDelta > 0 ? '#16a34a' : '#d97706' }}>
                  {isSimulated && cell.aqiDelta > 0 ? `-${cell.aqiDelta} AQI` : cell.baselineAQI}
                </strong>
              </div>

              <div style={{ textAlign: 'right', paddingLeft: '10px', borderLeft: '1px solid var(--border-light)' }}>
                <span style={{ fontSize: '0.66rem', color: 'var(--text-muted)', fontWeight: 600, display: 'block' }}>Equity Score</span>
                <strong style={{ fontSize: '0.95rem', color: 'var(--primary-sky)' }}>
                  {cell.benefitScore || Math.round(cell.vulnerabilityScore * 1.8)}
                </strong>
              </div>

              <ChevronRight size={18} color="var(--text-muted)" />
            </div>

          </motion.div>
        ))}
      </motion.div>

    </motion.div>
  );
};
