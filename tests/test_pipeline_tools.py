import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def mock_conn():
    conn = MagicMock()
    cursor = MagicMock()
    cursor.__enter__ = lambda s: cursor
    cursor.__exit__ = MagicMock(return_value=False)
    conn.cursor.return_value = cursor
    return conn, cursor


def test_get_trending_markets_returns_list(mock_conn):
    conn, cursor = mock_conn
    cursor.fetchall.return_value = [
        ("trump-vs-kamala-2024", 1500.0, 2.5, "YES"),
        ("will-btc-hit-100k", 800.0, 1.8, "NO"),
    ]
    cursor.description = [("market_id",), ("volume",), ("zscore",), ("top_outcome",)]
    with patch("tools.pipeline_tools.get_conn", return_value=conn):
        from tools.pipeline_tools import get_trending_markets

        result = get_trending_markets(hours=24, limit=10)
    assert isinstance(result, list)
    assert result[0]["market_id"] == "trump-vs-kamala-2024"
    assert result[0]["volume"] == 1500.0
    # verify SQL hits trades + trending, joined by slug
    sql = cursor.execute.call_args[0][0]
    assert "FROM trades" in sql
    assert "FROM trending" in sql
    assert "slug" in sql


def test_get_trade_volume_queries_by_slug(mock_conn):
    conn, cursor = mock_conn
    cursor.fetchone.return_value = (42, 1234.5, 0.67)
    with patch("tools.pipeline_tools.get_conn", return_value=conn):
        from tools.pipeline_tools import get_trade_volume

        result = get_trade_volume("trump-vs-kamala-2024", hours=24)
    assert result["market_id"] == "trump-vs-kamala-2024"
    assert result["trade_count"] == 42
    assert result["total_volume"] == 1234.5
    sql = cursor.execute.call_args[0][0]
    assert "WHERE slug = %s" in sql


def test_get_price_history_returns_list(mock_conn):
    conn, cursor = mock_conn
    cursor.fetchall.return_value = [
        ("2026-04-16T10:00:00Z", 0.65),
        ("2026-04-16T11:00:00Z", 0.70),
    ]
    cursor.description = [("ts",), ("price",)]
    with patch("tools.pipeline_tools.get_conn", return_value=conn):
        from tools.pipeline_tools import get_price_history

        result = get_price_history("trump-vs-kamala-2024", hours=12)
    assert len(result) == 2
    assert result[0]["price"] == 0.65


def test_get_zscore_anomalies_uses_trending(mock_conn):
    conn, cursor = mock_conn
    cursor.fetchall.return_value = [
        ("trump-vs-kamala-2024", 3.2, 5000.0, "2026-04-16T12:00:00Z"),
    ]
    cursor.description = [("market_id",), ("zscore",), ("volume",), ("timestamp",)]
    with patch("tools.pipeline_tools.get_conn", return_value=conn):
        from tools.pipeline_tools import get_zscore_anomalies

        result = get_zscore_anomalies(threshold=2.0, hours=24)
    assert result[0]["market_id"] == "trump-vs-kamala-2024"
    assert result[0]["zscore"] == 3.2
    sql = cursor.execute.call_args[0][0]
    assert "FROM trending" in sql
    assert "volume_zscore" in sql


def test_check_worker_health_returns_dict():
    with patch("tools.pipeline_tools.requests.get") as mock_get:
        mock_get.return_value = MagicMock(status_code=200)
        from tools.pipeline_tools import check_worker_health

        result = check_worker_health({"trades_to_tsdb": "http://localhost:8080"})
    assert result["trades_to_tsdb"] == "healthy"


def test_check_worker_health_marks_down_on_error():
    with patch("tools.pipeline_tools.requests.get", side_effect=Exception("conn refused")):
        from tools.pipeline_tools import check_worker_health

        result = check_worker_health({"trades_to_tsdb": "http://localhost:8080"})
    assert result["trades_to_tsdb"] == "down"


def test_check_worker_health_marks_degraded_on_non_200():
    with patch("tools.pipeline_tools.requests.get") as mock_get:
        mock_get.return_value = MagicMock(status_code=503)
        from tools.pipeline_tools import check_worker_health

        result = check_worker_health({"trades_to_tsdb": "http://localhost:8080"})
    assert result["trades_to_tsdb"] == "degraded"


def test_get_pipeline_coverage_flags_missing_when_provider_down():
    with patch("tools.pipeline_tools.requests.get", side_effect=Exception("conn refused")):
        from tools.pipeline_tools import get_pipeline_coverage

        coverage = get_pipeline_coverage(
            ["trade_history", "news_events"],
            {"trades_to_tsdb": "http://x", "events_to_weaviate": "http://y"},
        )
    assert coverage["trade_history"]["missing"] is True
    assert coverage["trade_history"]["providers"] == ["trades_to_tsdb"]
    assert coverage["news_events"]["missing"] is True


def test_get_pipeline_coverage_marks_present_when_healthy():
    with patch("tools.pipeline_tools.requests.get") as mock_get:
        mock_get.return_value = MagicMock(status_code=200)
        from tools.pipeline_tools import get_pipeline_coverage

        coverage = get_pipeline_coverage(
            ["trade_history"],
            {"trades_to_tsdb": "http://x"},
        )
    assert coverage["trade_history"]["missing"] is False
    assert coverage["trade_history"]["healthy_providers"] == ["trades_to_tsdb"]


def test_get_pipeline_coverage_unknown_signal_is_missing():
    from tools.pipeline_tools import get_pipeline_coverage

    coverage = get_pipeline_coverage(["unmapped_signal"], {})
    assert coverage["unmapped_signal"]["missing"] is True
    assert coverage["unmapped_signal"]["providers"] == []


def test_get_pipeline_coverage_zscore_needs_both_workers():
    """zscore_anomalies depends on trades_to_trending + trending_to_tsdb."""
    with patch("tools.pipeline_tools.requests.get") as mock_get:

        def _resp(url, **_):
            r = MagicMock()
            r.status_code = 200 if "trending" in url else 200
            return r

        mock_get.side_effect = _resp
        from tools.pipeline_tools import get_pipeline_coverage

        coverage = get_pipeline_coverage(
            ["zscore_anomalies"],
            {
                "trades_to_trending": "http://a",
                "trending_to_tsdb": "http://b",
            },
        )
    # both healthy → not missing
    assert coverage["zscore_anomalies"]["missing"] is False
    assert set(coverage["zscore_anomalies"]["healthy_providers"]) == {
        "trades_to_trending",
        "trending_to_tsdb",
    }


def test_propose_pipeline_change_creates_approval_request():
    from tools.pipeline_tools import propose_pipeline_change

    with patch("tools.approval_tools.add_approval_request", return_value="abc123") as mock_add:
        req_id = propose_pipeline_change("Add volatility worker", priority="high")
    assert req_id == "abc123"
    mock_add.assert_called_once()
    kwargs = mock_add.call_args.kwargs
    assert kwargs["category"] == "PIPELINE_CHANGE"
    assert kwargs["decision"]["description"] == "Add volatility worker"
    assert kwargs["decision"]["priority"] == "high"
