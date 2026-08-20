import React from 'react';
import { motion } from 'framer-motion';
import confetti from 'canvas-confetti';
import { Trees, SunMedium, Car, Shield, Play, RotateCcw, Sparkles, Zap, Bot, Target } from 'lucide-react';

export const SimulationPanel = ({
  scenario,
  setScenario,
  onRunSimulation,
  onResetSimulation,
  selectedCellCount,
  onClearSelectedCells,
  liveWeatherData
}) => {
  const handleSliderChange = (field, value) => {
    setScenario(prev => ({
      ...prev,
      [field]: Number(value)
    }));
    onRunSimulation(false); // Manual slider live update
  };

  const applyPreset = (presetType) => {
    switch (presetType) {
      case 'forest':
        setScenario(prev => ({ ...prev, treeCanopyAdd: 30, coolRoofAdd: 10, shadeAdd: 15, trafficReduce: 10 }));
        break;
      case 'coolroof':
        setScenario(prev => ({ ...prev, treeCanopyAdd: 10, coolRoofAdd: 50, shadeAdd: 10, trafficReduce: 0 }));
        break;
      case 'evzone':
        setScenario(prev => ({ ...prev, treeCanopyAdd: 15, coolRoofAdd: 15, shadeAdd: 10, trafficReduce: 60 }));
        break;
      case 'max':
        setScenario(prev => ({ ...prev, treeCanopyAdd: 35, coolRoofAdd: 45, shadeAdd: 25, trafficReduce: 50 }));
        break;
      case 'ai_auto':
        // Dynamic AI recommendation calculated from live OpenWeather weather API telemetry
        const liveTemp = liveWeatherData?.temperature || 31.4;
        const liveSolar = liveWeatherData?.solarIrradiance || 750;
        
        const recTree = liveTemp > 30 ? 35 : 20;
        const recRoof = liveTemp > 30 ? 50 : 30;
        const recShade = liveSolar > 500 ? 30 : 15;
        const recTraffic = 50;

        setScenario(prev => ({
          ...prev,
          treeCanopyAdd: recTree,
          coolRoofAdd: recRoof,
          shadeAdd: recShade,
          trafficReduce: recTraffic
        }));
        break;
      default:
        break;
    }
    onRunSimulation(true);
  };

  const handleRunAndConfetti = () => {
    confetti({
      particleCount: 90,
      spread: 75,
      origin: { y: 0.8 },
      colors: ['#0284c7', '#16a34a', '#38bdf8', '#34d399', '#9333ea']
    });
    onRunSimulation(true); // Lock in scenario & switch to Delta Map
  };

  // Reached Metrics Calculations
  const totalCanopyReached = 18 + scenario.treeCanopyAdd;
  const totalCoolRoofReached = 12 + scenario.coolRoofAdd;
  const totalShadeReached = 10 + scenario.shadeAdd;
  const calculatedTempDrop = Math.min(5.5, (scenario.treeCanopyAdd * 0.08 + scenario.coolRoofAdd * 0.07 + scenario.shadeAdd * 0.03)).toFixed(1);
  const calculatedAQIDrop = Math.round(scenario.trafficReduce * 0.85 + scenario.treeCanopyAdd * 0.4);

  return (
    <motion.div
      initial={{ opacity: 0, x: -20 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ duration: 0.4, ease: [0.16, 1, 0.3, 1] }}
      className="theme-panel"
      style={{
        padding: '20px',
        height: '100%',
        display: 'flex',
        flexDirection: 'column',
        gap: '16px',
        overflowY: 'auto'
      }}
    >
      
      {/* Panel Header */}
      <div style={{ borderBottom: '1px solid var(--border-light)', paddingBottom: '12px' }}>
        <h3 style={{ fontSize: '1.1rem', fontWeight: 800, color: 'var(--text-main)', margin: 0, display: 'flex', alignItems: 'center', gap: '8px' }}>
          <Sparkles size={18} color="var(--primary-sky)" />
          3D Microclimate Simulator
        </h3>
        <p style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', margin: '3px 0 0 0' }}>
          Model cooling interventions before capital investment
        </p>
      </div>

      {/* Target Scope Selection */}
      <div style={{ background: 'var(--bg-subtle)', padding: '10px 14px', borderRadius: '10px', border: '1px solid var(--border-light)' }}>
        <span style={{ fontSize: '0.68rem', fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', display: 'block', marginBottom: '4px' }}>
          Simulated Scope:
        </span>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <span style={{ fontSize: '0.82rem', color: selectedCellCount > 0 ? 'var(--primary-sky)' : 'var(--text-main)', fontWeight: 700 }}>
            {selectedCellCount > 0 ? `${selectedCellCount} Custom Cell(s) Selected` : 'Entire Pilot Zone (~196 Cells)'}
          </span>
          {selectedCellCount > 0 && (
            <button
              onClick={onClearSelectedCells}
              style={{ background: 'transparent', border: 'none', color: '#dc2626', fontSize: '0.72rem', cursor: 'pointer', fontWeight: 600, textDecoration: 'underline' }}
            >
              Clear Selection
            </button>
          )}
        </div>
      </div>

      {/* AI Live Weather Auto-Recommend Preset Button */}
      <motion.button
        whileHover={{ scale: 1.02 }}
        whileTap={{ scale: 0.98 }}
        onClick={() => applyPreset('ai_auto')}
        className="card-3d"
        style={{
          padding: '12px 14px',
          borderRadius: '10px',
          background: 'linear-gradient(135deg, rgba(2, 132, 199, 0.15), rgba(147, 51, 234, 0.15))',
          border: '1px solid rgba(2, 132, 199, 0.35)',
          cursor: 'pointer',
          textAlign: 'left',
          display: 'flex',
          alignItems: 'center',
          gap: '10px'
        }}
      >
        <div style={{ padding: '8px', background: 'var(--primary-sky)', borderRadius: '8px', color: '#ffffff' }}>
          <Bot size={18} />
        </div>
        <div>
          <strong style={{ fontSize: '0.82rem', color: 'var(--primary-sky)', display: 'block' }}>
            AI Auto-Recommend (Live Weather Data)
          </strong>
          <span style={{ fontSize: '0.68rem', color: 'var(--text-secondary)', display: 'block', marginTop: '1px' }}>
            {liveWeatherData ? `Calculated from OpenWeather Live: ${liveWeatherData.temperature}°C` : 'Calculates optimal levers from live weather telemetry'}
          </span>
        </div>
      </motion.button>

      {/* Quick Scenario Presets */}
      <div>
        <span style={{ fontSize: '0.68rem', fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', display: 'block', marginBottom: '8px' }}>
          Quick Scenario Presets:
        </span>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px' }}>
          
          <button
            onClick={() => applyPreset('forest')}
            className="card-3d"
            style={{ padding: '10px', cursor: 'pointer', textAlign: 'left', border: '1px solid rgba(22, 163, 74, 0.3)' }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '0.78rem', fontWeight: 700, color: '#16a34a' }}>
              <Trees size={14} /> Canopy Corridor
            </div>
            <span style={{ fontSize: '0.66rem', color: 'var(--text-secondary)', display: 'block', marginTop: '2px' }}>+30% Trees, +15% Shade</span>
          </button>

          <button
            onClick={() => applyPreset('coolroof')}
            className="card-3d"
            style={{ padding: '10px', cursor: 'pointer', textAlign: 'left', border: '1px solid rgba(2, 132, 199, 0.3)' }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '0.78rem', fontWeight: 700, color: '#0284c7' }}>
              <SunMedium size={14} /> Cool Roof Blitz
            </div>
            <span style={{ fontSize: '0.66rem', color: 'var(--text-secondary)', display: 'block', marginTop: '2px' }}>+50% Reflective Roofs</span>
          </button>

          <button
            onClick={() => applyPreset('evzone')}
            className="card-3d"
            style={{ padding: '10px', cursor: 'pointer', textAlign: 'left', border: '1px solid rgba(217, 119, 6, 0.3)' }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '0.78rem', fontWeight: 700, color: '#d97706' }}>
              <Car size={14} /> Clean Air Zone
            </div>
            <span style={{ fontSize: '0.66rem', color: 'var(--text-secondary)', display: 'block', marginTop: '2px' }}>-60% Traffic Mobility</span>
          </button>

          <button
            onClick={() => applyPreset('max')}
            className="card-3d"
            style={{ padding: '10px', cursor: 'pointer', textAlign: 'left', border: '1px solid rgba(147, 51, 234, 0.3)' }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '0.78rem', fontWeight: 700, color: '#9333ea' }}>
              <Zap size={14} /> Max Package
            </div>
            <span style={{ fontSize: '0.66rem', color: 'var(--text-secondary)', display: 'block', marginTop: '2px' }}>Full Multi-Lever Package</span>
          </button>

        </div>
      </div>

      {/* Reached Target Metrics Live Summary Banner */}
      <div style={{
        background: 'var(--bg-surface)',
        padding: '12px 14px',
        borderRadius: '10px',
        border: '1px solid var(--border-light)',
        boxShadow: 'var(--shadow-sm)'
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '0.75rem', fontWeight: 800, color: 'var(--text-main)', marginBottom: '8px' }}>
          <Target size={15} color="#16a34a" />
          SIMULATION TARGETS REACHED
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', fontSize: '0.74rem' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', color: '#16a34a', fontWeight: 700 }}>
            <span>🌳 Total Tree Canopy Reached:</span>
            <span>{totalCanopyReached}% (Baseline 18% + {scenario.treeCanopyAdd}%)</span>
          </div>

          <div style={{ display: 'flex', justifyContent: 'space-between', color: '#0284c7', fontWeight: 700 }}>
            <span>☀️ Total Cool Roof Albedo Reached:</span>
            <span>{totalCoolRoofReached}% (Baseline 12% + {scenario.coolRoofAdd}%)</span>
          </div>

          <div style={{ display: 'flex', justifyContent: 'space-between', color: '#9333ea', fontWeight: 700 }}>
            <span>🛡️ Total Pedestrian Shade Reached:</span>
            <span>{totalShadeReached}% (Baseline 10% + {scenario.shadeAdd}%)</span>
          </div>

          <div style={{ display: 'flex', justifyContent: 'space-between', color: '#d97706', fontWeight: 700 }}>
            <span>🚗 Traffic Reroute Achieved:</span>
            <span>-{scenario.trafficReduce}% Mobility Reduction</span>
          </div>

          <div style={{ borderTop: '1px dashed var(--border-light)', paddingTop: '6px', marginTop: '2px', display: 'flex', justifyContent: 'space-between', fontSize: '0.78rem', fontWeight: 800 }}>
            <span style={{ color: '#16a34a' }}>❄️ Net Cooling Drop Reached:</span>
            <span style={{ color: '#16a34a' }}>-{calculatedTempDrop}°C Drop</span>
          </div>

          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.78rem', fontWeight: 800 }}>
            <span style={{ color: 'var(--primary-sky)' }}>🍃 Net AQI Cleanup Reached:</span>
            <span style={{ color: 'var(--primary-sky)' }}>-{calculatedAQIDrop} AQI Clean</span>
          </div>
        </div>
      </div>

      {/* Sliders for 4 Primary Intervention Levers */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: '14px', marginTop: '2px' }}>
        
        {/* 1. Tree Canopy Cover */}
        <div style={{ background: 'var(--bg-subtle)', padding: '12px 14px', borderRadius: '10px', border: '1px solid var(--border-light)' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
            <span style={{ fontSize: '0.82rem', fontWeight: 700, color: 'var(--text-main)', display: 'flex', alignItems: 'center', gap: '6px' }}>
              <Trees size={16} color="#16a34a" />
              Tree Canopy Cover
            </span>
            <span style={{ fontSize: '0.88rem', fontWeight: 800, color: '#16a34a' }}>
              +{scenario.treeCanopyAdd}% (Reached {totalCanopyReached}%)
            </span>
          </div>
          <input
            type="range"
            min="0"
            max="50"
            step="5"
            value={scenario.treeCanopyAdd}
            onChange={(e) => handleSliderChange('treeCanopyAdd', e.target.value)}
            style={{ width: '100%' }}
          />
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.66rem', color: 'var(--text-muted)', marginTop: '3px' }}>
            <span>0% (Baseline 18%)</span>
            <span>+25% (43% Total)</span>
            <span>+50% (68% Dense)</span>
          </div>
        </div>

        {/* 2. Cool Roof Conversion */}
        <div style={{ background: 'var(--bg-subtle)', padding: '12px 14px', borderRadius: '10px', border: '1px solid var(--border-light)' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
            <span style={{ fontSize: '0.82rem', fontWeight: 700, color: 'var(--text-main)', display: 'flex', alignItems: 'center', gap: '6px' }}>
              <SunMedium size={16} color="#0284c7" />
              Cool Reflective Roofs
            </span>
            <span style={{ fontSize: '0.88rem', fontWeight: 800, color: '#0284c7' }}>
              +{scenario.coolRoofAdd}% (Reached {totalCoolRoofReached}%)
            </span>
          </div>
          <input
            type="range"
            min="0"
            max="70"
            step="5"
            value={scenario.coolRoofAdd}
            onChange={(e) => handleSliderChange('coolRoofAdd', e.target.value)}
            style={{ width: '100%' }}
          />
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.66rem', color: 'var(--text-muted)', marginTop: '3px' }}>
            <span>0% (Baseline 12%)</span>
            <span>+35% (47% Total)</span>
            <span>+70% (82% Albedo)</span>
          </div>
        </div>

        {/* 3. Shade Canopies */}
        <div style={{ background: 'var(--bg-subtle)', padding: '12px 14px', borderRadius: '10px', border: '1px solid var(--border-light)' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
            <span style={{ fontSize: '0.82rem', fontWeight: 700, color: 'var(--text-main)', display: 'flex', alignItems: 'center', gap: '6px' }}>
              <Shield size={16} color="#9333ea" />
              Shade Structures / Canopies
            </span>
            <span style={{ fontSize: '0.88rem', fontWeight: 800, color: '#9333ea' }}>
              +{scenario.shadeAdd}% (Reached {totalShadeReached}%)
            </span>
          </div>
          <input
            type="range"
            min="0"
            max="40"
            step="5"
            value={scenario.shadeAdd}
            onChange={(e) => handleSliderChange('shadeAdd', e.target.value)}
            style={{ width: '100%' }}
          />
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.66rem', color: 'var(--text-muted)', marginTop: '3px' }}>
            <span>0% (Baseline 10%)</span>
            <span>+20% (30% Total)</span>
            <span>+40% (50% Covered)</span>
          </div>
        </div>

        {/* 4. Traffic Rerouting */}
        <div style={{ background: 'var(--bg-subtle)', padding: '12px 14px', borderRadius: '10px', border: '1px solid var(--border-light)' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
            <span style={{ fontSize: '0.82rem', fontWeight: 700, color: 'var(--text-main)', display: 'flex', alignItems: 'center', gap: '6px' }}>
              <Car size={16} color="#d97706" />
              Traffic Rerouting / EV Zone
            </span>
            <span style={{ fontSize: '0.88rem', fontWeight: 800, color: '#d97706' }}>
              -{scenario.trafficReduce}% Mobility Reduction
            </span>
          </div>
          <input
            type="range"
            min="0"
            max="80"
            step="10"
            value={scenario.trafficReduce}
            onChange={(e) => handleSliderChange('trafficReduce', e.target.value)}
            style={{ width: '100%' }}
          />
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.66rem', color: 'var(--text-muted)', marginTop: '3px' }}>
            <span>0%</span>
            <span>-40% Reroute</span>
            <span>-80% Low Emission</span>
          </div>
        </div>

      </div>

      {/* 3D Elevated Action Buttons */}
      <div style={{ marginTop: 'auto', display: 'flex', flexDirection: 'column', gap: '8px' }}>
        <motion.button
          whileHover={{ scale: 1.03 }}
          whileTap={{ scale: 0.97 }}
          onClick={handleRunAndConfetti}
          className="btn-3d-primary"
          style={{ width: '100%', justifyContent: 'center', padding: '13px' }}
        >
          <Play size={16} fill="#ffffff" />
          Run "What-If" 3D Simulation
        </motion.button>

        <button
          onClick={onResetSimulation}
          style={{
            padding: '8px',
            borderRadius: '8px',
            border: '1px solid var(--border-light)',
            background: 'var(--bg-subtle)',
            color: 'var(--text-secondary)',
            fontSize: '0.75rem',
            fontWeight: 600,
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            gap: '6px'
          }}
        >
          <RotateCcw size={12} />
          Reset Sliders to Baseline
        </button>
      </div>

    </motion.div>
  );
};
