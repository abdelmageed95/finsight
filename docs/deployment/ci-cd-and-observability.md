# CI/CD & Observability — in detail

How code gets from a `git push` to running in production, and how we know it's
healthy once it's there. This is the companion to `docs/deployment/README.md`
(the deployment narrative) and `docs/terraform-study-guide.md` (the
infrastructure deep dive). Where those explain *what* the infrastructure is,
this explains the *pipelines and feedback loops* that operate it.

- **CI** = Continuous Integration — every change is built and tested automatically.
- **CD** = Continuous Delivery/Deployment — changes that pass land in production
  automatically.
- **Observability** = the ability to answer "is it healthy, and if not, why?"
  from the outside, using logs, metrics, and alarms.

Source files this doc describes:

| Concern | File |
|---|---|
| CI workflow | `.github/workflows/ci.yml` |
| CD workflow | `.github/workflows/deploy.yml` |
| Manual deploy (reference) | `infra/scripts/deploy.sh` |
| OIDC trust + deploy role | `infra/terraform/github_oidc.tf` |
| Alarms, SNS, dashboard | `infra/terraform/cloudwatch.tf` |
| Log groups | `infra/terraform/task_definitions.tf` (ECS `logConfiguration`) |

---

# Part 1 — CI/CD

## 1.1 The big picture

```
        ┌──────────────────────── developer ────────────────────────┐
        │   git push (feature branch / PR)        git push to main    │
        └───────────────┬───────────────────────────────┬────────────┘
                        │                                 │
                        ▼                                 ▼
              ┌──────────────────┐              ┌──────────────────────┐
              │   CI  (ci.yml)   │              │   CD  (deploy.yml)    │
              │  on: PR + push   │              │  on: push to main     │
              │  (not main)      │              │       + manual        │
              ├──────────────────┤              ├──────────────────────┤
              │ backend:         │              │ test:  (gate)         │
              │  ruff + pytest   │              │  pytest unit          │
              │ frontend:        │              │        │ needs:       │
              │  eslint + build  │              │        ▼              │
              └──────────────────┘              │ deploy:               │
                  no AWS access                 │  OIDC → AWS           │
                  just "is it correct?"         │  build+push images    │
                                                │  run migration        │
                                                │  roll ECS services    │
                                                └──────────────────────┘
                                                     touches production
```

Two workflows, two jobs each, with a clean split of responsibility:

- **`ci.yml`** runs on every PR and on pushes to *any branch except `main`*. It
  proves a change is **correct** — it never touches AWS. No cloud credentials
  are even available to it.
- **`deploy.yml`** runs on pushes to `main` (and manual dispatch). It re-runs the
  tests as a **gate**, then **ships** — and only this workflow can reach AWS.

The branch split is deliberate: `ci.yml`'s trigger is `push: branches-ignore:
[main]`, and `deploy.yml` owns `main`. So a push to `main` does *not* trigger
both — `deploy.yml` runs the tests itself before deploying, so there's no
redundant CI run, and no way to deploy something whose tests haven't passed.

> **In this repo:** you work on `dev`. A push to `dev` runs `ci.yml`. Nothing
> reaches production until `dev` is merged into `main`, which triggers
> `deploy.yml`. That is why the chat `uid()` fix and the workflow Node-24 bumps
> won't appear in prod until they're merged to `main`.

---

## 1.2 The CI workflow (`ci.yml`) — "is it correct?"

```
trigger: pull_request  OR  push to any branch except main

job: backend ──────────────────────────────┐   job: frontend ───────────────┐
  ubuntu-latest                             │     ubuntu-latest               │
  1. checkout                               │     1. checkout                 │
  2. setup-python 3.12 (pip cache)          │     2. setup-node 20 (npm cache)│
  3. pip install torch (CPU) + dev deps     │     3. npm ci                   │
  4. ruff check .            ← lint         │     4. npm run lint  ← eslint   │
  5. pytest tests/unit/ -v   ← tests        │     5. npm run build ← typecheck+│
                                            │                       bundle    │
  (the two jobs run in parallel)            │                                 │
└────────────────────────────────────────────────────────────────────────────┘
```

Key points:

- **CPU-only torch** (`--index-url .../whl/cpu`) — the default torch wheel pulls
  multi-GB CUDA libraries the runner doesn't need. This keeps CI fast and under
  disk limits. The same trick is used in the Docker build.
- **`npm run build` *is* the frontend type-check** — Next.js compiles
  TypeScript during the production build, so a type error fails CI here. The
  build needs `NEXT_PUBLIC_API_URL` set (it's inlined at build time), so CI
  passes a placeholder `http://localhost:8000`; the *real* value is baked in
  later by `deploy.yml`.
