# Triage Protocol

> Einstiegspunkt für JEDE Aufgabe.
> Bestimmt Komplexität und wählt Pipeline.
> **KEINE Implementierung in diesem Schritt.**

---
## Minimaler Output für Architect-light
Architect-light nutzt dieses Dokument als Entscheidungsgrundlage,
muss aber ein **vereinfachtes TRIAGE-Format** ausgeben.

Verbindliches Ausgabeformat von Architect-light:

[TRIAGE]
SIZE: S|M|L
Begründung: <1 kurzer Satz, warum diese Size gewählt wurde>
[/TRIAGE]


Die weiteren Abschnitte in diesem Dokument (Decision Tree, Keyword-Matrix,
Pipelines etc.) dienen als **Guidelines** für die Entscheidung, aber müssen
nicht 1:1 im Output wiederholt werden.
## Quick Decision Tree

```
Aufgabe erhalten
      │
      ▼
┌─────────────────────────────────────────┐
│ Ist es ein Typo/Einzeiler?              │
│ (< 10 LOC, 1 File, offensichtlich)      │
└─────────────────────────────────────────┘
      │                    │
     JA                   NEIN
      │                    │
      ▼                    ▼
   Size S            Weiter analysieren
   Direct                  │
                          ▼
              ┌─────────────────────────────┐
              │ IB/Auth/Breaking Change?    │
              └─────────────────────────────┘
                    │              │
                   JA            NEIN
                    │              │
                    ▼              ▼
              Mindestens M    LOC schätzen
                    │              │
                    ▼              ▼
              Weiter          S / M / L
              analysieren     basierend
                              auf Matrix
```

---

## Step 1: Complexity Assessment

### Basis-Matrix

| Size | LOC Delta | Files | Agents | Risiko | Pipeline |
|------|-----------|-------|--------|--------|----------|
| **S** | < 30 | 1-2 | 1 | Low | Direct |
| **M** | 30-150 | 2-5 | 2-3 | Medium | Standard |
| **L** | > 150 | 5+ | 3+ | High | Full |

### Automatische Upgrades (Override Matrix)

**Zu mindestens M hochstufen wenn:**
- [ ] IB/Broker/TWS betroffen
- [ ] Auth/Security/Permissions betroffen
- [ ] Neue externe Dependency
- [ ] State-Struktur ändert sich

**Zu L hochstufen wenn:**
- [ ] Breaking API Change
- [ ] Datenbank-Migration
- [ ] Mehr als 2 Agents müssen koordiniert arbeiten
- [ ] Cross-Concern Änderungen (Backend + Frontend + IB)

### Automatische Downgrades

**Darf S bleiben trotz mehrerer Files wenn:**
- Nur Typos/Docs
- Nur Config-Änderungen
- Copy-Paste ähnlicher Code (DRY refactor)

---

## Step 2: Agent Selection

### Keyword-Trigger Matrix

| Keywords im Task | → Agent | Confidence |
|------------------|---------|------------|
| `button, modal, layout, responsive, component, page, UI, UX, style, navbar, form` | Frontend | High |
| `State, event_handler, db, auth, service, model, API, validate, business` | Backend | High |
| `order, position, contract, TWS, ib_, broker, fill, execution, market data, trailing, connection` | IB Specialist | High |
| `slow, latency, cache, optimize, performance, memory` | Performance* | Medium |
| `login, permission, token, session, PII, password, encrypt` | Security* | Medium |

*Performance/Security nur wenn explizit aktiviert

### Multi-Agent Entscheidung

```
Wenn Task NUR Frontend Keywords:
  → Nur Frontend Specialist

Wenn Task NUR Backend Keywords:
  → Nur Backend Specialist

Wenn Task IB Keywords enthält:
  → IB Specialist PFLICHT
  → + Backend wenn State-Integration nötig
  → + Frontend wenn UI-Änderungen nötig

Wenn Task Frontend UND Backend Keywords:
  → Beide Specialists
  → Backend zuerst (liefert Contracts)
  → Frontend danach (nutzt Contracts)
```

### Selection Output Format

```
[TRIAGE]
═══════════════════════════════════════════════════════════════
Task: <kurze Beschreibung>
Size: S | M | L
Reason: <1 Satz warum diese Size>

Detected Keywords:
  - <keyword 1> → <Agent>
  - <keyword 2> → <Agent>

Agents Selected:
  ✅ <Agent 1>: <warum, 1 Satz>
  ✅ <Agent 2>: <warum, 1 Satz>
  
Agents Skipped:
  ⏭️ <Agent>: <warum nicht nötig, 1 Satz>

Execution Order:
  1. <Agent>
  2. <Agent>
  3. Review Gate
  4. QA Gate

Pipeline: Direct | Standard | Full
═══════════════════════════════════════════════════════════════
[/TRIAGE]
```

---

## Step 3: Pipeline Selection

### Direct Pipeline (Size S)

