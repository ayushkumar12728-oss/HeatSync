// areaStats.js
// Lightweight client-side geometry helpers used to derive REAL statistics from
// the OSM layer GeoJSON already loaded into the 3D map (buildings, roads,
// green, water, trees) for the selected-area panel. All values are computed
// from actual data; results are labelled "approximate".

const EARTH_RADIUS_M = 6_371_000;
const REF_LAT = (20.26 * Math.PI) / 180;
const M_PER_DEG_LAT = (Math.PI * EARTH_RADIUS_M) / 180;
const M_PER_DEG_LNG = M_PER_DEG_LAT * Math.cos(REF_LAT);

const TREE_NATURAL = new Set(['tree', 'tree_row', 'wood', 'scrub']);

function haversineM(lat1, lng1, lat2, lng2) {
  const a = Math.sin(((lat2 - lat1) * Math.PI / 180) / 2) ** 2
    + Math.cos((lat1 * Math.PI) / 180) * Math.cos((lat2 * Math.PI) / 180)
    * Math.sin(((lng2 - lng1) * Math.PI / 180) / 2) ** 2;
  return 2 * EARTH_RADIUS_M * Math.asin(Math.min(1, Math.sqrt(a)));
}

function iterCoords(geometry) {
  const coords = [];
  const walk = (value) => {
    if (Array.isArray(value) && value.length >= 2
        && typeof value[0] === 'number' && typeof value[1] === 'number') {
      coords.push([value[0], value[1]]);
      return;
    }
    if (Array.isArray(value)) value.forEach(walk);
  };
  if (geometry) walk(geometry.coordinates);
  return coords;
}

function featureCentroid(feature) {
  const coords = iterCoords(feature.geometry);
  if (coords.length === 0) return null;
  const lng = coords.reduce((a, c) => a + c[0], 0) / coords.length;
  const lat = coords.reduce((a, c) => a + c[1], 0) / coords.length;
  return { lng, lat };
}

function withinRadius(centroid, lng, lat, radiusM) {
  if (!centroid) return false;
  return haversineM(lat, lng, centroid.lat, centroid.lng) <= radiusM;
}

function polygonAreaM2(coords) {
  if (coords.length < 4) return 0;
  let area = 0;
  for (let i = 0; i < coords.length - 1; i += 1) {
    const [lng1, lat1] = coords[i];
    const [lng2, lat2] = coords[i + 1];
    area += (lng2 - lng1) * (lat2 + lat1);
  }
  return (Math.abs(area) / 2) * M_PER_DEG_LNG * M_PER_DEG_LAT;
}

function lineLengthWithinM(coords, lng, lat, radiusM) {
  let total = 0;
  for (let i = 0; i < coords.length - 1; i += 1) {
    const [lng1, lat1] = coords[i];
    const [lng2, lat2] = coords[i + 1];
    const d1 = haversineM(lat, lng, lat1, lng1);
    const d2 = haversineM(lat, lng, lat2, lng2);
    if (d1 <= radiusM || d2 <= radiusM) {
      total += haversineM(lat1, lng1, lat2, lng2);
    }
  }
  return total;
}

// Compute real OSM-derived statistics within `radiusM` of (lng, lat).
// `collections` maps layer key -> GeoJSON FeatureCollection (already loaded).
export function computeAreaStats(collections, lng, lat, radiusM = 150) {
  const stats = {
    radiusM,
    buildings: 0,
    roadLengthM: 0,
    greenCount: 0,
    greenAreaM2: 0,
    waterCount: 0,
    waterAreaM2: 0,
    trees: 0
  };

  const countPolygons = (collection, key) => {
    (collection?.features || []).forEach((feature) => {
      const centroid = featureCentroid(feature);
      if (!withinRadius(centroid, lng, lat, radiusM)) return;
      const props = feature.properties || {};
      const natural = String(props.natural || '').toLowerCase();
      if (key === 'green') {
        stats.greenCount += 1;
        stats.greenAreaM2 += polygonAreaM2(iterCoords(feature.geometry));
        if (TREE_NATURAL.has(natural)) stats.trees += 1;
      } else if (key === 'water') {
        stats.waterCount += 1;
        stats.waterAreaM2 += polygonAreaM2(iterCoords(feature.geometry));
      }
    });
  };

  (collections.buildings?.features || []).forEach((feature) => {
    const centroid = featureCentroid(feature);
    if (withinRadius(centroid, lng, lat, radiusM)) stats.buildings += 1;
  });

  (collections.roads?.features || []).forEach((feature) => {
    stats.roadLengthM += lineLengthWithinM(iterCoords(feature.geometry), lng, lat, radiusM);
  });

  countPolygons(collections.green, 'green');
  countPolygons(collections.natural, 'green'); // natural wood/tree/scrub counts as green
  countPolygons(collections.water, 'water');

  stats.buildings = Math.round(stats.buildings);
  stats.roadLengthM = Math.round(stats.roadLengthM * 10) / 10;
  stats.greenAreaM2 = Math.round(stats.greenAreaM2);
  stats.waterAreaM2 = Math.round(stats.waterAreaM2);
  stats.trees = Math.round(stats.trees);
  return stats;
}

export function featureDisplayName(feature) {
  const props = feature?.properties || {};
  const keys = ['name', 'building', 'highway', 'leisure', 'natural', 'water'];
  for (const key of keys) {
    const value = props[key];
    if (value !== undefined && value !== null && String(value).trim()) {
      return key === 'name' ? value : `${key}: ${value}`;
    }
  }
  return 'Selected area';
}

export default computeAreaStats;
