import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from decimal import Decimal
from unittest.mock import MagicMock, patch


def _make_mock_conn():
    conn = MagicMock()
    cur = MagicMock()
    cur.__enter__ = lambda s: cur
    cur.__exit__ = MagicMock(return_value=False)
    conn.cursor.return_value = cur
    conn.__enter__ = lambda s: conn
    conn.__exit__ = MagicMock(return_value=False)
    return conn, cur


def test_place_simulated_bet_returns_id():
    conn, cur = _make_mock_conn()
    cur.fetchone.return_value = (42, None)
    with patch("tools.simulation_tools.get_conn", return_value=conn):
        from tools.simulation_tools import place_simulated_bet

        result = place_simulated_bet(
            market_id="market-1",
            outcome="YES",
            stake=50.0,
            odds=1.8,
            cycle=1,
        )
    assert result["position_id"] == 42
    assert result["market_id"] == "market-1"


def test_get_open_positions_returns_list():
    conn, cur = _make_mock_conn()
    cur.fetchall.return_value = [(1, "market-1", "YES", Decimal("50.00"), Decimal("1.8"), "open")]
    cur.description = [("id",), ("market_id",), ("outcome",), ("stake",), ("odds",), ("status",)]
    with patch("tools.simulation_tools.get_conn", return_value=conn):
        from tools.simulation_tools import get_open_positions

        result = get_open_positions()
    assert len(result) == 1
    assert result[0]["outcome"] == "YES"


def test_close_simulated_position_marks_closed():
    conn, cur = _make_mock_conn()
    cur.fetchone.return_value = (Decimal("50.00"), Decimal("1.8"))
    with patch("tools.simulation_tools.get_conn", return_value=conn):
        from tools.simulation_tools import close_simulated_position

        result = close_simulated_position(position_id=1, closing_price=0.9)
    assert result["status"] == "closed"
    assert result["position_id"] == 1
