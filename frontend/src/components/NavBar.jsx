import React from 'react';
import { Box, Columns2, BarChart3, Bot, UserCheck, Eye, FileText, RefreshCw } from 'lucide-react';

const PRIMARY_TABS = [
  { key: 'map', label: '3D Map', icon: Box },
  { key: 'comparison', label: 'Split Comparison', icon: Columns2 },
  { key: 'analytics', label: 'Analytics', icon: BarChart3 },
  { key: 'ai-scenario', label: 'AI Scenario', icon: Bot, ai: true }
];

export const NavBar = ({
  activeTab,
  setActiveTab,
  userRole,
  setUserRole,
  onExportReport,
  onResetScenarios,
  isSimulated
}) => {
  return (
    <div className="nav-bar">
      <div className="nav-inner">
        <div className="nav-tabs" role="tablist">
          {PRIMARY_TABS.map((tab) => {
            const Icon = tab.icon;
            return (
              <button
                key={tab.key}
                role="tab"
                aria-selected={activeTab === tab.key}
                className={`nav-tab ${activeTab === tab.key ? 'active' : ''}`}
                onClick={() => setActiveTab(tab.key)}
              >
                <Icon size={15} className={tab.ai ? 'tab-ai' : ''} />
                {tab.label}
              </button>
            );
          })}
        </div>

        <div className="nav-secondary">
          {isSimulated && (
            <button
              className="btn-export"
              onClick={onResetScenarios}
              style={{ background: 'rgba(220, 38, 38, 0.12)', color: '#dc2626', boxShadow: 'none', border: '1px solid rgba(220, 38, 38, 0.3)' }}
              title="Reset pilot simulation to baseline"
            >
              <RefreshCw size={14} />
              Reset
            </button>
          )}

          <div className="role-switch">
            <button
              className={`role-btn ${userRole === 'planner' ? 'active-planner' : ''}`}
              onClick={() => setUserRole('planner')}
            >
              <UserCheck size={13} />
              Planner
            </button>
            <button
              className={`role-btn ${userRole === 'citizen' ? 'active-citizen' : ''}`}
              onClick={() => setUserRole('citizen')}
            >
              <Eye size={13} />
              Citizen
            </button>
          </div>

          <button className="btn-export" onClick={onExportReport} title="Export / print municipal report">
            <FileText size={15} />
            Export Report
          </button>
        </div>
      </div>
    </div>
  );
};

export default NavBar;
