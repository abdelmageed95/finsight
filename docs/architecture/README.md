# Architecture — the *why* behind every major choice

The other docs in `docs/` answer *what* and *how*. This one answers **why**: why the multi-agent shape, why two databases, why Claude Haiku for everything, why ECS Fargate instead of Kubernetes, why JWT, why Next.js + FastAPI. Each section gives the choice, the alternatives we rejected, and the reason we picked what we picked.

If you only read one doc to understand FinSight's design, read this one.

---

## 0. The product shape that drives everything

Before any tool choice makes sense, the constraints have to be on the table:

- **One developer, portfolio scope.** Every hour spent on infra is an hour not spent on the product. The bar is "correct, deployable, explainable" — not "Netflix-scale."
- **Mixed read/write workload.** RAG retrieval (read-heavy, vector-shaped), business data (relational, transactional), and conversation state (write-heavy, simple keys).
- **Latency target ≈ 10–30 s** for a research query, ≈ 2–3 s for chat. That's enough headroom to choose the simpler tool in almost every case.
- **Real money on every LLM call.** OpenAI embeddings and Anthropic completions both cost per token; reducing redundant work is a first-class concern.
- **International coverage from day one.** US-only data providers are unacceptable — Middle East tickers must just work.

Every design choice below traces back to one of these.

---

## 1. Why a multi-agent pipeline (LangGraph), not a single LLM call

**The choice.** `Supervisor → DataAgent → RAGAgent → ReportAgent`, wired in `agents/orchestrator.py` as a LangGraph `StateGraph` with a state schema and reducers (`add_messages`, `extend_list`, `merge_dicts`).

**The problem it solves.** A single LLM call asked to "research AAPL" has to silently invent everything — there's no way to inject fresh prices, no way to ground citations, no way to cache intermediate results, and no place to put a non-LLM step like "fetch SEC EDGAR with retry." It also makes a greeting (`hi`) cost the same as a real research query.

**Alternatives considered.**
- **One big prompt with tool-use** — works, but conflates orchestration with reasoning. Every step is in the model's hot context; you can't cache the data fetch independently of the analysis.
- **Plain function chain (no framework)** — fine until you need conditional routing, partial-state recovery, or streaming intermediate events. We'd have built a worse LangGraph.
- **CrewAI / AutoGen** — heavier abstractions, more opinionated, more magic.

**Why LangGraph.** Explicit state, explicit edges, explicit reducers. The graph is readable as a diagram, and each node is just a Python function. Conditional routing (`supervisor` → `smalltalk` vs. `data_agent`) is one edge, not a try/except in a prompt. Adding a node later doesn't require rethinking the whole pipeline.

**The supervisor pattern specifically** is what makes greetings cheap: a Claude Haiku 4.5 classifier (+ a regex fast path for obvious greetings) routes `hi`/`thanks` to a 2-second smalltalk reply that never touches the data pipeline. Without it, every "hello" would cost ~30 seconds and dozens of API calls.

---

## 2. Why two databases — Postgres *and* ChromaDB

**The choice.** Postgres is the system of record for business data (users, tickers, filings, conversations, reports). ChromaDB is the system of record for vectors and chunked text. Linked by `Chunk.embedding_id` → Chroma vector id. Full detail in [`docs/databases/README.md`](../databases/README.md).

**The problem it solves.** Vectors and relational rows want completely different things:
- Vectors want HNSW ANN indexes, metadata-where filtering, and large per-row payloads (3072 floats).
- Business data wants foreign keys, unique constraints, migrations, transactions.

Putting both in one engine forces compromise on at least one side.

**Alternatives considered.**
- **Postgres + `pgvector`** (everything in Postgres). Real option. We rejected it because: (a) Chroma's metadata filter API is friendlier for our use case, (b) re-embedding millions of chunks shouldn't churn the OLTP DB, (c) Chroma can be rebuilt from scratch from Postgres `Filing.raw_text` — treating vectors as a *derived index* is a much cleaner mental model than treating them as a co-equal table.
- **Pinecone / Weaviate / Qdrant managed.** All work. All add a paid service for something we can run for free in a container. Not portfolio-appropriate.
- **One document store (Mongo, etc.).** Loses the relational integrity we rely on for conversations, reports, and re-embedding triggers.

**Why this split wins.** Each engine runs on hardware sized for its workload (Postgres = small rows mixed read/write, Chroma = read-heavy large values), and the contract between them — `Filing.content_hash` vs `Filing.embedded_content_hash` triggers re-embed — is just one column comparison. Drift is recoverable by re-running `embed_all_pending` (idempotent).

