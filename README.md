# Polymarket Subagents

Repository dei sub-agent A2A usati dal CEO agent:

- `market_analyst`: segnali quantitativi da TimescaleDB.
- `news_analyst`: segnali news da PostgreSQL e Weaviate.
- `portfolio_manager`: stato del portafoglio simulato.
- `risk_manager`: valutazione rischio e proposte di cambio limiti.
- `trader`: esecuzione paper trading su `simulated_trades`.

Il repo sibling `../ceo` contiene solo l'orchestratore CEO, la dashboard/API e AG-UI.

## Toolchain

```bash
uv sync --dev
uv run ruff check .
uv run mypy .
uv run pytest
```

## Avvio Locale

```bash
uv run python -m agents.market_analyst_server
uv run python -m agents.news_analyst_server
uv run python -m agents.portfolio_manager_server
uv run python -m agents.risk_manager_server
uv run python -m agents.trader_server
```

Ogni server espone una agent card A2A su `/.well-known/agent-card.json` e ascolta sulla porta configurata dalla libreria A2A.

## Build Images

La workflow `.github/workflows/build.yml` pubblica:

- `ghcr.io/nicolamasseroni/poly-market-analyst`
- `ghcr.io/nicolamasseroni/poly-news-analyst`
- `ghcr.io/nicolamasseroni/poly-portfolio-manager`
- `ghcr.io/nicolamasseroni/poly-risk-manager`
- `ghcr.io/nicolamasseroni/poly-trader`

Le ImagePolicy Flux in `../poly-flux/base/*-analyst`, `../poly-flux/base/*-manager` e `../poly-flux/base/trader` continuano a seguire questi tag.

## Variabili Ambiente

```bash
ANTHROPIC_API_KEY
DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD
WEAVIATE_HOST, WEAVIATE_PORT, WEAVIATE_GRPC_HOST, WEAVIATE_GRPC_PORT
LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, LANGFUSE_HOST
SUBAGENT_MODEL
```

I tool leggono gli schemi pipeline descritti in `docs/pipeline-schema.md` e `docs/tools-reference.md`.
