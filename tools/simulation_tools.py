"""CRUD sulla tabella simulated_trades (paper trading)."""

from __future__ import annotations

from datetime import UTC, datetime

from tools.db import get_conn


def place_simulated_bet(
    market_id: str,
    outcome: str,
    stake: float,
    odds: float,
    cycle: int | None = None,
    notes: str | None = None,
) -> dict:
    """
    Inserisce un bet simulato. Restituisce:
    {position_id, market_id, outcome, stake, odds, opened_at}
    """
    sql = """
        INSERT INTO simulated_trades (market_id, outcome, stake, odds, cycle, notes)
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING id, opened_at
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, (market_id, outcome, float(stake), float(odds), cycle, notes))
            row = cur.fetchone()
        conn.commit()
    finally:
        conn.close()
    return {
        "position_id": row[0],
        "market_id": market_id,
        "outcome": outcome,
        "stake": float(stake),
        "odds": float(odds),
        "opened_at": row[1].isoformat() if row[1] else None,
    }


def close_simulated_position(position_id: int, closing_price: float) -> dict:
    """
    Chiude una posizione simulata e calcola il P&L.
    P&L = stake * (odds * closing_price - 1)
    Restituisce: {position_id, status, pnl, closed_at}
    """
    select_sql = "SELECT stake, odds FROM simulated_trades WHERE id = %s"
    update_sql = """
        UPDATE simulated_trades
        SET status = 'closed', closed_at = NOW(), pnl = %s
        WHERE id = %s
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(select_sql, (position_id,))
            row = cur.fetchone()
            if row is None:
                return {"error": f"Position {position_id} not found"}
            stake, odds = float(row[0]), float(row[1])
            pnl = round(stake * (odds * closing_price - 1), 2)
            cur.execute(update_sql, (pnl, position_id))
        conn.commit()
    finally:
        conn.close()
    return {
        "position_id": position_id,
        "status": "closed",
        "pnl": pnl,
        "closed_at": datetime.now(UTC).isoformat(),
    }


def get_open_positions() -> list[dict]:
    """Tutte le posizioni con status='open'."""
    sql = """
        SELECT id, market_id, outcome, stake, odds, opened_at, cycle
        FROM simulated_trades
        WHERE status = 'open'
        ORDER BY opened_at DESC
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]
    finally:
        conn.close()


def get_simulated_portfolio() -> dict:
    """
    Stato aggregato del portafoglio simulato.
    Restituisce: {open_positions_count, total_exposure, total_pnl_realized, positions}
    """
    positions = get_open_positions()
    total_exposure = sum(float(p["stake"]) for p in positions)

    pnl_sql = "SELECT COALESCE(SUM(pnl), 0) FROM simulated_trades WHERE status = 'closed'"
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(pnl_sql)
            total_pnl = float(cur.fetchone()[0])
    finally:
        conn.close()

    return {
        "open_positions_count": len(positions),
        "total_exposure": total_exposure,
        "total_pnl_realized": total_pnl,
        "positions": positions,
    }


def get_pnl_history(days: int = 7) -> list[dict]:
    """P&L giornaliero delle ultime `days` giornate (solo posizioni chiuse)."""
    sql = """
        SELECT
            DATE(closed_at)   AS day,
            SUM(pnl)          AS daily_pnl,
            COUNT(*)          AS trades_closed
        FROM simulated_trades
        WHERE status = 'closed'
          AND closed_at >= NOW() - (%s || ' days')::interval
        GROUP BY day
        ORDER BY day DESC
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, (str(days),))
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]
    finally:
        conn.close()
