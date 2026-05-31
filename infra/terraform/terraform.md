# FinSight infrastructure (Terraform)

This directory provisions FinSight's entire AWS deployment **as code**. If
you're new to Terraform, read the next two sections first — they explain
enough to operate this confidently.

---

## 1. What is Terraform, in one minute

Terraform is **infrastructure as code**. Instead of clicking around the AWS
console to create a database, a network, servers, etc., you *describe* what you
want in `.tf` files, and Terraform creates it for you — repeatably, and in the
right order.

You work with five ideas:

| Concept | What it is | Example here |
|---|---|---|
| **Provider** | A plugin that knows how to talk to a cloud. We use the AWS provider. | `providers.tf` |
| **Resource** | One piece of real infrastructure. | `resource "aws_vpc" "main"` → a VPC |
| **Data source** | A *read-only* lookup of something that already exists. | `data "aws_ami"` → finds the latest Amazon Linux image |
| **Variable** | An input you can set (region, sizes, secrets). | `variables.tf`, filled by `terraform.tfvars` |
| **Output** | A value Terraform prints after building (e.g. the database address). | `outputs.tf` |

**It's declarative.** You don't write "create this, then that". You describe
the desired end state; Terraform compares it to what already exists and works
out the minimal set of changes. Run it twice with no edits → the second run
does nothing ("no changes"). That property is called *idempotence*.

**It figures out order automatically.** When `rds.tf` references
`aws_security_group.rds.id`, Terraform knows the security group must exist
first. You never sequence things by hand.

### The core workflow

```
terraform init      → download the AWS provider plugin (run once per machine)
terraform plan      → preview: what would change? (read-only, safe)
terraform apply     → actually create/update the infrastructure
terraform destroy   → tear it all down
```

You will run `plan` constantly — it's your safety net. Nothing changes in AWS
until you `apply` and type `yes`.

### State — the most important concept

Terraform records everything it created in a file called **`terraform.tfstate`**.
This file is the link between your `.tf` code and the real AWS resources. When
you run `plan`, Terraform compares three things: your code, the state file, and
the live AWS reality.

- **Never delete `terraform.tfstate`** — if you do, Terraform forgets it owns
  those resources and would try to create duplicates.
- **Never commit it to git** — it can contain secrets. It is already gitignored.
- Here, state is a **local file** in this directory. That's fine for one
  person. For a team you'd move it to an S3 bucket (see `versions.tf`).

---

## 2. The architecture this builds

```
Route53 (optional) ─► ALB ─┬─► frontend  (ECS Fargate)        [Week 7]
                           └─► api       (ECS Fargate)        [Week 7]
                                  │
   private subnets ───────────────┼──────────────────────────────────
     api tasks ─► RDS Postgres  (single-AZ)                   [Week 6]
              ─► ElastiCache Redis                            [Week 6]
              ─► ChromaDB        (dedicated EC2 + EBS)        [Week 6]
              ─► Anthropic / OpenAI / SEC EDGAR  (via NAT)
```

**Portfolio-grade** sizing: single-AZ RDS, one NAT gateway, small instances —
roughly **$70–120/month** while running. A production build would add
multi-AZ failover and a NAT gateway per availability zone.

The network has two tiers:
- **Public subnets** — only the load balancer and NAT gateway. Reachable from
  the internet.
- **Private subnets** — the database, cache, Chroma, and the app containers.
  *No* inbound internet access; they reach out (to call Anthropic/OpenAI/SEC)
  through the NAT gateway. This is the standard "don't expose your database"
  pattern.

---

## 3. File map

Terraform loads **every `.tf` file in this directory** and treats them as one
configuration — the split is purely for human readability.

| File | What it defines |
|---|---|
| `versions.tf` | Required Terraform + provider versions; the (optional) S3 state backend |
| `providers.tf` | AWS provider config; tags every resource with `Project`/`Environment` |
| `variables.tf` | All inputs and their defaults |
| `locals.tf` | The `${project}-${env}` name prefix; the availability-zone lookup |
| `vpc.tf` | VPC, 2 public + 2 private subnets, internet gateway, NAT gateway, routing |
| `security_groups.tf` | Firewall rules — the `internet → alb → ecs → rds/redis/chroma` chain |
| `ecr.tf` | Docker image registries for the API and frontend images |
| `rds.tf` | PostgreSQL 16 database |
| `elasticache.tf` | Redis cache |
| `secrets.tf` | Secrets Manager entries (API keys, JWT secret, DB connection string) |
| `iam.tf` | Permission roles for ECS and the Chroma EC2 host |
| `chroma.tf` | The ChromaDB EC2 instance + its persistent EBS data volume |
| `chroma_user_data.sh.tftpl` | Boot script for that instance (installs Docker, runs Chroma) |
| `alb.tf` | Application Load Balancer, target groups, path-based routing |
| `ecs.tf` | ECS cluster, the API + frontend services, log groups, API autoscaling |
| `task_definitions.tf` | Container blueprints — `api`, `frontend`, one-shot `migrate` |
| `github_oidc.tf` | OIDC provider + IAM role GitHub Actions assumes to deploy |
| `cloudwatch.tf` | SNS alert topic, metric alarms, the monitoring dashboard |
| `outputs.tf` | Values printed after `apply` (endpoints, registry URLs, …) |
| `terraform.tfvars.example` | Template for your secrets — copy it to `terraform.tfvars` |

