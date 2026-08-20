-- ============================================================================
-- Urban Digital Twin - Database Schema
-- PostgreSQL + PostGIS
--
-- The grid_cells table mirrors the ML training dataset produced by
-- data-processing/feature_engineering (data/feature_engineering/
-- training_dataset.csv) so the seed loader can map columns 1:1.
-- ============================================================================

CREATE EXTENSION IF NOT EXISTS postgis;

-- ---------------------------------------------------------------------------
-- Grid cells: one row per 100 m cell with every engineered feature.
-- Column names are snake_case versions of the training CSV headers.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS grid_cells (
    grid_id                     BIGINT PRIMARY KEY,
    geometry                    GEOMETRY(POLYGON, 4326) NOT NULL,

    -- building / infrastructure
    area_m2                     DOUBLE PRECISION,
    building_count              DOUBLE PRECISION,
    building_coverage_pct       DOUBLE PRECISION,
    avg_building_footprint      DOUBLE PRECISION,
    building_density            DOUBLE PRECISION,
    road_length                 DOUBLE PRECISION,
    road_intersection_count     DOUBLE PRECISION,
    dist_to_major_road          DOUBLE PRECISION,
    road_density                DOUBLE PRECISION,
    road_intersection_density   DOUBLE PRECISION,

    -- green / vegetation
    tree_count                  DOUBLE PRECISION,
    tree_density                DOUBLE PRECISION,
    green_space_pct             DOUBLE PRECISION,
    mean_ndvi                   DOUBLE PRECISION,
    max_ndvi                    DOUBLE PRECISION,
    min_ndvi                    DOUBLE PRECISION,
    green_cover                 DOUBLE PRECISION,
    vegetation_density          DOUBLE PRECISION,
    veg_density_class           INTEGER,
    land_cover_class            INTEGER,

    -- land use / land cover shares
    land_use_residential_pct    DOUBLE PRECISION,
    land_use_commercial_pct     DOUBLE PRECISION,
    land_use_industrial_pct     DOUBLE PRECISION,
    land_use_institutional_pct  DOUBLE PRECISION,
    land_use_agriculture_pct    DOUBLE PRECISION,
    land_use_green_pct          DOUBLE PRECISION,
    land_use_railway_pct        DOUBLE PRECISION,
    land_use_other_pct          DOUBLE PRECISION,
    land_cover_water_pct        DOUBLE PRECISION,
    land_cover_vegetation_pct   DOUBLE PRECISION,
    land_cover_builtup_pct      DOUBLE PRECISION,
    land_cover_bare_land_pct    DOUBLE PRECISION,

    -- proximity / access
    dist_to_park                DOUBLE PRECISION,
    dist_to_water               DOUBLE PRECISION,
    dist_to_hospital            DOUBLE PRECISION,
    dist_to_school              DOUBLE PRECISION,
    bus_stop_count              DOUBLE PRECISION,
    dist_to_bus_stop            DOUBLE PRECISION,
    bus_stop_density            DOUBLE PRECISION,
    hospital_count              DOUBLE PRECISION,
    school_count                DOUBLE PRECISION,

    -- thermal observations (leakage columns - informational)
    mean_lst                    DOUBLE PRECISION,
    max_lst                     DOUBLE PRECISION,
    min_lst                     DOUBLE PRECISION,

    -- terrain
    mean_elevation              DOUBLE PRECISION,
    mean_slope                  DOUBLE PRECISION,
    aspect                      DOUBLE PRECISION,

    -- air quality
    mean_aqi                    DOUBLE PRECISION,
    mean_pm25                   DOUBLE PRECISION,
    mean_pm10                   DOUBLE PRECISION,
    mean_no2                    DOUBLE PRECISION,
    mean_so2                    DOUBLE PRECISION,
    mean_co                     DOUBLE PRECISION,
    mean_o3                     DOUBLE PRECISION,

    -- weather (single-value columns for this snapshot)
    temperature                 DOUBLE PRECISION,
    temperature_7d              DOUBLE PRECISION,
    humidity                    DOUBLE PRECISION,
    humidity_7d                 DOUBLE PRECISION,
    wind_speed                  DOUBLE PRECISION,
    wind_speed_7d               DOUBLE PRECISION,
    pressure                    DOUBLE PRECISION,
    pressure_7d                 DOUBLE PRECISION,
    solar_radiation             DOUBLE PRECISION,
    solar_radiation_7d          DOUBLE PRECISION,
    rainfall                    DOUBLE PRECISION,
    rainfall_7d                 DOUBLE PRECISION,
    heat_index                  DOUBLE PRECISION,
    heat_index_7d               DOUBLE PRECISION,
    season                      TEXT,
    month                       TEXT,
    temperature_monthly_mean    DOUBLE PRECISION,
    humidity_monthly_mean       DOUBLE PRECISION,
    wind_speed_monthly_mean     DOUBLE PRECISION,
    pressure_monthly_mean       DOUBLE PRECISION,
    solar_radiation_monthly_mean DOUBLE PRECISION,
    rainfall_monthly_mean       DOUBLE PRECISION,
    heat_index_monthly_mean     DOUBLE PRECISION,

    -- derived UHI indices
    impervious_surface_ratio    DOUBLE PRECISION,
    green_to_built_ratio        DOUBLE PRECISION,
    cooling_distance_index      DOUBLE PRECISION,
    road_exposure_index         DOUBLE PRECISION,
    vegetation_cooling_index    DOUBLE PRECISION,
    terrain_exposure_index      DOUBLE PRECISION,
    heat_vulnerability_index    DOUBLE PRECISION,

    -- target
    target_lst                  DOUBLE PRECISION,

    created_at                  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_grid_cells_geometry ON grid_cells USING GIST (geometry);

-- ---------------------------------------------------------------------------
-- Model predictions (per scenario)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS predictions (
    prediction_id   SERIAL PRIMARY KEY,
    grid_id         BIGINT REFERENCES grid_cells (grid_id),
    scenario        VARCHAR(50) NOT NULL DEFAULT 'baseline',
    predicted_lst   DOUBLE PRECISION,
    target_lst      DOUBLE PRECISION,
    residual_lst    DOUBLE PRECISION,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_predictions_grid ON predictions (grid_id);
CREATE INDEX IF NOT EXISTS idx_predictions_scenario ON predictions (scenario);

-- ---------------------------------------------------------------------------
-- Simulation results (sensitivity analysis)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS simulations (
    simulation_id   SERIAL PRIMARY KEY,
    scenario        VARCHAR(50) NOT NULL,
    description     TEXT,
    n_cells         INTEGER,
    baseline_lst    DOUBLE PRECISION,
    mean_predicted_lst DOUBLE PRECISION,
    mean_delta_lst  DOUBLE PRECISION,
    min_delta       DOUBLE PRECISION,
    max_delta       DOUBLE PRECISION,
    pct_cells_cooler DOUBLE PRECISION,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ---------------------------------------------------------------------------
-- Weather / AQI time series
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS weather_daily (
    date            DATE PRIMARY KEY,
    temperature     DOUBLE PRECISION,
    humidity        DOUBLE PRECISION,
    wind_speed      DOUBLE PRECISION,
    solar_radiation DOUBLE PRECISION,
    precipitation   DOUBLE PRECISION,
    pressure        DOUBLE PRECISION
);

CREATE TABLE IF NOT EXISTS aqi_daily (
    date        DATE,
    station_id  VARCHAR(50),
    parameter   VARCHAR(20),
    value       DOUBLE PRECISION,
    unit        VARCHAR(20),
    PRIMARY KEY (date, station_id, parameter)
);
