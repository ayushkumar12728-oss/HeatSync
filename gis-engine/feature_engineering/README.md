# GIS Feature Engineering Engine — Urban Heat Island training dataset

Merges every processed dataset of the Bhubaneswar urban digital twin (OSM
vectors, Sentinel-2 rasters, Landsat LST, DEM terrain, air quality, NASA
POWER weather) into one unified machine-learning table on a regular
**100 m x 100 m grid**, ready for XGBoost UHI regression.

No data is downloaded — the engine only reads the already-processed files.

## Run

```bash
cd gis-engine/feature_engineering
python main.py                       # full pipeline (~3 min, parallel)
python main.py --grid-size 200       # coarser grid
python main.py --acquisition-date 2026-05-16   # override weather join date
python main.py --no-parallel         # single-process debugging
python main.py --skip-quality        # skip reports / plots / baseline
```

The acquisition date defaults to the Landsat scene date in
`data/processed/lst/LST_statistics.json` (2026-05-16); weather columns are
joined for that date.

## Outputs (`data/feature_engineering/`)

| File | Contents |
|------|----------|
| `training_dataset.csv` | **53,802 rows x 86 columns** — raw features + `Target_LST`. What XGBoost consumes. |
| `training_dataset_normalized.csv` | z-score normalised copy (for linear models / inspection) |
| `training_dataset.geojson` | same table as grid polygons (EPSG:32645) |
| `feature_statistics.json` | count/mean/std/min/quartiles/max per feature |
| `correlation_matrix.csv` | Pearson correlations between numeric features |
| `feature_importance_baseline.csv` | RandomForest baseline importance vs `Target_LST` |
| `missing_value_report.json` | missing values before/after cleaning |
| `quality_report.json` | CRS / geometry / duplicate / range checks |
| `plots/*.png` | correlation heatmap, distributions, histograms, spatial maps, target distribution |

## Module layout

```
feature_engineering/
├── config.py            paths, grid, land-cover classes, weights
├── grid_generator.py    STEP 1  - 100 m grid (Grid_ID, lat/lon, area)
├── vector_features.py   STEP 2  - buildings, roads, trees, green, land use, distances
├── raster_features.py   STEP 3  - zonal stats for 15 rasters (parallel)
├── weather_features.py  STEP 4  - weather join by acquisition date
├── derived_features.py  STEP 5  - 7 UHI indices + Target_LST
├── merge_features.py    STEP 6  - merge, dedupe, missing values, CRS/geometry checks
├── quality_checks.py    STEP 7  - reports, correlation, baseline, plots
└── main.py              CLI entry point
```

## Design decisions worth knowing

- **Grid**: 100 m cells in UTM 45N (EPSG:32645) so lengths/areas/distances are
  true metres; clipped to `boundary.geojson` (53,802 cells, 533 km²).
- **Raster zonal stats**: cells are rasterised into each raster's own pixel
  grid and aggregated with numpy `ufunc.at` accumulators — no per-pixel
  Python loops. Rasters coarser than the grid (the 1 km AQI surfaces) are
  resampled to 100 m first so every cell receives a value.
- **Weather is constant across the grid** (single acquisition date), so those
  columns carry no spatial signal in this snapshot; they become predictive
  once multiple scenes/dates are stacked.
- **`training_dataset.csv` keeps raw values** — XGBoost is scale-invariant, and
  raw units keep feature importance interpretable. The normalised copy
  satisfies the "normalize numeric variables" requirement without degrading
  the primary deliverable.
- **`Target_LST` = cell mean LST (°C)** — the standard UHI intensity proxy.
  To model the *anomaly* form of UHI, subtract a rural reference:
  `Target_UHI = Target_LST - Target_LST[rural_mask].mean()`.
- Missing layers degrade gracefully: e.g. the OSM extraction contains no
  railway *lines* (only 2 polygons), so railway features are skipped with a
  warning rather than failing the run.

---

## 1. Why every feature is useful

