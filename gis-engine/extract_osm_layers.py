#!/usr/bin/env python3
"""
OSM GeoJSON Feature Extractor
==============================
Automatically detects and separates all OpenStreetMap feature categories
from a single GeoJSON file into individual layer files.

Usage:
    python extract_osm_layers.py <input_geojson_path> [output_dir]

Output:
    A "layers/" directory containing one GeoJSON file per feature category.
    Empty layers are skipped automatically.

Example:
    python extract_osm_layers.py bhubaneswar_osm.geojson
    python extract_osm_layers.py my_city.osm.geojson ./output_layers
"""

import sys
import os
import json
import logging
from pathlib import Path
from datetime import datetime

try:
    import geopandas as gpd
    import pandas as pd
except ImportError:
    print("ERROR: Required packages not found. Install them with:")
    print("  pip install geopandas pandas")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Primary OSM tag columns to extract
# ---------------------------------------------------------------------------
# These are the OSM tags that represent meaningful geographic features.
# The script auto-detects which of these are present in the input file.
PRIMARY_OSM_TAGS = [
    "highway",           # roads, paths, footways, bus stops, etc.
    "building",          # buildings of all types
    "amenity",           # schools, hospitals, restaurants, parking, etc.
    "landuse",           # residential, commercial, forest, farmland, etc.
    "natural",           # water, trees, wood, peaks, wetland, etc.
    "waterway",          # rivers, streams, canals, etc.
    "leisure",           # parks, playgrounds, sports, gardens, etc.
    "tourism",           # hotels, museums, attractions, etc.
    "shop",              # retail shops of all types
    "religion",          # temples, churches, mosques, etc.
    "man_made",          # towers, water towers, pipelines, etc.
    "barrier",           # walls, fences, gates, etc.
    "aeroway",           # airports, runways, helipads, etc.
    "sport",             # cricket, football, tennis, golf, etc.
    "healthcare",        # hospitals, clinics, pharmacies, etc.
    "emergency",         # ambulances, defibrillators, hydrants, etc.
    "historic",          # castles, monuments, ruins, etc.
    "military",          # barracks, military bases, etc.
    "craft",             # workshops, breweries, etc.
    "office",            # company, government, NGO offices, etc.
    "social_facility",   # shelters, group homes, etc.
    "power",             # stations, substations, towers, etc.
    "boundary",          # administrative, national park boundaries
    "place",             # cities, towns, villages, suburbs, etc.
    "water",             # water bodies (rivers, lakes, ponds, etc.)
]

# Columns we know are NOT OSM tags
NON_TAG_COLUMNS = {
    "geometry", "id", "element", "osm_id", "osm_type",
    "source", "note", "fixme", "created_by", "description",
}

