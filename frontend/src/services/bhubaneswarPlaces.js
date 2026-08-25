/**
 * Comprehensive Bhubaneswar Locations, Corridors & Study Area Constants
 */

export const BHUBANESWAR_CENTER = [20.2961, 85.8245];
export const DEFAULT_ZOOM = 13;

export const BHUBANESWAR_PLACES = [
  {
    id: "iter_khandagiri",
    name: "ITER Campus (Khandagiri)",
    category: "Campus / Education",
    lat: 20.2520,
    lng: 85.7950,
    zone: "West Zone",
    description: "Siksha 'O' Anusandhan university engineering campus, Khandagiri"
  },
  {
    id: "master_canteen",
    name: "Master Canteen Station",
    category: "Transit / Central",
    lat: 20.2644,
    lng: 85.8427,
    zone: "Central Zone",
    description: "Bhubaneswar Railway Station square and major transit junction"
  },
  {
    id: "kiit_patia",
    name: "KIIT University (Patia)",
    category: "Campus / Education",
    lat: 20.3540,
    lng: 85.8188,
    zone: "North Zone",
    description: "KIIT / KISS university district, North Bhubaneswar"
  },
  {
    id: "saheed_nagar",
    name: "Saheed Nagar Commercial Hub",
    category: "Commercial",
    lat: 20.2882,
    lng: 85.8468,
    zone: "Central Zone",
    description: "Dense commercial and retail zone along Janpath"
  },
  {
    id: "jayadev_vihar",
    name: "Jayadev Vihar Overbridge",
    category: "Transit / Commercial",
    lat: 20.3015,
    lng: 85.8251,
    zone: "Central Zone",
    description: "Major flyover intersection connecting NH16 and Nandankanan Rd"
  },
  {
    id: "nayapalli",
    name: "Nayapalli / IRC Village",
    category: "Residential / Commercial",
    lat: 20.2942,
    lng: 85.8118,
    zone: "Central Zone",
    description: "ISKON temple corridor and high-density residential area"
  },
  {
    id: "aiims_bhubaneswar",
    name: "AIIMS Bhubaneswar (Sijua)",
    category: "Healthcare",
    lat: 20.2312,
    lng: 85.7766,
    zone: "South-West Zone",
    description: "All India Institute of Medical Sciences campus"
  },
  {
    id: "lingaraj_temple",
    name: "Lingaraj Temple (Old Town)",
    category: "Heritage",
    lat: 20.2382,
    lng: 85.8336,
    zone: "South Zone",
    description: "11th-century monument and traditional dense historic core"
  },
  {
    id: "infocity_patia",
    name: "Infocity / TCS / Infosys",
    category: "IT Hub",
    lat: 20.3588,
    lng: 85.8078,
    zone: "North Zone",
    description: "Silicon corridor and technology park"
  },
  {
    id: "chandrasekharpur",
    name: "Chandrasekharpur (CSPur)",
    category: "Residential",
    lat: 20.3275,
    lng: 85.8196,
    zone: "North Zone",
    description: "Planned residential sector with tree-lined avenues"
  },
  {
    id: "khandagiri_caves",
    name: "Khandagiri & Udayagiri Caves",
    category: "Heritage / Green",
    lat: 20.2588,
    lng: 85.7876,
    zone: "West Zone",
    description: "Ancient rock-cut caves with forested hill slopes"
  },
  {
    id: "rasulgarh_square",
    name: "Rasulgarh Intersection",
    category: "Transit / Industrial",
    lat: 20.2980,
    lng: 85.8640,
    zone: "East Zone",
    description: "High traffic corridor towards Cuttack"
  },
  {
    id: "biju_patnaik_park",
    name: "Biju Patnaik Park (Forest Park)",
    category: "Park / Canopy",
    lat: 20.2678,
    lng: 85.8272,
    zone: "Central Zone",
    description: "Major urban cooling sink with mature broadleaf forest canopy"
  },
  {
    id: "ekamra_kanan",
    name: "Ekamra Kanan Botanical Gardens",
    category: "Park / Botanical",
    lat: 20.3065,
    lng: 85.8038,
    zone: "West-Central Zone",
    description: "Large 500-acre botanical garden and lake buffer"
  }
];

export const COOLING_CORRIDORS = [
  {
    id: "biju_patnaik_greenway",
    name: "Via Biju Patnaik Park Greenway",
    description: "Dense mature sal & neem canopy with microclimate temperature reduction of ~5.8°C",
    canopyCoverPct: 72,
    uvIndex: "Moderate (4.1)",
    avgLST: 33.8
  },
  {
    id: "ekamra_kanan_trail",
    name: "Via Ekamra Kanan Lake Buffer",
    description: "Waterbody breeze corridor combined with botanical tree buffers",
    canopyCoverPct: 78,
    uvIndex: "Low (3.2)",
    avgLST: 32.5
  },
  {
    id: "chandrasekharpur_avenue",
    name: "Via CSPur Tree Boulevard",
    description: "Double-row street tree shading along the north-south arterial",
    canopyCoverPct: 65,
    uvIndex: "Moderate (4.8)",
    avgLST: 34.2
  },
  {
    id: "khandagiri_hill_greenbelt",
    name: "Via Khandagiri Reserved Forest Edge",
    description: "Hilly elevation buffer with natural breeze flow and reduced thermal inertia",
    canopyCoverPct: 80,
    uvIndex: "Low (3.5)",
    avgLST: 32.9
  }
];

export const BHUBANESWAR_ZONES = [
  { id: "all", name: "Whole Bhubaneswar Study Area", cells: 53802 },
  { id: "north", name: "North Zone (Patia / CSPur / Infocity)", cells: 14200 },
  { id: "central", name: "Central Zone (Saheed Nagar / Unit-1 / Janpath)", cells: 16450 },
  { id: "south", name: "South Zone (Old Town / Lingaraj / Sundarpada)", cells: 11800 },
  { id: "west", name: "West Zone (Khandagiri / ITER / Ghatikia)", cells: 11352 }
];
