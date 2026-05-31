# FinSight Deployment — Weeks 5 → 8

This document records how FinSight goes from *source code on a laptop* to a
*running, self-deploying application on AWS*. It covers four project weeks:

| Week | Theme | Question it answers |
|---|---|---|
| **5** | **Containerization** (Docker) | "How do I package the app so it runs the same everywhere?" |
| **6** | **Cloud infrastructure** (Terraform) | "What AWS resources does it need to live on?" |
| **7** | **Container orchestration** (ECS Fargate + ALB) | "How do the containers actually run and receive traffic?" |
| **8** | **CI/CD + observability** (GitHub Actions + CloudWatch) | "How do I deploy a change automatically, and know it's healthy?" |

---

## The big picture

Four layers stack on top of each other. Each week builds one layer:

```
  Week 8  ┌─────────────────────────────────────────────┐
 AUTOMA-  │  GitHub Actions ships every push to main;    │
  TION    │  CloudWatch watches the running system       │
          └───────────────────┬─────────────────────────┘
  Week 7  ┌───────────────────┴─────────────────────────┐
ORCHESTRA-│  ECS Fargate runs the containers,            │
  TION    │  an ALB routes traffic to them               │
          └───────────────────┬─────────────────────────┘
  Week 6  ┌───────────────────┴─────────────────────────┐
  INFRA-  │  Terraform provisions the AWS resources      │
STRUCTURE │  (network, databases, registries, secrets)   │
          └───────────────────┬─────────────────────────┘
  Week 5  ┌───────────────────┴─────────────────────────┐
 CONTAIN- │  Docker packages the code into images        │
ERIZATION │  (one for the API, one for the frontend)     │
          └─────────────────────────────────────────────┘
```

Each layer depends on the one beneath it: you can't orchestrate containers (7)
without containers (5), can't run them on AWS (7) without infrastructure (6),
and can't automate the deploy (8) until there's a deploy to automate.

---

# Week 5 — Containerization (Docker)

**Goal:** turn the two codebases (Python backend, Next.js frontend) into
**Docker images** — self-contained, runs-anywhere bundles of code + runtime +
dependencies — and provide a one-command local stack.

## Why containers at all

The app depends on a specific Python version, `torch`, a 300 MB ML model,
Postgres, Redis, ChromaDB. "Works on my machine" is not a deployment strategy.
A Docker **image** freezes all of that into one artifact; whatever runs the
image — your laptop, a teammate's, or AWS Fargate — gets a byte-identical
environment.

## 5.1 The API image — `Dockerfile` (repo root)

A **multi-stage build**: a fat *builder* stage compiles everything, a lean
*runtime* stage keeps only what's needed to run. The final image never ships
`gcc` or build headers.

```
┌─ builder (python:3.12-slim) ────────────────┐
│  • apt: build-essential, gcc                │
│  • python venv at /opt/venv                 │
│  • pip install CPU-only torch  ◄── see note │
│  • pip install -r requirements.txt          │
│  • pre-download the reranker model          │
└──────────────────┬──────────────────────────┘
                   │ COPY --from=builder
┌─ runtime (python:3.12-slim) ────────────────┐
│  • apt: curl, libpq5  (runtime libs only)   │
│  • copy /opt/venv and /opt/hf-cache         │
│  • copy app code, run as non-root `app`     │
│  • HEALTHCHECK on /health                   │
│  • CMD uvicorn api.main:app :8000           │
└─────────────────────────────────────────────┘
```

Three decisions worth understanding:

- **CPU-only `torch`.** Installed *before* `requirements.txt`. If left to
  resolve normally, `sentence-transformers` would pull the default CUDA
  `torch` wheel (~2 GB) — useless, because Fargate has no GPU. Installing the
  CPU wheel first satisfies the dependency, so the rest resolves against it.
- **The reranker model is baked into the image.** The build runs
  `CrossEncoder('Alibaba-NLP/gte-reranker-modernbert-base', …)` so the ~300 MB
  weights live *inside* the image (`HF_HOME=/opt/hf-cache`). At runtime
  `HF_HUB_OFFLINE=1` forbids network downloads. Without this, the **first
  `/analyze` on every new container** would block on a 300 MB download — fatal
  for autoscaling cold starts, where new tasks must be useful immediately.