# ---------------------------------------------------------------------------
# Known OSM tag → human-readable category mapping
# ---------------------------------------------------------------------------
# Keys are the OSM tag columns; values map tag values to output file names.
# Anything not listed here is handled dynamically with auto-generated names.
OSM_TAG_LABELS: dict[str, dict[str, str]] = {
    "highway": {
        "motorway":          "roads_motorway",
        "trunk":             "roads_trunk",
        "primary":           "roads_primary",
        "secondary":         "roads_secondary",
        "tertiary":          "roads_tertiary",
        "residential":       "roads_residential",
        "unclassified":      "roads_unclassified",
        "service":           "roads_service",
        "living_street":     "roads_living_street",
        "pedestrian":        "roads_pedestrian",
        "primary_link":      "roads_primary_link",
        "secondary_link":    "roads_secondary_link",
        "tertiary_link":     "roads_tertiary_link",
        "trunk_link":        "roads_trunk_link",
        "motorway_link":     "roads_motorway_link",
        "footway":           "footways",
        "cycleway":          "cycleways",
        "path":              "paths",
        "track":             "tracks",
        "steps":             "steps",
        "construction":      "roads_construction",
        "raceway":           "roads_raceway",
        "bus_guideway":      "roads_bus_guideway",
        "bus_stop":          "bus_stops",
        "traffic_signals":   "traffic_signals",
        "crossing":          "crossings",
        "motorway_junction": "motorway_junctions",
        "turning_circle":    "turning_circles",
        "mini_roundabout":   "mini_roundabouts",
        "speed_camera":      "speed_cameras",
        "street_lamp":       "street_lamps",
        "traffic_mirror":    "traffic_mirrors",
        "services":          "road_services",
        "passing_place":     "passing_places",
    },
    "building": {
        "yes":               "buildings_generic",
        "house":             "buildings_house",
        "apartments":        "buildings_apartments",
        "detached":          "buildings_detached",
        "terrace":           "buildings_terrace",
        "semidetached_house":"buildings_semidetached",
        "commercial":        "buildings_commercial",
        "industrial":        "buildings_industrial",
        "retail":            "buildings_retail",
        "warehouse":         "buildings_warehouse",
        "hotel":             "buildings_hotel",
        "church":            "buildings_church",
        "cathedral":         "buildings_cathedral",
        "mosque":            "buildings_mosque",
        "temple":            "buildings_temple",
        "synagogue":         "buildings_synagogue",
        "school":            "buildings_school",
        "university":        "buildings_university",
        "college":           "buildings_college",
        "hospital":          "buildings_hospital",
        "clinic":            "buildings_clinic",
        "government":        "buildings_government",
        "civic":             "buildings_civic",
        "public":            "buildings_public",
        "shed":              "buildings_shed",
        "garage":            "buildings_garage",
        "garages":           "buildings_garages",
        "carport":           "buildings_carport",
        "container":         "buildings_container",
        "kiosk":             "buildings_kiosk",
        "roof":              "buildings_roof",
        "hut":               "buildings_hut",
        "barn":              "buildings_barn",
        "farm_auxiliary":     "buildings_farm_auxiliary",
        "stables":           "buildings_stables",
        "greenhouse":        "buildings_greenhouse",
        "tower":             "buildings_tower",
        "bunker":            "buildings_bunker",
        "dormitory":         "buildings_dormitory",
        "fire_station":      "buildings_fire_station",
        "hangar":            "buildings_hangar",
        "healthcare":        "buildings_healthcare",
        "museum":            "buildings_museum",
        "office":            "buildings_office",
        "outbuilding":       "buildings_outbuilding",
        "stadium":           "buildings_stadium",
        "train_station":     "buildings_train_station",
        "transportation":    "buildings_transportation",
    },
    "amenity": {
        "school":            "schools",
        "university":        "universities",
        "college":           "colleges",
        "kindergarten":      "kindergartens",
        "hospital":          "hospitals",
        "clinic":            "clinics",
        "doctors":           "doctors",
        "pharmacy":          "pharmacies",
        "dentist":           "dentists",
        "veterinary":        "veterinaries",
        "police":            "police_stations",
        "fire_station":      "fire_stations",
        "court":             "courts",
        "prison":            "prisons",
        "townhall":          "townhalls",
        "community_centre":  "community_centres",
        "conference_centre": "conference_centres",
        "events_venue":      "events_venues",
        "library":           "libraries",
        "post_office":       "post_offices",
        "bank":              "banks",
        "atm":               "atms",
        "bureau_de_change":  "bureau_de_change",
        "restaurant":        "restaurants",
        "fast_food":         "fast_food",
        "cafe":              "cafes",
        "bar":               "bars",
        "pub":               "pubs",
        "ice_cream":         "ice_cream_shops",
        "food_court":        "food_courts",
        "bbq":               "bbq",
        "drinking_water":    "drinking_water",
        "water_point":       "water_points",
        "parking":           "parking",
        "parking_entrance":  "parking_entrances",
        "parking_space":     "parking_spaces",
        "bicycle_parking":   "bicycle_parking",
        "bicycle_rental":    "bicycle_rental",
        "taxi":              "taxi_stands",
        "fuel":              "fuel_stations",
        "car_wash":          "car_wash",
        "car_rental":        "car_rental",
        "bus_station":       "bus_stations",
        "ferry_terminal":    "ferry_terminals",
        "marketplace":       "markets",
        "fountain":          "fountains",
        "toilets":           "toilets",
        "shower":            "showers",
        "bench":             "benches",
        "shelter":           "shelters",
        "waste_disposal":    "waste_disposal",
        "recycling":         "recycling",
        "telephone":         "telephones",
        "internet_cafe":     "internet_cafes",
        "clock":             "clocks",
        "place_of_worship":  "places_of_worship",
        "grave_yard":        "graveyards",
        "crematorium":       "crematoriums",
        "funeral_hall":      "funeral_halls",
        "monastery":         "monasteries",
        "nursing_home":      "nursing_homes",
        "social_facility":   "social_facilities",
        "childcare":         "childcare",
        "dojo":              "dojos",
        "public_bath":       "public_baths",
        "biergarten":        "biergartens",
        "internet_access":   "internet_access_points",
        "luggage_locker":    "luggage_lockers",
        "car_sharing":       "car_sharing",
        "planetarium":       "planetaria",
        "theatre":           "theatres",
    },
    "landuse": {
        "residential":       "landuse_residential",
        "commercial":        "landuse_commercial",
        "industrial":        "landuse_industrial",
        "retail":            "landuse_retail",
        "agriculture":       "landuse_agriculture",
        "farmland":          "landuse_farmland",
        "farmyard":          "landuse_farmyard",
        "orchard":           "landuse_orchard",
        "vineyard":          "landuse_vineyard",
        "forest":            "forests",
        "grass":             "landuse_grass",
        "meadow":            "landuse_meadow",
        "recreation_ground": "recreation_grounds",
        "cemetery":          "cemeteries",
        "allotments":        "allotments",
        "railway":           "landuse_railway",
        "military":          "landuse_military",
        "quarry":            "quarries",
        "landfill":          "landfills",
        "construction":      "landuse_construction",
        "brownfield":        "landuse_brownfield",
        "garages":           "landuse_garages",
        "depot":             "landuse_depots",
        "port":              "landuse_ports",
        "harbour":           "landuse_harbours",
        "basin":             "landuse_basins",
        "reservoir":         "landuse_reservoirs",
        "education":         "landuse_education",
        "greenfield":        "landuse_greenfield",
        "greenhouse_horticulture": "landuse_greenhouse_horticulture",
        "religious":         "landuse_religious",
    },
    "natural": {
        "water":             "water_bodies",
        "wood":              "natural_wood",
        "tree":              "trees",
        "tree_row":          "tree_rows",
        "scrub":             "scrub",
        "grassland":         "natural_grassland",
        "wetland":           "wetlands",
        "sand":              "sand",
        "rock":              "rocks",
        "cliff":             "cliffs",
        "bare_rock":         "bare_rocks",
        "scree":             "scree",
        "shingle":           "shingle",
        "mud":               "mud",
        "fell":              "fells",
        "tundra":            "tundra",
        "glacier":           "glaciers",
        "volcano":           "volcanoes",
        "spring":            "springs",
        "hot_spring":        "hot_springs",
        "geyser":            "geysers",
        "cave_entrance":     "cave_entrances",
        "dune":              "dunes",
        "cape":              "capes",
        "bay":               "bays",
        "strait":            "straits",
        "reef":              "reefs",
        "coastline":         "coastlines",
        "beach":             "beaches",
        "shoal":             "shoals",
        "saddle":            "saddles",
        "peak":              "peaks",
        "ridge":             "ridges",
        "valley":            "valleys",
        "plateau":           "plateaus",
        "hill":              "hills",
        "mountain_range":    "mountain_ranges",
        "sinkhole":          "sinkholes",
    },
    "waterway": {
        "river":             "rivers",
        "stream":            "streams",
        "canal":             "canals",
        "drain":             "drains",
        "ditch":             "ditches",
        "wadi":              "wadis",
        "rapids":            "rapids",
        "waterfall":         "waterfalls",
        "dam":               "dams",
        "weir":              "weirs",
        "lock":              "locks",
        "dock":              "docks",
        "boatyard":          "boatyards",
        "fish_pass":         "fish_passes",
    },
    "leisure": {
        "park":              "parks",
        "playground":        "playgrounds",
        "garden":            "gardens",
        "nature_reserve":    "nature_reserves",
        "sports_centre":     "sports_centres",
        "stadium":           "stadiums",
        "pitch":             "sports_pitches",
        "swimming_pool":     "swimming_pools",
        "water_park":        "water_parks",
        "ice_rink":          "ice_rinks",
        "fitness_centre":    "fitness_centres",
        "sauna":             "saunas",
        "beach_resort":      "beach_resorts",
        "fishing":           "fishing_spots",
        "marina":            "marinas",
        "slipway":           "slipways",
        "dog_park":          "dog_parks",
        "amusement_ride":    "amusement_rides",
        "bandstand":         "bandstands",
        "common":            "commons",
        "game_feeding":      "game_feedings",
        "hackerspace":       "hackerspaces",
        "maker_space":       "maker_spaces",
        "outdoor_seating":   "outdoor_seating",
        "picnic_table":      "picnic_tables",
        "wildlife_hide":     "wildlife_hides",
        "dive_site":         "dive_sites",
        "observation_tower": "observation_towers",
    },
    "tourism": {
        "hotel":             "hotels",
        "motel":             "motels",
        "hostel":            "hostels",
        "guest_house":       "guest_houses",
        "camp_site":         "camp_sites",
        "caravan_site":      "caravan_sites",
        "museum":            "museums",
        "gallery":           "galleries",
        "attraction":        "attractions",
        "theme_park":        "theme_parks",
        "viewpoint":         "viewpoints",
        "information":       "information_points",
        "artwork":           "artworks",
        "wins":              "wins",
        "picnic_site":       "picnic_sites",
        "wilderness_hut":    "wilderness_huts",
        "chalet":            "chalets",
        "zoo":               "zoos",
        "aquarium":          "aquariums",
        "alpine_hut":        "alpine_huts",
    },
    "shop": {
        "supermarket":        "shops_supermarket",
        "convenience":        "shops_convenience",
        "clothes":            "shops_clothes",
        "shoes":              "shops_shoes",
        "jewellery":          "shops_jewellery",
        "jewelry":            "shops_jewelry",
        "electronics":        "shops_electronics",
        "furniture":          "shops_furniture",
        "diy":                "shops_diy",
        "garden_centre":      "shops_garden_centre",
        "car":                "shops_car",
        "bicycle":            "shops_bicycle",
        "motorcycle":         "shops_motorcycle",
        "hairdresser":        "shops_hairdresser",
        "beauty":             "shops_beauty",
        "chemist":            "shops_chemist",
        "optician":           "shops_optician",
        "bakery":             "shops_bakery",
        "butcher":            "shops_butcher",
        "greengrocer":        "shops_greengrocer",
        "deli":               "shops_deli",
        "dairy":              "shops_dairy",
        "seafood":            "shops_seafood",
        "wine":               "shops_wine",
        "books":              "shops_books",
        "stationery":         "shops_stationery",
        "toys":               "shops_toys",
        "sports":             "shops_sports",
        "outdoor":            "shops_outdoor",
        "kiosk":              "shops_kiosk",
        "mall":               "shops_mall",
        "department_store":   "shops_department_store",
        "general":            "shops_general",
        "gift":               "shops_gift",
        "florist":            "shops_florist",
        "pet":                "shops_pet",
        "computer":           "shops_computer",
        "mobile_phone":       "shops_mobile_phone",
        "photo":              "shops_photo",
        "art":                "shops_art",
        "music":              "shops_music",
        "video":              "shops_video",
        "confectionery":      "shops_confectionery",
        "watches":            "shops_watches",
        "car_repair":         "shops_car_repair",
        "car_parts":          "shops_car_parts",
        "tyres":              "shops_tyres",
        "hardware":           "shops_hardware",
        "laundry":            "shops_laundry",
        "tailor":             "shops_tailor",
        "tattoo":             "shops_tattoo",
        "newsagent":          "shops_newsagent",
        "travel_agency":      "shops_travel_agency",
        "yes":                "shops_generic",
    },
    "religion": {
        "hindu":              "hindu_temples",
        "muslim":             "mosques",
        "christian":          "churches",
        "buddhist":           "buddhist_temples",
        "sikh":               "gurdwaras",
        "jain":               "jain_temples",
        "jewish":             "synagogues",
        "shinto":             "shinto_shrines",
        "taoist":             "taoist_temples",
        "confucian":          "confucian_temples",
        "pagan":              "pagan_sites",
        "zoroastrian":        "zoroastrian_temples",
    },
    "man_made": {
        "tower":              "towers",
        "mast":               "masts",
        "lighthouse":         "lighthouses",
        "windmill":           "windmills",
        "watermill":          "watermills",
        "chimney":            "chimneys",
        "silo":               "silos",
        "storage_tank":       "storage_tanks",
        "pipeline":           "pipelines",
        "bridge":             "man_made_bridges",
        "pier":               "piers",
        "breakwater":         "breakwaters",
        "water_tower":        "water_towers",
        "communications_tower":"communications_towers",
        "obelisk":            "obelisks",
        "quay":               "quays",
        "survey_point":       "survey_points",
    },
    "barrier": {
        "wall":               "walls",
        "fence":              "fences",
        "hedge":              "hedges",
        "guard_rail":         "guard_rails",
        "kerb":               "kerbs",
        "bollard":            "bollards",
        "gate":               "gates",
        "lift_gate":          "lift_gates",
        "swing_gate":         "swing_gates",
        "cycle_barrier":      "cycle_barriers",
        "stile":              "stiles",
        "block":              "barrier_blocks",
        "boulder":            "boulders",
        "jersey_barrier":     "jersey_barriers",
        "city_wall":          "city_walls",
        "retaining_wall":     "retaining_walls",
        "boom_barrier":       "boom_barriers",
        "entrance":           "barrier_entrances",
        "yes":                "barriers_generic",
    },
    "aeroway": {
        "aerodrome":          "aerodromes",
        "helipad":            "helipads",
        "runway":             "runways",
        "taxiway":            "taxiways",
        "apron":              "aprons",
        "hangar":             "hangars",
        "terminal":           "airport_terminals",
        "control_tower":      "control_towers",
        "windsock":           "windsocks",
    },
    "emergency": {
        "ambulance_station":  "ambulance_stations",
        "defibrillator":      "defibrillators",
        "fire_hydrant":       "fire_hydrants",
        "phone":              "emergency_phones",
        "siren":              "emergency_sirens",
    },
    "historic": {
        "castle":             "castles",
        "fort":               "forts",
        "ruins":              "ruins",
        "monument":           "monuments",
        "memorial":           "memorials",
        "arch":               "arches",
        "city_gate":          "city_gates",
        "tower":              "historic_towers",
        "church":             "historic_churches",
        "temple":             "historic_temples",
        "battlefield":        "battlefields",
        "tomb":               "tombs",
        "yes":                "historic_generic",
    },
    "military": {
        "barracks":           "barracks",
        "airfield":           "military_airfields",
        "base":               "military_bases",
    },
    "office": {
        "company":            "offices_company",
        "government":         "government_offices",
        "ngo":                "ngo_offices",
        "educational_institution":"educational_institution_offices",
        "yes":                "offices_generic",
    },
    "social_facility": {
        "shelter":            "social_shelters",
        "group_home":         "group_homes",
        "nursing_home":       "social_nursing_homes",
        "workshop":           "social_workshops",
        "food_bank":          "food_banks",
    },
    "power": {
        "station":            "power_stations",
        "substation":         "power_substations",
        "plant":              "power_plants",
        "generator":          "power_generators",
        "tower":              "power_towers",
        "pole":               "power_poles",
        "line":               "power_lines",
    },
    "boundary": {
        "administrative":     "administrative_boundaries",
        "national_park":      "national_park_boundaries",
        "protected_area":     "protected_area_boundaries",
    },
    "sport": {
        "tennis":             "sports_tennis",
        "basketball":         "sports_basketball",
        "football":           "sports_football",
        "soccer":             "sports_soccer",
        "cricket":            "sports_cricket",
        "baseball":           "sports_baseball",
        "volleyball":         "sports_volleyball",
        "golf":               "sports_golf",
        "swimming":           "sports_swimming",
        "athletics":          "sports_athletics",
        "yoga":               "sports_yoga",
        "gymnastics":         "sports_gymnastics",
    },
    "place": {
        "city":              "places_city",
        "town":              "places_town",
        "village":           "places_village",
        "hamlet":            "places_hamlet",
        "suburb":            "places_suburb",
        "neighbourhood":     "places_neighbourhood",
        "locality":          "places_locality",
        "island":            "places_island",
        "islet":             "places_islet",
        "square":            "places_square",
        "farm":              "places_farm",
        "allotments":        "places_allotments",
        "yes":               "places_generic",
    },
    "water": {
        "river":             "water_river",
        "lake":              "water_lake",
        "pond":              "water_pond",
        "canal":             "water_canal",
        "reservoir":         "water_reservoir",
        "basin":             "water_basin",
        "stream":            "water_stream",
        "ditch":             "water_ditch",
        "lagoon":            "water_lagoon",
        "oxbow":             "water_oxbow",
    },
    "healthcare": {
        "hospital":          "healthcare_hospitals",
        "clinic":            "healthcare_clinics",
        "doctors":           "healthcare_doctors",
        "pharmacy":          "healthcare_pharmacies",
        "dentist":           "healthcare_dentists",
        "laboratory":        "healthcare_laboratories",
        "rehabilitation":    "healthcare_rehabilitation",
        "nursing_home":      "healthcare_nursing_homes",
        "yes":               "healthcare_generic",
    },
}


