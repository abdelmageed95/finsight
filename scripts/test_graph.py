"""Test the full LangGraph multi-agent pipeline.

Usage:
    python -m scripts.test_graph MSFT "Is MSFT a good long-term investment?"
    python -m scripts.test_graph AAPL "What are AAPL's main revenue risks?"
"""

from __future__ import annotations

import json
import logging
import sys

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


def main(ticker: str, question: str):
    from agents.orchestrator import build_graph
    from langchain_core.messages import HumanMessage

    print(f"Building FinSight graph...")
    graph = build_graph()

    print(f"\nTicker:   {ticker}")
    print(f"Question: {question}")
    print("=" * 60)
    print("Running full agent pipeline...\n")

    config = {"configurable": {"thread_id": f"test-{ticker}"}}

    initial_state = {
        "messages": [HumanMessage(content=f"[{ticker}] {question}")],
        "ticker": ticker.upper(),
        "question": question,
        "retrieved_docs": [],
        "tool_results": {},
        "final_report": {},
    }

    # Stream updates to see progress
    for event in graph.stream(initial_state, config, stream_mode="updates"):
        for node_name, update in event.items():
            if "messages" in update and update["messages"]:
                last_msg = update["messages"][-1]
                name = getattr(last_msg, "name", "unknown")
                content = last_msg.content[:200] if hasattr(last_msg, "content") else str(last_msg)[:200]
                print(f"  [{name}] {content}")
                print()

    # Get final state
    final_state = graph.get_state(config)
    final_report = final_state.values.get("final_report", {})

    if final_report:
        print("\n" + "=" * 60)
        print("FINAL REPORT:")
        print("=" * 60)
        print(json.dumps(final_report, indent=2, default=str))
    else:
        print("\nNo final report generated.")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print('Usage: python -m scripts.test_graph TICKER "question"')
        print('Example: python -m scripts.test_graph AAPL "What are the main risks?"')
        sys.exit(1)

    main(sys.argv[1], " ".join(sys.argv[2:]))
