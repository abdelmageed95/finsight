import { z } from "zod";

// Mirror api/schemas.py — keep field names in sync with FastAPI.

export const healthSchema = z.object({
  status: z.enum(["ok", "degraded"]),
  db: z.string(),
  redis: z.string(),
  chroma: z.string(),
});
export type Health = z.infer<typeof healthSchema>;

export const tokenResponseSchema = z.object({
  access_token: z.string(),
  token_type: z.literal("bearer"),
});
export type TokenResponse = z.infer<typeof tokenResponseSchema>;

export const analyzeResponseSchema = z.object({
  job_id: z.string(),
  status: z.string(),
  message: z.string().optional(),
});
export type AnalyzeResponse = z.infer<typeof analyzeResponseSchema>;

export const reportStatusSchema = z.enum([
  "pending",
  "running",
  "completed",
  "failed",
  "overwritten",
]);
export type ReportStatus = z.infer<typeof reportStatusSchema>;

export const riskCategorySchema = z.object({
  category: z.string(),
  score: z.number(),
  rationale: z.string(),
});
export type RiskCategory = z.infer<typeof riskCategorySchema>;

export const reportResponseSchema = z.object({
  job_id: z.string(),
  status: reportStatusSchema,
  ticker: z.string().nullable().optional(),
  question: z.string().nullable().optional(),
  summary: z.string().nullable().optional(),
  risk_score: z.number().nullable().optional(),
  risk_level: z.string().nullable().optional(),
  risk_rationale: z.string().nullable().optional(),
  risk_breakdown: z.array(riskCategorySchema).nullable().optional(),
  executive_summary: z.string().nullable().optional(),
  swot: z.object({
    strengths: z.array(z.string()).default([]),
    weaknesses: z.array(z.string()).default([]),
    opportunities: z.array(z.string()).default([]),
    threats: z.array(z.string()).default([]),
  }).nullable().optional(),
  bull_case: z.string().nullable().optional(),
  bear_case: z.string().nullable().optional(),
  catalysts: z.array(z.object({
    event: z.string(),
    expected_timing: z.string(),
    impact: z.string(),
    rationale: z.string(),
  })).nullable().optional(),
  competitive_moat: z.string().nullable().optional(),
  moat_rating: z.string().nullable().optional(),
  revenue_segments: z.array(z.object({
    name: z.string(),
    value: z.string(),
    percentage: z.number().nullable(),
    trend: z.string().optional(),
  })).nullable().optional(),
  management_assessment: z.string().nullable().optional(),
  valuation_verdict: z.string().nullable().optional(),
  valuation_rating: z.string().nullable().optional(),
  confidence: z.string().nullable().optional(),
  key_metrics: z.array(z.record(z.string(), z.any())).nullable().optional(),
  citations: z
    .array(
      z
        .object({
          source_index: z.number().nullable().optional(),
          doc_type: z.string().nullable().optional(),
          excerpt: z.string().nullable().optional(),
        })
        .passthrough(),
    )
    .nullable()
    .optional(),
  generated_at: z.string().nullable().optional(),
  is_starred: z.boolean().optional().default(false),
});

export type ReportCitation = {
  source_index?: number | null;
  doc_type?: string | null;
  excerpt?: string | null;
};
export type ReportResponse = z.infer<typeof reportResponseSchema>;

export const historyItemSchema = z.object({
  job_id: z.string(),
  ticker: z.string(),
  question: z.string().nullable().optional(),
  status: reportStatusSchema,
  risk_score: z.number().nullable().optional(),
  is_starred: z.boolean().optional().default(false),
  created_at: z.string().nullable().optional(),
});
export type HistoryItem = z.infer<typeof historyItemSchema>;

export const historySchema = z.array(historyItemSchema);

// Ticker detail — powers the dashboard page
export const pricePointSchema = z.object({
  date: z.string(),
  open: z.number().nullable().optional(),
  high: z.number().nullable().optional(),
  low: z.number().nullable().optional(),
  close: z.number().nullable().optional(),
  volume: z.number().nullable().optional(),
});
export type PricePoint = z.infer<typeof pricePointSchema>;

export const financialsMetricsSchema = z.object({
  period: z.string().nullable().optional(),
  revenue: z.number().nullable().optional(),
  net_income: z.number().nullable().optional(),
  eps: z.number().nullable().optional(),
  pe_ratio: z.number().nullable().optional(),
  gross_margin: z.number().nullable().optional(),
});
export type FinancialsMetrics = z.infer<typeof financialsMetricsSchema>;

export const latestFilingSchema = z.object({
  filing_type: z.string(),
  filed_date: z.string().nullable().optional(),
  accession_number: z.string().nullable().optional(),
  source_url: z.string().nullable().optional(),
});
export type LatestFiling = z.infer<typeof latestFilingSchema>;

export const tickerResponseSchema = z.object({
  symbol: z.string(),
  company_name: z.string().nullable().optional(),
  sector: z.string().nullable().optional(),
  industry: z.string().nullable().optional(),
  market_cap: z.number().nullable().optional(),
  latest_price: z.number().nullable().optional(),
  previous_close: z.number().nullable().optional(),
  day_change: z.number().nullable().optional(),
  day_change_pct: z.number().nullable().optional(),
  updated_at: z.string().nullable().optional(),
  prices: z.array(pricePointSchema).default([]),
  financials: financialsMetricsSchema.nullable().optional(),
  latest_filing: latestFilingSchema.nullable().optional(),
  filings: z.array(latestFilingSchema).default([]),
  financials_history: z.array(financialsMetricsSchema).default([]),
});
export type TickerResponse = z.infer<typeof tickerResponseSchema>;

// Chat message response (lightweight RAG)
export const chatMessageResponseSchema = z.object({
  answer: z.string(),
  citations: z.array(z.string()).default([]),
  confidence: z.string().nullable().optional(),
});
export type ChatMessageResponse = z.infer<typeof chatMessageResponseSchema>;

// Analyze check (existing report)
export const analyzeCheckSchema = z.object({
  exists: z.boolean(),
  ticker: z.string(),
  job_id: z.string().optional(),
  created_at: z.string().nullable().optional(),
  summary_preview: z.string().optional(),
});
export type AnalyzeCheck = z.infer<typeof analyzeCheckSchema>;

// Conversations
export const turnSchema = z.object({
  id: z.string(),
  role: z.enum(["user", "assistant"]),
  content: z.string(),
  job_id: z.string().nullable().optional(),
  created_at: z.string(),
});
export type Turn = z.infer<typeof turnSchema>;

export const conversationSchema = z.object({
  id: z.string(),
  ticker: z.string().nullable().optional(),
  title: z.string(),
  created_at: z.string(),
  updated_at: z.string(),
  turns: z.array(turnSchema).default([]),
});
export type Conversation = z.infer<typeof conversationSchema>;

export const conversationListItemSchema = z.object({
  id: z.string(),
  ticker: z.string().nullable().optional(),
  title: z.string(),
  created_at: z.string(),
  updated_at: z.string(),
});
export type ConversationListItem = z.infer<typeof conversationListItemSchema>;

export const conversationListSchema = z.array(conversationListItemSchema);

export const tickerHitSchema = z.object({
  ticker: z.string(),
  name: z.string(),
  exchange: z.string(),
  score: z.number(),
});
export type TickerHit = z.infer<typeof tickerHitSchema>;

export const tickerHitListSchema = z.array(tickerHitSchema);
