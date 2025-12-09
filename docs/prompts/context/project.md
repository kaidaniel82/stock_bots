# Project Context

> Diese Datei enthält statische Projektinformationen.
> Wird von allen Agents gelesen, aber nie verändert.

## Project Profile

| Attribut | Wert |
|----------|------|
| Size | Small-Medium |
| Team | Solo-Dev |
| Priority | Quality + Speed |

## Tech Stack

### Frontend & Backend (unified)
- **Framework:** Reflex.dev (Python full-stack)
- **Pattern:** States + Components in Python
- **Styling:** Reflex built-in + Tailwind where needed

### Broker Integration
- **Provider:** Interactive Brokers
- **API:** TWS API via ib_insync
- **Entry Point:** `broker.py` (single source of truth)

## Architecture Principles

1. **Separation by Concern, not Language**
   - Frontend: UI/UX, Components, Layout, Routing, Responsive, UI-States
   - Backend: Business-States, Data Access, Auth, Services, Integrations
   - Broker: All IB/TWS interactions isolated in broker.py

2. **No Big Refactors**
   - Incremental improvements only
   - Large architecture changes require explicit approval

3. **Knowledge Persistence**
   - No "knowledge only in chat"
   - Decisions → docs or code comments
   - IB learnings → `docs/ib/ib_bible.md`

## File Ownership

```
Frontend Concern:
  - components/
  - pages/
  - layouts/
  - UI-related states

Backend Concern:
  - states/ (business logic)
  - services/
  - models/
  - auth/

Broker Concern (IB Specialist only):
  - broker.py
  - tests/ib/
  - docs/ib/
```

## Quality Gates

- Tests required for non-trivial changes
- Code review for M/L changes
- IB changes require fixture + contract test
