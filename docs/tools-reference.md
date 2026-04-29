# Tools Reference

Ogni tool è una funzione Python esposta all'LLM dell'agente via Anthropic tool use.
Le implementazioni stanno in `tools/`.

---

## Market Analyst (`tools/pipeline_tools.py`)

| Tool | Parametri | Fonte dati | Output |
|------|-----------|------------|--------|
| `get_trending_markets` | `hours=24`, `limit=20` | TimescaleDB → `trades` + `trending` | `[{market_id, volume, zscore, top_outcome}]` |
| `get_trade_volume` | `market_id`*, `hours=24` | TimescaleDB → `trades` | `{market_id, trade_count, total_volume, avg_price}` |
| `get_price_history` | `market_id`*, `hours=24` | TimescaleDB → `trades` | `[{ts, price}]` (serie oraria) |
| `get_zscore_anomalies` | `threshold=2.0`, `hours=24` | TimescaleDB → `trending` | `[{market_id, zscore, volume, timestamp}]` |

**Flusso tipico:** l'agente chiama prima `get_trending_markets` e `get_zscore_anomalies` per identificare i mercati di interesse, poi approfondisce con `get_trade_volume` e `get_price_history` per i singoli mercati prima di emettere i segnali.

---

## News Analyst (`tools/news_tools.py`)

| Tool | Parametri | Fonte dati | Output |
|------|-----------|------------|--------|
| `get_recent_news_links` | `hours=24` | PostgreSQL → `relevantnews ⋈ events ⋈ markets` | `[{market_id, event_slug, event_title, title, description, source, published_at}]` |
| `search_news_by_market` | `market_id`*, `limit=10` | PostgreSQL → `relevantnews ⋈ events ⋈ markets` | `[{title, description, source, published_at}]` |
| `semantic_search` | `query`*, `limit=10` | Weaviate → collection `Events` | `[{title, url, content, slug}]` |

**Flusso tipico:** `get_recent_news_links` per una panoramica generale, poi `search_news_by_market` per i mercati specifici e `semantic_search` per trovare eventi correlati via embedding.

---

## Portfolio Manager (`tools/simulation_tools.py`)

| Tool | Parametri | Fonte dati | Output |
|------|-----------|------------|--------|
| `get_simulated_portfolio` | — | PostgreSQL → `simulated_trades` | `{open_positions_count, total_exposure, total_pnl_realized, positions}` |
| `get_pnl_history` | `days=7` | PostgreSQL → `simulated_trades` (status=closed) | `[{day, daily_pnl, trades_closed}]` |
| `get_open_positions` | — | PostgreSQL → `simulated_trades` (status=open) | `[{id, market_id, outcome, stake, odds, opened_at, cycle}]` |

---

## Risk Manager (`tools/simulation_tools.py` + `tools/state_store.py`)

| Tool | Parametri | Fonte dati | Output |
|------|-----------|------------|--------|
| `get_portfolio_exposure` | — | wraps `get_simulated_portfolio()` | `{total_exposure, open_positions_count}` |
| `get_risk_limits` | — | PostgreSQL → `ceo_state` | `{max_total_exposure, max_stake_per_bet, max_open_positions}` |

**Flusso tipico:** chiama entrambi i tool, confronta `total_exposure` con `max_total_exposure` e lo `stake` proposto con `max_stake_per_bet`, poi emette `approved: true/false` per ogni bet.

---

## Trader (`tools/simulation_tools.py`)

| Tool | Parametri | Fonte dati | Output |
|------|-----------|------------|--------|
| `place_simulated_bet` | `market_id`*, `outcome`*, `stake`*, `odds`*, `cycle`, `notes` | PostgreSQL → INSERT `simulated_trades` | `{position_id, market_id, outcome, stake, odds, opened_at}` |
| `close_simulated_position` | `position_id`*, `closing_price`* | PostgreSQL → UPDATE `simulated_trades` | `{position_id, status, pnl, closed_at}` |

`close_simulated_position` calcola il P&L come `stake × (odds × closing_price − 1)`.

---

## Matrice agenti × tool

|  | `get_trending_markets` | `get_trade_volume` | `get_price_history` | `get_zscore_anomalies` | `get_recent_news_links` | `search_news_by_market` | `semantic_search` | `get_simulated_portfolio` | `get_pnl_history` | `get_open_positions` | `get_portfolio_exposure` | `get_risk_limits` | `place_simulated_bet` | `close_simulated_position` |
|--|--|--|--|--|--|--|--|--|--|--|--|--|--|--|
| **Market Analyst** | ✓ | ✓ | ✓ | ✓ | | | | | | | | | | |
| **News Analyst** | | | | | ✓ | ✓ | ✓ | | | | | | | |
| **Portfolio Manager** | | | | | | | | ✓ | ✓ | ✓ | | | | |
| **Risk Manager** | | | | | | | | | | | ✓ | ✓ | | |
| **Trader** | | | | | | | | | | | | | ✓ | ✓ |

`*` = parametro obbligatorio
