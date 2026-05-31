"""LangGraph orchestrator — StateGraph wiring + supervisor node.

This module defines the shared graph state and builds the multi-agent
StateGraph that routes requests through the supervisor → data_agent →
rag_agent → report_agent pipeline.

Usage:
    from agents.orchestrator import build_graph

    graph = build_graph()
    result = graph.invoke({
        "ticker": "AAPL",
        "question": "What are AAPL's main revenue risks?",
        "messages": [],
    })
    print(result["final_report"])
"""

from __future__ import annotations

import logging
import operator
import os
from datetime import datetime
from typing import Annotated, Any, Literal

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage
from langchain_anthropic import ChatAnthropic
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.types import Command
from pydantic import BaseModel, Field
from typing_extensions import TypedDict

from agents.data_agent import data_agent_node
from agents.rag_agent import rag_agent_node
from agents.report_agent import report_agent_node

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Custom reducers
# ---------------------------------------------------------------------------

def merge_dicts(left: dict, right: dict) -> dict:
    """Reducer that merges dicts (right keys win) instead of overwriting."""
    merged = left.copy()
    merged.update(right)
    return merged


def extend_list(left: list, right: list) -> list:
    """Reducer that extends a list instead of overwriting."""
    return left + right


# ---------------------------------------------------------------------------
# 1. Graph State
# ---------------------------------------------------------------------------

class GraphState(TypedDict, total=False):
    """Shared state flowing through all nodes in the graph.

    - messages:       Conversation history (appended via add_messages reducer).
    - ticker:         Stock ticker symbol to analyse (e.g. "AAPL").
    - question:       The user's natural-language question.
    - intent:         Classified intent of the user message (set by supervisor).
    - prior_turns:    Previous conversation turns for multi-turn context.
    - financial_context: Structured multi-year financials block (set by the
                      data agent, read by the RAG agent).
    - retrieved_docs: Document chunks retrieved by the RAG agent (appended).
    - tool_results:   Results from each agent, keyed by agent name (merged).
    - final_report:   The completed research report (merged).
    """

    messages: Annotated[list[AnyMessage], add_messages]
    ticker: str
    question: str
    intent: str
    job_id: str
    prior_turns: list[dict]
    financial_context: str
    retrieved_docs: Annotated[list[dict], extend_list]
    tool_results: Annotated[dict[str, Any], merge_dicts]
    final_report: Annotated[dict[str, Any], merge_dicts]


# ---------------------------------------------------------------------------
# 2. Supervisor — intent classification + routing
# ---------------------------------------------------------------------------

class IntentClassification(BaseModel):
    """Structured output of the supervisor's intent classifier."""

    intent: Literal["greeting", "smalltalk", "research_query"] = Field(
        description=(
            "greeting — user said hi/hello/thanks with no question; "
            "smalltalk — chitchat or meta question about the assistant itself; "
            "research_query — user is asking something substantive about a company, "
            "stock, filings, financials, or markets."
        )
    )
    reasoning: str = Field(description="Brief explanation of the classification.")


INTENT_SYSTEM_PROMPT = """\
You are the router for a financial research assistant. Classify the user's latest
message into one of three intents:

- greeting: "hi", "hello", "thanks", "bye", "how are you" — no real question.
- smalltalk: chitchat, jokes, meta questions about you ("what can you do?", "who
  made you?"). Still no substantive research question.
- research_query: the user wants information about a company, ticker, stock,
  filings, earnings, risks, fundamentals, news, or the market. Even a short
  message like "AAPL risks?" or "how is Tesla doing" counts as research_query.

When in doubt between smalltalk and research_query, pick research_query only if
there is a clear company/ticker/finance topic. Otherwise pick smalltalk.
"""


# Cheap fast-path heuristic: very short messages that are obviously greetings
# don't need an LLM call. This catches the most common case ("hi", "hey", "hello")
# in microseconds with zero API cost.
_GREETING_WORDS = {
    "hi", "hey", "hello", "yo", "sup", "hiya", "howdy",
    "thanks", "thank", "thx", "ty", "bye", "goodbye", "cya",
}


