# Onboarding Orchestrator

> Event-driven global onboarding orchestration system connecting **Kissflow → Remote → Slack → Notion** into an audited, state-tracked workflow.

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

### Key Design Principles

| Principle | Implementation |
|-----------|---------------|
| **Event-first** | Webhooks acknowledged immediately (202), processing is async via queue |
| **State machine** | Single gateway for all status changes — every transition is audited |
| **Idempotent** | Every external write carries an idempotency key; replays skip completed tasks |
| **Human-in-the-loop** | Validation failures stop the workflow safely with an assigned owner |
| **Configurable** | Validation rules, SLA thresholds, and retry policies are config-driven |

## Quick Start

```bash
# 1. Copy env file
cp .env.example .env

# 2. Start services (PostgreSQL + App)
docker-compose up -d

# 3. Run database migrations
docker-compose exec app alembic upgrade head

# 4. Access the app
# API:       http://localhost:8000
# Dashboard: http://localhost:8000/admin/ui/dashboard
# OpenAPI:   http://localhost:8000/docs
```

### Local Development (without Docker)

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Start PostgreSQL (or use sqlite for tests)
# Run migrations
alembic upgrade head

# Start the dev server
uvicorn app.main:app --reload

# Run tests
pytest -v
```

## API Endpoints

### Webhooks (Inbound)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/webhooks/kissflow` | Receive Kissflow hire events |
| `POST` | `/webhooks/remote` | Receive Remote lifecycle events |
| `POST` | `/webhooks/notion` | Receive Notion change signals |

### Admin API (Protected by `X-API-Key` header)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/admin/cases` | List cases (filterable by status, severity, country, owner) |
| `GET` | `/admin/cases/{id}` | Case detail |
| `GET` | `/admin/cases/{id}/events` | Event history |
| `GET` | `/admin/cases/{id}/validations` | Validation results |
| `GET` | `/admin/cases/{id}/tasks` | Sync task status |
| `GET` | `/admin/cases/{id}/audit` | Audit trail |
| `GET` | `/admin/cases/{id}/escalations` | Escalation records |
| `POST` | `/admin/cases/{id}/replay` | Replay failed case |
| `POST` | `/admin/cases/{id}/cancel` | Cancel case |
| `POST` | `/admin/cases/{id}/note` | Add operator note |
| `PATCH` | `/admin/cases/{id}/reassign` | Reassign owner |
| `GET` | `/admin/dashboard/stats` | Dashboard statistics |

### Operations Dashboard (Server-Rendered UI)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/admin/ui/dashboard` | KPI cards, pipeline view, recent cases |
| `GET` | `/admin/ui/cases` | Full case list with search and filter |
| `GET` | `/admin/ui/cases/{id}` | Case detail with lifecycle tracker |

### System

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Health check (queue depth, DLQ depth) |
| `GET` | `/docs` | OpenAPI interactive documentation |

## Case Lifecycle (State Machine)

```
RECEIVED → VALIDATING → READY_FOR_REMOTE → REMOTE_SYNC_IN_PROGRESS
                ↓                                      ↓
        BLOCKED_VALIDATION                      REMOTE_INVITED
                                                       ↓
                                        REMOTE_ONBOARDING_IN_PROGRESS
                                                       ↓
                                                  COMPLETED

Side branches:
  → PENDING_DOCUMENTS       (missing docs)
  → PENDING_CONTRACT_ACTION (contract edit requested)
  → LEGAL_REVIEW_REQUIRED   (Notion legal item created)
  → ESCALATED               (SLA breached)
  → CANCELLED               (manual cancellation)
  → FAILED_TERMINAL         (unrecoverable error)
```

## Project Structure