- **No AWS credentials** — CI only answers "does it lint, type-check, test, and
  build?" It cannot deploy, by design.

---

## 1.3 The CD workflow (`deploy.yml`) — "ship it"

```
trigger: push to main  OR  workflow_dispatch (manual button)

concurrency: group=deploy-production, cancel-in-progress=false
   → never two prod deploys at once; queued, not cancelled.

permissions: id-token: write   ← REQUIRED for OIDC (request a token)
             contents: read

┌── job: test ───────────────┐
│  pytest tests/unit/        │   gate — deploy waits on this
└──────────────┬─────────────┘
               │ needs: test
               ▼
┌── job: deploy ─────────────────────────────────────────────────────────┐
│ 1. checkout                                                              │
│ 2. configure-aws-credentials (OIDC)  → assumes AWS_DEPLOY_ROLE_ARN       │
│ 3. amazon-ecr-login                  → docker login to ECR              │
│ 4. resolve infra values              → ALB DNS, private subnets, API SG │
│ 5. build & push API image            → :latest and :<git-sha>          │
│ 6. build & push frontend image       → ALB URL baked in via build-arg   │
│ 7. run DB migration (ECS RunTask)    → alembic upgrade head, wait, check │
│ 8. roll ECS services (force-new-deployment) → wait services-stable      │
│ 9. summary                           → app URL + image tag in job summary│
└─────────────────────────────────────────────────────────────────────────┘
```

### Why each step exists

| Step | Why |
|---|---|
| **`test` as a separate gated job** | `deploy` declares `needs: test`, so a red test stops the deploy before it touches AWS. |
| **`concurrency` group** | Two overlapping deploys could roll the service to different image SHAs and race. `cancel-in-progress: false` *queues* the second so the first finishes cleanly. |
| **`id-token: write`** | Without this permission GitHub won't mint an OIDC token, and `configure-aws-credentials` can't federate. This is the single most common "why won't my OIDC work" cause. |
| **Resolve infra values at runtime** | The workflow reads ALB DNS / subnets / SG from AWS by tag (`describe-*`) instead of hard-coding them, so it keeps working if infra is re-created. |
| **Two image tags (`latest` + `<sha>`)** | `latest` is what the task definition references; `<git-sha>` gives an immutable, traceable handle for rollback ("redeploy the task def pointing at sha abc123"). |
| **Frontend ALB URL via `--build-arg`** | Next.js inlines `NEXT_PUBLIC_*` at *build* time. The API URL can't be a runtime env var, so it must be passed when the image is built. |
| **Migration before service roll** | New code may expect new columns. Run `alembic upgrade head` (as a one-shot ECS task) and verify exit code 0 *before* rolling the app onto the new image. |
| **`force-new-deployment` + `wait services-stable`** | The image tag (`latest`) doesn't change, so ECS needs an explicit nudge to pull the new image. Then we block until both services are healthy so the job reflects real success. |

### The manual equivalent (`infra/scripts/deploy.sh`)

`deploy.sh` does the exact same 7 steps from a laptop (read tf outputs → ECR
login → build/push API → build/push frontend → migrate → roll → wait). It is the
**reference implementation** the CD workflow automates, and the fallback when CI
is unavailable. It reads connection details from `terraform output`; the
workflow instead resolves them via `aws ... describe-*` because GitHub runners
don't have the Terraform state.

> Neither `deploy.sh` nor `deploy.yml` provisions infrastructure or touches
> Chroma — they only ship application images and run migrations. Infra
> (VPC, ECS, RDS, the Chroma EC2 + its EBS volume, secrets) is owned by
> `terraform apply`. This separation is why a secret rotation needs
> `terraform apply` + a service roll, **not** a CD run.

---

## 1.4 OIDC — deploying with no stored AWS keys

The old way: create an IAM user, generate an access key + secret, paste them into
GitHub repo secrets. Those are long-lived credentials sitting in a third-party
system forever — the highest-value thing an attacker can steal.

The OIDC way: GitHub proves *who it is* to AWS for each run, and AWS hands back
**credentials that expire in ~1 hour**. Nothing long-lived is stored anywhere.

