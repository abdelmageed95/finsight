"""Markdown rendering for eval results."""

from __future__ import annotations

from typing import Any


def _fmt(v: Any) -> str:
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:.3f}"
    return str(v)


def render_markdown(summary: dict, rows: list[dict], meta: dict) -> str:
    lines: list[str] = []
    lines.append(f"# FinSight eval results — {meta['timestamp']}")
    lines.append("")
    lines.append(f"- Dataset: `{meta['dataset']}`")
    lines.append(f"- Rows: **{meta['n_rows']}**")
    lines.append(f"- LLM judge: {'enabled' if meta['use_llm_judge'] else 'disabled'}")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append("| Metric | Score |")
    lines.append("|---|---:|")
    lines.append(f"| Faithfulness (citations supported)   | {_fmt(summary['mean_faithfulness'])} |")
    lines.append(f"| Factuality (must_contain match rate) | {_fmt(summary['mean_factuality'])} |")
    lines.append(f"| Doc-type coverage                    | {_fmt(summary['mean_citation_doctypes'])} |")
    lines.append(f"| Refusal correctness                  | {_fmt(summary['mean_refusal_correctness'])} |")
    lines.append(f"| Risk-band correctness                | {_fmt(summary['mean_risk_band'])} |")
    lines.append(f"| Latency p50                          | {_fmt(summary['p50_latency_s'])}s |")
    lines.append(f"| Latency p95                          | {_fmt(summary['p95_latency_s'])}s |")
    lines.append(f"| Latency mean                         | {_fmt(summary['mean_latency_s'])}s |")
    lines.append("")

    lines.append("## Per-row")
    lines.append("")
    lines.append("| id | ticker | latency | faithfulness | factuality | doc-types | refusal | risk-band | error |")
    lines.append("|---|---|---:|---:|---:|---:|---:|---:|---|")
    for r in rows:
        s = r.get("scores") or {}

        def _g(key: str) -> str:
            section = s.get(key)
            if not section:
                return "—"
            return _fmt(section.get("score"))

        lines.append(
            "| {id} | {ticker} | {lat}s | {f} | {fa} | {dt} | {rf} | {rb} | {err} |".format(
                id=r["id"],
                ticker=r["ticker"],
                lat=_fmt(r.get("latency_s")),
                f=_g("faithfulness"),
                fa=_g("factuality"),
                dt=_g("citation_doctypes"),
                rf=_g("refusal"),
                rb=_g("risk_band"),
                err=(r.get("error") or "").replace("|", "\\|")[:60] or "—",
            )
        )
    lines.append("")

    # Failure detail section: anything < 1.0 on any scorer
    lines.append("## Notable failures")
    lines.append("")
    any_failures = False
    for r in rows:
        s = r.get("scores") or {}
        bad = []
        for name in ("faithfulness", "factuality", "citation_doctypes", "refusal", "risk_band"):
            section = s.get(name)
            if not section:
                continue
            score = section.get("score")
            if score is not None and score < 1.0:
                bad.append((name, section))
        if not bad and not r.get("error"):
            continue
        any_failures = True
        lines.append(f"### `{r['id']}` — {r['ticker']}: {r['query']!r}")
        lines.append("")
        if r.get("error"):
            lines.append(f"- **error**: `{r['error']}`")
        for name, section in bad:
            lines.append(f"- **{name}**: {_fmt(section.get('score'))}  ·  `{section}`")
        lines.append("")
    if not any_failures:
        lines.append("_None — all rows scored 1.0 across the board._")
        lines.append("")

    return "\n".join(lines)
