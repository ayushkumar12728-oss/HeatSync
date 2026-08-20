import React from 'react';
import { Building2, Route, Trees, Waves, ThermometerSun, Droplets, Wind, MapPin, Flame, Leaf, Gauge, AlertTriangle } from 'lucide-react';

// KPI cards. Every value is either:
//   - real, derived from OSM layer files or the live OpenWeather API, or
//   - explicitly "Data unavailable" when the GIS pipeline has not produced it.
export const KpiCards = ({ environmentSummary, liveWeather, availability }) => {
  const stats = environmentSummary?.stats;
  const derived = environmentSummary?.derived || {};

  const cards = [
    {
      key: 'buildings',
      label: 'Buildings',
      value: stats?.buildings?.count?.toLocaleString() ?? null,
      unit: 'features',
      icon: Building2,
      color: '#2563eb',
      date: 'OSM (real)',
      note: 'Real OSM building footprints in the 3D city'
    },
    {
      key: 'roads',
      label: 'Road Network',
      value: stats?.roads?.length_km?.toLocaleString() ?? null,
      unit: 'km',
      icon: Route,
      color: '#f97316',
      date: 'OSM (real)',
      note: 'Real OSM road centreline length'
    },
    {
      key: 'green',
      label: 'Green Cover (OSM)',
      value: derived?.green_cover_pct ?? null,
      unit: '%',
      icon: Trees,
      color: '#16a34a',
      date: 'OSM (real)',
      note: 'OSM green + natural area vs boundary area (approximate)'
    },
    {
      key: 'water',
      label: 'Water Area',
      value: stats?.water?.area_km2?.toLocaleString() ?? null,
      unit: 'km²',
      icon: Waves,
      color: '#0ea5e9',
      date: 'OSM (real)',
      note: 'Real OSM water polygons (approximate area)'
    },
    {
      key: 'temp',
      label: 'Temperature',
      value: liveWeather?.temperature != null ? `${liveWeather.temperature}°C` : null,
      unit: '',
      icon: ThermometerSun,
      color: '#dc2626',
      date: liveWeather ? 'LIVE (OpenWeather)' : null,
      note: 'Real current observation for Bhubaneswar (OpenWeather API)'
    },
    {
      key: 'humidity',
      label: 'Humidity',
      value: liveWeather?.humidity != null ? `${liveWeather.humidity}%` : null,
      unit: '',
      icon: Droplets,
      color: '#0284c7',
      date: liveWeather ? 'LIVE (OpenWeather)' : null,
      note: 'Real current relative humidity (OpenWeather API)'
    },
    {
      key: 'wind',
      label: 'Wind Speed',
      value: liveWeather?.windSpeed != null ? `${liveWeather.windSpeed} km/h` : null,
      unit: '',
      icon: Wind,
      color: '#7c3aed',
      date: liveWeather ? 'LIVE (OpenWeather)' : null,
      note: 'Real current wind speed (OpenWeather API)'
    },
    {
      key: 'area',
      label: 'Study Area',
      value: environmentSummary?.boundary_area_km2?.toLocaleString() ?? null,
      unit: 'km²',
      icon: MapPin,
      color: '#64748b',
      date: 'boundary.geojson',
      note: 'Real Bhubaneswar study-area boundary'
    },
    {
      key: 'lst',
      label: 'Avg LST',
      value: null,
      unit: '°C',
      icon: Flame,
      color: '#dc2626',
      unavailable: !(availability?.lst ?? false),
      note: availability?.lst ? 'Satellite-derived (Landsat)' : 'Data unavailable - run gis-engine pipeline (Landsat LST)'
    },
    {
      key: 'ndvi',
      label: 'Avg NDVI',
      value: null,
      unit: 'index',
      icon: Leaf,
      color: '#16a34a',
      unavailable: !(availability?.ndvi ?? false),
      note: availability?.ndvi ? 'Satellite-derived (Sentinel-2)' : 'Data unavailable - run gis-engine pipeline (Sentinel-2 NDVI)'
    },
    {
      key: 'aqi',
      label: 'Avg AQI',
      value: null,
      unit: 'index',
      icon: Gauge,
      color: '#d97706',
      unavailable: !(availability?.aqi ?? false),
      note: availability?.aqi ? 'Station-interpolated AQI' : 'Data unavailable - run gis-engine pipeline (AQI)'
    },
    {
      key: 'risk',
      label: 'High-Risk Area',
      value: null,
      unit: '%',
      icon: AlertTriangle,
      color: '#b91c1c',
      unavailable: true,
      note: 'Requires heat-class raster (Landsat LST) - unavailable'
    }
  ];

  return (
    <div className="kpi-grid">
      {cards.map((card) => {
        const Icon = card.icon;
        const isUnavailable = card.unavailable || card.value === null;
        return (
          <div className="kpi-card theme-panel" key={card.key} title={card.note}>
            <div className="kpi-icon" style={{ background: `${card.color}1a`, color: card.color }}>
              <Icon size={16} />
            </div>
            <div className="kpi-body">
              <span className="kpi-label">{card.label}</span>
              {isUnavailable ? (
                <span className="kpi-unavailable">N/A</span>
              ) : (
                <span className="kpi-value" style={{ color: card.color }}>
                  {card.value}
                  {card.unit && <small> {card.unit}</small>}
                </span>
              )}
              <span className="kpi-note">{isUnavailable && card.unavailable ? card.note : card.note}</span>
            </div>
          </div>
        );
      })}
    </div>
  );
};

export default KpiCards;