```
 ┌─ GitHub Actions run (job: deploy) ─────────────────────────────────────┐
 │                                                                         │
 │  (1) job has  permissions: id-token: write                             │
 │  (2) GitHub mints a signed OIDC JWT describing this run:               │
 │         iss = token.actions.githubusercontent.com                      │
 │         sub = repo:<owner>/<repo>:ref:refs/heads/main                  │
 │         aud = sts.amazonaws.com                                        │
 └───────────────────────────────┬─────────────────────────────────────────┘
                                  │ configure-aws-credentials sends the JWT
                                  ▼
 ┌─ AWS STS : AssumeRoleWithWebIdentity ──────────────────────────────────┐
 │  (3) Is the issuer a trusted OIDC provider?                             │
 │         → aws_iam_openid_connect_provider.github  (github_oidc.tf)      │
 │  (4) Does the JWT satisfy the role's trust policy?                      │
 │         aud StringEquals  sts.amazonaws.com                            │
 │         sub StringLike    repo:<github_repo>:*                         │
 │         → data.aws_iam_policy_document.github_assume                    │
 │  (5) If yes → return TEMPORARY creds for finsight-prod-github-actions   │
 │         (access key + secret + session token, ~1h TTL)                  │
 └───────────────────────────────┬─────────────────────────────────────────┘
                                  ▼
 ┌─ rest of the job uses those temp creds ────────────────────────────────┐
 │  ECR push · ECS RunTask · UpdateService · describe-* lookups            │
 └─────────────────────────────────────────────────────────────────────────┘
```

The trust is two-sided and both sides live in `github_oidc.tf`:

1. **The identity provider** (`aws_iam_openid_connect_provider.github`) tells AWS
   to trust tokens issued by `token.actions.githubusercontent.com` with audience
   `sts.amazonaws.com`. One per AWS account.
2. **The role trust policy** (`data.aws_iam_policy_document.github_assume`)
   restricts *which* GitHub workflows may assume the role:
   - `aud == sts.amazonaws.com` — the token was minted for AWS, not some other service.
   - `sub LIKE repo:${var.github_repo}:*` — only runs from *your* repo. The `:*`
     allows any branch/ref; tighten to `repo:owner/repo:ref:refs/heads/main` to
     allow only `main`.

### The deploy role's permissions (least privilege)

`data.aws_iam_policy_document.github_deploy` grants exactly what the 7 steps
need and nothing more:

| Statement | Actions | Scope |
|---|---|---|
| `ECRAuth` | `ecr:GetAuthorizationToken` | `*` (the token API has no resource) |
| `ECRPush` | layer upload + `PutImage` | only the two ECR repos |
| `ECSDeploy` | `RunTask`, `UpdateService`, `Describe*`, `ListTasks` | `*` (ECS describe needs it) |
| `PassECSRoles` | `iam:PassRole` | **only** the task-execution and task roles, and only to `ecs-tasks.amazonaws.com` |
| `DescribeInfra` | `ec2:DescribeSubnets/SecurityGroups`, `elb:DescribeLoadBalancers` | `*` (read-only lookups) |

`PassRole` is the subtle one: `RunTask` launches a task that *uses* the ECS
roles, so the workflow must be allowed to "pass" them — but scoped to exactly
those two roles, conditioned on the service that may receive them. Without the
condition, a `PassRole` grant is a privilege-escalation hole.

### One-time setup

