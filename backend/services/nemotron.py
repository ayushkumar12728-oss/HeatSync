"""
Nemotron explanation service
=============================
Thin, environment-driven client for the **NVIDIA NIM** Nemotron API
(OpenAI-compatible ``/v1/chat/completions``). Nemotron is ONLY the
natural-language explanation layer — it never produces numerical predictions.
All numbers shown in its answers come from the supplied context (XGBoost,
scenario engine, GIS/OSM, weather).

Model selection (Phase 17)
--------------------------
The default is ``nvidia/nemotron-mini-4b-instruct`` — the smallest Nemotron
chat/text-generation model in the NVIDIA NIM catalog actually reachable with
the configured key (verified live against ``GET /v1/models``; 102 models
listed). It is ~12x smaller than the previous default
(``nvidia/llama-3.3-nemotron-super-49b-v1``) and well suited to the
application's short urban-environment explanations. The Nano-family models
in the current catalog are larger (8B v1, 30B a3b) or non-chat (12B VL,
embed models), so the 4B instruct model is the smallest suitable chat option.
The model is fully configurable via environment (``NEMOTRON_MODEL``).

Cost control (Phase 18)
-----------------------
Sensible defaults for an explanation-only workload:

    temperature  = 0.2   (deterministic, within 0.1-0.3)
    max_tokens   = 512   (short answers; 256-512 recommended)
    timeout      = 25 s  (20-30 s recommended)
    max_retries  = 1     (never hammer an expensive provider)

Configuration (env or ``.env`` — never commit real keys):

    NEMOTRON_API_KEY=            # NVIDIA build.nvidia.com / NGC API key
    NEMOTRON_BASE_URL=           # default https://integrate.api.nvidia.com/v1
    NEMOTRON_MODEL=              # default nvidia/nemotron-mini-4b-instruct
    NEMOTRON_TIMEOUT_SECONDS=    # default 25
    NEMOTRON_MAX_RETRIES=        # default 1
    NEMOTRON_MAX_TOKENS=         # default 512
    NEMOTRON_TEMPERATURE=        # default 0.2

The API key stays server-side; React only ever talks to FastAPI.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("backend.nemotron")

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

DEFAULT_BASE_URL = "https://integrate.api.nvidia.com/v1"
# Smallest Nemotron chat model reachable with the key (Phase 17): verified
# against GET /v1/models - mini-4b-instruct is the smallest chat-capable
# Nemotron; the catalog's Nano options are larger (8B/30B) or non-chat.
DEFAULT_MODEL = "nvidia/nemotron-mini-4b-instruct"

# Cost-control defaults (Phase 18).
DEFAULT_TIMEOUT_SECONDS = 25.0
DEFAULT_MAX_RETRIES = 1
DEFAULT_MAX_TOKENS = 512
DEFAULT_TEMPERATURE = 0.2

# Error categories surfaced to the API/frontend.
ERROR_AUTH = "auth_error"
ERROR_TIMEOUT = "timeout"
ERROR_RATE_LIMIT = "rate_limit"
ERROR_PROVIDER = "provider_unavailable"
ERROR_EMPTY = "empty_response"
ERROR_MALFORMED = "malformed_response"


class NemotronError(Exception):
    """A failed / unavailable Nemotron call with a stable category."""

    def __init__(self, category: str, message: str):
        super().__init__(message)
        self.category = category


def _env(name: str, default: str | None = None) -> str | None:
    """Env var with a fallback to the project's .env file (NEMOTRON_* keys)."""
    value = os.environ.get(name)
    if value not in (None, ""):
        return value
    env_file = PROJECT_ROOT / ".env"
    if env_file.exists():
        try:
            for line in env_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith(name + "="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
        except OSError:
            pass
    return default


@dataclass
class NemotronConfig:
    api_key: str | None
    base_url: str
    model: str
    timeout_seconds: float
    max_retries: int
    max_tokens: int
    temperature: float

    @classmethod
    def from_env(cls) -> NemotronConfig:
        return cls(
            api_key=_env("NEMOTRON_API_KEY"),
            base_url=_env("NEMOTRON_BASE_URL", DEFAULT_BASE_URL) or DEFAULT_BASE_URL,
            model=_env("NEMOTRON_MODEL", DEFAULT_MODEL) or DEFAULT_MODEL,
            timeout_seconds=float(_env("NEMOTRON_TIMEOUT_SECONDS", str(DEFAULT_TIMEOUT_SECONDS))
                                  or DEFAULT_TIMEOUT_SECONDS),
            max_retries=int(_env("NEMOTRON_MAX_RETRIES", str(DEFAULT_MAX_RETRIES))
                            or DEFAULT_MAX_RETRIES),
            max_tokens=int(_env("NEMOTRON_MAX_TOKENS", str(DEFAULT_MAX_TOKENS))
                           or DEFAULT_MAX_TOKENS),
            temperature=float(_env("NEMOTRON_TEMPERATURE", str(DEFAULT_TEMPERATURE))
                              or DEFAULT_TEMPERATURE),
        )

    @property
    def configured(self) -> bool:
        return bool(self.api_key)


class NemotronClient:
    """NVIDIA NIM chat-completions client (requests, no new dependency)."""

    def __init__(self, config: NemotronConfig | None = None):
        self.config = config or NemotronConfig.from_env()

    # ------------------------------------------------------------------ #
    def status(self) -> dict:
        """Configuration / availability report (no network call)."""
        if not self.config.configured:
            return {
                "provider": "NVIDIA NIM (Nemotron)",
                "model": self.config.model,
                "base_url": self.config.base_url,
                "available": False,
                "status": "configuration_required",
                "message": (
                    "Nemotron configuration required: set NEMOTRON_API_KEY "
                    "in .env (see .env.example)."
                ),
            }
        return {
            "provider": "NVIDIA NIM (Nemotron)",
            "model": self.config.model,
            "base_url": self.config.base_url,
            "available": True,
            "status": "configured",
            "message": "Nemotron configured (availability verified on first request).",
        }

    # ------------------------------------------------------------------ #
    def ask(self, question: str, system_prompt: str,
            context_text: str | None = None, max_tokens: int | None = None) -> str:
        """Send one user question (with optional structured context) to Nemotron.

        Returns the plain-text answer. Raises :class:`NemotronError` with a
        stable category on failure so the API can respond gracefully. Retries
        at most ``max_retries`` times (default 1) to protect the budget.
        """
        if not self.config.configured:
            raise NemotronError(ERROR_AUTH, "Nemotron API key is not configured.")

        import requests

        messages: list[dict] = [{"role": "system", "content": system_prompt}]
        user_content = question if not context_text else f"{context_text}\n\nQUESTION: {question}"
        messages.append({"role": "user", "content": user_content})

        payload = {
            "model": self.config.model,
            "messages": messages,
            "temperature": self.config.temperature,
            "max_tokens": min(max_tokens or self.config.max_tokens, self.config.max_tokens),
        }
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }
        url = f"{self.config.base_url.rstrip('/')}/chat/completions"

        last_error: Exception | None = None
        for attempt in range(self.config.max_retries + 1):
            try:
                response = requests.post(
                    url, json=payload, headers=headers,
                    timeout=self.config.timeout_seconds,
                )
            except requests.exceptions.Timeout:
                last_error = NemotronError(
                    ERROR_TIMEOUT,
                    f"Nemotron request timed out after {self.config.timeout_seconds}s.",
                )
            except requests.exceptions.RequestException as exc:
                last_error = NemotronError(ERROR_PROVIDER, f"Nemotron connection failed: {exc}")
            else:
                if response.status_code == 401 or response.status_code == 403:
                    raise NemotronError(
                        ERROR_AUTH,
                        "Nemotron authentication failed - check NEMOTRON_API_KEY.",
                    )
                if response.status_code == 429:
                    last_error = NemotronError(
                        ERROR_RATE_LIMIT, "Nemotron rate limit exceeded."
                    )
                elif response.status_code >= 500:
                    last_error = NemotronError(
                        ERROR_PROVIDER, f"Nemotron provider error ({response.status_code})."
                    )
                elif response.status_code != 200:
                    raise NemotronError(
                        ERROR_PROVIDER,
                        f"Nemotron returned {response.status_code}: {response.text[:200]}",
                    )
                else:
                    return self._parse_answer(response)

            if last_error is not None and attempt < self.config.max_retries:
                log.warning("Nemotron attempt %d failed: %s", attempt + 1, last_error)
                time.sleep(1.5 * (attempt + 1))
            else:
                raise last_error  # type: ignore[misc]

        raise NemotronError(ERROR_PROVIDER, "Nemotron request failed after retries.")

    # ------------------------------------------------------------------ #
    def _parse_answer(self, response) -> str:
        try:
            data = response.json()
            choices = data.get("choices") or []
            if not choices:
                raise NemotronError(ERROR_EMPTY, "Nemotron returned no choices.")
            content = (choices[0].get("message") or {}).get("content")
        except ValueError as exc:
            raise NemotronError(ERROR_MALFORMED, f"Malformed Nemotron response: {exc}") from exc
        if not content or not str(content).strip():
            raise NemotronError(ERROR_EMPTY, "Nemotron returned an empty answer.")
        return str(content).strip()
