# Databases (Postgres + ChromaDB)

FinSight runs on two databases that play very different roles. This guide explains what each one stores, why we split them, and how they stay in sync.

---

## 1. The split — one sentence each

- **Postgres (RDS)** — system of record for *structured business data*: users, tickers, prices, filings, conversations, analysis reports.
- **ChromaDB** — system of record for *vectors and chunked text*: the searchable representation of every SEC filing, used by RAG.

They are not redundant. Postgres holds the raw filing text and the metadata that drives the app's CRUD operations. Chroma holds the same text *chunked, headered, and embedded* for semantic search. The two are linked by `Chunk.embedding_id` → ChromaDB vector id.

---

## 2. Postgres (RDS) — the operational database

### Engine

- **Local dev**: Postgres 16 in Docker on `localhost:5433` (`docker/docker-compose.yml`).
- **Production**: AWS RDS Postgres 16, single-AZ, in private subnets — `infra/terraform/rds.tf`.
- **Driver**: `asyncpg` via SQLAlchemy 2's async engine (`db/session.py`).
- **Pool**: 5 connections + 10 overflow, `pool_pre_ping=True`, `pool_recycle=300` — see `db/session.py:14-21`.
- **Migrations**: Alembic. `alembic upgrade head` runs automatically on Docker startup; in prod it runs as a one-shot ECS task before service rollout (`infra/scripts/deploy.sh`).

### Tables (defined in `db/models.py`)

| Table | Purpose | Key columns |
|---|---|---|
| `users` | Auth identities | `email`, `password_hash`, `google_id` |
| `tickers` | Master list of symbols + company metadata | `symbol`, `sector`, `industry` |
| `prices` | Daily OHLCV from yfinance / fallbacks | `(ticker_id, date)` unique |
| `financials` | Per-period fundamentals (revenue, EPS, margins) | `(ticker_id, period)` unique |
| `filings` | Raw SEC filings (10-K / 10-Q text) | `accession_number`, `content_hash`, `embedded_content_hash`, `period_of_report` |
| `chunks` | One row per chunk written to Chroma | `embedding_id` (link to Chroma vector) |
| `analysis_reports` | Persisted output of the multi-agent pipeline | `job_id`, `status`, `report_json`, `risk_score` |
| `conversations` | One per `(user, ticker)` | unique `(user_id, ticker)` |
| `conversation_turns` | User + assistant messages, oldest → newest | `role`, `content`, optional `job_id` |
| `news_articles` | News with sentiment, deduped by URL | unique `(ticker_id, url)` |

### Why Postgres, not just files or a vector DB

- **Relations and constraints** — `Filing` belongs to `Ticker`, `Chunk` belongs to `Filing`, cascade-delete a ticker and everything goes. Foreign keys + unique constraints prevent the "two prices for the same day" or "filing missing a ticker" bugs that quietly corrupt a NoSQL store.
- **Concurrency** — `Conversation` has a unique `(user_id, ticker)`; two concurrent chat starts race-safely into the same row instead of creating duplicates.
- **Auditability** — `created_at` / `completed_at` / `fetched_at` columns turn the DB into a usable timeline for debugging "why did the report look stale yesterday".
- **Migrations** — Alembic + autogenerate lets us change schema in code review and ship it the same way as the rest of the app.

### Non-obvious patterns

- **`content_hash` vs `embedded_content_hash`** (`db/models.py:112-115`) — When a filing's text changes (an SEC amendment, a re-fetch with cleaner HTML), we update `content_hash`. The embedder later spots `content_hash != embedded_content_hash` and re-embeds that filing only. This is the entire mechanism that keeps Chroma in sync with Postgres — see `pipelines/embedder.py:440-510` (`embed_all_pending`).
- **`period_of_report` ≠ `filed_date`** — A 10-K filed February 2025 reports on the previous fiscal year. We index on `period_of_report` for temporal filtering so a "2024 results" question doesn't surface a chunk filed in 2025 *about* 2023.
- **`ticker_symbol` is VARCHAR(30) on `analysis_reports`** — to hold comparison labels like `AAPL_vs_MSFT`, not just plain tickers.
- **Background tasks open their own engine with `NullPool`** — see `api/routers/analyze.py`. The shared pool can't be reused across the asyncio thread boundary that `asyncio.to_thread` introduces, so background jobs build a one-shot engine to avoid "Future attached to different loop" errors.
- **Free-tier note** — `backup_retention_period = 0` in `infra/terraform/rds.tf`. AWS free-tier accounts can't take automated snapshots; flip to 7 once you're off free tier.

---

## 3. ChromaDB — the embeddings database

### Engine

- **Local dev**: Chroma in Docker on `localhost:8100`.
- **Production**: `chromadb/chroma` container on a single EC2 instance, with an EBS volume mounted at the data directory — `infra/terraform/chroma.tf`. The EBS volume is the source of truth; the EC2 instance can be replaced without losing data.
- **Client**: `chromadb.HttpClient(host, port)` — async-friendly, network-only API.
- **Collection**: single collection `finsight_filings` with HNSW index, cosine distance (`rag/vector_store.py:39-42`).