- **Non-root user.** The runtime stage creates a system user `app` and runs as
  it — a container best practice, so a process escape doesn't land as root.

A `HEALTHCHECK` curls `/health` every 30s; ECS and the ALB both use it to
decide whether a task is alive.

## 5.2 The frontend image — `frontend/Dockerfile`

Also multi-stage — `deps` → `builder` → `runner` — built on `node:20-alpine`.

The one subtlety is **`NEXT_PUBLIC_API_URL`**. Next.js *inlines* any
`NEXT_PUBLIC_*` variable into the JavaScript bundle at **build time** — it
becomes a literal string in the compiled output. It therefore cannot be
changed by a runtime environment variable. The Dockerfile takes it as a
**build arg**:

```dockerfile
ARG NEXT_PUBLIC_API_URL=http://localhost:8000
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
RUN npm run build
```

Consequence: the frontend image must be **rebuilt for each environment** with
the right URL — `localhost` for local, the ALB hostname for AWS. This is why
`deploy.sh` passes `--build-arg NEXT_PUBLIC_API_URL=<alb-url>` (Week 7).

The `runner` stage copies only Next's **standalone output** (`server.js` plus
the minimal subset of `node_modules` it actually uses) — a much smaller image
than shipping the whole `node_modules`.

## 5.3 The local full stack — `docker/docker-compose.yml`

`docker-compose.yml` wires five services into one command for local
development:

| Service | Image | Host port | Purpose |
|---|---|---|---|
| `postgres` | `postgres:16-alpine` | 5433 | Relational store |
| `redis` | `redis:7-alpine` | 6379 | Cache |
| `chromadb` | `chromadb/chroma:latest` | 8100 | Vector store |
| `app` | built from `Dockerfile` | 8000 | FastAPI + LangGraph |
| `frontend` | built from `frontend/Dockerfile` | 3000 | Next.js |

`depends_on` + `healthcheck` enforce start order: `app` waits until Postgres,
Redis, and ChromaDB are *healthy*, and `frontend` waits for `app`. The `app`
service runs `alembic upgrade head` before `uvicorn` — fine locally with one
container; in AWS this becomes a separate task (see Week 7).

This compose file mirrors the AWS topology so that "it works in
`docker compose up`" is strong evidence it will work on ECS.

## 5.4 What does *not* go in the image — `.dockerignore`

`.dockerignore` keeps the build context (and the image) lean and clean. It
excludes `.git`, `.venv`, `__pycache__`, `tests`, `docs`/`Docs`, `mlruns`,
`mlflow.db`, **`chroma_data`**, `.env*`, `.claude`, `.github`, and a stray
credentials CSV.

Two of these matter for correctness, not just size:

- **`.env*`** — secrets never enter an image. They're injected at runtime
  (Secrets Manager on AWS — Week 6).
- **`chroma_data`** — your *local* vector data is excluded, so test embeddings
  never leak into a production image. Production starts with an empty store.

## Week 5 — summary

| Decision | Why |
|---|---|
| Multi-stage builds | Small runtime images; no compilers shipped |
| CPU-only torch | No GPU on Fargate; avoids a 2 GB wasted download |
| Reranker baked into image | Cold-start tasks must be instantly useful |
| `NEXT_PUBLIC_API_URL` as build arg | Next.js inlines it at build time |
| Non-root container user | Reduces blast radius of a compromise |
| `.dockerignore` excludes `.env`, `chroma_data` | No secrets, no test data in images |

---

# Week 6 — Cloud infrastructure (Terraform)

**Goal:** describe every AWS resource the app needs as code, so the whole
environment can be created, inspected, and destroyed reproducibly.

## What Terraform is, briefly

Terraform is **infrastructure as code**. You declare the *desired state* of
your cloud ("a VPC, a database, two registries…") in `.tf` files; Terraform
diffs that against reality and makes the API calls to converge. The recorded
reality lives in a **state file** (`terraform.tfstate`). The loop is:

```
terraform init   → download the AWS provider
terraform plan   → preview the diff (read-only, free, changes nothing)
terraform apply  → make it real (this is when billing starts)
terraform destroy→ tear it all down
```

Everything for Week 6 lives in `infra/terraform/`. Terraform loads **all
`.tf` files in the directory as one configuration** — the split is purely for
human readability.

## 6.1 The files

| File | Provisions |
|---|---|
| `versions.tf` | Required Terraform + AWS provider versions |
| `providers.tf` | AWS provider; tags every resource `Project`/`Environment` |
| `variables.tf` | All inputs and defaults (region, instance sizes, secrets) |
| `locals.tf` | The `finsight-prod` name prefix; availability-zone lookup |
| `vpc.tf` | VPC, 2 public + 2 private subnets, internet + NAT gateways |
| `security_groups.tf` | The firewall chain (see 6.3) |
| `ecr.tf` | Two Docker image registries (API, frontend) |
| `rds.tf` | PostgreSQL 16 database |
| `elasticache.tf` | Redis 7 cache |
| `secrets.tf` | Secrets Manager entries (API keys, JWT, DB connection string) |
| `iam.tf` | Permission roles for ECS tasks and the Chroma host |
| `chroma.tf` + `chroma_user_data.sh.tftpl` | ChromaDB EC2 instance + EBS volume + boot script |
| `outputs.tf` | Values printed after `apply` (endpoints, URLs, names) |
| `terraform.tfvars.example` | Template for your secret values |

## 6.2 Network topology — `vpc.tf`

A single VPC, `10.0.0.0/16`, spanning two availability zones:

```
            Internet
               │
        ┌──────┴──────┐  Internet Gateway
   ┌────┴────┐   ┌─────┴───┐   PUBLIC subnets (10.0.1.0/24, 10.0.2.0/24)
   │   ALB   │   │  NAT GW │   • ALB
   └────┬────┘   └────┬────┘   • NAT gateway
        │             │        • Chroma EC2 host
   ┌────┴─────────────┴──────┐
   │   PRIVATE subnets       │  PRIVATE subnets (10.0.3.0/24, 10.0.4.0/24)
   │   ECS tasks, RDS, Redis │  • ECS Fargate tasks
   └─────────────────────────┘  • RDS, ElastiCache
```

- **Public subnets** hold things that face the internet (the ALB) or need a
  routable path out (the NAT gateway).
- **Private subnets** hold everything else. ECS tasks, RDS, and Redis have
  **no public IP** — they're unreachable from the internet directly.
- The **NAT gateway** lets private resources make *outbound* calls (pull
  images from ECR, reach the Anthropic/OpenAI APIs) while remaining
  *inbound*-unreachable.

Portfolio-grade choice: **one NAT gateway** (not one per AZ). A NAT gateway is
~$32/month, so one instead of two roughly halves the biggest fixed cost. A
production build would run one per AZ for fault tolerance.

## 6.3 The security-group chain — `security_groups.tf`

Security groups are stateful firewalls. They're chained so each tier accepts
traffic **only from the tier in front of it**:

```
internet ──:80──▶ alb ──:8000──▶ ecs_api ──┬──:5432──▶ rds
                      ──:3000──▶ ecs_frontend │
                                              ├──:6379──▶ redis
                                              └──:8000──▶ chroma
```

- `alb` — the **only** group open to the internet (port 80).
- `ecs_api` / `ecs_frontend` — accept traffic only from the ALB's security
  group, on 8000 / 3000.
- `rds`, `redis`, `chroma` — accept traffic only from `ecs_api`.

There is no path from the internet to the database. To reach Postgres you must
go through the ALB, into a task, and out from there.

## 6.4 Databases — `rds.tf`, `elasticache.tf`, `chroma.tf`

Three data stores, three hosting models:

| Store | Service | Why this model |
|---|---|---|
| Postgres 16 | **RDS** (managed) | AWS handles patching, the engine, networking |
| Redis 7 | **ElastiCache** (managed) | Same — fully managed cache |
| ChromaDB | **EC2 + EBS** (self-managed) | No managed ChromaDB exists on AWS |

