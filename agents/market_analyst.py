"""
Market Analyst sub-agent.
Analisi quantitativa dei mercati Polymarket da TimescaleDB.
Restituisce MarketSignals: lista mercati con segnale, z-score, volume.
"""

from __future__ import annotations

import json
from typing import Any

import anthropic
from dotenv import load_dotenv
from langfuse.types import TraceContext

from observability import langfuse
from runtime_config import get_subagent_model
from tools.pipeline_tools import (
    get_price_history,
    get_trade_volume,
    get_trending_markets,
    get_zscore_anomalies,
)

load_dotenv()

SYSTEM_PROMPT = """Sei il Market Analyst di una agenzia di bet trading su Polymarket.
Il tuo compito è analizzare i dati quantitativi dei mercati (volume, prezzi, z-score) e
produrre una lista di segnali trading.

Per ogni mercato rilevante produci:
- segnale: "bullish" | "bearish" | "neutral"
- forza: 1-5 (5 = segnale molto forte)
- ragionamento: spiegazione concisa (max 2 frasi)

Alla fine rispondi SOLO con JSON valido nel formato:
{"signals": [{"market_id": "...", "signal": "...", "strength": N, "volume": N, "zscore": N, "reasoning": "..."}]}
"""

TOOLS = [
    {
        "name": "get_trending_markets",
        "description": "Mercati con maggior volume nelle ultime N ore.",
        "input_schema": {
            "type": "object",
            "properties": {
                "hours": {"type": "integer", "default": 24},
                "limit": {"type": "integer", "default": 20},
            },
        },
    },
    {
        "name": "get_trade_volume",
        "description": "Volume totale e numero trade per un mercato specifico.",
        "input_schema": {
            "type": "object",
            "properties": {
                "market_id": {"type": "string"},
                "hours": {"type": "integer", "default": 24},
            },
            "required": ["market_id"],
        },
    },
    {
        "name": "get_price_history",
        "description": "Serie temporale oraria dei prezzi per un mercato.",
        "input_schema": {
            "type": "object",
            "properties": {
                "market_id": {"type": "string"},
                "hours": {"type": "integer", "default": 24},
            },
            "required": ["market_id"],
        },
    },
    {
        "name": "get_zscore_anomalies",
        "description": "Mercati con z-score anomalo (volume inusuale).",
        "input_schema": {
            "type": "object",
            "properties": {
                "threshold": {"type": "number", "default": 2.0},
                "hours": {"type": "integer", "default": 24},
            },
        },
    },
]

_TOOL_DISPATCH = {
    "get_trending_markets": lambda inp: get_trending_markets(**inp),
    "get_trade_volume": lambda inp: get_trade_volume(**inp),
    "get_price_history": lambda inp: get_price_history(**inp),
    "get_zscore_anomalies": lambda inp: get_zscore_anomalies(**inp),
}


def run(
    context: dict,
    langfuse_trace_id: str | None = None,
    langfuse_obs_id: str | None = None,
) -> dict:
    """
    Esegue il Market Analyst agent.
    `context`: dizionario opzionale con parametri (es. hours, zscore_threshold).
    Restituisce: {"signals": [...]}
    """
    client = anthropic.Anthropic()
    model = get_subagent_model()

    user_message = (
        f"Analizza i mercati Polymarket. Parametri: {json.dumps(context)}. "
        "Usa i tool disponibili per raccogliere dati, poi produci i segnali."
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
    result: dict = {"signals": []}
    with langfuse.start_as_current_observation(
        as_type="span",
        name="market-analyst",
        input={"context": context},
        trace_context=trace_ctx,
    ) as agent_span:
        turn = 0
        while True:
            turn += 1
            with langfuse.start_as_current_observation(
                as_type="generation",
                name=f"market-analyst-llm-turn-{turn}",
                model=model,
                input=messages,
            ) as gen:
                response = client.messages.create(
                    model=model,
                    max_tokens=4096,
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