def _fast_greeting_check(text: str) -> bool:
    """Return True if the message is unambiguously a short greeting."""
    tokens = [t.strip(".,!?;:") for t in text.lower().split()]
    tokens = [t for t in tokens if t]
    if not tokens or len(tokens) > 4:
        return False
    return all(t in _GREETING_WORDS or t in {"you", "there", "finsight"} for t in tokens)


def _classify_intent(question: str) -> str:
    """Classify the user message using a cheap LLM call with structured output."""
    if _fast_greeting_check(question):
        return "greeting"

    try:
        llm = ChatAnthropic(
            model="claude-haiku-4-5-20251001",
            temperature=0,
            max_tokens=512,
            api_key=os.getenv("CLAUDE_API_KEY") or os.getenv("ANTHROPIC_API_KEY"),
        )
        classifier = llm.with_structured_output(IntentClassification)
        result = classifier.invoke([
            SystemMessage(content=INTENT_SYSTEM_PROMPT),
            HumanMessage(content=question),
        ])
        logger.info("Intent classifier: %s (%s)", result.intent, result.reasoning)
        return result.intent
    except Exception:
        # If classification fails, default to research_query — safer to run the
        # pipeline and give a real answer than to brush off a real question.
        logger.exception("Intent classification failed, defaulting to research_query")
        return "research_query"


def supervisor_node(state: GraphState) -> Command[Literal["data_agent", "rag_agent", "report_agent", "smalltalk_agent", "__end__"]]:
    """Supervisor examines state and routes to the next agent.

    On first entry (no tool_results yet), classifies intent and routes either to
    the smalltalk branch or the full research pipeline. On subsequent entries,
    advances the research pipeline deterministically.
    """
    tool_results = state.get("tool_results", {})
    final_report = state.get("final_report", {})
    intent = state.get("intent")

    # First entry — classify intent before doing anything else.
    if not tool_results and not intent:
        question = state.get("question", "") or ""
        intent = _classify_intent(question)

        if intent in ("greeting", "smalltalk"):
            logger.info("Supervisor routing to smalltalk_agent (intent=%s)", intent)
            return Command(
                goto="smalltalk_agent",
                update={
                    "intent": intent,
                    "messages": [AIMessage(
                        content=f"Supervisor → smalltalk_agent (intent={intent})",
                        name="supervisor",
                    )],
                },
            )

        # Fall through to the research pipeline with intent persisted.
        return Command(
            goto="data_agent",
            update={
                "intent": intent,
                "messages": [AIMessage(
                    content=f"Supervisor → data_agent (intent={intent})",
                    name="supervisor",
                )],
            },
        )

    # Subsequent entries — deterministic pipeline advancement.
    if "data_agent" not in tool_results:
        next_agent = "data_agent"
        reasoning = "No data fetched yet — starting with data ingestion."
    elif "rag_agent" not in tool_results:
        next_agent = "rag_agent"
        reasoning = "Data fetched — proceeding to RAG analysis."
    elif not final_report:
        next_agent = "report_agent"
        reasoning = "RAG analysis complete — generating final report."
    else:
        logger.info("Supervisor: all agents completed, finishing.")
        return Command(goto="__end__")

    logger.info("Supervisor routing to %s: %s", next_agent, reasoning)

    return Command(
        goto=next_agent,
        update={
            "messages": [AIMessage(
                content=f"Supervisor → {next_agent}: {reasoning}",
                name="supervisor",
            )],
        },
    )


# ---------------------------------------------------------------------------
# 2b. Smalltalk agent — handles greetings and meta questions
# ---------------------------------------------------------------------------