ChromaDB has no AWS-managed equivalent, so `chroma.tf` launches a dedicated
**EC2 instance** (`t3.small`) with a separate **EBS volume** for persistence.
`chroma_user_data.sh.tftpl` is the boot script — it installs Docker and runs
the `chromadb/chroma` container, mounting the EBS volume so vector data
survives an instance replacement.

Portfolio-grade choices: RDS is **single-AZ** with **automated backups off**
(`backup_retention_period = 0`) — a free-tier-account restriction and a cost
saving. Production would flip `multi_az = true` and raise retention.

## 6.5 Secrets — `secrets.tf`

Every sensitive value lives in **AWS Secrets Manager**, never in an image or a
committed file. Nine secrets:

```
finsight-prod/claude-api-key          finsight-prod/massive-api-key
finsight-prod/openai-api-key          finsight-prod/twelvedata-api-key
finsight-prod/alpha-vantage-api-key   finsight-prod/eodhd-api-key
finsight-prod/jwt-secret-key          finsight-prod/tiingo-api-key
finsight-prod/database-url
```

`database-url` is *assembled* by Terraform from the RDS endpoint + credentials
— so the app gets a complete async DSN without anyone hand-typing it. Optional
keys (Alpha Vantage, the four fallback data providers) are `coalesce`d to a
placeholder when blank, because Secrets Manager rejects an empty value.

You supply the real values once, in `terraform.tfvars` (gitignored). The ECS
task definitions reference each secret **by ARN** (Week 7) — the value itself
never appears in a task definition or an image.

## 6.6 Permissions — `iam.tf`

Two IAM roles for ECS, because they do different jobs:

- **Execution role** — used by the *ECS agent* to start a task: pull the image
  from ECR, fetch secrets from Secrets Manager, write logs to CloudWatch.
- **Task role** — used by the *application code* inside the container for any
  AWS calls it makes itself.

Plus an instance profile for the Chroma EC2 host (so it can be managed via SSM
without SSH keys).

## Week 6 — summary

After `terraform apply`, AWS holds: a VPC with public/private subnets and a
NAT gateway, a firewall chain, two empty ECR registries, an empty Postgres
database, a Redis cache, a ChromaDB host, nine secrets, and the IAM roles —
**but nothing is running the application yet.** That is Week 7.

---

# Week 7 — Container orchestration (ECS Fargate + ALB)

**Goal:** actually *run* the Week 5 container images on the Week 6
infrastructure, and route internet traffic to them.

## What ECS Fargate is

**ECS** (Elastic Container Service) is AWS's container scheduler. **Fargate**
is the "serverless" mode — you specify CPU/memory and an image; AWS finds the
hardware, places the container, and replaces it if it dies. There are no EC2
servers for you to patch. Three concepts:

- **Task definition** — the *blueprint* for a container (image, CPU, memory,
  env vars, secrets, ports). Like a class.
- **Task** — one *running instance* of a task definition. Like an object.
- **Service** — a controller that keeps *N* tasks of a definition running,
  replaces unhealthy ones, and registers them with the load balancer.

## 7.1 Task definitions — `task_definitions.tf`

Three blueprints:

| Task def | CPU / Mem | Lifetime | Command |
|---|---|---|---|
| `api` | 1024 / 4096 | long-running | `uvicorn …` (image default) |
| `frontend` | 256 / 512 | long-running | `node server.js` (image default) |
| `migrate` | 256 / 512 | **one-shot** | `alembic upgrade head` |

- The **API** gets 1 vCPU / 4 GB — it must hold `torch` plus the in-memory
  reranker model.
- **Secrets** are injected via the `secrets` block (`valueFrom` an ARN). ECS
  resolves the ARN at launch; the value never sits in the definition.
- Non-secret config is plain `environment` — including
  **`SCHEDULER_ENABLED=false`**: the in-app APScheduler is disabled in AWS
  because with several autoscaled API tasks, each would fire the same
  refresh. Scheduled ingestion belongs on EventBridge instead.
