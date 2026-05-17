"""Test the RAG pipeline end-to-end.

Usage:
    python -m scripts.test_rag
"""

from __future__ import annotations

import json
import logging

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


def main():
    from rag.chain import create_rag_chain

    chain = create_rag_chain()

    print(f"Vector store contains {chain._retriever._store.count()} vectors\n")

    ticker = "AAPL"
    question = "What are AAPL's main revenue risks?"

    print(f"Question: {question}")
    print(f"Ticker: {ticker}")
    print("=" * 60)
    print("Running RAG chain...\n")

    report = chain.invoke(ticker, question)

    print("=" * 60)
    print(f"TICKER: {report.ticker}")
    print(f"RISK SCORE: {report.risk_score}/100")
    print(f"RISK RATIONALE: {report.risk_rationale}")
    print(f"CONFIDENCE: {report.confidence}")
    print(f"\nSUMMARY:\n{report.summary}")

    if report.key_metrics:
        print(f"\nKEY METRICS:")
        for m in report.key_metrics:
            print(f"  - {m.name}: {m.value} ({m.trend}) — {m.context}")

    if report.citations:
        print(f"\nCITATIONS:")
        for c in report.citations:
            print(f"  [Source {c.source_index}] {c.doc_type}: {c.excerpt[:100]}")

    # Also dump the full JSON
    print(f"\n{'=' * 60}")
    print("FULL JSON OUTPUT:")
    print(json.dumps(report.model_dump(), indent=2))


if __name__ == "__main__":
    main()
