# FinSight

**An AI-powered financial research agent that ingests SEC filings and market data, and answers natural-language questions with cited, risk-scored research reports.**

FinSight is a full-stack application built around a LangGraph multi-agent pipeline:

1. A **Supervisor** classifies the user's message as a greeting, smalltalk, or a real research query. Greetings and smalltalk short-circuit to a fast reply; research queries run the full pipeline below.
2. A **Data Agent** fetches prices, financials, SEC filings (10-K and 10-Q), and news. It uses a **multi-source fallback chain** (yfinance → Massive → Twelve Data → EODHD → Tiingo) with automatic **exchange suffix detection** so international / Middle East tickers (Tadawul, ADX, DFM, EGX, QSE, etc.) resolve without manual configuration. It respects per-source TTLs so repeat questions within the cache window return in seconds.
3. A **RAG Agent** retrieves the most relevant filing chunks from the vector store and asks an LLM to answer the user's question with citations. Filings are **semantically chunked by SEC Item section** (Item 1A, 7, 7A, etc.) with **token-level splitting** (tiktoken, 512 tokens) and **HTML tables extracted as markdown**. In multi-turn conversations, prior turns are injected into the LLM prompt so the analysis builds on earlier context.
4. A **Report Agent** formats the analysis into a structured, risk-scored research report.

Conversations are persisted in Postgres — each chat is a `Conversation` with ordered `ConversationTurn` rows. Follow-up messages in the same conversation reuse the ticker context and Data Agent cache, and the RAG chain receives prior turns so it can produce continuity-aware answers.

The whole pipeline runs behind a FastAPI backend, with a Next.js finance-terminal-style frontend on top. Everything runs locally in Docker Compose.

---

## Table of contents

