"""
News Analyst sub-agent.
Analisi qualitativa news collegate ai mercati (Weaviate + PostgreSQL).
Restituisce NewsSignals: per ogni mercato, notizie rilevanti e sentiment.
"""

from __future__ import annotations

import json
from typing import Any

import anthropic
from dotenv import load_dotenv
from langfuse.types import TraceContext

from observability import langfuse
from runtime_config import get_subagent_model
from tools.news_tools import (
    get_recent_news_links,
    search_news_by_market,
    semantic_search,
)

load_dotenv()

SYSTEM_PROMPT = """Sei il News Analyst di una agenzia di bet trading su Polymarket.
Analizza le notizie collegate ai mercati e valuta il loro impatto sulle probabilità.

Per ogni mercato con notizie rilevanti produci:
- sentiment: "positive" | "negative" | "neutral" (rispetto all'outcome YES)
- strength: 1-5 (5 = impatto molto forte)
- headlines: lista delle notizie più rilevanti (max 3)

Alla fine rispondi SOLO con JSON valido nel formato:
{"news_signals": [{"market_id": "...", "sentiment": "...", "strength": N, "headlines": ["..."]}]}
"""

TOOLS = [
    {
        "name": "get_recent_news_links",
        "description": "News collegate ai mercati nelle ultime N ore.",
        "input_schema": {
            "type": "object",
            "properties": {"hours": {"type": "integer", "default": 24}},
        },
    },
    {
        "name": "search_news_by_market",
        "description": "Notizie per un mercato specifico.",
        "input_schema": {
            "type": "object",
            "properties": {
                "market_id": {"type": "string"},
                "limit": {"type": "integer", "default": 10},
            },
            "required": ["market_id"],
        },
    },
    {
        "name": "semantic_search",
        "description": "Ricerca semantica su Weaviate per trovare notizie rilevanti.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "default": 10},
            },
            "required": ["query"],
        },
    },
]

_TOOL_DISPATCH = {
    "get_recent_news_links": lambda inp: get_recent_news_links(**inp),
    "search_news_by_market": lambda inp: search_news_by_market(**inp),
    "semantic_search": lambda inp: semantic_search(**inp),
}


def run(
    context: dict,
    langfuse_trace_id: str | None = None,
    langfuse_obs_id: str | None = None,
) -> dict:
    """
    Esegue il News Analyst agent.
    `context`: dizionario con market_ids opzionali da analizzare.
    Restituisce: {"news_signals": [...]}
    """
    client = anthropic.Anthropic()
    model = get_subagent_model()

    user_message = (
        f"Analizza le notizie rilevanti per i mercati Polymarket. "
        f"Contesto: {json.dumps(context)}. "
        "Usa i tool per raccogliere notizie recenti e produci i segnali."
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
    result: dict = {"news_signals": []}
    with langfuse.start_as_current_observation(
        as_type="span",
        name="news-analyst",
        input={"context": context},
        trace_context=trace_ctx,
    ) as agent_span:
        turn = 0
        while True:
            turn += 1
            with langfuse.start_as_current_observation(
                as_type="generation",
                name=f"news-analyst-llm-turn-{turn}",
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
