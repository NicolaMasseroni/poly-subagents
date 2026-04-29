"""
Accesso notizie collegate ai mercati.

Schema reale (stream/infra/schema.sql):
- `relevantnews(event_slug, event_id, event_title, news_title, news_description, news_source, news_time)`
- `events(event_id, slug, ...)`
- `markets(market_id, event_id, slug, ...)`

Il link è a livello di EVENTO: una news si propaga a tutti i mercati del suo evento.
Identificatore CEO `market_id` = `markets.slug`.
"""

from __future__ import annotations

import os

import weaviate
from dotenv import load_dotenv

from tools.db import get_conn

load_dotenv()

_WEAVIATE_COLLECTION = "Events"


def _get_weaviate_client():
    http_host = os.getenv("WEAVIATE_HOST", "192.168.0.250")
    grpc_host = os.getenv("WEAVIATE_GRPC_HOST", http_host)
    openai_key = os.getenv("OPENAI_APIKEY", "")
    return weaviate.connect_to_custom(
        http_host=http_host,
        http_port=int(os.getenv("WEAVIATE_PORT", "8888")),
        http_secure=False,
        grpc_host=grpc_host,
        grpc_port=int(os.getenv("WEAVIATE_GRPC_PORT", "50051")),
        grpc_secure=False,
        headers={"X-Openai-Api-Key": openai_key},
    )


def get_recent_news_links(hours: int = 24) -> list[dict]:
    """
    News pubblicate nelle ultime `hours` ore, esplose a livello di mercato
    via JOIN `relevantnews → events → markets`.

    Una singola riga di `relevantnews` genera N righe nell'output (una per
    mercato attivo dell'evento). Output: {market_id, event_slug, event_title,
    title, description, source, published_at}.
    """
    sql = """
        SELECT
            m.slug           AS market_id,
            rn.event_slug    AS event_slug,
            rn.event_title   AS event_title,
            rn.news_title    AS title,
            rn.news_description AS description,
            rn.news_source   AS source,
            rn.news_time     AS published_at
        FROM relevantnews rn
        JOIN events  e ON e.slug = rn.event_slug
        JOIN markets m ON m.event_id = e.event_id
        WHERE rn.news_time >= NOW() - (%s || ' hours')::interval
          AND m.active = TRUE AND m.closed = FALSE
        ORDER BY rn.news_time DESC
        LIMIT 200
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, (str(hours),))
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]
    finally:
        conn.close()


def search_news_by_market(market_id: str, limit: int = 10) -> list[dict]:
    """
    Notizie per un mercato specifico (ricercate per evento padre).
    `market_id` = market slug.
    """
    sql = """
        SELECT
            rn.news_title       AS title,
            rn.news_description AS description,
            rn.news_source      AS source,
            rn.news_time        AS published_at
        FROM relevantnews rn
        JOIN events  e ON e.slug = rn.event_slug
        JOIN markets m ON m.event_id = e.event_id
        WHERE m.slug = %s
        ORDER BY rn.news_time DESC
        LIMIT %s
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, (market_id, limit))
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]
    finally:
        conn.close()


def semantic_search(query: str, limit: int = 10) -> list[dict]:
    """Ricerca semantica su Weaviate nella collection Events."""
    client = _get_weaviate_client()
    try:
        collection = client.collections.get(_WEAVIATE_COLLECTION)
        result = collection.query.near_text(
            query=query,
            limit=limit,
        )
        return [
            {
                "title": obj.properties.get("title", ""),
                "url": obj.properties.get("url", ""),
                "content": obj.properties.get("content", ""),
                "slug": obj.properties.get("slug", ""),
            }
            for obj in result.objects
        ]
    finally:
        client.close()
