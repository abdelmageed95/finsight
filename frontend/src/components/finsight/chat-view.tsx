"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  BarChart3,
  FileText,
  MessageSquare,
  Plus,
  Send,
  Sparkles,
  X,
} from "lucide-react";
import { api } from "@/lib/api";
import { cn, formatRelativeTime } from "@/lib/utils";
import type { ConversationListItem } from "@/lib/schemas";
import { Button } from "@/components/ui/button";

interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  text: string;
  citations?: string[];
  confidence?: string;
  streaming?: boolean;
}

interface ChatViewProps {
  initialTicker?: string;
  initialQuestion?: string;
}

const SUGGESTED_QUESTIONS = [
  "What are the main risks?",
  "How is revenue trending?",
  "Summarize the latest 10-K",
  "What's the competitive moat?",
  "Key financial metrics?",
  "Any red flags in the filings?",
];

export function ChatView({ initialTicker, initialQuestion }: ChatViewProps) {
  const [ticker, setTicker] = useState(initialTicker || "");
  const [input, setInput] = useState(initialQuestion ?? "");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [busy, setBusy] = useState(false);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [autoLoaded, setAutoLoaded] = useState(false);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const qc = useQueryClient();

  const { data: conversations } = useQuery({
    queryKey: ["conversations"],
    queryFn: () => api.listConversations(),
  });

  // Auto-load conversation for initial ticker
  useEffect(() => {
    if (!initialTicker || autoLoaded) return;
    setAutoLoaded(true);
    (async () => {
      try {
        const conv = await api.getConversationByTicker(initialTicker);
        setConversationId(conv.id);
        if (conv.ticker) setTicker(conv.ticker);
        if (conv.turns.length > 0) {
          setMessages(
            conv.turns.map((t) => ({
              id: t.id,
              role: t.role,
              text: t.content,
            }))
          );
        }
      } catch (err) {
        console.error("Failed to auto-load conversation", err);
      }
    })();
  }, [initialTicker, autoLoaded]);

  // Auto-scroll on new messages / streaming tokens
  useEffect(() => {
    scrollRef.current?.scrollTo({
      top: scrollRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [messages]);

  // Auto-resize textarea
  const adjustTextarea = useCallback(() => {
    const ta = textareaRef.current;
    if (!ta) return;
    ta.style.height = "auto";
    ta.style.height = `${Math.min(ta.scrollHeight, 160)}px`;
  }, []);

  async function selectConversation(conv: ConversationListItem) {
    try {
      const full = await api.getConversation(conv.id);
      setConversationId(full.id);
      if (full.ticker) setTicker(full.ticker);
      setMessages(
        full.turns.map((t) => ({
          id: t.id,
          role: t.role,
          text: t.content,
        }))
      );
    } catch (err) {
      console.error("Failed to load conversation", err);
    }
  }

  async function send(overrideInput?: string) {
    const q = (overrideInput ?? input).trim();
    if (!q || busy || !ticker) return;

    const userMsg: ChatMessage = {
      id: crypto.randomUUID(),
      role: "user",
      text: q,
    };
    const asstId = crypto.randomUUID();
    const asstMsg: ChatMessage = {
      id: asstId,
      role: "assistant",
      text: "",
      streaming: true,
    };
    setMessages((m) => [...m, userMsg, asstMsg]);
    setInput("");
    setBusy(true);

    // Reset textarea height
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
    }

    try {
      // Find-or-create conversation
      let convId = conversationId;
      if (!convId) {
        const conv = await api.getConversationByTicker(ticker);
        convId = conv.id;
        setConversationId(convId);
      }

      // Stream the response
      await api.sendMessageStream(convId, q, {
        onToken(text: string) {
          setMessages((m) =>
            m.map((msg) =>
              msg.id === asstId
                ? { ...msg, text: msg.text + text }
                : msg
            )
          );
        },
        onDone(meta: { citations: string[]; confidence: string }) {
          setMessages((m) =>
            m.map((msg) =>
              msg.id === asstId
                ? { ...msg, streaming: false, citations: meta.citations, confidence: meta.confidence }
                : msg
            )
          );
        },
        onError(err: string) {
          setMessages((m) =>
            m.map((msg) =>
              msg.id === asstId
                ? { ...msg, text: `Sorry, something went wrong: ${err}`, streaming: false }
                : msg
            )
          );
        },
      });

      qc.invalidateQueries({ queryKey: ["conversations"] });
    } catch (err) {
      console.error("Chat error", err);
      setMessages((m) =>
        m.map((msg) =>
          msg.id === asstId
            ? { ...msg, text: "Sorry, something went wrong. Please try again.", streaming: false }
            : msg
        )
      );
    } finally {
      setBusy(false);
    }
  }

  function newChat() {
    setMessages([]);
    setConversationId(null);
    setTicker("");
    setAutoLoaded(false);
  }

  function handleTickerChange(newTicker: string) {
    const upper = newTicker.toUpperCase();
    if (upper !== ticker) {
      setTicker(upper);
      setMessages([]);
      setConversationId(null);
    } else {
      setTicker(upper);
    }
  }

  return (
    <div className="flex flex-1 overflow-hidden">
      {/* Sessions sidebar */}
      <aside className="hidden w-72 shrink-0 flex-col border-r border-[var(--color-border)] bg-[var(--color-surface)]/30 lg:flex">
        <div className="border-b border-[var(--color-border)] p-4">
          <Button
            variant="secondary"
            size="sm"
            className="w-full justify-start"
            onClick={newChat}
          >
            <Plus className="h-4 w-4" /> New chat
          </Button>
        </div>
        <div className="flex-1 overflow-y-auto p-3">
          {conversations && conversations.length > 0 && (
            <>
              <p className="mb-2 px-2 text-[10px] uppercase tracking-wider text-[var(--color-muted)]">
                Conversations
              </p>
              {conversations.map((c) => (
                <button
                  key={c.id}
                  type="button"
                  onClick={() => selectConversation(c)}
                  className={cn(
                    "mb-1 block w-full rounded-[var(--radius-md)] p-2 text-left transition-colors hover:bg-[var(--color-surface)]",
                    conversationId === c.id && "bg-[var(--color-surface)]"
                  )}
                >
                  <div className="flex items-baseline justify-between">
                    <span className="flex items-center gap-1 font-mono text-xs font-medium text-[var(--color-foreground)]">
                      <MessageSquare className="h-3 w-3 text-[var(--color-muted)]" />
                      {c.ticker ?? "—"}
                    </span>
                    <span className="text-[10px] text-[var(--color-muted)]">
                      {formatRelativeTime(c.updated_at)}
                    </span>
                  </div>
                  <p className="mt-0.5 line-clamp-2 text-xs text-[var(--color-muted-strong)]">
                    {c.title}
                  </p>
                </button>
              ))}
            </>
          )}

          {(!conversations || conversations.length === 0) && (
            <p className="px-2 text-xs text-[var(--color-muted)]">
              No conversations yet. Analyze a ticker first to start chatting.
            </p>
          )}
        </div>
      </aside>

      {/* Main chat */}
      <div className="flex flex-1 flex-col">
        <header className="flex items-center justify-between border-b border-[var(--color-border)] px-6 py-3">
          <div className="flex items-center gap-3">
            <Sparkles className="h-4 w-4 text-[var(--color-accent)]" />
            <h1 className="text-sm font-medium text-[var(--color-foreground)]">
              {ticker ? `${ticker} Research Chat` : "Research Chat"}
            </h1>
          </div>
          <div className="flex items-center gap-2">
            {ticker && (
              <Link
                href={`/workspace/${ticker}?tab=overview`}
                className="inline-flex items-center gap-1.5 rounded-full border border-[var(--color-border)] px-3 py-1 text-xs text-[var(--color-muted-strong)] transition-colors hover:border-[var(--color-accent)] hover:text-[var(--color-accent)]"
              >
                <BarChart3 className="h-3 w-3" />
                Overview
              </Link>
            )}
            {ticker && (
              <Link
                href={`/workspace/${ticker}?tab=research`}
                className="inline-flex items-center gap-1.5 rounded-full border border-[var(--color-border)] px-3 py-1 text-xs text-[var(--color-muted-strong)] transition-colors hover:border-[var(--color-accent)] hover:text-[var(--color-accent)]"
              >
                <FileText className="h-3 w-3" />
                Research
              </Link>
            )}
          </div>
        </header>

        <div
          ref={scrollRef}
          className="flex-1 overflow-y-auto px-6 py-6"
        >
          <div className="mx-auto w-full max-w-3xl space-y-6">
            {messages.length === 0 && (
              <EmptyState
                ticker={ticker}
                onSuggest={(q) => {
                  setInput(q);
                  send(q);
                }}
              />
            )}
            {messages.map((m) => (
              <MessageBubble key={m.id} m={m} />
            ))}
          </div>
        </div>

        {/* Composer */}
        <div className="border-t border-[var(--color-border)] bg-[var(--color-surface)]/30 px-6 py-3">
          <div className="mx-auto w-full max-w-3xl">
            <div className="mb-2 flex items-center gap-2">
              <span className="inline-flex items-center gap-2 rounded-full border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-1 text-xs">
                <span className="text-[var(--color-muted)]">Ticker:</span>
                <input
                  value={ticker}
                  onChange={(e) => handleTickerChange(e.target.value)}
                  className="w-16 bg-transparent font-mono font-medium tracking-wide outline-none"
                  maxLength={6}
                  placeholder="AAPL"
                />
                {ticker && (
                  <button
                    type="button"
                    onClick={() => handleTickerChange("")}
                    className="text-[var(--color-muted)] hover:text-[var(--color-foreground)]"
                    aria-label="Clear ticker"
                  >
                    <X className="h-3 w-3" />
                  </button>
                )}
              </span>
            </div>
            <form
              onSubmit={(e) => {
                e.preventDefault();
                send();
              }}
              className="flex items-end gap-2 rounded-[var(--radius-lg)] border border-[var(--color-border)] bg-[var(--color-surface)] p-2 focus-within:border-[var(--color-accent)] transition-colors"
            >
              <textarea
                ref={textareaRef}
                value={input}
                onChange={(e) => {
                  setInput(e.target.value);
                  adjustTextarea();
                }}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    send();
                  }
                }}
                placeholder={ticker ? `Ask about ${ticker}…` : "Set a ticker first…"}
                rows={1}
                className="max-h-40 flex-1 resize-none bg-transparent px-2 py-2 text-sm text-[var(--color-foreground)] placeholder:text-[var(--color-muted)] outline-none"
                disabled={busy || !ticker}
              />
              <Button
                type="submit"
                variant="primary"
                size="icon"
                disabled={busy || !input.trim() || !ticker}
              >
                <Send className="h-4 w-4" />
              </Button>
            </form>
            <p className="mt-1.5 text-center text-[10px] text-[var(--color-muted)]">
              Answers are based on SEC filings in the database. Always verify important decisions.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Empty state with suggested questions                                */
/* ------------------------------------------------------------------ */

function EmptyState({
  ticker,
  onSuggest,
}: {
  ticker: string;
  onSuggest: (q: string) => void;
}) {
  return (
    <div className="flex flex-col items-center justify-center py-16">
      <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-[var(--color-accent)]/10">
        <Sparkles className="h-6 w-6 text-[var(--color-accent)]" />
      </div>
      <h2 className="text-lg font-semibold text-[var(--color-foreground)]">
        {ticker ? `Ask anything about ${ticker}` : "Pick a ticker to start chatting"}
      </h2>
      <p className="mt-2 max-w-md text-center text-sm text-[var(--color-muted)]">
        {ticker
          ? "Get quick, focused answers grounded in SEC filings. Responses stream in real time."
          : "Type a ticker in the box below, or jump straight in with one of these:"}
      </p>
      {!ticker && (
        <div className="mt-6 flex flex-wrap justify-center gap-2">
          {[
            { t: "AAPL", n: "Apple" },
            { t: "NVDA", n: "NVIDIA" },
            { t: "TSLA", n: "Tesla" },
            { t: "MSFT", n: "Microsoft" },
            { t: "GOOGL", n: "Alphabet" },
          ].map((s) => (
            <Link
              key={s.t}
              href={`/workspace/${s.t}?tab=chat`}
              className="inline-flex items-center gap-2 rounded-full border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-1 text-xs text-[var(--color-muted-strong)] transition-colors hover:border-[var(--color-accent)] hover:text-[var(--color-accent)]"
            >
              <span className="font-mono font-semibold text-[var(--color-foreground)]">
                {s.t}
              </span>
              <span className="text-[var(--color-muted)]">·</span>
              <span>{s.n}</span>
            </Link>
          ))}
        </div>
      )}
      {ticker && (
        <div className="mt-6 grid grid-cols-2 gap-2 sm:grid-cols-3">
          {SUGGESTED_QUESTIONS.map((q) => (
            <button
              key={q}
              type="button"
              onClick={() => onSuggest(q)}
              className="rounded-[var(--radius-md)] border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-2 text-xs text-[var(--color-muted-strong)] transition-all hover:border-[var(--color-accent)] hover:text-[var(--color-accent)] hover:shadow-sm"
            >
              {q}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* Message bubble with markdown rendering                              */
/* ------------------------------------------------------------------ */

function MessageBubble({ m }: { m: ChatMessage }) {
  if (m.role === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[80%] rounded-2xl rounded-br-sm bg-[var(--color-accent)] px-4 py-2.5 text-sm text-white">
          {m.text}
        </div>
      </div>
    );
  }

  return (
    <div className="flex gap-3">
      <div className="mt-1 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-[var(--color-accent)]/10">
        <Sparkles className="h-3.5 w-3.5 text-[var(--color-accent)]" />
      </div>
      <div className="min-w-0 flex-1">
        {m.text ? (
          <div className="prose-chat text-sm leading-relaxed text-[var(--color-foreground)]">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{m.text}</ReactMarkdown>
          </div>
        ) : (
          <div className="flex items-center gap-2 text-sm text-[var(--color-muted)]">
            <span className="inline-flex gap-1">
              <span className="h-2 w-2 animate-bounce rounded-full bg-[var(--color-accent)]/60" style={{ animationDelay: "0ms" }} />
              <span className="h-2 w-2 animate-bounce rounded-full bg-[var(--color-accent)]/60" style={{ animationDelay: "150ms" }} />
              <span className="h-2 w-2 animate-bounce rounded-full bg-[var(--color-accent)]/60" style={{ animationDelay: "300ms" }} />
            </span>
            Searching filings…
          </div>
        )}

        {/* Streaming cursor */}
        {m.streaming && m.text && (
          <span className="inline-block h-4 w-0.5 animate-pulse bg-[var(--color-accent)]" />
        )}

        {/* Citations + confidence badge */}
        {!m.streaming && m.citations && m.citations.length > 0 && (
          <div className="mt-3 flex flex-wrap items-center gap-1.5">
            {m.confidence && (
              <span
                className={cn(
                  "rounded-full px-2 py-0.5 text-[10px] font-medium",
                  m.confidence === "high" && "bg-emerald-500/10 text-emerald-600",
                  m.confidence === "medium" && "bg-amber-500/10 text-amber-600",
                  m.confidence === "low" && "bg-red-500/10 text-red-600",
                )}
              >
                {m.confidence} confidence
              </span>
            )}
            {m.citations.map((c, i) => (
              <span
                key={i}
                className="rounded-full border border-[var(--color-border)] bg-[var(--color-surface)] px-2 py-0.5 font-mono text-[10px] text-[var(--color-muted-strong)]"
              >
                {c}
              </span>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
