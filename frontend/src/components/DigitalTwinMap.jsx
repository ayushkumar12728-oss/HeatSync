import React, { useEffect } from 'react';
import { MapContainer, TileLayer, Rectangle, Marker, Popup, Tooltip, LayerGroup, Polygon, useMap } from 'react-leaflet';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import { PILOT_METADATA } from '../data/pilotDataset';
import { Flame, Wind, ShieldAlert, AlertTriangle, Sparkles, MapPin } from 'lucide-react';

// Fix default Leaflet icon paths
delete L.Icon.Default.prototype._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl: 'https://unpkg.com/leaflet@1.7.1/dist/images/marker-icon-2x.png',
  iconUrl: 'https://unpkg.com/leaflet@1.7.1/dist/images/marker-icon.png',
  shadowUrl: 'https://unpkg.com/leaflet@1.7.1/dist/images/marker-shadow.png',
});

// Sample OSM Building & Amenity Polygons in Khandagiri / ITER Campus
const OSM_BUILDING_FOOTPRINTS = [
  {
    id: "osm-bldg-1",
    name: "ITER Campus Main Academic Block A",
    type: "Educational Geometry",
    coords: [
      [20.2520, 85.7885], [20.2530, 85.7885], [20.2530, 85.7900], [20.2520, 85.7900]
    ]
  },
  {
    id: "osm-bldg-2",
    name: "SUM Hospital Medical Complex",
    type: "Healthcare Amenity",
    coords: [
      [20.2505, 85.7935], [20.2520, 85.7935], [20.2520, 85.7950], [20.2505, 85.7950]
    ]
  },
  {
    id: "osm-bldg-3",
    name: "Khandagiri Square Commercial Complex",
    type: "Commercial Footprint",
    coords: [
      [20.2570, 85.7870], [20.2585, 85.7870], [20.2585, 85.7890], [20.2570, 85.7890]
    ]
  },
  {
    id: "osm-bldg-4",
    name: "Baramunda Transport Terminal",
    type: "Transit Amenity",
    coords: [
      [20.2590, 85.7920], [20.2605, 85.7920], [20.2605, 85.7940], [20.2590, 85.7940]
    ]
  }
];

// Map Resizer Helper: Calls map.invalidateSize() to ensure 100% clear rendering
function MapResizer({ theme }) {
  const map = useMap();
  useEffect(() => {
    const timer = setTimeout(() => {
      map.invalidateSize();
    }, 200);
    return () => clearTimeout(timer);
  }, [map, theme]);
  return null;
}

// Color Helpers
const getLSTColor = (lst) => {
  if (lst < 34.0) return '#2563eb'; // Deep Blue
  if (lst < 36.5) return '#059669'; // Emerald
  if (lst < 38.5) return '#d97706'; // Amber
  if (lst < 41.0) return '#dc2626'; // Red
  return '#9333ea';                 // Purple
};

const getAQIColor = (aqi) => {
  if (aqi < 100) return '#16a34a';  // Good
  if (aqi < 200) return '#ca8a04';  // Moderate
  if (aqi < 280) return '#ea580c';  // Poor
  if (aqi < 350) return '#dc2626';  // Very Poor
  return '#9333ea';                 // Severe
};

const getVulnerabilityColor = (score) => {
  if (score < 40) return '#0284c7'; // Low risk
  if (score < 70) return '#d97706'; // Moderate risk
  return '#b91c1c';                 // High vulnerability
};

const getUncertaintyColor = (score) => {
  if (score < 30) return '#16a34a'; // High confidence
  if (score < 60) return '#d97706'; // Moderate uncertainty
  return '#e11d48';                 // High uncertainty
};

const getDeltaColor = (deltaT) => {
  if (deltaT <= 0) return '#94a3b8';
  if (deltaT < 1.5) return '#0284c7';
  if (deltaT < 3.0) return '#10b981';
  return '#15803d';
};

