"""CRUD PostgreSQL per lo stato persistente del CEO agent."""

from __future__ import annotations

import json

from tools.db import get_conn


def load_state() -> dict:
    """Restituisce la riga singleton di ceo_state come dict, oppure default."""
    sql = """
        SELECT id, cycle, last_run, simulation_balance, execution_enabled, risk_limits, pipeline_health
        FROM ceo_state WHERE id = 1
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
            row = cur.fetchone()
            if row is None:
                return {
                    "cycle": 0,
                    "last_run": None,
                    "simulation_balance": 10000,
                    "execution_enabled": True,
                    "risk_limits": {},
                    "pipeline_health": {"last_checked": None, "issues": []},
                }
            cols = [d[0] for d in cur.description]
            data = dict(zip(cols, row, strict=True))
            last_run = data["last_run"]
            return {
                "cycle": int(data["cycle"]),
                "last_run": last_run.isoformat() if last_run is not None else None,
                "simulation_balance": float(data["simulation_balance"]),
                "execution_enabled": bool(data["execution_enabled"]),
                "risk_limits": data["risk_limits"],
                "pipeline_health": data["pipeline_health"],
            }
    finally:
        conn.close()


def save_state(state: dict) -> None:
    """Aggiorna la riga singleton di ceo_state."""
    sql = """
        UPDATE ceo_state
           SET cycle = %s,
               last_run = %s,
               simulation_balance = %s,
               execution_enabled = %s,
               risk_limits = %s::jsonb,
               pipeline_health = %s::jsonb,
               updated_at = NOW()
         WHERE id = 1
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                sql,
                (
                    state["cycle"],
                    state["last_run"],
                    state["simulation_balance"],
                    state["execution_enabled"],
                    json.dumps(state["risk_limits"]),
                    json.dumps(state["pipeline_health"]),
                ),
            )
        conn.commit()
    finally:
        conn.close()


def add_pending_approval(req_id: str, category: str, decision: dict, reason: str) -> str:
    sql = """
        INSERT INTO pending_approvals (id, category, decision, reason)
        VALUES (%s, %s, %s::jsonb, %s)
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, (req_id, category, json.dumps(decision), reason))
        conn.commit()
        return req_id
    finally:
        conn.close()


def list_pending_approvals() -> list[dict]:
    sql = """
        SELECT id, category, decision, reason, status, user_note, created_at, resolved_at
        FROM pending_approvals
        WHERE status = 'pending'
        ORDER BY created_at ASC
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]
    finally:
        conn.close()


def resolve_pending_approval(req_id: str, status: str, note: str | None = None) -> None:
    if status not in {"approved", "rejected", "modified", "timed_out"}:
        raise ValueError(f"Invalid status: {status!r}")
    sql = """
        UPDATE pending_approvals
           SET status = %s, user_note = %s, resolved_at = NOW()
         WHERE id = %s AND status = 'pending'
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, (status, note, req_id))
            if cur.rowcount == 0:
                raise ValueError(f"Approval {req_id!r} not found or already resolved")
        conn.commit()
    finally:
        conn.close()


def get_approval_status(req_id: str) -> dict | None:
    """Ritorna {status, user_note} o None se l'ID non esiste."""
    sql = "SELECT status, user_note FROM pending_approvals WHERE id = %s"
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, (req_id,))
            row = cur.fetchone()
            if row is None:
                return None
            return {"status": row[0], "user_note": row[1]}
    finally:
        conn.close()


def count_pending_approvals() -> int:
    """Conta le approval attualmente in stato pending."""
    sql = "SELECT COUNT(*) FROM pending_approvals WHERE status = 'pending'"
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
            row = cur.fetchone()
            return int(row[0] or 0)
    finally:
        conn.close()


def set_execution_enabled(enabled: bool) -> None:
    """Aggiorna lo stato di esecuzione dei cicli CEO."""
    sql = """
        UPDATE ceo_state
           SET execution_enabled = %s,
               updated_at = NOW()
         WHERE id = 1
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, (enabled,))
            if cur.rowcount == 0:
                raise ValueError("CEO state row not found")
        conn.commit()
    finally:
        conn.close()


def register_cycle_report(cycle: int, report_path: str) -> None:
    sql = """
        INSERT INTO cycle_reports_index (cycle, report_path)
        VALUES (%s, %s)
        ON CONFLICT (cycle) DO UPDATE
           SET report_path = EXCLUDED.report_path,
               written_at = NOW()
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, (cycle, report_path))
        conn.commit()
    finally:
        conn.close()
