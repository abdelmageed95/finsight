# Terraform Study Guide — Using FinSight as a Worked Example

> A complete, interview-ready walkthrough of Terraform built around the
> real infrastructure in `infra/terraform/`. Every concept is paired with
> the file in this repo that demonstrates it.

---

## Table of contents

1. [What Terraform is — and why it exists](#1-what-terraform-is)
2. [Mental model: the four-way diff](#2-mental-model-the-four-way-diff)
3. [HCL syntax — the language you're writing](#3-hcl-syntax)
4. [The five building blocks](#4-the-five-building-blocks)
5. [The Terraform CLI workflow](#5-the-cli-workflow)
6. [State — the most important concept](#6-state)
7. [Providers — `versions.tf`, `providers.tf`](#7-providers)
8. [Variables, locals, outputs — `variables.tf`, `locals.tf`, `outputs.tf`](#8-variables-locals-outputs)
9. [Resources & data sources — `vpc.tf`, `chroma.tf`](#9-resources--data-sources)
10. [Expressions, references, interpolation](#10-expressions)
11. [Meta-arguments — `count`, `for_each`, `depends_on`, `lifecycle`](#11-meta-arguments)
12. [Functions you'll actually use](#12-functions)
13. [Templates & dynamic content — `chroma_user_data.sh.tftpl`](#13-templates)
14. [Modules — and why FinSight doesn't use them](#14-modules)
15. [Backends — local vs remote state](#15-backends)
16. [The full FinSight stack, file by file](#16-the-full-finsight-stack)
17. [Security & secrets — `secrets.tf`, `iam.tf`, `github_oidc.tf`](#17-security--secrets)
18. [Common pitfalls & how to debug](#18-common-pitfalls--debugging)
19. [Best practices](#19-best-practices)
20. [Interview questions & answers](#20-interview-questions)
21. [Glossary](#21-glossary)

---

## 1. What Terraform is

**Terraform** is an **Infrastructure-as-Code (IaC)** tool by HashiCorp. Instead
of clicking around the AWS console to create a VPC, a database, a load
balancer, etc., you *describe* the desired infrastructure in `.tf` files written
in **HCL** (HashiCorp Configuration Language). Terraform then makes the API
calls to build it.

### Key properties

| Property | Meaning | How FinSight benefits |
|---|---|---|
| **Declarative** | You describe the *end state*, not the steps. Terraform computes the diff. | You say "I want a VPC with these subnets". You never write the order to create them in. |
| **Idempotent** | Running `apply` twice with no edits = no changes the second time. | Running `terraform apply` after a fresh `apply` is safe — it does nothing. |
| **Dependency-aware** | Terraform builds a graph from references and creates resources in topological order. | `rds.tf` references `aws_security_group.rds.id` — the SG is built first, automatically. |
| **Provider-agnostic** | The same language works for AWS, GCP, Azure, GitHub, Cloudflare, Kubernetes, etc. (via different providers). | FinSight uses only the AWS provider, but you could add others without changing the workflow. |
| **State-tracked** | A `terraform.tfstate` file is the ledger linking your code to real cloud resources. | When you `apply` again, Terraform knows what already exists and updates in place. |

### Terraform vs alternatives

| Tool | Style | Notes |
|---|---|---|
| **CloudFormation** | AWS-only, declarative (JSON/YAML) | Native to AWS but verbose; harder to reuse across clouds. |
| **Pulumi** | Multi-cloud, *real programming languages* (Python, TS, Go) | More expressive but the codebase becomes a real program. |
| **Ansible** | Procedural, primarily *configuration management* | Better at "configure this server", weaker at "create cloud resources". |
| **AWS CDK** | TypeScript/Python, compiles to CloudFormation | AWS-only; nice DX, inherits CloudFormation's quirks. |
| **Terraform** | Multi-cloud, declarative HCL | Industry standard for cloud-agnostic IaC. |

---

## 2. Mental model: the four-way diff

The single most important picture in your head:

```
        ┌─────────────────┐
        │  Your .tf code  │  ← the *desired* state
        └────────┬────────┘
                 │
                 ▼
        ┌─────────────────┐    ┌────────────────────────┐
        │  terraform plan │ ←─ │ terraform.tfstate file │  ← what Terraform thinks
        └────────┬────────┘    └────────────────────────┘   already exists
                 │                       ▲
                 ▼                       │
        ┌─────────────────┐              │
        │ Real cloud (AWS)│ ─────────────┘ (refresh)
        └─────────────────┘
```

`terraform plan` compares **three** things — code, state, and live reality —
and produces a list of `+ create`, `~ update`, `- destroy` actions. `apply`
executes that list.

**This is why every Terraform problem boils down to: which of these three is
out of sync?**

---

## 3. HCL syntax

HCL is JSON-like but more pleasant. Every `.tf` file is composed of **blocks**.

```hcl
block_type "label_a" "label_b" {
  argument_name = expression

  nested_block {
    other_argument = "value"
  }
}
```

### Block types you'll see in FinSight

```hcl
# Top-level configuration of Terraform itself.
terraform {
  required_version = ">= 1.6"
  required_providers { ... }
}

# Provider config (AWS, Google, etc.)
provider "aws" {
  region = var.aws_region
}

# Real cloud resource. First label = type, second = local name.
resource "aws_vpc" "main" {
  cidr_block = "10.0.0.0/16"
}

# Read-only lookup.
data "aws_availability_zones" "available" {
  state = "available"
}

# Inputs.
variable "aws_region" {
  type    = string
  default = "eu-central-1"
}

# Local helpers (computed values).
locals {
  name_prefix = "${var.project}-${var.environment}"
}

# Values printed after apply.
output "vpc_id" {
  value = aws_vpc.main.id
}
```

### Comments

```hcl
# single-line
// also single-line
/* multi
   line */
```

### Heredocs (multi-line strings)

```hcl
policy = <<-EOT
  {
    "Statement": [...]
  }
EOT
```

### File layout convention

Terraform **loads every `.tf` file in the directory** as a single configuration.
The split is for human readability only. You'll typically see:

- `versions.tf` — Terraform & provider versions
- `providers.tf` — provider config
- `variables.tf` — inputs
- `locals.tf` — derived values
- `outputs.tf` — outputs
- One `.tf` file per logical concern (`vpc.tf`, `rds.tf`, `ecs.tf` …)

This is exactly the FinSight layout.

---

## 4. The five building blocks

| Concept | Purpose | FinSight example |
|---|---|---|
| **Provider** | Plugin that talks to a cloud API. | `providers.tf` configures `hashicorp/aws`. |
| **Resource** | One piece of real infrastructure you manage. | `resource "aws_vpc" "main"` in `vpc.tf`. |
| **Data source** | Read-only lookup of something that already exists or is provider-managed. | `data "aws_ami" "al2023"` finds the latest Amazon Linux AMI. |
| **Variable** | Input value (region, sizes, secrets). | `variable "db_password"` in `variables.tf`. |
| **Output** | Value Terraform prints after apply. | `output "rds_endpoint"` in `outputs.tf`. |

There's also `locals` (named expressions) and `module` (a reusable bundle of
the above) — we cover those below.

---

## 5. The CLI workflow

The core loop is **four commands**. Read these like a beginner: you will run
them hundreds of times.

```bash
terraform init      # download providers, set up state. Run once per machine
                    # per config (and after changing required_providers).

terraform plan      # READ-ONLY. Show what would change. Nothing is created.

terraform apply     # Apply the plan. Prompts "yes" by default.

terraform destroy   # Delete every resource Terraform manages.
```

### Other commands you should know

```bash
terraform fmt                # auto-format .tf files (canonical style)
terraform validate           # syntax / type check, no AWS calls
terraform output             # print all outputs
terraform output -raw NAME   # print one output, unquoted (script-friendly)
terraform state list         # list every resource Terraform tracks
terraform state show ADDR    # show a single resource's attributes
terraform show               # show the entire current state
terraform show tfplan        # show a saved plan file in human-readable form
terraform plan -out tfplan   # save the plan (idempotent apply)
terraform apply tfplan       # apply exactly that saved plan
terraform refresh            # re-sync state with real cloud (rarely needed)
terraform taint / untaint    # mark a resource for replacement on next apply
                             # (modern style: terraform apply -replace=ADDR)
terraform import ADDR ID     # adopt an existing resource into state
terraform graph              # output the dependency graph
```

### What `terraform init` does

1. Downloads the **providers** declared in `required_providers` into `.terraform/`.
2. Creates a **lock file** (`.terraform.lock.hcl`) pinning provider versions
   and their hashes — committed to git, so teammates resolve to identical
   plugin versions.
3. Configures the **backend** (where state lives).
4. Discovers any local **modules**.

You re-run `init` whenever you change provider versions, the backend, or add a
new module.

### Plan output reading

```
  # aws_vpc.main will be created
  + resource "aws_vpc" "main" {
      + cidr_block = "10.0.0.0/16"
      + id         = (known after apply)
    }

Plan: 1 to add, 0 to change, 0 to destroy.
```

Symbol legend:

| Symbol | Meaning |
|---|---|
| `+` | create |
| `-` | destroy |
| `~` | update in place |
| `-/+` | destroy and replace (sometimes the only way to change an attribute) |
| `# forces replacement` (annotation) | the listed attribute can't change in place — Terraform must recreate |

**A `-/+` line on a database is the moment you stop and think.**

---

## 6. State

`terraform.tfstate` is a JSON file that maps `resource "aws_vpc" "main"` →
the real AWS VPC's ID, attributes, dependencies. **Without state, Terraform
has amnesia.**

### Three rules of state

1. **Never delete it.** If you do, Terraform forgets it owns those resources
   and on next `apply` would try to create them again (and probably fail
   because they already exist with the same name).
2. **Never commit it to git.** It can contain secrets (the DB password gets
   stored in plaintext for some resources, for example). FinSight's
   `.gitignore` already excludes it.
3. **One state per environment.** Don't share `prod` and `staging` state.

### Local vs remote state

FinSight uses **local state** — `terraform.tfstate` lives in `infra/terraform/`.
This is fine for one person.

For a team you switch to a **remote backend** (S3 + DynamoDB on AWS):

- **S3** holds the state file (versioned, encrypted).
- **DynamoDB** provides a *lock* so two engineers can't `apply` at once.

FinSight has this scaffolded but commented out in `infra/terraform/versions.tf`:

```hcl
# backend "s3" {
#   bucket         = "finsight-tfstate"
#   key            = "prod/terraform.tfstate"
#   region         = "us-east-1"
#   dynamodb_table = "finsight-tflock"
#   encrypt        = true
# }
```

To migrate: create the S3 bucket + DynamoDB table once (outside Terraform or
in a tiny bootstrap config), uncomment the block, then
`terraform init -migrate-state`.

### State commands you'll need

```bash
terraform state list                       # all addresses
terraform state show aws_vpc.main          # one resource
terraform state rm aws_vpc.main            # forget it (does NOT delete cloud)
terraform state mv OLD NEW                 # rename without recreating
terraform import aws_vpc.main vpc-abc123   # adopt existing AWS resource
```

`state rm` followed by `import` is how you fix "Terraform lost track" or move
between modules without churn.

---

## 7. Providers

A **provider** is a plugin that wraps a cloud's API. FinSight uses only AWS.

### `infra/terraform/versions.tf` — pinning

```hcl
terraform {
  required_version = ">= 1.6"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.60"
    }
  }
}
```

- `required_version` — fail-fast if someone runs an older Terraform.
- `source` — the provider's address on the Terraform Registry.
- `version = "~> 5.60"` — **pessimistic constraint**: any `5.x` ≥ 5.60, no `6.x`.
  Other operators: `= 5.60.0` (exact), `>= 5.60` (any newer).

`.terraform.lock.hcl` records the *exact* version chosen plus checksums. Commit
it. Run `terraform init -upgrade` to bump within the constraint.

### `infra/terraform/providers.tf` — configuration

```hcl
provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = var.project
      Environment = var.environment
      ManagedBy   = "terraform"
    }
  }
}
```

Two things to notice:

- **No credentials in code.** The AWS provider reads `~/.aws/credentials`,
  environment variables (`AWS_ACCESS_KEY_ID`, …), or an EC2/ECS role
  automatically. Secrets stay out of git.
- **`default_tags`** apply to every resource the provider creates. This is how
  every FinSight resource gets `Project=finsight`/`ManagedBy=terraform`
  without writing it 30 times — invaluable for cost allocation and cleanup.

### Multiple provider instances (aliases)

You can configure the same provider twice — e.g. one for `us-east-1` (for
ACM certificates required by CloudFront) and one for your real region:

```hcl
provider "aws" {
  region = "eu-central-1"
}

provider "aws" {
  alias  = "use1"
  region = "us-east-1"
}

resource "aws_acm_certificate" "cf" {
  provider = aws.use1   # opt in to the alias
  ...
}
```

FinSight doesn't use aliases — only one region.

---

## 8. Variables, locals, outputs

### Variables (`infra/terraform/variables.tf`)

A variable is an **input** to the configuration.

```hcl
variable "vpc_cidr" {
  description = "CIDR block for the VPC."
  type        = string
  default     = "10.0.0.0/16"
}

variable "db_password" {
  description = "Postgres master password."
  type        = string
  sensitive   = true              # masked in plan / apply output
}

variable "public_subnet_cidrs" {
  type    = list(string)
  default = ["10.0.1.0/24", "10.0.2.0/24"]
}
```

#### Fields

| Field | Purpose |
|---|---|
| `type` | `string`, `number`, `bool`, `list(...)`, `set(...)`, `map(...)`, `object({...})`, `tuple([...])`, `any` |
| `default` | Optional. If omitted, the variable is **required**. |
| `description` | Shown in `terraform plan` and on the registry. Write these. |
| `sensitive` | `true` → value never appears in plan/output. |
| `validation { ... }` | Custom validation rules. |
| `nullable` | If `false`, the value cannot be `null`. |

#### Setting variable values, in precedence order

1. **`-var` / `-var-file` flags** on the CLI (highest)
2. **`*.auto.tfvars`** files in the working dir
3. **`terraform.tfvars`** (FinSight's convention)
4. **`TF_VAR_<name>`** environment variables
5. **`default`** in the variable definition (lowest)

FinSight uses `terraform.tfvars` for the values you must supply:

```hcl
db_password    = "..."
claude_api_key = "sk-ant-..."
github_repo    = "abdelmageedahmed/finsight"
```

`terraform.tfvars` is **gitignored**. The committed `terraform.tfvars.example`
documents the shape without exposing real secrets.

### Locals (`infra/terraform/locals.tf`)

A local is a **named expression** — DRY for things you'd otherwise repeat.

```hcl
locals {
  name_prefix = "${var.project}-${var.environment}"
}
```

You reference it as `local.name_prefix` (singular `local`, even though the
block is plural `locals`). Used throughout FinSight to tag everything with
`finsight-prod-...`.

Locals can also do non-trivial computation:

```hcl
# infra/terraform/ecr.tf
locals {
  ecr_lifecycle_policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Expire all but the 10 most recent images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 10
      }
      action = { type = "expire" }
    }]
  })
}
```

This builds the lifecycle policy once, reused for both the API and frontend
repos.

### Outputs (`infra/terraform/outputs.tf`)

Outputs **expose** values after apply — for humans, for scripts, for other
configurations.

```hcl
output "rds_endpoint" {
  description = "Postgres host:port."
  value       = aws_db_instance.main.endpoint
}

output "application_url" {
  description = "Open this in a browser."
  value       = "http://${aws_lb.main.dns_name}"
}

output "secret_arns" {
  value     = { for k, s in aws_secretsmanager_secret.app : k => s.arn }
  sensitive = false
}
```

Why outputs matter in FinSight:

- `infra/scripts/deploy.sh` reads them via `terraform output -raw <name>` — it
  doesn't hard-code the ECR URL, the ALB DNS, or any other value.
- `terraform output github_actions_role_arn` is how you bootstrap the GitHub
  Actions OIDC variable.

---

## 9. Resources & data sources

### Resources

A `resource` block describes one piece of cloud infrastructure that **Terraform
manages** (creates, updates, deletes).

```hcl
# infra/terraform/vpc.tf
resource "aws_vpc" "main" {
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = { Name = "${local.name_prefix}-vpc" }
}
```

- `resource` — keyword.
- `"aws_vpc"` — **resource type**, defined by the provider. Always
  `<provider>_<thing>`.
- `"main"` — **local name**, *your* identifier for referring to this resource
  inside the configuration (`aws_vpc.main.id`). Doesn't appear in AWS.
- The block body lists **arguments** (inputs) and reads-only **attributes** are
  exposed after creation.

### Data sources

A `data` block **reads** something that already exists (or that the provider
manages for you):

```hcl
# infra/terraform/locals.tf
data "aws_availability_zones" "available" {
  state = "available"
}

# infra/terraform/chroma.tf — find the latest Amazon Linux 2023 AMI
data "aws_ami" "al2023" {
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["al2023-ami-2023.*-x86_64"]
  }
  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}
```

Reference: `data.aws_ami.al2023.id`. Note the extra `data.` prefix — that's how
the resolver knows it's a data source, not a resource.

### Resource = managed; Data = read-only

| | resource | data |
|---|---|---|
| Creates AWS objects | yes | no |
| Updates AWS objects | yes | no |
| Destroys AWS objects | yes (on destroy) | no |
| Affected by your config | yes | no |
| Refreshed each `plan` | yes | yes |

### Implicit & explicit dependencies

The dependency graph is built **automatically from references**. When `rds.tf`
contains:

```hcl
resource "aws_db_instance" "main" {
  ...
  vpc_security_group_ids = [aws_security_group.rds.id]
}
```

Terraform sees `aws_security_group.rds.id` and knows the SG must exist first.
You don't write `depends_on` here — the reference *is* the dependency.

Use `depends_on` only when there's a real ordering Terraform can't infer
(no reference exists), e.g.:

```hcl
# infra/terraform/vpc.tf
resource "aws_nat_gateway" "main" {
  allocation_id = aws_eip.nat.id
  subnet_id     = aws_subnet.public[0].id

  depends_on = [aws_internet_gateway.main]
}
```

The NAT gateway doesn't directly reference the IGW, but it needs to exist after
the IGW is attached — AWS is finicky about this. Explicit `depends_on` makes it
correct.

---

## 10. Expressions

HCL expressions look familiar to anyone who's used a templating language.

### Interpolation

```hcl
tags = { Name = "${local.name_prefix}-vpc" }
```

`${ ... }` interpolates an expression into a string. Bare references in
non-string contexts don't need `${}`:

```hcl
cidr_block = var.vpc_cidr      # no quotes
```

### Indexing & splat

```hcl
aws_subnet.public[0].id              # first public subnet
aws_subnet.public[*].id              # list of all public subnet IDs (splat)
```

The **splat operator** `[*]` is the idiomatic way to get a list of attributes
across all instances of a counted/`for_each`'d resource. Used in FinSight:

```hcl
# infra/terraform/alb.tf
subnets = aws_subnet.public[*].id

# infra/terraform/rds.tf
subnet_ids = aws_subnet.private[*].id
```

### Conditional

```hcl
count = var.alarm_email != "" ? 1 : 0
```

Ternary. Used in `infra/terraform/cloudwatch.tf` to make the email subscription
optional.

### `for` expressions

Iterate over collections:

```hcl
# from infra/terraform/outputs.tf
value = { for k, s in aws_secretsmanager_secret.app : k => s.arn }
```

Reads as: "build a map where every key is `k` and value is `s.arn`, iterating
over `aws_secretsmanager_secret.app` (which has multiple instances)".

Also handy in `iam.tf`:

```hcl
resources = [for s in aws_secretsmanager_secret.app : s.arn]
```

---

## 11. Meta-arguments

These are special arguments that **any** resource block accepts.

### `count` — create N identical instances

```hcl
# infra/terraform/vpc.tf
resource "aws_subnet" "public" {
  count                   = length(var.public_subnet_cidrs)
  vpc_id                  = aws_vpc.main.id
  cidr_block              = var.public_subnet_cidrs[count.index]
  availability_zone       = data.aws_availability_zones.available.names[count.index]
  map_public_ip_on_launch = true

  tags = {
    Name = "${local.name_prefix}-public-${count.index + 1}"
    Tier = "public"
  }
}
```

- `count = 2` → produces `aws_subnet.public[0]` and `aws_subnet.public[1]`.
- `count.index` is `0`, `1`, … inside the block.

**Caveat:** `count` indexes are positional. If you remove the *middle* element
from `public_subnet_cidrs`, every later subnet shifts and gets recreated. Use
`for_each` (a map/set) for stable identifiers.

### `for_each` — create one instance per key

```hcl
# infra/terraform/secrets.tf
resource "aws_secretsmanager_secret" "app" {
  for_each                = local.secrets
  name                    = "${local.name_prefix}/${each.key}"
  recovery_window_in_days = 0
}
```

- `for_each` takes a `map` or `set`.
- Inside the block, `each.key` and `each.value` are available.
- Resources are addressed by key: `aws_secretsmanager_secret.app["claude-api-key"]`.

Adding a new secret only creates *that* secret — the others are untouched. With
`count` you'd have to reorder a list and risk recreating others.

**Rule of thumb:** if the "list" is really a *set of named things*, use
`for_each`. If it's "give me N copies", use `count`.

### `lifecycle` — fine-tune the diff behaviour

```hcl
# infra/terraform/ecs.tf
resource "aws_ecs_service" "api" {
  ...
  desired_count = var.api_desired_count

  lifecycle {
    ignore_changes = [desired_count]
  }
}
```

This says: "don't fight autoscaling. Once the service exists, ignore changes
to `desired_count` on `apply`." Without this, Terraform would set the count
back to `var.api_desired_count` every time you ran it, even if the autoscaling
policy had scaled out to 3.

Other useful `lifecycle` knobs:

```hcl
lifecycle {
  create_before_destroy = true    # build the new one before deleting the old
  prevent_destroy       = true    # error out if a plan would destroy this
  ignore_changes        = [tags]  # ignore manual edits to specific attributes
  replace_triggered_by  = [...]   # force replacement when another thing changes
}
```

`prevent_destroy = true` on a production RDS is a great seatbelt.

### `depends_on` — explicit ordering

Already covered — only when there's no reference to express the dependency.

### `provider` — pick a non-default provider

```hcl
resource "aws_acm_certificate" "cf" {
  provider = aws.use1   # use the aliased "us-east-1" provider
  ...
}
```

Not used in FinSight (single region).

---

## 12. Functions

HCL ships ~100 built-in functions. The handful you'll actually reach for:

| Function | Example | What it does |
|---|---|---|
| `length(x)` | `length(var.public_subnet_cidrs)` | Length of list/map/string. |
| `concat(a, b)` | `concat(["a"], ["b"])` | Join lists. |
| `coalesce(a, b)` | `coalesce(var.alpha_vantage_api_key, "unset")` | First non-empty value. **Used in `secrets.tf`** so blank keys still produce valid secrets. |
| `jsonencode(x)` | The ECR lifecycle policy, the CloudWatch dashboard body | Turn HCL into JSON for arguments that expect a JSON string. |
| `jsondecode(s)` | reverse | Parse JSON into HCL. |
| `templatefile(p, vars)` | `templatefile("${path.module}/chroma_user_data.sh.tftpl", {...})` | Render a template file with variables. |
| `file(p)` | `file("policy.json")` | Read a file's contents as a string. |
| `lookup(map, key, default)` | `lookup(var.tags, "Env", "dev")` | Map access with a fallback. |
| `merge(a, b)` | `merge(var.tags, {Name = "..."})` | Combine maps. |
| `format(s, args...)` | `format("%s-%d", name, count.index)` | Like `printf`. |
| `cidrsubnet(cidr, bits, n)` | `cidrsubnet("10.0.0.0/16", 8, 0)` | Compute sub-CIDRs. |
| `toset(list)` | `toset(["a", "b"])` | Convert list → set (for `for_each`). |
| `try(x, fallback)` | `try(data.aws_xxx.id, "")` | Return fallback if expression errors. |

Why `jsonencode` rather than writing literal JSON? Because HCL → JSON has
proper quoting, references, and you keep HCL's readability:

```hcl
# Compare this:
container_definitions = jsonencode([{
  name  = "api"
  image = "${aws_ecr_repository.api.repository_url}:${var.api_image_tag}"
  ...
}])

# To the alternative (a JSON string heredoc with `${}` escaping):
container_definitions = <<EOT
[
  {
    "name": "api",
    "image": "${aws_ecr_repository.api.repository_url}:${var.api_image_tag}",
    ...
  }
]
EOT
```

The first is type-checked by Terraform; the second is a wall of strings.

---

## 13. Templates

Some configurations need to ship *files* with Terraform-substituted values —
shell scripts, user-data, config files. The `templatefile` function does this.

### FinSight example — Chroma's boot script

`infra/terraform/chroma.tf`:

```hcl
resource "aws_instance" "chroma" {
  ...
  user_data = templatefile("${path.module}/chroma_user_data.sh.tftpl", {
    chroma_image = var.chroma_image
  })
}
```

`infra/terraform/chroma_user_data.sh.tftpl`:

```bash
#!/bin/bash
set -euxo pipefail

dnf install -y docker
systemctl enable --now docker
...
docker run -d --name chroma --restart unless-stopped \
  -p 8000:8000 \
  ${chroma_image}
```

When AWS boots the EC2 instance, this script runs as cloud-init user data. The
`${chroma_image}` placeholder is replaced by Terraform at plan time with
whatever the variable resolved to.

**Two gotchas:**

1. The file extension `.tftpl` is convention — Terraform treats *any* file
   passed to `templatefile` as a template; the suffix just signals it to humans
   and to editors for syntax highlighting.
2. Inside the template, `$${literal}` escapes a literal `${...}` that should
   not be interpolated by Terraform (e.g. shell variables). The Chroma script
   doesn't need this, but a more complex script often does.

### `path.module` vs `path.root`

- `path.module` — directory of the current `.tf` file/module. Use this for
  files alongside the config (FinSight does).
- `path.root` — the root config directory.

---

## 14. Modules

A **module** is a reusable bundle of Terraform configuration — a directory of
`.tf` files you can call from elsewhere:

```hcl
module "vpc" {
  source = "terraform-aws-modules/vpc/aws"
  version = "~> 5.0"

  name = "my-vpc"
  cidr = "10.0.0.0/16"
  ...
}
```

Modules can be:

- **Local** (a directory in your repo): `source = "./modules/vpc"`
- **Public registry**: `source = "terraform-aws-modules/vpc/aws"`
- **Git**: `source = "git::https://github.com/.../vpc.git?ref=v1.0"`

Outputs of a module are referenced as `module.<name>.<output_name>`.

### Why FinSight doesn't use modules

FinSight is a single-environment portfolio project. Modules pay off when:

- You deploy the same shape across **multiple environments** (dev/staging/prod)
  or **regions**.
- You want a clean abstraction boundary that a teammate could call without
  reading the internals.

For a one-environment learning project, flat `.tf` files in one directory are
clearer — you see every resource without jumping through indirection. The
trade-off is intentional.

### When to extract a module

Three signals:

1. You're copy-pasting a block of `.tf` to make another `staging` deployment.
2. A logical group (VPC + subnets + routes) is reused across configurations.
3. You want to publish it for others (Terraform Registry).

---

## 15. Backends

A **backend** determines where state is stored and how `apply` is coordinated.

### Local backend (FinSight's current choice)

State is a file in the working directory. No locking. Fine for one person.

### S3 backend (recommended for teams)

```hcl
terraform {
  backend "s3" {
    bucket         = "finsight-tfstate"
    key            = "prod/terraform.tfstate"
    region         = "us-east-1"
    dynamodb_table = "finsight-tflock"   # state locking
    encrypt        = true
  }
}
```

- The S3 bucket holds the state (enable versioning + SSE).
- The DynamoDB table provides a lock — `apply` acquires it, releases on exit,
  and a second concurrent `apply` waits.

**Chicken-and-egg:** you can't use Terraform to create the bucket that holds
its own state (clean room). Either create it manually once, or in a tiny
bootstrap config with a local backend.

### Migration

After uncommenting the backend block:

```bash
terraform init -migrate-state
```

Terraform copies state from local to S3 and points future runs there.

### Other backends

`azurerm`, `gcs`, `consul`, `kubernetes`, `remote` (Terraform Cloud / HCP),
`http`. Pick the one matching your team's storage.

---

## 16. The full FinSight stack

This is the most useful section for interviews — talk through each file,
explain *why*.

### Architecture at a glance

```
                       Internet
                          │
                ┌─────────┴─────────┐
                │      ALB :80      │  ← only public surface
                └─────────┬─────────┘
                          │
        ┌─────────────────┼──────────────────┐
        │ path-based routing                  │
        ▼                                     ▼
  /api paths                          everything else
        │                                     │
        ▼                                     ▼
   ECS api task (private)                 ECS frontend task (private)
        │
        ├── RDS Postgres   (private subnet)
        ├── ElastiCache    (private subnet)
        ├── Chroma EC2     (private subnet)
        ├── Secrets Manager (at launch)
        └── via NAT GW → Anthropic / OpenAI / SEC EDGAR
```

Two-tier subnet layout (public/private), one VPC across two AZs. The only
inbound door is the ALB.

### File-by-file tour

#### `versions.tf` — pinning

Pins Terraform `>= 1.6` and AWS provider `~> 5.60`. Empty commented S3
backend stanza ready for team use.

#### `providers.tf` — the AWS provider

Configures the AWS provider with a region and `default_tags`. **Every** resource
in the stack is automatically tagged `Project=finsight`,
`Environment=prod`, `ManagedBy=terraform`.

Interview point: explain how `default_tags` is a cheap way to make every
resource discoverable and cost-attributable without per-resource boilerplate.

#### `locals.tf` — the name prefix

```hcl
locals {
  name_prefix = "${var.project}-${var.environment}"   # "finsight-prod"
}

data "aws_availability_zones" "available" {
  state = "available"
}
```

Every named resource is prefixed `finsight-prod-...`. The AZ data source
provides the list of zones — used to spread subnets across them.

#### `variables.tf` — inputs

Three groups: core (region, project, env), networking (CIDRs), databases,
secrets, ECS sizing, CI/CD. Sensitive variables (`db_password`, `claude_api_key`,
…) are marked `sensitive = true`.

Optional API keys default to `""` so the user can leave them blank in
`terraform.tfvars` — the `coalesce` in `secrets.tf` handles the empty case.

#### `vpc.tf` — networking

| Resource | Role |
|---|---|
| `aws_vpc.main` | The VPC itself (10.0.0.0/16). |
| `aws_internet_gateway.main` | Internet door for public subnets. |
| `aws_subnet.public[0..1]` | 10.0.1.0/24, 10.0.2.0/24 — for ALB & NAT. |
| `aws_subnet.private[0..1]` | 10.0.3.0/24, 10.0.4.0/24 — for ECS, RDS, Redis, Chroma. |
| `aws_eip.nat` | Elastic IP for the NAT gateway. |
| `aws_nat_gateway.main` | Lets private subnets call out to the internet. |
| `aws_route_table.public` / `.private` | Route tables (public → IGW, private → NAT). |
| `aws_route_table_association.*` | Wire subnets to their route table. |

Two-AZ spread uses `count = length(var.public_subnet_cidrs)` + `count.index`
to pick the CIDR and AZ for each subnet.

**Portfolio-grade trade-off:** one NAT gateway (not one per AZ). A NAT is ~$32/mo;
running two would double the single biggest fixed cost. Production would
prefer one-per-AZ for fault tolerance.

#### `security_groups.tf` — the firewall chain

```
internet ──:80──▶ alb ──:8000──▶ ecs_api ──┬──:5432──▶ rds
                      ──:3000──▶ ecs_frontend │
                                              ├──:6379──▶ redis
                                              └──:8000──▶ chroma
```

Each SG accepts traffic only from the one in front of it via
`security_groups = [aws_security_group.X.id]` rather than CIDRs. This is the
**least-privilege chain** — there is no path from the internet to the database,
not even by mistake.

Interview point: distinguish security groups (stateful, instance-level) from
NACLs (stateless, subnet-level). FinSight uses SGs only.

#### `ecr.tf` — container registries

Two registries: `finsight-prod-api`, `finsight-prod-frontend`. Both:

- `image_tag_mutability = "MUTABLE"` — `latest` can be overwritten.
- `force_delete = true` — `terraform destroy` works even with images present.
- `scan_on_push = true` — ECR runs a vulnerability scan after each push.
- Lifecycle policy keeps only the 10 most recent images per repo.

The lifecycle policy is built with `jsonencode` in a local block and attached
to both repos — DRY.

#### `rds.tf` — Postgres

```hcl
resource "aws_db_instance" "main" {
  engine                  = "postgres"
  engine_version          = "16"
  instance_class          = var.db_instance_class   # db.t3.micro
  storage_type            = "gp3"
  allocated_storage       = var.db_allocated_storage
  max_allocated_storage   = var.db_allocated_storage * 3   # autoscaling headroom
  storage_encrypted       = true
  db_subnet_group_name    = aws_db_subnet_group.main.name
  vpc_security_group_ids  = [aws_security_group.rds.id]
  publicly_accessible     = false
  multi_az                = false
  backup_retention_period = 0
  skip_final_snapshot     = true
  ...
}
```

Portfolio-grade defaults; production would flip `multi_az`, raise retention,
turn on `deletion_protection`.

**Subnet group** is a tiny but important AWS concept: RDS chooses which subnets
it can place the DB into.

#### `elasticache.tf` — Redis

Single node, `cache.t3.micro`, in private subnets, accessible only from the
API tasks via the `redis` SG.

#### `secrets.tf` — secrets manager

```hcl
locals {
  secrets = {
    claude-api-key        = var.claude_api_key
    openai-api-key        = var.openai_api_key
    alpha-vantage-api-key = coalesce(var.alpha_vantage_api_key, "unset")
    jwt-secret-key        = var.jwt_secret_key
    ...
    database-url = "postgresql+asyncpg://${var.db_username}:${var.db_password}@${aws_db_instance.main.address}:5432/${var.db_name}"
  }
}

resource "aws_secretsmanager_secret" "app" {
  for_each                = local.secrets
  name                    = "${local.name_prefix}/${each.key}"
  recovery_window_in_days = 0
}

resource "aws_secretsmanager_secret_version" "app" {
  for_each      = local.secrets
  secret_id     = aws_secretsmanager_secret.app[each.key].id
  secret_string = each.value
}
```

Three things worth understanding:

1. **`for_each` over a map** — adding a new secret only creates that secret.
2. **`coalesce`** so blank optional keys still produce a valid (placeholder)
   secret. Secrets Manager rejects empty strings.
3. **`database-url` is composed** — Terraform builds the full DSN from the RDS
   endpoint + creds, so the app never hand-types it.

The ECS task definitions reference each secret **by ARN** (not value) — the
secret value only resolves at task launch time, inside the ECS agent.

#### `iam.tf` — IAM roles

Two roles for ECS, one for the Chroma EC2 host.

```
ecs_task_execution      — used by the ECS *agent* to launch a task:
                          • pull image from ECR
                          • read secrets from Secrets Manager
                          • write logs to CloudWatch

ecs_task                — used by *application code* in the container.
                          FinSight's app makes no AWS calls itself, so
                          this role has no policies. It exists for the
                          execution-vs-runtime separation.

chroma_ec2              — for the EC2 host:
                          • SSM Session Manager (admin without SSH)
                          • CloudWatch Logs (system/Docker logs)
                          Wrapped in an aws_iam_instance_profile.
```

The split between **execution role** and **task role** is a standard
defense-in-depth idea: compromising the running container's role does not
give the attacker the ability to pull arbitrary images or fetch unrelated
secrets.

#### `chroma.tf` & `chroma_user_data.sh.tftpl` — the vector DB

ChromaDB has no managed AWS offering, so we run it ourselves:

- `data.aws_ami.al2023` — find the latest Amazon Linux 2023 AMI.
- `aws_instance.chroma` — EC2 instance in a private subnet, no SSH, only
  reachable from API tasks on port 8000.
- `aws_ebs_volume.chroma_data` + `aws_volume_attachment` — separate data
  volume so the host can be rebuilt without losing embeddings.
- `templatefile("chroma_user_data.sh.tftpl", {...})` — boot script installs
  Docker, mounts the EBS volume, runs the Chroma container.

Notice how a separate data volume is the standard pattern when you need to
treat compute as ephemeral but data as durable.

#### `alb.tf` — the load balancer

One internet-facing ALB; one HTTP listener; default action routes to the
frontend; two listener rules peel off API paths to the API target group.

```
priority 100: /analyze* /report* /ticker* /history* /conversations*  → API
priority 110: /auth*    /health* /docs*    /openapi.json              → API
default:      everything else                                          → frontend
```

Two rules because each listener rule caps at 5 path-pattern values.

Both target groups use `target_type = "ip"` because Fargate tasks have their
own ENI (`awsvpc` network mode) — they register **by private IP**, not
instance ID.

Health checks:
- API: `GET /health` → 200, every 30s.
- Frontend: `GET /` → 200, every 30s.

Same-origin trick: because frontend & API share the same ALB hostname, the
browser calls them as the same origin → **no CORS** configuration needed.

#### `ecs.tf` — the cluster, services, autoscaling

- `aws_ecs_cluster.main` — the logical cluster.
- `aws_cloudwatch_log_group.api` / `.frontend` — destinations for container
  stdout.
- `aws_ecs_service.api` — long-running, in private subnets, registered with
  the API target group. Rolling update keeps capacity ≥ 100%.
- `aws_ecs_service.frontend` — same shape, smaller.
- `aws_appautoscaling_target` + `aws_appautoscaling_policy` — target-tracking
  on average CPU (60%), 1→3 tasks, slow scale-in.

The `lifecycle { ignore_changes = [desired_count] }` on the API service is
the important detail — autoscaling owns `desired_count`, so Terraform must
not fight it.

#### `task_definitions.tf` — container blueprints

Three task definitions:

- `api` — 1024 CPU / 4096 MB (needs torch + reranker).
- `frontend` — 256 / 512.
- `migrate` — 256 / 512, **one-shot**, command overridden to
  `["alembic", "upgrade", "head"]`. Same image as the API.

The migration task pattern is worth understanding cold: if migrations ran in
the API container's startup, N autoscaled tasks would race the same
`alembic upgrade head`. Pulling migrations into a one-shot Fargate task means
exactly one process runs them, on demand, off the critical path.

Notice the secrets/environment split inside the container definition:
- `environment` — non-sensitive: `REDIS_URL`, `CHROMA_HOST`, `CORS_ORIGINS`.
- `secrets` — sensitive, each entry has `valueFrom` an ARN. ECS resolves at
  launch.

#### `github_oidc.tf` — keyless CI authentication

Three resources:

- `aws_iam_openid_connect_provider.github` — registers GitHub's OIDC issuer
  as trusted in your AWS account.
- `aws_iam_role.github_actions` — the role that CI assumes. Its **trust
  policy** allows assumption only when (a) audience = `sts.amazonaws.com`,
  and (b) the JWT's `sub` claim matches `repo:<your-repo>:*`. Setting
  `var.github_repo` wrong simply prevents assumption — no risk of granting
  a stranger's repo access.
- `aws_iam_role_policy.github_deploy` — least-privilege permissions: push to
  the two ECR repos, run/update ECS tasks, `iam:PassRole` for **exactly** the
  two ECS roles, and read-only describe calls. It **cannot** touch RDS, read
  app secrets, or alter the network.

Interview point: contrast OIDC with the older pattern of stored access
keys — short-lived (1h), no secret to leak, scoped to one repo.

#### `cloudwatch.tf` — observability

- `aws_sns_topic.alerts` — every alarm publishes here.
- Optional email subscription via `count = var.alarm_email != "" ? 1 : 0`.
- Six metric alarms (ALB 5xx, unhealthy hosts, ECS CPU/mem, RDS CPU/storage).
- A dashboard with four widgets, body built with `jsonencode`.

The dashboard URL is exposed as an output for one-click access.

#### `outputs.tf` — the contract

Everything `deploy.sh` and the GitHub Actions workflow need: the registry
URLs, ECS service names, the migration task family, the API security group,
the ALB DNS, the dashboard URL, the OIDC role ARN.

`output "application_url"` is a friendly final value — paste into a browser
after deploy.

---

## 17. Security & secrets

### The four "where do secrets live" choices

| Where | OK? | Why |
|---|---|---|
| In a `.tf` file committed to git | NEVER | Anyone with read access to the repo has them forever. |
| In `terraform.tfvars` (gitignored) | OK for *plaintext source* on disk | Acceptable for the *input* to Terraform. |
| In **Secrets Manager / SSM Parameter Store** | YES (runtime) | Application reads at startup. |
| Baked into a Docker image | NEVER | Image is a redistributable artifact; layers leak. |

FinSight uses the first three correctly:

1. Real values live in `terraform.tfvars` (gitignored).
2. Terraform pushes them into **AWS Secrets Manager**.
3. The ECS task definition references the secrets **by ARN**; the ECS agent
   resolves them at container launch and injects them as env vars.

The value is *never* written to a Docker image or a task definition JSON.

### IAM — separation of duties

Two ECS roles, distinct trust + permissions:

- **Execution role** — what the *ECS agent* needs (pull image, read secret,
  write log).
- **Task role** — what the *application* needs at runtime (none, for FinSight).

This separation matters: a process escape inside the container only grants
the task role's permissions — it can't, for example, pull an arbitrary image
from ECR or read unrelated secrets, because those rights live on the
execution role and aren't available inside the container's metadata service.

### GitHub OIDC — no stored keys

Already covered. Replaces "create an IAM user, paste an access key into
GitHub Secrets" with "trust GitHub's OIDC issuer, gate it to your repo,
exchange tokens for ~1h credentials at run time".

### Defense in depth

The stack stacks several layers:

1. **VPC isolation** — RDS/Redis/Chroma have no public IP.
2. **Security-group chain** — even within the VPC, only the API can reach RDS.
3. **Secrets Manager** — no plaintext on disk or in images.
4. **Two-role IAM split** — runtime ≠ launch-time permissions.
5. **Short-lived OIDC creds** — CI can't leak a long-lived key.
6. **SSM Session Manager** — admin access to Chroma EC2 with no SSH port open.
7. **Encryption at rest** — RDS, EBS, ECR all `encrypted = true`.

---

## 18. Common pitfalls & debugging

### State drift

Someone clicks something in the AWS console. Terraform doesn't know. Next
`plan` either silently corrects it, or fails (e.g. the resource was deleted
manually and Terraform tries to update a thing that no longer exists).

**Fix:** `terraform plan -refresh-only` to see drift; if you want to keep
the manual change, edit the `.tf` to match; if not, `apply` to revert.

### Cycle errors

```
Error: Cycle: aws_security_group.a, aws_security_group.b
```

Two resources reference each other. Common with SGs that have ingress/egress
rules between them.

**Fix:** Extract the rules into separate `aws_security_group_rule` resources
so the SG definitions can be created independently, then the rules attach.

### "Forces replacement" on a critical resource

A change to an attribute that can't update in place (e.g. `aws_db_instance.engine`)
triggers `-/+`. Always read the plan.

**Fix:** Sometimes you can use `lifecycle { create_before_destroy = true }`
to avoid downtime; sometimes you have to accept replacement (and migrate
data); sometimes the cleanest path is `terraform import` of the existing
resource after a manual change.

### Sensitive output errors

```
Error: Output refers to sensitive values
```

If a value comes from a `sensitive = true` variable, the output must also be
`sensitive = true`.

### `apply` is stuck

RDS, NAT gateways, and ALB targets becoming healthy genuinely take several
minutes. `apply` is not stuck; check the AWS console.

### "Resource already exists"

Usually means the state file was lost or never had this resource. Either:

- `terraform import aws_vpc.main vpc-abc123` to adopt it, or
- Delete the existing AWS resource if it's safe.

### Provider version drift

Two engineers on different provider versions can produce diverging plans.
The `.terraform.lock.hcl` is committed to git precisely to prevent this.
Run `terraform init -upgrade` deliberately, then commit the updated lock file.

### Debugging logs

```bash
TF_LOG=DEBUG terraform apply
TF_LOG_PATH=./tf.log TF_LOG=TRACE terraform apply   # save to file
```

`TRACE` is verbose; `DEBUG` is usually enough.

### Targeted apply (use sparingly)

```bash
terraform apply -target=aws_vpc.main
```

Only acts on that resource and its dependencies. Useful when an `apply` is
partially failing and you want to make incremental progress. **Don't make
it a habit** — your state drifts from your code.

---

## 19. Best practices

A condensed checklist drawn from FinSight + general convention:

### Layout & style

- One `.tf` per concern; meaningful filenames (`vpc.tf`, `rds.tf`).
- Run `terraform fmt` before committing (and add it to CI).
- Run `terraform validate` in CI.
- Every variable has a `description`. Every output has a `description`.
- Use `local.name_prefix` to namespace every resource.
- Use `default_tags` to tag every resource without per-resource boilerplate.

### State

- Don't commit `terraform.tfstate`.
- For teams, use a remote backend (S3 + DynamoDB).
- One state per environment, never share `prod` and `staging`.
- `prevent_destroy` on production-critical resources (RDS, S3 buckets that
  hold data).

### Variables & secrets

- Sensitive variables → `sensitive = true`.
- Real secrets only in `terraform.tfvars` (gitignored) or `TF_VAR_*` env.
- Push secrets to Secrets Manager / SSM, never to `.tf` files or images.
- A `.tfvars.example` documents the shape without leaking values.

### Resources

- Prefer `for_each` over `count` when items are named (stable identity).
- `count` is fine for "give me N identical things".
- Add explicit `depends_on` only when there's no reference (rare).
- Use `lifecycle { ignore_changes = [...] }` when another system owns an
  attribute (autoscaling, autoscaling group AMI, etc.).

### CI / automation

- Lock provider versions (`required_providers` + `.terraform.lock.hcl`).
- Use OIDC, not stored keys, for cloud auth in CI.
- Run `terraform plan` on every PR, posted as a comment.
- Never `terraform apply` from a developer laptop in production once a team
  exists — go through CI.

### Cost & hygiene

- Tag *everything* (Project, Environment, ManagedBy).
- Set lifecycle policies on registries (FinSight keeps 10 images).
- Right-size the obvious cost centers (NAT gateway, RDS instance class).

---

## 20. Interview questions

Worked answers, grounded in this codebase.

### Q1. What is Terraform, and how is it different from a shell script?

A shell script is **imperative** — you write each `aws ec2 create-vpc` step.
Terraform is **declarative** — you describe the end state, and Terraform
computes the diff against reality. It's idempotent (re-runs are no-ops),
dependency-aware (it orders resources from the reference graph), and produces
a state file so you can reason about ownership and update in place.

### Q2. Walk me through `terraform init`, `plan`, `apply`, `destroy`.

- `init` — installs providers declared in `required_providers`, writes
  `.terraform.lock.hcl`, configures the backend, discovers modules.
- `plan` — read-only diff between code, state, and cloud. Outputs `+ / ~ / -`.
- `apply` — executes that plan (after re-displaying it and prompting `yes`).
- `destroy` — produces a plan that deletes everything Terraform manages.

### Q3. What is state, and why does it matter?

`terraform.tfstate` is the ledger mapping `resource "aws_vpc" "main"` to the
real AWS VPC ID and its attributes. Without it, Terraform can't compute a
diff. It must never be committed to git (often contains secrets), must never
be deleted (Terraform would forget it owns existing resources), and for a
team should live in a remote backend (S3 + DynamoDB lock) so concurrent
applies are serialized.

### Q4. How are dependencies between resources determined?

**Automatically, from references.** When `rds.tf` says
`vpc_security_group_ids = [aws_security_group.rds.id]`, Terraform builds a
dependency edge from the DB to the SG. You don't write `depends_on` for that.
You write `depends_on` only when ordering matters and there's no reference —
e.g. the NAT gateway depends on the internet gateway being attached, but
doesn't reference it.

### Q5. What's the difference between `count` and `for_each`?

`count = N` creates `[0..N-1]` instances, addressed by index. If you delete
the middle element of the input list, every later instance shifts and gets
recreated. `for_each = map_or_set` creates one instance per key, addressed
by key — adding/removing an entry only affects that one instance. Rule of
thumb: named items → `for_each`; "give me N copies" → `count`.

### Q6. Tell me about a `lifecycle` block in FinSight and why.

`infra/terraform/ecs.tf`:

```hcl
resource "aws_ecs_service" "api" {
  desired_count = var.api_desired_count

  lifecycle { ignore_changes = [desired_count] }
}
```

Once autoscaling exists, *it* owns `desired_count`. Without
`ignore_changes`, every `terraform apply` would set the count back to the
baseline (1) even after autoscaling had scaled to 3. The `lifecycle` block
tells Terraform "I made the initial value; from now on it isn't yours."

### Q7. How are secrets handled in FinSight?

In layers:

1. The real values are placed in `terraform.tfvars` (gitignored).
2. `infra/terraform/secrets.tf` creates one **Secrets Manager** entry per
   secret, with the value uploaded once.
3. The ECS task definition references each secret **by ARN** in its `secrets`
   block. The ECS agent resolves it at task launch and injects it as an
   environment variable inside the container.

The plaintext value is never inside a Docker image, never inside a task
definition JSON, and never in a committed file.

### Q8. Why does FinSight use GitHub OIDC instead of access keys?

A stored AWS access key is **long-lived** (valid until rotated) and
**stored** (leaks if the repo is compromised). OIDC federation removes both:
GitHub mints a short-lived JWT for each workflow run; AWS verifies the
signature + the `sub` claim against the role's trust policy and issues
~1-hour credentials. No AWS secret ever exists in GitHub. The trust policy
scopes acceptance to one repository, so a stolen token from another repo
is useless. This is in `infra/terraform/github_oidc.tf`.

### Q9. Walk me through `vpc.tf`'s network topology.

One VPC (`10.0.0.0/16`) spanning two AZs. Two tiers:

- **Public subnets** (10.0.1.0/24, 10.0.2.0/24) — ALB and NAT gateway.
- **Private subnets** (10.0.3.0/24, 10.0.4.0/24) — ECS tasks, RDS, Redis,
  Chroma. No public IP.

One internet gateway attached to the VPC; public route table sends
`0.0.0.0/0` to the IGW. One NAT gateway in the first public subnet; private
route table sends `0.0.0.0/0` to the NAT. Result: private resources can call
**out** (Anthropic, OpenAI, SEC) but nothing inbound from the internet
reaches them.

The one NAT (not one per AZ) is a deliberate portfolio-grade trade-off — a
single NAT is ~$32/mo; running two roughly doubles the biggest fixed cost.
Production would prefer one-per-AZ for fault tolerance.

### Q10. Why two listener rules on the ALB instead of one?

AWS limits a single listener rule to **5 path-pattern values**. FinSight
routes 9 API path prefixes, so they're split across two rules (priorities
100 and 110), both forwarding to the same target group. The default action
on the listener routes everything else to the frontend target group.

### Q11. Why is the migration a separate ECS task?

If `alembic upgrade head` ran inside the API container's startup, N
autoscaled tasks would race the same migration against the same database.
The `migrate` task definition (in `task_definitions.tf`) reuses the API
image but overrides the command, and is launched once per deploy with
`aws ecs run-task`. The schema change happens exactly once, off the
critical path.

### Q12. How would you turn this stack into multi-environment (dev/staging/prod)?

Options:

1. **Workspaces** — `terraform workspace new staging`; each workspace gets
   its own state. Same `.tf` code, parameterise by `terraform.workspace`.
   Simple, but you still share one state backend key prefix.
2. **Directory per environment** — `infra/terraform/prod/`, `.../staging/`,
   each with its own `.tfvars` and possibly its own backend key. Pulls
   shared logic into modules. More boilerplate, clearer blast radius.
3. **Terraform Cloud / Spacelift / Atlantis** — managed orchestration with
   workspaces, run history, PR previews.

For FinSight today, option 2 with a single `modules/` directory containing
`vpc`, `data-stores`, `ecs-app` would be the natural step.

### Q13. How would you add HTTPS?

Three pieces:

1. Request an **ACM certificate** for your domain in the same region as the
   ALB (`aws_acm_certificate`).
2. Validate it via DNS (Route 53 if your zone is in AWS:
   `aws_route53_record` + `aws_acm_certificate_validation`).
3. Add a `443` listener to the ALB with `certificate_arn`, `protocol =
   "HTTPS"`, and the same two path rules. Optionally redirect HTTP→HTTPS on
   port 80.

You'd also create a Route 53 alias record pointing your hostname at the ALB.

### Q14. The plan shows `# forces replacement` on the RDS instance. What now?

Read which attribute. Some changes (storage type, engine version) must
recreate the database — that's data loss. Mitigations:

1. Avoid the change (often, a minor-version change is in-place).
2. Take a **snapshot** before the apply (`final_snapshot_identifier` rather
   than `skip_final_snapshot = true`).
3. Add `lifecycle { prevent_destroy = true }` on production RDS as a
   seatbelt so an accidental `apply` errors instead of replacing.
4. Plan a controlled migration: create the new instance in parallel
   (`create_before_destroy`), migrate data, switch the app.

### Q15. Provider versions — `~> 5.60` vs `= 5.60.0` vs `>= 5.60`?

- `~> 5.60` — pessimistic. Allows any `5.x` ≥ 5.60 but rejects `6.x`. Best
  default — lets you pick up bug fixes without surprise major bumps.
- `= 5.60.0` — exact. Maximum reproducibility, but you miss every patch.
- `>= 5.60` — open-ended. You'll silently jump major versions someday.

Either way, `.terraform.lock.hcl` pins the exact version chosen at
`terraform init` time. Commit it.

### Q16. How does `for_each` use a `local`?

In `infra/terraform/secrets.tf`:

```hcl
locals {
  secrets = {
    claude-api-key = var.claude_api_key
    ...
  }
}

resource "aws_secretsmanager_secret" "app" {
  for_each = local.secrets
  name     = "${local.name_prefix}/${each.key}"
}
```

`local.secrets` is a map. `for_each` iterates over it; inside the block,
`each.key` is the secret slug and `each.value` is the raw value. Resources
are addressed as `aws_secretsmanager_secret.app["claude-api-key"]`. Adding
a new entry creates only that secret; removing one destroys only that one.

### Q17. What does `default_tags` give you?

A provider-level block that tags **every** resource the provider creates,
without writing `tags = {...}` on each one. FinSight uses it for `Project`,
`Environment`, `ManagedBy` — so the AWS billing console can filter "show me
costs for finsight-prod" with one click, and a `terraform destroy` that
fails halfway leaves orphaned resources that are easy to find.

### Q18. Talk me through `outputs.tf` and why it matters.

It's the **contract** between Terraform and everything that runs *after*
Terraform: `deploy.sh`, GitHub Actions, humans. Examples:

- `ecr_api_repository_url` — `docker push` target.
- `application_url` — what to paste into a browser.
- `migration_task_family` + `ecs_api_security_group_id` + `private_subnet_ids`
  — exactly what `aws ecs run-task` needs to launch the migration.
- `github_actions_role_arn` — the value to set as the GitHub
  `AWS_DEPLOY_ROLE_ARN` variable.

Without outputs, every downstream tool would have to re-discover these by
calling AWS APIs. Outputs centralize them.

### Q19. How would you migrate this to a remote backend?

1. Create an S3 bucket (`finsight-tfstate`) with **versioning** and
   **server-side encryption** enabled.
2. Create a DynamoDB table (`finsight-tflock`) with `LockID` as the partition
   key, **on-demand billing**.
3. Uncomment the `backend "s3" {...}` block in `versions.tf`.
4. Run `terraform init -migrate-state` — Terraform copies the local state
   to S3.
5. Delete the local `terraform.tfstate` (it's been migrated). Add it to
   `.gitignore` if not already.
6. Now any engineer with AWS creds + the repo can `apply`, and locking
   prevents concurrent runs.

### Q20. What's the most expensive resource in this stack and why?

The NAT gateway, at ~$32/mo + data processing. Reasons:
- It runs 24/7.
- AWS charges per hour and per GB processed.
- It's an architectural necessity — without it, private resources can't
  reach the internet (Anthropic, OpenAI, SEC EDGAR).

Alternatives if cost were critical: VPC endpoints for AWS services (so calls
to ECR, S3, Secrets Manager skip the NAT), or a **NAT instance** (a t4g.nano
running Linux NAT, ~$3/mo) for non-HA setups.

---

## 21. Glossary

| Term | Meaning |
|---|---|
| **IaC** | Infrastructure as Code — provisioning via versioned text files. |
| **HCL** | HashiCorp Configuration Language — Terraform's DSL. |
| **Provider** | Plugin that wraps a cloud's API (AWS, GCP, Azure, …). |
| **Resource** | A managed cloud object (`aws_vpc`, `aws_db_instance`, …). |
| **Data source** | A read-only lookup of something that exists or that the provider returns. |
| **State** | The file (`terraform.tfstate`) mapping code → real cloud objects. |
| **Backend** | Where the state file lives (local, S3, GCS, Terraform Cloud, …). |
| **Plan** | The diff between code, state, and reality — read-only. |
| **Apply** | Execute the plan; make changes in the cloud. |
| **Module** | A reusable directory of `.tf` files, called from elsewhere. |
| **Workspace** | Multiple states inside one backend (one per env). |
| **Output** | A value exposed after apply, for humans or scripts. |
| **Local** | A named expression in a `locals { ... }` block. |
| **Variable** | An input to the configuration. |
| **Meta-argument** | Special argument accepted by any resource (`count`, `for_each`, `lifecycle`, `depends_on`, `provider`). |
| **Splat (`[*]`)** | Get an attribute across all instances of a counted/`for_each`'d resource. |
| **`templatefile`** | Function that renders a template file with HCL variables. |
| **OIDC** | OpenID Connect — federated identity, used by GitHub Actions to assume an IAM role with no stored keys. |
| **Secrets Manager** | AWS service that stores secrets and lets ECS resolve them at task launch. |
| **Fargate** | "Serverless" mode of ECS — AWS places containers, you pay per task. |
| **awsvpc** | ECS network mode where each task gets its own ENI (private IP). |
| **Target type `ip`** | ALB target group registers by IP, required for Fargate `awsvpc`. |
| **NAT gateway** | Lets private-subnet resources reach the internet outbound, while remaining unreachable inbound. |
| **Subnet group** | RDS/ElastiCache concept — which subnets the managed DB may live in. |
| **`-/+`** | Plan symbol meaning "destroy and recreate" — read carefully. |

---

## Appendix A — Quick command reference

```bash
# Setup
terraform init                              # download providers, set up backend
terraform init -upgrade                     # bump providers within constraints
terraform init -migrate-state               # move state to a new backend

# Day-to-day
terraform fmt -recursive                    # canonical formatting
terraform validate                          # static checks
terraform plan                              # preview changes
terraform plan -out tfplan                  # save the plan
terraform apply                             # apply, prompts yes
terraform apply tfplan                      # apply a saved plan exactly
terraform apply -auto-approve               # CI use — skip prompt
terraform apply -target=aws_vpc.main        # narrow scope (use sparingly)
terraform apply -replace=aws_instance.x     # force one resource to recreate
terraform destroy                           # tear it all down

# Inspect
terraform output                            # all outputs
terraform output -raw rds_endpoint          # one output, no quotes
terraform state list                        # all addresses in state
terraform state show aws_vpc.main           # one resource's full state
terraform show                              # entire state, human-readable

# Surgery
terraform state mv OLD NEW                  # rename without recreating
terraform state rm aws_vpc.main             # forget (does NOT delete cloud)
terraform import aws_vpc.main vpc-abc123    # adopt existing into state

# Debug
TF_LOG=DEBUG terraform apply                # verbose
TF_LOG=TRACE TF_LOG_PATH=tf.log terraform apply
```

---

## Appendix B — A 90-second elevator pitch for FinSight's infra

> FinSight is a multi-agent RAG application deployed on AWS as code with
> Terraform. The infrastructure is a single VPC across two availability zones
> with a public/private subnet pair in each. The Application Load Balancer
> sits in the public tier as the only internet-facing entry point; it
> path-routes traffic to two ECS Fargate services — a FastAPI backend and a
> Next.js frontend — running in the private tier. The backend reaches
> Postgres on RDS, Redis on ElastiCache, and a self-hosted ChromaDB on EC2,
> all in private subnets. External APIs (Anthropic, OpenAI, SEC EDGAR) are
> reached via a single NAT gateway. Secrets live in Secrets Manager and are
> injected into containers at launch via the ECS task definition's
> `valueFrom` ARN — never baked into images or task definitions. CI/CD runs
> in GitHub Actions, which assumes an IAM role via OIDC federation rather
> than storing access keys; the role is scoped to one repository by its
> trust policy. Observability is CloudWatch — six metric alarms publish to
> an SNS topic, and a single dashboard shows ALB request volume + 5xx, ECS
> CPU/memory, RDS CPU/storage. `terraform apply` builds the entire stack
> from scratch in ~10–15 minutes; `terraform destroy` removes it cleanly,
> with `recovery_window_in_days = 0` on the secrets so the names free up
> immediately for a re-apply.

Good luck — you've got plenty of concrete material here. Walk an interviewer
through `infra/terraform/` file by file and you'll come across as someone
who's actually built and operated this, not just memorised concepts.

---

## Appendix C — AWS services & abbreviations reference

A complete catalogue of every AWS service and acronym that touches the
FinSight stack. Each entry answers four questions:

- **What is it?**
- **What is it used for?**
- **Why do we need it?**
- **How does it work on AWS?**

Plus a "**In FinSight**" line pointing at the file and resource that uses it.

> Mental shortcut: most AWS service names start with **E** for "Elastic"
> (= managed / scales for you) or **A** for "Amazon" (managed) or **AWS**
> (cross-service). The naming is uneven — don't read meaning into it.

### Index by category

- **Compute & containers** — EC2, ECS, Fargate, ECR, AMI, ENI, ASG vs App Auto Scaling
- **Networking** — VPC, Subnet, IGW, NAT GW, EIP, Route Table, ALB/ELB, Target Group, Security Group, NACL, CIDR, AZ, Region, Route 53, ACM, VPC Endpoint, CloudFront, AWS Global Accelerator
- **Storage & databases** — S3, EBS, RDS, ElastiCache, DynamoDB
- **Security & identity** — IAM, STS, OIDC, KMS, Secrets Manager, SSM, ARN
- **Observability & messaging** — CloudWatch (Logs / Metrics / Alarms / Dashboards), SNS, SQS, EventBridge
- **Account-level** — Account ID, Billing & Cost Explorer, AWS CLI

---

### Compute & containers

#### EC2 — Elastic Compute Cloud

- **What it is:** AWS's virtual machine service. You pick an OS image (AMI),
  an instance type (CPU/memory), a network, and AWS runs the VM for you.
- **What it's used for:** Anything that doesn't fit a higher-level managed
  service: a long-running daemon, a self-hosted database, a custom server.
- **Why we need it:** ChromaDB has no managed AWS equivalent. We need real
  Linux to run the Chroma container with persistent storage.
- **How it works on AWS:** You launch an `aws_instance` with an AMI, instance
  type, subnet, security group, and (optionally) user-data — a boot script
  that runs the first time the VM starts. AWS bills per second of running
  time. Stop the instance and you pay only for the attached EBS storage.
- **In FinSight:** `infra/terraform/chroma.tf` runs one `t3.small` instance
  in a private subnet, bootstrapped by `chroma_user_data.sh.tftpl`.

#### ECS — Elastic Container Service

- **What it is:** AWS's container orchestrator. The competitor to Kubernetes
  for AWS-only workloads.
- **What it's used for:** Run Docker containers as long-lived services (with
  auto-restart, rolling updates, health checks) or one-off tasks.
- **Why we need it:** Our app is a Docker image. ECS handles "keep N copies
  running, replace unhealthy ones, route traffic to them." We don't want to
  manage that by hand.
- **How it works on AWS:** Three concepts you must know cold:
  - **Cluster** — a logical home for services and tasks.
  - **Task definition** — the blueprint for a container (image, CPU, memory,
    env, secrets, ports). Like a class.
  - **Task** — one running instance of a task definition. Like an object.
  - **Service** — a controller that keeps *N* tasks running, replaces dead
    ones, and registers them with the load balancer.
- **In FinSight:** `infra/terraform/ecs.tf` (cluster + services),
  `task_definitions.tf` (the three blueprints — `api`, `frontend`, `migrate`).

#### Fargate

- **What it is:** A **launch type** for ECS (and EKS) where AWS owns the
  underlying servers. You declare "I want 1 vCPU and 4 GB"; AWS finds the
  hardware and places the container. There is no EC2 to patch.
- **What it's used for:** Running containers without managing servers.
- **Why we need it:** A portfolio project shouldn't be patching EC2 hosts
  every Tuesday. Fargate trades a small per-vCPU premium for zero ops on the
  compute fleet.
- **How it works on AWS:** Set `launch_type = "FARGATE"` on an ECS service.
  AWS schedules the task onto its managed capacity, gives it a private IP
  in the VPC (via the `awsvpc` network mode), and bills per second.
- **In FinSight:** `aws_ecs_service.api` and `aws_ecs_service.frontend` both
  use `launch_type = "FARGATE"`.

#### ECR — Elastic Container Registry

- **What it is:** A private Docker image registry, the AWS equivalent of
  Docker Hub but inside your account.
- **What it's used for:** Storing the API and frontend Docker images that
  ECS pulls when it launches tasks.
- **Why we need it:** Your Docker images contain your application code (and
  in our case the embedded reranker model). Pushing them to a private
  registry inside the VPC's reach is faster, secure, and free of public
  rate limits.
- **How it works on AWS:** Each `aws_ecr_repository` is a registry with a URL
  like `12345.dkr.ecr.eu-central-1.amazonaws.com/finsight-prod-api`. You
  `docker login` to it once with a short-lived token from
  `aws ecr get-login-password`, then `docker push` like any other registry.
  Lifecycle policies expire old image versions automatically.
- **In FinSight:** `infra/terraform/ecr.tf` defines two repos with a 10-image
  retention policy.

#### AMI — Amazon Machine Image

- **What it is:** A preconfigured disk image used to launch an EC2 instance:
  the OS, drivers, sometimes preinstalled software.
- **What it's used for:** Specifying "boot this VM with Amazon Linux 2023"
  (or Ubuntu, or Windows, or your custom image).
- **Why we need it:** Every EC2 launch needs an AMI ID. We use the latest
  Amazon Linux 2023 — minimal, secure defaults, free.
- **How it works on AWS:** AMIs are region-specific (an AMI ID in
  `eu-central-1` doesn't exist in `us-east-1`). To stay region-agnostic, use
  a `data "aws_ami"` block that looks up by name pattern + filter.
- **In FinSight:** `data "aws_ami" "al2023"` in `chroma.tf` finds the most
  recent `al2023-ami-2023.*-x86_64`.

#### ENI — Elastic Network Interface

- **What it is:** A virtual network card. Every EC2 instance and every
  Fargate task gets at least one ENI, which has a private IP in a subnet
  and one or more security groups attached.
- **What it's used for:** Giving compute resources their own IP, MAC address,
  and security boundary inside the VPC.
- **Why we need it:** Without ENIs, Fargate tasks couldn't have unique
  private IPs (and the ALB couldn't target them by IP).
- **How it works on AWS:** Created implicitly when you launch an EC2/ECS
  task with `network_mode = "awsvpc"`. The ENI lives in a subnet, has a
  fixed private IP for the task's lifetime, and is destroyed when the task
  is.
- **In FinSight:** Implicit. The ALB target group `target_type = "ip"` in
  `alb.tf` works because each Fargate task has its own ENI/IP.

#### ASG vs Application Auto Scaling

- **ASG (Auto Scaling Group):** scales **EC2 instances** up and down.
  We don't use it because we don't manage EC2 fleets — Fargate handles
  capacity.
- **Application Auto Scaling:** a separate AWS service that scales
  *non-EC2* things: ECS services, DynamoDB tables, Aurora replicas, etc.
- **What it's used for:** Keeping a metric (e.g. CPU) near a target by
  scaling tasks/replicas in or out.
- **Why we need it:** Traffic spikes hit one API task; one task gets hot;
  Application Auto Scaling spins up a second.
- **How it works on AWS:** You register a **scalable target** (the thing to
  scale, with min/max bounds), then attach a **scaling policy**. The most
  common policy is **target tracking** — "keep average CPU at 60%" — which
  AWS implements via internal CloudWatch alarms.
- **In FinSight:** `aws_appautoscaling_target.api` + `aws_appautoscaling_policy.api_cpu`
  in `ecs.tf`. Scales the API service between 1 and 3 tasks at 60% CPU.

---

### Networking

#### VPC — Virtual Private Cloud

- **What it is:** A private, isolated network inside AWS, defined by a CIDR
  block. Everything you build lives in a VPC.
- **What it's used for:** Isolating your resources from other AWS customers
  and from the public internet by default.
- **Why we need it:** Without a VPC, your database would have to be on the
  public internet. With a VPC, RDS sits in a private subnet that has no
  route to the internet for inbound traffic at all.
- **How it works on AWS:** A VPC is a region-scoped, software-defined
  network. You carve it into subnets, attach gateways, and configure route
  tables. Resources placed in the VPC get private IPs from your CIDR.
- **In FinSight:** `infra/terraform/vpc.tf`. One VPC at `10.0.0.0/16`.

#### Subnet

- **What it is:** A slice of the VPC's CIDR, tied to a single Availability
  Zone.
- **What it's used for:** Placing resources into specific AZs (for HA) and
  separating "public" from "private" via routing.
- **Why we need it:** AWS requires every IP-bearing resource (EC2, RDS,
  ENIs) to live in a subnet. A subnet's routing determines what counts as
  "public" or "private".
- **How it works on AWS:**
  - **Public subnet** = route table sends `0.0.0.0/0` to an Internet Gateway.
  - **Private subnet** = route table sends `0.0.0.0/0` to a NAT Gateway
    (outbound only) or nowhere.
- **In FinSight:** Two public + two private subnets, each pair in different
  AZs. `aws_subnet.public[0..1]` and `aws_subnet.private[0..1]`.

#### IGW — Internet Gateway

- **What it is:** A horizontally-scaled, redundant gateway that connects a
  VPC to the public internet.
- **What it's used for:** Giving public subnets a path to/from the internet.
- **Why we need it:** Without an IGW, even a "public" subnet can't reach the
  internet. The ALB and NAT both need this path.
- **How it works on AWS:** Attach exactly one IGW to a VPC. Add a route
  `0.0.0.0/0 → igw-...` in a public route table. Any subnet associated with
  that route table becomes "public" — but a resource still needs a *public
  IP* to be reachable.
- **In FinSight:** `aws_internet_gateway.main` in `vpc.tf`.

#### NAT GW — NAT Gateway (Network Address Translation)

- **What it is:** A managed device that lets resources in private subnets
  make **outbound** connections to the internet, while remaining unreachable
  from the internet.
- **What it's used for:** Letting private resources call Anthropic, OpenAI,
  and the SEC EDGAR API without exposing themselves.
- **Why we need it:** API tasks need to reach external HTTPS endpoints. They
  must not be reachable from the internet. NAT solves exactly that.
- **How it works on AWS:** A NAT gateway lives in a *public* subnet (it
  needs an IGW). It has an Elastic IP. Outbound packets from a private subnet
  hit the private route table's `0.0.0.0/0 → nat-...` rule, get rewritten to
  use the NAT's public IP, and go out via the IGW. Return packets reverse
  the translation. **It's expensive** — ~$32/mo plus per-GB processing.
- **In FinSight:** One `aws_nat_gateway.main` (cost saving — production would
  run one per AZ).

#### EIP — Elastic IP

- **What it is:** A static, public IPv4 address you reserve in your AWS
  account.
- **What it's used for:** Attaching to a NAT gateway (or an EC2 instance you
  want a fixed IP for). The IP stays the same even if the resource is
  replaced.
- **Why we need it:** A NAT gateway needs an EIP so its outbound traffic
  has a stable source IP — useful when an external API allowlists your IP.
- **How it works on AWS:** Allocate one (`aws_eip`); it's tied to your
  account until you release it. Charged a small fee if idle, free while
  attached to a running resource (NAT/EC2).
- **In FinSight:** `aws_eip.nat` in `vpc.tf`, allocated for the NAT gateway.

#### Route Table

- **What it is:** A list of routing rules: "for traffic to this CIDR, send
  it through that gateway/interface."
- **What it's used for:** Deciding where outbound traffic from each subnet
  goes.
- **Why we need it:** A subnet only becomes "public" because its route table
  says `0.0.0.0/0 → igw-...`. Routing is what makes the distinction real.
- **How it works on AWS:** Every VPC has a default route table. You create
  your own with `aws_route_table`, add routes with `route { ... }` blocks,
  and associate subnets to it with `aws_route_table_association`.
- **In FinSight:** Two route tables in `vpc.tf` — public (→ IGW) and private
  (→ NAT). Each pair of subnets associates with its tier's table.

#### ALB / ELB — Application / Elastic Load Balancer

- **What it is:** AWS's HTTP(S) load balancer. **ELB** is the umbrella name;
  the three types are **ALB** (layer 7, HTTP/HTTPS, our choice), **NLB**
  (layer 4, TCP/UDP, high-throughput), and **CLB** (classic, legacy).
- **What it's used for:** Spreading traffic across multiple backend tasks,
  performing health checks, terminating TLS, doing path-based routing.
- **Why we need it:** Two backend services (API and frontend) share one
  public hostname; the ALB routes by URL path so the browser sees a single
  origin (= no CORS). It also health-checks tasks and stops sending traffic
  to unhealthy ones.
- **How it works on AWS:** An ALB has **listeners** (port + protocol), each
  with **rules** that match request attributes (path, host, headers) and
  forward to a **target group**. Target groups contain the actual backends.
- **In FinSight:** `aws_lb.main`, `aws_lb_listener.http`, two
  `aws_lb_listener_rule` for API paths, and two `aws_lb_target_group`s.

#### Target Group

- **What it is:** A pool of backend targets (IPs or instances) that an ALB
  forwards traffic to. Health-checks happen here.
- **What it's used for:** Grouping the backend tasks for one service so the
  ALB can route to them as a unit.
- **Why we need it:** Without a target group, the ALB has nothing to forward
  *to*. Each service needs its own group because they have different ports
  and health check paths.
- **How it works on AWS:** `target_type = "ip"` for Fargate (each task has
  its own ENI/IP); `"instance"` for EC2 ASGs. Health check path + interval
  + thresholds determine when a target is "healthy."
- **In FinSight:** `aws_lb_target_group.api` (port 8000, health `/health`)
  and `aws_lb_target_group.frontend` (port 3000, health `/`).

#### Security Group (SG)

- **What it is:** A virtual, stateful firewall attached to an ENI (so:
  EC2 instance / Fargate task / RDS / ElastiCache).
- **What it's used for:** Allowing or denying traffic at the *resource*
  level. "This task accepts TCP 8000 from the ALB only."
- **Why we need it:** Even within the VPC, you want least-privilege —
  the database accepts traffic *only* from the API tasks, not from anything
  else in the same VPC.
- **How it works on AWS:**
  - **Stateful:** allowed inbound returns automatically — you don't write
    matching egress rules.
  - **Default outbound = all allowed.** You typically restrict ingress only.
  - **Reference by SG, not CIDR:** `security_groups = [aws_security_group.alb.id]`
    means "allow from anything wearing this SG." More flexible than CIDRs.
- **In FinSight:** `security_groups.tf` defines the chain
  `alb → ecs_api → rds / redis / chroma`, each accepting from the one
  in front of it.

#### NACL — Network Access Control List

- **What it is:** A *stateless*, subnet-level firewall.
- **What it's used for:** A coarser, defense-in-depth layer beneath SGs.
- **Why we need it:** Most stacks don't. Default NACLs allow all traffic;
  FinSight uses only security groups.
- **How it works on AWS:** Numbered ordered rules (lowest first), allow or
  deny, applied at the subnet boundary. Because they're stateless, you
  must write *both* inbound and outbound rules for the same flow.
- **In FinSight:** Not used — security groups are sufficient.

#### CIDR — Classless Inter-Domain Routing

- **What it is:** Notation for an IP address range:
  `10.0.0.0/16` = "the first 16 bits are the network, the last 16 are hosts"
  = 65,536 addresses (`10.0.0.0` – `10.0.255.255`).
- **What it's used for:** Sizing VPCs and subnets, writing firewall rules.
- **Why we need it:** Every VPC, subnet, and security group rule is defined
  in CIDR terms.
- **How it works on AWS:** AWS reserves the first 4 + last 1 IPs in every
  subnet (broadcast, DNS, gateway). A `/24` (256 addresses) gives you 251
  usable.
- **In FinSight:** VPC = `/16` (~65k IPs), each subnet = `/24` (~250 IPs).
  Way more headroom than needed.

#### AZ — Availability Zone & Region

- **What it is:** **Region** = a geographic area (e.g. `eu-central-1` =
  Frankfurt). **AZ** = an isolated datacenter cluster within a region
  (e.g. `eu-central-1a`, `1b`, `1c`).
- **What it's used for:** Spreading resources across AZs for fault
  tolerance. Each AZ is isolated — power, network, cooling.
- **Why we need it:** If one AZ goes down, an HA stack with resources in
  another AZ keeps serving. RDS multi-AZ, ECS tasks across AZs, etc.
- **How it works on AWS:** AZs in a region are connected by low-latency
  links. Most managed services let you opt into multi-AZ. You select AZs
  by name (`eu-central-1a`) or by data source.
- **In FinSight:** `data.aws_availability_zones.available` picks the first
  two AZs in the region; subnets spread across them.

#### Route 53

- **What it is:** AWS's managed DNS service.
- **What it's used for:** Pointing a custom domain (e.g. `finsight.com`)
  at the ALB, or at any AWS or external endpoint.
- **Why we need it:** We *don't*, in this portfolio build — the app is
  reached at the raw ALB hostname. You'd need Route 53 to add HTTPS with
  a real domain.
- **How it works on AWS:** You buy/host a **hosted zone** for your domain.
  Inside it, **records** (A, CNAME, MX, …) map hostnames to addresses.
  Route 53 has a special **alias record** that resolves to AWS targets (ALB,
  CloudFront) without an extra DNS hop.
- **In FinSight:** Not used. Referenced in the HTTPS section of
  `docs/deployment/README.md` as the path to TLS.

#### ACM — AWS Certificate Manager

- **What it is:** A free service that issues and auto-renews TLS
  certificates for AWS-hosted services.
- **What it's used for:** TLS on an ALB, CloudFront, or API Gateway.
- **Why we need it:** To add HTTPS to the ALB without paying for or
  hand-rotating certs.
- **How it works on AWS:** Request a cert for a domain; ACM proves you own
  the domain via DNS or email; it issues a cert tied to your account that
  AWS services can attach. Certs auto-renew before expiry.
- **In FinSight:** Not used today; required if/when HTTPS is added.

#### VPC Endpoint

- **What it is:** A private connection from your VPC to an AWS service,
  bypassing the public internet (and thus the NAT gateway).
- **What it's used for:** Cost optimization (skip NAT data charges) and a
  small security improvement (traffic to ECR/S3/Secrets Manager doesn't
  leave the AWS network).
- **Why we need it:** Not strictly needed; useful if NAT data costs grow.
- **How it works on AWS:** Two types — **Gateway endpoints** (S3, DynamoDB
  — free, route-table-based) and **Interface endpoints** (most others — ENI
  in your VPC, ~$7/mo per endpoint per AZ).
- **In FinSight:** Not used. Possible future optimization.

#### CloudFront

- **What it is:** AWS's global CDN — caches content at edge locations
  worldwide.
- **What it's used for:** Speeding up static-asset delivery to faraway
  users, terminating TLS at the edge, DDoS protection (with AWS Shield).
- **Why we need it:** Not for a portfolio demo. Would be relevant if the
  app were globally popular.
- **How it works on AWS:** A **distribution** sits in front of your origin
  (ALB, S3, custom). Requests hit the nearest edge POP; cache hits return
  immediately, cache misses fetch from the origin.
- **In FinSight:** Not used.

#### AWS Global Accelerator

- **What it is:** Two static **anycast** IPs that route users to your AWS
  endpoints over AWS's backbone network.
- **What it's used for:** Faster, more reliable global access for
  TCP/UDP services (not HTTP-only — that's CloudFront's job).
- **Why we need it:** Not in scope.
- **In FinSight:** Not used.

---

### Storage & databases

#### S3 — Simple Storage Service

- **What it is:** Object storage. You upload files ("objects") into
  "buckets" via HTTP. Effectively infinite capacity, very durable
  (11 9's), cheap.
- **What it's used for:** Static assets, backups, build artifacts, large
  files, and — critically for Terraform — **remote state storage**.
- **Why we need it:** FinSight doesn't ship application data to S3 today,
  but the **commented-out S3 backend** in `versions.tf` is how we'd move
  Terraform state to a team-shareable location.
- **How it works on AWS:** Buckets are globally-named. Within a bucket,
  objects have keys (paths). Bucket policies and IAM control access.
  Versioning lets you keep historical versions; encryption is on by default.
- **In FinSight:** Not currently used; scaffolded in `versions.tf` as the
  remote state target.

#### EBS — Elastic Block Store

- **What it is:** Network-attached block storage (like a virtual hard drive)
  for EC2 instances.
- **What it's used for:** The disk that an EC2 boots from, and any extra
  data volumes attached to it.
- **Why we need it:** ChromaDB needs durable storage that survives instance
  replacement. Mounting a separate EBS volume to `/data/chroma` means we
  can rebuild the host without losing embeddings.
- **How it works on AWS:** An EBS volume is bound to a single AZ (matches
  the instance's AZ). You attach it like a disk; the OS formats and mounts
  it. Types include `gp3` (general SSD, our choice), `io2` (high-IOPS SSD),
  `st1` (throughput HDD). All can be encrypted with KMS.
- **In FinSight:** `aws_ebs_volume.chroma_data` (8 GiB gp3, encrypted) +
  `aws_volume_attachment` in `chroma.tf`. The boot script formats it on
  first launch and adds it to `/etc/fstab`.

#### RDS — Relational Database Service

- **What it is:** Managed relational databases (Postgres, MySQL, MariaDB,
  Oracle, SQL Server, Aurora).
- **What it's used for:** Running a production database without managing
  the OS, the engine, backups, or replication.
- **Why we need it:** We need Postgres. We don't want to run it on EC2 and
  patch it monthly. RDS handles all of that.
- **How it works on AWS:** You pick an engine + version, instance class
  (`db.t3.micro`), storage, and a subnet group. RDS provisions the DB in
  one or two AZs (single-AZ vs **multi-AZ** — the latter has a synchronous
  standby that AWS fails over to automatically). Automated backups, point-in-time
  recovery, snapshots are built-in.
- **In FinSight:** `aws_db_instance.main` in `rds.tf` — Postgres 16,
  single-AZ, encrypted gp3 storage, in private subnets, reachable only
  from the API tasks' SG.

#### ElastiCache

- **What it is:** Managed Redis or Memcached.
- **What it's used for:** In-memory cache for hot data, session stores,
  rate-limit counters, query-embedding caches.
- **Why we need it:** The app caches OpenAI embeddings of recent queries
  (so we don't pay for the same embedding twice), holds rate-limit counters,
  and stores ephemeral session data.
- **How it works on AWS:** A "cluster" can be a single Redis node or a
  primary + replicas. ElastiCache patches the engine, monitors it, and (if
  you opt into "replication groups") fails over automatically.
- **In FinSight:** `aws_elasticache_cluster.main` in `elasticache.tf` — one
  Redis 7.1 node, `cache.t3.micro`, private subnets, accessible only from
  the API tasks' SG.

#### DynamoDB

- **What it is:** AWS's managed NoSQL key-value/document database. Massive
  scale, single-digit-ms reads, pay-per-request.
- **What it's used for:** Tables, sessions, leaderboards, IoT — anywhere a
  schemaless KV store fits.
- **Why we need it:** FinSight's application doesn't use DynamoDB. It's
  *referenced* as the **lock table** for the S3 Terraform backend: a tiny
  table with one item per state file, used to ensure two engineers can't
  `apply` simultaneously.
- **How it works on AWS:** Tables with a **partition key** (and optional
  sort key). On-demand billing (per request) or provisioned (per RCU/WCU).
  Built-in replication (DAX cache, Global Tables).
- **In FinSight:** Mentioned in `versions.tf` and §6/§15 of this guide as
  the state-lock table.

---

### Security & identity

#### IAM — Identity and Access Management

- **What it is:** The AWS service for *who can do what*. Defines users,
  groups, roles, and policies.
- **What it's used for:** Granting permissions to humans, services, and
  third-party systems.
- **Why we need it:** Everything in AWS is permission-checked against IAM.
  ECS needs IAM roles to pull images and read secrets; GitHub Actions needs
  an IAM role to deploy.
- **How it works on AWS:** Four primitives:
  - **User** — a human or long-lived programmatic identity (avoid; prefer
    roles).
  - **Group** — a collection of users (just for policy attachment).
  - **Role** — an *identity that something can assume temporarily*. Used by
    services (EC2, ECS) and federated identities (GitHub OIDC).
  - **Policy** — a JSON document granting/denying specific actions on
    specific resources.
  Permissions are *additive* (no implicit allow) and *deny overrides allow*.
- **In FinSight:** `iam.tf` (ECS execution + task roles, Chroma EC2 instance
  profile) and `github_oidc.tf` (the deploy role).

#### STS — Security Token Service

- **What it is:** The AWS service that mints *temporary* credentials.
- **What it's used for:** Whenever something **assumes a role**, STS hands
  back short-lived (15 min – 12 h) access keys.
- **Why we need it:** It's the engine underneath OIDC federation, role
  assumption from the CLI (`aws sts assume-role`), and ECS task credentials.
- **How it works on AWS:** Call `AssumeRole` (with creds) or
  `AssumeRoleWithWebIdentity` (with an OIDC token); AWS verifies the trust
  policy of the target role and returns temporary access key + secret +
  session token.
- **In FinSight:** Implicit — every GitHub Actions deploy call to
  `AssumeRoleWithWebIdentity` is STS at work.

#### OIDC — OpenID Connect

- **What it is:** A standards-based identity protocol built on OAuth 2.0.
  Lets one system "vouch for" identities to another by signing short-lived
  JWT tokens.
- **What it's used for:** Federating CI systems (GitHub Actions, GitLab,
  Bitbucket, …) to AWS without storing access keys.
- **Why we need it:** Storing a long-lived AWS access key in GitHub is a
  liability. OIDC lets GitHub mint a fresh, signed token per workflow run;
  AWS trades it for ~1h credentials.
- **How it works on AWS:**
  1. Register GitHub's OIDC issuer as a trusted provider
     (`aws_iam_openid_connect_provider`).
  2. Create an IAM role whose **trust policy** accepts assumption only when
     the token's `sub` claim matches your repo.
  3. The workflow calls `AssumeRoleWithWebIdentity` with the token; AWS
     verifies signature + claims and returns temp creds.
- **In FinSight:** `infra/terraform/github_oidc.tf`.

#### KMS — Key Management Service

- **What it is:** AWS's managed cryptographic key store and operations
  service. Generates and stores symmetric/asymmetric keys that *never leave*
  KMS.
- **What it's used for:** Encrypting data at rest — RDS storage, EBS
  volumes, S3 objects, Secrets Manager secrets — all use KMS keys under the
  hood.
- **Why we need it:** Every "encrypted = true" in FinSight is silently
  backed by an AWS-managed KMS key. We never call KMS directly.
- **How it works on AWS:** A **CMK** (customer master key) lives in KMS;
  services request it to wrap/unwrap data keys (envelope encryption). You
  can use AWS-managed keys (free, simple) or your own customer-managed keys
  (extra control, ~$1/mo each).
- **In FinSight:** Implicit. `storage_encrypted = true` on RDS, `encrypted
  = true` on EBS — both use the AWS-managed `aws/rds` and `aws/ebs` keys.

#### Secrets Manager

- **What it is:** A managed store for secrets — API keys, DB passwords,
  OAuth tokens — with encryption, audit logging, and (optional) automatic
  rotation.
- **What it's used for:** Keeping secrets out of code, images, and config
  files; injecting them into running containers at launch.
- **Why we need it:** Anthropic API keys, OpenAI keys, JWT secrets, the DB
  password — none of these can live in code or images. Secrets Manager is
  the durable, auditable home.
- **How it works on AWS:** Each secret has a name (e.g.
  `finsight-prod/claude-api-key`), an encrypted value (KMS), and an ARN.
  IAM controls who can read; CloudTrail logs every read. ECS task
  definitions reference secrets by ARN in `secrets[].valueFrom`; the ECS
  agent fetches the value at launch and exposes it as an env var inside the
  container.
- **In FinSight:** `infra/terraform/secrets.tf` (creating them) +
  `task_definitions.tf` (referencing them).

#### SSM — Systems Manager

- **What it is:** A suite of management tools for EC2 fleets — Session
  Manager, Parameter Store, Patch Manager, Run Command, etc.
- **What it's used for in FinSight:**
  - **Session Manager** — open a shell on the Chroma EC2 host without ever
    opening port 22. Auth + audit go through IAM and CloudTrail.
  - **Parameter Store** — *alternative* to Secrets Manager (cheaper, less
    feature-rich). We use Secrets Manager instead.
- **Why we need it:** SSM Session Manager replaces SSH entirely — no key
  pairs, no public IPs, no port 22 ingress in the SG.
- **How it works on AWS:** The EC2 host runs the **SSM agent** (preinstalled
  in Amazon Linux 2023) and assumes a role with `AmazonSSMManagedInstanceCore`.
  You shell in with `aws ssm start-session --target i-...`.
- **In FinSight:** `aws_iam_role_policy_attachment.chroma_ssm` attaches the
  managed policy to the Chroma EC2's role.

#### ARN — Amazon Resource Name

- **What it is:** A globally-unique identifier for an AWS resource. Format:
  `arn:aws:<service>:<region>:<account-id>:<resource-type>/<resource-id>`.
- **What it's used for:** Referring to resources in IAM policies, task
  definitions, target groups — everywhere AWS needs to name something
  precisely.
- **Why we need it:** IAM policies grant access *to specific ARNs*.
  Specifying ARNs (not `*`) is the difference between least-privilege and
  "give me everything."
- **How it works on AWS:** AWS generates the ARN when a resource is
  created; Terraform exposes it as `.arn` on the resource object.
- **In FinSight:** Throughout — e.g. `aws_secretsmanager_secret.app["claude-api-key"].arn`
  is used in `task_definitions.tf` and in the IAM policy that scopes the
  GitHub deploy role to exactly the two ECS task roles.

---

### Observability & messaging

#### CloudWatch (umbrella)

CloudWatch is the AWS observability platform; it has four products you'll
touch in FinSight.

##### CloudWatch Logs

- **What it is:** A managed log-aggregation service.
- **What it's used for:** Collecting container stdout/stderr from ECS,
  function logs from Lambda, RDS logs, etc.
- **Why we need it:** ECS tasks are ephemeral — when a task dies, its local
  disk vanishes. Logs must be shipped *off* the task to survive.
- **How it works on AWS:** Logs are grouped into **log groups**, then
  **streams**. Each ECS task with `awslogs` log driver streams its output
  to a configured log group. Set `retention_in_days` to cap retention cost.
- **In FinSight:** `aws_cloudwatch_log_group.api` (`/ecs/finsight-prod/api`)
  and `.frontend` (`/ecs/finsight-prod/frontend`) in `ecs.tf`. Task
  definitions point the `awslogs` driver at them.

##### CloudWatch Metrics

- **What it is:** A time-series database. AWS services publish metrics here
  automatically (CPU, request count, errors, etc.).
- **What it's used for:** Graphing, alarming, and triggering autoscaling.
- **Why we need it:** Without metrics there's no way to know if the system
  is healthy, and no signal for autoscaling.
- **How it works on AWS:** Every service has a **namespace** (e.g.
  `AWS/ECS`, `AWS/RDS`, `AWS/ApplicationELB`). Metrics have **dimensions**
  (the keys identifying the resource — e.g. `ClusterName`, `ServiceName`).
- **In FinSight:** Referenced by every alarm and dashboard widget in
  `cloudwatch.tf`. Autoscaling also reads `ECSServiceAverageCPUUtilization`.

##### CloudWatch Alarms

- **What it is:** Threshold-based triggers on metrics. Each alarm watches
  one metric, fires when it crosses a threshold for N evaluation periods.
- **What it's used for:** Notifying you when something's broken. Each alarm
  can publish to SNS, trigger Auto Scaling, or invoke a Lambda.
- **Why we need it:** A dashboard nobody is looking at is useless. Alarms
  push to you (email/SMS/Slack via SNS) when thresholds break.
- **How it works on AWS:** Define `namespace`, `metric_name`, `dimensions`,
  `statistic` (Sum/Average/Maximum), `period`, `threshold`,
  `comparison_operator`, `evaluation_periods`. The alarm has states OK /
  ALARM / INSUFFICIENT_DATA; transitions fire `alarm_actions`.
- **In FinSight:** Six alarms in `cloudwatch.tf` (ALB 5xx, unhealthy hosts,
  API CPU, API memory, RDS CPU, RDS storage), all publishing to one SNS topic.

##### CloudWatch Dashboard

- **What it is:** A user-defined page with metric widgets — graphs,
  numbers, text.
- **What it's used for:** A single pane of glass to see the running system.
- **Why we need it:** Trends matter — you spot creeping memory leaks before
  they trip an alarm.
- **How it works on AWS:** The dashboard body is a JSON document with
  widget definitions. Terraform builds it via `jsonencode`.
- **In FinSight:** `aws_cloudwatch_dashboard.main` in `cloudwatch.tf`, with
  four widgets. The URL is exposed as `cloudwatch_dashboard_url`.

#### SNS — Simple Notification Service

- **What it is:** A pub-sub message router. Publishers send to a **topic**;
  AWS fans the message out to all **subscribers** (email, SMS, HTTP, SQS,
  Lambda).
- **What it's used for:** Alarm notifications, application events that need
  multiple consumers.
- **Why we need it:** CloudWatch alarms publish to SNS, which fans out to
  email and (later) Slack/Pagerduty — without alarms knowing or caring who
  the subscribers are.
- **How it works on AWS:** Create an `aws_sns_topic`; subscribe endpoints
  with `aws_sns_topic_subscription`. Email subscribers must click a
  one-time confirmation link.
- **In FinSight:** `aws_sns_topic.alerts` is the destination for every
  alarm; an optional email subscription fires when `var.alarm_email` is set.

#### SQS — Simple Queue Service

- **What it is:** A managed message queue. Producers `SendMessage`,
  consumers `ReceiveMessage` and `DeleteMessage`.
- **What it's used for:** Decoupling services — buffer work between a
  bursty producer and a slower consumer.
- **Why we need it:** Not used today. Would be natural if we moved the
  long-running `/analyze` pipeline off the request thread.
- **How it works on AWS:** Two flavours — **Standard** (at-least-once, high
  throughput) and **FIFO** (exactly-once, ordered). Pay per message.
- **In FinSight:** Not used.

#### EventBridge

- **What it is:** A managed event bus. Rules pattern-match events from AWS
  services or your apps and dispatch them to targets (Lambda, ECS, SNS, …).
- **What it's used for:** **Scheduled triggers** (cron-like), reacting to
  AWS state changes (an EC2 starts, an S3 upload happens).
- **Why we need it:** Future work. FinSight currently disables the in-app
  scheduler with `SCHEDULER_ENABLED=false`. The proper home for scheduled
  ingestion is an EventBridge rule firing a dedicated ECS task at intervals.
- **How it works on AWS:** Events arrive on a bus; rules match on event
  pattern or run on a schedule; targets execute.
- **In FinSight:** Not used today; called out as the future direction in
  `docs/deployment/README.md`'s "What's next" section.

---

### Account-level

#### AWS Account ID

- **What it is:** A 12-digit number identifying your AWS account.
- **What it's used for:** Embedded in ARNs (`arn:aws:iam::123456789012:role/...`).
- **How it works on AWS:** Look it up with `aws sts get-caller-identity`.
- **In FinSight:** `infra/scripts/deploy.sh` reads it once to construct
  the ECR registry hostname.

#### Billing & Cost Explorer

- **What it is:** AWS's billing dashboards and reports.
- **What it's used for:** Tracking spend by service, tag, or AZ.
- **Why we need it:** A portfolio project that runs continuously costs
  ~$120/mo — set a billing alarm! The `Project=finsight` default tag makes
  filtering for *this* stack's cost trivial.
- **How it works on AWS:** Cost Explorer reads from the billing data lake.
  AWS Budgets can fire alerts when spend exceeds a threshold.
- **In FinSight:** Not provisioned by Terraform; configured in the AWS
  console.

#### AWS CLI

- **What it is:** The command-line tool for AWS, `aws ...`.
- **What it's used for:** Bootstrapping credentials (`aws configure`),
  running tasks (`aws ecs run-task`), reading outputs after Terraform.
- **Why we need it:** Terraform handles infrastructure; the CLI handles the
  glue (running the migration, forcing service redeploys) that Terraform
  doesn't manage as resources.
- **How it works on AWS:** Reads `~/.aws/credentials`, environment
  variables, or instance/role metadata. Every command maps 1:1 to an AWS
  API call.
- **In FinSight:** `infra/scripts/deploy.sh` uses it extensively after
  `terraform apply` finishes.

---

### Cross-cutting concepts you'll be asked about

#### Public vs private subnet

A subnet's name doesn't make it public — its **route table** does. If the
table has a `0.0.0.0/0 → IGW` route, the subnet is public. If it has
`0.0.0.0/0 → NAT`, the subnet is private with outbound internet. If it has
no `0.0.0.0/0` at all, it's an isolated private subnet (no internet at all).

#### Security Group vs NACL

| | Security Group | NACL |
|---|---|---|
| **Level** | Per resource (ENI) | Per subnet |
| **State** | Stateful (replies auto-allowed) | Stateless (must allow both directions) |
| **Default** | Deny all in / allow all out | Allow all in / allow all out |
| **Rules** | Allow only | Allow *and* deny |
| **Order** | Rules unordered (all evaluated) | Numbered, lowest first |

FinSight uses only SGs.

#### Stateless vs stateful

- **Stateful** services keep track of in-flight context — Security Groups
  remember "this connection was established outbound, so allow the reply."
- **Stateless** services do not — NACLs evaluate every packet independently.

#### Encryption at rest vs in transit

- **At rest** = the data is encrypted on disk. RDS storage, EBS volumes,
  S3 objects, Secrets Manager — all do this via KMS. FinSight enables it
  on RDS and EBS explicitly (`storage_encrypted = true`).
- **In transit** = the data is encrypted as it moves. TLS/HTTPS handles
  this. FinSight's ALB is HTTP-only today (portfolio-grade); HTTPS would
  add transit encryption.

#### Why so many "Elastic" things?

"Elastic" in AWS means *managed and scales for you*. EC2 = compute that
scales; EBS = storage that grows; ELB = load balancer that scales; ECS =
container service that scales; ECR = registry that scales. The naming is
historical, not informative — just translate "Elastic X" as "managed X."

---

### One-page cheat-sheet (memorize this for interviews)

| Acronym | Service | One-line role in FinSight |
|---|---|---|
| **VPC** | Virtual Private Cloud | The private network everything lives in |
| **EC2** | Elastic Compute Cloud | Virtual machine — runs the Chroma container |
| **EBS** | Elastic Block Store | Disk for the Chroma host |
| **ECS** | Elastic Container Service | Orchestrates the API + frontend containers |
| **ECR** | Elastic Container Registry | Stores the Docker images |
| **ALB** | Application Load Balancer | Public entry point, routes by URL path |
| **RDS** | Relational Database Service | Managed Postgres 16 |
| **ElastiCache** | (no abbrev — full name) | Managed Redis 7 |
| **IAM** | Identity and Access Management | Who can do what |
| **STS** | Security Token Service | Mints temporary credentials |
| **OIDC** | OpenID Connect | GitHub→AWS federation, no stored keys |
| **KMS** | Key Management Service | Encryption keys (implicit) |
| **SSM** | Systems Manager | Shell into Chroma without SSH |
| **SNS** | Simple Notification Service | Fans out alarm notifications |
| **CloudWatch** | (no abbrev) | Logs, metrics, alarms, dashboard |
| **NAT GW** | NAT Gateway | Private subnets' outbound internet path |
| **IGW** | Internet Gateway | Public subnets' inbound/outbound internet |
| **EIP** | Elastic IP | Static public IP (the NAT's) |
| **AMI** | Amazon Machine Image | Boot image (latest AL2023 for Chroma) |
| **ENI** | Elastic Network Interface | Per-task virtual network card |
| **AZ** | Availability Zone | One DC in a region; we span two |
| **ARN** | Amazon Resource Name | Globally-unique resource ID |
| **CIDR** | Classless Inter-Domain Routing | IP-range notation (`10.0.0.0/16`) |
| **S3** | Simple Storage Service | (Future) remote Terraform state |
| **DynamoDB** | (no abbrev) | (Future) Terraform state lock |
| **ACM** | AWS Certificate Manager | (Future) TLS certs for HTTPS |
| **Route 53** | (no abbrev) | (Future) DNS for a custom domain |
| **EventBridge** | (no abbrev) | (Future) scheduled ingestion trigger |
| **Fargate** | (launch type, not a service) | Serverless ECS — no EC2 to manage |

---

## Appendix D — Alembic (database migrations)

Alembic is referenced everywhere in this stack: the Docker compose file runs
`alembic upgrade head` on startup; the `migrate` ECS task runs the same
command in production; the `CLAUDE.md` development commands list it. If you
don't know what it is, the whole deployment story has a black box in the
middle. This appendix removes the black box.

### D.1 What is a database migration?

A database **schema** is the shape of your tables: column names, types,
indexes, foreign keys, constraints. The schema changes over time — you add
a column, widen a string, create a new table, add an index. A **migration**
is one specific, ordered, version-controlled change to that schema.

Why bother with formal migrations instead of editing the schema by hand?

1. **Reproducibility.** A new developer clones the repo, runs the migration
   tool, and gets the *exact* same schema as production.
2. **History.** Each migration is a file in git. You can see who added the
   `news_articles` table, when, and why.
3. **Forward and backward.** Most migrations include a `downgrade` so you
   can roll back if a deploy goes wrong.
4. **Deterministic deploys.** CI runs the migrations in production exactly
   the same way you ran them locally.

Without migrations, the database becomes the "snowflake" — every environment
is subtly different and no one quite knows the truth.

### D.2 What Alembic is

**Alembic** is the migration tool for **SQLAlchemy** (Python's most-used ORM
and database toolkit), written by the same author. Think of it as
**"git for your database schema"**:

- Each migration is a tiny Python file in `db/migrations/versions/`.
- The files form a **linked list** — each one knows the previous one's ID.
- Alembic tracks which migrations have been applied to a database by
  storing the *current* migration ID in a special `alembic_version` table.
- You run `alembic upgrade head` to apply every migration the database
  doesn't have yet, in order, transactionally.

It's the Python ecosystem's answer to Rails' Active Record migrations,
Django's `migrate` command, Java's Flyway/Liquibase, or Node's Knex/Prisma
migrations.

### D.3 How Alembic works — the mental model

```
   Your SQLAlchemy models                    Real database
   (db/models.py)                            (Postgres / SQLite / …)
          │                                          │
          │ Base.metadata describes                   │ has its own
          │ the *desired* schema                      │ current schema
          ▼                                          ▼
   target_metadata    ─compares─►   alembic_version table
                                    ("we are at revision X")
                                         │
                                         ▼
                              Pending migration files
                              (X → Y → Z → head)
                                         │
                                         ▼
                              `alembic upgrade head`
                              applies each one in order,
                              updating alembic_version as it goes
```

Three things to internalize:

1. **`alembic_version` is a real table** in your database. Alembic creates it
   the first time it runs and stores one row: the ID of the most recent
   applied migration. That's the link between your code and the database's
   state.
2. **Migrations form a linked list.** Each file has a `revision` ID (its own)
   and `down_revision` (the parent). The first migration's `down_revision`
   is `None`. Alembic walks the chain from `alembic_version` toward `head`.
3. **`head` is whichever migration has no children yet.** When you create a
   new migration, *it* becomes head. Branches are possible but rare.

### D.4 Anatomy of a migration file

Look at `db/migrations/versions/09f8550da2e7_widen_ticker_symbol_to_30.py`:

```python
"""Widen ticker_symbol to 30 chars for comparison labels.

Revision ID: 09f8550da2e7
Revises: d4e5f6a7b8c9
Create Date: 2026-04-06
"""

from alembic import op
import sqlalchemy as sa

revision = "09f8550da2e7"           # this migration's ID
down_revision = "d4e5f6a7b8c9"      # the parent migration's ID
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "analysis_reports",
        "ticker_symbol",
        existing_type=sa.String(10),
        type_=sa.String(30),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "analysis_reports",
        "ticker_symbol",
        existing_type=sa.String(30),
        type_=sa.String(10),
        existing_nullable=False,
    )
```

Key parts:

| Section | Meaning |
|---|---|
| **Docstring** | Free-form description. Read by humans only, but invaluable. |
| **`revision`** | This file's unique ID (random hex). The "Git SHA" of this migration. |
| **`down_revision`** | The ID of the parent migration. Sets the order. |
| **`upgrade()`** | Forward operation — applied by `alembic upgrade`. |
| **`downgrade()`** | Reverse operation — applied by `alembic downgrade`. |

The `op` module gives you database-agnostic schema operations:
`op.create_table`, `op.drop_table`, `op.add_column`, `op.drop_column`,
`op.alter_column`, `op.create_index`, `op.drop_index`, `op.create_foreign_key`,
`op.execute` (raw SQL escape hatch), and many more. Alembic translates each
to the right SQL for your engine (Postgres, SQLite, MySQL).

### D.5 The FinSight setup — files

| File | Purpose |
|---|---|
| `alembic.ini` | Top-level Alembic config — script location, log levels, DB URL fallback. |
| `db/migrations/env.py` | The runtime entry point. Loaded for every Alembic command. |
| `db/migrations/script.py.mako` | Template used to scaffold new migration files. |
| `db/migrations/versions/*.py` | One file per migration, ordered by `down_revision`. |
| `db/models.py` | SQLAlchemy models — the source of truth for `--autogenerate`. |

#### `alembic.ini` — global config

```ini
[alembic]
script_location = db/migrations
sqlalchemy.url  = postgresql+asyncpg://finsight:finsight@localhost:5433/finsight
```

`script_location` tells Alembic where the migration files live.
`sqlalchemy.url` is a local-dev default — in production it's **overridden
by the `DATABASE_URL` environment variable** (see `env.py` below).

#### `db/migrations/env.py` — the runtime glue

```python
# (excerpt — full file in db/migrations/env.py)
from db.models import Base

target_metadata = Base.metadata          # the model definitions

db_url = os.getenv("DATABASE_URL")
if db_url:
    config.set_main_option("sqlalchemy.url", db_url)   # env overrides ini
```

Three things this file does:

1. Imports your SQLAlchemy models so `--autogenerate` can compare them
   against the database.
2. Lets `DATABASE_URL` (an environment variable) override the `alembic.ini`
   URL — which is how the production migration task connects to RDS
   (FinSight injects the DSN from Secrets Manager).
3. Configures Alembic to use SQLAlchemy's **async engine** with a
   `NullPool` — necessary because FinSight uses `asyncpg`.

The file has both `run_migrations_offline()` (emit SQL without connecting)
and `run_migrations_online()` (connect and apply) — both are standard
Alembic boilerplate; you rarely touch them.

#### `db/migrations/versions/` — the history

FinSight's history reads like a changelog:

```
314798936e19_initial_tables.py            ← root migration (down_revision = None)
a1b2c3d4e5f6_filing_content_hash.py
b2c3d4e5f6a7_add_conversations.py
c3d4e5f6a7b8_add_users_and_auth.py
d4e5f6a7b8c9_add_news_articles.py
09f8550da2e7_widen_ticker_symbol_to_30.py
e5f6a7b8c9d0_add_starred_reports.py
f6a7b8c9d0e1_add_filing_period_of_report.py    ← head (no child)
```

Each line is one schema change, in one git commit, with both forward and
reverse operations.

### D.6 The Alembic CLI — commands you'll actually use

```bash
# --- everyday ---------------------------------------------------------------
alembic current                  # show the migration the DB is currently at
alembic history                  # show the full chain of migrations
alembic upgrade head             # apply every pending migration (most common)
alembic upgrade +1               # apply just the next one
alembic downgrade -1             # roll back the most recent migration
alembic downgrade <revision>     # roll back to a specific revision
alembic downgrade base           # roll back EVERYTHING (drop all)

# --- creating a migration --------------------------------------------------
alembic revision -m "add foo column"
                                 # creates an EMPTY migration file you fill in

alembic revision --autogenerate -m "add foo column"
                                 # diffs db/models.py against the DB and
                                 # writes the upgrade()/downgrade() body
                                 # for you — usually 90% correct, ALWAYS
                                 # review by hand

# --- inspection ------------------------------------------------------------
alembic show <revision>          # one migration's full text
alembic heads                    # all heads (>1 means branched history)
alembic check                    # do the models match the DB? (in 1.9+)

# --- offline / dry-run -----------------------------------------------------
alembic upgrade head --sql       # print the SQL it would run, don't connect
alembic upgrade <from>:<to> --sql > migration.sql
                                 # generate a deployable SQL file
```

In FinSight you'll mainly run:

```bash
alembic upgrade head                                   # apply
alembic revision --autogenerate -m "description"       # create from models
alembic downgrade -1                                   # rollback one step
```

These three are in `CLAUDE.md` under "Database migrations."

### D.7 The autogenerate workflow

This is the most useful Alembic feature — and the one with the biggest
foot-guns.

**The flow:**

```
1. Edit db/models.py (add a column, change a type, add an index, …)
2. Make sure your local DB is at head:
       alembic upgrade head
3. Generate a migration:
       alembic revision --autogenerate -m "add foo to bar"
4. OPEN the generated file. Read it carefully. Adjust if needed.
5. Apply:
       alembic upgrade head
6. Commit both the model change AND the new migration file together.
```

**What autogenerate detects well:**

- New / dropped tables
- New / dropped columns
- New / dropped indexes
- New / dropped unique constraints
- Foreign key add / drop
- Column type changes (most)
- Nullable / not-null changes

**What it detects poorly (always review):**

- **Column renames** — looks like "drop old + add new" → data loss. Edit by
  hand to `op.alter_column(..., new_column_name=...)`.
- **Server defaults and check constraints** — often missed.
- **Index rename or reorder** — not detected by content.
- **Custom Postgres types** (ENUMs, JSON variants) — handle with care.

**Why the warning matters.** Look at the comment in the initial migration:

```python
# ### commands auto generated by Alembic - please adjust! ###
op.create_table('analysis_reports', ...)
# ### end Alembic commands ###
```

Alembic literally writes "please adjust" — because every autogenerated
migration is a *proposal*, not a finished product.

### D.8 How Alembic fits into FinSight's deploy

Three places Alembic runs in FinSight, each with a different host:

#### Local dev (Docker Compose)

`docker/docker-compose.yml`'s `app` service runs `alembic upgrade head`
before `uvicorn`. One container, no race — the API container does both.

#### Production (ECS Fargate)

Migrations run in a **separate one-shot ECS task** — never inside the API
container. This is critical: with N autoscaled API tasks each booting, all
of them would race to run `alembic upgrade head` against the same database.

The task definition is `aws_ecs_task_definition.migrate` in
`infra/terraform/task_definitions.tf`. It:

- Reuses the **API image** (Alembic + your models are already inside).
- Overrides the command to `["alembic", "upgrade", "head"]`.
- Has only `DATABASE_URL` from Secrets Manager — nothing else.

`deploy.sh` (and the GitHub Actions workflow) launch this task once per
deploy with `aws ecs run-task`, **wait for it to stop**, check the exit
code, and only then roll the API service forward.

#### GitHub Actions CI

`deploy.yml` does the same thing as `deploy.sh`: build the image → push to
ECR → `aws ecs run-task migrate` → wait → check exit code → roll services.

#### Diagram

```
    git push to main
          │
          ▼
   ┌─────────────────┐
   │  GitHub Actions │
   └────────┬────────┘
            ▼
   ┌─────────────────┐
   │ Build + push    │
   │ Docker image    │
   └────────┬────────┘
            ▼
   ┌─────────────────┐         ┌────────────────────┐
   │ ecs run-task    │ ──────► │ migrate Fargate    │
   │ migrate         │         │ task               │
   └────────┬────────┘         │                    │
            │                  │ alembic upgrade    │
            │                  │ head ──► RDS       │
            │                  │                    │
            │     wait + exit code OK │              │
            ▼                  └────────────────────┘
   ┌─────────────────┐
   │ update-service  │ ──────► API + frontend roll
   │ --force-new-    │         to the new image
   │ deployment      │
   └─────────────────┘
```

The key invariant: **the schema is at head before any new API task starts.**

### D.9 Common gotchas

1. **Forgetting to commit the migration file.** You generated it; you ran
   it locally; you pushed your model change without the file. CI's
   `alembic upgrade head` does nothing (no new migration). Production
   ORM crashes on missing columns. Always `git status` after a model change.

2. **Two developers branching head.** Both `alembic revision` at the same
   time → both files have `down_revision = OLD`, both claim to be head.
   `alembic upgrade head` errors with "multiple heads." Fix:
   `alembic merge -m "merge xyz" head1 head2` to create a merge migration.

3. **Editing an already-applied migration.** Don't. Once a migration is in
   anyone's database (or git history visible to others), it's frozen. Make
   a new migration to fix the mistake.

4. **`op.add_column` with `nullable=False` and no default on a non-empty
   table.** Postgres rejects this. Two-step pattern: add as nullable, fill
   with a default in a second migration step, then `alter_column` to
   not-null.

5. **Long-running migrations and locks.** A migration that takes a `LOCK
   TABLE` on a large hot table blocks everything else. For production:
   prefer additive migrations (add column, fill, swap reads, drop old);
   use `CREATE INDEX CONCURRENTLY` in Postgres; consider tools like
   `pg-osc` for the very large changes.

6. **`alembic.ini` URL vs `DATABASE_URL` env var.** In FinSight, *anywhere
   the env var is set, the `.ini` is ignored.* That's how production
   (`DATABASE_URL` from Secrets Manager) connects to RDS without anyone
   editing `alembic.ini`.

7. **Async vs sync.** FinSight uses `asyncpg`, so `env.py` uses
   `async_engine_from_config` and `connection.run_sync(do_run_migrations)`.
   A vanilla Alembic template assumes sync — if you scaffold a new
   project with `alembic init`, you must adapt `env.py` (FinSight already
   has this done).

8. **Migrations can't depend on application code that may change.** A
   migration imports `from db.models import Base`, fine — but if you do
   `from myapp.utils import compute_default`, then next month rename
   that function, the old migration breaks. Keep migrations self-contained.

### D.10 Best practices

- **Migration messages are descriptions, not commit messages.** `-m "add
  email column to users"` reads well in `alembic history`; `-m "fix"`
  doesn't.
- **One logical change per migration.** Easier to review, easier to roll
  back.
- **Always write `downgrade()`.** Even if you'll never run it, writing it
  forces you to think about reversibility. The `--autogenerate` output
  usually gets it right.
- **Review autogenerated migrations.** Treat them like AI-generated code:
  90% correct, 10% wrong in subtle ways.
- **Run migrations in CI in a fresh database.** Catches "I forgot the
  migration file" before it reaches production.
- **Don't put `INSERT INTO` data seeding in migrations.** Migrations are
  for *schema*. Data goes in a separate seed script or fixture.
- **Pin the migration head in a tag for each deploy.** `git log` of the
  migration files == schema history of production.
- **Match Postgres version locally and in production.** Some `op.alter_*`
  operations behave differently across major versions.

### D.11 Alembic vs the alternatives

| Tool | Ecosystem | Style |
|---|---|---|
| **Alembic** | Python / SQLAlchemy | Versioned Python migrations, `--autogenerate` from ORM. **(FinSight)** |
| **Django Migrations** | Python / Django ORM | Built into Django; very similar idea. |
| **Flyway** | Java / language-agnostic | **Plain SQL** files named with version prefixes. |
| **Liquibase** | Java / language-agnostic | XML/YAML/SQL "changesets." |
| **Knex / Prisma** | Node / JavaScript | Similar — code-defined or schema-diff. |
| **golang-migrate** | Go | Pure SQL files; CLI runs them. |
| **Active Record Migrations** | Ruby / Rails | Ruby DSL similar to Alembic's `op.*`. |
| **Atlas / sqitch** | Language-agnostic | Newer; declarative schema or planned changes. |

The common pattern: a directory of versioned files + a table in the DB
recording which have been applied.

### D.12 Quick command reference

```bash
# Apply
alembic upgrade head                 # apply every pending migration
alembic upgrade +1                   # apply only the next one
alembic upgrade <rev>                # apply forward to a specific revision

# Roll back
alembic downgrade -1                 # one step back
alembic downgrade <rev>              # back to a specific revision
alembic downgrade base               # roll back ALL migrations

# Create
alembic revision -m "msg"            # empty migration to fill in by hand
alembic revision --autogenerate -m "msg"   # diff from db/models.py

# Inspect
alembic current                      # which rev is the DB at?
alembic history                      # full migration chain
alembic heads                        # any branching?
alembic show <rev>                   # print one migration
alembic check                        # models match DB? (Alembic ≥ 1.9)

# Dry run / SQL output
alembic upgrade head --sql           # print SQL, don't connect
alembic upgrade <a>:<b> --sql > out.sql

# Branches (rare)
alembic merge -m "merge" <head1> <head2>   # merge two heads
```

### D.13 Likely interview questions

**Q1. What is Alembic and why do you use it?**

Alembic is the migration tool for SQLAlchemy. It manages incremental,
version-controlled changes to a database schema — each migration is a
Python file with an `upgrade()` and `downgrade()`, identified by a revision
ID, linked to its parent. Alembic tracks the current state in an
`alembic_version` table inside the database itself, so it can compute
"what's pending" and apply only the missing migrations in order.

**Q2. How does `--autogenerate` work, and when does it fail?**

Alembic loads your SQLAlchemy models (`Base.metadata`), reflects the
current database schema, and diffs them. The diff is rendered as
`op.create_table`, `op.add_column`, etc. It fails to detect renames
(looks like drop + add), some constraint changes, custom Postgres types,
and server defaults. The rule is: always read and adjust the generated
file before applying.

**Q3. Why do migrations run as a separate ECS task in FinSight?**

If migrations ran inside the API container's startup, N autoscaled API
tasks would race the same `alembic upgrade head` against the same database
— at best a wasted run, at worst conflicting DDL. Pulling migrations into
a dedicated one-shot Fargate task (same image, command overridden to
`alembic upgrade head`) means exactly one process runs them, on demand,
before any new API task starts. CI runs the migrate task, waits for it
to exit 0, *then* rolls the API service.

**Q4. How does Alembic know which migrations have been applied?**

It maintains a table called `alembic_version` in the database, containing
one row: the revision ID of the most recently applied migration. On
`alembic upgrade head`, Alembic reads that row, walks the migration chain
forward, applies each missing one inside a transaction (where the engine
supports it), and updates `alembic_version` as it goes.

**Q5. What's the difference between `down_revision` and `revision`?**

`revision` is the migration's own ID. `down_revision` is the ID of its
parent — the migration that must already be applied before this one runs.
Together they form a singly-linked list whose tail is `head`. Branches
exist (two children of the same parent) but require a merge migration
to reconcile.

**Q6. You added a column, forgot to generate a migration, and pushed.
What happens?**

CI's `alembic upgrade head` does nothing because no new migration exists.
Production RDS still has the old schema. The new container code expects
the new column and crashes on first query. Fix: either generate the
migration and redeploy, or revert the model change. Prevention: a
pre-push or CI check that runs `alembic check` (`alembic --autogenerate
--check` in older versions) to fail when models drift from the DB.

**Q7. Two engineers add migrations on separate branches at the same
time. Both `down_revision` point to the same parent. What now?**

You have two heads. `alembic upgrade head` errors with "multiple head
revisions." Fix: `alembic merge -m "merge X and Y" <head1> <head2>` — this
creates an empty merge migration whose `down_revision` is a tuple of both
heads. After committing, `head` becomes the merge, and `upgrade head`
applies both branches in deterministic order, then the merge.

**Q8. How would you migrate a not-null column on a large hot table?**

Three steps over multiple deploys:
1. Add the column as **nullable**, with a server default or no default.
2. Backfill values (data migration outside Alembic, or `op.execute`).
3. `alter_column` to `nullable=False`.

For very large tables, prefer additive patterns (add new column, dual-write,
backfill, swap reads, drop old) and tools like `pg-osc`. Locks on a hot
table can stall the whole app.

**Q9. What's the difference between Alembic and Django migrations?**

Both apply the same pattern (versioned Python files + a tracking table).
Differences: Django migrations are tightly integrated with the Django ORM
and the `manage.py` CLI; Alembic is decoupled and works with any
SQLAlchemy model. Alembic's `--autogenerate` is generally weaker than
Django's `makemigrations` because Django's ORM has stricter conventions
that make diffing easier. FinSight is FastAPI + SQLAlchemy, so Alembic is
the natural choice.

**Q10. How does Alembic connect to the production database?**

In `db/migrations/env.py`, FinSight overrides the `sqlalchemy.url` from
`alembic.ini` with the `DATABASE_URL` environment variable. In production,
the `migrate` ECS task's container has `DATABASE_URL` injected from
Secrets Manager (the same way the API container does) — so Alembic uses
the same async DSN to RDS that the live app uses. The plaintext DSN is
never on disk in the image or the task definition; it's only resolved by
the ECS agent at task launch.

---

### Cheat sheet

| Idea | One-liner |
|---|---|
| What is Alembic? | Versioned schema migration tool for SQLAlchemy. |
| Where is state stored? | In an `alembic_version` table in the database. |
| What's `head`? | The most recent migration with no children. |
| Apply pending migrations | `alembic upgrade head` |
| Generate from model changes | `alembic revision --autogenerate -m "msg"` |
| Roll back one step | `alembic downgrade -1` |
| Why a separate ECS task? | Avoid N autoscaled API tasks racing the same migration. |
| How does production get the DB URL? | `DATABASE_URL` env var from Secrets Manager overrides `alembic.ini`. |
| Most common mistake | Generating a migration locally and forgetting to commit the file. |
| Always do this | Read the autogenerated file before applying it. |
