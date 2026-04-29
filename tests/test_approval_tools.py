import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import patch

import pytest


def test_add_approval_request_delegates_to_state_store():
    with patch(
        "tools.approval_tools.state_store.add_pending_approval", return_value="abc12345"
    ) as mock_add:
        from tools.approval_tools import add_approval_request

        req_id = add_approval_request(
            category="BET_PROPOSAL",
            decision={"market_id": "m1"},
            reason="strong bullish",
        )
    assert req_id == "abc12345"
    mock_add.assert_called_once()
    kwargs = mock_add.call_args.kwargs
    assert kwargs["category"] == "BET_PROPOSAL"
    assert kwargs["decision"] == {"market_id": "m1"}
    assert kwargs["reason"] == "strong bullish"
    assert len(kwargs["req_id"]) == 8


def test_add_approval_request_rejects_unknown_category():
    from tools.approval_tools import add_approval_request

    with pytest.raises(ValueError, match="Unknown category"):
        add_approval_request("UNKNOWN", {}, "r")


def test_get_pending_approvals_delegates_to_state_store():
    fake_rows = [{"id": "a", "status": "pending"}]
    with patch("tools.approval_tools.state_store.list_pending_approvals", return_value=fake_rows):
        from tools.approval_tools import get_pending_approvals

        result = get_pending_approvals()
    assert result == fake_rows


def test_resolve_approval_delegates_to_state_store():
    with patch("tools.approval_tools.state_store.resolve_pending_approval") as mock_resolve:
        from tools.approval_tools import resolve_approval

        resolve_approval("id1", "approved", note=None)
    mock_resolve.assert_called_once_with("id1", "approved", note=None)


def test_resolve_approval_rejects_invalid_status():
    from tools.approval_tools import resolve_approval

    with pytest.raises(ValueError, match="Invalid status"):
        resolve_approval("id1", "bogus")


def test_request_human_approval_polls_until_resolved():
    # first poll: still pending; second poll: approved
    statuses = iter(
        [
            {"status": "pending", "user_note": None},
            {"status": "approved", "user_note": None},
        ]
    )
    with (
        patch("tools.approval_tools.state_store.add_pending_approval", return_value="id1"),
        patch(
            "tools.approval_tools.state_store.get_approval_status",
            side_effect=lambda rid: next(statuses),
        ),
        patch("tools.approval_tools.time.sleep"),
    ):
        from tools.approval_tools import request_human_approval

        result = request_human_approval(
            "BET_PROPOSAL",
            {"m": 1},
            "reason",
            timeout_s=5,
            poll_interval_s=1,
        )
    assert result == {"id": "id1", "status": "approved", "note": None}


def test_request_human_approval_returns_timeout():
    with (
        patch("tools.approval_tools.state_store.add_pending_approval", return_value="id2"),
        patch(
            "tools.approval_tools.state_store.get_approval_status",
            return_value={"status": "pending", "user_note": None},
        ),
        patch("tools.approval_tools.state_store.resolve_pending_approval") as mock_resolve,
        patch("tools.approval_tools.time.sleep"),
        patch("tools.approval_tools.time.monotonic", side_effect=[0.0, 10.0, 20.0]),
    ):
        from tools.approval_tools import request_human_approval

        result = request_human_approval(
            "RISK_CHANGE",
            {},
            "reason",
            timeout_s=5,
            poll_interval_s=1,
        )
    assert result["status"] == "timeout"
    assert result["id"] == "id2"
    mock_resolve.assert_called_once_with("id2", "timed_out", note="Approval timed out after 5s")


def test_request_human_approval_uses_env_timeout_when_not_explicit(monkeypatch):
    monkeypatch.setenv("APPROVAL_TIMEOUT_S", "7")
    with (
        patch("tools.approval_tools.state_store.add_pending_approval", return_value="id3"),
        patch(
            "tools.approval_tools.state_store.get_approval_status",
            return_value={"status": "pending", "user_note": None},
        ),
        patch("tools.approval_tools.state_store.resolve_pending_approval"),
        patch("tools.approval_tools.time.sleep"),
        patch("tools.approval_tools.time.monotonic", side_effect=[0.0, 3.0, 10.0]),
    ):
        from tools.approval_tools import request_human_approval

        result = request_human_approval("BET_PROPOSAL", {"m": 1}, "reason", poll_interval_s=1)
    assert result["status"] == "timeout"