---

## 3. Why Redis is scoped to *one* thing

**The choice.** Redis caches OpenAI query embeddings (24-hour TTL, three-tier lookup with an in-memory LRU on top). Full detail in [`docs/cache/README.md`](../cache/README.md).

**The problem it solves.** Embedding a user query costs ~300 ms and real money. The same question — phrased identically by anyone — should not re-pay both.

**What we deliberately *don't* use Redis for.**
- Sessions → JWT carries everything we need; no server-side store needed.
- Job queue → analysis runs as a FastAPI `BackgroundTask`. No Celery, no SQS.
- Pub/sub for progress events → in-memory `asyncio.Queue` (`api/event_bus.py`). Single uvicorn process; the docstring notes Redis pub/sub would be the upgrade if we scaled to multi-worker.
- Rate limiting → `slowapi` is in-process for now.

**Why narrow.** Every additional Redis use case is another invalidation problem, another failure mode in `/health`, another thing to reason about. Scoping it to embeddings — where the keys are content-addressed SHA-256 hashes and a stale value is impossible — makes the cache a near-zero-risk performance win.

---

## 4. Why Claude Haiku 4.5 for *every* LLM call, OpenAI only for embeddings

**The choice.** All generation — intent classification, smalltalk, RAG report writing, stock comparison, and the eval LLM-as-judge — runs on `claude-haiku-4-5-20251001`. OpenAI is used only for `text-embedding-3-large`.

**The problem it solves.** Mixed-vendor LLM stacks make latency, cost, and quality reasoning much harder ("is this slow because of GPT-4 or because of Claude?"). They also mean two sets of rate limits to monitor, two auth flows, and two failure modes per request.

**Why Haiku, not Sonnet/Opus?**
- Intent classification is a 50-token decision — using a frontier model would burn money for no quality win.
- Report generation with structured output (`ReportSchema` SWOT/bull/bear/risk-breakdown) is well within Haiku's capability when the context is well-curated (which the RAG layer makes sure it is).
- Latency: Haiku is roughly 3–5× faster than Sonnet for the same prompt; that translates directly into the 10–30 s end-to-end target.

**Why OpenAI for embeddings?**
- `text-embedding-3-large` (3072 dim) gives best-in-class retrieval quality at low cost.
- Embeddings are stateless and cacheable — vendor concentration risk here is much lower than for generation.

**Switching cost is low** — every LLM call uses LangChain's `ChatAnthropic`, so swapping models or vendors is a config change, not a refactor.

---

## 5. Why the multi-source data fallback chain

**The choice.** Prices/financials: yfinance → Massive (Polygon) → Twelve Data → EODHD → Tiingo. News: Alpha Vantage → Massive → EODHD → Tiingo. The first provider that returns data wins; the result records which provider served it (`price_source`, `financials_source`).

**The problem it solves.** yfinance is free and great for US tickers — and useless for half the world. EODHD has 70+ exchanges but costs money. Twelve Data is strong on Middle East but weaker on US fundamentals. **No single provider covers every market FinSight needs at every price point.**

**Alternatives considered.**
- **One paid provider for everything** (e.g. Bloomberg, Refinitiv). Out of budget by two orders of magnitude.
- **Fail fast on missing data.** Acceptable for US-only apps; unacceptable for "what about 2222.SR (Saudi Aramco)?"

**Why a chain.** Each source has a small adapter (`pipelines/massive.py`, `pipelines/twelvedata.py`, etc.) with a common interface. Order is cost + coverage optimized: free + broad first, paid + niche last. A missing API key just skips that link in the chain — adding a new provider is one file.

---

## 6. Why ECS Fargate + ALB (and not Kubernetes)

The full per-dimension comparison is below in §9. Short version:

**The choice.** ECS Fargate for compute, one ALB for ingress (path-based routing splits API and frontend on the same hostname), application-auto-scaling target-tracking on CPU. Full detail in [`docs/alb-autoscaling/README.md`](../alb-autoscaling/README.md).

**The problem it solves.** "Run two containers, route traffic to them, scale the busy one, and don't make me run servers."

