# Automated Global Onboarding Orchestrator

> **Designed for Remote**  An event-driven system that replaces manual coordination between Kissflow, Remote, Slack, and Notion with a fully tracked, state-machine-driven workflow.

---

## Why I Built This

Remote enables global employment across dozens of countries each with its own compliance rules, legal workflows, and onboarding dependencies. At that scale, the core challenge isn't any single tool. It's the **connections between them**.

I framed this around one question:

> *How do you build a system where onboarding runs reliably without depending on human coordination?*

---

## The Problem

The individual tools (Kissflow, Remote, Notion, Slack) each work fine on their own. The breakdown happens in between:

- **Human-driven handoffs**  Every step depends on someone remembering to do the next action
- **Fragmented state** — Kissflow knows approvals, Remote knows employment status, Notion tracks legal, Slack carries communication but no system answers *"Where is this hire right now?"*
- **Delayed failure detection**  Missing documents or invalid data are caught days later through manual checks
- **Implicit compliance**  Country-specific rules live in people's heads, not in the system

**The real issue isn't the tools  it's the lack of a central orchestration layer that owns the workflow end-to-end.**

### Current Manual Workflow (What Exists Today)

```
Check Kissflow  →  Copy data to Remote  →  Update Kissflow  →  Notify Slack  →  Update Notion
   (manual)          (manual entry)         (manual)            (manual)         (if needed)
```

One coordinator carries all 5 steps sequentially across 4 different tools, **25–40 times per day**. Every handoff is a potential failure point.

### Known Failure Patterns (Mapped to Root Causes)

| Error Pattern | Root Cause | System Impact |
|---|---|---|
| **Field doesn't sync** | Manual copy-paste between Kissflow → Remote | Bad employment records, compliance risk |
| **Start date is incorrect** | Date format varies by country (MM/DD vs DD/MM), no validation | Payroll misalignment, premature onboarding |
| **Documents are incomplete** | No per-country checklist enforced by the system | Onboarding stalls weeks later when compliance discovers gaps |
| **Workflow is missed** | No central tracker — a Kissflow record can sit unactioned indefinitely | Hire falls through the cracks, discovered days/weeks later |

---

## How I Solved It

I built a **central orchestrator** where every new hire becomes a tracked workflow case, and the system takes full ownership of moving it forward:

1. **Event-Driven Ingestion** — Kissflow webhook fires → orchestrator reacts instantly. No polling, no manual triggers.

2. **Automated Validation** — Before anything reaches Remote, the system validates required fields, date logic, country compliance, and duplicates. Bad data never enters downstream systems.

3. **State Machine Ownership** — Each hire moves through 17 defined states (`RECEIVED → VALIDATING → READY_FOR_REMOTE → ... → COMPLETED`). At any point: *"What is the exact status of this hire?"*

4. **System-to-System Sync** — Data flows to Remote, legal items to Notion, notifications to Slack — automatically, with idempotency keys so replays never create duplicates.

5. **Active Failure Handling** — Validation failures get an assigned owner. API errors retry with backoff. Stuck cases are swept every 5 minutes. SLA breaches trigger Slack alerts. **Nothing sits silently.**

6. **Real-Time Visibility** — Operations dashboard shows pipeline distribution, blocked cases, and SLA health at a glance.

### Design Philosophy

> Instead of *"How do we automate tasks?"* → I focused on *"How do we make onboarding a system-owned workflow?"*

- Every action is **event-driven**
- Every state change is **audited**
- Every failure is **handled, not ignored**
- Every hire has a **complete trail from webhook to completion**

---

## Architecture

```
Kissflow Webhook  ─┐
Remote  Webhook   ─┤──▶ Event Gateway (FastAPI) ──▶ Queue ──▶ Worker Service
Notion  Webhook   ─┘                                              │
                                                    ┌──────────────┤
                                                    ▼              ▼
                                              State Machine    Integration Clients
                                                    │         (Remote, Slack, Notion, Kissflow)
                                                    ▼
                                              PostgreSQL
                                        (state, audit, events)
```

### How It Works

