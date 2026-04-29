"""
Portfolio Manager sub-agent.
Stato del portafoglio simulato: posizioni aperte, P&L, cash disponibile.
"""

from __future__ import annotations

import json
from typing import Any

import anthropic
from dotenv import load_dotenv
from langfuse.types import TraceContext

from observability import langfuse
from runtime_config import get_subagent_model
from tools.simulation_tools import (
    get_open_positions,
    get_pnl_history,
    get_simulated_portfolio,
)

load_dotenv()

SYSTEM_PROMPT = """Sei il Portfolio Manager di una agenzia di bet trading su Polymarket.
Analizza il portafoglio simulato corrente e produci una sintesi operativa.

Includi:
- cash_available: capitale iniziale meno esposizione corrente
- performance_summary: andamento P&L recente
- position_alerts: posizioni che richiedono attenzione (posizioni molto vecchie, odds deteriorate)
- allocation_recommendation: percentuale del cash che raccomandi di allocare nel prossimo ciclo

Rispondi SOLO con JSON valido nel formato:
{
  "cash_available": N,
  "total_exposure": N,
  "total_pnl_realized": N,
  "open_positions_count": N,
  "performance_summary": "...",
  "position_alerts": [],
  "allocation_recommendation": N
}
"""

TOOLS = [
    {
        "name": "get_simulated_portfolio",
        "description": "Stato aggregato portafoglio: posizioni aperte, esposizione, P&L.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_pnl_history",
        "description": "P&L giornaliero delle ultime N giornate.",
        "input_schema": {
            "type": "object",
            "properties": {"days": {"type": "integer", "default": 7}},
        },
    },
    {
        "name": "get_open_positions",
        "description": "Lista dettagliata delle posizioni aperte.",
        "input_schema": {"type": "object", "properties": {}},
    },
]

_TOOL_DISPATCH = {
    "get_simulated_portfolio": lambda inp: get_simulated_portfolio(),
    "get_pnl_history": lambda inp: get_pnl_history(**inp),
    "get_open_positions": lambda inp: get_open_positions(),
}


def _get_initial_balance() -> float:
    from tools.state_store import load_state

    return float(load_state().get("simulation_balance", 10000))


def run(
    langfuse_trace_id: str | None = None,
    langfuse_obs_id: str | None = None,
) -> dict:
    """Esegue il Portfolio Manager. Restituisce lo stato del portafoglio."""
    client = anthropic.Anthropic()
    model = get_subagent_model()
    initial_balance = _get_initial_balance()

    user_message = (
        f"Analizza il portafoglio simulato. Capitale iniziale: {initial_balance}. "
        "Usa i tool per raccogliere i dati e produci la sintesi operativa."
    )
    messages: list[dict[str, Any]] = [{"role": "user", "content": user_message}]

    if langfuse_trace_id:
        trace_ctx: TraceContext | None = (
            TraceContext(trace_id=langfuse_trace_id, parent_span_id=langfuse_obs_id)
            if langfuse_obs_id
            else TraceContext(trace_id=langfuse_trace_id)
        )
    else:
        trace_ctx = None
    result: dict = {}
    with langfuse.start_as_current_observation(
        as_type="span",
        name="portfolio-manager",
        input={"initial_balance": initial_balance},
        trace_context=trace_ctx,
    ) as agent_span:
        turn = 0
        while True:
            turn += 1
            with langfuse.start_as_current_observation(
                as_type="generation",
                name=f"portfolio-manager-llm-turn-{turn}",
                model=model,
                input=messages,
            ) as gen:
                response = client.messages.create(
                    model=model,
                    max_tokens=2048,
                    system=[
                        {
                            "type": "text",
                            "text": SYSTEM_PROMPT,
                            "cache_control": {"type": "ephemeral"},
                        }
                    ],
                    tools=TOOLS,  # type: ignore[arg-type]
                    messages=messages,  # type: ignore[arg-type]
                )
                gen.update(
                    output=json.dumps(
                        [
                            b.model_dump() if hasattr(b, "model_dump") else str(b)
                            for b in response.content
                        ],
                        default=str,
                    ),
                    usage={
                        "input": response.usage.input_tokens,
                        "output": response.usage.output_tokens,
                    },
                    metadata={"stop_reason": response.stop_reason},
                )

            if response.stop_reason == "end_turn":
                for block in response.content:
                    if hasattr(block, "text"):
                        text = block.text.strip()
                        start = text.find("{")
                        if start != -1:
                            try:
                                result = json.JSONDecoder().raw_decode(text[start:])[0]
                                break
                            except json.JSONDecodeError:
                                pass
                agent_span.update(output=result)
                break

            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    with langfuse.start_as_current_observation(
                        as_type="span",
                        name=f"tool:{block.name}",
                        input=block.input,
                    ) as tool_span:
                        fn = _TOOL_DISPATCH.get(block.name)
                        tool_result = (
                            fn(block.input) if fn else {"error": f"Unknown tool: {block.name}"}
                        )
                        tool_span.update(output=json.dumps(tool_result, default=str))
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": json.dumps(tool_result, default=str),
                        }
                    )

            if not tool_results:
                break
            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": tool_results})

    langfuse.flush()
    return result
