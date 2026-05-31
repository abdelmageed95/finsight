# FinSight evaluation harness

Quantifies pipeline quality on a labeled set of queries. Lets us compare
runs (e.g. before/after a retrieval change) and quote real numbers on the
project README + resume.

The harness invokes the **real** LangGraph pipeline end to end — supervisor →
data agent → RAG agent → report agent — so it measures the system as shipped,
not a mock.

## Quick start

```bash
# Run the full dataset
python -m tests.evals.run_evals

# Iterate fast on 2 rows, no LLM judge (cheap)
python -m tests.evals.run_evals --limit 2 --no-llm-judge

# Run specific rows
python -m tests.evals.run_evals --ids aapl-001,smalltalk-001

# Pace rows to stay under a low per-minute API rate limit
python -m tests.evals.run_evals --row-delay 70

# Also log the run to MLflow (see "MLflow tracking" below)
python -m tests.evals.run_evals --mlflow
```

Results are written to `evals/results/<UTC-timestamp>/`:

- `results.json` — full per-row data (scores, slim report, retrieved-doc count)
- `results.md` — human-readable summary table + failure highlights

The runner also prints a colored summary block to stdout.

## CLI reference

| Flag | Default | Effect |
|---|---|---|
| `--dataset PATH` | `tests/evals/dataset.jsonl` | Dataset to load. |
| `--out DIR` | `evals/results` | Parent dir; a timestamped subdir is created under it. |
| `--limit N` | — | Run only the first N rows. |
| `--ids a,b,c` | — | Run only these row ids (overrides `--limit`). |
| `--no-llm-judge` | off | Skip the LLM judge for faithfulness — substring matching only. |
| `--thread-prefix S` | `eval` | Prefix for LangGraph `thread_id`s; namespaces concurrent runs. |
| `--row-delay SEC` | `0` | Sleep between rows. Use to stay under a per-minute API rate limit. |
| `--mlflow` | off | Also log params/metrics/artifacts to MLflow. |

Also honored: env var `FINSIGHT_EVAL_THREAD_PREFIX`.

## How the harness works

`tests/evals/` contains four files:

| File | Role |
|---|---|
| `run_evals.py` | CLI runner — load → invoke → score → aggregate → write. |
| `scorers.py` | The five scorers + the LLM judge. |
| `report.py` | Renders `results.md`. |
| `dataset.jsonl` | The labeled query set. |

The per-run flow (`run_evals.main`):

1. **Load** — `load_dataset` reads `dataset.jsonl`, skipping blank lines and
   `//` comments. `--ids` / `--limit` subset the rows.
2. **Invoke** — for each row, `run_one` builds a fresh graph
   (`build_graph()`), constructs the initial `GraphState`
   (`messages`, `ticker`, `question`, …), and calls `graph.invoke` with a
   `thread_id` of `<thread-prefix>-<row-id>`. Wall-clock time around
   `graph.invoke` is the row's latency.
   - The research path doesn't carry `intent` through `final_report`, so
     `run_one` merges `state["intent"]` back in — refusal scoring needs it.
   - Returns `(final_report, retrieved_docs, latency)`. `retrieved_docs` is the
     parent-block chunks the RAG agent fed the LLM, **plus** the structured
     financial-history block (`state["financial_context"]`) appended as a
     synthetic `doc_type: "financials"` source — both are things the LLM read,
     so both belong in the faithfulness source pool.
3. **Score** — `score_row` runs all five scorers on the report.
4. **Aggregate** — `aggregate` computes the mean of each scorer and latency
   percentiles across rows.
5. **Write** — `write_results` emits `results.json` + `results.md`;
   `print_summary` prints the stdout block; `--mlflow` logs the run.

A row that raises is caught — its `error` is recorded, its `scores` are `{}`,
and the run continues.

## What it measures

Each scorer returns a dict with a `score` in `[0, 1]` (or `None` when skipped).

### Faithfulness — are citations grounded?

`score_faithfulness(report, retrieved_docs, use_llm)`. For each `Citation` in the
report it checks the `excerpt` against the joined retrieved-chunk text
(capped at 8000 chars), in **two stages**:

1. **Substring match** — `excerpt[:80]` (case-insensitive) appears verbatim in
   the chunks → `SUPPORTED`. Cheap, catches direct quotes.
2. **LLM judge** — otherwise a Claude Haiku call (`_llm_judge`) labels the
   (claim, source) pair `SUPPORTED` / `PARTIAL` / `UNSUPPORTED`. Temperature 0,
   `max_tokens` 8; an unrecognised reply defaults to `UNSUPPORTED`.

Score:

```
faithfulness = (n_SUPPORTED + 0.5 · n_PARTIAL) / n_citations
```

