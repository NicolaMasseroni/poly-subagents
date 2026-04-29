"""
Lettura dati di mercato da TimescaleDB + health check dei worker.

Allineato allo schema reale della pipeline (stream/infra/schema.sql):
- `trades(timestamp, slug, event_slug, asset, outcome, side, price, size, volume, ...)`
- `trending(slug, window_end, volume_zscore, trades_zscore, volume_total, ...)`

Identificatore canonico del "market" nel CEO = `market_id` a livello di API,
contiene il VALORE di `trades.slug` / `trending.slug` / `markets.slug`.
"""

from __future__ import annotations

import requests

from tools.db import get_conn


def get_trending_markets(hours: int = 24, limit: int = 20) -> list[dict]:
    """
    Mercati con maggior volume negli ultimi `hours`.
    Restituisce: {market_id, volume, zscore, top_outcome}
    """
    sql = """
        WITH recent_trades AS (
            SELECT
                slug,
                SUM(volume)                                    AS total_volume,
                mode() WITHIN GROUP (ORDER BY outcome)         AS top_outcome
            FROM trades
            WHERE timestamp >= NOW() - (%s || ' hours')::interval
            GROUP BY slug
        ),
        latest_zscore AS (
            SELECT DISTINCT ON (slug)
                slug,
                volume_zscore
            FROM trending
            WHERE window_end >= NOW() - (%s || ' hours')::interval
            ORDER BY slug, window_end DESC
        )
        SELECT
            rt.slug                          AS market_id,
            rt.total_volume                  AS volume,
            COALESCE(lz.volume_zscore, 0)    AS zscore,
            rt.top_outcome                   AS top_outcome
        FROM recent_trades rt
        LEFT JOIN latest_zscore lz USING (slug)
        ORDER BY rt.total_volume DESC NULLS LAST
        LIMIT %s
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, (str(hours), str(hours), limit))
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]
    finally:
        conn.close()


def get_trade_volume(market_id: str, hours: int = 24) -> dict:
    """Volume totale e numero trade per un mercato nelle ultime `hours` ore.

    `market_id` è la slug del mercato (colonna `trades.slug`).
    """
    sql = """
        SELECT
            COUNT(*)    AS trade_count,
            SUM(volume) AS total_volume,
            AVG(price)  AS avg_price
        FROM trades
        WHERE slug = %s
          AND timestamp >= NOW() - (%s || ' hours')::interval
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, (market_id, str(hours)))
            row = cur.fetchone()
            return {
                "market_id": market_id,
                "trade_count": int(row[0] or 0),
                "total_volume": float(row[1] or 0),
                "avg_price": float(row[2] or 0),
            }
    finally:
        conn.close()


def get_price_history(market_id: str, hours: int = 24) -> list[dict]:
    """Serie temporale oraria del prezzo per un mercato."""
    sql = """
        SELECT
            time_bucket('1 hour', timestamp) AS ts,
            AVG(price)                        AS price
        FROM trades
        WHERE slug = %s
          AND timestamp >= NOW() - (%s || ' hours')::interval
        GROUP BY ts
        ORDER BY ts ASC
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, (market_id, str(hours)))
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]
    finally:
        conn.close()


def get_zscore_anomalies(threshold: float = 2.0, hours: int = 24) -> list[dict]:
    """
    Mercati con z-score anomalo sul volume (`trending.volume_zscore >= threshold`).
    Prende l'ultima finestra disponibile per ogni mercato nell'intervallo.
    """
    sql = """
        SELECT DISTINCT ON (slug)
            slug          AS market_id,
            volume_zscore AS zscore,
            volume_total  AS volume,
            window_end    AS timestamp
        FROM trending
        WHERE window_end >= NOW() - (%s || ' hours')::interval
          AND volume_zscore >= %s
        ORDER BY slug, window_end DESC
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, (str(hours), threshold))
            cols = [d[0] for d in cur.description or []]
            return [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]
    finally:
        conn.close()


def check_worker_health(worker_urls: dict[str, str]) -> dict[str, str]:
    """
    Controlla lo stato /healthz di ogni worker.
    Restituisce {worker_name: "healthy" | "degraded" | "down"}.
    - "healthy": HTTP 200
    - "degraded": HTTP non-200
    - "down": connessione fallita
    """
    results = {}
    for name, base_url in worker_urls.items():
        try:
            resp = requests.get(f"{base_url}/healthz", timeout=3)
            results[name] = "healthy" if resp.status_code == 200 else "degraded"
        except Exception:
            results[name] = "down"
    return results


# Mappa segnale → worker che lo produce. Usata da get_pipeline_coverage
# per determinare se i dati che il CEO si aspetta sono effettivamente prodotti.
_SIGNAL_PROVIDERS: dict[str, list[str]] = {
    "trade_history": ["trades_to_tsdb"],
    "market_trends": ["trades_to_tsdb"],
    "zscore_anomalies": ["trades_to_trending", "trending_to_tsdb"],
    "news_events": ["events_to_weaviate"],
    "news_feed": ["news_to_kafka"],
    "news_links": ["get_relevant_news"],
}


def get_pipeline_coverage(
    needed_signals: list[str],
    worker_urls: dict[str, str],
    health: dict[str, str] | None = None,
) -> dict[str, dict]:
    """
    Per ogni segnale richiesto, restituisce quali worker lo producono e
    se almeno uno è healthy. Un segnale è `missing` se non ha provider
    mappati oppure se nessun provider è healthy.
    Se `health` è fornito, evita una seconda chiamata a check_worker_health.
    """
    if health is None:
        health = check_worker_health(worker_urls)
    coverage: dict[str, dict] = {}
    for signal in needed_signals:
        providers = _SIGNAL_PROVIDERS.get(signal, [])
        healthy = [p for p in providers if health.get(p) == "healthy"]
        coverage[signal] = {
            "providers": providers,
            "healthy_providers": healthy,
            "missing": not providers or not healthy,
        }
    return coverage


def propose_pipeline_change(description: str, priority: str = "normal") -> str:
    """
    Crea una PIPELINE_CHANGE approval request. Restituisce l'ID della richiesta.
    Wrapper thin su `tools.approval_tools.add_approval_request`.
    """
    from tools.approval_tools import add_approval_request

    return add_approval_request(
        category="PIPELINE_CHANGE",
        decision={"description": description, "priority": priority},
        reason=description,
    )