- The **`migrate`** task reuses the *API image* but overrides the command. It
  runs `alembic upgrade head` **once per deploy** and exits. Keeping
  migrations in their own task means N autoscaled API tasks never race to
  migrate the same database — the schema change happens exactly once, off the
  critical path.

## 7.2 Services — `ecs.tf`

Two long-running services:

- **`api`** — baseline 1 task, in the private subnets, registered with the API
  target group. A 120-second health-check grace period covers the slow
  boot (loading the reranker).
- **`frontend`** — 1 task, private subnets, registered with the frontend
  target group.

Both deploy with `minimum_healthy_percent = 100` / `maximum_percent = 200` —
a rolling update that starts the new task and only then drains the old one, so
capacity never dips.

**Autoscaling** (API only): a target-tracking policy holds average CPU at
**60%**, scaling between **1 and 3 tasks**. Scale-out is quick (60s cooldown),
scale-in is cautious (300s) to avoid flapping. `desired_count` is then owned
by autoscaling, so Terraform `ignore_changes` it.

## 7.3 The load balancer — `alb.tf`

One internet-facing **Application Load Balancer** fronts both services on a
**single hostname**, split by URL path:

```
                       http://<alb-dns-name>/
                                │
                   ┌────────────┴────────────┐
   path matches one of:                  everything else
   /analyze* /report* /ticker*                │
   /history* /conversations*                  │
   /auth* /health* /docs* /openapi.json        │
            │                                  │
            ▼                                  ▼
     API target group  (:8000)         frontend target group (:3000)
            │                                  │
       ECS api tasks                     ECS frontend tasks
```

- The HTTP:80 listener's **default action** forwards to the frontend.
- **Two listener rules** peel the API paths off to the API target group. (Two,
  not one, because AWS caps a rule at 5 path-pattern values and there are 9
  prefixes.)
- Fargate tasks register **by IP** (`target_type = "ip"`) because `awsvpc`
  networking gives each task its own ENI.

Because the frontend and the API share one hostname, the browser loads the UI
and calls the API as the **same origin** — no CORS configuration, no second
domain. The ALB is **HTTP-only** (portfolio-grade); HTTPS would need a domain
and an ACM certificate.

## 7.4 Why the services are empty right after `apply`

`terraform apply` creates the *services* and two *empty ECR registries*. A
service wants to run a task, a task needs an image, and the registries have
none — so the services sit at **0 healthy tasks**. **This is expected**, not a
failure. You then run the post-apply sequence, automated by
`infra/scripts/deploy.sh`:

```
1. docker login to ECR
2. build + push the API image
3. build + push the frontend image  (NEXT_PUBLIC_API_URL = ALB url)
4. run the `migrate` task once       → creates the DB tables
5. force-redeploy both services      → they pull the images, go healthy
```

`deploy.sh` deals only with **code** (images) and **schema** (the migration).
It moves **no data** — production RDS, ChromaDB, and Redis all start empty. See
`infra/terraform/terraform.md` for the full command-by-command walkthrough.

## Week 7 — summary

| Piece | Role |
|---|---|
| ECS cluster | Logical home for the services |
| `api` / `frontend` services | Keep the containers running, self-heal |
| `migrate` task | One-shot `alembic upgrade head` per deploy |
| ALB + 2 listener rules | One hostname, path-routed to API vs frontend |
| API autoscaling | 1→3 tasks, target 60% CPU |
| `deploy.sh` | Builds, pushes, migrates, rolls — the post-apply sequence |

---

# Week 8 — CI/CD + observability

**Goal:** stop deploying by hand. After Weeks 5–7 a deploy is two manual
commands (`terraform apply`, then `./infra/scripts/deploy.sh`). Week 8 turns
the *application* deploy into a `git push`, and adds the monitoring needed to
know the running system is healthy.

Two concerns, two halves:

- **CI/CD** — GitHub Actions workflows that test every change and deploy every
  push to `main`.
- **Observability** — CloudWatch alarms and a dashboard, so problems surface
  without anyone watching logs.

## What CI and CD mean