A report with **zero citations scores 1.0** — a greeting legitimately has none.
`retrieved_docs` here are the **parent blocks** the RAG agent surfaced *and* the
structured financial-history block (each dict carries a `text` key); the scorer
reads `d["content"] or d["text"]`. Including the financials block matters: the
RAG prompt feeds the LLM that table as an authoritative source, so a citation
grounded in it must be checkable — otherwise faithfulness would falsely flag a
correctly-sourced figure as `UNSUPPORTED`.

### Factuality — `must_contain` coverage

`score_factuality(report, must_contain)`. Case-insensitive substring search for
each required term over a haystack of `summary + executive_summary + bull_case +
bear_case + risk_rationale`.

```
factuality = n_matched / n_required        # 1.0 when must_contain is empty
```

### Doc-type coverage

`score_citation_doctypes(report, must_cite_doc_types)`. Did the report cite at
least one source of each required `doc_type`? Set membership over
`{c.doc_type.upper() for c in citations}`.

```
doc_type = n_matched / n_required          # 1.0 when no doc types required
```

### Refusal / routing correctness

`score_refusal_correctness(report, expected_intent, is_refusal)`. Binary —
`1.0` only if **both** hold:

- **intent_correct** — `report.intent` equals `expected_intent`; or, when
  `expected_intent` is null, it falls in the right family
  (`is_refusal` → `greeting`/`smalltalk`; else → `research_query`).
- **shape_correct** — a refusal report has *no* `risk_score` and *no*
  citations; a research report has a non-empty `summary`.

This catches both misrouting *and* a pipeline that hallucinated a risk score
for "hello".

### Risk band

`score_risk_band(report, expected_band)`. Bands: `low` 0–33, `medium` 34–66,
`high` 67–100. Score is `1.0` if `risk_score` lands in the band, else `0.0`.
**Skipped** (`score=None`) when `expected_risk_band` is null.

### Aggregation

- **Means** — `aggregate.mean_of` averages a scorer across rows, *skipping*
  rows where the section is missing (errored row) or `score is None` (skipped
  scorer). A scorer skipped on every row aggregates to `None`.
- **Latency** — p50 / p95 / mean of per-row wall-clock around `graph.invoke`.
  The percentile index is `round(p/100 · (n−1))` into the sorted list
  (nearest-rank, no interpolation).

Cost is **not** scored yet — that comes with Track 2 (observability).

## Output files

`results.json`:

```jsonc
{
  "meta":    { "timestamp", "dataset", "n_rows", "use_llm_judge", "thread_prefix" },
  "summary": { "mean_faithfulness", "mean_factuality", "mean_citation_doctypes",
               "mean_refusal_correctness", "mean_risk_band",
               "p50_latency_s", "p95_latency_s", "mean_latency_s", "n_rows" },
  "rows":    [ { "id", "ticker", "query", "latency_s",
                 "report":  { /* slim: intent, summary[:500], risk_score, … */ },
                 "n_retrieved_docs", "scores": { /* the 5 scorer dicts */ },
                 "error" } ]
}
```

The `report` field is **slimmed** (`_slim_report`) — truncated summaries and
counts only — so the JSON stays small. `results.md` (from `report.py`) renders
the summary table, a per-row table, and a "Notable failures" section.

## Dataset format (`tests/evals/dataset.jsonl`)

One JSON object per line:

```json
{
  "id": "aapl-002",
  "ticker": "AAPL",
  "query": "What are the biggest risks facing Apple right now?",
  "must_contain": ["China", "competition"],
  "must_cite_doc_types": ["10-K"],
  "expected_intent": "research_query",
  "expected_risk_band": "medium",
  "is_refusal": false,
  "notes": "Risk question — expect medium risk band."
}
```

| Field | Required | Meaning |
|---|---|---|
| `id` | yes | Stable identifier; used as the LangGraph thread_id suffix. |
| `ticker` | yes | Symbol (uppercased before invocation). |
| `query` | yes | The user message. |
| `must_contain` | no | Substrings the report must mention (case-insensitive). |
| `must_cite_doc_types` | no | Doc types that must appear in citations. |
| `expected_intent` | no | `greeting` / `smalltalk` / `research_query`. |
| `expected_risk_band` | no | `low` / `medium` / `high`. Skipped if null. |
| `is_refusal` | yes | True for greetings/smalltalk; the report should be empty of analysis. |
| `notes` | no | Free-text, ignored by the runner. |

Blank lines and lines starting with `//` are skipped by the loader, so the file
can be commented.

### The `is_refusal` flag

`is_refusal` marks **what kind of input a row is** — and therefore **how the
harness scores it**. The word is slightly misleading: it does *not* mean the
model rejects the user. It means *"this row expects the pipeline to decline to
do research analysis."*