**Alternatives considered.**
- **EC2 + ASG** (the classic). Means patching AMIs, managing user-data, sizing instances. Hours of toil to save dollars.
- **Lambda + API Gateway.** Wrong shape — our requests are 10–30 s with WebSocket-like streaming, the reranker model is 100 MB+, and cold starts on that are painful.
- **EKS (managed Kubernetes).** ~$73/month for the control plane *before any workload runs*, plus weeks of cluster-shaped learning. Overkill for two services. See §9.
- **App Runner / Lightsail.** Too opinionated; harder to integrate with VPC/RDS/Secrets the way we want.

**Why Fargate.** No node management, per-second billing, autoscaling is a few Terraform lines, integrates natively with ALB target groups and IAM task roles. The smallest possible "real" container platform.

---

## 7. Why Next.js + FastAPI (instead of one monolith)

**The choice.** FastAPI backend serves JSON over REST + SSE. Next.js 16 (App Router) frontend served separately. Both live behind the same ALB so the browser sees one origin (no CORS).

**The problem it solves.** The backend is async-Python-heavy (LangGraph, asyncpg, embeddings) and the frontend is React-heavy with charts and streaming UIs. Lumping them into one runtime would compromise both.

**Alternatives considered.**
- **Streamlit / Gradio.** Great for prototypes; terrible for the rich workspace UI we wanted (per-ticker tabs, candlestick charts, draggable layouts, OAuth, PDF export).
- **Django + HTMX** (full-stack Python). Viable, but loses the type-safe Zod-mirror-of-Pydantic schema layer and the rich React ecosystem (TradingView Lightweight Charts, Radix UI, TanStack Query).
- **Next.js fullstack (API routes only).** Would mean writing the agents in TypeScript or shelling out — neither is good.

**Why this split.** FastAPI gives us first-class async + Pydantic type contracts. Next.js gives us static-at-the-edge marketing pages, SSR for the workspace, and HMR during dev. The Pydantic ↔ Zod schema mirror (`api/schemas.py` ↔ `frontend/src/lib/schemas.ts`) means the boundary is type-safe in both languages — wrong response shapes break tests, not users.

---

## 8. Smaller "why"s worth a paragraph each

**Why JWT (24 h expiry) and not server-side sessions.** No Redis dependency for auth, stateless API tasks (any task can serve any user), simple to revoke at expiry. 24 h is the trade between user friction and blast radius if a token leaks.

**Why Alembic, not SQLAlchemy `create_all`.** Schema changes have to be reviewable, ordered, and reversible. `create_all` works in dev and silently drifts in prod. Alembic + autogenerate gives us migrations as code-review artifacts; they run automatically on container start.

**Why Docker Compose for local dev, native runtimes for hot-reload.** Compose is the right tool for the *databases* (single command, isolated, ephemeral). Native Python + Node is the right tool for the *app code* (one-second reload vs 30-second rebuild). The hybrid (`./scripts/dev.sh`) gives both.

**Why Terraform, not CDK / Pulumi / ClickOps.** Terraform's HCL is the lowest-cognitive-overhead way to describe AWS, and the entire state can be torn down with one command — the most important property for a portfolio project. CDK would mean writing more code; ClickOps would mean no record of what's deployed.

**Why GitHub Actions + OIDC, not stored AWS keys.** Long-lived secrets in CI are the #1 cause of AWS account compromise stories. OIDC means each workflow run gets a 1-hour token scoped to one IAM role — there is no key to leak.

**Why parent/child chunking + temporal headers + hybrid retrieval.** Each defends against a specific failure mode dense embeddings have: parent/child gives the LLM enough context to reason from, temporal headers stop "FY2024 wins on similarity over FY2025", hybrid retrieval (vector + BM25 via RRF) catches keyword-exact terms that embeddings smudge. Full mechanism in [`docs/agents/README.md`](../agents/README.md).

**Why the cross-encoder reranker, baked into the image.** The reranker (`ms-marco-MiniLM-L-6-v2`) buys a measurable accuracy bump on top-k retrieval. Baking it into the Docker image (instead of downloading at boot) means deterministic startup time and no surprise outage when HuggingFace hub has a bad day.

---

## 9. ECS Fargate + ALB vs Kubernetes — the full comparison

This is the question every container-shaped project gets asked. The short version: **for one developer running two services in one AWS account, ECS Fargate is the correct answer.** Kubernetes wins as the surface area grows — multi-team, multi-cluster, multi-cloud, or rich scheduling.