export const DigitalTwinMap = ({
  gridCells,
  activeLayer,
  showStations,
  showBuildings = true,
  selectedCellIds,
  onCellClick,
  isSimulated,
  theme = 'light'
}) => {
  const center = [20.2520, 85.7880]; // Khandagiri & ITER Campus, Bhubaneswar center
  const zoom = 14;

  // Dynamic Map Tiles URL
  const tileUrl = theme === 'dark'
    ? 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png'
    : 'https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png';

  const getCellFillStyle = (cell) => {
    let color = '#0284c7';
    let fillOpacity = 0.65;

    switch (activeLayer) {
      case 'lst':
        const lstVal = isSimulated ? cell.simulatedLST : cell.baselineLST;
        color = getLSTColor(lstVal);
        fillOpacity = 0.7;
        break;
      case 'aqi':
        const aqiVal = isSimulated ? cell.simulatedAQI : cell.baselineAQI;
        color = getAQIColor(aqiVal);
        fillOpacity = 0.7;
        break;
      case 'vulnerability':
        color = getVulnerabilityColor(cell.vulnerabilityScore);
        fillOpacity = 0.75;
        break;
      case 'uncertainty':
        color = getUncertaintyColor(cell.uncertaintyScore);
        fillOpacity = 0.65;
        break;
      case 'delta':
        color = getDeltaColor(cell.tempDelta);
        fillOpacity = cell.tempDelta > 0 ? 0.8 : 0.15;
        break;
      default:
        color = '#0284c7';
    }

    const isSelected = selectedCellIds && selectedCellIds.includes(cell.id);

    return {
      fillColor: color,
      fillOpacity: fillOpacity,
      color: isSelected ? '#38bdf8' : (cell.uncertaintyScore > 65 ? '#e11d48' : (theme === 'dark' ? 'rgba(255, 255, 255, 0.25)' : 'rgba(15, 23, 42, 0.25)')),
      weight: isSelected ? 3 : 1,
      dashArray: cell.uncertaintyScore > 65 && activeLayer === 'uncertainty' ? '4, 4' : null
    };
  };

  return (
    <div style={{ width: '100%', height: '100%', minHeight: '480px', position: 'relative', borderRadius: '14px', overflow: 'hidden', boxShadow: 'var(--shadow-md)', border: '1px solid var(--border-light)' }}>
      
      <MapContainer
        center={center}
        zoom={zoom}
        style={{ width: '100%', height: '100%', minHeight: '480px' }}
        zoomControl={true}
      >
        <MapResizer theme={theme} />

        {/* Dynamic Theme Map Tile Baseline */}
        <TileLayer
          key={theme}
          attribution='&copy; <a href="https://carto.com/">CARTO</a> & OpenStreetMap'
          url={tileUrl}
          maxZoom={19}
        />

        {/* Spatial Grid Cells */}
        <LayerGroup>
          {gridCells.map((cell) => {
            const style = getCellFillStyle(cell);

            return (
              <Rectangle
                key={cell.id}
                bounds={cell.bounds}
                pathOptions={style}
                eventHandlers={{
                  click: () => onCellClick(cell)
                }}
              >
                <Tooltip sticky>
                  <div style={{ fontSize: '0.78rem', color: 'var(--text-main)' }}>
                    <strong style={{ display: 'block', color: 'var(--primary-sky)', marginBottom: '2px' }}>{cell.streetName}</strong>
                    <div>
                      Temp (LST): <strong>{isSimulated ? cell.simulatedLST : cell.baselineLST}°C</strong>
                      {isSimulated && cell.tempDelta > 0 && (
                        <span style={{ color: '#16a34a', fontWeight: 700, marginLeft: '4px' }}>(-{cell.tempDelta}°C)</span>
                      )}
                    </div>
                    <div>
                      AQI (PM2.5): <strong>{isSimulated ? cell.simulatedAQI : cell.baselineAQI}</strong>
                      {isSimulated && cell.aqiDelta > 0 && (
                        <span style={{ color: '#16a34a', fontWeight: 700, marginLeft: '4px' }}>(-{cell.aqiDelta})</span>
                      )}
                    </div>
                    <div style={{ marginTop: '2px', fontSize: '0.7rem', color: 'var(--text-secondary)' }}>
                      Vulnerability Score: <span style={{ color: '#9333ea', fontWeight: 700 }}>{cell.vulnerabilityScore}/100</span>
                    </div>
                    <div style={{ fontSize: '0.7rem', color: 'var(--text-secondary)' }}>
                      Confidence Score: <span style={{ color: '#16a34a', fontWeight: 700 }}>{100 - cell.uncertaintyScore}%</span>
                    </div>
                  </div>
                </Tooltip>
              </Rectangle>
            );
          })}
        </LayerGroup>

        {/* OSM Building Footprint Vector Overlays */}
        {showBuildings && (
          <LayerGroup>
            {OSM_BUILDING_FOOTPRINTS.map(bldg => (
              <Polygon
                key={bldg.id}
                positions={bldg.coords}
                pathOptions={{
                  fillColor: '#9333ea',
                  fillOpacity: 0.45,
                  color: '#7e22ce',
                  weight: 2,
                  dashArray: '2, 2'
                }}
              >
                <Tooltip sticky>
                  <div style={{ fontSize: '0.75rem', fontWeight: 700, color: '#9333ea' }}>
                    🏢 OSM Polygon: {bldg.name}
                    <span style={{ display: 'block', fontSize: '0.68rem', color: '#64748b', fontWeight: 500 }}>
                      Type: {bldg.type} (Extracted via Overpass API)
                    </span>
                  </div>
                </Tooltip>
              </Polygon>
            ))}
          </LayerGroup>
        )}

        {/* Ground Station Pins */}
        {showStations && PILOT_METADATA.groundStations.map(stn => (
          <Marker key={stn.id} position={[stn.lat, stn.lng]}>
            <Popup>
              <div style={{ padding: '4px', fontSize: '0.8rem', color: 'var(--text-main)' }}>
                <strong style={{ color: 'var(--primary-sky)', display: 'flex', alignItems: 'center', gap: '4px' }}>
                  <MapPin size={14} /> {stn.name}
                </strong>
                <p style={{ margin: '4px 0 0 0', color: 'var(--text-secondary)', fontSize: '0.72rem' }}>
                  Type: {stn.type}
                </p>
                <div style={{ marginTop: '6px', fontSize: '0.75rem', borderTop: '1px solid var(--border-light)', paddingTop: '4px' }}>
                  Status: <span style={{ color: '#d97706', fontWeight: 700 }}>Demo location (live feed not connected)</span>
                </div>
              </div>
            </Popup>
          </Marker>
        ))}

      </MapContainer>

      {/* Floating Theme Map Legend */}
      <div className="theme-panel" style={{
        position: 'absolute',
        bottom: '20px',
        left: '20px',
        zIndex: 999,
        padding: '10px 14px',
        borderRadius: '10px',
        maxWidth: '250px',
        boxShadow: 'var(--shadow-md)'
      }}>
        <div style={{ fontSize: '0.75rem', fontWeight: 700, color: 'var(--text-main)', marginBottom: '6px', display: 'flex', alignItems: 'center', gap: '6px' }}>
          {activeLayer === 'lst' && <Flame size={14} color="#dc2626" />}
          {activeLayer === 'aqi' && <Wind size={14} color="#d97706" />}
          {activeLayer === 'vulnerability' && <ShieldAlert size={14} color="#9333ea" />}
          {activeLayer === 'uncertainty' && <AlertTriangle size={14} color="#0284c7" />}
          {activeLayer === 'delta' && <Sparkles size={14} color="#16a34a" />}
          {activeLayer.toUpperCase()} Scale
        </div>

        {activeLayer === 'lst' && (
          <div>
            <div style={{ height: '8px', borderRadius: '4px', background: 'linear-gradient(to right, #2563eb, #059669, #d97706, #dc2626, #9333ea)', marginBottom: '4px' }} />
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.65rem', color: 'var(--text-secondary)', fontWeight: 600 }}>
              <span>&lt; 34°C (Cool)</span>
              <span>38°C</span>
              <span>&gt; 41°C (Extreme)</span>
            </div>
          </div>
        )}

        {activeLayer === 'aqi' && (
          <div>
            <div style={{ height: '8px', borderRadius: '4px', background: 'linear-gradient(to right, #16a34a, #ca8a04, #ea580c, #dc2626, #9333ea)', marginBottom: '4px' }} />
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.65rem', color: 'var(--text-secondary)', fontWeight: 600 }}>
              <span>100 (Good)</span>
              <span>250</span>
              <span>&gt; 350 (Severe)</span>
            </div>
          </div>
        )}

        {activeLayer === 'vulnerability' && (
          <div>
            <div style={{ height: '8px', borderRadius: '4px', background: 'linear-gradient(to right, #0284c7, #d97706, #b91c1c)', marginBottom: '4px' }} />
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.65rem', color: 'var(--text-secondary)', fontWeight: 600 }}>
              <span>0 (Low Risk)</span>
              <span>50</span>
              <span>100 (High Risk)</span>
            </div>
          </div>
        )}

        {activeLayer === 'uncertainty' && (
          <div>
            <div style={{ height: '8px', borderRadius: '4px', background: 'linear-gradient(to right, #16a34a, #d97706, #e11d48)', marginBottom: '4px' }} />
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.65rem', color: 'var(--text-secondary)', fontWeight: 600 }}>
              <span>High Conf (Near Station)</span>
              <span>Low Conf (Sparse)</span>
            </div>
          </div>
        )}

        {activeLayer === 'delta' && (
          <div>
            <div style={{ height: '8px', borderRadius: '4px', background: 'linear-gradient(to right, #94a3b8, #0284c7, #10b981, #15803d)', marginBottom: '4px' }} />
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.65rem', color: 'var(--text-secondary)', fontWeight: 600 }}>
              <span>0°C Drop</span>
              <span>-2.0°C</span>
              <span>-5.5°C Cooling</span>
            </div>
          </div>
        )}
      </div>

    </div>
  );
};
