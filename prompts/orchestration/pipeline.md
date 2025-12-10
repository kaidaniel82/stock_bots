# Pipeline Protocol

> Definiert den Ablauf für jede Pipeline-Variante.
> Wird vom Orchestrator nach Triage ausgeführt.

## Verwendung mit Architect-light

Architect-light wählt auf Basis der TRIAGE-Entscheidung eine Pipeline
(Direct | Standard | Full) und erstellt dann einen [PLAN]-Block.

Das **Output-Format** von Architect-light ist in `prompts/agents/architect.md`
definiert. Dieses Dokument (`pipeline.md`) dient als Referenz, wie die
einzelnen Pipeline-Schritte aussehen sollen, und welche Gates (Review, QA,
Integration) dazugehören. Es definiert **KEIN eigenes Pflichtformat** für den
[PLAN]-Block, sondern nur die Inhalte, die der Plan berücksichtigen soll.

## Pipeline Variants
---

## 1. Direct Pipeline (Size S)
**Für:** Quick fixes, Typos, kleine Anpassungen (< 30 LOC, 1-2 Files)

### Ablauf

```
DIRECT PIPELINE
═══════════════

[1] TRIAGE
    └→ Size S bestätigt
    └→ 1 Agent ausgewählt

[2] IMPLEMENT
    Agent: <selected>
    └→ Änderungen durchführen
    └→ Inline Self-Review
    └→ Tests wenn sinnvoll

[3] COMMIT
    └→ Direkt auf current branch
    └→ Conventional commit message

DONE
```

### Regeln
- Kein separater Feature-Branch
- Kein externes Review nötig
- Agent macht Self-Review inline
- Commit direkt

---

## 2. Standard Pipeline (Size M)

**Für:** Features, Bugfixes, moderate Änderungen (30-150 LOC, 2-5 Files)

### Ablauf

```
STANDARD PIPELINE
═════════════════

[1] TRIAGE
    └→ Size M bestätigt
    └→ 2-3 Agents ausgewählt
    └→ Pipeline: Standard

[2] PLAN-LIGHT
    Agent: Architect
    └→ Micro-Slices definieren
    └→ Acceptance Criteria
    └→ File-Liste
    └→ Risiken (kurz)
    
    Output: [PLAN]...[/PLAN]

[3] GIT-BRANCH
    └→ Branch anlegen nach Schema
    └→ feat|fix|refactor/<name>

[4] IMPLEMENT
    Agents: <selected specialists>
    └→ Sequentielle Ausführung
    └→ Jeder Agent: [HANDOFF] am Ende
    └→ Scope-Grenzen einhalten

[5] REVIEW-GATE
    Agent: Reviewer
    └→ Code-Qualität prüfen
    └→ Scope-Leaks identifizieren
    └→ Test-Abdeckung prüfen
    
    Output: [REVIEW]...[/REVIEW]
    
    Bei Findings:
    └→ MINOR: dokumentieren, weiter
    └→ MAJOR: zurück zu [4]

[6] QA-GATE
    Agent: QA
    └→ Tests ausführen
    └→ Acceptance Criteria prüfen
    
    Output: [QA]...[/QA]
    
    Bei Failure:
    └→ zurück zu [4] mit Findings

[7] MERGE
    └→ Commits squash/rebase
    └→ PR/Merge

DONE
```

---

## 3. Full Pipeline (Size L)

**Für:** Große Features, Refactorings, kritische Änderungen (> 150 LOC, 5+ Files)

### Ablauf

```
FULL PIPELINE
═════════════

[1] TRIAGE
    └→ Size L bestätigt
    └→ 3+ Agents ausgewählt
    └→ Pipeline: Full

[2] PLAN-FULL
    Agent: Architect
    └→ Detaillierte Micro-Slices
    └→ Acceptance Criteria (detailliert)
    └→ Risiko-Analyse
    └→ Edge Cases
    └→ Abhängigkeiten zwischen Slices
    └→ Rollback-Strategie
    
    Output: [PLAN]...[/PLAN]
    
    ⚠️  Plan muss bestätigt werden vor Weitergang

[3] GIT-BRANCH
    └→ Feature-Branch pflicht
    └→ Optional: Task-Branches pro Slice

[4] IMPLEMENT-STAGED
    Agents: <selected specialists>
    
    Pro Stage:
    ┌─────────────────────────────────┐
    │ [4.x] STAGE: <slice name>       │
    │   └→ Agent implementiert        │
    │   └→ [HANDOFF]                  │
    │   └→ Mini-Review                │
    │   └→ Commit                     │
    └─────────────────────────────────┘
    
    Zwischen Stages: Sync-Point
    └→ Prüfe: Sind wir noch on track?
    └→ Bei Blocker: Eskalation zu Architect

[5] REVIEW-GATE
    Agent: Reviewer
    └→ Full Code Review
    └→ Architecture Review
    └→ Security Scan (wenn Auth betroffen)
    
    Output: [REVIEW]...[/REVIEW]

[6] QA-GATE
    Agent: QA
    └→ Alle Tests
    └→ Integration Tests
    └→ Edge Case Tests
    
    Output: [QA]...[/QA]

[7] INTEGRATION-CHECK
    └→ Merge-Konflikte lösen
    └→ Final test run
    └→ Smoke test

[8] MERGE
    └→ Commits aufräumen
    └→ PR mit Summary
    └→ Merge

DONE
```

---

## Rollback Protocol

### Bei QA Failure (Size M/L)

```
[QA-FAIL]
Severity: blocking | degraded | cosmetic

BLOCKING:
  └→ Stoppe Pipeline
  └→ Analysiere Failure
  └→ Optionen:
      a) Fix in place → zurück zu Implement
      b) Reset Slice → git reset soft
      c) Abort Feature → Branch löschen

DEGRADED:
  └→ Issue erstellen
  └→ Merge erlaubt mit known-issue Tag
  └→ Follow-up Task erstellen

COSMETIC:
  └→ Inline Fix
  └→ Weiter
```

### Bei Review Rejection

```
[REVIEW-REJECT]
Type: scope-leak | quality | security | design

SCOPE-LEAK:
  └→ Änderungen rückgängig die out-of-scope
  └→ Zurück zu Implement

QUALITY:
  └→ Specific Fixes
  └→ Re-Review nur geänderte Teile

SECURITY:
  └→ Stopp
  └→ Security Review erforderlich
  └→ Architect entscheidet

DESIGN:
  └→ Zurück zu Plan
  └→ Re-Design erforderlich
```

---

## State Tracking

Jeder Pipeline-Run trackt:

```
[PIPELINE-STATE]
id: <uuid>
task: <beschreibung>
size: S | M | L
pipeline: Direct | Standard | Full
branch: <name>

current_step: <step number>
current_agent: <name>

history:
  - step: 1, agent: Triage, status: complete
  - step: 2, agent: Architect, status: complete
  - step: 3, agent: Backend, status: in_progress

blockers: []
warnings: []
[/PIPELINE-STATE]
```
