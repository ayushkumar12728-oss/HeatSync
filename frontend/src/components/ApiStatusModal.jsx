import React from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { X, CheckCircle2, Database } from 'lucide-react';

export const ApiStatusModal = ({
  onClose,
  apiList
}) => {
  return (
    <AnimatePresence>
      <div style={{
        position: 'fixed',
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        background: 'rgba(15, 23, 42, 0.6)',
        backdropFilter: 'blur(10px)',
        zIndex: 3500,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '20px'
      }}>
        <motion.div
          initial={{ opacity: 0, scale: 0.93, y: 20 }}
          animate={{ opacity: 1, scale: 1, y: 0 }}
          exit={{ opacity: 0, scale: 0.93, y: 20 }}
          className="theme-panel card-3d"
          style={{
            width: '100%',
            maxWidth: '720px',
            maxHeight: '85vh',
            overflowY: 'auto',
            padding: '28px',
            borderRadius: '18px',
            background: 'var(--bg-surface)'
          }}
        >
          
          {/* Header */}
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', borderBottom: '1px solid var(--border-light)', paddingBottom: '14px', marginBottom: '20px' }}>
            <div>
              <span style={{ fontSize: '0.72rem', fontWeight: 800, color: 'var(--primary-sky)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
                SIH MASTER API AUDIT & STATUS
              </span>
              <h2 style={{ fontSize: '1.35rem', fontWeight: 800, color: 'var(--text-main)', margin: '2px 0 0 0', display: 'flex', alignItems: 'center', gap: '8px' }}>
                <Database size={20} color="var(--primary-sky)" />
                API Pipeline ({apiList.filter(a => a.active).length} / {apiList.length} Active)
              </h2>
            </div>
            <button
              onClick={onClose}
              style={{ background: 'var(--bg-subtle)', border: 'none', borderRadius: '50%', padding: '8px', cursor: 'pointer', color: 'var(--text-secondary)' }}
            >
              <X size={18} />
            </button>
          </div>

          {/* Intro Notice */}
          <div style={{ background: 'var(--primary-sky-light)', padding: '12px 16px', borderRadius: '10px', border: '1px solid var(--border-light)', fontSize: '0.78rem', color: 'var(--text-main)', marginBottom: '18px' }}>
            <strong style={{ color: 'var(--primary-sky)', display: 'block', marginBottom: '2px' }}>
              Multi-Source Data Fusion Engine:
            </strong>
            Only Open-Meteo is queried live (keyless). The remaining connectors report their true configuration state — a status is never claimed without a real request.
          </div>

          {/* API Grid Table */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px' }}>
            {apiList.map((api, idx) => (
              <div
                key={idx}
                style={{
                  padding: '12px 14px',
                  background: 'var(--bg-subtle)',
                  borderRadius: '10px',
                  border: '1px solid var(--border-light)',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between'
                }}
              >
                <div>
                  <strong style={{ fontSize: '0.84rem', color: 'var(--text-main)', display: 'block' }}>
                    {api.name}
                  </strong>
                  <span style={{ fontSize: '0.7rem', color: 'var(--text-secondary)' }}>
                    {api.type}
                  </span>
                </div>

                <div style={{ display: 'flex', alignItems: 'center', gap: '5px', fontSize: '0.72rem', fontWeight: 700, color: api.active ? '#16a34a' : '#d97706', background: api.active ? 'rgba(22, 163, 74, 0.12)' : 'rgba(217, 119, 6, 0.12)', padding: '4px 8px', borderRadius: '8px', border: `1px solid ${api.active ? 'rgba(22, 163, 74, 0.3)' : 'rgba(217, 119, 6, 0.3)'}` }}>
                  <CheckCircle2 size={13} />
                  {api.status}
                </div>
              </div>
            ))}
          </div>

        </motion.div>
      </div>
    </AnimatePresence>
  );
};