- **CI — Continuous Integration.** On *every* change, automatically build and
  test it, so breakage is caught before it merges. CI touches no
  infrastructure — it only needs the code.
- **CD — Continuous Deployment.** On every change that lands on `main`,
  automatically ship it to production.

FinSight splits these into two workflow files in `.github/workflows/`. A
GitHub Actions **workflow** is a YAML file describing **jobs** (groups of
steps) that run on a fresh virtual machine — a **runner** — when a **trigger**
fires (a push, a pull request, a button).

| File | Trigger | What it does |
|---|---|---|
| `ci.yml` | pull requests, non-`main` pushes | lint + test backend & frontend |
| `deploy.yml` | push to `main`, manual dispatch | test, then build → push → migrate → roll |

A change's lifecycle: branch, push, open a PR → `ci.yml` runs and must be
green → merge to `main` → `deploy.yml` runs and ships it.

## 8.1 The authentication problem — and OIDC

For `deploy.yml` to touch AWS (push images, run tasks) it must
**authenticate**. The obvious way is to create an IAM user, generate an access
key + secret, and paste them into GitHub as secrets. That works, but those
credentials are **long-lived** (valid until you manually rotate them) and
**stored** (they sit in GitHub; a repo compromise leaks a real, working AWS
key). FinSight uses **OIDC federation** instead — *no stored AWS credentials at
all.*

### What OIDC is

OIDC (OpenID Connect) is a standard way for one system to **vouch for an
identity** to another. GitHub runs an **OIDC provider**: for any workflow run,
it can mint a short-lived, cryptographically-signed **token** that asserts
facts — "this run is from repo `owner/finsight`, branch `main`, commit `abc…`".

AWS is told, once, to **trust** GitHub's OIDC provider. A workflow can then
hand AWS that GitHub token and ask for credentials; AWS verifies the signature,
checks the asserted facts against a **trust policy**, and — if they match —
issues **temporary** credentials (good for ~1 hour) for one specific IAM role.

### The exchange, step by step

```
1. deploy.yml starts.  GitHub mints an OIDC token describing this run
   (repository, branch, commit) and signs it.
2. The workflow calls AWS STS:  "here is my GitHub token —
   let me assume role finsight-prod-github-actions."
3. AWS checks:
     • is the token signed by the trusted GitHub OIDC provider?    ✓
     • does the token's `sub` claim satisfy the role's trust-policy
       condition  repo:<owner>/<repo>:*  ?                         ✓
4. AWS returns temporary credentials (~1 hour, then dead).
5. The workflow uses them for the rest of the run. Nothing is stored.
```

The result: **no AWS secret ever exists in GitHub.** A leaked repository
exposes no usable credential — a token is only mintable by a real workflow run,
expires within an hour, and is accepted only for your one repository.

### What Terraform sets up — `github_oidc.tf`

- `aws_iam_openid_connect_provider.github` — registers GitHub's OIDC issuer as
  trusted in your AWS account. One per account.
- `aws_iam_role.github_actions` — the role the workflow assumes. Its **trust
  policy** is the gate: it accepts a token only if the audience is
  `sts.amazonaws.com` *and* the `sub` claim matches `repo:<github_repo>:*` —
  i.e. **only your repository**, no one else's.
- An attached **permissions policy**, deliberately minimal: push to the two ECR
  repos, run/update ECS tasks & services, `iam:PassRole` for *exactly* the two
  ECS roles, and read-only describe calls (ALB DNS, subnets, security group).
  It cannot touch RDS, read application secrets, or alter the network.

The `github_repo` value (`owner/repo`) you set in `terraform.tfvars` is what
scopes that trust — set it wrong and the workflow simply can't assume the role.

## 8.2 `ci.yml` — test on every change

Runs on every pull request and every push to a non-`main` branch. Two jobs run
in parallel:

- **backend** — sets up Python 3.12, installs CPU-only torch + dev
  dependencies, runs `ruff` (lint) and `pytest tests/unit/`.
- **frontend** — sets up Node 20, runs `npm ci`, `npm run lint`, `npm run
  build`. The build step is exactly what catches errors like the
  `useSearchParams`/Suspense bug before they ever reach `main`.

