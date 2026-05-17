"""Evaluation harness for the FinSight multi-agent pipeline.

Runs a labeled dataset of queries through the full LangGraph pipeline and
scores outputs on citation faithfulness, factuality, and refusal correctness.

Entry point:
    python -m tests.evals.run_evals [--limit N] [--out path/]
"""