```
┌─────────┐     ┌───────────┐     ┌─────────────┐
│ Triage  │ ──▶ │ Implement │ ──▶ │ Self-Review │ ──▶ Done
└─────────┘     └───────────┘     └─────────────┘
     │
     └── 1 Agent, kein Branch, direkter Commit
```

**Regeln:**
- 1 Agent arbeitet alleine
- Inline Self-Review (keine separate Review-Phase)
- Kein Feature-Branch nötig
- Commit direkt auf current branch
- Hand-off Format: vereinfacht

### Standard Pipeline (Size M)

```
┌─────────┐     ┌────────────┐     ┌─────────┐     ┌───────────┐     ┌────────┐     ┌────┐
│ Triage  │ ──▶ │ Plan-Light │ ──▶ │ Branch  │ ──▶ │ Implement │ ──▶ │ Review │ ──▶ │ QA │ ──▶ Done
└─────────┘     └────────────┘     └─────────┘     └───────────┘     └────────┘     └────┘
                     │                                   │
                     │                                   └── 2-3 Agents sequentiell
                     └── Architect: Micro-Slices, AC, Files
```

**Regeln:**
- Architect erstellt Light-Plan
- Feature-Branch wird angelegt
- 2-3 Agents arbeiten sequentiell
- Voller Hand-off zwischen Agents
- Code Review Gate
- QA Gate

### Full Pipeline (Size L)

```
┌─────────┐     ┌───────────┐     ┌─────────┐     ┌─────────────────┐     ┌────────┐     ┌────┐     ┌─────────────┐
│ Triage  │ ──▶ │ Plan-Full │ ──▶ │ Branch  │ ──▶ │ Implement-Staged│ ──▶ │ Review │ ──▶ │ QA │ ──▶ │ Integration │ ──▶ Done
└─────────┘     └───────────┘     └─────────┘     └─────────────────┘     └────────┘     └────┘     └─────────────┘
                     │                                    │
                     │                                    └── Stages mit Zwischen-Reviews
                     └── Architect: Full Analysis, Dependencies, Rollback
```

**Regeln:**
- Architect erstellt Full Plan mit Risiko-Analyse
- Feature-Branch pflicht
- Implementation in Stages
- Review nach jeder Stage
- Alle Gates mandatory
- Integration Check am Ende

---

## Step 4: Edge Cases

### Unsichere Size-Entscheidung

```
Wenn unklar ob M oder L:
  → Starte mit M
  → Während Implement: wenn Scope wächst → Upgrade zu L
  → Dokumentiere Upgrade-Grund
```

### Agent nicht verfügbar

```
Wenn benötigter Custom Agent fehlt:
  → Prüfe ob Marketplace-Equivalent existiert
  → Wenn ja: nutze mit Context Injection
  → Wenn nein: Eskaliere zu Human

Wenn Marketplace Agent fehlschlägt:
  → Retry mit präziserem Context
  → Nach 2 Retries: Eskaliere
```

### Scope-Konflikt während Implement

```
Wenn Agent X Änderung in Scope von Agent Y braucht:
  → Stopp
  → [BLOCKER] melden
  → Architect entscheidet:
    a) Agent Y macht Änderung zuerst
    b) Scope-Erweiterung für Agent X
    c) Design überdenken
```

---

## Step 5: Output Summary

## Step 5: Output Summary

Nach Triage, gib aus:

```
╔═══════════════════════════════════════════════════════════════╗
║                     TRIAGE COMPLETE                            ║
╠═══════════════════════════════════════════════════════════════╣
║ Task:     <kurze beschreibung>                                 ║
║ Size:     S | M | L                                            ║
║ Pipeline: Direct | Standard | Full                             ║
║ Branch:   <branch-name> | n/a (direct)                         ║
╠═══════════════════════════════════════════════════════════════╣
║ EXECUTION ORDER                                                ║
╠═══════════════════════════════════════════════════════════════╣
║ 1. <Agent> (role: <was tut er>)                                ║
║ 2. <Agent> (role: <was tut er>)                                ║
║ 3. Review Gate                                                 ║
║ 4. QA Gate                                                     ║
╠═══════════════════════════════════════════════════════════════╣
║ ESTIMATED EFFORT                                               ║
╠═══════════════════════════════════════════════════════════════╣
║ Working Agents: <n>                                            ║
║ Gate Agents:    <n>                                            ║
║ Commits:        ~<n>                                           ║
╠═══════════════════════════════════════════════════════════════╣
║ RISKS (if any)                                                 ║
╠═══════════════════════════════════════════════════════════════╣
║ - <risk 1>                                                     ║
╚═══════════════════════════════════════════════════════════════╝
```

---

## Quick Reference Card

```
S = Simple    → 1 Agent, Direct, kein Branch
M = Medium    → 2-3 Agents, Standard, Feature-Branch  
L = Large     → 3+ Agents, Full, Staged Implementation

IB betroffen? → mindestens M
Auth/Security? → mindestens M
Breaking Change? → L
```
