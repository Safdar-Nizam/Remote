# Automated Global Onboarding Orchestrator
### Design Brief — Safdar Nizam

---

## Slide 1: Current Manual Workflow

Today, the onboarding team repeats this process **25–40 times per day** across global regions:

```
┌─────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  1. CHECK   │────▶│  2. CROSS-REF    │────▶│  3. UPDATE      │
│  Kissflow   │     │  Upload to       │     │  Kissflow with  │
│  for new    │     │  Remote Platform │     │  actions taken  │
│  hires      │     │  (manual entry)  │     │                 │
└─────────────┘     └──────────────────┘     └────────┬────────┘
                                                       │
                    ┌──────────────────┐     ┌─────────▼────────┐
                    │  5. UPDATE       │◀────│  4. NOTIFY       │
                    │  Notion legal    │     │  Slack channel   │
                    │  tracker (if     │     │  with involved   │
                    │  redlining)      │     │  stakeholders    │
                    └──────────────────┘     └──────────────────┘
```

### Key Handoff Pain Points

| Step | Action | Owner | Risk |
|------|--------|-------|------|
| 1 → 2 | Copy employee data from Kissflow to Remote | Onboarding coordinator | Manual data entry errors |
| 2 → 3 | Update Kissflow with confirmation | Same person | Forgotten or delayed updates |
| 3 → 4 | Post Slack notification | Same person | Missed or inconsistent messaging |
| 4 → 5 | Create Notion entry for legal review | Same person | Only triggered sometimes, easy to skip |

**Core issue:** One person carries a sequential chain of 5 manual steps across 4 different tools. At 25–40 hires/day, this is unsustainable and error-prone.

---

## Slide 2: Failure Points

Mapped directly to the **known error patterns** from the brief:

### 1. "A field doesn't sync"
- **Root cause:** Manual copy-paste between Kissflow and Remote. No validation before data lands in Remote.
- **Impact:** Incorrect employment records, compliance risk, delayed onboarding.
- **How my system solves it:** Automated normalizer maps Kissflow fields → canonical format. Validation engine checks every field *before* pushing to Remote. Failures block the case with a clear owner.

### 2. "A start date is incorrect"
- **Root cause:** Date formats vary across countries (MM/DD vs DD/MM). Manual entry without validation.
- **Impact:** Employee starts before legal setup is complete, or payroll misalignment.
- **How my system solves it:** Date parser handles multiple formats. Validation rule rejects start dates in the past or >12 months out. `WARN` for unusual dates, `ERROR` for invalid ones.

### 3. "Uploaded documents are incomplete"
- **Root cause:** No systematic check of which documents are required per country/hire-type. Coordinators rely on memory.
- **Impact:** Onboarding stalls weeks later when compliance discovers missing docs.
- **How my system solves it:** `document_check` table tracks required vs. present documents per case. Missing docs → case moves to `PENDING_DOCUMENTS` state, not silently ignored.

### 4. "A workflow is created but is missed or not followed"
- **Root cause:** No central tracker. A Kissflow record can sit unactioned if the coordinator is busy, on leave, or switches context.
- **Impact:** Hire falls through cracks. Discovered days/weeks later.
- **How my system solves it:** Every hire enters the state machine automatically via webhook. A **watchdog sweeps every 5 minutes** for stuck cases. SLA breaches trigger Slack escalation alerts. Nothing can sit silently.

---

## Slide 3: Proposed Automation Architecture

```
Kissflow Webhook  ─┐
Remote  Webhook   ─┤──▶ Event Gateway (FastAPI) ──▶ Queue ──▶ Worker Service
Notion  Webhook   ─┘         │                                     │
                          202 Accepted                  ┌──────────┤
                          (instant)                     ▼          ▼
                                                  State Machine  Integration
                                                       │        Clients
                                                       ▼      (Remote, Slack,
                                                  PostgreSQL    Notion, Kissflow)
                                               (state, audit,
                                                 events, SLA)
```

### Processing Pipeline (Per Hire)

| Stage | What Happens | If It Fails |
|-------|-------------|-------------|
| **Ingest** | Webhook received, payload enqueued, 202 returned instantly | Signature verification rejects bad payloads |
| **Normalize** | Country names → ISO codes, dates parsed, emails lowercased | Malformed data → case blocked with error details |
| **Validate** | Required fields, date logic, duplicates, country compliance | `ERROR` → `BLOCKED_VALIDATION` + owner assigned + Slack alert |
| **Sync to Remote** | Employment created via API with idempotency key | Retries with exponential backoff (up to 5x) → DLQ |
| **Notify Slack** | Structured Block Kit message posted to stakeholder channel | Retry → DLQ (non-blocking) |
| **Update Notion** | Legal tracker item created when contract edits requested | Retry → DLQ (non-blocking) |
| **Update Kissflow** | Status pushed back to source system | Retry → DLQ (non-blocking) |

