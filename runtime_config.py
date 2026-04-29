"""Risoluzione centralizzata della configurazione runtime del CEO agent."""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

_CONFIG_FILE = Path(__file__).parent / "config.yaml"
_DEFAULT_CEO_MODEL = "claude-opus-4-6"
_DEFAULT_SUBAGENT_MODEL = "claude-sonnet-4-6"
_DEFAULT_APPROVAL_TIMEOUT_S = 3600
_DEFAULT_LOOP_INTERVAL_MINUTES = 60


@lru_cache(maxsize=1)
def load_config() -> dict[str, Any]:
    """Carica `config.yaml` una sola volta per processo."""
    if not _CONFIG_FILE.exists():
        return {}
    data = yaml.safe_load(_CONFIG_FILE.read_text())
    return data if isinstance(data, dict) else {}


def clear_config_cache() -> None:
    """Azzera la cache di configurazione; utile nei test."""
    load_config.cache_clear()


def get_loop_interval_minutes() -> int:
    """Risolva l'intervallo dello scheduler da env o config."""
    env_val = os.getenv("LOOP_INTERVAL_MINUTES")
    if env_val:
        return int(env_val)
    return int(load_config().get("loop_interval_minutes", _DEFAULT_LOOP_INTERVAL_MINUTES))


def get_ceo_model() -> str:
    """Restituisce il modello del CEO con precedenza alle env."""
    return os.getenv("CEO_MODEL") or str(
        load_config().get("models", {}).get("ceo", _DEFAULT_CEO_MODEL)
    )


def get_subagent_model() -> str:
    """Restituisce il modello dei sub-agent con precedenza alle env."""
    return os.getenv("SUBAGENT_MODEL") or str(
        load_config().get("models", {}).get("subagents", _DEFAULT_SUBAGENT_MODEL)
    )


def get_approval_timeout_s() -> int:
    """Restituisce il timeout di approval in secondi."""
    env_val = os.getenv("APPROVAL_TIMEOUT_S")
    if env_val:
        return int(env_val)
    return _DEFAULT_APPROVAL_TIMEOUT_S


def get_reports_dir() -> Path:
    """Restituisce la directory dei report con override via env."""
    raw_path = os.getenv("REPORTS_DIR")
    if raw_path:
        return Path(raw_path)
    return Path(__file__).parent / "reports"


def _get_pipeline_worker_health_urls() -> dict[str, str] | None:
    """Legge le worker URLs da env se presenti."""
    raw = os.getenv("WORKER_HEALTH_URLS")
    if not raw:
        return None
    data = json.loads(raw)
    return data if isinstance(data, dict) else None


def get_pipeline_config() -> dict[str, Any]:
    """Restituisce la config pipeline con override via env."""
    pipeline = dict(load_config().get("pipeline", {}))

    worker_urls = _get_pipeline_worker_health_urls()
    if worker_urls is not None:
        pipeline["worker_health_urls"] = worker_urls

    trend_lookback_hours = os.getenv("TREND_LOOKBACK_HOURS")
    if trend_lookback_hours:
        pipeline["trend_lookback_hours"] = int(trend_lookback_hours)

    zscore_threshold = os.getenv("ZSCORE_THRESHOLD")
    if zscore_threshold:
        pipeline["zscore_threshold"] = float(zscore_threshold)

    return pipeline