`ci.yml` never authenticates to AWS — integration testing only needs the code.

## 8.3 `deploy.yml` — ship on every push to main

Runs on every push to `main` (and on demand via a manual "Run workflow" button
— the `workflow_dispatch` trigger). It is the automated form of `deploy.sh`.
Two jobs, the second **gated** on the first:

```
job: test       ──(must pass)──▶   job: deploy
runs the unit tests                OIDC → build → push → migrate → roll
```

`deploy` does not start unless `test` is green — broken code that reaches
`main` is caught, and never shipped.

The `deploy` job, step by step — compare it with the §7 `deploy.sh` sequence:
it is the *same five actions*, just run by a robot.

| Step | What it does |
|---|---|
| Configure AWS credentials | the OIDC exchange (8.1) → temporary creds |
| Log in to ECR | Docker authenticates, using the temp creds |
| Resolve infra values | `aws` describe calls find the ALB DNS, subnets, SG |
| Build & push API image | tagged both `latest` *and* the git commit SHA |
| Build & push frontend image | `--build-arg NEXT_PUBLIC_API_URL=<alb-url>` |
| Run DB migration | `aws ecs run-task` on `migrate`, wait, check exit code |
| Roll ECS services | `--force-new-deployment`, then wait for stable |

Two safety details worth understanding:

- **`concurrency: deploy-production`** — if two pushes land close together,
  GitHub queues the second deploy rather than running both at once, so two
  deploys can never fight over the same services.
- **Image tags** — every image is pushed as both `latest` (the tag the task
  definition references) and `:<git-sha>` (an *immutable* record of exactly
  what shipped — so any past deploy can be identified, and rolled back to).

### The deploy-time flow

```
git push origin main
       │
       ▼
GitHub Actions ── job: test ──▶ pytest unit tests   (gate — must pass)
       │
       ▼  job: deploy
  OIDC: GitHub token ──▶ AWS STS ──▶ temporary credentials
       │
       ├─▶ docker build / push   ──▶  ECR  (api + frontend repos)
       ├─▶ ecs run-task migrate  ──▶  RDS  (alembic upgrade head)
       └─▶ ecs update-service    ──▶  ECS pulls new images, rolls tasks
                                            │
                                            ▼
                                   new version live behind the ALB
```

### One-time GitHub setup

The OIDC exchange needs the role ARN known to GitHub. After the first
`terraform apply`:

1. Read the ARN: `terraform output -raw github_actions_role_arn`
2. In the GitHub repo: **Settings → Secrets and variables → Actions →
   Variables** → new **variable** named `AWS_DEPLOY_ROLE_ARN`, value = that ARN.

It is a *variable*, not a secret — an ARN merely *names* the role; it grants
nothing without a valid OIDC token. This is the only manual wiring; after it,
`git push` to `main` deploys.

## 8.4 Observability — `cloudwatch.tf`

A deploy that succeeds is not the end — you need to know the *running* system
stays healthy. Three layers, in increasing usefulness:

**Logs** (already created in Week 7). Each ECS service streams its container
stdout/stderr to a CloudWatch **log group** — `/ecs/finsight-prod/api` and
`/ecs/finsight-prod/frontend`. The `migrate` task logs there too, under a
`migrate` stream prefix. Logs answer *"what happened?"* — but only if you go
look.

**Alarms.** `cloudwatch.tf` defines **metric alarms** — each watches one metric
and trips when it crosses a threshold for long enough:

| Alarm | Trips when | Why it matters |
|---|---|---|
| `alb-5xx` | ALB returns >5 server errors in 5 min | users are seeing failures |
| `api-unhealthy-hosts` | an API task fails ALB health checks | a task is broken |
| `api-cpu-high` | API CPU >85% for 10 min | undersized or overloaded |
| `api-memory-high` | API memory >90% for 10 min | risk of an out-of-memory kill |
| `rds-cpu-high` | DB CPU >85% for 10 min | slow queries / undersized DB |
| `rds-low-storage` | DB free storage <2 GiB | the disk is about to fill |

