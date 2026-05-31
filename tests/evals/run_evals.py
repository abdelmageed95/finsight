"""CLI runner for the FinSight evaluation harness.

Usage:
    python -m tests.evals.run_evals
    python -m tests.evals.run_evals --limit 3
    python -m tests.evals.run_evals --no-llm-judge
    python -m tests.evals.run_evals --dataset tests/evals/dataset.jsonl --out evals/results
    python -m tests.evals.run_evals --mlflow          # also log to MLflow

What it does:
    1. Loads dataset.jsonl
    2. For each row, invokes the LangGraph pipeline via run_analysis()
    3. Runs scorers (faithfulness, factuality, doc-type, refusal, risk-band)
    4. Writes JSON + Markdown summary to evals/results/<timestamp>/
    5. Prints aggregate scores + p50/p95 latency to stdout
    6. With --mlflow: logs params, metrics and artifacts to MLflow

Notes:
    - Each row triggers real API calls (LLM, yfinance, SEC). Use --limit N
      while iterating.
    - LLM-judge responses are cached in tests/evals/.judge_cache.json so
      re-runs are nearly free.
    - Set FINSIGHT_EVAL_THREAD_PREFIX to namespace the LangGraph thread_ids
      if running multiple evals in parallel against the same DB.
    - --mlflow tracking is local/file-based (./mlruns) by default; set the
      MLFLOW_TRACKING_URI env var to log to a server instead. View with
      `mlflow ui`.
"""

from __future__ import annotations

import argparse
import json
import logging
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Make the repo root importable when running as a script.
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

# Load .env so OPENAI_API_KEY / CLAUDE_API_KEY are available before the
# orchestrator builds its LLM clients.
try:
    from dotenv import load_dotenv  # type: ignore

    load_dotenv(REPO_ROOT / ".env")
except ImportError:
    pass

from tests.evals.scorers import (  # noqa: E402
    score_citation_doctypes,
    score_factuality,
    score_faithfulness,
    score_refusal_correctness,
    score_risk_band,
)

logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


# Dataset loading
def load_dataset(path: Path) -> list[dict]:
    rows = []
    with path.open() as f:
        for i, line in enumerate(f, start=1):
            line = line.strip()
            if not line or line.startswith("//"):
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as e:
                raise ValueError(f"{path}:{i}: invalid JSON — {e}") from e
    return rows


# Pipeline invocation
def run_one(row: dict, thread_prefix: str) -> tuple[dict, list[dict], float]:
    """Invoke the pipeline once and return (final_report, retrieved_docs, latency_s)."""
    from agents.orchestrator import build_graph
    from langchain_core.messages import HumanMessage

    graph = build_graph()
    thread_id = f"{thread_prefix}-{row['id']}"
    config = {"configurable": {"thread_id": thread_id}}

    initial_state = {
        "messages": [HumanMessage(content=f"[{row['ticker']}] {row['query']}")],
        "ticker": row["ticker"].upper(),
        "question": row["query"],
        "retrieved_docs": [],
        "tool_results": {},
        "final_report": {},
    }

    t0 = time.perf_counter()
    result = graph.invoke(initial_state, config)
    latency = time.perf_counter() - t0

    # The research path's `final_report` doesn't carry `intent` through —
    # only the smalltalk node populates it. Merge from state so refusal
    # scoring works for both branches.
    final_report = (result.get("final_report") or {}).copy()
    if "intent" not in final_report and result.get("intent"):
        final_report["intent"] = result["intent"]

    # Faithfulness checks citations against the sources the LLM actually saw.
    # The structured financial-history block is one of those sources, so
    # append it to the pool — otherwise a citation grounded in the financials
    # table is wrongly scored UNSUPPORTED.
    retrieved_docs = list(result.get("retrieved_docs", []) or [])
    financial_context = result.get("financial_context") or ""
    if financial_context:
        retrieved_docs.append({"doc_type": "financials", "text": financial_context})

    return (final_report, retrieved_docs, latency)


# Per-row scoring

def score_row(row: dict, report: dict, retrieved_docs: list[dict], use_llm_judge: bool) -> dict:
    return {
        "faithfulness": score_faithfulness(report, retrieved_docs, use_llm=use_llm_judge),
        "factuality": score_factuality(report, row.get("must_contain") or []),
        "citation_doctypes": score_citation_doctypes(report, row.get("must_cite_doc_types") or []),
        "refusal": score_refusal_correctness(
            report,
            expected_intent=row.get("expected_intent"),
            is_refusal=bool(row.get("is_refusal")),
        ),
        "risk_band": score_risk_band(report, row.get("expected_risk_band")),
    }