### Built environment (STEP 2)
| Feature | Why it matters for UHI |
|---|---|
| `BuildingCount`, `BuildingDensity`, `BuildingCoveragePct`, `AvgBuildingFootprint` | Buildings are thermal mass: they store solar heat by day and re-radiate it at night. Coverage drives canyon geometry; density drives the urban-fabric heat source; footprint size hints at building type (small houses vs large commercial blocks). |
| `RoadLength`, `RoadDensity`, `RoadIntersectionCount`, `RoadIntersectionDensity`, `DistToMajorRoad` | Asphalt/concrete have low albedo and high heat capacity. Road density = transport heat source; intersections concentrate traffic/emissions; distance to arterial roads captures proximity to the hottest paved surfaces. |
| `TreeCount`, `TreeDensity`, `GreenSpacePct` | Trees shade surfaces and transpire (evaporative cooling). Green-space fraction is the primary *cooling* term in every empirical UHI model. |
| `LandUse_*Pct` | Land use integrates function and materials: residential/commercial/industrial fabric vs agriculture/green. It encodes the "what is this neighbourhood made of" signal that pure raster indices miss. |
| `DistToPark`, `DistToWater` | Parks and water bodies are cool islands; proximity to them cools surrounding cells (park cool-island effect extends hundreds of metres). |
| `DistToHospital`, `DistToSchool`, `HospitalCount`, `SchoolCount` | Density of large public/institutional buildings and their parking lots correlates with dense urban fabric — weak but real heat-source proxies. |
| `BusStopCount`, `BusStopDensity`, `DistToBusStop` | Busy transport nodes imply paved plazas, idling vehicles and dense pedestrian activity. |

### Surface state (STEP 3)
| Feature | Why it matters |
|---|---|
| `MeanNDVI`, `MaxNDVI`, `MinNDVI` | Vegetation vigour. NDVI is the single most used predictor of LST in the literature (R² typically 0.3–0.6 against LST alone). |
| `GreenCover` (%) | Binary green mask share — directly the "vegetated fraction" used in SUHI models. |
| `VegetationDensity`, `VegDensityClass` | 5-class vegetation intensity (from NDVI) — a coarser but robust greenness measure. |
| `LandCoverClass`, `LandCover_*Pct` | Land-cover fractions (water/vegetation/built-up/bare) are the material surface mix; built-up share is the direct driver of the urban heat island. |
| `MeanLST`, `MaxLST`, `MinLST` | The observed surface temperature — these are the **target signal** (kept as features for multi-target/leakage studies; excluded from baseline importance). |
| `MeanElevation`, `MeanSlope`, `Aspect` | Terrain: elevation → lapse-rate cooling (~6.5 °C/km); slope/aspect → solar exposure (south-facing slopes heat more). |
| `MeanAQI`, `MeanPM25`, `MeanPM10`, `MeanNO2`, `MeanSO2`, `MeanCO`, `MeanO3` | Air pollution co-varies with urban heat (same emission sources — traffic, industry — and photochemistry is temperature-driven). Useful as covariates, not causes. |

### Weather (STEP 4)
| Feature | Why it matters |
|---|---|
| `Temperature`, `Humidity`, `WindSpeed`, `Pressure`, `SolarRadiation`, `Rainfall`, `HeatIndex` (+ `_7d` rolling, `_MonthlyMean`) | Boundary conditions for the scene: the same city on a hot, calm, clear day shows a far stronger UHI than on a windy/cloudy day. Constant in this single-date snapshot but essential once multi-date data is stacked. |
| `Season`, `Month` | Seasonal context for the acquisition. |

### Derived indices (STEP 5)
| Feature | Why it matters |
|---|---|
| `ImperviousSurfaceRatio` | Built-up + bare land share — the canonical "urban fabric" proxy (r = −0.95 with green cover here). |
| `GreenToBuiltRatio` | Vegetation-to-built balance — directly the green-vs-grey competition that sets LST. |
| `CoolingDistanceIndex` | Blends proximity to park/water with green-area share → continuous cool-island exposure score. |
| `RoadExposureIndex` | Road density + arterial proximity → transport heat exposure. |
| `VegetationCoolingIndex` | NDVI × green-cover share → actual cooling delivered by vegetation. |
| `TerrainExposureIndex` | Normalised slope → exposure/ventilation potential. |
| `HeatVulnerabilityIndex` | Weighted composite (impervious 0.30, low green 0.25, building density 0.20, road exposure 0.15, low NDVI 0.10) — a single interpretable vulnerability score. |