Every alarm publishes to an **SNS topic** (`finsight-prod-alerts`). SNS (Simple
Notification Service) is a fan-out notifier: set `alarm_email` in
`terraform.tfvars` and you receive an email whenever an alarm trips — you just
confirm the AWS subscription link once. Alarms answer *"is something wrong
**now**?"* without anyone watching.

**Dashboard.** `aws_cloudwatch_dashboard.main` is a single pane of glass — ALB
request count & 5xx, API CPU/memory, RDS CPU/storage, ALB p95 latency. Open it
with `terraform output cloudwatch_dashboard_url`. It answers *"how is the
system **trending**?"*

The progression is the point: **logs** tell you what happened, **alarms** tell
you something is wrong right now, the **dashboard** shows you the trend.

## Week 8 — summary

| Piece | Role |
|---|---|
| `ci.yml` | Lint + test every pull request and branch push |
| `deploy.yml` | Test, then auto-deploy every push to `main` |
| OIDC provider + role | GitHub authenticates to AWS with **no stored keys** |
| `concurrency` + SHA tags | No overlapping deploys; every image is traceable |
| CloudWatch alarms + SNS | Get *told* when something breaks |
| CloudWatch dashboard | One-glance health of the running stack |

After Week 8 the full loop is automatic: **push to `main` → tests run → images
build → DB migrates → services roll → alarms watch the result.** No terminal.

---

## How a production request flows (the running system)

```
Browser
  │  GET http://<alb-dns>/                     ← path doesn't match API rules
  ▼
ALB ──▶ frontend target group ──▶ ECS frontend task (Next.js, :3000)
  │
  │  Browser then calls POST http://<alb-dns>/analyze
  ▼
ALB ──▶ (matches /analyze*) ──▶ API target group ──▶ ECS api task (:8000)
                                         │
        ┌────────────────────────────────┼─────────────────────────┐
        ▼                ▼                ▼               ▼          ▼
    RDS Postgres   ElastiCache Redis  Chroma EC2   Secrets Manager  Anthropic /
    (private)      (private)          (private)    (keys at launch)  OpenAI APIs
                                                                     (out via NAT)
```

Everything except the ALB sits in private subnets; the only inbound door is
the ALB on port 80, and outbound calls to Anthropic/OpenAI leave through the
NAT gateway.

## Cost (rough, `eu-central-1`, stack left running)

| Resource | ~ Monthly |
|---|---|
| NAT gateway | $32 + data |
| ALB | $16 + LCU |
| RDS `db.t3.micro` | $13 |
| ElastiCache `cache.t3.micro` | $12 |
| Chroma EC2 `t3.small` + 8 GB EBS | $16 |
| Fargate (1 API + 1 frontend) | $35 |
| **Total** | **~$120–140** |

`terraform destroy` removes all of it; `recovery_window_in_days = 0` on the
secrets frees their names immediately for a clean recreate.

Week 8 adds **almost nothing** to this bill: CloudWatch alarms, the dashboard,
and the SNS topic cost cents at this scale, and GitHub Actions is free for a
public repository (and generous for private ones). CI/CD is essentially free
insurance.

## What's next — beyond Week 8

The stack is now complete and self-deploying. The remaining items are
production hardening — none required for a portfolio demo, all layerable later:

- **HTTPS** — the ALB is HTTP-only. Real TLS needs a domain you control: an ACM
  certificate, a `443` listener with the same path rules, and a Route 53
  record pointing at the ALB.
- **Scheduled ingestion** — `SCHEDULER_ENABLED=false` in AWS (8.1 of Week 7's
  reasoning). Move the periodic data refresh to an **EventBridge** rule that
  triggers a dedicated ECS task, instead of the in-app scheduler.
- **High availability** — flip RDS to `multi_az`, run one NAT gateway per AZ,
  and raise the Fargate minimum above a single task.
- **Remote Terraform state** — move `terraform.tfstate` to the S3 backend
  (already scaffolded in `versions.tf`) so the state is not tied to one laptop
  and a teammate can also run `apply`.
