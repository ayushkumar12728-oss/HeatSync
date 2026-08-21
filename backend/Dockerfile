FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gdal-bin \
    libgdal-dev \
    libgeos-dev \
    libproj-dev \
    proj-data \
    proj-bin \
    libspatialindex-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt

RUN pip install --upgrade pip && \
    pip install -r /app/requirements.txt

# Application source
COPY backend /app/backend
COPY ai-engine /app/ai-engine
COPY gis-engine /app/gis-engine
COPY scenario-engine /app/scenario-engine

# ML models
COPY models /app/models

# Boundary
COPY boundary.geojson /app/boundary.geojson

# Required training dataset
COPY data/feature_engineering/training_dataset.csv \
     /app/data/feature_engineering/training_dataset.csv

# Preprocessor cache (avoids re-fitting on startup, which triggers the
# ai-engine DataLoader and its "GeoJSON grid not found" warning)
COPY data/predictions/serving/preprocessor.json \
     /app/data/predictions/serving/preprocessor.json

# Required prediction artifacts
COPY data/predictions/Predicted_LST.png \
     /app/data/predictions/Predicted_LST.png

COPY data/predictions/Predicted_LST.tif \
     /app/data/predictions/Predicted_LST.tif

COPY data/predictions/predictions.csv \
     /app/data/predictions/predictions.csv

# 3D OSM layers
COPY data/raw/osm/layers \
     /app/data/raw/osm/layers

RUN mkdir -p /app/backend/logs

EXPOSE 8000

CMD ["sh", "-c", "uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8000}"]