import { z } from "zod";
import {
  analyzeCheckSchema,
  analyzeResponseSchema,
  chatMessageResponseSchema,
  conversationListSchema,
  conversationSchema,
  healthSchema,
  historySchema,
  reportResponseSchema,
  tickerHitListSchema,
  tickerResponseSchema,
  type AnalyzeCheck,
  type AnalyzeResponse,
  type ChatMessageResponse,
  type Conversation,
  type ConversationListItem,
  type Health,
  type HistoryItem,
  type ReportResponse,
  type TickerHit,
  type TickerResponse,
} from "./schemas";
import { clearAuth, getToken } from "./auth";

const AUTH_ENDPOINTS = ["/auth/login", "/auth/register", "/auth/google"];

function handleUnauthorized(path: string) {
  if (typeof window === "undefined") return;
  if (AUTH_ENDPOINTS.some((p) => path.startsWith(p))) return;
  clearAuth();
  if (window.location.pathname !== "/login") {
    window.location.href = "/login?reason=expired";
  }
}

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  status: number;
  body?: unknown;
  constructor(message: string, status: number, body?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }
}

// Auth response schema (not in schemas.ts since it's only used here)
const authResponseSchema = z.object({
  access_token: z.string(),
  token_type: z.literal("bearer"),
  user: z.object({
    id: z.string(),
    email: z.string(),
    name: z.string().nullable(),
  }),
});
export type AuthResponse = z.infer<typeof authResponseSchema>;

async function request<T>(
  path: string,
  init: RequestInit,
  schema: z.ZodType<T>
): Promise<T> {
  const url = `${API_BASE}${path}`;

  // Auto-attach token from localStorage
  const token = getToken();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...(init.headers as Record<string, string> ?? {}),
  };

  const res = await fetch(url, {
    ...init,
    headers,
    cache: "no-store",
  });
  const text = await res.text();
  const body = text ? safeJson(text) : null;
  if (!res.ok) {
    if (res.status === 401) handleUnauthorized(path);
    throw new ApiError(
      `API ${res.status} ${res.statusText} on ${path}`,
      res.status,
      body
    );
  }
  return schema.parse(body);
}

