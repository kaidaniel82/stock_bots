# Master Orchestrator

> Kontext-Dokument für Claude Code.
> Definiert wie Agents zusammenarbeiten.

## System-Architektur

```
┌─────────────────────────────────────────────────────────────┐
│                     CLAUDE CODE                              │
│                                                              │
│  Liest: prompts/agents/architect.md                         │
│         ↓                                                    │
│  Architect-light erstellt Plan                              │
│         ↓                                                    │
│  Plan enthält: "Order of execution"                         │
│         ↓                                                    │
│  Claude Code ruft Agents der Reihe nach auf:                │
│    - @backend-specialist (Marketplace)                       │
│    - @frontend-specialist (Marketplace)                      │
│    - IB/TWS Specialist (Custom Prompt)                       │
│    - @code-review-ai (Marketplace)                           │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

---

## Verfügbare Agents

### Marketplace Agents (installiert via wshobson/agents)

| Agent | Aufruf | Zweck |
|-------|--------|-------|
| `@backend-specialist` | Per @-mention | States, Services, Business-Logik |
| `@frontend-specialist` | Per @-mention | UI-Komponenten, Layout, Styling |
| `@code-review-ai` | Per @-mention | Code Review |
| `@full-stack-orchestration` | Per @-mention | Plan-Support (optional) |

### Custom Agents (projektspezifisch)

| Agent | Prompt | Zweck |
|-------|--------|-------|
| Architect-light | `prompts/agents/architect.md` | Planung, Agent-Auswahl |
| IB/TWS Specialist | `prompts/agents/ib_specialist.md` | broker.py, tests/ib/, docs/ib/ |

---

## Workflow

### 1. Neue Aufgabe → Architect

```
User: "Ich brauche Feature X"
      ↓
Claude Code liest: prompts/agents/architect.md
      ↓
Architect-light erstellt:
  - Triage (Size S/M/L)
  - Micro-Slices
  - Agent-Selection mit @-mentions
  - Execution Order
```

### 2. User Approval

```
User prüft Plan
  - "Sieht gut aus, starte"
  - oder: "Bitte anpassen weil..."
```

### 3. Execution

```
Claude Code führt aus:
  1. Branch anlegen
  2. @first-agent (z.B. @backend-specialist)
  3. @second-agent (z.B. @frontend-specialist)
  4. @code-review-ai
  5. QA/Test
```

### 4. IB-Spezialfall

```
Wenn IB betroffen:
  → Claude Code liest: prompts/agents/ib_specialist.md
  → Implementiert nach diesen Regeln
  → Danach weiter mit @backend-specialist für Integration
```

---

## Context für Marketplace Agents

Wenn Marketplace Agents aufgerufen werden, gib ihnen diesen Kontext:

```markdown
PROJECT CONTEXT:
- Stack: Reflex.dev (Python full-stack)
- Solo-Dev, Quality + Speed
- IB-Integration nur via broker.py (NICHT ANFASSEN!)

CURRENT TASK:
<aus Architect Plan>

YOUR SCOPE:
<aus Agent-Selection>

CONTRACTS AVAILABLE:
<aus vorherigen Hand-offs>

CONSTRAINTS:
- Nicht broker.py ändern (IB Specialist only)
- Nicht tests/ib/ ändern (IB Specialist only)
- Hand-off Format am Ende liefern
```

---

## Definition of Done

```
[DONE-CHECKLIST]
- [ ] Alle Acceptance Criteria erfüllt
- [ ] Tests vorhanden (bei M/L)
- [ ] @code-review-ai passed
- [ ] Keine offenen Blockers

IB-spezifisch:
- [ ] Bible updated
- [ ] Fixture + Contract Test

Status: DONE | INCOMPLETE
[/DONE-CHECKLIST]
```

---

## Protokoll-Referenzen

| Dokument | Wann nutzen |
|----------|-------------|
| `prompts/orchestration/triage.md` | Architect für Size-Entscheidung |
| `prompts/orchestration/pipeline.md` | Pipeline-Details |
| `prompts/orchestration/handoff_protocol.md` | Nach jedem Agent |
| `prompts/context/project.md` | Kontext für alle |
| `prompts/agents/architect.md` | Start jeder Aufgabe |
| `prompts/agents/ib_specialist.md` | Nur bei IB-Aufgaben |
| `prompts/tools/git_conventions.md` | Branch/Commit Regeln |
