import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datetime import UTC
from unittest.mock import MagicMock, patch


def _mock_conn():
    conn = MagicMock()
    cursor = MagicMock()
    cursor.__enter__ = lambda s: cursor
    cursor.__exit__ = MagicMock(return_value=False)
    conn.cursor.return_value = cursor
    return conn, cursor


def test_load_state_returns_full_row():
    from datetime import datetime

    dt = datetime(2026, 4, 16, 10, 0, 0, tzinfo=UTC)
    conn, cursor = _mock_conn()
    cursor.fetchone.return_value = (
        1,
        5,
        dt,
        10000,
        True,
        {"max_stake_per_bet": 100},
        {"last_checked": None, "issues": []},
    )
    cursor.description = [
        ("id",),
        ("cycle",),
        ("last_run",),
        ("simulation_balance",),
        ("execution_enabled",),
        ("risk_limits",),
        ("pipeline_health",),
    ]
    with patch("tools.state_store.get_conn", return_value=conn):
        from tools.state_store import load_state

        state = load_state()
    assert state["cycle"] == 5
    assert state["last_run"] == "2026-04-16T10:00:00+00:00"
    assert state["simulation_balance"] == 10000
    assert state["execution_enabled"] is True
    assert state["risk_limits"] == {"max_stake_per_bet": 100}
    assert state["pipeline_health"] == {"last_checked": None, "issues": []}


def test_save_state_executes_update():
    import json as _json

    conn, cursor = _mock_conn()
    with patch("tools.state_store.get_conn", return_value=conn):
        from tools.state_store import save_state

        save_state(
            {
                "cycle": 7,
                "last_run": "2026-04-16T11:00:00+00:00",
                "simulation_balance": 9500,
                "execution_enabled": False,
                "risk_limits": {"x": 1},
                "pipeline_health": {"last_checked": "t", "issues": []},
            }
        )
    cursor.execute.assert_called_once()
    sql, params = cursor.execute.call_args[0]
    assert "UPDATE ceo_state" in sql
    assert params == (
        7,
        "2026-04-16T11:00:00+00:00",
        9500,
        False,
        _json.dumps({"x": 1}),
        _json.dumps({"last_checked": "t", "issues": []}),
    )
    conn.commit.assert_called_once()


def test_add_pending_approval_inserts_row():
    conn, cursor = _mock_conn()
    with patch("tools.state_store.get_conn", return_value=conn):
        from tools.state_store import add_pending_approval

        req_id = add_pending_approval(
            req_id="abc12345",
            category="BET_PROPOSAL",
            decision={"market_id": "m1"},
            reason="bullish",
        )
    assert req_id == "abc12345"
    cursor.execute.assert_called_once()
    assert "INSERT INTO pending_approvals" in cursor.execute.call_args[0][0]
    conn.commit.assert_called_once()


def test_list_pending_approvals_filters_status():
    conn, cursor = _mock_conn()
    cursor.fetchall.return_value = [
        (
            "id1",
            "BET_PROPOSAL",
            {"x": 1},
            "reason",
            "pending",
            None,
            "2026-04-16T10:00:00+00:00",
            None,
        ),
    ]
    cursor.description = [
        ("id",),
        ("category",),
        ("decision",),
        ("reason",),
        ("status",),
        ("user_note",),
        ("created_at",),
        ("resolved_at",),
    ]
    with patch("tools.state_store.get_conn", return_value=conn):
        from tools.state_store import list_pending_approvals

        rows = list_pending_approvals()
    assert len(rows) == 1
    assert rows[0]["id"] == "id1"
    assert rows[0]["status"] == "pending"


def test_resolve_pending_approval_updates_row():
    conn, cursor = _mock_conn()
    cursor.rowcount = 1
    with patch("tools.state_store.get_conn", return_value=conn):
        from tools.state_store import resolve_pending_approval

        resolve_pending_approval("id1", "approved", note=None)
    cursor.execute.assert_called_once()
    assert "UPDATE pending_approvals" in cursor.execute.call_args[0][0]


def test_resolve_pending_approval_raises_when_not_found():
    import pytest

    conn, cursor = _mock_conn()
    cursor.rowcount = 0
    with patch("tools.state_store.get_conn", return_value=conn):
        from tools.state_store import resolve_pending_approval

        with pytest.raises(ValueError, match="not found"):
            resolve_pending_approval("unknown", "approved")


def test_resolve_pending_approval_accepts_timed_out():
    conn, cursor = _mock_conn()
    cursor.rowcount = 1
    with patch("tools.state_store.get_conn", return_value=conn):
        from tools.state_store import resolve_pending_approval

        resolve_pending_approval("id1", "timed_out", note="Approval timed out after 5s")
    cursor.execute.assert_called_once()


def test_get_approval_status_returns_current_status():
    conn, cursor = _mock_conn()
    cursor.fetchone.return_value = ("approved", "optional note")
    with patch("tools.state_store.get_conn", return_value=conn):
        from tools.state_store import get_approval_status

        result = get_approval_status("id1")
    assert result == {"status": "approved", "user_note": "optional note"}


def test_count_pending_approvals_returns_integer():
    conn, cursor = _mock_conn()
    cursor.fetchone.return_value = (4,)
    with patch("tools.state_store.get_conn", return_value=conn):
        from tools.state_store import count_pending_approvals

        result = count_pending_approvals()
    assert result == 4


def test_set_execution_enabled_updates_row():
    conn, cursor = _mock_conn()
    cursor.rowcount = 1
    with patch("tools.state_store.get_conn", return_value=conn):
        from tools.state_store import set_execution_enabled

        set_execution_enabled(False)
    cursor.execute.assert_called_once()
    sql, params = cursor.execute.call_args[0]
    assert "UPDATE ceo_state" in sql
    assert params == (False,)
    conn.commit.assert_called_once()


def test_register_cycle_report_inserts_row():
    conn, cursor = _mock_conn()
    with patch("tools.state_store.get_conn", return_value=conn):
        from tools.state_store import register_cycle_report

        register_cycle_report(cycle=7, report_path="/app/reports/x.md")
    cursor.execute.assert_called_once()
    sql = cursor.execute.call_args[0][0]
    assert "INSERT INTO cycle_reports_index" in sql
    assert "ON CONFLICT" in sql
    conn.commit.assert_called_once()
