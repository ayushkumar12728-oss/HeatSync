# HeatSync — Hyperlocal Urban Heat & Air-Quality Digital Twin

[![SIH / SOAIDEATHON-S18](https://img.shields.io/badge/Track-Clean%20%26%20Green%20Technology-10b981.svg)](https://github.com/ayushkumar12728-oss/HeatSync)
[![License-MIT](https://img.shields.io/badge/License-MIT-0284c7.svg)](../LICENSE)
[![React](https://img.shields.io/badge/Frontend-React%2018%20%2B%20Vite-0284c7.svg)](https://react.dev/)
[![Leaflet](https://img.shields.io/badge/GIS-Leaflet%20%2B%20Carto%20Voyager-16a34a.svg)](https://leafletjs.com/)
[![Chart.js](https://img.shields.io/badge/Analytics-Chart.js%20%2B%20React%20Chartjs%202-ff6384.svg)](https://www.chartjs.org/)

**HeatSync** is an interactive, full-stack **Hyperlocal Urban Heat and Air-Quality Digital Twin & Microclimate Simulator** ($25\text{m} - 100\text{m}$ grid resolution). Built for Smart India Hackathon (SIH / SOAIDEATHON-S18) under the **Clean & Green Technology** track, HeatSync enables municipal urban planners, public health officers, and campus facilities teams to model microclimatic heat islands, quantify baseline exposure, simulate "what-if" cooling interventions (tree canopy, cool roofs, shade structures, traffic rerouting), rank interventions by **Demographic Equity Score**, view interactive **Chart.js Analytics (Pie, Bar, Line, Radar graphs)**, and compute **95% Kriging Uncertainty Bounds** per grid cell.

---

> **Monorepo note:** HeatSync is the frontend of the `urban-digital-twin`
> monorepo — it lives in `frontend/` and talks to the FastAPI backend in
> `backend/` (see the root `README.md`).

## 📍 Pilot Zone: Khandagiri & ITER Campus, Bhubaneswar, Odisha

- **Bounding Region**: Lat `20.2420° N` to `20.2620° N`, Long `85.7760° E` to `85.8000° E` (~196 spatial grid cells at 100m resolution).
- **Core Microclimate Sectors**:
  - **ITER Campus Academic Corridor**: High student density, medium building shade, cool roof conversion potentials.
  - **Khandagiri & Udayagiri Hills**: Forested canopy reserve ($< 34^\circ\text{C}$ LST).
  - **Khandagiri Square & NH-16 Junction**: High asphalt concrete heat island ($> 41^\circ\text{C}$ LST), heavy transit outdoor worker exposure.
  - **SUM Hospital Corridor**: High vulnerability sensitive receptor zone.

---

## ✨ Key Features

1. **Hyperlocal 100m Grid Raster Mesh**:
   - Fuses satellite Land Surface Temperature (LST) from Landsat-9 TIRS and Sentinel-2 NDVI with CPCB CAAQMS regulatory air quality monitors.
   - Calculates **Demographic Vulnerability Index (0–100)** combining population density, outdoor worker concentration, informal settlement presence, and sensitive receptors (hospitals/schools).

2. **"What-If" Physics-Informed Microclimate Simulator**:
   - **Tree Canopy Cover (+0 to 50%)**: Microclimate cooling ($0.16^\circ\text{C}$ drop per 10% canopy) & PM2.5 absorption.
   - **Cool Reflective Roofs (+0 to 70%)**: Surface albedo reduction ($0.28^\circ\text{C}$ cooling per 10% conversion).
   - **Shade Canopies (+0 to 40%)**: Solar radiation pedestrian relief.
   - **Traffic Rerouting (-0 to 80%)**: Localized PM2.5 / AQI reduction (up to -85 points).
   - **Preset Quick Scenarios**: *Canopy Corridor*, *Cool Roof Blitz*, *Clean Air Zone*, and *Max Package*.

3. **Interactive Chart.js Analytics Dashboard**:
   - **LST Temperature Distribution (Pie Chart)**: Categorizes cool zones, moderate zones, and extreme heat islands.
   - **PM2.5 Air Quality Exposure (Doughnut Chart)**: Visualizes clean, moderate, and severe AQI exposure.
   - **Baseline vs. Simulated Impact (Bar Graph)**: Comparative bars for average LST, peak heat, PM2.5 AQI, and vulnerability.
   - **24-Hour Diurnal Thermal Cycle (Line Graph)**: 24-hour heat curve comparing baseline vs simulated cooling.
   - **Multi-Lever Intervention Coverage (Radar Chart)**: 5-axis polar coverage tracker.

4. **Vulnerability-Weighted Priority Action Matrix**:
   - Ranks top street blocks by **Equity Benefit-to-Cost Score**:
     $$\text{Benefit Score} = \text{Cooling ROI} \times \left(1 + \frac{\text{VulnerabilityScore}}{35}\right)$$

5. **Kriging Uncertainty Bounds & Confidence Overlay**:
   - Computes empirical 95% confidence intervals $[T_{\text{lower}}, T_{\text{upper}}]$ per cell based on distance decay from regulatory ground stations.

6. **Split-Screen Before/After Comparison Mode**:
   - Synchronized side-by-side maps displaying baseline current thermal state vs. live post-intervention simulated state with real-time temperature drop ($\Delta T$) highlights.

7. **Executive Municipal Decision Report Generator**:
   - Print-ready and downloadable PDF summary for city officials detailing modeled scenario parameters, population shielded, and top priority street allocations.

8. **Dynamic Dark & Light Theme Switcher with 3D Styles**:
   - One-click theme toggle switching between Pristine Light Mode (Carto Voyager GIS tiles) and Sleek Dark Mode (Carto Dark Matter GIS tiles).
   - Interactive 3D Card Tilt Effects (`card-3d`) and ambient background lighting orbs.

10. **API Integration & Audit Engine**:
   - Live Open-Meteo REST weather telemetry integrated into header (`Live Open-Meteo: 31.4°C`).
   - One-click API Audit Modal reporting the true connection state of all 11 configured APIs in `.env` (NASA Earthdata, Copernicus, OpenAQ, OpenWeather, NASA POWER, TomTom, HERE, Mapbox, ISRO Bhuvan, Data.gov.in, Cesium). Only Open-Meteo is queried live; the other connectors report their real configuration state — a status is never claimed without a real request.

---

## 🛠️ Technology Stack

| Layer | Technologies |
|---|---|
| **Frontend Framework** | React 18, Vite 8 |
| **Analytics & Charts** | Chart.js 4, React-Chartjs-2 |
| **GIS & Mapping** | Leaflet JS, React-Leaflet, Carto Voyager & Carto Dark Matter Tiles |
| **Styling & Theme** | Vanilla CSS, Light/Dark Root Variables, Google Fonts (Outfit & Inter) |
| **Animations & 3D** | Framer Motion, Canvas Confetti, 3D Perspective Card Tilts |
| **Icons & UI** | Lucide React |
| **Spatial Engine** | Turf.js / Custom Kriging & Physics Microclimate Matrix |

---

## 🚀 Quick Start Guide

### Prerequisites
- Node.js `v18.0.0` or higher
- npm `v9.0.0` or higher

### Installation

1. **Clone the repository**:
   ```bash
   # The frontend lives in the monorepo at urban-digital-twin/frontend/
   cd urban-digital-twin/frontend
   ```

2. **Install dependencies**:
   ```bash
   npm install
   ```

3. **Set up Environment Variables**:
   Copy `.env.example` to `.env`:
   ```bash
   cp .env.example .env
   ```

4. **Start the Vite Frontend Dashboard**:
   ```bash
   npm run dev
   ```
   Open `http://localhost:5173/` in your browser.

5. **Build for Production**:
   ```bash
   npm run build
   ```

---

## 📁 Project Structure

```
frontend/
├── src/
│   ├── components/
│   │   ├── Header.jsx                 # Top bar with live counters, theme toggle & API status
│   │   ├── LayerControl.jsx           # GIS layer switcher (LST, AQI, Vuln, Uncertainty)
│   │   ├── DigitalTwinMap.jsx         # Interactive Leaflet 3D GIS map & resizer
│   │   ├── SimulationPanel.jsx        # 4-lever intervention sliders & presets
│   │   ├── PriorityMatrix.jsx         # Equity-ranked priority action matrix
│   │   ├── ComparisonView.jsx         # Synchronized split-screen before/after map
│   │   ├── AnalyticsCharts.jsx        # Chart.js analytics dashboard (Pie, Bar, Line, Radar)
│   │   ├── CellDetailsModal.jsx       # Grid cell spatial diagnostics modal
│   │   ├── ReportModal.jsx            # Printable municipal decision report
│   │   └── ApiStatusModal.jsx         # Audit modal for all 11 API connections
│   ├── data/
│   │   └── pilotDataset.js            # Authentic pilot dataset for Khandagiri & ITER Campus
│   ├── engine/
│   │   └── simulationEngine.js        # Physics-informed microclimate equations & uncertainty
│   ├── services/
│   │   └── apiServices.js            # Master API connectors & audit module
│   ├── App.jsx                        # Main state, theme & layout orchestrator
│   ├── index.css                      # Light/Dark theme variables, 3D card tilt & animations
│   └── main.jsx                       # React entry point
├── .env                               # Environment variables (ignored by Git)
├── .env.example                       # Environment variables template
├── .gitignore                         # Git ignore rules (includes WORKFLOW.md, EXPLANATION_GUIDE.md, .env)
├── EXPLANATION_GUIDE.md               # Detailed private explanation & SIH user guide (ignored by Git)
├── WORKFLOW.md                        # Internal development & deployment workflow (ignored by Git)
├── index.html                         # App root HTML
├── package.json                       # Dependencies & scripts
└── README.md                          # Project documentation
```

---

## 📜 License

This project is licensed under the MIT License — see the [LICENSE](../LICENSE) file for details. Prepared for **SOAIDEATHON-S18 / SIH — Hyperlocal Urban Heat and Air-Quality Digital Twin for Cooling Intervention Planning**.
