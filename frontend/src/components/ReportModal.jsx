import React from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { X, Printer } from 'lucide-react';

export const ReportModal = ({
  onClose,
  summary,
  rankedPriorityCells,
  scenario
}) => {
  const handlePrint = () => {
    window.print();
  };

  return (
    <AnimatePresence>
      <div style={{
        position: 'fixed',
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        background: 'rgba(15, 23, 42, 0.5)',
        backdropFilter: 'blur(10px)',
        zIndex: 3000,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '24px'
      }}>
        <motion.div
          initial={{ opacity: 0, scale: 0.94, y: 20 }}
          animate={{ opacity: 1, scale: 1, y: 0 }}
          exit={{ opacity: 0, scale: 0.94, y: 20 }}
          transition={{ duration: 0.35, ease: [0.16, 1, 0.3, 1] }}
          className="light-panel"
          style={{
            width: '100%',
            maxWidth: '850px',
            maxHeight: '90vh',
            overflowY: 'auto',
            padding: '36px',
            borderRadius: '20px',
            background: '#ffffff',
            color: '#0f172a',
            border: '1px solid #e2e8f0',
            boxShadow: '0 25px 50px -12px rgba(0, 0, 0, 0.25)'
          }}
        >
          
          {/* Action Header */}
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', borderBottom: '1px solid #e2e8f0', paddingBottom: '18px', marginBottom: '24px' }}>
            <div>
              <span style={{ fontSize: '0.72rem', fontWeight: 800, color: '#0284c7', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
                MUNICIPAL DECISION REPORT
              </span>
              <h2 style={{ fontSize: '1.45rem', fontWeight: 800, color: '#0f172a', margin: '2px 0 0 0' }}>
                Hyperlocal Urban Cooling & Air Quality Intervention Assessment
              </h2>
            </div>

            <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
              <button
                onClick={handlePrint}
                style={{
                  padding: '9px 18px',
                  borderRadius: '9px',
                  border: 'none',
                  background: '#0284c7',
                  color: '#ffffff',
                  fontSize: '0.82rem',
                  fontWeight: 700,
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '6px',
                  boxShadow: '0 4px 12px rgba(2, 132, 199, 0.25)'
                }}
              >
                <Printer size={15} /> Print / Save PDF
              </button>
              <button
                onClick={onClose}
                style={{ background: '#f1f5f9', border: 'none', borderRadius: '50%', padding: '9px', cursor: 'pointer', color: '#64748b' }}
              >
                <X size={18} />
              </button>
            </div>
          </div>

          {/* Executive Summary Metrics Box */}
          <div style={{ background: '#f8fafc', padding: '20px', borderRadius: '14px', border: '1px solid #e2e8f0', marginBottom: '24px' }}>
            <h3 style={{ fontSize: '1.0rem', fontWeight: 800, color: '#0f172a', marginBottom: '14px' }}>
              1. Executive Scenario Impact Summary
            </h3>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr 1fr', gap: '14px' }}>
              <div style={{ padding: '14px', background: '#ffffff', borderRadius: '10px', border: '1px solid #e2e8f0' }}>
                <span style={{ fontSize: '0.7rem', color: '#64748b', fontWeight: 600, display: 'block' }}>Avg Surface Cooling</span>
                <strong style={{ fontSize: '1.4rem', color: '#16a34a', fontWeight: 800 }}>-{summary.avgTempDrop}°C</strong>
              </div>

              <div style={{ padding: '14px', background: '#ffffff', borderRadius: '10px', border: '1px solid #e2e8f0' }}>
                <span style={{ fontSize: '0.7rem', color: '#64748b', fontWeight: 600, display: 'block' }}>Avg PM2.5 AQI Drop</span>
                <strong style={{ fontSize: '1.4rem', color: '#0284c7', fontWeight: 800 }}>-{summary.avgAQIDrop} pts</strong>
              </div>

              <div style={{ padding: '14px', background: '#ffffff', borderRadius: '10px', border: '1px solid #e2e8f0' }}>
                <span style={{ fontSize: '0.7rem', color: '#64748b', fontWeight: 600, display: 'block' }}>Total Equity Score</span>
                <strong style={{ fontSize: '1.4rem', color: '#d97706', fontWeight: 800 }}>{summary.totalEquityBenefitScore.toLocaleString()}</strong>
              </div>
            </div>
          </div>

          {/* Applied Intervention Parameters */}
          <div style={{ marginBottom: '24px' }}>
            <h3 style={{ fontSize: '1.0rem', fontWeight: 800, color: '#0f172a', marginBottom: '12px' }}>
              2. Modeled Intervention Parameters
            </h3>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr 1fr', gap: '12px', fontSize: '0.8rem' }}>
              <div style={{ padding: '12px', background: '#f0fdf4', borderRadius: '10px', border: '1px solid #bbf7d0' }}>
                <span style={{ color: '#64748b' }}>Tree Canopy:</span> <strong style={{ color: '#16a34a', fontWeight: 800 }}>+{scenario.treeCanopyAdd}%</strong>
              </div>
              <div style={{ padding: '12px', background: '#f0f9ff', borderRadius: '10px', border: '1px solid #bae6fd' }}>
                <span style={{ color: '#64748b' }}>Cool Roofs:</span> <strong style={{ color: '#0284c7', fontWeight: 800 }}>+{scenario.coolRoofAdd}%</strong>
              </div>
              <div style={{ padding: '12px', background: '#faf5ff', borderRadius: '10px', border: '1px solid #e9d5ff' }}>
                <span style={{ color: '#64748b' }}>Shade Canopies:</span> <strong style={{ color: '#9333ea', fontWeight: 800 }}>+{scenario.shadeAdd}%</strong>
              </div>
              <div style={{ padding: '12px', background: '#fffbeb', borderRadius: '10px', border: '1px solid #fde68a' }}>
                <span style={{ color: '#64748b' }}>Traffic Reroute:</span> <strong style={{ color: '#d97706', fontWeight: 800 }}>-{scenario.trafficReduce}%</strong>
              </div>
            </div>
          </div>

          {/* Top Priority Action Matrix Table */}
          <div style={{ marginBottom: '24px' }}>
            <h3 style={{ fontSize: '1.0rem', fontWeight: 800, color: '#0f172a', marginBottom: '12px' }}>
              3. Top Recommended Street Blocks for Immediate Budget Allocation
            </h3>

            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.8rem' }}>
              <thead>
                <tr style={{ background: '#f1f5f9', color: '#475569', textAlign: 'left', borderBottom: '2px solid #e2e8f0' }}>
                  <th style={{ padding: '12px' }}>Rank</th>
                  <th style={{ padding: '12px' }}>Street Block Name</th>
                  <th style={{ padding: '12px' }}>Vulnerability Category</th>
                  <th style={{ padding: '12px' }}>Cooling ΔT</th>
                  <th style={{ padding: '12px' }}>AQI Δ</th>
                  <th style={{ padding: '12px' }}>Equity Score</th>
                </tr>
              </thead>
              <tbody>
                {rankedPriorityCells.map((c, i) => (
                  <tr key={c.id} style={{ borderBottom: '1px solid #e2e8f0', background: i % 2 === 0 ? '#f8fafc' : '#ffffff' }}>
                    <td style={{ padding: '12px', fontWeight: 800, color: '#0284c7' }}>#{i+1}</td>
                    <td style={{ padding: '12px', fontWeight: 700, color: '#0f172a' }}>{c.streetName}</td>
                    <td style={{ padding: '12px', color: '#9333ea', fontWeight: 600 }}>{c.vulnerabilityType}</td>
                    <td style={{ padding: '12px', color: '#16a34a', fontWeight: 800 }}>-{c.tempDelta}°C</td>
                    <td style={{ padding: '12px', color: '#0284c7', fontWeight: 800 }}>-{c.aqiDelta} AQI</td>
                    <td style={{ padding: '12px', color: '#d97706', fontWeight: 800 }}>{c.benefitScore}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Methodology Footer */}
          <div style={{ background: '#f8fafc', padding: '16px', borderRadius: '10px', border: '1px dashed #cbd5e1', fontSize: '0.75rem', color: '#64748b' }}>
            <strong style={{ color: '#0f172a', display: 'block', marginBottom: '4px' }}>
              Methodology & Calibration (SOAIDEATHON-S18 Standard):
            </strong>
            Land Surface Temperature (LST) derived from Landsat-9 TIRS and Sentinel-2 NDVI. Air quality PM2.5 baseline calibrated against CPCB regulatory CAAQMS stations. Microclimate cooling effect sizes computed using peer-reviewed urban energy balance equations ($0.16^\circ\text{C}$ cooling per 10% canopy increase; $0.28^\circ\text{C}$ surface reduction per 10% cool roof albedo). 95% confidence bounds account for spatial kriging decay from regulatory ground monitors.
          </div>

        </motion.div>
      </div>
    </AnimatePresence>
  );
};
