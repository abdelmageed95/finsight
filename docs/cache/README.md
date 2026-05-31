# Cache (Redis)

A small, focused guide to where Redis lives in FinSight, what it actually caches, and why we kept it that narrow.

---

## 1. What we use Redis for — the short answer

**One thing: caching OpenAI query embeddings.**

When a user asks a question, we need to turn that question into a 3072-dim vector before we can search ChromaDB. That vector comes from OpenAI's `text-embedding-3-large` endpoint, which costs money and adds latency (~200–500 ms per call). The same question — or even the same question phrased identically by a different user — would otherwise pay that cost every time.

Redis solves exactly that: hash the query → look up the vector → skip the OpenAI call on a hit.

> Redis is **not** used for sessions, rate limits, job queues, pub/sub, or any other classic Redis use case in this codebase. The job-progress event bus (`api/event_bus.py`) is deliberately in-memory; the file note says we'd swap to Redis pub/sub only if we scale to multiple worker processes.

---

## 2. How it works in code

The cache is a three-tier lookup inside `VectorStore.embed_query` — `rag/vector_store.py:60-95`:

```
embed_query(query)
  1. In-memory LRU (process-local, 256 entries)  → ~0 ms
  2. Redis              (cross-process, 24h TTL)  → ~1–5 ms
  3. OpenAI API         (network round-trip)      → ~200–500 ms
```

- **Key**: `emb:{sha256(query_text)}` — stable across processes and restarts.
- **Value**: the embedding vector, JSON-encoded.
- **TTL**: 24 hours via `setex(key, 86400, ...)`. We don't try to invalidate manually; old keys just expire.
- **Write path**: every miss that calls OpenAI writes back into **both** the LRU and Redis so the next request from any process hits L1 or L2.

Why two tiers (LRU + Redis) instead of just Redis? The LRU is free (just a Python `OrderedDict`) and faster than a network hop. Redis is the cross-process layer so a hit in `uvicorn worker A` is reusable by `worker B` and survives a container restart.

---

## 3. Where Redis is configured

| Layer | What | Where |
|---|---|---|
| **Local dev** | Redis 7 in Docker, exposed on `localhost:6379` | `docker/docker-compose.yml` |
| **Production (AWS)** | ElastiCache Redis 7, single-node, private subnets | `infra/terraform/elasticache.tf` |
| **Client** | `redis.from_url(REDIS_URL, socket_connect_timeout=2)` | `api/routers/health.py:42` and injected into `VectorStore` |
| **Env var** | `REDIS_URL` (defaults to `redis://localhost:6379/0`) | `.env` + Secrets Manager in prod |
| **Health check** | `/health` pings Redis on every ALB probe | `api/routers/health.py:42-50` |

In production, ElastiCache lives in the private subnets — the only thing that can reach it is the ECS API task via the `ecs_api → redis` security-group rule. There's no public endpoint and no auth token (it's network-isolated).

---

## 4. Why such a narrow scope?

We deliberately kept Redis to one job. The other things that *look* like caching in this app are actually persisted state in Postgres, not Redis:

- **Market-data freshness** (`agents/data_agent.py:75-113`) — "cache hit" log lines refer to skipping a *re-fetch* because the row in Postgres is still within its TTL (15 min for prices, 24 h for SEC filings). The check reads `prices.created_at` / `filings.fetched_at` from RDS, not Redis.
- **Re-embedding guard** — `Filing.content_hash` vs `Filing.embedded_content_hash` in Postgres tells the embedder whether the filing changed since last embed. Again, Postgres.
- **No-store HTTP responses** — `Cache-Control: no-cache` headers on the SSE streaming endpoints (`api/routers/analyze.py:264`, `conversations.py:276`) tell the *browser* not to cache; nothing to do with Redis.

Keeping Redis to one job means: small blast radius, simple mental model, easy to reason about a cache hit/miss, and an obvious upgrade path (add pub/sub for multi-worker progress events) without touching anything else.

---

## 5. Operational notes

- **Misses are cheap, hits are huge** — a miss costs an extra `~3 ms` Redis call before falling through; a hit saves a ~300 ms OpenAI round trip. The ratio strongly favors leaving the cache enabled even at low hit rates.
- **Restart safety** — losing Redis (container restart, ElastiCache failover) only re-warms the cache. Nothing breaks; the next requests just pay the OpenAI cost until the cache fills back up.
- **TTL choice** — 24 h is long enough that a typical user's repeated questions hit cache within the same day, and short enough that an OpenAI model upgrade or any embedding-drift issue rolls itself out within a day without manual flushing.
- **Memory footprint** — each entry is one SHA-256 key (~64 bytes) + one 3072-float JSON vector (~30 KB). 100k cached queries ≈ 3 GB; a `cache.t4g.micro` (~0.5 GB) easily holds tens of thousands of unique queries.
- **Health check** — `/health` returns `"redis": "ok" | "error"`. ECS doesn't mark the task unhealthy on a Redis error (the API still works without Redis — it just gets slower), but the overall status flips to `"degraded"` so the dashboard alarm fires.

---

## 6. When we'd extend Redis usage

The current bottleneck isn't caching, so we haven't. But the natural next uses, if they came up, would be:

| Use case | Why Redis fits |
|---|---|
| Job-progress pub/sub across multiple uvicorn workers | The `api/event_bus.py` docstring already calls this out as the upgrade path. |
| Per-user rate limits on `/analyze` | Sliding-window counter with `INCR` + `EXPIRE` — a few lines of code. |
| Idempotency keys on POST `/analyze` | Stop duplicate jobs when the frontend retries a flaky request. |
| Short-lived JWT denylist for forced logout | A `SETEX` per revoked `jti` for the remaining token TTL. |

None of those are implemented today — flagged here so a future contributor knows the shape of what'd go where if/when needed.