### State Machine (17 States)

```
RECEIVED → VALIDATING → READY_FOR_REMOTE → REMOTE_SYNC → REMOTE_INVITED → COMPLETED
                ↓                                                   
        BLOCKED_VALIDATION  →  (data corrected)  →  re-enters pipeline
                
Side branches: PENDING_DOCUMENTS | LEGAL_REVIEW | ESCALATED | CANCELLED
```

Every transition is **audited** with actor, timestamp, before/after state, and reason.

---

## Slide 4: Tooling, Monitoring & Escalation

### Tooling Choices

| Component | Tool | Why This Over Alternatives |
|-----------|------|---------------------------|
| **Orchestrator** | Python 3.12 + FastAPI | Async-first, Pydantic-native validation, auto OpenAPI docs. No vendor lock-in. |
| **Database** | PostgreSQL 16 | Relational integrity for state tracking + audit trails. Mature, battle-tested. |
| **Queue** | AWS SQS + DLQ (memory for dev) | Decoupled processing. DLQ captures failures for review. Scales horizontally. |
| **ORM** | SQLAlchemy + SQLModel | Models serve double duty as DB schema AND API response DTOs. Less boilerplate. |
| **Scheduler** | APScheduler (in-process) | Lightweight watchdog. No need for separate Celery/cron infrastructure. |
| **Logging** | structlog (JSON) | Correlation IDs across all systems. CloudWatch/Datadog ready. |
| **Dashboard** | Jinja2 (server-rendered) | Ships with the API server. Zero frontend infrastructure. Ops team gets visibility immediately. |

### Monitoring & Escalation Logic

| Check | Frequency | Action on Failure |
|-------|-----------|-------------------|
| **Stuck case detection** | Every 5 minutes (watchdog sweep) | Cases idle > 4 hours → Slack alert to ops channel |
| **Validation SLA** | On every case | Blocked > 5 minutes without owner → auto-escalate to manager |
| **Missing documents** | On every case | Missing > 24 hours → severity raised to HIGH, Slack reminder |
| **DLQ depth** | Continuous (health endpoint) | DLQ > 0 → operational incident, Slack alert |
| **Legal review SLA** | On flagged cases | Notion item unresolved > threshold → escalation alert |

### Escalation Chain

```
Normal flow:        Coordinator handles case
After SLA breach:   Slack alert → Team lead notified → Severity raised
After 2nd breach:   Case marked ESCALATED → Dashboard highlights it
DLQ failure:        Ops team reviews manually → Replay or manual fix
```

---

## Slide 5: Trade-offs & Phasing

### What I Would NOT Automate Yet (and Why)

| Area | Decision | Reasoning |
|------|----------|-----------|
| **Legal contract review** | Keep human-in-the-loop | Legal decisions require judgment. System creates the Notion tracker and alerts, but a human reviews and signs off. |
| **Country-specific rule files** | Start with config, not per-country YAML | Build the framework first. Add country-specific rules as data accumulates from real operations. |
| **IT provisioning** | Webhook hooks only (no implementation) | Depends on internal tooling (Okta, Google Workspace, etc.). Design the integration point now, implement when access is granted. |
| **Slack two-way interaction** | One-way notifications only in v1 | Bidirectional Slack bots add complexity (approval buttons, thread management). Ship one-way first, add interactivity in v2. |
| **Full Remote API automation** | Create employment only | Remote's API has edge cases per country (EOR vs. direct, contractor types). Start with the core flow, expand as we hit real scenarios. |
| **Welcome email triggers** | Integration point only | Depends on email platform (SendGrid, internal SMTP). Design the hook, implement when email infra is confirmed. |

### Phasing Strategy

| Phase | Scope | Timeline |
|-------|-------|----------|
| **Phase 1** | Kissflow → Validation → Remote sync → Slack notifications | Week 1–2 |
| **Phase 2** | Remote webhook callbacks → Notion legal tracker → Kissflow status pushback | Week 3–4 |
| **Phase 3** | Watchdog, escalation engine, reconciliation, operations dashboard | Week 5–6 |
| **Phase 4** | Country-specific rules, IT provisioning hooks, Slack interactivity | Week 7+ |

### Key Principle

> **Automate the reliable path first. Handle exceptions with clear ownership, not silence.**

The system doesn't try to handle every edge case on day one. Instead, it ensures that every case is either **progressing automatically** or **visibly blocked with an assigned owner**. Nothing falls through the cracks.

---

*Full working implementation available at: [github.com/Safdar-Nizam/Remote](https://github.com/Safdar-Nizam/Remote)*
*74 files · 62 unit tests · 6 integration tests · Docker-ready*
