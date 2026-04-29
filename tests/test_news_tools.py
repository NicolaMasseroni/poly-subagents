import contextlib
import importlib
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import MagicMock, create_autospec, patch

import weaviate


def _mock_conn():
    conn = MagicMock()
    cursor = MagicMock()
    cursor.__enter__ = lambda s: cursor
    cursor.__exit__ = MagicMock(return_value=False)
    conn.cursor.return_value = cursor
    return conn, cursor


def test_get_recent_news_links_joins_events_and_markets():
    conn, cursor = _mock_conn()
    cursor.fetchall.return_value = [
        (
            "trump-vs-kamala-2024",
            "us-election-2024",
            "US Presidential Election 2024",
            "Breaking: Poll shift",
            "Short description",
            "Reuters",
            "2026-04-16T10:00:00+00:00",
        ),
    ]
    cursor.description = [
        ("market_id",),
        ("event_slug",),
        ("event_title",),
        ("title",),
        ("description",),
        ("source",),
        ("published_at",),
    ]
    with patch("tools.news_tools.get_conn", return_value=conn):
        from tools.news_tools import get_recent_news_links

        result = get_recent_news_links(hours=12)
    assert len(result) == 1
    assert result[0]["market_id"] == "trump-vs-kamala-2024"
    assert result[0]["event_slug"] == "us-election-2024"
    assert result[0]["source"] == "Reuters"
    # verify JOIN structure
    sql = cursor.execute.call_args[0][0]
    assert "FROM relevantnews" in sql
    assert "JOIN events" in sql
    assert "JOIN markets" in sql


def test_search_news_by_market_filters_by_slug():
    conn, cursor = _mock_conn()
    cursor.fetchall.return_value = [
        ("Big news", "Description", "Reuters", "2026-04-16T10:00:00+00:00"),
    ]
    cursor.description = [("title",), ("description",), ("source",), ("published_at",)]
    with patch("tools.news_tools.get_conn", return_value=conn):
        from tools.news_tools import search_news_by_market

        result = search_news_by_market("trump-vs-kamala-2024", limit=5)
    assert len(result) == 1
    assert result[0]["title"] == "Big news"
    assert result[0]["source"] == "Reuters"
    sql = cursor.execute.call_args[0][0]
    assert "WHERE m.slug = %s" in sql


def test_get_weaviate_client_uses_correct_param_names():
    """Regression: weaviate 4.x uses 'headers', not 'additional_headers'."""
    mock_connect = create_autospec(weaviate.connect_to_custom)
    with patch("tools.news_tools.weaviate.connect_to_custom", mock_connect):
        import tools.news_tools as nt

        importlib.reload(nt)
        with contextlib.suppress(Exception):
            nt._get_weaviate_client()
        _, kwargs = mock_connect.call_args
        assert "headers" in kwargs, "must use 'headers', not 'additional_headers'"
        assert "additional_headers" not in kwargs


def test_semantic_search_returns_results():
    mock_collection = MagicMock()
    mock_collection.query.near_text.return_value = MagicMock(
        objects=[
            MagicMock(
                properties={
                    "title": "Trump wins",
                    "url": "http://x.com",
                    "content": "...",
                    "slug": "test",
                }
            )
        ]
    )
    mock_client = MagicMock()
    mock_client.collections.get.return_value = mock_collection
    with patch("tools.news_tools._get_weaviate_client", return_value=mock_client):
        from tools.news_tools import semantic_search

        result = semantic_search("US election 2026", limit=5)
    assert len(result) == 1
    assert result[0]["title"] == "Trump wins"
