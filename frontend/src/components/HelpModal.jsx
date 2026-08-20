import React from 'react';
import { X, Flame, Layers, BarChart3, Bot, FileText } from 'lucide-react';

export const HelpModal = ({ onClose }) => {
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-card" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <div>
            <span className="kicker">HeatSync · Bhubaneswar 3D Digital Twin</span>
            <h2>Help — Urban Digital Twin command center</h2>
          </div>
          <button className="modal-close" onClick={onClose} aria-label="Close help">
            <X size={17} />
          </button>
        </div>

        <div className="help-section">
          <h4><Flame size={13} style={{ verticalAlign: '-2px' }} /> 3D Map</h4>
          <p>
            The map is the centerpiece. Drag to pan, scroll to zoom, right-click
            drag to tilt. Click any building, road, green space or water body to
            compute real OSM-derived statistics for the area (shown in the
            Selected Area Analytics bar below the map).
          </p>
        </div>

        <div className="help-section">
          <h4><Layers size={13} style={{ verticalAlign: '-2px' }} /> Map Layers</h4>
          <p>
            The right panel controls every layer: OSM city geometry (buildings,
            roads, green, water, trees) plus thematic GIS layers (NDVI, LST,
            terrain, air quality) when the backend reports them. Each layer has
            an opacity slider and its own legend. Layers the pipeline has not
            produced yet are shown as <em>Unavailable</em>.
          </p>
        </div>

        <div className="help-section">
          <h4><BarChart3 size={13} style={{ verticalAlign: '-2px' }} /> Analytics &amp; Scenarios</h4>
          <p>
            <strong>Analytics</strong> distinguishes <em>REAL DATA</em> (OSM +
            live OpenWeather) from clearly-labelled <em>PILOT / SIMULATION</em>{' '}
            grids. <strong>AI Scenario</strong> runs the trained XGBoost model
            through the scenario engine and shows CURRENT / SCENARIO /
            DIFFERENCE per grid cell on the map.
          </p>
        </div>

        <div className="help-section">
          <h4><Bot size={13} style={{ verticalAlign: '-2px' }} /> Urban AI Assistant</h4>
          <p>
            Nemotron explains real project data only. The API key stays on the
            backend (<code>NEMOTRON_API_KEY</code>). When it is not configured
            the panel reports <em>Configuration Required</em> — it never shows
            fake answers.
          </p>
        </div>

        <div className="help-section">
          <h4><FileText size={13} style={{ verticalAlign: '-2px' }} /> Export Report</h4>
          <p>
            Use the <strong>Export Report</strong> button in the navigation bar
            to open the municipal decision report and print / save it as PDF.
          </p>
        </div>

        <div className="help-section">
          <h4>Data integrity</h4>
          <p>
            Every number on this dashboard comes from the backend API, live
            OpenWeather, or the real OSM layers bundled with the frontend.
            Unavailable datasets are shown as N/A — nothing is fabricated.
          </p>
        </div>
      </div>
    </div>
  );
};

export default HelpModal;