SMALLTALK_SYSTEM_PROMPT = """\
You are FinSight, an AI-powered financial research assistant. You analyse SEC
filings (10-K, 10-Q), market data, and financials to produce risk-scored research
reports with citations.

The user has greeted you or asked a meta question. Reply in 1–3 friendly sentences.
If appropriate, briefly tell them what you can do: "Ask me about any public company
— I'll pull recent filings and market data and give you a cited research summary."
Do NOT fabricate financial data. Do NOT invent risk scores. Just answer the
conversation, naturally.
"""


def smalltalk_agent_node(state: GraphState) -> Command[Literal["__end__"]]:
    """Generate a short conversational reply for greetings/smalltalk and end.

    Slots the reply into `final_report.summary` so the existing frontend polling
    code displays it without any special-casing.
    """
    question = state.get("question", "") or ""
    ticker = state.get("ticker", "")
    logger.info("Smalltalk agent: replying to %r", question[:80])

    try:
        llm = ChatAnthropic(
            model="claude-haiku-4-5-20251001",
            temperature=0.7,
            max_tokens=512,
            api_key=os.getenv("CLAUDE_API_KEY") or os.getenv("ANTHROPIC_API_KEY"),
        )
        response = llm.invoke([
            SystemMessage(content=SMALLTALK_SYSTEM_PROMPT),
            HumanMessage(content=question),
        ])
        reply = response.content.strip() if hasattr(response, "content") else str(response)
    except Exception as e:
        logger.exception("Smalltalk generation failed")
        reply = "Hi! I'm FinSight. Ask me about any public company and I'll pull recent filings and market data to produce a cited research summary."

    final_report = {
        "ticker": ticker,
        "question": question,
        "status": "completed",
        "generated_at": datetime.utcnow().isoformat(),
        "summary": reply,
        "risk_score": None,
        "risk_rationale": None,
        "risk_level": None,
        "confidence": None,
        "key_metrics": [],
        "citations": [],
        "intent": state.get("intent", "smalltalk"),
    }

    return Command(
        goto="__end__",
        update={
            "messages": [AIMessage(content=reply, name="smalltalk_agent")],
            "final_report": final_report,
        },
    )


# ---------------------------------------------------------------------------
# 3. Build the graph
# ---------------------------------------------------------------------------

def build_graph(checkpointer=None) -> StateGraph:
    """Build and compile the FinSight multi-agent StateGraph.

    Args:
        checkpointer: LangGraph checkpointer for persistence.
                      Defaults to InMemorySaver for local development.

    Returns:
        Compiled StateGraph ready to invoke.
    """
    builder = StateGraph(GraphState)

    # Register nodes
    builder.add_node("supervisor", supervisor_node)
    builder.add_node("smalltalk_agent", smalltalk_agent_node)
    builder.add_node("data_agent", data_agent_node)
    builder.add_node("rag_agent", rag_agent_node)
    builder.add_node("report_agent", report_agent_node)

    # Entry point: always start with the supervisor
    builder.add_edge(START, "supervisor")

    # Compile with checkpointing
    if checkpointer is None:
        checkpointer = InMemorySaver()

    graph = builder.compile(checkpointer=checkpointer)

    logger.info("FinSight graph compiled with %d nodes", len(builder.nodes))
    return graph


def run_analysis(ticker: str, question: str, thread_id: str = "default") -> dict:
    """Convenience function to run the full analysis pipeline.

    Args:
        ticker: Stock ticker symbol (e.g. "AAPL").
        question: The user's question.
        thread_id: Thread ID for checkpointing.

    Returns:
        The final_report dict from the graph state.
    """
    graph = build_graph()

    config = {"configurable": {"thread_id": thread_id}}

    initial_state = {
        "messages": [HumanMessage(content=f"[{ticker}] {question}")],
        "ticker": ticker.upper(),
        "question": question,
        "retrieved_docs": [],
        "tool_results": {},
        "final_report": {},
    }

    result = graph.invoke(initial_state, config)
    return result.get("final_report", {})
