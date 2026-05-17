import Link from "next/link";
import { ArrowRight, BarChart3, Brain, FileText, MessageSquare } from "lucide-react";
import { Logo } from "@/components/finsight/logo";
import { TickerSearch } from "@/components/finsight/ticker-search";
import { AnimatedGrid } from "@/components/finsight/animated-grid";
import { Button } from "@/components/ui/button";

export default function LandingPage() {
  return (
    <main className="flex min-h-screen flex-col">
      <header className="relative z-10 mx-auto flex w-full max-w-7xl items-center justify-between px-6 py-5">
        <Logo size="lg" />
        <nav className="flex items-center gap-2 text-sm text-[var(--color-muted-strong)]">
          <Link
            href="/home"
            className="hidden rounded-[var(--radius-md)] px-3 py-2 hover:text-[var(--color-foreground)] md:block"
          >
            Home
          </Link>
          <Button variant="secondary" size="sm" asChild>
            <Link href="/home">Open app</Link>
          </Button>
        </nav>
      </header>

      <section className="relative flex flex-1 items-center justify-center overflow-hidden px-6 py-20">
        <AnimatedGrid />

        <div className="relative z-10 mx-auto flex w-full max-w-4xl flex-col items-center text-center">
          <span className="mb-6 inline-flex items-center gap-2 rounded-full border border-[var(--color-border)] bg-[var(--color-surface)]/80 px-3 py-1 text-xs text-[var(--color-muted-strong)] backdrop-blur">
            <span className="h-1.5 w-1.5 rounded-full bg-[var(--color-accent)]" />
            Live: SEC filings, market data, RAG, and multi-agent reasoning
          </span>

          <h1 className="text-balance text-5xl font-semibold leading-[1.05] tracking-tight text-[var(--color-foreground)] sm:text-6xl md:text-7xl">
            Institutional-grade
            <br />
            equity research,{" "}
            <span className="text-[var(--color-accent)]">in 30 seconds.</span>
          </h1>

          <p className="mt-6 max-w-2xl text-pretty text-base text-[var(--color-muted-strong)] sm:text-lg">
            An AI analyst trained on 10-Ks, live market data, and CFA methodology.
            Ask any question about any public company and get a cited, structured
            answer — not a hallucination.
          </p>

          <div className="mt-10 w-full">
            <TickerSearch className="mx-auto" />
          </div>
        </div>
      </section>

      <section className="relative z-10 border-t border-[var(--color-border)] bg-[var(--color-surface)]/40">
        <div className="mx-auto grid w-full max-w-7xl grid-cols-1 gap-px bg-[var(--color-border)] md:grid-cols-3">
          <Feature
            icon={<BarChart3 className="h-5 w-5" />}
            title="Live market data"
            body="OHLCV prices, financials, and KPIs ingested continuously from yfinance and SEC EDGAR."
          />
          <Feature
            icon={<Brain className="h-5 w-5" />}
            title="Multi-agent reasoning"
            body="A supervisor routes queries to specialist agents: data collection, RAG retrieval, and report synthesis."
          />
          <Feature
            icon={<FileText className="h-5 w-5" />}
            title="Cited, structured reports"
            body="Every claim links back to a specific 10-K chunk. Risk scored 0–100 with a CFA-style rationale."
          />
        </div>
      </section>

      {/* How it works */}
      <section className="border-t border-[var(--color-border)] bg-[var(--color-background)]">
        <div className="mx-auto w-full max-w-5xl px-6 py-16">
          <h2 className="text-center text-sm font-medium uppercase tracking-wider text-[var(--color-muted)]">
            How it works
          </h2>
          <div className="mt-8 grid grid-cols-1 gap-8 md:grid-cols-3">
            <Step
              number="1"
              title="Pick a ticker"
              body="Enter any US public company symbol above. First-time analysis takes ~30–60 seconds to fetch SEC filings and market data."
            />
            <Step
              number="2"
              title="View the dashboard"
              body="See live prices, financials, and a candlestick chart. Click 'Generate report' to run the AI analyst and get a risk-scored research summary."
            />
            <Step
              number="3"
              title="Ask follow-up questions"
              body="Open the Chat to have a multi-turn conversation. The AI remembers earlier questions and builds on previous analysis."
            />
          </div>
          <div className="mt-10 flex flex-wrap items-center justify-center gap-3">
            <Button variant="primary" size="lg" asChild>
              <Link href="/workspace/AAPL">
                <BarChart3 className="h-4 w-4" />
                Open AAPL workspace
              </Link>
            </Button>
            <Button variant="secondary" size="lg" asChild>
              <Link href="/workspace/AAPL?tab=chat">
                <MessageSquare className="h-4 w-4" />
                Try the chat
              </Link>
            </Button>
            <Button variant="ghost" size="lg" asChild>
              <Link href="/home">
                <FileText className="h-4 w-4" />
                Your reports
              </Link>
            </Button>
          </div>
        </div>
      </section>

      <footer className="border-t border-[var(--color-border)]">
        <div className="mx-auto flex w-full max-w-7xl flex-col items-center justify-between gap-4 px-6 py-10 sm:flex-row">
          <div className="flex items-center gap-3 text-xs text-[var(--color-muted)]">
            <Logo size="sm" />
            <span>© {new Date().getFullYear()} FinSight Research</span>
          </div>
          <Link
            href="/demo/AAPL"
            className="inline-flex items-center gap-1 text-sm text-[var(--color-muted-strong)] hover:text-[var(--color-accent)]"
          >
            See a sample report <ArrowRight className="h-3.5 w-3.5" />
          </Link>
        </div>
      </footer>
    </main>
  );
}

function Feature({
  icon,
  title,
  body,
}: {
  icon: React.ReactNode;
  title: string;
  body: string;
}) {
  return (
    <div className="bg-[var(--color-background)] p-8">
      <div className="mb-4 inline-flex h-9 w-9 items-center justify-center rounded-[var(--radius-md)] border border-[var(--color-border)] bg-[var(--color-surface)] text-[var(--color-accent)]">
        {icon}
      </div>
      <h3 className="text-base font-semibold text-[var(--color-foreground)]">
        {title}
      </h3>
      <p className="mt-1.5 text-sm leading-relaxed text-[var(--color-muted-strong)]">
        {body}
      </p>
    </div>
  );
}

function Step({
  number,
  title,
  body,
}: {
  number: string;
  title: string;
  body: string;
}) {
  return (
    <div className="flex gap-4">
      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full border border-[var(--color-accent)] text-sm font-semibold text-[var(--color-accent)]">
        {number}
      </div>
      <div>
        <h3 className="text-sm font-semibold text-[var(--color-foreground)]">
          {title}
        </h3>
        <p className="mt-1 text-sm leading-relaxed text-[var(--color-muted-strong)]">
          {body}
        </p>
      </div>
    </div>
  );
}