### What's actually stored in a Chroma vector

Each upserted row has four parts (see `pipelines/embedder.py:355-388`):

1. **`id`** — `{TICKER}_{accession_number}_{chunk_index}`, stable across re-embeds so we can delete old vectors by id when a filing changes.
2. **`embedding`** — 3072-dim float vector from OpenAI `text-embedding-3-large`.
3. **`document`** — the *headered* chunk text: `[AAPL · 10-K · FY2024 · Item 1A (Risk Factors)] <chunk body>`. The header is prepended **before** embedding so the fiscal year and section are encoded in the vector and visible to the reranker.
4. **`metadata`** — `ticker`, `doc_type`, `filed_date`, `fiscal_year`, `accession_number`, `chunk_index`, `source_url`, `section_name`, `item_number`, `chunk_type` (`prose` / `table`), `parent_id`, `parent_text`.

### Why a separate vector store

- **HNSW > Postgres ANN** — Chroma's HNSW index gives sub-50 ms top-k over hundreds of thousands of vectors with no tuning. Postgres `pgvector` is an option, but we'd lose Chroma's metadata-where API and add load to the operational DB.
- **Separate lifecycle** — re-embedding a corpus shouldn't churn the OLTP database. Putting vectors in Chroma means we can wipe and rebuild the index without touching `analysis_reports`, `users`, or anything else.
- **Different ops profile** — Chroma is read-heavy with large value sizes (3072 floats per row); Postgres is small-row mixed read/write. Splitting them lets each run on hardware sized for its workload.

### Parent/child chunking — why every chunk has two text fields

Defined in `pipelines/embedder.py:33-37`:

```
Child chunk:  500 tokens, overlap 80   → embedded, retrieved, reranked
Parent block: 2000 tokens, overlap 200 → handed to the LLM
```

Small chunks make sharp embeddings (less averaging → less noise), so retrieval is precise. But a 500-token sliver is a bad context for an LLM — it might cut off mid-sentence or strip the surrounding context that makes the answer correct. So every child carries the larger parent block it came from (`parent_id` + `parent_text` in metadata). At read time, the retriever expands hits to their parent and de-dupes by `parent_id`. The LLM sees coherent 2000-token blocks; the search index works on tight 500-token chunks.

### Metadata-driven filtering

`VectorStore.query` (`rag/vector_store.py:101-157`) accepts `ticker`, `doc_types`, `fiscal_years` and folds them into a Chroma `$and` `where` clause. This is what scopes a question to "AAPL 10-K filings from FY2024" before similarity ranks anything — without it, a similar-sounding chunk from the wrong company can win on cosine alone.

---

## 4. How they stay in sync

```
SEC fetcher (pipelines/sec_filings.py)
  └─ writes Filing row → Postgres   (raw_text + content_hash)

embed_all_pending (pipelines/embedder.py)
  ├─ finds Filing rows where chunks missing OR content_hash != embedded_content_hash
  ├─ chunks → embeds → upserts to ChromaDB    (vector + metadata)
  ├─ writes Chunk rows → Postgres             (embedding_id, token_count)
  └─ sets Filing.embedded_content_hash = Filing.content_hash
```

The contract: **Postgres `Filing` is the source of truth for text; Chroma is a derived index.** If they drift, the recovery is to re-run `embed_all_pending` (idempotent — re-embed deletes old vectors by id before upserting).

There is no two-phase commit between them. A crash mid-embed leaves orphan vectors in Chroma, but the next `embed_all_pending` purges and rewrites them (`_purge_filing_embeddings`, `pipelines/embedder.py:417-437`). The unique vector id `{TICKER}_{accession_number}_{chunk_index}` makes this safe.

---

## 5. Operational quick reference

| Action | Command |
|---|---|
| Apply migrations | `alembic upgrade head` |
| Generate a migration from model changes | `alembic revision --autogenerate -m "msg"` |
| Roll back one migration | `alembic downgrade -1` |
| Ingest tickers (Postgres + Chroma in one shot) | `python -m scripts.ingest_ticker AAPL MSFT` |
| Health check both DBs | `curl localhost:8000/health` → returns `db`, `redis`, `chroma` |
| Re-embed only what changed | `await embed_all_pending(session)` |

### Backup posture (production)

- **Postgres** — RDS automated snapshots. Currently `backup_retention_period = 0` for free-tier; flip to 7 days when off free tier.
- **ChromaDB** — data lives on EBS. EBS snapshots are not configured by Terraform today; add a snapshot lifecycle policy (DLM) before storing anything you can't re-derive.
- **Re-derivability** — Chroma can be fully rebuilt from Postgres `Filing.raw_text` by running `embed_all_pending`. Treat it as a cache that's expensive to warm but not irreplaceable.