| | `is_refusal: false` | `is_refusal: true` |
|---|---|---|
| The row is | a genuine research question ("What are NVIDIA's biggest risks?") | a greeting / smalltalk ("hi", "thanks!") |
| Correct behaviour | run the whole pipeline (Data → RAG → Report) and produce a report with summary, citations, `risk_score` | route to `SmallTalkAgent`, reply fast — **no** data fetch, **no** report, **no** `risk_score` |
| Scored on | faithfulness, factuality, doc-type coverage, risk band | refusal correctness — did it route to smalltalk *and* stay empty of analysis? |
| A failure means | the model gave a bad/unsupported answer | it ran the full pipeline on "hello", or hallucinated a risk score for a greeting |

### Provenance

The dataset ships with **37 rows**: 31 research questions across 6 tickers
(NVDA, AAPL, MSFT, GOOGL, AMZN, JPM) plus 6 routing/refusal cases. Every
research row is grounded in that company's most recent 10-K, verified against
SEC EDGAR. `must_contain` values are deliberately robust substrings — e.g.
`"competit"` matches competition/competitive/competitors.

To grow it, append rows. Re-run after every prompt or retrieval change, and
add a row whenever you find a bug (it becomes a regression test). When
labeling, read the actual filing — a wrong label silently punishes a correct
model.

## Caching

The LLM judge caches verdicts on disk at `tests/evals/.judge_cache.json`,
keyed on `sha256(claim || source)`. Re-runs are nearly free as long as
citations are stable. Delete the file to force re-judging.

Note: the key includes the *source* text, so a retrieval change that alters the
chunks behind a citation correctly produces a cache miss and re-judges.

## MLflow tracking

`--mlflow` additionally logs the run to MLflow, turning the timestamped
result folders into comparable runs you can chart over time:

```bash
python -m tests.evals.run_evals --mlflow
mlflow ui   # browse runs at http://localhost:5000
```

Each run is logged to the `finsight-evals` experiment:

- **params** — dataset path, `n_rows`, `use_llm_judge`, `thread_prefix`
- **metrics** — every aggregate score (`mean_faithfulness`, …) + `p50/p95/mean`
  latency + `n_errors`. A scorer skipped on every row (e.g. all risk bands
  null) logs no metric — MLflow rejects `None`.
- **artifacts** — the run's `results.json` and `results.md`

Tracking is local/file-based by default (`./mlruns` + `mlflow.db` in the cwd);
set `MLFLOW_TRACKING_URI` to log to a server instead. The flag is **off by
default**, and a missing `mlflow` install is a soft skip — the core harness
never depends on it. Install via `pip install -r requirements-dev.txt`.

The JSON/Markdown writers still run regardless of `--mlflow`; MLflow logging
is purely additive.

## API rate limits & pacing

Each research row makes real LLM calls; with the LLM judge enabled, faithfulness
adds one Claude call per *un-cached* citation. On a low-tier Anthropic account
(e.g. a 10k-input-tokens/minute limit) a back-to-back run can trip `429
RateLimitError`.

Mitigations, in order of preference:

1. **`--row-delay 70`** — pace rows so the per-minute budget refills between
   them.
2. **`--no-llm-judge`** while iterating — removes the judge's calls entirely.
3. The pipeline's LLM clients use `max_retries=8` and honor the `retry-after`
   header, so isolated bursts self-heal — but a sustained run still needs (1).
4. Raise the account tier for the full 37-row run.

## When to run

- Before merging any change to: prompts, retrieval, RAG chain, supervisor logic.
- Nightly (CI) once you wire it up — gate on regressions vs `main`, not absolute scores.
- Right before updating the resume number.

## Latest results

_Populate after the first real run:_

```
Date:        YYYY-MM-DD
Git SHA:     <short>
Faithfulness: 0.XX   Factuality: 0.XX   p95: XXs
```

## Limitations

- The pipeline calls real LLM + market data + SEC EDGAR APIs every run.
  Use `--limit` while iterating.
- Faithfulness via LLM-judge is one model judging another — not gospel.
  Spot-check the worst-scoring rows manually.
- Substring-only faithfulness (`--no-llm-judge`) is *stricter* than the judged
  score — it can't credit a correctly-paraphrased citation. Compare like with
  like across runs.
- The dataset is 37 rows — solid for catching regressions, but still small.
  Treat single-run scores as directional; trust trends across runs more.
- `expected_risk_band` is set on only 3 rows (NVDA, GOOGL, JPM risk
  questions) where "not low, not extreme" is clearly defensible. The band
  boundary (33/34) sits right where healthy mega-caps score, so most rows
  leave it null rather than ship a coin-flip label.
- Rows run sequentially — a 37-row judged run is long. See "API rate limits".
