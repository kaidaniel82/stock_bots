# Claude Code Project Instructions

## Projekt

| Attribut | Wert |
|----------|------|
| Projekt | stock_bots / trailing_stop_web |
| Team | Solo-Dev |
| Priority | Quality + Speed |

## Tech Stack

- **Framework:** Reflex.dev (Python full-stack)
- **Broker:** Interactive Brokers via ib_insync
- **Entry Point:** `trailing_stop_web/broker.py`

---

## Plugin Installation

```bash
# 1. Marketplace hinzufügen (einmalig)
/plugin marketplace add wshobson/agents

# 2. Plugins installieren
/plugin install python-development
/plugin install backend-development
/plugin install frontend-mobile-development
/plugin install code-review-ai
/plugin install unit-testing
/plugin install security-scanning
```

---

## Agents Übersicht

### Custom Agents (lokal)

| Agent | Aufruf | Zweck |
|-------|--------|-------|
| Architect | `@architect` | Triage, Planung, Agent-Zuweisung (KEIN Code!) |
| IB Specialist | `@ib-specialist` | EXKLUSIV für broker.py, IB/TWS |

### Marketplace Agents (nach Plugin-Installation)

| Plugin | Agent | Aufruf |
|--------|-------|--------|
| `python-development` | Python Pro | `@python-pro` |
| `python-development` | FastAPI Pro | `@fastapi-pro` |
| `backend-development` | Backend Architect | `@backend-architect` |
| `backend-development` | TDD Orchestrator | `@tdd-orchestrator` |
| `frontend-mobile-development` | Frontend Developer | `@frontend-developer` |
| `frontend-mobile-development` | Mobile Developer | `@mobile-developer` |
| `code-review-ai` | Code Reviewer | `@code-reviewer` |
| `unit-testing` | Test Automator | `@test-automator` |
| `security-scanning` | Security Auditor | `@security-auditor` |

---

## File Ownership

```
trailing_stop_web/
├── broker.py              → NUR @ib-specialist
├── components.py          → @frontend-developer
├── ui_config/             → @frontend-developer
├── state.py               → @backend-architect
├── config.py              → @backend-architect
├── groups.py              → @backend-architect
├── logger.py              → @backend-architect
├── metrics.py             → @backend-architect
├── strategy_classifier.py → @backend-architect
├── tick_rules.py          → @backend-architect
└── trailing_stop_web.py   → @backend-architect

docs/
├── ib/                    → NUR @ib-specialist
│   ├── vendor/
│   └── ib_bible.md
└── reflex/
    └── REFLEX_GOTCHAS.md  → Alle lesen!

tests/
├── ib/                    → NUR @ib-specialist
│   ├── contract/
│   ├── fixtures/
│   └── test_broker.py
├── test_strategy_classifier.py → @backend-architect
├── test_metrics.py        → @backend-architect
└── test_ui.py             → @frontend-developer
```

---

## Pipeline

| Size | Ablauf | Review | Tests |
|------|--------|--------|-------|
| S | @architect → 1 Agent → Commit | Self | Optional |
| M | @architect → Agents → @code-reviewer → Merge | Pflicht | Pflicht |
| L | @architect → Staged → @code-reviewer je Stage → Merge | Pflicht | Pflicht |

---

## Workflow

### 1. Starten
```
@architect <beschreibung>
```

### 2. Architect Output
```
[TRIAGE]
SIZE: S|M|L
Begründung: ...

[PLAN]
1. ...
2. ...

[AGENT-SELECTION]
- @agent: aufgabe

[PIPELINE]
Type: Direct | Standard | Full
```

### 3. Agents aufrufen
```
@ib-specialist <aufgabe>
@backend-architect <aufgabe>
@test-automator Tests generieren
@code-reviewer Änderungen prüfen
```

---

## Git

### Branch
```
feat/<name>   → Feature
fix/<name>    → Bugfix
```

### Commit
```
feat(ib): add trailing stop
fix(state): handle null
test(ib): add fixtures
```

---

## Wichtige Docs

| Doc | Wann |
|-----|------|
| `docs/ib/ib_bible.md` | VOR jeder IB-Änderung |
| `docs/reflex/REFLEX_GOTCHAS.md` | Bei UI/State-Problemen |
