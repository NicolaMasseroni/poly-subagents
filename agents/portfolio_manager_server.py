"""A2A server for the Portfolio Manager sub-agent."""

from __future__ import annotations

import asyncio
import functools
import os

import uvicorn
from a2a.helpers import new_message
from a2a.helpers.proto_helpers import new_data_part
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore
from a2a.types.a2a_pb2 import AgentCapabilities, AgentCard, AgentInterface, AgentSkill
from a2a.utils.constants import PROTOCOL_VERSION_1_0, TransportProtocol
from google.protobuf.json_format import MessageToDict
from starlette.applications import Starlette

from agents import portfolio_manager

AGENT_URL = os.getenv("PORTFOLIO_MANAGER_URL", "http://localhost:8080")


class PortfolioManagerExecutor(AgentExecutor):
    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        if context.message and context.message.parts:
            part = context.message.parts[0]
            payload = MessageToDict(part.data) if part.HasField("data") else {}
        else:
            payload = {}
        langfuse_trace_id = payload.get("_langfuse_trace_id")
        langfuse_obs_id = payload.get("_langfuse_obs_id")
        fn = functools.partial(
            portfolio_manager.run,
            langfuse_trace_id=langfuse_trace_id,
            langfuse_obs_id=langfuse_obs_id,
        )
        result = await asyncio.get_running_loop().run_in_executor(None, fn)
        await event_queue.enqueue_event(new_message(parts=[new_data_part(result)]))

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        pass


def build_app() -> Starlette:
    card = AgentCard(
        name="Portfolio Manager",
        description="Stato portafoglio simulato Polymarket: posizioni, P&L, cash",
        version="1.0.0",
        skills=[AgentSkill(id="portfolio-state", name="Portfolio State")],
        supported_interfaces=[
            AgentInterface(
                url=AGENT_URL,
                protocol_binding=TransportProtocol.JSONRPC.value,
                protocol_version=PROTOCOL_VERSION_1_0,
            )
        ],
        default_input_modes=["application/json"],
        default_output_modes=["application/json"],
        capabilities=AgentCapabilities(streaming=False),
    )
    handler = DefaultRequestHandler(
        agent_card=card,
        agent_executor=PortfolioManagerExecutor(),
        task_store=InMemoryTaskStore(),
    )
    routes = create_agent_card_routes(card) + create_jsonrpc_routes(handler, "/")
    return Starlette(routes=routes)


if __name__ == "__main__":
    uvicorn.run(build_app(), host="0.0.0.0", port=8080)
