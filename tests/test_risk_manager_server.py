import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from a2a.helpers.proto_helpers import new_data_part
from a2a.server.agent_execution import RequestContext
from a2a.types.a2a_pb2 import Message, Role


@pytest.mark.asyncio
async def test_agent_card_served():
    """GET /.well-known/agent-card.json → 200 with correct name and skill."""
    os.environ.setdefault("RISK_MANAGER_URL", "http://localhost:8080")
    with (
        patch("agents.risk_manager.anthropic.Anthropic"),
        patch("tools.db.get_conn"),
    ):
        from agents.risk_manager_server import build_app

        asgi_app = build_app()

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=asgi_app), base_url="http://test"
    ) as client:
        response = await client.get("/.well-known/agent-card.json")

    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Risk Manager"
    assert any(s["id"] == "risk-assessment" for s in data["skills"])


@pytest.mark.asyncio
async def test_executor_calls_run_with_payload():
    """Executor extracts the data part and calls risk_manager.run() with the correct payload."""
    with (
        patch("agents.risk_manager.anthropic.Anthropic"),
        patch("tools.db.get_conn"),
    ):
        from agents.risk_manager_server import RiskManagerExecutor

    context = MagicMock(spec=RequestContext)
    context.task_id = "t1"
    context.context_id = "c1"
    context.message = Message(
        role=Role.ROLE_USER,
        message_id="m1",
        parts=[
            new_data_part({"bets": [{"market_id": "m1", "outcome": "YES", "suggested_stake": 50}]})
        ],
    )
    queue = AsyncMock()

    with patch("agents.risk_manager.run", return_value={"assessments": []}) as mock_run:
        executor = RiskManagerExecutor()
        await executor.execute(context, queue)

    mock_run.assert_called_once_with(
        {"bets": [{"market_id": "m1", "outcome": "YES", "suggested_stake": 50}]},
        langfuse_trace_id=None,
        langfuse_obs_id=None,
    )


@pytest.mark.asyncio
async def test_executor_emits_single_message():
    """Executor emits exactly one Message (message-only A2A pattern)."""
    with (
        patch("agents.risk_manager.anthropic.Anthropic"),
        patch("tools.db.get_conn"),
    ):
        from agents.risk_manager_server import RiskManagerExecutor

    context = MagicMock(spec=RequestContext)
    context.task_id = "t1"
    context.context_id = "c1"
    context.message = Message(
        role=Role.ROLE_USER,
        message_id="m1",
        parts=[
            new_data_part({"bets": [{"market_id": "m1", "outcome": "YES", "suggested_stake": 50}]})
        ],
    )
    queue = AsyncMock()

    with patch("agents.risk_manager.run", return_value={"assessments": [{"market_id": "m1"}]}):
        executor = RiskManagerExecutor()
        await executor.execute(context, queue)

    assert queue.enqueue_event.call_count == 1
    from a2a.types.a2a_pb2 import Message as A2AMessage

    emitted = queue.enqueue_event.call_args[0][0]
    assert isinstance(emitted, A2AMessage)


@pytest.mark.asyncio
async def test_executor_handles_empty_parts():
    """Executor falls back to empty payload when message has no parts."""
    with (
        patch("agents.risk_manager.anthropic.Anthropic"),
        patch("tools.db.get_conn"),
    ):
        from agents.risk_manager_server import RiskManagerExecutor

    context = MagicMock(spec=RequestContext)
    context.task_id = "t1"
    context.context_id = "c1"
    context.message = Message(role=Role.ROLE_USER, message_id="m1")
    queue = AsyncMock()

    with patch("agents.risk_manager.run", return_value={"assessments": []}) as mock_run:
        executor = RiskManagerExecutor()
        await executor.execute(context, queue)

    mock_run.assert_called_once_with({}, langfuse_trace_id=None, langfuse_obs_id=None)
