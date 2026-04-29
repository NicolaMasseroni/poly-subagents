# Pipeline Schema — schema reale del DB condiviso

Il CEO è un consumer **read-only** delle tabelle scritte dalla pipeline `poly-stream`. Questo documento registra lo schema reale (fonte di verità: `/home/nmasseroni/dev/polymarket/code/stream/infra/schema.sql`) per evitare drift come quello scoperto il 2026-04-17.

## Identificatore canonico nel CEO

**`market_id`** nel CEO = `markets.slug` (il market slug).
Stesso valore di `trades.slug` e `trending.slug`.

Le query del CEO contro `trades`/`trending` filtrano per `slug = %s` usando questo identificatore.
Le query contro `relevantnews` fanno JOIN (`markets → events → relevantnews`) per ottenere le news associate.

## Tabelle consumate dal CEO

### `trades` (hypertable on `timestamp`)

```
timestamp    TIMESTAMPTZ    NOT NULL
slug         TEXT           NOT NULL    -- market slug (identificatore)
event_slug   TEXT           NOT NULL
asset        TEXT           NOT NULL    -- condition token id
outcome      TEXT           NOT NULL    -- es. "YES", "NO"
side         TEXT           NOT NULL    -- "buy" | "sell"
name         TEXT           NOT NULL
pseudonym    TEXT           NOT NULL
price        DOUBLE PRECISION
size         DOUBLE PRECISION
volume       DOUBLE PRECISION           -- pre-calcolato (size * price)
```

Scritta da `trades_to_tsdb` worker (consumer Kafka topic `trades`).

### `trending` (hypertable on `window_end`)

```
slug                 TEXT      NOT NULL    -- market slug
window_id            TEXT      NOT NULL
window_start         TIMESTAMPTZ
window_end           TIMESTAMPTZ NOT NULL
volume_zscore        NUMERIC              -- usato da get_zscore_anomalies
trades_zscore        NUMERIC
volume_last          NUMERIC
volume_total         NUMERIC              -- usato da get_zscore_anomalies
volume_mavg          NUMERIC
volume_devstd        NUMERIC
trades_last          NUMERIC
trades_total         INTEGER
trades_mavg          NUMERIC
trades_devstd        NUMERIC
PRIMARY KEY (slug, window_end)
```

Scritta da `trending_to_tsdb` (che consuma da `trades_to_trending`).

### `relevantnews` (hypertable on `news_time`)

```
event_slug        TEXT         NOT NULL    -- link verso events.slug
event_id          INTEGER      NOT NULL
event_title       TEXT         NOT NULL
news_title        TEXT         NOT NULL
news_description  TEXT         NOT NULL
news_source       TEXT         NOT NULL
news_time         TIMESTAMPTZ  NOT NULL
```

**Attenzione:** il link è **event-level**, non market-level. Un evento può avere N mercati (outcomes diversi). La query del CEO fa JOIN `relevantnews → events → markets` ed esplode la news su tutti i mercati attivi dell'evento.

### `events`

```
event_id        TEXT PRIMARY KEY
slug            TEXT NOT NULL   -- usato per JOIN con relevantnews.event_slug
title, description, category, ...
active          BOOLEAN  NOT NULL DEFAULT TRUE
closed          BOOLEAN  NOT NULL DEFAULT FALSE
end_date        TIMESTAMPTZ
```

### `markets`

```
market_id       TEXT PRIMARY KEY
event_id        TEXT NOT NULL REFERENCES events(event_id)
condition_id    TEXT
slug            TEXT NOT NULL   -- identificatore usato dal CEO
question        TEXT NOT NULL
outcomes        TEXT[]          -- es. ["YES", "NO"]
outcome_prices  TEXT[]
active          BOOLEAN  NOT NULL DEFAULT TRUE
closed          BOOLEAN  NOT NULL DEFAULT FALSE
```

## Mapping CEO → pipeline (query summary)

| CEO API | Tabella(e) lette | Colonna di JOIN/filter |
|---|---|---|
| `get_trending_markets(hours, limit)` | `trades` + `trending` | `slug` |
| `get_trade_volume(market_id, hours)` | `trades` | `slug = market_id` |
| `get_price_history(market_id, hours)` | `trades` | `slug = market_id` |
| `get_zscore_anomalies(threshold, hours)` | `trending` | filtro `volume_zscore ≥ threshold` |
| `get_recent_news_links(hours)` | `relevantnews ⋈ events ⋈ markets` | `rn.event_slug = e.slug`, `m.event_id = e.event_id` |
| `search_news_by_market(market_id, limit)` | `relevantnews ⋈ events ⋈ markets` | `m.slug = market_id` |

## Worker che producono ogni segnale (coverage map)

Definita in `tools/pipeline_tools.py::_SIGNAL_PROVIDERS`:

| Segnale richiesto dal CEO | Worker che lo produce |
|---|---|
| `trade_history` | `trades_to_tsdb` |
| `market_trends` | `trades_to_tsdb` |
| `zscore_anomalies` | `trades_to_trending`, `trending_to_tsdb` |
| `news_events` | `events_to_weaviate` |
| `news_feed` | `news_to_kafka` |
| `news_links` | `get_relevant_news` |

`check_worker_health` + `get_pipeline_coverage` usano questa mappa per firing `PIPELINE_CHANGE` approval quando un segnale atteso non è coperto da provider healthy.

## Tabelle NON lette (context)

- `tags`, `event_tags`: ignorate dal CEO (tag semantici, non usati per signals)
- `news_items`: tabella delle news grezze pre-filtering (no event link)