After `terraform apply`, copy the `github_actions_role_arn` output into the repo
as an **Actions variable** named `AWS_DEPLOY_ROLE_ARN` (Settings → Secrets and
variables → Actions → *Variables*, not Secrets — it's not sensitive). The
workflow reads it as `${{ vars.AWS_DEPLOY_ROLE_ARN }}`.

---

## 1.5 Zero-downtime rolling deploy

The ECS services deploy with `minimum_healthy_percent = 100` and
`maximum_percent = 200`. For a service whose desired count is *N*:

```
 time ─────────────────────────────────────────────────────────────────►
 t0   [old][old]                          N=2 running, 100% healthy
 t1   [old][old][new][new]                ECS starts new tasks (up to 200%)
 t2   [old][old][new✓][new✓]              new tasks pass ALB health checks
 t3              [new✓][new✓]             old tasks drained & stopped
                                          never below N healthy → no downtime
```

- `minimum_healthy_percent = 100` → ECS may **never** drop below *N* healthy
  tasks, so it must add new ones *before* removing old ones.
- `maximum_percent = 200` → it may run up to *2N* briefly (the overlap).
- Cost: one extra set of tasks for the ~1–2 minutes of overlap. Cheap insurance.

This is also the mechanism by which a secret rotation or config change reaches
running tasks: `--force-new-deployment` triggers exactly this roll, and the new
tasks read the fresh secret/image at startup.

---

## 1.6 Debugging the pipeline

| Symptom | Likely cause | Where to look |
|---|---|---|
| `configure-aws-credentials` fails: "Not authorized to perform sts:AssumeRoleWithWebIdentity" | `id-token: write` missing, or trust policy `sub`/`aud` mismatch, or wrong `AWS_DEPLOY_ROLE_ARN` | `deploy.yml` permissions block; `github_oidc.tf` trust conditions |
| `Database migration failed` (exit ≠ 0) | bad migration, or DB unreachable from the task SG/subnets | CloudWatch log group `/ecs/finsight-prod/api`, stream `migrate` |
| Deploy hangs on `wait services-stable` | new tasks crash-loop or fail health checks | ECS service "Events" tab; task stopped reason; app logs |
| App shows old code after a green deploy | browser cache, or the image tag didn't change and ECS reused layers | hard-refresh; confirm `:<sha>` pushed; check task def image |
| "Node.js 20 actions are deprecated" warnings | action majors on Node 20 | bump `checkout@v6`, `setup-python@v6`, `setup-node@v6`, `configure-aws-credentials@v6` |

---

# Part 2 — Observability

## 2.1 What we collect, and why

Observability here rests on the three CloudWatch primitives, all defined in
`cloudwatch.tf` (except logs, which are wired in the task definitions):

```
                         ┌────────────────────────────────────────┐
   ECS tasks ──stdout──► │ CloudWatch Logs                        │  "what happened?"
   (API, frontend,       │   /ecs/finsight-prod/<service>         │
    migrate)             └────────────────────────────────────────┘
                         ┌────────────────────────────────────────┐
   ALB / ECS / RDS ────► │ CloudWatch Metrics (AWS-emitted)       │  "what are the numbers?"
   (automatic)           │   RequestCount, 5XX, CPU, memory, …    │
                         └───────────────┬────────────────────────┘
                                         │ thresholds
                                         ▼
                         ┌────────────────────────────────────────┐
                         │ CloudWatch Alarms ──► SNS topic ──► email│ "tell me when it's bad"
                         │   6 alarms             finsight-prod-     │
                         │                        alerts            │
                         └────────────────────────────────────────┘
                         ┌────────────────────────────────────────┐
                         │ CloudWatch Dashboard (finsight-prod)   │  "show me at a glance"
                         │   4 widgets                            │
                         └────────────────────────────────────────┘
```

## 2.2 Logs

Each ECS task streams stdout/stderr to a CloudWatch log group via the `awslogs`
driver in its task definition. The API uses structured logging, so a request
line looks like:

```
info  request  client=10.0.1.38 duration_ms=36.41 method=GET path=/health
                request_id=a5037af0 status=200
```

How to read them:

```bash
# tail the API logs
aws logs tail /ecs/finsight-prod/api --follow --region eu-central-1

# search for a specific error across the last hour
aws logs filter-log-events \
  --log-group-name /ecs/finsight-prod/api \
  --filter-pattern "embedding failed" \
  --start-time $(( ($(date +%s) - 3600) * 1000 )) \
  --region eu-central-1
```

The `migrate` task logs to the same group under a `migrate` stream — that's where
a failed `alembic upgrade head` surfaces.

## 2.3 Alarms (six of them)

Every alarm sends to the **SNS topic** `finsight-prod-alerts` on *both* trip
(`alarm_actions`) and recovery (`ok_actions`), so you get a "FIRING" and a
matching "RESOLVED" email. Set `alarm_email` in `terraform.tfvars` to subscribe
(AWS emails a one-time confirmation link you must click).

| Alarm | Metric | Condition | Why this threshold |
|---|---|---|---|
| `alb-5xx` | `HTTPCode_ELB_5XX_Count` | > 5 in 5 min | A few 5xx can be transient; a sustained burst means the app or its deps are broken. |
| `api-unhealthy-hosts` | `UnHealthyHostCount` | > 0 for 3×60s | Any task failing health checks for 3 minutes is a real problem (crash loop, dependency down). |
| `api-cpu-high` | ECS `CPUUtilization` | > 85% avg, 2×5min | Sustained CPU saturation → latency. Signal to scale or investigate. |
| `api-memory-high` | ECS `MemoryUtilization` | > 90% avg, 2×5min | Approaching the task memory limit → OOM kill risk. |
| `rds-cpu-high` | RDS `CPUUtilization` | > 85% avg, 2×5min | DB CPU saturation slows every request. |
| `rds-low-storage` | RDS `FreeStorageSpace` | < 2 GiB | Running out of disk → writes fail. Early warning to grow storage. |

Two flags worth understanding on every alarm:

- **`treat_missing_data = "notBreaching"`** — if a metric stops reporting (e.g.
  zero traffic so the ALB emits no 5xx datapoints), treat the gap as healthy, not
  as an alarm. Prevents false pages during idle periods.
- **`evaluation_periods`** — how many consecutive bad periods before firing. `1`
  for fast-moving signals (5xx, low storage), `2–3` for noisy gauges (CPU,
  unhealthy hosts) to avoid flapping on a momentary spike.

### Alarm state machine

```
        enough good data, under threshold
   ┌──────────────────────────────────────────┐
   ▼                                            │
 ┌──────┐  threshold breached N periods   ┌─────────┐
 │  OK  │ ──────────────────────────────► │  ALARM  │ ──► SNS (alarm_actions) ──► email
 └──────┘                                 └─────────┘
   ▲  │                                        │
   │  │ no data + treat_missing_data           │ recovers
   │  ▼                                        ▼
   │ ┌───────────────────┐    (back under threshold) ──► SNS (ok_actions) ──► email
   └─│ INSUFFICIENT_DATA │
     └───────────────────┘
```

## 2.4 The dashboard

One dashboard, `finsight-prod`, with four widgets (`cloudwatch.tf`):

```
┌───────────────────────────────┬───────────────────────────────┐
│ ALB — requests & 5xx (Sum)    │ API service — CPU / memory %   │
│ RequestCount, 5XX_Count       │ ECS CPUUtilization, Memory     │
├───────────────────────────────┼───────────────────────────────┤
│ RDS — CPU % & free storage    │ ALB — target response time p95 │
│ CPUUtilization, FreeStorage   │ TargetResponseTime (p95)       │
└───────────────────────────────┴───────────────────────────────┘
```

This is the "is it healthy right now?" glance: traffic + errors, app saturation,
DB saturation, and latency — the four questions you ask first during an incident.

## 2.5 Worked example — using observability to debug

The real incidents from this project map cleanly onto the tools:

| Incident | What the signal looked like | Tool that localised it |
|---|---|---|
| Chroma EC2 never mounted its volume | `ValueError: Could not connect to a Chroma server`; `embedding failed` with an httpcore connection-pool traceback | **Logs** — the traceback; then SSM + `cloud-init-output.log` on the host |
| Wrong OpenAI key in prod | `openai.AuthenticationError: 401 invalid_api_key` in the `rag_agent` task | **Logs** — the exception named the exact cause |
| Chat broken in prod only | `crypto.randomUUID is not a function` | **Browser console** (client-side, outside CloudWatch) |

Note the gap that example exposes: **client-side errors don't reach
CloudWatch**, and the Chroma host had **no status alarm**, so it sat broken until
a user noticed. See the next section.

## 2.6 Gaps & what to add next

- **Chroma instance health alarm** — there is no alarm on the Chroma EC2. Add a
  `StatusCheckFailed` alarm on the instance, and ideally an app-level metric or
  log-metric-filter on the API's "Could not connect to a Chroma server" so a
  Chroma outage pages instead of waiting for a user report.
- **Frontend / client error tracking** — `crypto.randomUUID` failed in the
  browser, invisible to CloudWatch. A client error reporter (e.g. Sentry) would
  have surfaced it immediately.
- **Log-based metric filters** — turn recurring error log lines (auth failures,
  embedding failures) into metrics with their own alarms.
- **Alarm routing beyond email** — SNS → a chat channel (Slack/PagerDuty) so
  alerts are seen out of hours.
- **Deploy notifications** — post the `deploy.yml` summary (app URL + image SHA)
  to a channel so the team knows what shipped.

---

## See also

- `docs/deployment/README.md` — the end-to-end deployment narrative, incl. the
  `min_healthy=100 / max=200` explanation.
- `docs/system-diagrams.md` §9–11 — deployment workflow, OIDC flow, and
  observability as diagrams.
- `docs/terraform-study-guide.md` — the resources behind all of the above,
  file by file, plus the AWS-services glossary (Appendix C).