# Aggregation

def aggregate(per_row_scores: list[dict]) -> dict:
    """Compute mean of each scorer + p50/p95 latency across all rows."""
    def mean_of(key: str) -> float | None:
        vals = []
        for r in per_row_scores:
            section = (r.get("scores") or {}).get(key)
            if not section:
                continue
            v = section.get("score")
            if v is None:
                continue
            vals.append(v)
        return round(statistics.mean(vals), 3) if vals else None

    latencies = [r["latency_s"] for r in per_row_scores if r.get("latency_s") is not None]
    latencies.sort()

    def pct(p: float) -> float | None:
        if not latencies:
            return None
        idx = max(0, min(len(latencies) - 1, int(round(p / 100 * (len(latencies) - 1)))))
        return round(latencies[idx], 2)

    return {
        "n_rows": len(per_row_scores),
        "mean_faithfulness": mean_of("faithfulness"),
        "mean_factuality": mean_of("factuality"),
        "mean_citation_doctypes": mean_of("citation_doctypes"),
        "mean_refusal_correctness": mean_of("refusal"),
        "mean_risk_band": mean_of("risk_band"),
        "p50_latency_s": pct(50),
        "p95_latency_s": pct(95),
        "mean_latency_s": round(statistics.mean(latencies), 2) if latencies else None,
    }


# Output writers

def write_results(out_dir: Path, per_row_scores: list[dict], summary: dict, meta: dict) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "results.json").write_text(json.dumps({
        "meta": meta,
        "summary": summary,
        "rows": per_row_scores,
    }, indent=2, default=str))

    from tests.evals.report import render_markdown
    (out_dir / "results.md").write_text(render_markdown(summary, per_row_scores, meta))


def log_to_mlflow(summary: dict, meta: dict, per_row_scores: list[dict], out_dir: Path) -> None:
    """Log this eval run to MLflow — run config as params, aggregate scores as
    metrics, and the full results files as artifacts.

    Tracking is local/file-based (./mlruns) unless MLFLOW_TRACKING_URI is set.
    Only called when --mlflow is passed; a missing mlflow install is a soft
    skip so the core harness never depends on it.
    """
    try:
        import mlflow
    except ImportError:
        print(
            "  --mlflow was set but mlflow is not installed "
            "(`pip install mlflow`). Skipping MLflow logging.",
            file=sys.stderr,
        )
        return

    mlflow.set_experiment("finsight-evals")
    with mlflow.start_run(run_name=meta["timestamp"]):
        # Params — how the run was configured (str/num/bool only).
        mlflow.log_params({
            "dataset": meta["dataset"],
            "n_rows": meta["n_rows"],
            "use_llm_judge": meta["use_llm_judge"],
            "thread_prefix": meta["thread_prefix"],
        })
        # Metrics — aggregate scores + latency. MLflow rejects None, so a
        # scorer that was skipped for every row (e.g. all risk bands null)
        # is simply omitted.
        metrics = {k: v for k, v in summary.items() if isinstance(v, (int, float))}
        metrics["n_errors"] = sum(1 for r in per_row_scores if r.get("error"))
        mlflow.log_metrics(metrics)
        # Artifacts — the timestamped results.json + results.md.
        mlflow.log_artifacts(str(out_dir))

    print("  Logged run to MLflow experiment 'finsight-evals'. View with: mlflow ui")


def _fmt_opt(v: Any, suffix: str = "") -> str:
    return f"{v}{suffix}" if v is not None else "—"


def print_summary(summary: dict, meta: dict, per_row_scores: list[dict]) -> None:
    print()
    print("=" * 72)
    print(f"FinSight evals — {meta['timestamp']}  (n={summary['n_rows']})")
    print("=" * 72)
    rows = [
        ("Faithfulness (citations)", summary["mean_faithfulness"]),
        ("Factuality (must_contain)", summary["mean_factuality"]),
        ("Doc-type coverage", summary["mean_citation_doctypes"]),
        ("Refusal correctness", summary["mean_refusal_correctness"]),
        ("Risk-band correctness", summary["mean_risk_band"]),
    ]
    for name, val in rows:
        bar = ""
        if val is not None:
            n = int(round(val * 20))
            bar = "█" * n + "░" * (20 - n)
        print(f"  {name:<28} {bar}  {_fmt_opt(val)}")
    print()
    print(
        "  Latency  "
        f"p50={_fmt_opt(summary['p50_latency_s'], 's')}  "
        f"p95={_fmt_opt(summary['p95_latency_s'], 's')}  "
        f"mean={_fmt_opt(summary['mean_latency_s'], 's')}"
    )

    errors = [r for r in per_row_scores if r.get("error")]
    if errors:
        print()
        print(f"  ERRORS ({len(errors)}/{len(per_row_scores)} rows failed):")
        for r in errors:
            print(f"    - {r['id']}: {r['error']}")
    print("=" * 72)
    print()


