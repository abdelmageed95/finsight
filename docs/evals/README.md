# FinSight evaluation harness

Quantifies pipeline quality on a labeled set of queries. Lets us compare
runs (e.g. before/after a retrieval change) and quote real numbers on the
project README + resume.

## Quick start

```bash
# Run the full dataset
python -m tests.evals.run_evals

# Iterate fast on 2 rows, no LLM judge (cheap)
python -m tests.evals.run_evals --limit 2 --no-llm-judge

# Run specific rows
python -m tests.evals.run_evals --ids aapl-001,smalltalk-001

# Also log the run to MLflow (see "MLflow tracking" below)
python -m tests.evals.run_evals --mlflow
```

Results are written to `evals/results/<UTC-timestamp>/`:

- `results.json` — full per-row data (scores, slim report, retrieved-doc count)
- `results.md` — human-readable summary table + failure highlights

The runner also prints a colored summary block to stdout.

## What it measures

| Scorer | What it checks | How |
|---|---|---|
| **Faithfulness** | Each citation excerpt actually appears in (or is supported by) the retrieved chunks. | Substring match first, then LLM-judge fallback (`SUPPORTED` / `PARTIAL` / `UNSUPPORTED`). |
| **Factuality** | The report mentions every required keyword from `must_contain`. | Case-insensitive substring over summary + executive_summary + bull/bear case. |
| **Doc-type coverage** | The report cites at least one source of each required `doc_type` (10-K, 10-Q, …). | Set membership on `Citation.doc_type`. |
| **Refusal correctness** | The supervisor routed correctly: smalltalk/greeting → smalltalk_agent; research → full pipeline. | Compares `report.intent` vs `expected_intent`, plus shape checks (no risk_score on a refusal). |
| **Risk band** | `risk_score` falls in `low` (0–33), `medium` (34–66), or `high` (67–100). | Skipped when `expected_risk_band` is null. |

Latency: wall-clock around `graph.invoke`. p50 / p95 / mean reported.

Cost is **not** scored yet — that comes with Track 2 (observability).

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

The dataset ships with **37 rows**: 31 research questions across 6 tickers
(NVDA, AAPL, MSFT, GOOGL, AMZN, JPM) plus 6 routing/refusal cases. Every
research row is grounded in that company's most recent 10-K, verified against
SEC EDGAR. `must_contain` values are deliberately robust substrings — e.g.
`"competit"` matches competition/competitive/competitors.
```
Note:
  is_refusal marks what kind of input a row is — and therefore how the harness 
  scores it.

  is_refusal: false — a real research question

  The row is a genuine query about a company ("What are NVIDIA's biggest
  risks?"). The pipeline is expected to do the full job:

  - run the whole pipeline (DataAgent → RAGAgent → ReportAgent)
  - produce a report with a summary, citations, risk_score, etc.
  - the row gets scored on faithfulness, factuality, doc-type coverage, risk 
  band

  A failure here = the model gave a bad/unsupported answer.

  is_refusal: true — a greeting or smalltalk

  The row is not a research question ("hi", "how are you?", "thanks!"). The
  correct behavior is the opposite — the pipeline should not do analysis:

  - the Supervisor should route it to SmallTalkAgent
  - it should reply fast, with no data fetch, no report, no risk_score
  - the row gets scored on refusal correctness — did it route to smalltalk and
  stay empty of analysis?

  A failure here = the model wasted time/money running the full pipeline on
  "hello", or hallucinated a risk score for a greeting.

  Why the flag exists

  The word "refusal" is slightly misleading — it doesn't mean the model rejects
  the user. It means "this row expects the pipeline to decline to do research 
  analysis."
```


To grow it, append rows. Re-run after every prompt or retrieval change, and
add a row whenever you find a bug (it becomes a regression test). When
labeling, read the actual filing — a wrong label silently punishes a correct
model.

## Caching

The LLM judge caches verdicts on disk at `tests/evals/.judge_cache.json`,
keyed on `sha256(claim || source)`. Re-runs are nearly free as long as
citations are stable. Delete the file to force re-judging.

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
- The dataset is 37 rows — solid for catching regressions, but still small.
  Treat single-run scores as directional; trust trends across runs more.
- `expected_risk_band` is set on only 3 rows (NVDA, GOOGL, JPM risk
  questions) where "not low, not extreme" is clearly defensible. The band
  boundary (33/34) sits right where healthy mega-caps score, so most rows
  leave it null rather than ship a coin-flip label.
