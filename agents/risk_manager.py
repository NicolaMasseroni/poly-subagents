"""
Risk Manager sub-agent.
Valuta il rischio di un TradingProposal rispetto ai limiti correnti.
Restituisce RiskAssessment per ogni bet candidata.
Se i limiti sono inadeguati, suggerisce proposed_limit_change (decide il CEO cosa fare).
"""

from __future__ import annotations

import json
from typing import Any

import anthropic
from dotenv import load_dotenv
from langfuse.types import TraceContext

from observability import langfuse
from runtime_config import get_subagent_model
from tools.simulation_tools import get_simulated_portfolio

load_dotenv()

SYSTEM_PROMPT = """Sei il Risk Manager di una agenzia di bet trading su Polymarket.
Valuta ogni bet proposta rispetto all'esposizione corrente e ai limiti di rischio.

Regole:
- Non approvare bet che porterebbero l'esposizione totale oltre max_total_exposure
- Non approvare bet con stake > max_stake_per_bet
- Non approvare se ci sono già max_open_positions posizioni aperte
- Se i limiti sembrano troppo conservativi rispetto all'opportunità, suggerisci proposed_limit_change

Rispondi SOLO con JSON valido nel formato:
{
  "assessments": [
    {
      "market_id": "...",
      "outcome": "...",
      "approved": true/false,
      "max_stake": N,
      "reason": "...",
      "proposed_limit_change": null
    }
  ]
}
"""

TOOLS = [
    {
        "name": "get_portfolio_exposure",
        "description": "Esposizione totale corrente (somma stake posizioni aperte).",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_risk_limits",
        "description": "Limiti di rischio correnti (da tabella ceo_state su PG).",
        "input_schema": {"type": "object", "properties": {}},
    },
]


def _get_portfolio_exposure() -> dict:
    portfolio = get_simulated_portfolio()
    return {
        "total_exposure": portfolio["total_exposure"],
        "open_positions_count": portfolio["open_positions_count"],
    }


def _get_risk_limits() -> dict:
    from tools.state_store import load_state

    return load_state()["risk_limits"]


_TOOL_DISPATCH = {
    "get_portfolio_exposure": lambda inp: _get_portfolio_exposure(),
    "get_risk_limits": lambda inp: _get_risk_limits(),
}


def run(
    trading_proposal: dict,
    langfuse_trace_id: str | None = None,
    langfuse_obs_id: str | None = None,
) -> dict:
    """
    Valuta un trading proposal.
    `trading_proposal`: {"bets": [{"market_id": "...", "outcome": "...", "suggested_stake": N, "odds": N}]}
    Restituisce: {"assessments": [...]}
    """
    client = anthropic.Anthropic()
    model = get_subagent_model()

    user_message = (
        f"Valuta questo trading proposal: {json.dumps(trading_proposal)}. "
        "Usa i tool per verificare l'esposizione corrente e i limiti, "
        "poi produci il RiskAssessment per ogni bet."
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
    result: dict = {"assessments": []}
    with langfuse.start_as_current_observation(
        as_type="span",
        name="risk-manager",
        input={"bets_count": len(trading_proposal.get("bets", []))},
        trace_context=trace_ctx,
    ) as agent_span:
        turn = 0
        while True:
            turn += 1
            with langfuse.start_as_current_observation(
                as_type="generation",
                name=f"risk-manager-llm-turn-{turn}",
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
