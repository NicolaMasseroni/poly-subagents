"""
Trader sub-agent.
Esegue le bet approvate in modalità simulazione (paper trading only).
"""

from __future__ import annotations

import json
from typing import Any

import anthropic
from dotenv import load_dotenv
from langfuse.types import TraceContext

from observability import langfuse
from runtime_config import get_subagent_model
from tools.simulation_tools import close_simulated_position, place_simulated_bet

load_dotenv()

SYSTEM_PROMPT = """Sei il Trader di una agenzia di bet trading su Polymarket.
Esegui SOLO bet che ti vengono passate come approvate dal CEO.
NON prendere mai decisioni autonome su cosa tradare.

Per ogni bet approvata:
1. Chiama place_simulated_bet con i parametri forniti
2. Registra la conferma

Rispondi SOLO con JSON valido nel formato:
{"executions": [{"market_id": "...", "position_id": N, "outcome": "...", "stake": N, "odds": N, "status": "executed"}]}
"""

TOOLS = [
    {
        "name": "place_simulated_bet",
        "description": "Piazza una bet simulata (paper trading).",
        "input_schema": {
            "type": "object",
            "properties": {
                "market_id": {"type": "string"},
                "outcome": {"type": "string"},
                "stake": {"type": "number"},
                "odds": {"type": "number"},
                "cycle": {"type": "integer"},
                "notes": {"type": "string"},
            },
            "required": ["market_id", "outcome", "stake", "odds"],
        },
    },
    {
        "name": "close_simulated_position",
        "description": "Chiude una posizione simulata.",
        "input_schema": {
            "type": "object",
            "properties": {
                "position_id": {"type": "integer"},
                "closing_price": {"type": "number"},
            },
            "required": ["position_id", "closing_price"],
        },
    },
]

_TOOL_DISPATCH = {
    "place_simulated_bet": lambda inp: place_simulated_bet(**inp),
    "close_simulated_position": lambda inp: close_simulated_position(**inp),
}


def run(
    approved_bets: list[dict],
    cycle: int,
    langfuse_trace_id: str | None = None,
    langfuse_obs_id: str | None = None,
) -> dict:
    """
    Esegue le bet approvate.
    `approved_bets`: lista di {"market_id", "outcome", "stake", "odds"}
    Restituisce: {"executions": [...]}
    """
    if not approved_bets:
        return {"executions": []}

    client = anthropic.Anthropic()
    model = get_subagent_model()

    user_message = (
        f"Esegui queste bet approvate (ciclo {cycle}): "
        f"{json.dumps(approved_bets)}. "
        "Usa place_simulated_bet per ognuna."
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
    result: dict = {"executions": []}
    with langfuse.start_as_current_observation(
        as_type="span",
        name="trader",
        input={"bets_count": len(approved_bets), "cycle": cycle},
        trace_context=trace_ctx,
    ) as agent_span:
        turn = 0
        while True:
            turn += 1
            with langfuse.start_as_current_observation(
                as_type="generation",
                name=f"trader-llm-turn-{turn}",
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