| Dimension | ECS Fargate + ALB | Kubernetes (EKS) |
|---|---|---|
| **Time to first deploy** | Hours. One Terraform stack, one ALB, one service. | Days–weeks. Cluster + node groups + ingress controller + cert-manager + RBAC + IAM-for-service-accounts + Helm charts. |
| **Concepts to learn before shipping** | ~3: service, task, target group. | ~20: Pod, Deployment, Service, Ingress, ConfigMap, Secret, RBAC, Helm, controllers, operators, … |
| **Fixed monthly cost** | ~$0 — you pay only for running tasks + ALB. | ~$73/month for the EKS control plane *before any pod runs*, plus node cost if not on Fargate. |
| **Ops surface** | AWS console + `aws ecs` CLI. Logs in CloudWatch. | `kubectl`, Helm, k9s, plus everything AWS. Two ecosystems. |
| **Autoscaling** | Built-in, target-tracking, one Terraform block. | HPA + metrics-server + (optionally) Karpenter / Cluster Autoscaler. More flexible, more moving parts. |
| **Portability** | AWS-locked. Moving off ECS = rewrite. | Run anywhere — EKS, GKE, AKS, kind on your laptop. Real value if multi-cloud is on the table. |
| **Ecosystem** | What AWS gives you. | Huge — ArgoCD, service meshes, operators, Prometheus stack. Powerful when you actually need it. |
| **Team scale where it shines** | 1 dev → small team. | Multiple teams sharing a cluster, or a platform team supporting product teams. |

### When Kubernetes wins

- You run on **multiple clouds** (or want the option). Kubernetes is the only realistic abstraction.
- Multiple teams need **isolated namespaces** on shared infra, with quotas + RBAC.
- You need an **ecosystem tool that only exists as a K8s operator** (Crossplane, Strimzi, ArgoCD).
- You're **already running it elsewhere** — operational consistency outweighs per-service complexity.
- Workloads with **rich scheduling needs** — GPU scheduling, batch jobs, complex stateful failover.

### When ECS Fargate wins (and why FinSight uses it)

- Single AWS account, single region, single product.
- 1–3 services, deployed by 1–3 people.
- "Stand it up, point traffic at it, watch the dashboard."
- You'd rather spend the hours on product code than on the platform.

That last one is the entire game for FinSight. Every hour saved on infra was an hour spent on the RAG pipeline, the agents, the frontend — the things that actually make the project interesting.

### The honest meta-point

The default-cool answer to "which is better" is *"Kubernetes, obviously."* It's not. **Kubernetes is better at being Kubernetes** — distributed systems abstraction, multi-tenancy, ecosystem reach. **ECS Fargate is better at being out of your way** — and for a portfolio app with one API service, being out of your way is the entire requirement.

If FinSight grew into 10 microservices, 3 environments, a platform team, and multi-region — you'd revisit. Until then, what's here is correctly sized.

---

## 10. Decision summary

| Area | Choice | Top reason |
|---|---|---|
| Orchestration | LangGraph multi-agent | Explicit state, conditional routing, supervisor short-circuits cheap intents |
| Operational DB | Postgres 16 + Alembic | Relational integrity, transactions, reviewable migrations |
| Vector store | ChromaDB (separate) | HNSW + metadata filters, derivable from Postgres, separate ops profile |
| Cache | Redis (one job: embeddings) | Cross-process embedding cache; everything else stays in-process |
| LLM | Claude Haiku 4.5 (single vendor) | Latency, cost, simpler ops, sufficient quality with good RAG |
| Embeddings | OpenAI `text-embedding-3-large` | Best-quality 3072-dim vectors at low cost |
| Data sources | Multi-source fallback chain | No single provider covers Middle East + US + EMEA at portfolio prices |
| Backend | FastAPI (async) | Native async + Pydantic, perfect for LangGraph orchestration |
| Frontend | Next.js 16 App Router | SSR, HMR, rich ecosystem (charts, OAuth, PDF), Zod ↔ Pydantic |
| Auth | JWT (24 h) | Stateless, no Redis dependency, easy to scale tasks horizontally |
| Local dev | Docker (DBs) + native (app) | One-second hot-reload + isolated databases |
| IaC | Terraform | Reviewable, reproducible, fully tear-downable |
| Compute | ECS Fargate | Two services, no node management, scales automatically |
| Ingress | One ALB, path-based routing | One origin → no CORS, one ALB cost, simple routing rules |
| CI/CD | GitHub Actions + OIDC | No long-lived AWS keys, runs on push to main |

If you understand *why* each row is what it is, you understand FinSight's design.
