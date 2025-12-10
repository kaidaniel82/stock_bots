# Project Context

## Stack

- **Framework:** Reflex.dev
- **Broker:** Interactive Brokers (ib_insync)
- **DB:** SQLite (reflex.db)

---

## File Ownership

```
trailing_stop_web/
├── broker.py              → @ib-specialist (EXKLUSIV)
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

docs/ib/                   → @ib-specialist (EXKLUSIV)
tests/ib/                  → @ib-specialist (EXKLUSIV)
```

---

## Quality Gates

| Size | Tests | Review |
|------|-------|--------|
| S | Optional | Self |
| M | Pflicht | @code-reviewer |
| L | Pflicht | @code-reviewer |

---

## Docs

| Doc | Wann |
|-----|------|
| `docs/ib/ib_bible.md` | VOR IB-Änderung |
| `docs/reflex/REFLEX_GOTCHAS.md` | Bei UI/State |
