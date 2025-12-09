# Quick Reference Card

> Einseiter für den täglichen Gebrauch.
> Alle wichtigen Entscheidungen auf einen Blick.

---

## 🤖 Agents

### Marketplace (via @-mention)
```
@backend-specialist   → States, Services, Business
@frontend-specialist  → UI, Components, Layout
@code-review-ai       → Review Gate
```

### Custom (via Prompt-Datei)
```
Architect-light       → prompts/agents/architect.md
IB/TWS Specialist    → prompts/agents/ib_specialist.md
```

---

## 🎯 Triage Decision Tree

```
Aufgabe erhalten
      │
      ├─ Typo/Einzeiler? ──────────────────→ Size S (Direct)
      │
      ├─ IB/Auth/Breaking? ────────────────→ Mindestens M
      │
      ├─ < 30 LOC, 1-2 Files? ─────────────→ Size S
      ├─ 30-150 LOC, 2-5 Files? ───────────→ Size M
      └─ > 150 LOC, 5+ Files? ─────────────→ Size L
```

---

## 🔄 Pipelines

| Size | Pipeline | Branch | Agents | Gates |
|------|----------|--------|--------|-------|
| **S** | Direct | ❌ | 1 | Self-Review |
| **M** | Standard | ✅ | 2-3 | Review + QA |
| **L** | Full | ✅ | 3+ | Review + QA + Integration |

---

## 👥 Agent Selection

| Keywords | → Agent |
|----------|---------|
| `button, modal, layout, UI, component` | @frontend-specialist |
| `State, event_handler, db, auth, service` | @backend-specialist |
| `order, position, broker, TWS, ib_` | IB/TWS Specialist (Custom) |
| Review Gate | @code-review-ai |

```
IB Keywords    → IB Specialist (Custom) PFLICHT
Frontend only  → @frontend-specialist
Backend only   → @backend-specialist
Both           → @backend-specialist zuerst, dann @frontend-specialist
```

---

## 📁 Scope Boundaries

```
Frontend:    components/, pages/, layouts/
Backend:     states/, services/, models/, auth/
IB only:     broker.py, tests/ib/, docs/ib/
```

---

## 📤 Hand-off Formats

**Size S (Light):**
```
[HANDOFF-LIGHT]
Agent: <n>
Status: done
Files: <files>
Summary: <1-2 Sätze>
[/HANDOFF-LIGHT]
```

**Size M/L (Full):**
```
╔═══════════════════════════════════════╗
║           HAND-OFF                     ║
╠═══════════════════════════════════════╣
║ From/To/Status                         ║
║ Artifacts Changed                      ║
║ Contracts Exposed                      ║
║ Tests Added                            ║
║ Open Questions / Blockers              ║
╚═══════════════════════════════════════╝
```

---

## 🌿 Git Quick Reference

**Branch:**
```
feat/<name>  fix/<name>  refactor/<name>
```

**Commit:**
```
feat(scope): description
fix(scope): description
test(scope): description
```

**Scopes:** `ui`, `state`, `service`, `ib`, `auth`, `test`, `docs`

---

## ⚠️ Escalation Triggers

```
Agent blocked?           → [BLOCKER] → Architect entscheidet
Scope conflict?          → [ESCALATION] → Architect/Human
Review rejected?         → Zurück zu Implement
QA failed (blocking)?    → Stopp, analysieren
```

---

## ✅ Definition of Done

```
[ ] Acceptance Criteria erfüllt
[ ] Tests vorhanden (M/L)
[ ] Review passed (M/L)
[ ] Hand-offs vollständig
[ ] IB: Bible updated (wenn betroffen)
```

---

## 📚 Dokument-Referenz

| Dokument | Pfad |
|----------|------|
| Master | `prompts/master.md` |
| Triage | `prompts/orchestration/triage.md` |
| Pipeline | `prompts/orchestration/pipeline.md` |
| Hand-off | `prompts/orchestration/handoff_protocol.md` |
| Marketplace | `prompts/orchestration/marketplace_integration.md` |
| Git | `prompts/tools/git_conventions.md` |
| Context | `prompts/context/project.md` |
| Agents | `prompts/agents/*.md` |
