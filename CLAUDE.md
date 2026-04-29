# CLAUDE.md

## Commands

```bash
uv run pytest -q
uv run pytest tests/test_market_analyst_server.py
uv run ruff check .
uv run ruff format .
uv run mypy .
```

## Architecture

Questo repo contiene solo i sub-agent A2A e i tool usati dai sub-agent.
L'orchestratore CEO, dashboard/API e AG-UI vivono in `../ceo`.

Ogni sub-agent (`market_analyst.py`, `news_analyst.py`, `portfolio_manager.py`,
`risk_manager.py`, `trader.py`) segue lo stesso pattern:

```python
messages = [{"role": "user", "content": initial_message}]
while True:
    response = client.messages.create(model=..., tools=TOOLS, messages=messages)
    if response.stop_reason == "end_turn":
        # parse JSON from response.content and return
    tool_results = [call tools from response.content]
    if not tool_results:
        break
    messages.append({"role": "assistant", "content": response.content})
    messages.append({"role": "user", "content": tool_results})
```

Il guard `if not tool_results: break` evita messaggi user con `content=[]`, che
Anthropic rifiuta con HTTP 400.

## Boundaries

- Non aggiungere codice AG-UI qui: il transport AG-UI resta in `../ceo`.
- Non reintrodurre `agents.ceo` qui.
- I container devono continuare a partire con `python -m agents.<name>_server`.
- Le immagini pubblicate restano `poly-market-analyst`, `poly-news-analyst`,
  `poly-portfolio-manager`, `poly-risk-manager`, `poly-trader`.