## 2. Expected strongest predictors of UHI

1. **Land cover / imperviousness** — `ImperviousSurfaceRatio`,
   `LandCover_BuiltupPct`, `LandCover_BareLandPct` (direct material driver).
2. **Vegetation** — `GreenCover`, `MeanNDVI`, `VegetationCoolingIndex`,
   `GreenToBuiltRatio` (direct cooling driver; the strongest *negative* terms).
3. **Building/road density** — `BuildingCoveragePct`, `BuildingDensity`,
   `RoadDensity` (thermal mass + paving).
4. **Cooling proximity** — `CoolingDistanceIndex`, `DistToWater`, `DistToPark`.
5. **Terrain** — `MeanElevation` (lapse-rate), `Aspect` (solar exposure).

The RandomForest baseline already reflects this: `ImperviousSurfaceRatio`
(40% importance), `LandCover_BareLandPct`, `DistToWater`, `MeanElevation`,
`MinNDVI`, `MeanNDVI`. Treat the `MeanPM25`/`MeanO3` baseline rankings with
caution — the AQI surfaces come from interpolated/demo station data and
their apparent importance may be an artefact of spatial autocorrelation.

## 3. Features likely to be highly correlated (measured)

| Pair | r |
|---|---|
| `TreeCount` ~ `TreeDensity`, `BuildingCount` ~ `BuildingDensity`, `RoadLength` ~ `RoadDensity`, counts ~ densities | 1.00 (same signal, different denominator) |
| `MeanLST` ~ `MaxLST` ~ `MinLST` ~ `Target_LST` | 0.95–1.00 (same thermal scene) |
| `GreenCover` ~ `LandCover_VegetationPct` | 0.999 (both NDVI-derived) |
| `MeanNDVI` ~ `VegetationDensity` | 0.97 |
| `GreenCover` ~ `ImperviousSurfaceRatio` | −0.95 (green vs grey) |
| `DistToPark` ~ `DistToSchool` | 0.93 (urban structure) |
| `MeanSlope` ~ `TerrainExposureIndex` | 1.00 (by construction) |
| `ImperviousSurfaceRatio` ~ `HeatVulnerabilityIndex` | 0.94 (by construction) |

Practical guidance: drop one of each count/density pair, keep one of the LST
family as the target only, and expect XGBoost to largely ignore the derived
indices that duplicate raw features (e.g. `TerrainExposureIndex` adds nothing
over `MeanSlope`). `HeatVulnerabilityIndex` is best used for explainability,
not as a raw predictor.

## 4. How XGBoost uses the CSV

```python
import pandas as pd
from sklearn.model_selection import train_test_split
import xgboost as xgb

df = pd.read_csv("training_dataset.csv")
drop = ["Grid_ID", "Latitude", "Longitude", "Area_m2",
        "MeanLST", "MaxLST", "MinLST"]          # no leakage / ids
X = df.drop(columns=drop + ["Target_LST", "Season"])
y = df["Target_LST"]
X = pd.get_dummies(X, columns=["Month"])        # one-hot the single categorical
X_train, X_val, y_train, y_val = train_test_split(X, y, test_size=0.2,
                                                  random_state=42)

model = xgb.XGBRegressor(n_estimators=500, learning_rate=0.05,
                         max_depth=6, subsample=0.8, colsample_bytree=0.8,
                         early_stopping_rounds=30, random_state=42)
model.fit(X_train, y_train,
          eval_set=[(X_val, y_val)], verbose=False)
```

- **Row = one 100 m grid cell; column = one predictor; `Target_LST` = the
  regression target** (cell mean land-surface temperature, °C).
- XGBoost handles the raw units directly (tree splits are scale-invariant),
  missing values natively, and non-linear interactions (e.g. the
  vegetation×density cooling interaction) without manual feature crosses.
- Tree-based importance in `feature_importance_baseline.csv` gives the first
  ranking; use `permutation_importance` and SHAP after training for
  explanations.
- To turn predictions into a *UHI-intensity* map, either subtract a rural
  reference from `Target_LST` before training, or predict LST and compute
  `LST_pred - rural_mean` afterwards. Predictions map straight back onto the
  grid (`training_dataset.geojson`) for spatial visualisation.