function safeJson(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

// ---------------------------------------------------------------------------
// Public API — one function per endpoint
// ---------------------------------------------------------------------------

export const api = {
  base: API_BASE,

  // Auth
  register(email: string, password: string, name?: string): Promise<AuthResponse> {
    return request(
      "/auth/register",
      { method: "POST", body: JSON.stringify({ email, password, name }) },
      authResponseSchema
    );
  },

  login(email: string, password: string): Promise<AuthResponse> {
    return request(
      "/auth/login",
      { method: "POST", body: JSON.stringify({ email, password }) },
      authResponseSchema
    );
  },

  googleAuth(idToken: string): Promise<AuthResponse> {
    return request(
      "/auth/google",
      { method: "POST", body: JSON.stringify({ id_token: idToken }) },
      authResponseSchema
    );
  },

  health(): Promise<Health> {
    return request("/health", { method: "GET" }, healthSchema);
  },

  analyze(ticker: string, question: string): Promise<AnalyzeResponse> {
    return request(
      "/analyze",
      { method: "POST", body: JSON.stringify({ ticker, question }) },
      analyzeResponseSchema
    );
  },

  report(jobId: string): Promise<ReportResponse> {
    return request(
      `/report/${encodeURIComponent(jobId)}`,
      { method: "GET" },
      reportResponseSchema
    );
  },

  searchTickers(q: string, limit = 8): Promise<TickerHit[]> {
    const params = new URLSearchParams({ q, limit: String(limit) });
    return request(`/search?${params.toString()}`, { method: "GET" }, tickerHitListSchema);
  },

  suggestTickers(symbol: string, limit = 5): Promise<TickerHit[]> {
    const params = new URLSearchParams({ limit: String(limit) });
    return request(
      `/search/suggest/${encodeURIComponent(symbol)}?${params.toString()}`,
      { method: "GET" },
      tickerHitListSchema,
    );
  },

  ticker(symbol: string, days = 180): Promise<TickerResponse> {
    const params = new URLSearchParams({ days: String(days) });
    return request(
      `/ticker/${encodeURIComponent(symbol)}?${params.toString()}`,
      { method: "GET" },
      tickerResponseSchema
    );
  },

  history(opts: { ticker?: string; limit?: number } = {}): Promise<HistoryItem[]> {
    const params = new URLSearchParams();
    if (opts.ticker) params.set("ticker", opts.ticker);
    if (opts.limit) params.set("limit", String(opts.limit));
    const qs = params.toString();
    return request(
      `/history${qs ? `?${qs}` : ""}`,
      { method: "GET" },
      historySchema
    );
  },

  // Ticker sub-endpoints (news, holders, earnings, dividends)
  news(ticker: string): Promise<unknown> {
    return request(`/ticker/${encodeURIComponent(ticker)}/news`, { method: "GET" }, z.any());
  },

  holders(ticker: string): Promise<unknown> {
    return request(`/ticker/${encodeURIComponent(ticker)}/holders`, { method: "GET" }, z.any());
  },

  earnings(ticker: string): Promise<unknown> {
    return request(`/ticker/${encodeURIComponent(ticker)}/earnings`, { method: "GET" }, z.any());
  },

  dividends(ticker: string): Promise<unknown> {
    return request(`/ticker/${encodeURIComponent(ticker)}/dividends`, { method: "GET" }, z.any());
  },

  // Conversations
  createConversation(opts: { title?: string; ticker?: string } = {}): Promise<Conversation> {
    return request(
      "/conversations",
      { method: "POST", body: JSON.stringify(opts) },
      conversationSchema
    );
  },

  listConversations(): Promise<ConversationListItem[]> {
    return request(
      "/conversations",
      { method: "GET" },
      conversationListSchema
    );
  },

  getConversation(id: string): Promise<Conversation> {
    return request(
      `/conversations/${encodeURIComponent(id)}`,
      { method: "GET" },
      conversationSchema
    );
  },

  getConversationByTicker(ticker: string): Promise<Conversation> {
    return request(
      `/conversations/by-ticker/${encodeURIComponent(ticker)}`,
      { method: "GET" },
      conversationSchema
    );
  },

  sendMessage(conversationId: string, question: string): Promise<ChatMessageResponse> {
    return request(
      `/conversations/${encodeURIComponent(conversationId)}/messages`,
      { method: "POST", body: JSON.stringify({ question }) },
      chatMessageResponseSchema
    );
  },

  /**
   * Stream a chat message via SSE. Calls onToken for each text chunk,
   * onDone when complete with citations/confidence.
   */
  async sendMessageStream(
    conversationId: string,
    question: string,
    callbacks: {
      onToken: (text: string) => void;
      onDone: (meta: { citations: string[]; confidence: string }) => void;
      onError?: (err: string) => void;
    },
  ): Promise<void> {
    const url = `${API_BASE}/conversations/${encodeURIComponent(conversationId)}/messages/stream`;
    const token = getToken();
    const res = await fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({ question }),
    });

    if (!res.ok) {
      if (res.status === 401) handleUnauthorized(`/conversations/${conversationId}/messages/stream`);
      throw new ApiError(`Stream ${res.status}`, res.status);
    }

    const reader = res.body?.getReader();
    if (!reader) throw new Error("No response body");

    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() ?? "";

      for (const line of lines) {
        if (!line.startsWith("data: ")) continue;
        try {
          const event = JSON.parse(line.slice(6));
          if (event.type === "token") {
            callbacks.onToken(event.data);
          } else if (event.type === "done") {
            callbacks.onDone(event.data);
          } else if (event.type === "error") {
            callbacks.onError?.(event.data);
          }
        } catch {
          // skip malformed SSE lines
        }
      }
    }
  },

  /**
   * Stream live progress for an in-flight analysis job. Calls callbacks
   * on each `progress` / `partial` / `done` / `error` event from the server.
   */
  async streamAnalyzeProgress(
    jobId: string,
    callbacks: {
      onProgress?: (e: { stage: string; message: string; percent: number }) => void;
      onPartial?: (e: { summary: string; risk_score?: number; confidence?: string }) => void;
      onDone?: (e: { report?: unknown }) => void;
      onError?: (msg: string) => void;
    },
    signal?: AbortSignal,
  ): Promise<void> {
    const url = `${API_BASE}/analyze/stream/${encodeURIComponent(jobId)}`;
    const token = getToken();
    const res = await fetch(url, {
      method: "GET",
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      signal,
    });
    if (!res.ok) {
      if (res.status === 401) handleUnauthorized(`/analyze/stream/${jobId}`);
      throw new ApiError(`Stream ${res.status}`, res.status);
    }
    const reader = res.body?.getReader();
    if (!reader) throw new Error("No response body");
    const decoder = new TextDecoder();
    let buffer = "";
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() ?? "";
      for (const line of lines) {
        if (!line.startsWith("data: ")) continue;
        try {
          const event = JSON.parse(line.slice(6));
          if (event.type === "progress") callbacks.onProgress?.(event);
          else if (event.type === "partial") callbacks.onPartial?.(event);
          else if (event.type === "done") callbacks.onDone?.(event);
          else if (event.type === "error") callbacks.onError?.(event.message);
        } catch {
          // ignore malformed SSE lines
        }
      }
    }
  },

  toggleStar(jobId: string): Promise<{ job_id: string; is_starred: boolean }> {
    return request(
      `/report/${encodeURIComponent(jobId)}/star`,
      { method: "POST" },
      z.object({ job_id: z.string(), is_starred: z.boolean() }),
    );
  },

  refreshTicker(ticker: string): Promise<unknown> {
    return request(
      `/ticker/${encodeURIComponent(ticker)}/refresh`,
      { method: "POST" },
      z.any()
    );
  },

  peers(ticker: string): Promise<unknown> {
    return request(
      `/ticker/${encodeURIComponent(ticker)}/peers`,
      { method: "GET" },
      z.any()
    );
  },

  compare(tickerA: string, tickerB: string): Promise<{ job_id: string; status: string }> {
    return request(
      "/analyze/compare",
      { method: "POST", body: JSON.stringify({ ticker_a: tickerA, ticker_b: tickerB }) },
      z.object({ job_id: z.string(), status: z.string() })
    );
  },

  comparisonReport(jobId: string): Promise<unknown> {
    return request(
      `/report/${encodeURIComponent(jobId)}/compare`,
      { method: "GET" },
      z.any()
    );
  },

  checkExisting(ticker: string): Promise<AnalyzeCheck> {
    return request(
      `/analyze/check/${encodeURIComponent(ticker)}`,
      { method: "GET" },
      analyzeCheckSchema
    );
  },
};
