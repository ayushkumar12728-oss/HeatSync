"""
AI context builder & question routing
=====================================
Builds a *whitelisted* context payload for Nemotron from real project data
(monitoring status, environment summary, model status, scenario results and
client-supplied area context). Only fields that actually exist are included;
missing values stay ``null`` / ``unavailable`` — never guesses.

Nemotron receives numbers ONLY as explicit authoritative fields and is told
never to alter them. It explains; XGBoost predicts.

Updated to include historical Landsat LST observations.
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------- #
# System instruction (Session 5, step 7)
# ---------------------------------------------------------------------- #
SYSTEM_PROMPT = (
    "You are the explanation assistant for an Urban Digital Twin (Bhubaneswar). "
    "You explain technical city data in simple language. Strict rules:\n\n"
    "1. Use ONLY the supplied project context. Never invent information.\n"
    "2. Never invent numerical values, sensor readings or satellite observations.\n"
    "3. Never claim a prediction was produced if the prediction model was unavailable.\n"
    "4. Never change the XGBoost result. Values given as authoritative fields "
    "(e.g. BASELINE_LST_C) must appear unaltered in your explanation.\n"
    "5. Clearly distinguish: observed / predicted / simulated / historical / unavailable.\n"
    "6. If required data is missing, say so instead of guessing.\n"
    "7. Explain technical results in simple language.\n"
    "8. When discussing causality, avoid claiming that correlation proves causation.\n"
    "9. When discussing scenarios, distinguish model prediction from "
    "guaranteed real-world outcomes.\n"
    "10. Do not present visualization thresholds as medical or regulatory thresholds.\n"
    "11. Do not invent recommendations unsupported by the supplied context.\n"
    "12. Never output numbers that are not in the supplied context.\n"
    "13. Keep answers concise unless the user requests detail.\n"
    "14. When discussing historical Landsat LST data, clearly state it is "
    "satellite-observed/derived land surface temperature, NOT air temperature.\n"
    "15. Historical Landsat observations are from real satellite acquisitions "
    "on specific dates — never fabricate or interpolate missing dates.\n"
    "16. Current predicted LST is from XGBoost — never confuse it with "
    "satellite-observed LST."
)

# ---------------------------------------------------------------------- #
# Question routing (step 14) - decides what context is relevant
# ---------------------------------------------------------------------- #
QUESTION_CATEGORIES = {
    # COMPARISON first: "which scenario ..." must not be eaten by SCENARIO.
    "COMPARISON": ["compare", "which scenario", "before and after",
                    "before/after", "which performs better"],
    "SCENARIO": ["what happens if", "green cover", "cool roof", "increase tree", "intervention",
                 "increase green", "scenario prediction", "scenario result", "run the scenario"],
    "CITY": ["hotspot", "hot spots", "hottest", "city heat", "where is it hot",
             "most vulnerable", "vulnerable areas"],
    "AREA": ["why is this area", "why is this location", "why is this cell",
             "this area hot", "selected area"],
    "PREDICTION": ["model predict", "predicted lst", "what does the model", "prediction"],
    "RISK": ["risk", "high risk", "dangerous", "exposure"],
    "EXPLANATION": ["why", "factor", "contribute", "what causes", "explain"],
    "HISTORICAL": ["historical", "landsat", "satellite lst", "past", "time machine",
                   "time-series", "trend", "hottest period", "coolest",
                   "warmest", "seasonal", "season"],
    "DATA": ["when", "date", "collected", "acquisition"],
    "SOURCE": ["where did", "source", "origin", "which satellite", "which api"],
}


def route_question(question: str) -> str:
    """Classify a question into a category (default EXPLANATION)."""
    q = question.lower()
    for category, keywords in QUESTION_CATEGORIES.items():
        if any(k in q for k in keywords):
            return category
    return "EXPLANATION"


# ---------------------------------------------------------------------- #
# Context whitelist
# ---------------------------------------------------------------------- #
def _pick(source: dict | None, *keys: str) -> Any:
    """First present key from source, else None."""
    if not source:
        return None
    for key in keys:
        if key in source and source[key] is not None:
            return source[key]
    return None


def _clean(value: Any) -> Any:
    """Normalise floats for display; keep None as None (never guesses)."""
    if value is None:
        return None
    if isinstance(value, float):
        return round(value, 3)
    return value


def build_context(*, question: str = "", location: dict | None = None,
                  environment: dict | None = None,
                  urban: dict | None = None,
                  air_quality: dict | None = None,
                  weather: dict | None = None,
                  prediction: dict | None = None,
                  scenario: dict | None = None,
                  historical_lst: dict | None = None,
                  model_status: dict | None = None,
                  data_freshness: dict | None = None,
                  missing_sources: list[str] | None = None,
                  snapshot_id: str | None = None) -> dict:
    """Assemble the whitelisted context sent to Nemotron.

    Only fields present in the inputs are included. ``prediction`` is
    represented with an explicit ``available`` flag so Nemotron can never
    claim a prediction that does not exist.
    """
    prediction_block: dict = {"available": False, "status": "unavailable"}
    if prediction and prediction.get("available"):
        prediction_block = {
            "available": True,
            "predicted_lst_c": _clean(_pick(prediction, "predicted_lst_c", "predicted_lst")),
            "uhi_class": _pick(prediction, "uhi_class", "class"),
        }
    elif model_status and not model_status.get("available"):
        prediction_block["message"] = (
            "The trained prediction model is currently unavailable, so no "
            "model-based temperature prediction can be provided."
        )
    else:
        # the model exists but the client supplied no prediction for this
        # request - keep the block honest about what was actually provided
        prediction_block["message"] = (
            "A model-based temperature prediction is unavailable for this "
            "location in the supplied context (the XGBoost model is available "
            "but was not run for this request)."
        )

    context: dict[str, Any] = {}
    if location:
        context["location"] = {
            "grid_id": _pick(location, "grid_id", "name"),
            "latitude": _clean(_pick(location, "latitude", "lat")),
            "longitude": _clean(_pick(location, "longitude", "lng")),
        }
    if environment:
        env_block = {
            k: _clean(environment.get(k))
            for k in ("ndvi", "green_cover", "lst", "elevation", "slope")
            if environment.get(k) is not None
        }
        if env_block:
            context["environment"] = env_block
    if urban:
        urb_block = {
            k: _clean(urban.get(k))
            for k in ("building_density", "road_density", "tree_density", "green_area_m2")
            if urban.get(k) is not None
        }
        if urb_block:
            context["urban"] = urb_block
    if air_quality:
        aq_block = {
            k: _clean(air_quality.get(k))
            for k in ("aqi", "pm25", "pm10", "no2")
            if air_quality.get(k) is not None
        }
        if aq_block:
            context["air_quality"] = aq_block
    if weather:
        wx_block = {
            k: _clean(weather.get(k))
            for k in ("temperature", "humidity", "wind_speed", "source")
            if weather.get(k) is not None
        }
        if wx_block:
            context["weather"] = wx_block
    context["prediction"] = prediction_block

    # Historical Landsat LST context
    if historical_lst:
        hist_block = {
            "status": historical_lst.get("status", "unavailable"),
            "source": "Landsat Collection 2 Level-2",
            "metric": "land_surface_temperature",
            "unit": "°C",
        }
        # Include specific observation if provided
        obs = historical_lst.get("observation")
        if obs:
            hist_block["observation_date"] = obs.get("date")
            hist_block["mean_lst_c"] = _clean(obs.get("mean_lst"))
            hist_block["min_lst_c"] = _clean(obs.get("min_lst"))
            hist_block["max_lst_c"] = _clean(obs.get("max_lst"))
            hist_block["cloud_cover"] = _clean(obs.get("cloud_cover"))
            hist_block["valid_pixel_fraction"] = _clean(obs.get("valid_pixel_fraction"))
            hist_block["scene_id"] = obs.get("scene_id")
        # Include analytics if provided
        analytics = historical_lst.get("analytics")
        if analytics:
            hist_block["observation_count"] = analytics.get("observation_count")
            hist_block["mean_historical_lst"] = _clean(analytics.get("mean_historical_lst"))
            hist_block["hottest_date"] = analytics.get("hottest_date")
            hist_block["coolest_date"] = analytics.get("coolest_date")
        if hist_block.get("observation_date") or hist_block.get("observation_count"):
            context["historical_lst"] = hist_block

    # Data freshness & missing-source honesty — Nemotron must never present
    # stale satellite data as live.
    if data_freshness:
        freshness_block: dict[str, Any] = {}
        for src in ("weather", "aqi", "satellite"):
            ts = data_freshness.get(src)
            if ts and ts != "never":
                freshness_block[src] = f"last observed: {ts}"
            else:
                freshness_block[src] = "unavailable"
        context["data_freshness"] = freshness_block
    if missing_sources:
        context["missing_sources"] = missing_sources
        context["data_note"] = (
            "Satellite data unavailable — NDVI and land cover values are from "
            "the training dataset, not from a current satellite observation."
            if "satellite" in missing_sources
            else None
        )

    if scenario:
        sc_block = {
            k: _clean(scenario.get(k))
            for k in ("scenario", "baseline_lst", "mean_predicted_lst",
                      "mean_delta_lst", "pct_cells_cooler", "min_delta",
                      "max_delta", "n_cells", "changed_features",
                      "top_cooling_cells")
            if scenario.get(k) is not None
        }
        if sc_block:
            context["scenario"] = sc_block
    if snapshot_id:
        context["snapshot_id"] = snapshot_id
    context["question_category"] = route_question(question)
    return context


# ---------------------------------------------------------------------- #
# Numerical-value safety (step 15): authoritative fields + guard instruction
# ---------------------------------------------------------------------- #
def render_context_for_prompt(context: dict) -> str:
    """Flatten the context into a prompt block.

    Authoritative model outputs are spelled out as labelled fields and the
    model is instructed not to alter them.
    """
    lines = ["CITY DATA CONTEXT (whitelisted project data):"]
    lines.append("---")
    lines.append("AUTHORITATIVE MODEL OUTPUTS - do not alter these values:")
    for key in ("baseline_lst", "mean_predicted_lst", "mean_delta_lst",
                "predicted_lst_c", "pct_cells_cooler"):
        _inject_authoritative(lines, context, key)
    lines.append("---")

    def dump_block(label: str, block: dict) -> None:
        if not block:
            return
        lines.append(f"{label}:")
        for key, value in block.items():
            if value is None:
                lines.append(f"  {key}: unavailable")
            else:
                lines.append(f"  {key}: {value}")

    dump_block("LOCATION", context.get("location"))
    dump_block("ENVIRONMENT (observed/satellite)", context.get("environment"))
    dump_block("URBAN (OSM-derived)", context.get("urban"))
    dump_block("AIR QUALITY", context.get("air_quality"))
    dump_block("WEATHER", context.get("weather"))
    pred = context.get("prediction") or {}
    if pred.get("available"):
        dump_block("PREDICTION (XGBoost)", pred)
    else:
        lines.append("PREDICTION: unavailable (trained model not present)")
        if pred.get("message"):
            lines.append(f"  note: {pred['message']}")
    dump_block("SCENARIO (XGBoost)", context.get("scenario"))
    dump_block("HISTORICAL LST (Landsat satellite observation)", context.get("historical_lst"))
    dump_block("DATA FRESHNESS", context.get("data_freshness"))
    if context.get("missing_sources"):
        lines.append(
            f"MISSING DATA SOURCES: {', '.join(context['missing_sources'])}"
        )
    if context.get("data_note"):
        lines.append(f"NOTE: {context['data_note']}")
    lines.append(f"QUESTION CATEGORY: {context.get('question_category', 'EXPLANATION')}")
    return "\n".join(lines)


def _inject_authoritative(lines: list[str], context: dict, key: str) -> None:
    """Collect a key from the prediction/scenario blocks as an authoritative field."""
    for block_name in ("prediction", "scenario"):
        block = context.get(block_name) or {}
        if key in block and block[key] is not None:
            lines.append(f"  {key.upper()}: {block[key]}  [source: XGBoost]")
            return
