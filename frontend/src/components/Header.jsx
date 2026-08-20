import React, { useState, useEffect, useRef } from 'react';
import { Sun, Moon, HelpCircle, Bell, User, CloudSun, Bot, ShieldAlert, Activity, UserCheck, Eye, HeartPulse, ThermometerSun } from 'lucide-react';

// Compact professional header: brand logo (theme-aware), live weather,
// system status, theme, help, notifications and profile.
// The logo switches between light.jpeg (light theme) and dark.jpeg (dark
// theme) — one HeatSync logo, correct aspect ratio, never distorted.
export const Header = ({
  theme,
  setTheme,
  liveWeatherData,
  onOpenSystemStatus,
  onOpenHelp,
  monitoring,
  modelInfo,
  aiStatus,
  setUserRole
}) => {
  const [openPop, setOpenPop] = useState(null); // 'notif' | 'profile'
  const notifRef = useRef(null);
  const profileRef = useRef(null);

  useEffect(() => {
    const onDocClick = (e) => {
      const inNotif = notifRef.current && notifRef.current.contains(e.target);
      const inProfile = profileRef.current && profileRef.current.contains(e.target);
      if (!inNotif && !inProfile) setOpenPop(null);
    };
    document.addEventListener('mousedown', onDocClick);
    return () => document.removeEventListener('mousedown', onDocClick);
  }, []);

  const backendOk = monitoring?.backend_reachable !== false;
  const modelOk = modelInfo?.available === true;
  const aiConfigured = aiStatus?.status === 'configured';
  const weatherOk = Boolean(liveWeatherData);
  const missingDatasets = monitoring?.summary?.unavailable ?? 0;

  // Distinguish live weather from model-derived heat.
  // liveWeatherData comes from /api/system/weather (OpenWeather live probe).
  // model-derived heat comes from /api/city/intelligence (XGBoost full-grid prediction).


  const alerts = [
    { id: 'backend', icon: Activity, color: backendOk ? '#16a34a' : '#dc2626', title: backendOk ? 'Backend online' : 'Backend offline', text: backendOk ? 'Monitoring report received' : 'Using local OSM fallback layers' },
    { id: 'model', icon: Bot, color: modelOk ? '#16a34a' : '#d97706', title: modelOk ? 'XGBoost model ready' : 'Model unavailable', text: modelOk ? 'Predictions enabled' : 'Trained artifact (models/best_model.pkl) missing' },
    { id: 'ai', icon: ShieldAlert, color: aiConfigured ? '#16a34a' : '#d97706', title: aiConfigured ? 'Nemotron configured' : 'AI: Configuration required', text: aiConfigured ? 'Assistant ready' : 'Set NEMOTRON_API_KEY on the backend' },
    { id: 'weather', icon: CloudSun, color: weatherOk ? '#16a34a' : '#d97706', title: weatherOk ? 'Live weather connected' : 'Weather offline', text: weatherOk ? `${liveWeatherData.temperature}°C · OpenWeather (live air temperature — not LST)` : 'OpenWeather API unreachable' },
    { id: 'heat-source', icon: ThermometerSun, color: '#dc2626', title: 'Heat source', text: liveWeatherData ? 'Live air temperature (OpenWeather)' : 'Model-derived predicted LST (XGBoost full-grid)' }
  ];
  if (missingDatasets > 0) {
    alerts.push({ id: 'datasets', icon: HeartPulse, color: '#d97706', title: `${missingDatasets} datasets unavailable`, text: 'Run the gis-engine pipeline to produce them' });
  }

  const notifCount = alerts.filter((a) => a.color !== '#16a34a').length;
  const logo = theme === 'dark' ? '/logo-dark.jpeg' : '/logo-light.jpeg';

  return (
    <header className="app-header">
      <div className="header-inner">
        {/* Brand — one theme-aware HeatSync logo */}
        <div className="header-brand">
          <img
            src={logo}
            alt="HeatSync logo"
            className="header-logo-img"
            width="40"
            height="40"
          />
          <div className="header-title">
            <h1>HeatSync</h1>
            <p>Hyperlocal Urban Heat &amp; Air Quality Digital Twin</p>
          </div>
          <span className="header-badge">OSM · GIS · XGBoost</span>
        </div>

        {/* Right actions */}
        <div className="header-right">
<span className="header-chip weather-chip" title="Live OpenWeather observation">
              <span className="chip-dot" />
              {liveWeatherData ? `Live: ${liveWeatherData.temperature}°C · OpenWeather` : 'Weather: checking…'}
          </span>

          <button
            className="header-icon-btn sys-btn"
            onClick={onOpenSystemStatus}
            title="System health — backend, model, GIS, live data, AI"
          >
            <HeartPulse size={16} />
            <span className="sys-btn-label">System</span>
          </button>

          <button
            className="header-icon-btn"
            onClick={() => setTheme((prev) => (prev === 'light' ? 'dark' : 'light'))}
            title="Toggle theme"
            aria-label="Toggle theme"
          >
            {theme === 'light' ? <Sun size={17} /> : <Moon size={17} />}
          </button>

          <button className="header-icon-btn" onClick={onOpenHelp} title="Help" aria-label="Help">
            <HelpCircle size={17} />
          </button>

          <div style={{ position: 'relative' }} ref={notifRef}>
            <button
              className="header-icon-btn"
              onClick={() => setOpenPop((p) => (p === 'notif' ? null : 'notif'))}
              title="Notifications"
              aria-label="Notifications"
            >
              <Bell size={17} />
              {notifCount > 0 && <span className="notif-dot" />}
            </button>
            {openPop === 'notif' && (
              <div className="header-pop">
                <div style={{ padding: '8px 10px', fontSize: '0.66rem', fontWeight: 800, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                  System Alerts
                </div>
                {alerts.map((a) => {
                  const Icon = a.icon;
                  return (
                    <div className="pop-item" key={a.id}>
                      <span className="pop-icon" style={{ background: `${a.color}1a`, color: a.color }}>
                        <Icon size={15} />
                      </span>
                      <div>
                        <strong>{a.title}</strong>
                        <span>{a.text}</span>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          <div style={{ position: 'relative' }} ref={profileRef}>
            <button
              className="header-icon-btn"
              onClick={() => setOpenPop((p) => (p === 'profile' ? null : 'profile'))}
              title="Profile / role"
              aria-label="Profile"
            >
              <User size={17} />
            </button>
            {openPop === 'profile' && (
              <div className="header-pop header-pop-sm">
                <div style={{ padding: '8px 10px', fontSize: '0.66rem', fontWeight: 800, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                  Working as
                </div>
                <div className="pop-item" onClick={() => { setUserRole('planner'); setOpenPop(null); }}>
                  <span className="pop-icon" style={{ background: 'rgba(2, 132, 199, 0.12)', color: 'var(--primary-sky)' }}>
                    <UserCheck size={15} />
                  </span>
                  <div><strong>Planner</strong><span>Simulator & priority tools</span></div>
                </div>
                <div className="pop-item" onClick={() => { setUserRole('citizen'); setOpenPop(null); }}>
                  <span className="pop-icon" style={{ background: 'rgba(147, 51, 234, 0.12)', color: '#9333ea' }}>
                    <Eye size={15} />
                  </span>
                  <div><strong>Citizen</strong><span>Health guidance view</span></div>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </header>
  );
};

export default Header;