# Main

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run FinSight evaluation harness.")
    parser.add_argument(
        "--dataset",
        default=str(Path(__file__).parent / "dataset.jsonl"),
        help="Path to JSONL dataset.",
    )
    parser.add_argument(
        "--out",
        default=str(REPO_ROOT / "evals" / "results"),
        help="Output directory (a timestamped subdir will be created).",
    )
    parser.add_argument("--limit", type=int, default=None, help="Run only the first N rows.")
    parser.add_argument(
        "--no-llm-judge",
        action="store_true",
        help="Skip the LLM judge for faithfulness; rely only on substring matching.",
    )
    parser.add_argument(
        "--thread-prefix",
        default="eval",
        help="Prefix for LangGraph thread_id (helps namespace concurrent runs).",
    )
    parser.add_argument(
        "--ids",
        default=None,
        help="Comma-separated list of row ids to run (overrides --limit).",
    )
    parser.add_argument(
        "--mlflow",
        action="store_true",
        help="Also log this run (params, metrics, artifacts) to MLflow. Off by default.",
    )
    parser.add_argument(
        "--row-delay",
        type=float,
        default=0.0,
        help="Seconds to pause between rows. Use it to stay under a low "
             "per-minute API rate limit (e.g. --row-delay 60).",
    )
    args = parser.parse_args(argv)

    dataset_path = Path(args.dataset)
    rows = load_dataset(dataset_path)

    if args.ids:
        wanted = set(s.strip() for s in args.ids.split(",") if s.strip())
        rows = [r for r in rows if r["id"] in wanted]
    elif args.limit is not None:
        rows = rows[: args.limit]

    if not rows:
        print("No rows to run.", file=sys.stderr)
        return 2

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = Path(args.out) / timestamp

    meta = {
        "timestamp": timestamp,
        "dataset": str(dataset_path),
        "n_rows": len(rows),
        "use_llm_judge": not args.no_llm_judge,
        "thread_prefix": args.thread_prefix,
    }

    print(f"Running {len(rows)} rows from {dataset_path.name} → {out_dir}")
    per_row_scores = []
    for i, row in enumerate(rows, start=1):
        print(f"[{i}/{len(rows)}] {row['id']}  {row['ticker']}  {row['query'][:60]!r}")
        try:
            report, retrieved_docs, latency = run_one(row, args.thread_prefix)
            scores = score_row(row, report, retrieved_docs, use_llm_judge=not args.no_llm_judge)
            err = None
        except Exception as e:
            logger.exception("Row %s failed", row["id"])
            report, retrieved_docs, latency = {}, [], None
            scores = {}
            err = f"{type(e).__name__}: {e}"

        per_row_scores.append({
            "id": row["id"],
            "ticker": row["ticker"],
            "query": row["query"],
            "latency_s": round(latency, 2) if latency is not None else None,
            "report": _slim_report(report),
            "n_retrieved_docs": len(retrieved_docs),
            "scores": scores,
            "error": err,
        })

        # Pace rows to stay under a low per-minute API rate limit.
        if args.row_delay and i < len(rows):
            time.sleep(args.row_delay)

    summary = aggregate(per_row_scores)
    write_results(out_dir, per_row_scores, summary, meta)
    print_summary(summary, meta, per_row_scores)
    print(f"Results: {out_dir}/results.json")
    print(f"         {out_dir}/results.md")

    if args.mlflow:
        log_to_mlflow(summary, meta, per_row_scores, out_dir)

    return 0


def _slim_report(report: dict[str, Any]) -> dict[str, Any]:
    """Pick a small subset of the report for the JSON log (full dumps balloon size)."""
    if not report:
        return {}
    return {
        "intent": report.get("intent"),
        "summary": (report.get("summary") or "")[:500],
        "executive_summary": (report.get("executive_summary") or "")[:300],
        "risk_score": report.get("risk_score"),
        "risk_level": report.get("risk_level"),
        "n_citations": len(report.get("citations") or []),
        "n_key_metrics": len(report.get("key_metrics") or []),
    }


if __name__ == "__main__":
    sys.exit(main())
