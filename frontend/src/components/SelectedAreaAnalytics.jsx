import React from 'react';
import { MousePointerClick, ThermometerSun, Gauge, Leaf, Building2, Trees, ShieldAlert } from 'lucide-react';
import { computeRiskData } from '../services/riskData';

// Horizontal analytics card immediately below the 3D map.
// All values come from real data (OSM-derived stats from the map click,
// live weather, backend availability). Missing values are shown as N/A.
export const SelectedAreaAnalytics = ({ location, availability = {}, environmentSummary, liveWeather }) => {
  const osm = location?.stats;
  const lat = location?.lat;
  const lng = location?.lng;

  const riskData = computeRiskData({ environmentSummary, liveWeather, availability, areaOsm: osm });
  const overall = riskData.find((r) => r.name === 'Overall Urban Risk');

  const greenHa = osm?.greenAreaM2 ? Math.round((osm.greenAreaM2 / 10000) * 10) / 10 : null;
  const waterHa = osm?.waterAreaM2 ? Math.round((osm.waterAreaM2 / 10000) * 10) / 10 : null;

  const cards = [
    {
      key: 'lst', label: 'LST', icon: ThermometerSun, color: '#dc2626',
      value: availability?.lst ? '—' : 'N/A',
      meta: availability?.lst ? 'Landsat (30 m)' : 'GIS pipeline · unavailable'
    },
    {
      key: 'pm25', label: 'PM2.5', icon: Gauge, color: '#d97706',
      value: availability?.aqi ? '—' : 'N/A',
      meta: availability?.aqi ? 'CPCB/OpenAQ' : 'GIS pipeline · unavailable'
    },
    {
      key: 'ndvi', label: 'NDVI', icon: Leaf, color: '#16a34a',
      value: availability?.ndvi ? '—' : 'N/A',
      meta: availability?.ndvi ? 'Sentinel-2' : 'GIS pipeline · unavailable'
    },
    {
      key: 'buildings', label: 'Buildings', icon: Building2, color: '#2563eb',
      value: osm?.buildings != null ? osm.buildings.toLocaleString() : 'N/A',
      meta: osm ? `OSM within ${osm.radiusM ?? 150} m (real)` : 'Click a map feature'
    },
    {
      key: 'green', label: 'Green Area', icon: Trees, color: '#16a34a',
      value: greenHa != null ? `${greenHa} ha` : 'N/A',
      meta: osm ? 'OSM green/natural (real)' : 'Click a map feature'
    },
    {
      key: 'water', label: 'Water', icon: Trees, color: '#0ea5e9',
      value: waterHa != null ? `${waterHa} ha` : osm?.waterAreaM2 === 0 ? 'None nearby' : 'N/A',
      meta: osm ? 'OSM water (real)' : 'Click a map feature'
    },
    {
      key: 'risk', label: 'Risk Level', icon: ShieldAlert, color: '#b91c1c',
      value: overall?.level || 'N/A',
      meta: overall?.basis || 'Composite of live + OSM indicators'
    }
  ];

  if (!location) {
    return (
      <div className="area-analytics">
        <div className="area-analytics-head">
          <strong><MousePointerClick size={15} color="var(--primary-sky)" /> Selected Area Analytics</strong>
          <span>Click on map to select an area</span>
        </div>
        <div className="area-analytics-empty">
          <MousePointerClick size={18} />
          Click any building, road, green space or water body on the 3D map to
          compute real OSM-derived statistics for that location.
        </div>
      </div>
    );
  }

  return (
    <div className="area-analytics">
      <div className="area-analytics-head">
        <strong><MousePointerClick size={15} color="var(--primary-sky)" /> Selected Area Analytics</strong>
        <span>
          {location.name || 'Selected point'} · {Number(lat).toFixed(5)}° N, {Number(lng).toFixed(5)}° E
        </span>
      </div>
      <div className="aa-cards">
        {cards.map((card) => {
          const Icon = card.icon;
          const isNa = card.value === 'N/A';
          return (
            <div className="aa-card" key={card.key} title={card.meta}>
              <span className="aa-label"><Icon size={12} color={card.color} /> {card.label}</span>
              <span className="aa-value" style={{ color: isNa ? 'var(--text-muted)' : card.key === 'risk' ? (card.value === 'High' ? '#dc2626' : card.value === 'Moderate' ? '#d97706' : 'var(--text-main)') : 'var(--text-main)' }}>
                {isNa ? <span className="na">N/A</span> : card.value}
              </span>
              <span className="aa-meta">{card.meta}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
};

export default SelectedAreaAnalytics;
