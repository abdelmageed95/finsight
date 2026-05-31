# FinSight pipeline agents

How a question becomes a research report.

FinSight runs a **multi-agent pipeline** built on [LangGraph](https://langchain-ai.github.io/langgraph/).
A `POST /analyze` request kicks off a background task that invokes a compiled
`StateGraph`; the graph routes the request through a chain of agent nodes that
each do one job and hand control back to a supervisor.

```
                    ┌─────────────┐
   POST /analyze ──► │ Supervisor  │ ── intent classification
                    └──────┬──────┘
            greeting /     │      research_query
            smalltalk      │
          ┌────────────────┴───────────────────────────┐
          ▼                                            ▼
  ┌────────────────┐                          ┌──────────────────┐
  │ SmallTalkAgent │                          │   DataAgent      │  "The Collector"
  │  fast reply    │                          │  fetch + embed   │
  └───────┬────────┘                          └────────┬─────────┘
          │                                            ▼
          │                                   ┌──────────────────┐
          │                                   │   RAGAgent       │  "The Analyst"
          │                                   │  retrieve + LLM  │
          │                                   └────────┬─────────┘
          │                                            ▼
          │                                   ┌──────────────────┐
          │                                   │   ReportAgent    │  "The Publisher"
          │                                   │  format + score  │
          │                                   └────────┬─────────┘
          ▼                                            ▼
        END                                          END
```

Two paths leave the supervisor:

- **greeting / smalltalk** → `SmallTalkAgent` → END (fast, ~2 s, no data fetch)
- **research_query** → `DataAgent` → `RAGAgent` → `ReportAgent` → END (~15–40 s)

Every node returns control to the supervisor via a LangGraph `Command`; the
supervisor advances the pipeline deterministically until the report is done.

**Model policy:** every LLM call uses **Claude Haiku 4.5**
(`claude-haiku-4-5-20251001`). OpenAI is used **only** for embeddings
(`text-embedding-3-large`).

---

## Graph state

All nodes read and write a single shared `GraphState` (`agents/orchestrator.py`).
It is a `TypedDict`; several fields use **custom reducers** so concurrent or
sequential writes merge instead of clobber:

| Field | Type | Reducer | Meaning |
|---|---|---|---|
| `messages` | `list[AnyMessage]` | `add_messages` | Conversation/trace log — every node appends one |
| `ticker` | `str` | — | Symbol under analysis (e.g. `AAPL`) |
| `question` | `str` | — | The user's natural-language question |
| `intent` | `str` | — | `greeting` / `smalltalk` / `research_query` (set by supervisor) |
| `job_id` | `str` | — | SSE job id for progress streaming |
| `prior_turns` | `list[dict]` | — | Previous chat turns for multi-turn context |
| `financial_context` | `str` | — | Structured multi-year financials block (set by data agent, read by RAG agent) |
| `retrieved_docs` | `list[dict]` | `extend_list` | Source chunks the RAG agent used (appended) |
| `tool_results` | `dict` | `merge_dicts` | Per-agent output, keyed by agent name |
| `final_report` | `dict` | `merge_dicts` | The finished report |

`tool_results` is the pipeline's progress ledger — the supervisor decides what
runs next purely by checking which agent keys are already present.

---

## 1. Supervisor

**File:** `agents/orchestrator.py` · `supervisor_node`
**Job:** classify intent, then route — and keep routing until the pipeline is done.

The supervisor is entered **once at the start** and **again after every agent**.
Its behaviour depends on whether `tool_results` is empty:

### First entry — intent classification

1. **Regex fast-path** (`_fast_greeting_check`) — a ≤4-word message made only of
   known greeting words (`hi`, `hello`, `thanks`, …) is classified `greeting`
   instantly, with **zero API cost**.
2. **LLM classifier** — otherwise, a Claude Haiku call with structured output
   (`IntentClassification`) labels the message `greeting`, `smalltalk`, or
   `research_query`. If the classifier errors, it **defaults to
   `research_query`** — better to answer a real question than brush it off.

Routing:
- `greeting` / `smalltalk` → `smalltalk_agent`
- `research_query` → `data_agent`

### Subsequent entries — deterministic advancement

After an agent finishes it returns `goto="supervisor"`. The supervisor then
walks the pipeline by inspecting `tool_results`:

```
data_agent not done   → data_agent
rag_agent not done    → rag_agent
final_report empty    → report_agent
otherwise             → END
```

No LLM call here — it is pure, deterministic state inspection.

---

## 2. SmallTalkAgent

**File:** `agents/orchestrator.py` · `smalltalk_agent_node`
**Job:** answer greetings and meta questions ("what can you do?") — then END.

A single Claude Haiku call (temperature 0.7) produces a 1–3 sentence reply. The
reply is slotted into `final_report.summary` with `risk_score=None` and empty
`citations`, so the **existing frontend polling code renders it with no
special-casing**. No data fetch, no retrieval — this path is deliberately cheap.

---

## 3. DataAgent — "The Collector"

**File:** `agents/data_agent.py` · `data_agent_node`
**Job:** make sure fresh market data, SEC filings, news, and embeddings exist for
the ticker. **No LLM calls** — this is pure data engineering.

It runs four pipelines (`agents/../pipelines/`):

| Pipeline | What it does | Refresh policy |
|---|---|---|
| `market_data` | Prices + financials (yfinance → Massive → Twelve Data → EODHD → Tiingo fallback chain) | **TTL 15 min** |
| `sec_filings` | Downloads 10-K / 10-Q from SEC EDGAR | **TTL 24 h** (EDGAR is slow; filings rarely change) |
| `news_fetcher` | Headlines + sentiment (Alpha Vantage) | always (cheap) |
| `embedder` | Chunks + embeds any unembedded filings | always (short-circuits if nothing pending) |

**Freshness check:** if the `Ticker` row was updated within the TTL window, that
pipeline is skipped (`cache hit`). This is what makes a re-analysis fast.

### Two non-obvious details

- **Own database engine.** `_fetch_all` builds a *fresh* async engine with
  `NullPool` bound to the current event loop. The graph runs sync inside a
  worker thread (`asyncio.to_thread`); reusing the main FastAPI engine there
  triggers asyncpg's *"Future attached to a different loop"* error.
- **Errors are collected, not raised.** Each pipeline is wrapped in try/except;
  failures are appended to an `errors` list so one bad source (e.g. a news API
  hiccup) doesn't abort the whole analysis.

### Structured financial-history block

After the pipelines run, the DataAgent calls `build_financial_context`
(`pipelines/financial_summary.py`) — it already holds a DB session — to render
a compact markdown table of revenue, net income, EPS, and gross margin for the
last ~5 fiscal years and ~4 quarters, plus a price snapshot. This block is
lifted onto the top-level `financial_context` state field for the RAG agent to
read. It exists because the RAG report is grounded in filing *text*; without it
the LLM has no reliable multi-year number series (see §4.7).

Output: `tool_results["data_agent"]` = `{market, sec, news, embed, errors}`,
plus `state["financial_context"]`.

---

## 4. RAGAgent — "The Analyst"  ⭐

**File:** `agents/rag_agent.py` · `rag_agent_node`
**Job:** turn the user's question + the indexed filings into a structured,
cited, risk-scored research report.

This is the heart of FinSight. The node itself is thin — it delegates to the
**RAG chain** (`rag/chain.py`). Below is the full mechanism.

### 4.0 The node

```python
chain = create_rag_chain(use_reranker=True, top_k=16, rerank_top_n=8, mode="report")
report, source_chunks = chain.invoke(
    ticker, question,
    prior_turns=prior_turns,
    financial_context=state["financial_context"],   # from the DataAgent
)
```

After the chain returns it applies a **hard guard** and publishes results:

- **Citation guard** (`MIN_CITATIONS_FOR_RISK = 3`) — if the report has fewer
  than 3 citations, `risk_score` is forced to `None` and `confidence` to `low`.
  A risk score with no sources behind it is a hallucination; this is the belt to
  the prompt's suspenders.
- **`retrieved_docs`** is populated from `source_chunks` — the *actual parent
  blocks the LLM read* (text, doc_type, fiscal_year, source_url, …). This is
  what citation-faithfulness checks compare against.
- A **partial preview** (`summary`, `risk_score`, `confidence`) is streamed to
  the SSE bus at 90 % so the UI can render before persistence finishes.

### 4.1 The RAG chain — pipeline overview

`RAGChain.invoke` (`rag/chain.py`) is a six-step pipeline:

```
question
   │
   ▼  ① HYBRID RETRIEVE   dense (vector) ⊕ BM25 (keyword)  ─ fused by RRF
   │     + temporal filter (fiscal year) with soft fallback
   ▼  ② FILTER TO LATEST  keep newest 10-K + 10-Q only (report mode)
   ▼  ③ RERANK            cross-encoder scores each (query, child) pair
   ▼  ④ EXPAND TO PARENTS swap each child for its larger parent block
   │     + cap context to a token budget
   ▼  ⑤ BUILD PROMPT      financial table + numbered context + system + prior turns
   ▼  ⑥ LLM               Claude Haiku → structured ReportSchema
report, parent_chunks
```

### 4.2 The index: parent / child chunking

Built offline by `pipelines/embedder.py` (`chunk_filing`). Filings are split at
**two granularities**:

- **Child chunks (~500 tokens)** — *embedded and retrieved*. Small chunks give a
  sharp, un-blurred embedding, so similarity search is precise.
- **Parent blocks (~2000 tokens)** — *what the LLM reads*. Each child stores its
  `parent_id` and full `parent_text`.

The principle: **search precise, read rich**. You retrieve on a tight 500-token
chunk but answer from the 2000-token block around it, so the model never sees a
fact stranded without its context.

Each chunk is also prefixed with a **temporal/provenance header** (ticker,
filing type, fiscal year, section) before embedding, so the fiscal year is
encoded into the vector itself. Tables are chunked separately and tagged.

### 4.3 Step ① — Hybrid retrieval

**File:** `rag/retriever.py` · `HybridRetriever`

Two retrievers run over the same candidate corpus:

- **Dense** — the question is embedded (`text-embedding-3-large`) and ChromaDB
  does a cosine-similarity search. Catches *paraphrase* and *semantic* matches.
- **BM25** — a lexical keyword index (`rank_bm25`) built in-memory over the
  ticker's chunks. Catches *exact terms* an embedding blurs: statute numbers,
  `Item 1A`, product names, tickers.

Their two rankings are merged by **Reciprocal Rank Fusion**:

```
score(doc) = Σ  1 / (k + rank_in_list)        # k = 60
```

RRF needs no score-scale tuning — it fuses on *rank position* alone. If
`rank_bm25` is unavailable, hybrid degrades gracefully to dense-only.

**Temporal disambiguation.** `extract_fiscal_years` (`rag/temporal.py`) parses
year intent from the question ("in 2025", "FY25", "last year"). When a year is
found, retrieval is hard-filtered to chunks from that fiscal year, so a
similar-but-wrong-year chunk can't win on similarity alone.

**Soft fallback.** If the year filter returns fewer than `MIN_TEMPORAL_CHUNKS`
(4) chunks — e.g. the year isn't in the index — retrieval is re-run **unfiltered**.
A slightly year-mixed answer beats no answer; the temporal headers still let the
reranker and LLM tell years apart.

### 4.4 Step ② — Filter to latest filings

In `report` mode, `filter_to_latest_filings` keeps only chunks from the most
recent 10-K and most recent 10-Q (by filed date). This stops a report from
blending this year's and last year's numbers. `chat` mode skips this for
historical depth.

### 4.5 Step ③ — Reranking

**File:** `rag/reranker.py` · `CrossEncoderReranker`

Vector search is fast but imprecise; a **cross-encoder** re-scores each
`(question, child_chunk)` pair *directly* — far more accurate than comparing
pre-computed embeddings. Model: **`Alibaba-NLP/gte-reranker-modernbert-base`**,
an 8192-token-context reranker, so it scores full chunks without truncation. The
model is loaded **once per process** (cached behind a lock) — not per request.

### 4.6 Step ④ — Parent expansion + context cap

`expand_to_parents` takes the top reranked **children**, de-duplicates them by
`parent_id`, and swaps each one's text for its larger **`parent_text`**. The LLM
now reads coherent ~2000-token blocks instead of 500-token slivers.

`cap_context_tokens` then trims the parent list to a **5000-token budget**
(`MAX_CONTEXT_TOKENS`). Unbounded context balloons cost, risks the model's input
limit, and dilutes the answer ("lost in the middle").

### 4.7 Steps ⑤–⑥ — Prompt + structured generation

The prompt the LLM sees has **two distinct context sections**:

- **`## Historical Financials`** — the `financial_context` block the DataAgent
  built (`pipelines/financial_summary.py`): a structured table of revenue, net
  income, EPS, and margins for ~5 fiscal years + ~4 quarters, plus a price
  snapshot. `RAG_SYSTEM_PROMPT` instructs the model to treat it as the
  **authoritative source for figures and year-over-year trends**. This exists
  because numbers parsed from filing prose — or stranded in a table chunk that
  didn't survive retrieval — are unreliable; the structured table is exact and
  complete. It is ~300 tokens, budgeted separately from `MAX_CONTEXT_TOKENS`.
- **`## Retrieved Sources`** — the capped parent blocks, formatted into a
  numbered, cited context block (`[Source 1] 10-K | NVDA | FY2026 | …`). These
  supply the narrative, segment, and risk detail the table cannot.

Both are injected into `RAG_SYSTEM_PROMPT` and sent to Claude Haiku alongside
the last ≤10 prior turns.

The LLM is called with **structured output** — it must return a
`ReportSchema` (`rag/schemas.py`): `summary`, `executive_summary`, SWOT,
`risk_score` + `risk_breakdown` (4 categories), `key_metrics`, `citations`,
bull/bear case, catalysts, moat, valuation, `confidence`.

`ReportSchema` carries **defensive `field_validator`s** (`mode="before"`): when
retrieval is thin the model sometimes writes prose into a list field, or
`'<UNKNOWN>'` into a numeric one. The validators coerce these to safe defaults
(`[]`, `None`) so one bad field can't fail-validate and discard a whole report.

`invoke` returns `(report, parent_chunks)` — the parents are the exact text the
LLM saw, so downstream faithfulness scoring checks citations against the right
source.

### ChatChain — the lightweight sibling

`ChatChain` (`rag/chain.py`) reuses the same retrieve → rerank → expand → cap
machinery but skips structured output: it streams a plain-text conversational
answer with short citation labels. It backs the `/conversations` endpoint; the
heavy `RAGChain` backs `/analyze`.

---

## 5. ReportAgent — "The Publisher"

**File:** `agents/report_agent.py` · `report_agent_node`
**Job:** turn the RAG agent's raw structured output into the final user-facing
report — then END.

- Copies the analysis fields out of `tool_results["rag_agent"]`.
- **Normalises the risk score to a level** (`_score_to_level`):
  `≤25 LOW · ≤50 MODERATE · ≤75 ELEVATED · >75 HIGH`; `None → UNKNOWN`.
- Adds metadata: `generated_at`, `retrieved_docs_count`, `data_agent_results`.
- Builds a human-readable text rendering and publishes a 98 % progress event.
- Emits the finished `final_report` and routes to `END`.

`risk_score` stays **nullable end to end** — if the RAG agent surfaced `None`
(sparse retrieval), the report shows `UNKNOWN`, never a fabricated number.
Persistence of the `AnalysisReport` row is handled by the API background task
(`api/routers/analyze.py`), not this node.

---

## End-to-end: a research query

```
POST /analyze {ticker: NVDA, question: "biggest risks?"}
  │
  ├─ Supervisor      classify → research_query → data_agent
  ├─ DataAgent       market (TTL?) · SEC (TTL?) · news · embed   → tool_results[data_agent]
  │                  + build financials block                    → state.financial_context
  ├─ Supervisor      data done → rag_agent
  ├─ RAGAgent        hybrid retrieve → rerank → expand            → tool_results[rag_agent]
  │                  + financials block → Haiku
  │                  citation guard, partial preview @ 90%
  ├─ Supervisor      rag done → report_agent
  ├─ ReportAgent     normalise score, add metadata               → final_report
  └─ END
GET /report/{job_id}  ◄── polls final_report
```

A greeting short-circuits after the supervisor: `Supervisor → SmallTalkAgent → END`.

## State progression

| After node | `tool_results` keys | `final_report` | `intent` |
|---|---|---|---|
| Supervisor (1st) | — | — | set |
| DataAgent | `data_agent` | — | — |
| RAGAgent | `+ rag_agent` | — | — |
| ReportAgent | — | **set** | — |
| SmallTalkAgent | — | **set** (reply) | — |

## File map

| Concern | File |
|---|---|
| Graph wiring, state, supervisor, smalltalk | `agents/orchestrator.py` |
| Data ingestion node | `agents/data_agent.py` |
| RAG analysis node | `agents/rag_agent.py` |
| Report formatting node | `agents/report_agent.py` |
| RAG chain (retrieve→rerank→expand→LLM) | `rag/chain.py` |
| Hybrid retrieval, BM25, RRF, parent expansion | `rag/retriever.py` |
| Cross-encoder reranker | `rag/reranker.py` |
| Vector store (ChromaDB) | `rag/vector_store.py` |
| Fiscal-year extraction | `rag/temporal.py` |
| Structured output schema | `rag/schemas.py` |
| Chunking + embedding | `pipelines/embedder.py` |
| Structured financials block for the prompt | `pipelines/financial_summary.py` |

See also: [`docs/evals/README.md`](../evals/README.md) — the evaluation harness
that scores this pipeline.