Two things live alongside, outside this directory:

| File | What it does |
|---|---|
| `../scripts/deploy.sh` | Post-`apply` deploy by hand: builds + pushes both images, runs the DB migration, rolls the ECS services. See §6. |
| `../../.github/workflows/` | `ci.yml` (test on PRs) + `deploy.yml` (auto-deploy on push to main). See §8. |

---

## 4. Prerequisites

### a. Install Terraform

Get it from [terraform.io/downloads](https://developer.hashicorp.com/terraform/downloads),
then verify:

```bash
terraform version      # need >= 1.6
```

### b. An AWS account

You need an AWS account. The resources here are **not** all free-tier — see the
cost note in §2. Set a billing alarm.

### c. AWS credentials

Terraform's AWS provider needs credentials. The simplest way: install the AWS
CLI and run `aws configure`, which writes them to `~/.aws/credentials`:

```bash
aws configure
#   AWS Access Key ID:     <from an IAM user with programmatic access>
#   AWS Secret Access Key: <...>
#   Default region name:   eu-central-1
#   Default output format: json

aws sts get-caller-identity   # verify — should print your account id
```

Terraform picks these up automatically; you don't reference them in any `.tf`
file. The IAM user needs permission to create the resources (for a learning
project, `AdministratorAccess` is simplest; tighten later).

---

## 5. Configure your deployment

All inputs live in `variables.tf` with sensible defaults. You only *must*
provide the secrets. Copy the template:

```bash
cp terraform.tfvars.example terraform.tfvars
```

Then edit `terraform.tfvars`:

```hcl
db_password       = "a-strong-password"
anthropic_api_key = "sk-ant-..."
openai_api_key    = "sk-..."
jwt_secret_key    = "a-long-random-string"
alpha_vantage_api_key = ""        # optional
```

- **`terraform.tfvars` is gitignored** — your real secrets never get committed.
- Anything in `variables.tf` can be overridden here too — e.g. `aws_region`,
  `db_instance_class`. The default region is `eu-central-1`.
- The secrets you put here are uploaded into **AWS Secrets Manager**; the app
  containers read them from there at runtime (Week 7). They are never baked
  into a Docker image.

---

## 6. Deploy it

```bash
cd infra/terraform
```

**Step 1 — initialise** (downloads the AWS provider; run once):

```bash
terraform init
```

**Step 2 — preview** (read-only — changes nothing):

```bash
terraform plan
```

Read the output. Every line is `+ create`, `~ update`, or `- destroy`. The
first time, you'll see `Plan: ~30 to add, 0 to change, 0 to destroy`. If you
ever see unexpected `destroy` lines, stop and investigate.

**Step 3 — apply** (this is when AWS resources — and billing — actually start):

```bash
terraform apply
```

It shows the plan again and asks you to type `yes`. Expect it to take
**~10–15 minutes** — the RDS database and NAT gateway are slow to provision.
When it finishes you'll see the `outputs.tf` values:

```
ecr_api_repository_url = "....dkr.ecr.eu-central-1.amazonaws.com/finsight-prod-api"
rds_endpoint           = "finsight-prod-postgres.xxxx.eu-central-1.rds.amazonaws.com:5432"
chroma_private_ip      = "10.0.3.x"
application_url        = "http://finsight-prod-alb-xxxx.eu-central-1.elb.amazonaws.com"
...
```

### After the first apply — push images & run the migration

**The mental model.** `terraform apply` builds the *plumbing* but not the
*application*:

- The **ECR repositories** are empty shelves. Terraform built the shelves; it
  has no images to put on them — images are built from your code.
- An **ECS service** says "keep 1 task running", but a task needs an image.
  No image → the task cannot start → the service sits at **0 healthy tasks**,
  retrying. **This is expected after the first apply, not a failure.**
- **RDS** exists but has **no tables** — nothing has created the schema yet.

So after `apply` you do four things, once: put images on the shelves, create
the database tables, and tell the services to try again. After that the tasks
go healthy and `application_url` works.

#### The easy way — run the helper script

`infra/scripts/deploy.sh` does the whole sequence. Run it from anywhere in the
repo:

```bash
./infra/scripts/deploy.sh
```

It reads every name and URL from `terraform output`, so there is nothing to
fill in. It is **safe to re-run** — it is exactly the sequence for every future
redeploy, not just the first one. Requires `aws` (configured), `docker`
(running), `jq`, and `terraform`. Expect the API image build to take
**10–20 minutes** the first time (it installs torch and bakes the reranker
model).

#### What the script does, step by step

If you would rather run it by hand, or want to understand what the script is
doing, this is the same sequence. Run it from `infra/terraform/`:

```bash
# --- 1. Load everything Terraform knows into shell variables -------------
export AWS_REGION=$(terraform output -raw aws_region)
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

API_REPO=$(terraform output -raw ecr_api_repository_url)
FRONTEND_REPO=$(terraform output -raw ecr_frontend_repository_url)
ALB_URL=$(terraform output -raw application_url)
CLUSTER=$(terraform output -raw ecs_cluster_name)
API_SVC=$(terraform output -raw ecs_api_service_name)
FRONTEND_SVC=$(terraform output -raw ecs_frontend_service_name)
MIGRATE_FAMILY=$(terraform output -raw migration_task_family)
API_SG=$(terraform output -raw ecs_api_security_group_id)
SUBNETS=$(terraform output -json private_subnet_ids | jq -r 'join(",")')

# --- 2. Log Docker in to ECR (it is a private registry) -----------------
aws ecr get-login-password --region $AWS_REGION \
  | docker login --username AWS --password-stdin "${API_REPO%/*}"

# --- 3. Build + push the API image (run from the repo root) -------------
#    --platform linux/amd64: Fargate runs X86_64; without this an ARM-built
#    image will not start in AWS.
docker build --platform linux/amd64 -t "$API_REPO:latest" .
docker push "$API_REPO:latest"

# --- 4. Build + push the frontend ---------------------------------------
#    Next.js inlines NEXT_PUBLIC_* at BUILD time — the ALB URL must be a
#    build arg now; it cannot be set by a runtime env var.
docker build --platform linux/amd64 \
  --build-arg NEXT_PUBLIC_API_URL="$ALB_URL" \
  -t "$FRONTEND_REPO:latest" ./frontend
docker push "$FRONTEND_REPO:latest"

# --- 5. Run the DB migration once (creates the tables in RDS) -----------
TASK_ARN=$(aws ecs run-task --cluster "$CLUSTER" --launch-type FARGATE \
  --task-definition "$MIGRATE_FAMILY" \
  --network-configuration \
    "awsvpcConfiguration={subnets=[$SUBNETS],securityGroups=[$API_SG],assignPublicIp=DISABLED}" \
  --region $AWS_REGION --query 'tasks[0].taskArn' --output text)

aws ecs wait tasks-stopped --cluster "$CLUSTER" --tasks "$TASK_ARN" --region $AWS_REGION
# exitCode must be 0 — anything else means the migration failed:
aws ecs describe-tasks --cluster "$CLUSTER" --tasks "$TASK_ARN" \
  --region $AWS_REGION --query 'tasks[0].containers[0].exitCode'

# --- 6. Roll both services onto the freshly-pushed images ---------------
#    The tag stays "latest", so ECS only picks up a new image when forced.
aws ecs update-service --cluster "$CLUSTER" --service "$API_SVC" \
  --force-new-deployment --region $AWS_REGION
aws ecs update-service --cluster "$CLUSTER" --service "$FRONTEND_SVC" \
  --force-new-deployment --region $AWS_REGION

# --- 7. Wait for healthy, then open the app -----------------------------
aws ecs wait services-stable --cluster "$CLUSTER" \
  --services "$API_SVC" "$FRONTEND_SVC" --region $AWS_REGION
echo "Open: $ALB_URL"
```

**Why a separate migration task?** Schema migrations run as a one-shot
`migrate` task, *not* inside the API container's startup. If they ran on
startup, every autoscaled API task would race to run `alembic upgrade head`
against the same database. Running it once, on its own, keeps that off the
critical path.

**Redeploying later** is just steps 3–7 again (the script, re-run). **Week 8
automates this** in GitHub Actions, so day-to-day you only `git push`.

---

## 7. Inspect what you built

```bash
terraform output                 # re-print all outputs
terraform output rds_endpoint    # one specific value
terraform state list             # every resource Terraform manages
terraform show                   # the full current state, human-readable
```

You can also open the AWS console (in your region) — every resource is named
`finsight-prod-*` and tagged `Project=finsight`.

---

## 8. CI/CD — push to deploy

`deploy.sh` (§6) is the manual path. `.github/workflows/` automates it: a push
to `main` builds, migrates, and rolls the services with no terminal involved.

- **`ci.yml`** — runs on every pull request and feature-branch push: backend
  lint (`ruff`) + unit tests, frontend lint + build. It never touches AWS.
- **`deploy.yml`** — runs on every push to `main` (plus a manual "Run workflow"
  button). It runs the unit tests, then performs the exact §6 sequence: build +
  push both images → run the migration task → roll both ECS services.

### Authentication — OIDC, no stored keys

The workflow holds no AWS credentials. `github_oidc.tf` creates an IAM role
that GitHub Actions assumes at run time via OpenID Connect: GitHub mints a
short-lived token, AWS trades it for ~1-hour credentials, and the role's trust
policy only accepts tokens from your repository. Nothing to store, nothing to
rotate.

### One-time GitHub setup

After the first `terraform apply`:

1. Copy the role ARN:
   ```bash
   terraform output -raw github_actions_role_arn
   ```
2. In the GitHub repo: **Settings → Secrets and variables → Actions →
   Variables → New repository variable**. Name it `AWS_DEPLOY_ROLE_ARN` and
   paste the ARN. (A *variable*, not a secret — an ARN is not sensitive.)

From then on, every `git push` to `main` deploys automatically.

### Observability

`cloudwatch.tf` adds a **dashboard** (`terraform output cloudwatch_dashboard_url`)
and metric **alarms** — ALB 5xx, unhealthy API hosts, ECS CPU/memory, RDS
CPU/storage. Every alarm publishes to an SNS topic; set `alarm_email` in
`terraform.tfvars` to also get emails (confirm the AWS subscription link once).

---

## 9. Making changes

The loop is always the same:

1. Edit a `.tf` file (e.g. bump `db_instance_class` in `variables.tf`).
2. `terraform plan` — see exactly what will change.
3. `terraform apply` — apply it.

Terraform updates *in place* where it can, and replaces a resource only when
the change can't be done live (it tells you — look for `# forces replacement`).

---

## 10. Tear it down

To stop all charges, destroy everything:

```bash
terraform destroy
```

It lists everything to be deleted and asks for `yes`. Secrets are created with
`recovery_window_in_days = 0`, so their names free up immediately and a later
re-`apply` is clean. **`destroy` deletes the database and its data** — that's
the intent for a portfolio project you spin up and down.

---

## 11. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `No valid credential sources found` | AWS credentials not set — run `aws configure`. |
| `UnauthorizedOperation` / `AccessDenied` | Your IAM user lacks permissions for that resource. |
| `InvalidAMIID` / AMI not found | The AMI lookup is region-specific; make sure `aws_region` matches your configured region. |
| `apply` seems stuck | RDS + NAT genuinely take ~10 min. Give it time. |
| `Error acquiring the state lock` | Only with the S3 backend — a previous run didn't release. Not applicable to local state. |
| Re-`apply` after a partial failure | Safe — Terraform is idempotent; it resumes from the state file. |
| Changed `terraform.tfvars` secrets | Re-`apply` — Terraform updates the Secrets Manager values. |
| `deploy.yml`: `Not authorized to perform sts:AssumeRoleWithWebIdentity` | The `AWS_DEPLOY_ROLE_ARN` repo variable is missing/wrong, or `github_repo` in `terraform.tfvars` doesn't match the actual `owner/repo`. |
| `deploy.yml`: `services-stable` wait times out | The API task is slow to pass health checks (it loads the reranker). Check the CloudWatch log group `/ecs/finsight-prod/api`. |

---

## 12. What's next

- **Weeks 6–8 — done.** Core infrastructure, ECS Fargate services, the load
  balancer, autoscaling, the one-shot migration task, GitHub Actions CI/CD, and
  CloudWatch alarms + dashboard are all in this stack.
- The remaining optional hardening is **HTTPS** (below).

### HTTPS (optional, needs a domain)

The ALB is HTTP-only — fine for a portfolio demo on the raw ALB hostname. To
add TLS you need a domain you control: request an ACM certificate, add a
`443` HTTPS listener with the same path rules, and point a Route 53 record at
the ALB. That can be layered on without touching the rest of the stack.