**Inbound Flow:** When Kissflow fires a webhook (new hire created), the Event Gateway immediately returns `202 Accepted` and enqueues the payload for async processing. This ensures the upstream system never times out, regardless of how long validation or downstream syncing takes.

**Processing Pipeline:** The worker service picks up the message and runs it through a multi-stage pipeline:
- **Normalization** — Maps the Kissflow-specific payload into a canonical internal format (handles country name → ISO code conversion, date parsing, email normalization)
- **Validation** — Runs configurable business rules: required fields, email format, start date logic, country support, duplicate detection. `WARN`-level issues don't block; `ERROR`-level issues stop the case and assign an owner
- **State Transition** — The state machine moves the case forward (or blocks it) and writes an audit log entry for every change
- **Downstream Sync** — Creates sync tasks for Remote (employment creation), Slack (notifications), and Notion (legal tracker items), each with idempotency keys to prevent duplicate external calls

**Outbound Flow:** Remote, Slack, and Notion are updated via dedicated workers. Each external call is wrapped with exponential backoff retry logic. After max retries, messages land in a Dead Letter Queue for manual review.

**Feedback Loop:** Remote and Notion send webhooks back when employment status changes (e.g., "invite sent", "onboarding completed", "contract signed"), which the orchestrator processes to advance the case through its lifecycle automatically.

---

## Case Lifecycle (State Machine)

