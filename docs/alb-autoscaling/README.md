# ALB + ECS Autoscaling

How the front door (Application Load Balancer) and the elastic capacity layer (ECS auto-scaling) work together in FinSight's AWS deployment — and why we configured them the way we did.

---

## 1. The shape, in one picture

```
                    Internet (HTTP :80)
                         │
                         ▼
                ┌────────────────────┐
                │  ALB (public)      │   public subnets, internet-facing
                │  default → fe-tg   │
                │  /auth*  → api-tg  │   listener rules
                │  /api*   → api-tg  │
                └─────────┬──────────┘
                          │ register-by-IP
        ┌─────────────────┼──────────────────┐
        ▼                                    ▼
  ┌─────────────┐                      ┌─────────────┐
  │ ECS service │                      │ ECS service │
  │   api       │  ← autoscaled        │   frontend  │  fixed at 1 task
  │ 1 – 3 tasks │                      │             │
  └─────────────┘                      └─────────────┘
       private subnets, awsvpc — only the ALB can reach them
```

The ALB is the **only** public endpoint. Everything else (ECS tasks, RDS, Redis, Chroma) sits in private subnets and is reachable only by the security group of whatever should reach it.

---

## 2. The ALB — what it does for us

Defined in `infra/terraform/alb.tf`. Key choices:

| Property | Value | Why |
|---|---|---|
| `internal` | `false` | The ALB has a public DNS name (`finsight-prod-alb-...elb.amazonaws.com`) — that's the user-facing URL. |
| `load_balancer_type` | `application` | Layer 7 (HTTP) so we can route by URL path. An NLB would only see TCP. |
| Subnets | the 2 public subnets | An ALB must live in ≥ 2 AZs for high availability. |
| Security group | only allows :80 from `0.0.0.0/0` | Public ingress; egress is unrestricted because the ALB *talks to* the private ECS tasks. |

### Why one ALB instead of two

We host the API and the frontend behind the **same hostname**, split by URL path:

- `/analyze*`, `/report*`, `/ticker*`, `/history*`, `/conversations*`, `/auth*`, `/health*`, `/docs*`, `/openapi.json` → API target group
- Everything else (`/`, `/_next/*`, `/home`, `/workspace/*`, …) → frontend target group

This means the browser sees one origin, so **no CORS**, **no second domain**, and **no extra ALB cost** (an ALB is ~$17/month — running two would double the fixed cost).

The split is wired with two listener rules sharing the same listener (`alb.tf:79-112`). Two rules instead of one because an AWS listener rule allows at most **5 path-pattern values**, and we have nine — so we split them across rule priority 100 and 110. Both forward to the same `api-tg` target group.

### Target groups — what gets registered

Two target groups, both `target_type = "ip"`. Why "ip" and not "instance":

ECS Fargate uses `awsvpc` networking, which gives each task its own private IP (an ENI in your VPC) instead of sharing the host's IP. The ALB has to talk to that ENI directly, so it registers task IPs as targets. Every time ECS starts a new task, it auto-registers; every time a task stops, it deregisters.

| Target group | Port | Health check | Why those values |
|---|---|---|---|
| `api-tg` | 8000 | `GET /health` every 30s, healthy after 2 OKs, unhealthy after 3 fails | `/health` pings DB + Redis + Chroma (`api/routers/health.py`) so the ALB only routes to tasks that can actually serve real traffic. |
| `frontend-tg` | 3000 | `GET /` every 30s, same thresholds | Next.js doesn't need a richer probe — if `/` returns 200, the standalone server is up. |

`deregistration_delay = 30` (seconds) is the **drain time** — when ECS kills a task during a deploy, the ALB stops sending new requests immediately but lets in-flight requests finish for 30s before cutting the connection. AWS default is 300s; 30s is enough for our short request profile and makes deploys feel snappy.

### Listener

```
HTTP :80 ─┬─ default action → frontend-tg
          ├─ rule priority 100 (5 paths)  → api-tg
          └─ rule priority 110 (4 paths)  → api-tg
```

HTTP-only by design — this is portfolio-grade. Adding HTTPS would mean importing/issuing an ACM cert, adding a `:443` listener with `default_action.forward`, and pointing a custom domain via Route 53. That's a one-day extension, not a rewrite — the rest of the stack stays untouched.

---

## 3. ECS auto-scaling — the API service

The API is the only service that scales; the frontend is pinned to `desired_count = 1` because Next.js standalone is light (256 CPU / 512 MB) and serving static-ish HTML is rarely the bottleneck.

### Knobs (in `infra/terraform/variables.tf` and `ecs.tf`)

| Knob | Default | Meaning |
|---|---|---|
| `api_cpu` | `1024` | 1 vCPU per task — Torch + the cross-encoder reranker need a full core to feel snappy. |
| `api_memory` | `4096` | 4 GB per task — the reranker model + sentence-transformers stack is hungry. |
| `api_desired_count` | `1` | Baseline; also the autoscaling **minimum**. |
| `api_max_count` | `3` | Autoscaling **maximum** — caps cost at 3× baseline. |

### The policy — target-tracking on CPU

Defined in `infra/terraform/ecs.tf:90-113`:

```hcl
aws_appautoscaling_target.api    {min=1, max=3, ECS service desired_count}
aws_appautoscaling_policy.api_cpu {
  predefined_metric = "ECSServiceAverageCPUUtilization"
  target_value      = 60       # keep avg CPU ≈ 60%
  scale_out_cooldown = 60      # wait 1 min between scale-OUT actions
  scale_in_cooldown  = 300     # wait 5 min between scale-IN actions
}
```

That's the entire scaling brain. Target-tracking is the simplest of the three ECS scaling modes:

- **Target-tracking** *(what we use)* — you give a target value for a metric and AWS adjusts capacity to hit it. It auto-creates two CloudWatch alarms under the hood: one for "metric high → add tasks", one for "metric low → remove tasks".
- Step scaling — you wire up alarms and define explicit "+1 task" / "+3 tasks" steps yourself. More control, more rope.
- Scheduled scaling — fixed `desired_count` at fixed times. Useful for predictable spikes (market open).

### Why those specific values

| Choice | Why |
|---|---|
| **CPU not memory** | Memory is roughly flat per task (the torch/reranker baseline dominates over per-request usage). CPU tracks actual load — embeddings, reranking, and LLM IO-wait orchestration. |
| **target = 60%** | A target of, say, 80% would scale only after the existing task is already saturated — users see latency before extra capacity arrives. 60% gives headroom for a request burst between the alarm firing and the new task becoming healthy. |
| **scale-out cooldown = 60s** | A new Fargate task takes 60–120s to pull the image, boot, load the reranker, and pass `/health`. A short cooldown lets us react to genuine load quickly without flapping. |
| **scale-in cooldown = 300s** | Scaling in is cheap to do wrong (you kill a warm task) and expensive to recover from (next task needs another 60–120s to warm up). Long cooldown = stable, slightly more expensive, much less surprising. |
| **`lifecycle { ignore_changes = [desired_count] }`** on the service (`ecs.tf:54-56`) | Autoscaling **owns** `desired_count` once the service exists. Without this, every `terraform apply` would reset desired back to the variable's default and fight with the scaling policy. |

### What "scale-out" actually looks like end-to-end

1. Load arrives → existing API task's CPU climbs.
2. CloudWatch sees the 1-minute average breach the target → fires the auto-generated alarm.
3. Application Auto Scaling bumps the ECS service's `desired_count` from 1 → 2.
4. ECS asks Fargate to provision a second task in a private subnet.
5. Task starts (~60–120s with our image: torch + reranker init), passes `/health`.
6. ALB registers the new task's IP in `api-tg` (after the `health_check_grace_period_seconds = 120` window).
7. ALB starts splitting traffic ~50/50 across the two tasks (round-robin by default).
8. CPU per task drops. After `scale_in_cooldown` of below-target metrics, ECS drains one task and goes back to 1.

That's the whole loop. No code, no human, no pager.

---

## 4. Deployments and rolling updates

ECS handles deploys without help from the ALB rules above — but the ALB is what makes them zero-downtime.

In `infra/terraform/ecs.tf:48-49`:

```hcl
deployment_minimum_healthy_percent = 100
deployment_maximum_percent         = 200
```

Read literally: during a deploy ECS may run between **100%** and **200%** of `desired_count`. With `desired_count = 1`, that means it will spin up a **new** task before killing the old one — never going below 1 running task. The new task registers with `api-tg`, passes health checks, and only then does the old task drain (using the 30s `deregistration_delay`) and stop.

In CI this happens whenever the deploy workflow runs `aws ecs update-service --force-new-deployment` (see `infra/scripts/deploy.sh` and `.github/workflows/deploy.yml`). The ALB never returns a 5xx to the user during the swap — the old task is alive and serving until traffic has cleanly moved.

---

## 5. The minimal mental model

Three rules to keep in your head:

1. **The ALB is the only public thing.** Public DNS → public ALB → private ECS tasks → private databases. Every security group reflects this exact chain.
2. **The ALB picks which service** by URL path; **ECS auto-scaling picks how many copies** of the API service exist. They don't know about each other beyond the target group: ALB sees IPs, scaling moves them in and out.
3. **Health checks are the heartbeat.** `/health` decides "can this task receive traffic" (ALB) and indirectly "are my tasks healthy enough that I should not over-scale into dead ones" (ECS rolls deployments based on the same probe).

---

## 6. What we'd change if we needed more

| Change | What it would touch |
|---|---|
| Add HTTPS | New ACM cert + a `:443` listener in `alb.tf`; the existing rules clone onto it. |
| Custom domain | Route 53 A-record (alias) → ALB; nothing in code changes. |
| Higher peak capacity | Bump `api_max_count` in `tfvars`. Nothing else — the scaling policy stretches automatically. |
| Scale on a custom metric (e.g. SQS queue depth, RAG latency) | Switch policy from `predefined_metric_specification` to `customized_metric_specification`. |
| Frontend autoscaling | Mirror the same `aws_appautoscaling_target` + `aws_appautoscaling_policy` blocks against `aws_ecs_service.frontend`. |
| Blue/green deploys | Swap the rolling deployment for CodeDeploy with two target groups and a test listener — more moving parts, useful when one bad deploy can ruin your day. |

Today's setup is deliberately the minimum that's correct: one ALB, two target groups, one autoscaling policy on the only thing that varies in load. That's enough infrastructure to fit on one page and still cope with real traffic.