```
onboarding-orchestrator/
├── app/
│   ├── api/                      # FastAPI routers
│   │   ├── webhooks_kissflow.py  # Kissflow webhook ingestion
│   │   ├── webhooks_remote.py    # Remote webhook ingestion
│   │   ├── webhooks_notion.py    # Notion webhook ingestion
│   │   ├── admin_cases.py        # Admin REST API
│   │   ├── admin_replay.py       # Replay/cancel operations
│   │   └── admin_ui.py           # Server-rendered dashboard (Jinja2)
│   ├── core/                     # Cross-cutting concerns
│   │   ├── config.py             # Pydantic BaseSettings
│   │   ├── security.py           # Webhook signature verification
│   │   ├── correlation.py        # Correlation ID middleware
│   │   ├── idempotency.py        # Idempotency key generation
│   │   └── logging.py            # Structlog setup
│   ├── db/
│   │   └── session.py            # Async SQLAlchemy engine + session
│   ├── models/                   # SQLModel ORM tables
│   │   ├── onboarding_case.py    # Primary workflow record
│   │   ├── onboarding_event.py   # Raw inbound event log
│   │   ├── validation_result.py  # Per-rule validation outcomes
│   │   ├── document_check.py     # Document presence tracker
│   │   ├── sync_task.py          # Outbound integration tasks
│   │   ├── escalation.py         # SLA tracking + escalation records
│   │   └── audit_log.py          # Immutable state audit trail
│   ├── schemas/                  # Pydantic DTOs
│   │   ├── internal.py           # Canonical hire record + API responses
│   │   ├── kissflow.py           # Kissflow webhook schema
│   │   ├── remote.py             # Remote webhook schema
│   │   ├── notion.py             # Notion webhook schema
│   │   └── slack.py              # Slack notification blocks
│   ├── services/                 # Business logic
│   │   ├── normalizer.py         # Multi-source → canonical mapping
│   │   ├── validator.py          # Rule-based hire validation engine
│   │   ├── state_machine.py      # Case status transitions + audit
│   │   ├── slack_service.py      # Slack notification builder + sender
│   │   ├── kissflow_service.py   # Kissflow API client
│   │   ├── escalation_service.py # SLA monitoring + escalation logic
│   │   └── reconciliation_service.py  # Cross-system reconciliation
│   ├── queue/                    # Message queue abstraction
│   │   ├── memory_queue.py       # In-memory queue (dev/test)
│   │   └── sqs_client.py         # AWS SQS client (production)
│   ├── workers/                  # Background processors
│   │   ├── process_case.py       # Main case orchestration worker
│   │   ├── process_remote_sync.py    # Remote API integration
│   │   ├── process_notion_sync.py    # Notion API integration
│   │   ├── process_slack_notify.py   # Slack notification dispatcher
│   │   └── sweep_stuck_cases.py      # Watchdog scheduler (5min sweep)
│   ├── templates/admin/          # Jinja2 templates (dashboard UI)
│   └── main.py                   # FastAPI application factory
├── alembic/                      # Database migrations
│   ├── versions/001_initial_schema.py
│   └── env.py
├── tests/
│   ├── unit/                     # Validator, normalizer, state machine
│   ├── integration/              # Webhook → case lifecycle end-to-end
│   ├── contract/                 # Schema contract tests
│   └── conftest.py               # Shared fixtures + factories
├── docker-compose.yml            # PostgreSQL + App stack
├── Dockerfile                    # Python 3.12-slim production image
├── pyproject.toml                # Dependencies + tool config
└── .env.example                  # Required environment variables
```

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `DATABASE_URL` | PostgreSQL connection string | `postgresql+asyncpg://...` |
| `QUEUE_BACKEND` | `memory` (dev) or `sqs` (prod) | `memory` |
| `ADMIN_API_KEY` | API key for admin endpoints | (required) |
| `SLACK_WEBHOOK_URL` | Slack incoming webhook URL | (optional) |
| `REMOTE_API_TOKEN` | Remote.com API bearer token | (optional) |
| `NOTION_API_TOKEN` | Notion integration token | (optional) |
| `KISSFLOW_WEBHOOK_SECRET` | HMAC secret for Kissflow webhooks | (optional) |
| `REMOTE_WEBHOOK_SECRET` | HMAC secret for Remote webhooks | (optional) |

## Testing

```bash
# Run all tests
pytest -v

# Unit tests only
pytest tests/unit -v

# Integration tests only
pytest tests/integration -v

# With coverage
pytest --cov=app --cov-report=term-missing
```

## License

Internal tool — not for distribution.
