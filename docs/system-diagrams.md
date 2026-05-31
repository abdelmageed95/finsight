# FinSight — System Diagrams & Workflows

> A picture-first tour of the FinSight system. Read it top-down: each section
> zooms in by one level — from "what is this thing" down to "what happens
> when a single request lands."

## Table of contents

1. [The big picture (one diagram)](#1-the-big-picture)
2. [Layered architecture](#2-layered-architecture)
3. [Cloud deployment topology](#3-cloud-deployment-topology)
4. [The multi-agent pipeline (LangGraph)](#4-the-multi-agent-pipeline)
5. [End-to-end user journeys](#5-end-to-end-user-journeys)
6. [Data flows](#6-data-flows)
7. [Database — entity relationships](#7-database-entity-relationships)
8. [Security & defense in depth](#8-security--defense-in-depth)
9. [Deployment workflow (first deploy & redeploy)](#9-deployment-workflow)
10. [CI/CD — GitHub Actions + OIDC](#10-cicd-flow)
11. [Observability — logs, metrics, alarms](#11-observability)
12. [State machines](#12-state-machines)
13. [Quick lookup tables](#13-quick-lookup-tables)

---

## 1. The big picture

If you read only one diagram, read this one. Everything else is a zoom-in.

```
                                  ╔═════════════════════════════════════╗
                                  ║          THE USER'S BROWSER         ║
                                  ║      (Next.js app loaded from ALB)  ║
                                  ╚════════════════╤════════════════════╝
                                                   │ HTTP
                                                   ▼
   ┌────────────────────────────────────────────────────────────────────┐
   │                  AWS — region eu-central-1                          │
   │                                                                     │
   │   ┌────────────────────────────────────────────────────────────┐    │
   │   │           Application Load Balancer  (public)              │    │
   │   │                                                            │    │
   │   │   path = /analyze, /report, /ticker, /auth, /health …      │    │
   │   │                       ─►  API target group                 │    │
   │   │   everything else     ─►  Frontend target group            │    │
   │   └─────────────┬─────────────────────────┬──────────────────-─┘    │
   │                 │                         │                         │
   │      ┌──────────▼─────────┐    ┌──────────▼──────────┐              │
   │      │  ECS Fargate task  │    │  ECS Fargate task   │              │
   │      │      Next.js       │    │  FastAPI + LangGraph│              │
   │      │     (frontend)     │    │       (api)         │              │
   │      └────────────────────┘    └──────────┬──────────┘              │
   │                                           │                         │
   │    ┌──────────────────────────────────────┼────────────────────┐    │
   │    │                                      │                    │    │
   │    ▼                ▼               ▼     ▼              ▼      ▼   │
   │ ┌──────┐      ┌──────────┐    ┌─────────┐ ┌──────────────────┐      │
   │ │ RDS  │      │ ElastiC. │    │ Chroma  │ │ Secrets Manager  │      │
   │ │ Pg16 │      │ Redis 7  │    │ EC2+EBS │ │ (keys at launch) │      │
   │ └──────┘      └──────────┘    └─────────┘ └──────────────────┘      │
   │                                                                     │
   │                ┌─────────────────────────────┐                      │
   │                │       NAT Gateway           │                      │
   │                └──────────────┬──────────────┘                      │
   └───────────────────────────────┼─────────────────────────────────────┘
                                   │
                                   ▼
              ┌──────────────────────────────────────────┐
              │  External APIs (HTTPS, outbound only)    │
              │                                          │
              │  • Anthropic Claude (LLM)                │
              │  • OpenAI (embeddings)                   │
              │  • SEC EDGAR (filings)                   │
              │  • yfinance / Alpha Vantage / Tiingo …   │
              └──────────────────────────────────────────┘
```

**One-sentence summary:** users hit a public ALB; it splits HTTP between a
Next.js frontend and a FastAPI backend; the backend reaches three private
data stores (Postgres, Redis, ChromaDB) and calls out to external APIs
through a NAT gateway.

---

## 2. Layered architecture

```
╔════════════════════════════════════════════════════════════════════════╗
║                          PRESENTATION                                  ║
║                                                                        ║
║   Next.js 16 App Router  ·  Tailwind + shadcn UI  ·  Zod schemas       ║
║   /(app)/dashboard      /(app)/chat      /(app)/reports                ║
║   /(app)/compare        /login           /signup                       ║
║                                                                        ║
║   • AuthProvider context wraps the app, stores JWT in localStorage     ║
║   • lib/api.ts auto-injects Authorization: Bearer <jwt>                ║
║   • Every API response validated through Zod (lib/schemas.ts)          ║
╚═════════════════════════════════╤══════════════════════════════════════╝
                                  │  HTTP + JWT
╔═════════════════════════════════▼══════════════════════════════════════╗
║                            HTTP API                                    ║
║                                                                        ║
║   FastAPI (api/main.py)  ·  Routers in api/routers/                    ║
║                                                                        ║
║   ├─ analyze.py       POST /analyze, /analyze/compare,                 ║
║   │                   GET  /analyze/check/{ticker}, /analyze/stream    ║
║   ├─ report.py        GET  /report/{job_id}                            ║
║   ├─ ticker.py        GET  /ticker/{symbol}                            ║
║   ├─ history.py       GET  /history                                    ║
║   ├─ conversations.py CRUD on /conversations, /messages, /stream       ║
║   ├─ auth.py          /auth/signup, /auth/login, /auth/me              ║
║   ├─ search.py        ticker search                                    ║
║   └─ health.py        GET  /health                                     ║
║                                                                        ║
║   Dependencies (api/dependencies.py): DbSession, CurrentUser           ║
║   Middleware (pure ASGI, not BaseHTTPMiddleware)                       ║
╚═════════════════════════════════╤══════════════════════════════════════╝
                                  │
╔═════════════════════════════════▼══════════════════════════════════════╗
║                       ORCHESTRATION (LangGraph)                        ║
║                                                                        ║
║   StateGraph  ·  agents/orchestrator.py                                ║
║                                                                        ║
║          ┌───────────────────────────────────────┐                     ║
║          │            supervisor                 │  ← entry point      ║
║          └────────────┬───────────────┬──────────┘                     ║
║                       │               │                                ║
║          (smalltalk)  ▼               ▼  (research)                    ║
║          ┌──────────────┐   ┌──────────────────────────────────┐       ║
║          │ smalltalk    │   │ data_agent → rag_agent →         │       ║
║          │ _agent       │   │ report_agent                     │       ║
║          └──────────────┘   └──────────────────────────────────┘       ║
║                                                                        ║
║   State reducers: add_messages, extend_list, merge_dicts               ║
╚═════════════════════════════════╤══════════════════════════════════════╝
                                  │
╔═════════════════════════════════▼══════════════════════════════════════╗
║                          INFRASTRUCTURE                                ║
║                                                                        ║
║   pipelines/           rag/             db/                            ║
║   ─ market_data         ─ chain          ─ models (SQLAlchemy)         ║
║   ─ sec_filings         ─ retriever      ─ crud                        ║
║   ─ news_fetcher        ─ reranker       ─ session (async engine)      ║
║   ─ embedder            ─ vector_store   ─ migrations (Alembic)        ║
║   ─ scheduler           ─ prompts                                      ║
║   (fallback chain:                                                     ║
║    yfinance → Massive → TwelveData → EODHD → Tiingo)                   ║
╚═════════════════════════════════╤══════════════════════════════════════╝
                                  │
╔═════════════════════════════════▼══════════════════════════════════════╗
║                            DATA STORES                                 ║
║                                                                        ║
║   Postgres 16 (RDS)              Redis 7 (ElastiCache)                 ║
║   • users, tickers, filings      • query embedding cache               ║
║   • chunks, financials, prices   • rate-limit counters                 ║
║   • analysis_reports,            • short-lived session state           ║
║   • conversations + turns                                              ║
║   • news_articles                                                      ║
║                                                                        ║
║   ChromaDB (EC2 + EBS)                                                 ║
║   • per-chunk vector embeddings                                        ║
║   • collection per ticker                                              ║
╚════════════════════════════════════════════════════════════════════════╝
```

**Each layer talks only to the one directly below it.** The frontend doesn't
know LangGraph exists; LangGraph doesn't know FastAPI exists; the agents
don't know the database client; they all use clean abstractions in the layer
above.

---

## 3. Cloud deployment topology

Same picture as §1, but with the network details.

```
                              ╔══════════════════════════╗
                              ║   Internet (public)      ║
                              ╚════════════╤═════════════╝
                                           │
                              ┌────────────▼─────────────┐
                              │      Internet Gateway    │
                              └────────────┬─────────────┘
                                           │
   ╔═══════════════════════════════════════▼══════════════════════════════════╗
   ║    VPC  10.0.0.0/16    (eu-central-1)                                    ║
   ║                                                                          ║
   ║   ┌──────────────────────────  AZ a  ───┐  ┌──────────────  AZ b  ──┐    ║
   ║   │                                     │  │                        │    ║
   ║   │  PUBLIC SUBNET   10.0.1.0/24        │  │  PUBLIC   10.0.2.0/24  │    ║
   ║   │  ┌─────────────┐   ┌─────────────┐  │  │                        │    ║
   ║   │  │     ALB     │   │  NAT GW     │  │  │  ┌─────────────┐       │    ║
   ║   │  │  (port 80)  │   │   + EIP     │──┼──┼─►│  to internet│       │    ║
   ║   │  └──────┬──────┘   └──────▲──────┘  │  │  └─────────────┘       │    ║
   ║   │         │                 │         │  │                        │    ║
   ║   │  PRIVATE SUBNET  10.0.3.0/24        │  │  PRIVATE  10.0.4.0/24  │    ║
   ║   │  ┌──────▼──────┐                    │  │                        │    ║
   ║   │  │ ECS api task│ ───────────────────┼──┼─►(can call out via NAT)│    ║
   ║   │  │ ECS fe task │                    │  │                        │    ║
   ║   │  └──────┬──────┘                    │  │                        │    ║
   ║   │         │                           │  │                        │    ║
   ║   │  ┌──────▼──────┐  ┌──────────────┐  │  │  RDS standby could     │    ║
   ║   │  │ RDS Postgres│  │ ElastiC Redis│  │  │  live here  (multi-AZ) │    ║
   ║   │  └─────────────┘  └──────────────┘  │  │                        │    ║
   ║   │                                     │  │                        │    ║
   ║   │  ┌─────────────┐                    │  │                        │    ║
   ║   │  │ Chroma EC2  │                    │  │                        │    ║
   ║   │  │ + EBS data  │                    │  │                        │    ║
   ║   │  └─────────────┘                    │  │                        │    ║
   ║   └─────────────────────────────────────┘  └────────────────────────┘    ║
   ║                                                                          ║
   ║   Cross-AZ services (not subnet-bound):                                  ║
   ║     · Secrets Manager   · CloudWatch (logs/metrics)                      ║
   ║     · ECR registries     · IAM / STS                                     ║
   ╚══════════════════════════════════════════════════════════════════════════╝
```

### Security-group chain (zoom in)

```
   Internet
      │  TCP 80
      ▼
   ┌────────┐   :8000     ┌──────────┐   :5432      ┌──────┐
   │  alb   │ ───────────►│ ecs_api  │ ────────────►│ rds  │
   │  SG    │             │   SG     │              │  SG  │
   └───┬────┘             └────┬─────┘              └──────┘
       │                       │
       │  :3000                ├─── :6379 ──► [ redis SG ]
       ▼                       │
   ┌──────────────┐            └─── :8000 ──► [ chroma SG ]
   │ ecs_frontend │
   │      SG      │
   └──────────────┘
```

Each downstream SG accepts traffic **only** from the SG of the tier above
it. There is no path from the internet to the database that doesn't pass
through an API task.

---

## 4. The multi-agent pipeline

### Top-level graph (LangGraph)

`agents/orchestrator.py` builds a `StateGraph` with five nodes. The
supervisor is always the entry point; downstream nodes are reached via
`Command(goto=...)` returned from each node (LangGraph's modern dynamic
routing).

```
                         ┌────────────┐
                         │   START    │
                         └─────┬──────┘
                               ▼
                       ┌────────────────┐
                       │  supervisor    │
                       │ (Claude Haiku  │
                       │  intent class.)│
                       └─┬────────────┬─┘
            "greeting"   │            │   "research_query"
                         ▼            ▼
            ┌──────────────────┐   ┌──────────────────┐
            │ smalltalk_agent  │   │   data_agent     │
            │ (fast reply ~2s) │   │ (market + SEC +  │
            └────────┬─────────┘   │  news + cache)   │
                     │             └──────┬───────────┘
                     │                    │
                     │                    ▼
                     │             ┌──────────────────┐
                     │             │   rag_agent      │
                     │             │ (retrieve +      │
                     │             │  rerank + LLM)   │
                     │             └──────┬───────────┘
                     │                    │
                     │                    ▼
                     │             ┌──────────────────┐
                     │             │  report_agent    │
                     │             │ (format + persist│
                     │             │  to DB)          │
                     │             └──────┬───────────┘
                     │                    │
                     └──────────┬─────────┘
                                ▼
                         ┌────────────┐
                         │    END     │
                         └────────────┘
```

### Supervisor decision (zoom in)

```
                     ┌────────────────────────┐
                     │   User question text   │
                     └──────────┬─────────────┘
                                ▼
            ┌────────────────────────────────────┐
            │  Regex fast-path                   │
            │  e.g. /^(hi|hello|hey)\b/i         │
            └──┬─────────────────────┬───────────┘
               │ match               │ no match
               ▼                     ▼
        goto smalltalk      ┌────────────────────┐
                            │ Claude Haiku 4.5   │
                            │ structured output: │
                            │ { intent: ... }    │
                            └──┬─────────────────┘
                               │
              ┌────────────────┼────────────────┐
              ▼                ▼                ▼
        smalltalk          research        clarification
                                            (rare)
```

The fast-path saves ~1s on every "hi" — no LLM call when a regex suffices.

### DataAgent — multi-source fallback

```
            Need market data for AAPL
                       │
                       ▼
              ┌──────────────────┐
              │ Check cache TTL? │ ── fresh ──► return cached
              └────────┬─────────┘
                       │ stale or missing
                       ▼
              ┌────────────────────┐
              │     yfinance       │ ── ok ──► persist + return
              └────────┬───────────┘
                       │ fail / no data
                       ▼
              ┌────────────────────┐
              │   Massive API      │ ── ok ──► persist + return
              └────────┬───────────┘
                       │ fail
                       ▼
              ┌────────────────────┐
              │  Twelve Data       │ ── ok ──► …
              └────────┬───────────┘
                       │
                       ▼
              ┌────────────────────┐
              │      EODHD         │
              └────────┬───────────┘
                       │
                       ▼
              ┌────────────────────┐
              │      Tiingo        │
              └────────┬───────────┘
                       │
                       ▼
              all sources failed → error result, agent flags low confidence
```

**Per-source TTLs:** market data 15 min, SEC filings 24 h. The DataAgent
won't re-fetch within the TTL even if asked.

### RAGAgent — retrieve + rerank + generate

```
   user question + ticker
              │
              ▼
   ┌──────────────────────────┐
   │ Embed query (OpenAI)     │
   │ - check Redis cache first│
   └────────┬─────────────────┘
            │ vector
            ▼
   ┌──────────────────────────┐
   │ ChromaDB top-k=8 search  │
   │ collection per ticker    │
   └────────┬─────────────────┘
            │ 8 candidate chunks
            ▼
   ┌──────────────────────────┐
   │ Cross-encoder reranker   │
   │ (in-image, CPU)          │
   └────────┬─────────────────┘
            │ top-k=4 reranked
            ▼
   ┌──────────────────────────┐
   │ Build prompt:             │
   │  - retrieved chunks       │
   │  - structured output spec │
   │  - last 10 conv turns     │
   └────────┬──────────────────┘
            ▼
   ┌──────────────────────────┐
   │ Claude Haiku 4.5         │
   │ structured response:     │
   │ ReportSchema             │
   └────────┬─────────────────┘
            ▼
   { summary, swot, bull/bear, risk_breakdown, confidence, citations }
```

The reranker is baked into the Docker image (`HF_HOME=/opt/hf-cache`,
`HF_HUB_OFFLINE=1`) so cold-start tasks don't block on a 300 MB download.

---

## 5. End-to-end user journeys

### Journey A — login

```
  Browser                           ALB           API
  ───────                           ───           ───
  POST /login {email,pw}    ───────► /auth/login ──┐
                                                   │
                                                   ├─► verify pw (bcrypt)
                                                   ├─► mint JWT (24h)
                                                   ◄────  { token }
  store token in localStorage
  AuthProvider sets user state
  router pushes to /dashboard

  All subsequent requests:
  GET /history
    Authorization: Bearer <jwt>  ───►/history ────► decode JWT
                                                   ►load User from DB
                                                   ►return user-scoped
```

### Journey B — analyse a ticker (the long one)

```
   Browser                          ALB                       API                       LangGraph                     Data stores
   ───────                          ───                       ───                       ─────────                     ───────────
   POST /analyze {ticker:"AAPL"}
   └────────────────►          ─►   forward             ─►    create AnalysisReport
                                                              row, status=pending
                                                              return { job_id }
                                                              ┌─────────────────────┐
                                                              │ asyncio.to_thread + │
                                                              │ background task     │
                                                              │  (NullPool engine)  │
                                                              └──────────┬──────────┘
                                                                          ▼
                                                                supervisor → data_agent
                                                                              │
                                                                              ▼ fetch market data
                                                                              ────────────────────►  yfinance / fallback chain
                                                                              ◄────────────────────  prices, financials, P/E …
                                                                              ▼ fetch filings
                                                                              ────────────────────►  SEC EDGAR
                                                                              ◄────────────────────
                                                                              ▼ fetch news
                                                                              ────────────────────►  Alpha Vantage
                                                                              ◄────────────────────
                                                                              ▼ persist
                                                                              ────────────────────►  RDS (Filing, Price, NewsArticle)
                                                                              ▼ embed missing chunks
                                                                              ────────────────────►  OpenAI embeddings
                                                                              ────────────────────►  Chroma upsert
                                                                          rag_agent
                                                                              ▼ embed query
                                                                              ────────────────────►  Redis (cache hit?) → OpenAI
                                                                              ▼ retrieve
                                                                              ────────────────────►  Chroma top-k
                                                                              ▼ rerank (in-process)
                                                                              ▼ LLM
                                                                              ────────────────────►  Anthropic Claude
                                                                              ◄────────────────────  ReportSchema
                                                                          report_agent
                                                                              ▼ format + persist
                                                                              ────────────────────►  RDS (AnalysisReport.status=completed)
   GET /report/{job_id}        ─►    /report             ─► read AnalysisReport
   (polling every 2s)                                     return { status, report }
   ◄─────────────────                                    ◄─────────────────────────
   render ReportDetailView
```

The whole flow takes **15–40 seconds** for a research query. The browser
polls `/report/{job_id}` until `status == "completed"` (or `failed`).

### Journey C — chat about an existing report

Chat takes a **separate, lighter path** — no full analysis, just RAG.

```
   Browser ──► POST /conversations/{id}/messages
                    body: { content: "What's the biggest risk?" }
                    │
                    ▼
              FastAPI conversations.py
                    │
                    ├─► load Conversation + last 10 turns
                    │
                    ├─► embed query (Redis cached)
                    │
                    ├─► Chroma retrieve top-k by ticker
                    │
                    ├─► Claude Haiku with prompt
                    │      (chunks + recent turns + question)
                    │
                    ├─► persist ConversationTurn (user + assistant)
                    │
                    └─► return { answer, citations, confidence }
                    ◄─── synchronous
```

Notice: **chat creates no AnalysisReport.** It uses the vector store that
was filled in by a prior `/analyze`.

### Journey D — compare two tickers

```
  Browser ──► POST /analyze/compare { tickers: ["AAPL","MSFT"] }
                    │
                    ▼
              FastAPI analyze.py
                    │
                    ├─► fan out:    /analyze AAPL  (async task)
                    │               /analyze MSFT  (async task)
                    │
                    ├─► wait for both AnalysisReports
                    │
                    ├─► create a comparison row with
                    │     ticker_symbol = "AAPL_vs_MSFT"   ← VARCHAR(30) for this
                    │
                    └─► return { comparison_id, ... }
```

The widened `ticker_symbol` column (the `09f8550da2e7` migration) exists
specifically to fit these comparison labels.

---

## 6. Data flows

### Ingestion pipeline

```
   External sources                  Pipelines                  Persistence
   ────────────────                  ─────────                  ───────────

   yfinance ──┐
   Massive    │
   Twelve     ├──►  pipelines/market_data.py  ──►  RDS: Price, Financials
   EODHD      │     (TTL 15 min)
   Tiingo  ───┘

   SEC EDGAR  ────►  pipelines/sec_filings.py ──►  RDS: Filing(.raw_text)
                     (TTL 24 h)                          │
                                                          ▼
                                                pipelines/cleaner.py
                                                          │
                                                          ▼
                                                  text chunks
                                                          │
                                                          ▼
                                                pipelines/embedder.py
                                                          │
                            OpenAI embeddings ◄──────────┤
                                                          ▼
                                              ┌──► RDS: Chunk (with embedding_id)
                                              │
                                              └──► ChromaDB (vector + metadata)

   Alpha Vantage ─►  pipelines/news_fetcher  ──►  RDS: NewsArticle
                     (dedup by URL)
```

### Re-embedding trigger (the `content_hash` mechanism)

```
   New /analyze run
        │
        ▼
   fetch filing text
        │
        ▼
   sha256(text) = hash_new
        │
        ▼
   compare to Filing.embedded_content_hash
        │
        ├── matches ──► skip embedding (already in Chroma)
        │
        └── differs ──► chunk + embed + upsert into Chroma
                       → update Filing.embedded_content_hash = hash_new
```

Saves the cost of re-embedding unchanged filings.

### Retrieval pipeline (read path)

```
        query "What is the biggest risk for AAPL?"
                │
                ▼
        ┌────────────────────────────┐
        │ Redis: SHA(query) ?         │
        └──────┬─────────────────────┘
               │
        cache hit │       │ cache miss
               │  │       │
               ▼  │       ▼
          embedding│    OpenAI embeddings ──► Redis SET
               │  │       │
               ▼  ▼       ▼
        ┌────────────────────────────┐
        │ Chroma similarity_search   │
        │ collection=ticker, k=8     │
        └──────────┬─────────────────┘
                   ▼
        ┌────────────────────────────┐
        │ Cross-encoder rerank       │
        │ keep top 4                 │
        └──────────┬─────────────────┘
                   ▼
        ┌────────────────────────────┐
        │ Build LLM prompt           │
        └──────────┬─────────────────┘
                   ▼
                Claude
                   │
                   ▼
        structured ReportSchema
```

---

## 7. Database — entity relationships

```
             ┌────────────┐
             │   users    │
             └─────┬──────┘
                   │ 1
                   │
                   │ N         ┌──────────────────┐
                   ├──────────►│ analysis_reports │
                   │           │  · ticker_symbol │
                   │           │  · question      │
                   │           │  · status        │
                   │           │  · report_json   │
                   │           │  · risk_score    │
                   │           └──────────────────┘
                   │
                   │ N         ┌────────────────┐         ┌──────────────────────┐
                   ├──────────►│ conversations  │────────►│ conversation_turns   │
                   │           │  · user_id     │ 1     N │  · role (user/asst)  │
                   │           │  · ticker_id   │         │  · content           │
                   │           └────────────────┘         │  · created_at        │
                   │                                      └──────────────────────┘
                   │
                   │ N         ┌────────────────┐
                   └──────────►│ starred_reports│ (many-to-many to analysis_reports)
                               └────────────────┘

             ┌────────────┐
             │  tickers   │ (symbol unique)
             └─────┬──────┘
                   │ 1
                   │
   ┌───────────────┼──────────────────────────────────┬───────────────┐
   │ N             │ N                                │ N             │ N
   ▼               ▼                                  ▼               ▼
┌────────┐   ┌────────────┐                     ┌──────────┐    ┌──────────────┐
│ prices │   │ financials │                     │ filings  │    │ news_articles│
│        │   │ (revenue,  │                     │  · type  │    │ (url unique) │
│        │   │  eps, p/e) │                     │  · text  │    │              │
└────────┘   └────────────┘                     │  · hash  │    └──────────────┘
                                                 └─────┬────┘
                                                       │ 1
                                                       │
                                                       │ N
                                                       ▼
                                                 ┌──────────┐         vector_id ──►  ChromaDB
                                                 │  chunks  │                          (out of DB)
                                                 │ · text   │
                                                 │ · idx    │
                                                 │ ·embed_id│
                                                 └──────────┘

   Schema is managed by Alembic (see Appendix D of terraform-study-guide.md).
   Migrations live in db/migrations/versions/.
```

### Status transitions (`AnalysisReport.status`)

```
            new /analyze
                │
                ▼
          ┌─────────┐
          │ pending │
          └────┬────┘
               │ background task picks up
               ▼
          ┌─────────┐
          │ running │
          └────┬────┘
               │                          │
   success ────┤                          ├── exception in agent
               ▼                          ▼
          ┌──────────┐               ┌─────────┐
          │completed │               │ failed  │
          └──────────┘               └─────────┘
               │
               │ user re-runs /analyze for same ticker
               ▼
          ┌────────────┐
          │overwritten │  (the *old* report; the new one is "completed")
          └────────────┘
```

The frontend's Zod schema `reportStatusSchema` must list **all four** —
otherwise the history endpoint fails validation when it returns
"overwritten" rows.

---

## 8. Security & defense in depth

Seven layers stack between an attacker and your data. Each is independent;
breaking one doesn't break the rest.

```
                       The Internet
                            │
   ─────────────────────────┼──────────────────────────
   1. Network — VPC + IGW   │   only ALB has a public route
   ─────────────────────────┼──────────────────────────
                            ▼
   ─────────────────────────────────────────────────────
   2. Firewall (ALB SG)         only :80 (and :443 if HTTPS) ingress
   ─────────────────────────────────────────────────────
                            │
                            ▼
   ─────────────────────────────────────────────────────
   3. SG chain                   API/frontend SGs accept ONLY from ALB SG.
                                 RDS/Redis/Chroma SGs accept ONLY from API SG.
   ─────────────────────────────────────────────────────
                            │
                            ▼
   ─────────────────────────────────────────────────────
   4. App authentication         JWT required on every protected route.
                                 user_id filter on every query.
   ─────────────────────────────────────────────────────
                            │
                            ▼
   ─────────────────────────────────────────────────────
   5. IAM least-privilege        execution role: pull image + secrets + logs
                                 task role:      empty (app makes no AWS calls)
                                 GitHub OIDC:    push ECR, run/update ECS,
                                                  PassRole only the two ECS roles
   ─────────────────────────────────────────────────────
                            │
                            ▼
   ─────────────────────────────────────────────────────
   6. Secrets at rest            Secrets Manager (KMS-encrypted).
                                 Never in code, image, or task def.
                                 Resolved at task launch only.
   ─────────────────────────────────────────────────────
                            │
                            ▼
   ─────────────────────────────────────────────────────
   7. Data at rest               RDS storage encrypted (KMS).
                                 EBS volumes encrypted.
                                 ECR images encrypted.
   ─────────────────────────────────────────────────────
                            ▼
                       Your data
```

### Where secrets travel

```
    terraform.tfvars  (gitignored, on your laptop)
        │
        │ terraform apply
        ▼
    Secrets Manager  (encrypted at rest, KMS, audited)
        │
        │ ECS task launch
        │ (ECS agent uses *execution role*)
        ▼
    Container environment variables  (in memory only, never disk)
        │
        │ app reads at boot
        ▼
    httpx / asyncpg / anthropic SDK
```

The value is never on disk in the image, never in a task definition JSON,
never in CloudWatch logs, never in a `git diff`. The only durable copy is
in Secrets Manager.

---

## 9. Deployment workflow

### First-time deploy

```
   ┌────────────────────────────────────────────────────┐
   │ 1. ONE-TIME SETUP                                  │
   │   • aws configure                                  │
   │   • cp terraform.tfvars.example terraform.tfvars   │
   │   • fill in secrets, github_repo                   │
   └────────────────────┬───────────────────────────────┘
                        ▼
   ┌────────────────────────────────────────────────────┐
   │ 2. PROVISION (~10–15 min)                          │
   │   $ cd infra/terraform                             │
   │   $ terraform init                                 │
   │   $ terraform plan                                 │
   │   $ terraform apply                                │
   │                                                    │
   │   Creates: VPC, subnets, IGW/NAT, SGs, ALB,        │
   │            ECR (empty), RDS (empty), ElastiCache,  │
   │            Chroma EC2 + EBS, Secrets Manager,      │
   │            IAM roles, ECS cluster + services       │
   │            (0 healthy tasks ← expected!),          │
   │            CloudWatch dashboard + alarms, SNS,     │
   │            GitHub OIDC provider + role             │
   └────────────────────┬───────────────────────────────┘
                        ▼
   ┌────────────────────────────────────────────────────┐
   │ 3. SHIP CODE & SCHEMA (~10–20 min, first time)     │
   │   $ ./infra/scripts/deploy.sh                       │
   │                                                    │
   │   ┌──────────────────────────────────────────────┐ │
   │   │ a. read all `terraform output`s              │ │
   │   │ b. docker login to ECR                       │ │
   │   │ c. docker build + push API image             │ │
   │   │ d. docker build + push frontend (ALB URL     │ │
   │   │    baked in via --build-arg)                 │ │
   │   │ e. aws ecs run-task migrate                  │ │
   │   │    (alembic upgrade head → RDS)              │ │
   │   │ f. aws ecs update-service --force-new-       │ │
   │   │    deployment   (× api, frontend)            │ │
   │   │ g. aws ecs wait services-stable              │ │
   │   └──────────────────────────────────────────────┘ │
   └────────────────────┬───────────────────────────────┘
                        ▼
   ┌────────────────────────────────────────────────────┐
   │ 4. ONE-TIME GITHUB SETUP                           │
   │   • copy github_actions_role_arn output            │
   │   • paste as AWS_DEPLOY_ROLE_ARN variable in repo  │
   └────────────────────┬───────────────────────────────┘
                        ▼
              Open the application_url in a browser
```

### Redeploys

After the first time, redeploying = step 3 only. After step 4 is wired,
`git push origin main` does step 3 automatically.

---

## 10. CI/CD flow

### `ci.yml` — runs on every PR / non-main push

```
   PR opened or push to feature branch
              │
              ▼
   ┌─────────────────────────┐
   │ GitHub Actions runner   │
   └────┬───────────────┬────┘
        │               │
        ▼               ▼
   ┌─────────┐   ┌──────────────┐    (parallel)
   │backend  │   │   frontend   │
   │job      │   │     job      │
   ├─────────┤   ├──────────────┤
   │python   │   │node 20       │
   │3.12     │   │npm ci        │
   │cpu torch│   │npm run lint  │
   │ruff     │   │npm run build │
   │pytest   │   │              │
   │unit/    │   │              │
   └────┬────┘   └──────┬───────┘
        │               │
        ▼               ▼
   ┌──────────────────────────┐
   │ Both green? PR mergeable │
   └──────────────────────────┘
```

`ci.yml` **never touches AWS** — no auth needed.

### `deploy.yml` — runs on push to main

```
   git push origin main
            │
            ▼
   ┌─────────────────────┐
   │   job: test          │ ── same as ci.yml backend job (gate)
   └──────────┬──────────┘
              │ green
              ▼
   ┌──────────────────────────────────────────────────┐
   │   job: deploy                                    │
   │                                                  │
   │  STEP 1: OIDC token exchange                     │
   │  ┌───────────────────────────────────────────┐   │
   │  │ GitHub mints JWT for this run             │   │
   │  │   sub = "repo:owner/finsight:ref:..."     │   │
   │  │ aws-actions/configure-aws-credentials@v4  │   │
   │  │  → STS AssumeRoleWithWebIdentity           │   │
   │  │  → ~1h temp creds (no stored secrets)     │   │
   │  └───────────────────────────────────────────┘   │
   │                                                  │
   │  STEP 2: docker login ECR                        │
   │                                                  │
   │  STEP 3: resolve infra (aws describe-*)          │
   │                                                  │
   │  STEP 4: build + push images                     │
   │   tags: latest  AND  <git-sha>                   │
   │                                                  │
   │  STEP 5: aws ecs run-task migrate                │
   │   wait tasks-stopped                             │
   │   check exitCode == 0                            │
   │                                                  │
   │  STEP 6: aws ecs update-service --force-new      │
   │   wait services-stable                           │
   └──────────────────────────────────────────────────┘
              │
              ▼
         New version live behind the ALB
```

Concurrency-group `deploy-production` ensures two pushes don't fight over
the same services — the second deploy queues.

### Rolling update (zoom in to step 6)

```
   time ─►

   t0:  [OLD v1 healthy]                     desired_count = 1
                                              min_healthy = 100%
                                              max_percent = 200%

   t1:  [OLD v1 healthy]   [NEW v2 starting]    ECS launches new task
                                                  (can run up to 2 tasks)

   t2:  [OLD v1 healthy]   [NEW v2 healthy]      ALB sees new target pass

   t3:                     [NEW v2 healthy]      old task drained + stopped

   At no point are there fewer than 1 healthy task.  Zero downtime.
```

---

## 11. Observability

### Three layers of "what is going on?"

```
   ┌─────────────────────────────────────────────────────────────┐
   │  LOGS — "what happened?"                                    │
   │                                                             │
   │   API container stdout ──► CloudWatch Logs                  │
   │      log group:  /ecs/finsight-prod/api                     │
   │      streams:    api/<task-id>, migrate/<task-id>           │
   │                                                             │
   │   Frontend container stdout ──► /ecs/finsight-prod/frontend │
   │                                                             │
   │   Retention: 14 days (var.log_retention_days)               │
   └─────────────────────────────────────────────────────────────┘

                              ▼  drill down to root cause

   ┌─────────────────────────────────────────────────────────────┐
   │  ALARMS — "something is wrong NOW"                          │
   │                                                             │
   │   alb-5xx              ──┐                                  │
   │   api-unhealthy-hosts  ──┤                                  │
   │   api-cpu-high         ──┼──► SNS topic ──► email           │
   │   api-memory-high      ──┤    finsight-prod-alerts          │
   │   rds-cpu-high         ──┤                                  │
   │   rds-low-storage      ──┘                                  │
   │                                                             │
   │   States:  OK  ──►  ALARM  ──►  OK  (publishes both ways)   │
   └─────────────────────────────────────────────────────────────┘

                              ▼  proactive signal

   ┌─────────────────────────────────────────────────────────────┐
   │  DASHBOARD — "how is the system TRENDING?"                  │
   │                                                             │
   │   ┌─────────────────────┐  ┌──────────────────────┐         │
   │   │ ALB requests + 5xx  │  │ API CPU / memory %   │         │
   │   └─────────────────────┘  └──────────────────────┘         │
   │   ┌─────────────────────┐  ┌──────────────────────┐         │
   │   │ RDS CPU + storage   │  │ ALB target p95 ms    │         │
   │   └─────────────────────┘  └──────────────────────┘         │
   │                                                             │
   │   URL via terraform output cloudwatch_dashboard_url         │
   └─────────────────────────────────────────────────────────────┘
```

### Alarm signal flow

```
   AWS service metric (e.g. AWS/ECS CPUUtilization)
            │
            │ every period (60 or 300s)
            ▼
   CloudWatch Metrics
            │
            ▼
   evaluate alarm:  statistic ≥ threshold for N periods?
            │
        yes ▼
   Alarm transitions OK → ALARM
            │
            ▼
   alarm_actions: publish to SNS topic
            │
            ├── email subscription ──► your inbox
            └── (future) Slack webhook, PagerDuty
            ▼
   you investigate
            │
            ▼
   metric drops below threshold
            │
            ▼
   Alarm transitions ALARM → OK   (ok_actions also publish)
            │
            ▼
   email: "alarm cleared"
```

---

## 12. State machines

### Background analysis job

```
                          POST /analyze
                                │
                                ▼
                          ┌───────────┐
                  ┌──────►│  pending  │
                  │       └─────┬─────┘
                  │             │ background task picks up
                  │             ▼
                  │       ┌───────────┐
                  │       │  running  │
                  │       └─────┬─────┘
                  │             │
                  │   ┌─────────┴─────────┐
                  │   │                   │
                  │   ▼                   ▼
                  │ ┌───────────┐  ┌───────────┐
                  │ │ completed │  │  failed   │
                  │ └─────┬─────┘  └───────────┘
                  │       │
                  │       │ user re-runs /analyze same ticker
                  │       ▼
                  │ ┌──────────────┐
                  │ │ overwritten  │   (the *old* row; new one is "completed")
                  │ └──────────────┘
                  │       ▲
                  └───────┘
```

### ECS task lifecycle

```
       run-task / desired_count++
             │
             ▼
       ┌─────────────┐
       │ PROVISIONING │  ENI being created
       └─────┬───────┘
             ▼
       ┌─────────────┐
       │   PENDING   │  image pulling
       └─────┬───────┘
             ▼
       ┌─────────────┐
       │   RUNNING   │  container started
       └─────┬───────┘
             │ health_check_grace_period (120s for API)
             ▼
       ┌─────────────┐
       │  HEALTHY    │  ALB target health passing — receives traffic
       └─────┬───────┘
             │ deregistration_delay (30s)
             ▼
       ┌─────────────┐
       │ DEPROVISIO- │  ALB drained, container SIGTERM
       │  NING       │
       └─────┬───────┘
             ▼
       ┌─────────────┐
       │   STOPPED   │  bills end
       └─────────────┘
```

### CloudWatch alarm

```
                       ┌───────────────────────┐
                       │  INSUFFICIENT_DATA    │ (first launch, no metric yet)
                       └──────────┬────────────┘
                                  │ metrics start flowing
                                  ▼
            ┌────────────────────────────────────────┐
            │                                        │
            ▼                                        │
       ┌─────────┐  threshold crossed N periods   ┌─────────┐
       │   OK    │ ────────────────────────────►  │  ALARM  │
       └─────────┘                                 └────┬────┘
            ▲                                           │
            │                                           │
            └────────────────  metric drops ◄───────────┘

       Each transition publishes to the SNS topic
       (both alarm_actions and ok_actions are set).
```

---

## 13. Quick lookup tables

### Ports

| Port | Service | Where |
|---|---|---|
| 80 | ALB HTTP | public |
| 443 | ALB HTTPS | public (future) |
| 8000 | FastAPI | container internal |
| 3000 | Next.js | container internal |
| 5432 | Postgres | RDS, private |
| 6379 | Redis | ElastiCache, private |
| 8000 | ChromaDB | EC2, private |

### TTLs

| Source | TTL | Why |
|---|---|---|
| Market data (prices, P/E) | 15 min | Frequently changing |
| SEC filings | 24 h | Filed quarterly/yearly; rarely change |
| Conversation context | last 10 turns | Bounded prompt size |
| JWT | 24 h | Balance security vs UX |
| ECR image retention | 10 most recent | Cleanup |
| CloudWatch log retention | 14 days | Cost / debug window |

### Costs (rough, eu-central-1)

| Item | ~Monthly |
|---|---|
| NAT gateway | $32 + data |
| ALB | $16 + LCU |
| RDS db.t3.micro | $13 |
| ElastiCache cache.t3.micro | $12 |
| Chroma EC2 t3.small + 8 GB EBS | $16 |
| Fargate (1 api + 1 frontend) | $35 |
| CloudWatch alarms + SNS | <$1 |
| **Total** | **~$120–140** |

### Where each thing lives

| Resource | File | Subnet tier | Public? |
|---|---|---|---|
| ALB | `infra/terraform/alb.tf` | public | yes |
| API ECS service | `infra/terraform/ecs.tf` | private | no |
| Frontend ECS service | `infra/terraform/ecs.tf` | private | no |
| RDS Postgres | `infra/terraform/rds.tf` | private | no |
| Redis | `infra/terraform/elasticache.tf` | private | no |
| Chroma EC2 | `infra/terraform/chroma.tf` | private | no |
| NAT gateway | `infra/terraform/vpc.tf` | public | yes (egress only) |
| ECR registries | `infra/terraform/ecr.tf` | regional service | yes (AWS-managed) |
| Secrets Manager | `infra/terraform/secrets.tf` | regional service | no (IAM-gated) |
| CloudWatch | `infra/terraform/cloudwatch.tf` | regional service | yes (AWS-managed) |

### "When something goes wrong, look at…"

| Symptom | First place to look |
|---|---|
| ALB 5xx alarm | CloudWatch logs `/ecs/finsight-prod/api` |
| ALB unhealthy hosts | ECS service events; `/health` endpoint locally |
| Migration task fails | `/ecs/finsight-prod/api`, stream `migrate/<task>` |
| Frontend white screen | Browser devtools (NEXT_PUBLIC_API_URL build arg?) |
| Deploy step "Configure AWS credentials" fails | `AWS_DEPLOY_ROLE_ARN` variable, `github_repo` in tfvars |
| RDS connection refused from container | SG chain — does `ecs_api` reach `rds`? Is `DATABASE_URL` correct? |
| Chroma host unreachable | SSM Session Manager, check Docker is running |
| Costs spiking | CloudWatch metric for NAT data; tag-filtered Cost Explorer |

---

## How to use this document

1. **First read** — skim §1, §2, §3 to anchor the big shapes.
2. **Studying a feature** — find the matching journey in §5.
3. **Studying a layer** — find its row in §2 and follow into §4 (agents)
   or §6 (data).
4. **Interview prep** — practice walking someone through §3 (cloud) and §10
   (CI/CD) without looking; these are the two everyone asks about.
5. **Debugging** — start at the "look at" table in §13.

> Pair this with `docs/terraform-study-guide.md` (the deep dive on every
> `.tf` file + AWS services + Alembic) and `docs/deployment/README.md` (the
> Weeks 5–8 narrative). This file is the *map*; those two are the *manual*.