Every onboarding case moves through a defined set of states. The state machine enforces valid transitions and prevents impossible jumps (e.g., you can't go from `RECEIVED` directly to `COMPLETED`).

```
RECEIVED → VALIDATING → READY_FOR_REMOTE → REMOTE_SYNC_IN_PROGRESS
                ↓                                      ↓
        BLOCKED_VALIDATION                      REMOTE_INVITED
                                                       ↓
                                        REMOTE_ONBOARDING_IN_PROGRESS
                                                       ↓
                                                  COMPLETED

Side branches:
  → PENDING_DOCUMENTS       (missing docs detected)
  → PENDING_CONTRACT_ACTION (contract edit requested by legal)
  → LEGAL_REVIEW_REQUIRED   (Notion legal item created for review)
  → ESCALATED               (SLA breached — Slack alert fired)
  → CANCELLED               (manual cancellation by operator)
  → FAILED_TERMINAL         (unrecoverable error after max retries)
```

**17 total states** with guarded transitions. Terminal states (`COMPLETED`, `CANCELLED`, `FAILED_TERMINAL`) cannot be transitioned out of. Every transition writes to the `audit_log` table with actor, timestamp, before/after state, and reason.

---

## Technical Deep Dive

### Tech Stack

| Layer | Technology | Why |
|-------|-----------|-----|
| **Framework** | Python 3.12, FastAPI | Async-first, native Pydantic integration, auto-generated OpenAPI docs |
| **ORM** | SQLAlchemy 2.0 + SQLModel | Pydantic ↔ SQLAlchemy bridge — models serve as both DB schema and API DTOs |
| **Database** | PostgreSQL 16 | Relational integrity for state tracking, audit trails, and complex queries |
| **Migrations** | Alembic | Version-controlled schema evolution |
| **Queue** | AWS SQS (prod) / In-memory (dev) | Decoupled async processing with Dead Letter Queue support |
| **Scheduler** | APScheduler | In-process watchdog sweeps every 5 minutes for stuck cases |
| **Logging** | structlog | Structured JSON logs with correlation IDs for distributed tracing |
| **Validation** | Custom rule engine | Config-driven, extensible validation with severity levels |
| **Container** | Docker + docker-compose | One-command local development stack |

### Database Schema (7 Tables)

| Table | Purpose | Key Fields |
|-------|---------|------------|
| `onboarding_case` | Primary workflow record — one row per hire | status, severity, owner, correlation_id |
| `onboarding_event` | Raw inbound webhook log — every event ever received | source_system, payload_json, processing_result |
| `validation_result` | Per-rule validation outcome per case | validation_type, severity (INFO/WARN/ERROR), result |
| `document_check` | Document presence and verification tracker | document_type, file_status, file_category |
| `sync_task` | Outbound integration task with retry metadata | target_system, idempotency_key, retry_count |
| `escalation` | SLA tracking and escalation records | escalation_type, sla_deadline, acknowledged_at |
| `audit_log` | Immutable record of every state change and action | actor_type, action, before_json, after_json |

### Validation Engine

The validation engine runs a configurable set of rules against every incoming hire:

```python
# Each rule returns structured results with severity levels
VALIDATION_RULES = [
    RequiredFieldsCheck(["employee_email", "employee_full_name", "country_code"]),
    EmailFormatCheck(["employee_email", "manager_email"]),
    StartDateCheck(min_days=-7, max_days=365),
    CountryCodeCheck(supported=SUPPORTED_COUNTRIES),
    DuplicateDetectionCheck(active_cases),
]
```

- **ERROR** severity → blocks the case, assigns an owner, fires a Slack alert
- **WARN** severity → logged but doesn't block (e.g., start date 6+ months out)
- **INFO** severity → informational only

### Idempotency & Reliability

Every external API call is wrapped with an **idempotency key** derived from the case workflow ID and operation type. This means:
- Replaying a failed case never creates duplicate Remote employments
- Retrying a Slack notification doesn't spam the channel
- Network timeouts during Notion page creation are safe to retry

### Retry Policy

| Failure Type | Strategy |
|-------------|----------|
| Retryable (5xx, 429, timeout) | Exponential backoff: 1s → 2s → 4s → 8s (up to 5 attempts) |
| Non-retryable (4xx, bad data) | Immediate fail → `BLOCKED_VALIDATION` or `FAILED_TERMINAL` |
| Max retries exceeded | Message → Dead Letter Queue, Slack alert to ops team |

---

## API Reference

### Webhook Endpoints (Inbound)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/webhooks/kissflow` | Receive Kissflow hire created/updated events |
| `POST` | `/webhooks/remote` | Receive Remote employment lifecycle events |
| `POST` | `/webhooks/notion` | Receive Notion page change signals |

### Admin REST API (Protected by `X-API-Key` header)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/admin/cases` | List cases with filters (status, severity, country, owner) + pagination |
| `GET` | `/admin/cases/{id}` | Full case detail |
| `GET` | `/admin/cases/{id}/events` | Chronological event history |
| `GET` | `/admin/cases/{id}/validations` | All validation rule results |
| `GET` | `/admin/cases/{id}/tasks` | Sync task status and retry info |
| `GET` | `/admin/cases/{id}/audit` | Complete audit trail |
| `GET` | `/admin/cases/{id}/escalations` | Escalation records and SLA tracking |
| `POST` | `/admin/cases/{id}/replay` | Re-process a failed case from a specific step |
| `POST` | `/admin/cases/{id}/cancel` | Cancel an active case |
| `POST` | `/admin/cases/{id}/note` | Add an operator note to the audit trail |
| `PATCH` | `/admin/cases/{id}/reassign` | Reassign the case owner |
| `GET` | `/admin/dashboard/stats` | Aggregated pipeline statistics |

### Operations Dashboard (Server-Rendered)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/admin/ui/dashboard` | KPI cards, pipeline distribution, recent activity |
| `GET` | `/admin/ui/cases` | Searchable case list with severity indicators |
| `GET` | `/admin/ui/cases/{id}` | Case detail with visual lifecycle tracker |

### System

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Health check with queue depth and DLQ depth |
| `GET` | `/docs` | Interactive OpenAPI documentation |

---

## Project Structure

```
onboarding-orchestrator/
├── app/
│   ├── api/                          # FastAPI route handlers
│   │   ├── webhooks_kissflow.py      # Kissflow webhook ingestion
│   │   ├── webhooks_remote.py        # Remote webhook ingestion
│   │   ├── webhooks_notion.py        # Notion webhook ingestion
│   │   ├── admin_cases.py            # Admin REST API (12 endpoints)
│   │   ├── admin_replay.py           # Replay and cancel operations
│   │   └── admin_ui.py               # Server-rendered dashboard (Jinja2)
│   ├── core/                         # Cross-cutting infrastructure
│   │   ├── config.py                 # Pydantic BaseSettings (all env vars)
│   │   ├── security.py               # HMAC webhook signature verification
│   │   ├── correlation.py            # Correlation ID middleware
│   │   ├── idempotency.py            # Deterministic idempotency key generation
│   │   └── logging.py                # Structlog JSON logging setup
│   ├── db/
│   │   └── session.py                # Async SQLAlchemy engine + session factory
│   ├── models/                       # SQLModel ORM (7 tables)
│   │   ├── onboarding_case.py        # Primary workflow record + enums
│   │   ├── onboarding_event.py       # Raw inbound event log
│   │   ├── validation_result.py      # Per-rule validation outcomes
│   │   ├── document_check.py         # Document presence tracker
│   │   ├── sync_task.py              # Outbound integration task tracker
│   │   ├── escalation.py             # SLA and escalation records
│   │   └── audit_log.py              # Immutable state change audit
│   ├── schemas/                      # Pydantic DTOs (request/response)
│   │   ├── internal.py               # Canonical hire record + case DTOs
│   │   ├── kissflow.py               # Kissflow webhook payload schema
│   │   ├── remote.py                 # Remote webhook + API schemas
│   │   ├── notion.py                 # Notion webhook + page schemas
│   │   └── slack.py                  # Slack Block Kit message schemas
│   ├── services/                     # Business logic layer
│   │   ├── normalizer.py             # Multi-source → canonical mapping
│   │   ├── validator.py              # Config-driven rule engine
│   │   ├── state_machine.py          # FSM transitions + audit hooks
│   │   ├── slack_service.py          # Slack Block Kit builder + sender
│   │   ├── kissflow_service.py       # Kissflow outbound API client
│   │   ├── escalation_service.py     # SLA monitoring + severity routing
│   │   └── reconciliation_service.py # Cross-system drift detection
│   ├── queue/                        # Message queue abstraction
│   │   ├── memory_queue.py           # In-memory queue (dev/test)
│   │   └── sqs_client.py             # AWS SQS producer/consumer (prod)
│   ├── workers/                      # Background job processors
│   │   ├── process_case.py           # Main orchestration worker (437 lines)
│   │   ├── process_remote_sync.py    # Remote API create/update/invite
│   │   ├── process_notion_sync.py    # Notion legal tracker CRUD
│   │   ├── process_slack_notify.py   # Slack message dispatcher
│   │   └── sweep_stuck_cases.py      # Watchdog scheduler (5min sweep)
│   ├── templates/admin/              # Jinja2 dashboard templates
│   │   ├── base.html                 # Glassmorphism layout + nav
│   │   ├── dashboard.html            # KPI cards + pipeline visualization
│   │   ├── case_list.html            # Searchable case table
│   │   └── case_detail.html          # Lifecycle tracker + danger zone
│   └── main.py                       # FastAPI app factory + lifespan
├── alembic/                          # Database migrations
│   ├── versions/001_initial_schema.py
│   └── env.py                        # Async migration runner
├── tests/
│   ├── unit/                         # 62 tests: validator, normalizer, FSM
│   ├── integration/                  # 6 tests: webhook → case lifecycle
│   ├── contract/                     # Schema contract test scaffolding
│   └── conftest.py                   # Shared fixtures + test factories
├── docker-compose.yml                # PostgreSQL 16 + App stack
├── Dockerfile                        # Python 3.12-slim production image
├── pyproject.toml                    # Dependencies + ruff + pytest config
└── .env.example                      # All required environment variables
```

---

## Getting Started

### With Docker (Recommended)

```bash
# 1. Clone and configure
git clone https://github.com/Safdar-Nizam/Remote.git
cd Remote
cp .env.example .env

# 2. Start the full stack
docker-compose up -d

# 3. Run database migrations
docker-compose exec app alembic upgrade head

# 4. Access the application
# Dashboard:  http://localhost:8000/admin/ui/dashboard
# API Docs:   http://localhost:8000/docs
# Health:     http://localhost:8000/health
```

### Local Development

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Run migrations (requires PostgreSQL or use SQLite for tests)
alembic upgrade head

# Start the dev server with hot reload
uvicorn app.main:app --reload

# Run the full test suite
pytest -v
```

## Testing

The project includes **68 automated tests** across three tiers:

```bash
# All tests
pytest -v

# Unit tests (62 tests) — validator rules, normalizer logic, state machine transitions
pytest tests/unit -v

# Integration tests (6 tests) — webhook → queue → worker → database lifecycle
pytest tests/integration -v

# With coverage report
pytest --cov=app --cov-report=term-missing
```

### What the Tests Cover

| Test Suite | Count | What It Validates |
|-----------|-------|-------------------|
| `test_validator.py` | 18 | Required fields, email format, start date logic, country codes, duplicate detection |
| `test_normalizer.py` | 12 | Country name → ISO code, date parsing, email normalization, payload preservation |
| `test_state_machine.py` | 25 | Valid/invalid transitions, terminal states, escalation flows, coverage of all states |
| `test_idempotency.py` | 7 | Key determinism, uniqueness, length constraints |
| `test_webhook_to_case.py` | 6 | Full lifecycle, validation failure path, dedup, revalidation, Remote callbacks, admin API |

---

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `DATABASE_URL` | PostgreSQL async connection string | `postgresql+asyncpg://orchestrator:orchestrator_dev@localhost:5432/onboarding` |
| `QUEUE_BACKEND` | `memory` for local dev, `sqs` for production | `memory` |
| `ADMIN_API_KEY` | API key for protected admin endpoints | `dev-admin-key-change-me` |
| `SLACK_WEBHOOK_URL` | Slack incoming webhook URL for notifications | _(optional)_ |
| `REMOTE_API_TOKEN` | Remote.com API bearer token | _(optional)_ |
| `REMOTE_API_BASE_URL` | Remote API base URL | `https://gateway.remote.com/v1` |
| `NOTION_API_TOKEN` | Notion internal integration token | _(optional)_ |
| `NOTION_LEGAL_DB_ID` | Notion database ID for legal tracker | _(optional)_ |
| `KISSFLOW_WEBHOOK_SECRET` | HMAC secret for verifying Kissflow webhooks | _(optional)_ |
| `REMOTE_WEBHOOK_SECRET` | HMAC secret for verifying Remote webhooks | _(optional)_ |
| `MAX_RETRY_ATTEMPTS` | Maximum retry attempts for failed tasks | `5` |
| `SLA_VALIDATION_BLOCKED_MINUTES` | SLA threshold before escalation | `5` |
| `SLA_IDLE_CASE_HOURS` | Hours before a case is considered stuck | `4` |

---

## Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| **Async queue processing** | Webhooks return 202 instantly — external systems never time out waiting for our validation/sync pipeline |
| **Single state machine gateway** | All status changes go through one function — impossible to change status without an audit log entry |
| **Idempotency keys on every external call** | Safe to replay any failed case without creating duplicates in Remote/Slack/Notion |
| **Configurable validation rules** | Adding a new country's compliance rules doesn't require code changes — just config updates |
| **Server-rendered dashboard** | No separate frontend build step — dashboard ships with the API server, zero additional infrastructure |
| **Correlation IDs everywhere** | Every request, queue message, and DB record shares a correlation ID for end-to-end tracing |

---

## Trade-offs: What I Would NOT Automate Yet

| Area | Decision | Reasoning |
|------|----------|----------|
| **Legal contract review** | Human-in-the-loop | Legal decisions require judgment. The system creates the Notion tracker and alerts, but a human reviews and signs off. |
| **Country-specific rule files** | Config-driven framework only | Build the extensible framework first. Add per-country rules as data accumulates from real operations. |
| **IT provisioning** | Webhook hooks only | Depends on internal tooling (Okta, Google Workspace). Design the integration point now, implement when access is available. |
| **Slack two-way interaction** | One-way notifications in v1 | Bidirectional Slack bots add complexity. Ship one-way first, add approval buttons in v2. |
| **Full Remote API coverage** | Create employment only | Remote's API has edge cases per country (EOR vs. direct). Start with the core flow, expand with real scenarios. |

> **Principle:** Automate the reliable path first. Handle exceptions with clear ownership, not silence.

---

## License

Internal tool — built for demonstration purposes.