def _sanitize_filename(name: str) -> str:
    """Make a string safe for use as a filename."""
    return (
        name.lower()
        .replace(" ", "_")
        .replace("/", "_")
        .replace("\\", "_")
        .replace(":", "_")
        .replace("&", "and")
        .replace("'", "")
        .replace('"', "")
        .replace("(", "")
        .replace(")", "")
        .replace("[", "")
        .replace("]", "")
        .replace(",", "")
        .replace(".", "")
        .replace("-", "_")
        .replace("+", "plus")
        .replace("@", "at")
        .replace("#", "hash")
        .replace("%", "pct")
        .replace("=", "eq")
        .replace("?", "")
        .replace("!", "")
        .replace(";", "")
    )


def extract_osm_layers(input_path: str, output_dir: str | None = None):
    """
    Main extraction function.
    Reads an OSM GeoJSON, auto-detects all tag columns, and writes
    one GeoJSON file per feature category into an output directory.
    """
    input_path = Path(input_path)
    if not input_path.exists():
        log.error(f"Input file not found: {input_path}")
        sys.exit(1)

    if output_dir is None:
        output_dir = input_path.parent / "layers"
    else:
        output_dir = Path(output_dir)

    output_dir.mkdir(parents=True, exist_ok=True)
    log.info(f"Input file : {input_path}")
    log.info(f"Output dir : {output_dir}")

    # ------------------------------------------------------------------
    # 1. Load the GeoJSON
    # ------------------------------------------------------------------
    log.info("Loading GeoJSON with GeoPandas...")
    try:
        gdf = gpd.read_file(input_path)
    except Exception as e:
        log.error(f"Failed to read GeoJSON: {e}")
        sys.exit(1)

    log.info(f"Loaded {len(gdf)} features with {len(gdf.columns)} columns.")

    # ------------------------------------------------------------------
    # 2. Print all columns
    # ------------------------------------------------------------------
    all_columns = list(gdf.columns)
    log.info("=" * 60)
    log.info("ALL COLUMNS:")
    log.info("=" * 60)
    for i, col in enumerate(all_columns, 1):
        log.info(f"  {i:3d}. {col}")

    # ------------------------------------------------------------------
    # 3. Detect OSM tag columns (only primary ones that exist in file)
    # ------------------------------------------------------------------
    tag_columns = [c for c in PRIMARY_OSM_TAGS if c in all_columns]
    missing_tags = [c for c in PRIMARY_OSM_TAGS if c not in all_columns]
    log.info(f"\nDetected {len(tag_columns)} primary OSM tag columns: {', '.join(tag_columns)}")
    if missing_tags:
        log.info(f"Missing/skipped tags: {', '.join(missing_tags)}")

    # ------------------------------------------------------------------
    # 4. Print unique values per tag column (for inspection)
    # ------------------------------------------------------------------
    log.info("=" * 60)
    log.info("UNIQUE VALUES PER TAG COLUMN:")
    log.info("=" * 60)
    for col in tag_columns:
        unique_vals = gdf[col].dropna().unique()
        if len(unique_vals) > 0:
            vals_str = ", ".join(str(v) for v in sorted(unique_vals, key=str)[:30])
            suffix = " ..." if len(unique_vals) > 30 else ""
            log.info(f"  {col:25s} ({len(unique_vals):4d} unique): {vals_str}{suffix}")
        else:
            log.info(f"  {col:25s} (all null/empty)")

    # ------------------------------------------------------------------
    # 5. Extract feature categories
    # ------------------------------------------------------------------
    log.info("\n" + "=" * 60)
    log.info("EXTRACTING FEATURE CATEGORIES...")
    log.info("=" * 60)

    extracted_layers: dict[str, gpd.GeoDataFrame] = {}
    total_layers_created = 0

    # For each tag column, group by its non-null values and create layers
    for tag_col in tag_columns:
        # Get non-null rows for this tag
        mask = gdf[tag_col].notna() & (gdf[tag_col].astype(str).str.strip().ne(""))
        if not mask.any():
            continue

        tag_gdf = gdf[mask].copy()
        unique_vals = tag_gdf[tag_col].unique()

        # Look up friendly labels for this tag column
        label_map = OSM_TAG_LABELS.get(tag_col, {})

        for val in unique_vals:
            val_str = str(val).strip()
            if not val_str or val_str.lower() == "nan":
                continue

            val_mask = tag_gdf[tag_col].astype(str).str.strip() == val_str
            features = tag_gdf[val_mask]

            if len(features) == 0:
                continue

            # Determine layer name
            val_lower = val_str.lower().strip()
            if val_lower in label_map:
                layer_name = label_map[val_lower]
            else:
                # Auto-generate a name: {tag}_{value}
                layer_name = f"{tag_col}_{val_lower}"

            layer_name = _sanitize_filename(layer_name)

            # Handle duplicates by appending a numeric suffix
            base_name = layer_name
            counter = 1
            while layer_name in extracted_layers:
                layer_name = f"{base_name}_{counter}"
                counter += 1

            extracted_layers[layer_name] = features

    # ------------------------------------------------------------------
    # 6. Also create "all_X" summary layers (all roads, all buildings, etc.)
    # ------------------------------------------------------------------
    for tag_col in tag_columns:
        mask = gdf[tag_col].notna() & (gdf[tag_col].astype(str).str.strip().ne(""))
        if not mask.any():
            continue

        generic_name = f"all_{_sanitize_filename(tag_col)}"
        if generic_name not in extracted_layers:
            extracted_layers[generic_name] = gdf[mask].copy()

    # ------------------------------------------------------------------
    # 7. Write each layer to a GeoJSON file
    # ------------------------------------------------------------------
    log.info("\n" + "=" * 60)
    log.info("WRITING LAYER FILES...")
    log.info("=" * 60)

    summary = []

    for layer_name, layer_gdf in sorted(extracted_layers.items()):
        if len(layer_gdf) == 0:
            log.info(f"  [SKIP] {layer_name}: empty layer")
            continue

        # Remove exact duplicates
        layer_gdf = layer_gdf.drop_duplicates()

        out_file = output_dir / f"{layer_name}.geojson"
        try:
            layer_gdf.to_file(out_file, driver="GeoJSON", encoding="utf-8")
            total_layers_created += 1
            summary.append((layer_name, len(layer_gdf)))
            log.info(f"  [OK]   {layer_name:50s} -> {len(layer_gdf):6d} features")
        except Exception as e:
            log.error(f"  [ERR]  {layer_name}: failed to write - {e}")

    # ------------------------------------------------------------------
    # 8. Print summary
    # ------------------------------------------------------------------
    log.info("\n" + "=" * 60)
    log.info("EXTRACTION COMPLETE")
    log.info("=" * 60)
    log.info(f"Total layers created: {total_layers_created}")
    log.info(f"Output directory    : {output_dir.resolve()}")
    log.info("")

    if summary:
        log.info("Layer summary:")
        log.info(f"  {'Layer Name':<50s} {'Features':>10s}")
        log.info(f"  {'-'*50} {'-'*10}")
        for name, count in summary:
            log.info(f"  {name:<50s} {count:>10,d}")

    # Also write a summary JSON for quick reference
    summary_file = output_dir / "_summary.json"
    summary_data = {
        "source_file": str(input_path.resolve()),
        "extraction_date": datetime.now().isoformat(),
        "total_input_features": len(gdf),
        "total_columns": len(gdf.columns),
        "columns": all_columns,
        "tag_columns_detected": tag_columns,
        "layers": [{"name": name, "feature_count": count} for name, count in summary],
        "total_layers_created": total_layers_created,
    }
    try:
        with open(summary_file, "w", encoding="utf-8") as f:
            json.dump(summary_data, f, indent=2, ensure_ascii=False)
        log.info(f"\nSummary written to {summary_file}")
    except Exception as e:
        log.error(f"Failed to write summary: {e}")

    return extracted_layers


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python extract_osm_layers.py <input_geojson_path> [output_dir]")
        print()
        print("Examples:")
        print("  python extract_osm_layers.py my_city.osm.geojson")
        print("  python extract_osm_layers.py my_city.osm.geojson ./my_layers")
        print()
        print("The script will:")
        print("  1. Read the input GeoJSON file")
        print("  2. Auto-detect all OSM tag columns")
        print("  3. Extract each feature category into separate GeoJSON files")
        print("  4. Save everything to a 'layers/' directory (or custom output dir)")
        sys.exit(0)

    input_file = sys.argv[1]
    out_dir = sys.argv[2] if len(sys.argv) > 2 else None

    extract_osm_layers(input_file, out_dir)