- [Architecture at a glance](#architecture-at-a-glance)
- [System diagrams](#system-diagrams)
- [Deeper reading](#deeper-reading)
- [Tech stack](#tech-stack)
- [Repository layout](#repository-layout)
- [Prerequisites](#prerequisites)
- [Quick start (Docker Compose)](#quick-start-docker-compose)
- [Environment variables](#environment-variables)
- [Data lifecycle: ingestion, caching, and freshness](#data-lifecycle-ingestion-caching-and-freshness)
- [Using the app](#using-the-app)
- [API reference](#api-reference)
- [Development workflow](#development-workflow)
- [Database migrations](#database-migrations)
- [Testing](#testing)
- [Troubleshooting](#troubleshooting)
- [Project status](#project-status)

---

## Architecture at a glance

```
                           ┌───────────────────────┐
                           │   Next.js frontend    │
                           │  home / ticker        │
                           │  workspace / compare  │
                           └───────────┬───────────┘
                                       │  REST + JWT
                           ┌───────────▼───────────┐
                           │   FastAPI backend     │
                           │  /analyze  /report    │
                           │  /ticker   /history   │
                           │  /conversations       │
                           │  /analyze/compare     │
                           │  /auth     /health    │
                           └───────────┬───────────┘
                                       │
              ┌────────────────────────┼────────────────────────┐
              │                        │                        │
   ┌──────────▼──────────┐   ┌─────────▼──────────┐   ┌─────────▼─────────┐
   │  LangGraph graph    │   │     Postgres       │   │     ChromaDB      │
   │                     │   │  tickers, prices,  │   │  filing-chunk     │
   │  supervisor         │   │  filings (+hash),  │   │  embeddings       │
   │    ├─ smalltalk ────┤   │  chunks, reports,  │   │                   │
   │    └─ data → rag    │   │  news_articles,    │   │                   │
   │         → report    │   │  conversations,    │   │                   │
   │                     │   │  conversation_turns│   │                   │
   └──────────┬──────────┘   └────────────────────┘   └───────────────────┘
              │
   ┌──────────▼──────────────────────────┐
   │   External APIs (with fallback)     │
   │  Anthropic (LLM), OpenAI (embed),   │
   │  SEC EDGAR                          │
   │  Prices/Financials:                 │
   │    yfinance → Massive → Twelve Data │
   │    → EODHD → Tiingo                 │
   │  News: Alpha Vantage → Massive      │
   │    → EODHD → Tiingo                 │
   └─────────────────────────────────────┘
```

The graph is wired in `agents/orchestrator.py`; each node lives in its own file under `agents/`. The retrieval chain is in `rag/chain.py`. For the full visual tour — cloud topology, data flows, deployment, and state machines — see [System diagrams](#system-diagrams) below.

**Models.** Every LLM call — intent classification, smalltalk, RAG report generation, stock comparison, and the eval LLM-as-judge — runs on **Claude Haiku 4.5** (`claude-haiku-4-5-20251001`). OpenAI is used **only** for embeddings (`text-embedding-3-large`). Nothing else touches OpenAI for generation.

**Routing at a glance.** The supervisor runs a cheap Claude Haiku 4.5 classifier (with a zero-cost regex fast path for obvious greetings like `hi`/`thanks`) and sends the turn down one of two branches:

- `greeting` / `smalltalk` → `smalltalk_agent` produces a short conversational reply and ends. No data fetch, no RAG, no risk score. Typical latency: 2–3 s.
- `research_query` → `data_agent` → `rag_agent` → `report_agent`. Typical latency: 8–30 s depending on cache state.

**Data freshness policy.** The Data Agent reads `tickers.updated_at` and skips ingestion pipelines whose data is still inside their TTL:

| Source        | TTL     | Who touches it                |
|---------------|---------|-------------------------------|
| Market data   | 15 min  | `ingest_market_data` bumps `updated_at` |
| SEC filings   | 24 h    | same timestamp, longer window |
| Embeddings    | hash-based | re-embed only when `Filing.content_hash` changes |

An `APScheduler` job (`SCHEDULER_ENABLED=true` by default) also refreshes every tracked ticker every 6 hours, so users returning after days see fresh data immediately on their first query. Users can also hit the **"Refresh"** button on a workspace's Overview tab to re-pull prices + news immediately without regenerating the report.

**International coverage.** yfinance handles US tickers out of the box; for other markets the Data Agent auto-tries exchange suffixes (`.SR` Tadawul, `.AE` ADX/DFM, `.QA` Qatar, `.KW` Kuwait, `.BH` Bahrain, `.CA` Egypt, `.L` London, `.TO` Toronto, `.HK` Hong Kong), then falls through to Massive, Twelve Data, EODHD, and Tiingo in order. EODHD in particular has strong Middle East + EMEA coverage (70+ exchanges).

---

## System diagrams

A picture-first tour of the system — zoom out, then zoom in. Each topic below shows its primary diagram; secondary and zoom-in views live in the expandable blocks. Every diagram's accompanying prose is in [`docs/system-diagrams.md`](docs/system-diagrams.md).

| Architecture | Flows, data & security | Delivery & ops |
|---|---|---|
| [1 · The big picture](#1-the-big-picture) | [5 · User journeys](#5-end-to-end-user-journeys) | [9 · Deployment workflow](#9-deployment-workflow) |
| [2 · Layered architecture](#2-layered-architecture) | [6 · Data flows](#6-data-flows) | [10 · CI/CD pipeline](#10-cicd-pipeline) |
| [3 · Cloud topology](#3-cloud-deployment-topology) | [7 · Database & ER](#7-database-and-entity-relationships) | [11 · Observability](#11-observability) |
| [4 · Multi-agent pipeline](#4-multi-agent-pipeline-langgraph) | [8 · Security](#8-security-and-defense-in-depth) | [12 · State machines](#12-state-machines) |

### 1. The big picture

Users hit a public ALB, which splits traffic between the Next.js frontend and the FastAPI backend; the backend reaches three private stores (Postgres, Redis, ChromaDB) and calls external APIs through a NAT gateway.

![The big picture](docs/images/01_big_picture.png)

### 2. Layered architecture

Five layers — presentation → HTTP API → LangGraph orchestration → infrastructure → data stores — each talking only to the one directly below it.

![Layered architecture](docs/images/02_layered_architecture.png)

### 3. Cloud deployment topology

The §1 picture with VPC / subnet / AZ detail. The security-group chain ensures nothing reaches the database without first passing through an API task.

![Cloud deployment topology](docs/images/03_cloud_topology.png)

<details>
<summary>Zoom in — security-group chain</summary>

![Security-group chain](docs/images/04_security_group_chain.png)

</details>

### 4. Multi-agent pipeline (LangGraph)

`supervisor` is the entry point; it routes each turn to `smalltalk_agent` or the `data_agent → rag_agent → report_agent` chain via `Command(goto=...)`.

![LangGraph top-level graph](docs/images/05_langgraph_top_level.png)

<details>
<summary>Zoom in — supervisor decision · DataAgent fallback · RAGAgent path</summary>

![Supervisor intent decision](docs/images/06_supervisor_decision.png)

![DataAgent multi-source fallback](docs/images/07_data_agent_fallback.png)

![RAGAgent retrieve → rerank → generate](docs/images/08_rag_agent_pipeline.png)

</details>

### 5. End-to-end user journeys

The flagship flow: `POST /analyze` starts a background LangGraph run; the browser polls `/report/{job_id}` until it completes (15–40 s).

![Journey — analyse a ticker](docs/images/10_journey_b_analyze_ticker.png)

<details>
<summary>Other journeys — login · chat (no report created) · compare two tickers</summary>

![Login](docs/images/09_journey_a_login.png)

![Chat about a report](docs/images/11_journey_c_chat.png)

![Compare two tickers](docs/images/12_journey_d_compare.png)

</details>

### 6. Data flows

Ingestion: external sources → pipelines → Postgres + ChromaDB.

![Ingestion pipeline](docs/images/13_ingestion_pipeline.png)

<details>
<summary>Zoom in — content_hash re-embedding trigger · retrieval read path</summary>

![Re-embedding trigger](docs/images/14_reembedding_trigger.png)

![Retrieval pipeline](docs/images/15_retrieval_pipeline.png)

</details>

### 7. Database and entity relationships

The Alembic-managed relational schema and how the tables relate.

![Database entity relationships](docs/images/16_database_er.png)

<details>
<summary>Zoom in — AnalysisReport.status transitions</summary>

![Status transitions](docs/images/17_status_transitions.png)

</details>

### 8. Security and defense in depth

Seven independent layers between an attacker and your data.

![Security — defense in depth](docs/images/18_defense_in_depth.png)

<details>
<summary>Zoom in — where secrets travel (laptop → Secrets Manager → container memory)</summary>

![Where secrets travel](docs/images/19_secrets_travel.png)

</details>

### 9. Deployment workflow

First deploy: one-time setup → Terraform provision → ship code & schema → wire GitHub. Redeploys are just the ship step.

![First-time deploy](docs/images/20_first_time_deploy.png)

### 10. CI/CD pipeline

`deploy.yml` on push to `main`: OIDC token exchange → build & push images → run migrations → zero-downtime rolling update.

![Deploy workflow](docs/images/22_cicd_deploy_yml.png)

<details>
<summary>Zoom in — ci.yml PR gate (never touches AWS) · rolling-update timeline</summary>

![CI workflow](docs/images/21_cicd_ci_yml.png)

![Rolling update](docs/images/23_rolling_update.png)

</details>

### 11. Observability

Three layers of "what's going on?" — logs → alarms → dashboard.

![Observability layers](docs/images/24_observability_layers.png)

<details>
<summary>Zoom in — alarm signal flow (metric → threshold → SNS → inbox)</summary>

![Alarm signal flow](docs/images/25_alarm_signal_flow.png)

</details>

### 12. State machines

The analysis job lifecycle: pending → running → completed / failed, with re-runs marking the old report `overwritten`.

![Background analysis job](docs/images/26_background_job_state_machine.png)

<details>
<summary>Zoom in — ECS task lifecycle · CloudWatch alarm states</summary>

![ECS task lifecycle](docs/images/27_ecs_task_lifecycle.png)

![CloudWatch alarm](docs/images/28_cloudwatch_alarm_state.png)

</details>

---

## Deeper reading

Short, focused guides under `docs/`. Each is independently readable and links to the exact files/lines it describes.

| Topic | Read |
|---|---|
| **Architecture — the *why* behind every major choice** (start here if you're reading the codebase for the first time) | [`docs/architecture/README.md`](docs/architecture/README.md) |
| Pipeline agents — supervisor, data agent, RAG mechanism end-to-end | [`docs/agents/README.md`](docs/agents/README.md) |
| Postgres (RDS) + ChromaDB — what each stores, why they're split, how they stay in sync | [`docs/databases/README.md`](docs/databases/README.md) |
| Redis cache — what we cache (just one thing), why it's that narrow, future use cases | [`docs/cache/README.md`](docs/cache/README.md) |
| AWS ALB + ECS auto-scaling — listener rules, target groups, target-tracking policy | [`docs/alb-autoscaling/README.md`](docs/alb-autoscaling/README.md) |
| AWS deployment walkthrough — Terraform, CI/CD, OIDC, observability | [`docs/deployment/README.md`](docs/deployment/README.md) |
| Offline LLM eval harness — dataset format, scorers, MLflow integration | [`docs/evals/README.md`](docs/evals/README.md) |

---

## Tech stack

**Backend**
- Python 3.12, FastAPI, Uvicorn
- LangChain + LangGraph (multi-agent orchestration with checkpointing)
- SQLAlchemy 2 (async) + asyncpg + Alembic
- ChromaDB (vector store, `text-embedding-3-large`, 3072 dims)
- **Anthropic Claude Haiku 4.5** (`claude-haiku-4-5-20251001`) — every LLM call: classification, RAG generation, comparison, eval judge
- OpenAI — embeddings only (`text-embedding-3-large`); tiktoken (token-level chunking)
- BeautifulSoup (SEC filing section parsing + HTML table → markdown extraction)
- **Market data (multi-source fallback)**: yfinance, Massive (Polygon.io), Twelve Data, EODHD, Tiingo
- SEC EDGAR (10-K / 10-Q filings — latest 4 per ticker: most recent 10-K + 3 recent 10-Qs, downloaded concurrently with retry/backoff)
- sentence-transformers cross-encoder reranker (`ms-marco-MiniLM-L-6-v2`), loaded once per process
- **News (multi-source fallback)**: Alpha Vantage, Massive, EODHD, Tiingo
- Redis (cache, scheduler locks)
- JWT auth (email/password + Google OAuth), structlog, slowapi rate limiting

**Frontend**
- Next.js 16 (App Router, standalone output)
- React 19, TypeScript (strict)
- Tailwind CSS v4 + CSS custom properties
- TanStack Query v5
- TradingView Lightweight Charts (candlestick + SMA/Bollinger overlays)
- html2canvas-pro + jsPDF (client-side PDF export)
- Radix UI primitives, lucide-react, Geist fonts
- Zod schemas mirroring the Pydantic models

**Infrastructure (local)**
- Docker Compose: `postgres`, `redis`, `chromadb`, `app`, `frontend`
- Multi-stage Dockerfiles for both backend (Python slim) and frontend (Node Alpine standalone)

---

## Repository layout

```
Finsight/
├── api/                   FastAPI app, routers, schemas, auth
│   ├── main.py
│   ├── dependencies.py    DbSession, CurrentUser (JWT)
│   ├── schemas.py         Pydantic request/response models
│   └── routers/           analyze, report, ticker, history, conversations, auth, health
├── agents/                LangGraph nodes
│   ├── orchestrator.py    StateGraph wiring, supervisor w/ intent classifier, smalltalk node
│   ├── data_agent.py      Fetches market data + SEC filings (with TTL cache)
│   ├── rag_agent.py       Retrieves chunks, calls LLM
│   └── report_agent.py    Formats the final report
├── rag/                   Retrieval chain, reranker, prompts, vector store
│   ├── schemas.py         ReportSchema (SWOT, bull/bear, risk breakdown), ComparisonReport
│   ├── temporal.py        Extracts target fiscal year(s) from a query
│   └── prompts.py         RAG + comparison system prompts
├── pipelines/             market_data, sec_filings, embedder, cleaner, scheduler, hashing
│   ├── financial_summary.py  Structured multi-year financials block for the RAG prompt
│   ├── massive.py         Massive (Polygon.io) — OHLCV, profile, financials, news
│   ├── twelvedata.py      Twelve Data — OHLCV, profile, statistics (Middle East coverage)
│   ├── eodhd.py           EODHD — OHLCV, fundamentals, quarterly, news (70+ exchanges)
│   ├── tiingo.py          Tiingo — OHLCV, profile, news (US-focused fallback)
│   └── news_fetcher.py    Multi-source news sentiment → DB persistence
├── db/
│   ├── models.py          SQLAlchemy models (tickers, prices, filings, chunks, reports, news_articles, conversations, turns)
│   ├── session.py         Async engine + session factory
│   ├── crud.py
│   └── migrations/        Alembic revisions
├── frontend/              Next.js app
│   ├── src/app/(app)/     home, workspace/[ticker], compare routes (+ legacy redirects)
│   ├── src/components/    finsight/* (workspace-view, workspace-overview/research/chat, home-view, …), ui/*
│   ├── src/lib/           api client, zod schemas, utils
│   └── Dockerfile
├── tests/
│   ├── unit/              agents, pipelines, rag
│   ├── integration/       API end-to-end
│   └── evals/             offline LLM eval harness (dataset, scorers, runner)
├── scripts/
│   └── ingest_ticker.py   Manual ingestion of a single ticker
├── docker/
│   └── docker-compose.yml Full local stack
├── docs/
│   ├── architecture/README.md       The *why* behind every major design choice (start here)
│   ├── agents/README.md             Pipeline-agents deep dive (full RAG mechanism)
│   ├── evals/README.md              Evaluation harness reference
│   ├── cache/README.md              Redis — what we cache and why it's that narrow
│   ├── databases/README.md          Postgres + ChromaDB — split, sync, schema
│   ├── alb-autoscaling/README.md    AWS ALB + ECS auto-scaling deep dive
│   └── deployment/README.md         End-to-end AWS deployment walkthrough
├── Dockerfile             Backend image
├── alembic.ini
├── requirements.txt
├── requirements-dev.txt
└── Docs/project_proposal.md
```

---

## Prerequisites

- Docker and Docker Compose (Compose v2, `docker compose ...`)
- An **Anthropic API key** (required — every LLM call runs on Claude Haiku 4.5)
- An **OpenAI API key** (required — used only for embeddings)
- ~4 GB free disk for images and the `pgdata` / `chromadata` volumes
- Free local ports: `3000`, `5433`, `6379`, `8000`, `8100`

If you want to run the backend or frontend outside Docker, you additionally need Python 3.12 and Node 20.

---

## Quick start (Docker Compose)

From the project root:

```bash
# 1. Create .env in the project root (see next section for all vars)
cat > .env <<'EOF'
ANTHROPIC_API_KEY=sk-ant-...your-key...
OPENAI_API_KEY=sk-proj-...your-key...
JWT_SECRET_KEY=change-me-to-a-long-random-string
EOF

# 2. Build and start the full stack
docker compose -f docker/docker-compose.yml up -d --build

# 3. Check everything is healthy
docker compose -f docker/docker-compose.yml ps
```

You should see five services, all `healthy`:

| Service  | URL / port                  | What it is                  |
|----------|------------------------------|-----------------------------|
| frontend | http://localhost:3000        | Next.js UI                  |
| app      | http://localhost:8000        | FastAPI backend             |
| postgres | localhost:5433               | Postgres 16                 |
| redis    | localhost:6379               | Redis 7                     |
| chromadb | http://localhost:8100        | Chroma vector store         |

Alembic migrations run automatically on app startup (`alembic upgrade head`).

Logs:

```bash
docker compose -f docker/docker-compose.yml logs -f app
docker compose -f docker/docker-compose.yml logs -f frontend
```

Stop the stack:

```bash
docker compose -f docker/docker-compose.yml down          # keep volumes
docker compose -f docker/docker-compose.yml down -v       # wipe postgres + chroma data
```

---

## Environment variables

The `app` service loads variables from `.env` at the **project root** via `env_file: ../.env`. Do not put the `.env` inside `docker/` — Compose reads its own `.env` from that directory for variable substitution, which is a separate concern.

| Variable             | Required | Default                                        | Notes                                   |
|----------------------|----------|------------------------------------------------|-----------------------------------------|
| `ANTHROPIC_API_KEY`  | yes      | —                                              | All LLM calls (Claude Haiku 4.5). `CLAUDE_API_KEY` is also accepted as an alias. |
| `OPENAI_API_KEY`     | yes      | —                                              | Embeddings only (`text-embedding-3-large`) |
| `JWT_SECRET_KEY`     | yes      | `change-me-in-production`                      | Signing key for JWT access tokens       |
| `DATABASE_URL`       | no       | `postgresql+asyncpg://finsight:finsight@postgres:5432/finsight` | Set by Compose inside the container |
| `REDIS_URL`          | no       | `redis://redis:6379/0`                         | Set by Compose                          |
| `CHROMA_HOST`        | no       | `chromadb`                                     | Set by Compose                          |
| `CHROMA_PORT`        | no       | `8000`                                         | Container-side port                     |
| `CORS_ORIGINS`       | no       | `http://localhost:3000,http://127.0.0.1:3000`  | Comma-separated list                    |
| `SCHEDULER_ENABLED`  | no       | `true`                                         | APScheduler refreshes all tracked tickers every 6 h. Set to `false` to disable. |
| `ALPHA_VANTAGE_API_KEY` | no    | —                                              | News sentiment (primary). Free tier: 25 requests/day. |
| `MASSIVE_API_KEY`    | no       | —                                              | Massive (Polygon.io) — OHLCV + financials + news fallback #2 |
| `TWELVEDATA_API_KEY` | no       | —                                              | Twelve Data — OHLCV + profile fallback (strong Middle East coverage) |
| `EODHD_API_KEY`      | no       | —                                              | EODHD — OHLCV + fundamentals fallback for 70+ exchanges |
| `TIINGO_API_KEY`     | no       | —                                              | Tiingo — OHLCV + news fallback (US-focused)  |
| `GOOGLE_CLIENT_ID` | no       | —                                              | Required for Google OAuth login         |
| `NEXT_PUBLIC_API_URL`| no       | `http://localhost:8000`                        | Baked into the frontend at build time   |

Any other keys in your `.env` (e.g. extra third-party data providers) are also passed through into the container via `env_file`.

---

## Data lifecycle: ingestion, caching, and freshness

The pipeline can answer questions only for tickers whose filings have been ingested into Postgres and embedded into Chroma. There are three ways data enters the system — and an explicit freshness policy that governs when it gets refreshed.

### How data is ingested

**1. Automatic ingestion via `/analyze` (Data Agent).**
Every research request runs through the Data Agent, which fetches:

1. Prices, financials, and quarterly periods — tries yfinance first (with exchange-suffix auto-detection for international tickers), then falls through the provider chain (Massive → Twelve Data → EODHD → Tiingo) until one returns data. The `price_source` / `financials_source` fields in the result record which provider actually served the request.
2. Recent 10-K **and** 10-Q filings from SEC EDGAR (**latest 4 per company** — most recent 10-K plus the last three 10-Qs). Filings are downloaded concurrently (capped at 4 in-flight) with retry-and-backoff on SEC throttling; already-stored filings are skipped, so history accrues across runs. The SEC `reportDate` (the fiscal period a filing *covers*, distinct from its filing date) is captured and stored on each filing.
3. News sentiment via the Alpha Vantage → Massive → EODHD → Tiingo fallback chain.
4. Filings are **section-aware-chunked** (split by SEC Item headers, tables extracted as markdown) using **parent-document chunking**: small ~500-token *child* chunks are embedded for retrieval precision, each linked to a larger ~2000-token *parent* block that is what the LLM actually reads (search precise, read rich). Children are embedded with `text-embedding-3-large` into ChromaDB, prefixed with a temporal/provenance header (e.g. `[NVDA · 10-K · FY2025 · Item 7]`) and tagged with `fiscal_year` + `parent_id` metadata — see [Temporal retrieval](#temporal-retrieval-getting-the-right-year) below. Retrieval is **hybrid** (dense vector search ⊕ BM25 keyword search, fused by Reciprocal Rank Fusion) and reranked by a cross-encoder; the full mechanism is documented in [`docs/agents/README.md`](docs/agents/README.md).

First-time ingestion for a new ticker takes ~30–60 seconds. On subsequent requests, the agent consults the cache (see below) and skips whatever is still fresh — repeat queries on the same ticker complete in ~6–10 seconds.

**1b. On-demand refresh from the workspace.**
The workspace Overview tab's **"Refresh"** button calls `POST /ticker/{symbol}/refresh`, which runs `ingest_market_data` + `ingest_news` only (no LLM, no report). This is the right escape hatch when a user returns after a few days and wants fresh prices/news without burning time regenerating an entire report.

**2. Background scheduler.**
With `SCHEDULER_ENABLED=true` (the default), an APScheduler job in `pipelines/scheduler.py` re-runs the full ingestion pipeline for every ticker in the `tickers` table every 6 hours. This keeps tracked companies warm so users returning after days still see current data on their first query.

**3. Manual CLI ingestion.**
For batch seeding or quickly populating a fresh install:

```bash
docker compose -f docker/docker-compose.yml exec app \
  python -m scripts.ingest_ticker AAPL MSFT TSLA
```

This writes to Postgres **and** Chroma, so later analyze requests go straight into the RAG path without waiting for the Data Agent.

### Cache policy — how long is data cached?

There is no blanket TTL. Each data source has its own freshness window, and the Data Agent decides per request whether to re-fetch:

| Source              | TTL         | Refresh trigger                                                  |
|---------------------|-------------|------------------------------------------------------------------|
| Prices + financials | **15 min**  | `tickers.updated_at` older than 15 min → `ingest_market_data` runs (also upserts the current-year financials row, so values actually refresh) |
| SEC filings         | **24 h**    | `tickers.updated_at` older than 24 h → `ingest_sec_filings` runs a fresh EDGAR lookup |
| Embeddings          | hash-based  | `Filing.content_hash != Filing.embedded_content_hash` → old chunks are purged from Postgres and Chroma, then re-embedded |
| Full refresh        | **6 h**     | Scheduler re-runs everything for all tracked tickers             |

**Worked example — a user comes back after 3 days:**

1. They ask "what are AAPL's recent risks?".
2. `tickers.updated_at` for AAPL is > 24 h old → Data Agent calls both `ingest_market_data` (new prices + refreshed FY financials) and `ingest_sec_filings` (new 10-Q if one was published).
3. If a new 10-Q was downloaded, its SHA-256 is different from the stored `embedded_content_hash` → the embedder purges old chunks + Chroma vectors and re-embeds.
4. RAG and Report agents then run against the fresh corpus.

Total extra latency vs a warm request: roughly the ingestion time for whatever was actually stale (often 10–30 s). Everything else is skipped as a cache hit.

**Worked example — a user asks two questions within a minute:**

1. First call ingests + runs the full pipeline (~15–30 s).
2. Second call sees `updated_at` within the 15 min window → both `ingest_market_data` and `ingest_sec_filings` return `{"skipped": true, "reason": "fresh"}`. Embedder short-circuits because nothing is pending. Only RAG + Report run. Total ~6–10 s.

### Temporal retrieval: getting the right year

Dense embeddings encode *topic*, not discrete facts: "2024" and "2025" produce near-identical vectors. So a question about FY2025 can retrieve a more semantically-similar FY2024 chunk and answer with the wrong year's numbers. FinSight defends against this in four layers:

1. **Period capture** — at ingestion, SEC's `reportDate` (the fiscal period a filing covers, *not* its filing date — a 10-K filed Feb 2025 reports on the prior fiscal year) is stored on `Filing.period_of_report`.
2. **Year in the chunk** — every chunk is prefixed with a temporal header (`[NVDA · 10-K · FY2025 · Item 7 (MD&A)]`) *before* embedding, so the year is encoded in the vector and visible to the cross-encoder reranker. Each chunk also carries a `fiscal_year` metadata tag.
3. **Query time-intent** — `rag/temporal.py` parses the target year(s) from the question: explicit years, `FY25` notation, and relative phrases ("last year"). "Latest" / "most recent" deliberately yield no year — that's handled by latest-filing filtering, not a hard year filter.
4. **Soft metadata filter** — when the query targets specific year(s), retrieval applies a hard ChromaDB `fiscal_year` filter so a wrong-year chunk simply isn't in the candidate set. If the filter returns too few chunks (missing/legacy metadata), it **relaxes to an unfiltered search** so a question is never starved of context.

Because the `fiscal_year` tag lives in chunk metadata, filings embedded before this feature shipped won't match a year filter — the soft fallback keeps them usable, and re-embedding (or a fresh ingest) populates the tag.

### Structured financials in the report

The RAG report is grounded in filing **text** — but numbers parsed from prose, or stranded in a table chunk that didn't survive retrieval, are unreliable. So the analyst is also handed a **structured financial-history block**, separately from the retrieved excerpts.

The Data Agent builds it from the `financials` and `prices` tables (`pipelines/financial_summary.py` · `build_financial_context`): a compact markdown table of revenue, net income, EPS, and gross margin for the **last ~5 fiscal years and ~4 quarters**, plus a short price snapshot. It flows through graph state (`financial_context`) into the RAG prompt under a dedicated `## Historical Financials` heading, and the prompt instructs the LLM to treat it as the **authoritative source** for quantitative figures and year-over-year trends — the filing excerpts supply the narrative, segment, and risk detail the table cannot.

The block is ~300 tokens, budgeted separately from the retrieved-chunk context, so it costs nothing meaningful. The result: the model sees a company's full multi-year trajectory, not just whatever figures happened to land in the latest 10-K's retrieved chunks.

### Handling greetings and smalltalk

The supervisor classifies every turn before touching the Data Agent. If a user says `hi`, `thanks`, or `what can you do?`, the request is routed to a dedicated `smalltalk_agent` that returns a short conversational reply in ~2–3 s — no ingestion, no RAG, no risk score. Real research questions still go through the full pipeline.

The classifier uses Claude Haiku 4.5 with structured output, plus a zero-cost regex fast path for unambiguous short greetings. On classification failure it defaults to `research_query` so genuine questions are never brushed off.

### Multi-turn conversations

Every chat session is a **persistent conversation** backed by `conversations` and `conversation_turns` tables in Postgres. When a user sends a follow-up message:

1. The user turn is saved immediately.
2. Prior turns from the same conversation are loaded and passed into the LangGraph state as `prior_turns`.
3. The Data Agent still runs but benefits from TTL cache hits — if the ticker data is already fresh, both market and SEC pipelines are skipped.
4. The RAG chain injects prior turns (capped at the last 10) into the LLM prompt between the system message and the current user message, so the analysis can reference earlier questions and answers.
5. The assistant turn (including the `job_id` linking to the full `AnalysisReport`) is persisted after completion.

Conversations survive across browser sessions — clicking a conversation in the sidebar reloads all its turns from the API.

---

## Using the app

Open **http://localhost:3000**. Register with email/password or sign in with Google OAuth. The backend uses JWT-based auth (`POST /auth/register`, `POST /auth/login`, `POST /auth/google`).

The app is organised around a **ticker workspace** — one page per company that unifies live data, AI reports, and chat so a new user always knows where each kind of information lives. There are three top-level destinations:

### `/home` — launcher + activity feed

The logged-in landing page:
- **Ticker launcher** — search any US public company by ticker or name.
- **Popular chips** — one click into common tickers (AAPL, NVDA, TSLA, …).
- **Activity feed** — "Starred" and "Recently run" reports across all tickers, filterable by ticker or question. Each row links straight into that report inside its workspace.

### `/workspace/{ticker}` — the ticker workspace

A **sticky header** shared across all tabs shows the ticker, live price, day-change badge, sector/industry, and the **Compare** and **Generate report** actions. The header's **Refresh** button (re-pulls prices + news only — no LLM, no report) appears on the Overview tab only. The active tab lives in the URL (`?tab=overview|research|chat`), so any view is linkable and shareable.

- **Overview tab — live market data, no AI.**
  - **KPIs**: market cap, P/E ratio, revenue, net income, EPS, gross margin, and a 30-day rolling volatility sparkline.
  - **Candlestick chart**: TradingView Lightweight Charts with volume bars and toggle-able SMA(20), SMA(50), and Bollinger Band overlays.
  - **Financial trends**: Revenue vs Net Income bar chart + Gross Margin sparkline across quarterly/annual periods.
  - **Filing timeline**: vertical timeline of 10-K/10-Q filings with SEC links.
  - **Peer comparison**: side-by-side table of sector peers (price, market cap, P/E, margin, day change).
  - **Metrics trend**: AI-extracted metrics across multiple re-analyses.
  - **News sentiment**: recent articles with color-coded sentiment dots and an average sentiment badge.
  - **Institutional holders**, **earnings calendar** (EPS beat/miss bars with surprise %), and **dividends** (yield, payout ratio, annual history — hidden for non-dividend stocks).
  - **Suggested questions** that jump straight into the Chat tab, and a thin **latest-report tile** linking into Research.

- **Research tab — AI-generated reports.**
  - A horizontal **picker of past reports, one entry per distinct question**. Re-running the *same* question overwrites its report; a *different* question is kept as its own report. Failed and superseded ("overwritten") runs are hidden.
  - Selecting a report renders the full detail view:
    - **Sticky TOC sidebar** (desktop) with scroll-to anchor links, and independently **collapsible sections**.
    - **Price snapshot strip**: live price, day change, market cap, 30-day sparkline.
    - **Executive summary** banner with the TL;DR verdict.
    - Summary, **risk gauge**, and risk breakdown (operational/financial/market/legal sub-scores). When retrieval is too sparse to judge risk honestly, the score is shown as **"Insufficient data"** rather than a fabricated placeholder.
    - **SWOT** 2×2 grid, **bull vs bear** thesis cards, **revenue segmentation** bars with trend indicators, **competitive moat** card with wide/narrow/none badge, **valuation verdict** badge, **catalysts** with impact-colored icons, **management assessment** card.
    - Key metrics with trend arrows, cited sources, a collapsed **market context** section (news + peers), and **follow-up question** suggestions.
    - **Share as image** (Web Share API → PNG fallback), **PDF export** (multi-page A4), and **JSON download**.
  - **Re-analysis**: if a report already exists for a ticker, the Generate dialog offers "View existing" or re-running.

- **Chat tab — lightweight RAG chat (no pipeline).** Each ticker gets one persistent conversation per user. Messages query the vector store directly and return an answer with citations — no report is created. Prior turns provide multi-turn context. The Overview tab's suggested questions and a `?q=` URL param can pre-fill the chat input.

### `/compare`

Side-by-side stock comparison. Enter two tickers to generate a structured comparison with metric-by-metric analysis (with winner highlighting) and an investment recommendation. Requires existing reports for both tickers for best results.

> **Legacy routes.** The pre-refactor pages still resolve: `/dashboard/{ticker}` → workspace Overview, `/reports` → `/home`, `/reports/{id}` and `/chat` → the matching workspace tab. Old bookmarks keep working.

Typical latency:

- **Greeting / smalltalk** — 2–3 s (smalltalk agent short-circuit).
- **Research query, cache hit** — 6–10 s (data skipped, RAG + Report only).
- **Research query, cold or stale** — 15–40 s depending on how much needs re-ingesting.

---

## API reference

All non-public routes require a `Bearer` token from the auth endpoints.

| Method | Path                | Body / params                              | Description                                           |
|--------|---------------------|--------------------------------------------|-------------------------------------------------------|
| GET    | `/health`           | —                                          | Liveness probe (db, redis, chroma status)             |
| POST   | `/auth/register`    | `{ "email", "password", "name?" }`         | Register a new account, returns JWT                   |
| POST   | `/auth/login`       | `{ "email", "password" }`                  | Login, returns JWT                                    |
| POST   | `/auth/google`      | `{ "id_token" }`                           | Google OAuth login, returns JWT                       |
| POST   | `/analyze`          | `{ "ticker": "AAPL", "question": "..." }`  | Kick off the full research pipeline in the background. Auto-creates a conversation for the user+ticker. |
| GET    | `/analyze/check/{ticker}` | —                                    | Check if a completed analysis exists for this user+ticker |
| POST   | `/analyze/compare`  | `{ "ticker_a": "AAPL", "ticker_b": "MSFT" }` | Compare two tickers side-by-side (background task)  |
| GET    | `/report/{job_id}`  | —                                          | Poll report status. Completed reports include summary, risk score/breakdown, SWOT, bull/bear case, key metrics, citations. |
| GET    | `/report/{job_id}/compare` | —                                   | Poll comparison report (metric comparisons, recommendation) |
| GET    | `/history`          | `?ticker=X&limit=N`                       | Recent analysis jobs, filterable by ticker            |
| GET    | `/ticker/{symbol}`  | `?days=N`                                  | Metadata + prices + financials (all periods) + filings (up to 20) |
| POST   | `/ticker/{symbol}/refresh` | —                                    | Re-pull prices + news using the multi-source fallback chain. No LLM / no report. Used by the workspace Overview "Refresh" button. |
| GET    | `/ticker/{symbol}/peers` | —                                      | Sector peer comparison (5 peers, live yfinance data)  |
| GET    | `/ticker/{symbol}/news` | `?limit=N`                              | Recent news articles with sentiment scores            |
| GET    | `/ticker/{symbol}/holders` | —                                    | Top 10 institutional holders (live yfinance)          |
| GET    | `/ticker/{symbol}/earnings` | —                                   | Earnings calendar + EPS surprise history              |
| GET    | `/ticker/{symbol}/dividends` | —                                  | Dividend yield, payout ratio, annual history          |
| POST   | `/conversations`    | `{ "title": "...", "ticker": "AAPL" }`     | Create a new conversation                             |
| GET    | `/conversations`    | —                                          | List conversations (most recent first)                |
| GET    | `/conversations/{id}` | —                                        | Get a conversation with all its turns                 |
| GET    | `/conversations/by-ticker/{ticker}` | —                          | Find-or-create conversation for a ticker              |
| POST   | `/conversations/{id}/messages` | `{ "question": "..." }`         | Lightweight RAG query — returns answer + citations directly (no report created). Prior turns provide multi-turn context. |

Interactive docs: **http://localhost:8000/docs** (Swagger UI) and **http://localhost:8000/redoc**.

### Example — full analysis round-trip

```bash
# 1. Register and get a token
TOKEN=$(curl -s -X POST http://localhost:8000/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"email":"demo@example.com","password":"demo1234","name":"Demo"}' \
  | python3 -c "import json,sys; print(json.load(sys.stdin)['access_token'])")
# Or login if already registered:
# TOKEN=$(curl -s -X POST http://localhost:8000/auth/login \
#   -H 'Content-Type: application/json' \
#   -d '{"email":"demo@example.com","password":"demo1234"}' \
#   | python3 -c "import json,sys; print(json.load(sys.stdin)['access_token'])")

# 2. Submit a job
JOB=$(curl -s -X POST http://localhost:8000/analyze \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"ticker":"AAPL","question":"What are the main revenue risks?"}' \
  | python3 -c "import json,sys; print(json.load(sys.stdin)['job_id'])")
echo "Job: $JOB"

# 3. Poll until complete
while true; do
  STATUS=$(curl -s http://localhost:8000/report/$JOB \
    -H "Authorization: Bearer $TOKEN" \
    | python3 -c "import json,sys; print(json.load(sys.stdin)['status'])")
  echo "status=$STATUS"
  [ "$STATUS" = "completed" ] || [ "$STATUS" = "failed" ] && break
  sleep 5
done

# 4. Fetch the final report
curl -s http://localhost:8000/report/$JOB \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```

### Example — multi-turn conversation (lightweight RAG chat)

```bash
# 1. Create a conversation
CONV=$(curl -s -X POST http://localhost:8000/conversations \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"title":"TSLA risks","ticker":"TSLA"}' \
  | python3 -c "import json,sys; print(json.load(sys.stdin)['id'])")
echo "Conversation: $CONV"

# 2. Send first message (lightweight RAG — returns answer directly, no report)
curl -s -X POST http://localhost:8000/conversations/$CONV/messages \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"question":"What are the main revenue risks for Tesla?"}' \
  | python3 -m json.tool
# Returns: { "answer": "...", "citations": [...], "confidence": "high" }

# 3. Send a follow-up (prior turns injected for context)
curl -s -X POST http://localhost:8000/conversations/$CONV/messages \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"question":"How do those compare to their competition risks?"}' \
  | python3 -m json.tool

# 4. Fetch the conversation with all turns
curl -s http://localhost:8000/conversations/$CONV \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```

### Example — stock comparison

```bash
# Compare two tickers (both must have existing reports for best results)
COMP=$(curl -s -X POST http://localhost:8000/analyze/compare \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"ticker_a":"AAPL","ticker_b":"MSFT"}' \
  | python3 -c "import json,sys; print(json.load(sys.stdin)['job_id'])")

# Poll until complete
while true; do
  STATUS=$(curl -s http://localhost:8000/report/$COMP/compare \
    -H "Authorization: Bearer $TOKEN" \
    | python3 -c "import json,sys; print(json.load(sys.stdin)['status'])")
  echo "status=$STATUS"
  [ "$STATUS" = "completed" ] || [ "$STATUS" = "failed" ] && break
  sleep 5
done

# Fetch the comparison
curl -s http://localhost:8000/report/$COMP/compare \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```

---

## Development workflow

There are two ways to run FinSight: **dev mode** (hot-reload, for active development) and **Docker mode** (production-like, for final testing).

### Dev mode (recommended during development)

In dev mode, only the databases run in Docker. The backend and frontend run natively on your machine with **hot-reload** — every code change is reflected instantly without rebuilding anything.

```bash
# One command to start everything:
./scripts/dev.sh
```

This will:
1. Start Postgres, Redis, and ChromaDB in Docker (lightweight, no rebuild needed)
2. Run Alembic migrations
3. Start FastAPI with `--reload` — edit any Python file, the server restarts in ~1 second
4. Start Next.js with `npm run dev` — edit any TSX/CSS file, the browser updates instantly (HMR)

```
  API:      http://localhost:8000
  Frontend: http://localhost:3000
  Swagger:  http://localhost:8000/docs
```

You can also start pieces individually:

```bash
./scripts/dev.sh infra    # just databases
./scripts/dev.sh api      # just backend (hot-reload)
./scripts/dev.sh web      # just frontend (hot-reload)
./scripts/dev.sh stop     # stop everything
```

Press `Ctrl+C` to stop all processes.

#### First-time setup

Before running dev mode for the first time, install dependencies:

```bash
# Python
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt

# Frontend
cd frontend && npm install && cd ..

# Create .env (see Environment variables section)
cp .env.example .env  # then fill in your API keys
```

### Docker mode (production build)

Use Docker mode when you're done developing and want to test the full production-like stack, or for deployment:

```bash
# Build and start everything in Docker:
docker compose -f docker/docker-compose.yml up -d --build

# Stop:
docker compose -f docker/docker-compose.yml down          # keep data
docker compose -f docker/docker-compose.yml down -v       # wipe data
```

### When to use which

| Scenario | Mode | Why |
|----------|------|-----|
| Writing code, fixing bugs | Dev mode | Instant feedback, no rebuild wait |
| Testing a new component | Dev mode | HMR shows changes in the browser immediately |
| Changing Python logic | Dev mode | Uvicorn auto-restarts in ~1s |
| Final testing before deploy | Docker mode | Matches production environment |
| Sharing with others | Docker mode | Single command, no local setup needed |
| Adding a new migration | Dev mode | Run `alembic revision --autogenerate -m "..."` directly |

> **Note:** Next.js 16 has breaking changes versus previous major versions. If you need to look up an API, read the docs shipped under `frontend/node_modules/next/dist/docs/` rather than relying on older guides.

---

## Database migrations

Alembic is configured in `alembic.ini` with scripts under `db/migrations/`.

```bash
# In Docker:
docker compose -f docker/docker-compose.yml exec app alembic upgrade head
docker compose -f docker/docker-compose.yml exec app alembic revision --autogenerate -m "add foo"

# Locally (with DATABASE_URL pointing at localhost:5433):
alembic upgrade head
alembic revision --autogenerate -m "add foo"
```

Migrations run automatically at container startup via the `app` service's command.

---

## Testing

```bash
# Unit tests (no external services required for most)
pytest tests/unit -v

# Integration tests — requires the stack running
docker compose -f docker/docker-compose.yml up -d postgres redis chromadb
pytest tests/integration -v
```

A one-off end-to-end smoke of the graph:

```bash
python -m scripts.test_graph AAPL "What are the main revenue risks?"
```

### Offline LLM eval harness

`tests/evals/` is an offline evaluation suite that runs the **real LangGraph pipeline** over a curated dataset and scores the output — the way to catch quality regressions that unit tests can't.

```bash
# From the project venv (.env is loaded automatically)
python -m tests.evals.run_evals                       # full dataset
python -m tests.evals.run_evals --limit 2 --no-llm-judge   # quick smoke, deterministic scorers only
python -m tests.evals.run_evals --mlflow              # also log the run to MLflow
```

It scores each row on citation faithfulness, factuality, refusal correctness, and risk-band accuracy. The LLM-as-judge scorer is disk-cached so re-runs are cheap; `--no-llm-judge` skips it entirely. Results are written under `evals/results/`.

With `--mlflow`, each run is also logged to the `finsight-evals` MLflow experiment — params, aggregate metrics, and the result files as artifacts — so quality can be charted across runs (`mlflow ui`) instead of diffing timestamped folders. Tracking is local/file-based by default; set `MLFLOW_TRACKING_URI` to use a server. The flag is off by default and a missing `mlflow` install is a soft skip.

See `docs/evals/README.md` for the dataset format and scorer details.

---

## Troubleshooting

**`openai.AuthenticationError: 401 - You didn't provide an API key`**
Your `.env` is not being loaded into the `app` container. Confirm the file lives at the project root (not `docker/.env`) and contains `OPENAI_API_KEY=sk-...`. Verify inside the container:

```bash
docker compose -f docker/docker-compose.yml exec app \
  python3 -c "import os; print(len(os.environ.get('OPENAI_API_KEY','')))"
```
It should print a number > 0.

**`RuntimeError: ... got Future ... attached to a different loop`**
This happens when the module-level async engine is reused from a worker thread with its own event loop. The Data Agent now builds a local `NullPool` engine per call to avoid it. If you hit it in new code, follow the same pattern: create a fresh `create_async_engine(..., poolclass=NullPool)` inside the coroutine.

**Report completes immediately with "No relevant documents found"**
Chroma is empty for that ticker. Either run the manual seeding script (`python -m scripts.ingest_ticker AAPL`) or let the Data Agent re-ingest by truncating the `chunks` table:

```bash
docker compose -f docker/docker-compose.yml exec -T postgres \
  psql -U finsight -d finsight -c "TRUNCATE chunks;"
```

Then submit a new analyze request — the Data Agent will re-embed all existing filings.

**Port 3000 already in use**
Something else is bound to it (often a stray `next dev`). Free it:

```bash
lsof -ti:3000 | xargs -r kill -9
```

**Frontend build shows an old `NEXT_PUBLIC_API_URL`**
Those variables are **inlined at build time** by Next.js. Rebuild the frontend image when you change them:

```bash
docker compose -f docker/docker-compose.yml up -d --build frontend
```

**Chat returns empty or no results**
The ticker's filings haven't been embedded yet. Run an analysis first from the workspace ("Generate report"), which triggers the Data Agent to ingest filings and create embeddings. Chat queries the same vector store.

**Reset everything**

```bash
docker compose -f docker/docker-compose.yml down -v
docker compose -f docker/docker-compose.yml up -d --build
```

---

The AWS deployment, CI/CD, and observability **designs** are captured in [System diagrams](#system-diagrams) (§3, §8–§12) and in full in [`docs/system-diagrams.md`](docs/system-diagrams.md); the hands-on provisioning and production-hardening work (Weeks 6–8) is still in progress.
