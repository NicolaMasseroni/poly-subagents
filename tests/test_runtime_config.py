import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_get_ceo_model_reads_config_when_env_missing(monkeypatch):
    monkeypatch.delenv("CEO_MODEL", raising=False)
    from runtime_config import clear_config_cache, get_ceo_model

    clear_config_cache()
    assert get_ceo_model() == "claude-opus-4-6"


def test_get_subagent_model_prefers_env(monkeypatch):
    monkeypatch.setenv("SUBAGENT_MODEL", "custom-subagent")
    from runtime_config import clear_config_cache, get_subagent_model

    clear_config_cache()
    assert get_subagent_model() == "custom-subagent"


def test_get_loop_interval_minutes_prefers_env(monkeypatch):
    monkeypatch.setenv("LOOP_INTERVAL_MINUTES", "15")
    from runtime_config import get_loop_interval_minutes

    assert get_loop_interval_minutes() == 15


def test_get_pipeline_config_prefers_env(monkeypatch):
    monkeypatch.setenv("WORKER_HEALTH_URLS", '{"worker_a":"http://worker-a:9108"}')
    monkeypatch.setenv("TREND_LOOKBACK_HOURS", "12")
    monkeypatch.setenv("ZSCORE_THRESHOLD", "3.5")
    from runtime_config import clear_config_cache, get_pipeline_config

    clear_config_cache()
    result = get_pipeline_config()
    assert result["worker_health_urls"] == {"worker_a": "http://worker-a:9108"}
    assert result["trend_lookback_hours"] == 12
    assert result["zscore_threshold"] == 3.5
