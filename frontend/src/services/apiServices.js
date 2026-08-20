// Master Live API Services & Data Fetcher (SIH / Hackathon Standard)
// Connects and verifies status for all 11 configured APIs from .env
//
// HONESTY POLICY (final audit): only Open-Meteo is actually called at
// runtime (keyless, real request). The other connectors are placeholders:
// they report whether a key is configured, and never claim to be "Active"
// without making a real request. No status shown here is fabricated.

const PILOT_LAT = 20.2520;
const PILOT_LNG = 85.7880;

/**
 * 1. Open-Meteo Live Weather & Forecast API (Zero Key Required)
 */
export const fetchLiveOpenMeteoWeather = async () => {
  try {
    const url = `https://api.open-meteo.com/v1/forecast?latitude=${PILOT_LAT}&longitude=${PILOT_LNG}&current=temperature_2m,relative_humidity_2m,surface_pressure,wind_speed_10m,direct_normal_irradiance&hourly=temperature_2m,relative_humidity_2m,precipitation,pm2_5&forecast_days=1`;
    const res = await fetch(url);
    if (!res.ok) throw new Error("OpenMeteo endpoint error");
    const data = await res.json();
    return {
      success: true,
      source: "Open-Meteo Live API",
      temperature: data.current.temperature_2m,
      humidity: data.current.relative_humidity_2m,
      windSpeed: data.current.wind_speed_10m,
      solarIrradiance: data.current.direct_normal_irradiance,
      pressure: data.current.surface_pressure,
      // Real hourly forecast series (next 24 h) for the analytics charts
      hourly: {
        time: (data.hourly?.time || []).slice(0, 24),
        temperature: (data.hourly?.temperature_2m || []).slice(0, 24),
        humidity: (data.hourly?.relative_humidity_2m || []).slice(0, 24),
        precipitation: (data.hourly?.precipitation || []).slice(0, 24),
        pm25: (data.hourly?.pm2_5 || []).slice(0, 24)
      },
      status: "Active (Keyless)"
    };
  } catch (err) {
    return { success: false, status: "Offline (Fallback Active)", error: err.message };
  }
};

/**
 * Placeholder connectors. None of these performs a real network call in the
 * current build, so they report their true configuration state instead of a
 * fabricated "Active" status.
 */
const placeholder = (source, key, keyLabel) => ({
  success: false,
  source,
  status: key ? `Key configured (live call not implemented)` : `${keyLabel} not configured`,
  active: false,
  note: "Demo connector - no live request is made by this build"
});

/**
 * 2. NASA POWER Climatology REST API
 */
export const fetchNasaPowerData = async (apiKey = null) =>
  placeholder("NASA POWER Climatology", apiKey, "VITE_NASA_POWER_API_KEY");

/**
 * 3. OpenAQ Ground Station PM2.5 REST API
 */
export const fetchOpenAQData = async (apiKey = null) =>
  placeholder("OpenAQ CAAQMS Feed", apiKey, "VITE_OPENAQ_API_KEY");

/**
 * 4. OpenWeather Live API
 */
export const fetchOpenWeatherData = async (apiKey) =>
  placeholder("OpenWeather Live API", apiKey, "VITE_OPENWEATHER_API_KEY");

/**
 * 5. TomTom Traffic Flow API
 */
export const fetchTomTomTrafficData = async (apiKey) =>
  placeholder("TomTom Traffic Flow API", apiKey, "VITE_TOMTOM_TRAFFIC_API_KEY");

/**
 * 6. HERE Traffic & Routing API
 */
export const fetchHereTrafficData = async (apiKey) =>
  placeholder("HERE Mobility & Incident API", apiKey, "VITE_HERE_TRAFFIC_API_KEY");

/**
 * 7. ISRO Bhuvan GIS Layer API
 */
export const fetchIsroBhuvanData = async (apiKey) =>
  placeholder("ISRO Bhuvan WMS Satellite Layer", apiKey, "VITE_ISRO_BHUVAN_API_KEY");

/**
 * 8. Data.gov.in Administrative Census API
 */
export const fetchDataGovInCensus = async (apiKey) =>
  placeholder("Data.gov.in Administrative Census", apiKey, "VITE_DATA_GOV_IN_API_KEY");

/**
 * 9. NASA Earthdata & Copernicus Data Space Ecosystem Connectors
 */
export const fetchSatelliteMetadata = async (earthdataToken, copernicusKey) =>
  placeholder(
    "NASA Earthdata / Copernicus Data Space",
    earthdataToken || copernicusKey,
    "VITE_NASA_EARTHDATA_TOKEN / VITE_COPERNICUS_DATASPACE_KEY"
  );

/**
 * 10. Cesium 3D Terrain & Building Extrusions Connector
 */
export const fetchCesium3DStatus = async (accessToken) =>
  placeholder("Cesium Ion 3D Engine", accessToken, "VITE_CESIUM_ACCESS_TOKEN");

/**
 * Master Verification Function: audits all 11 APIs configured in .env
 */
export const auditAllAPIConnections = async (envVars) => {
  const openMeteo = await fetchLiveOpenMeteoWeather();
  const nasaPower = await fetchNasaPowerData(envVars.VITE_NASA_POWER_API_KEY);
  const openaq = await fetchOpenAQData(envVars.VITE_OPENAQ_API_KEY);
  const openweather = await fetchOpenWeatherData(envVars.VITE_OPENWEATHER_API_KEY);
  const tomtom = await fetchTomTomTrafficData(envVars.VITE_TOMTOM_TRAFFIC_API_KEY);
  const hereTraffic = await fetchHereTrafficData(envVars.VITE_HERE_TRAFFIC_API_KEY);
  const isroBhuvan = await fetchIsroBhuvanData(envVars.VITE_ISRO_BHUVAN_API_KEY);
  const dataGovIn = await fetchDataGovInCensus(envVars.VITE_DATA_GOV_IN_API_KEY);
  const satellite = await fetchSatelliteMetadata(envVars.VITE_NASA_EARTHDATA_TOKEN, envVars.VITE_COPERNICUS_DATASPACE_KEY);
  const cesium = await fetchCesium3DStatus(envVars.VITE_CESIUM_ACCESS_TOKEN);

  return [
    { name: "Open-Meteo Weather API", type: "Weather & Forecast", status: openMeteo.status, active: openMeteo.success },
    { name: "OpenAQ CAAQMS Feed", type: "Air Quality PM2.5", status: openaq.status, active: openaq.success },
    { name: "NASA POWER Climatology", type: "Solar Radiation & Temp", status: nasaPower.status, active: nasaPower.success },
    { name: "OpenWeather API", type: "Live Meteorological Stream", status: openweather.status, active: openweather.success },
    { name: "TomTom Traffic API", type: "Mobility & Road Speed", status: tomtom.status, active: tomtom.success },
    { name: "HERE Developer API", type: "Traffic Incidents & Routing", status: hereTraffic.status, active: hereTraffic.success },
    { name: "ISRO Bhuvan GIS", type: "Indian Satellite WMS Layers", status: isroBhuvan.status, active: isroBhuvan.success },
    { name: "Data.gov.in API", type: "Government Census Data", status: dataGovIn.status, active: dataGovIn.success },
    { name: "NASA Earthdata", type: "Landsat-9 Thermal LST", status: satellite.status, active: satellite.success },
    { name: "Copernicus Data Space", type: "Sentinel-2 NDVI / Sentinel-5P", status: satellite.status, active: satellite.success },
    { name: "Cesium Ion 3D", type: "3D Terrain & Building Mesh", status: cesium.status, active: cesium.success }
  ];
};
