# Git Conventions

> Branch- und Commit-Standards für alle Pipeline-Größen.

---

## Branch Schema

### Naming Convention

```
<type>/<kurz-beschreibung>

Typen:
- feat/     → Neues Feature
- fix/      → Bugfix
- refactor/ → Code-Umbau ohne Funktionsänderung
- perf/     → Performance-Verbesserung
- docs/     → Nur Dokumentation
- test/     → Nur Tests
- chore/    → Maintenance, Dependencies
```

### Beispiele

```
feat/position-refresh
fix/trailing-stop-activation
refactor/broker-error-handling
perf/state-update-batching
docs/ib-bible-orders
test/contract-tests-positions
```

### Branch pro Pipeline

| Pipeline | Branch erforderlich? |
|----------|---------------------|
| Direct (S) | Nein, direkt auf current |
| Standard (M) | Ja, Feature-Branch |
| Full (L) | Ja, Feature-Branch + optional Task-Branches |

---

## Commit Convention

### Format (Conventional Commits)

```
<type>(<scope>): <kurze beschreibung>

[optional body]

[optional footer]
```

### Types

| Type | Wann |
|------|------|
| `feat` | Neues Feature |
| `fix` | Bugfix |
| `refactor` | Code-Umbau |
| `perf` | Performance |
| `test` | Tests hinzufügen/ändern |
| `docs` | Dokumentation |
| `chore` | Maintenance |
| `style` | Formatting (kein Code-Change) |

### Scopes

| Scope | Bereich |
|-------|---------|
| `ui` | Frontend/Components |
| `state` | Reflex States |
| `service` | Backend Services |
| `auth` | Authentication |
| `ib` | Broker/IB Integration |
| `test` | Test Infrastructure |
| `docs` | Documentation |

### Beispiele

```bash
# Feature
feat(state): add PositionState with refresh logic

# Bugfix
fix(ib): handle disconnection during order placement

# Refactor
refactor(service): extract position calculations to service

# Tests
test(ib): add contract tests for get_positions

# Documentation
docs(ib): document trailing stop edge cases in bible
```

---

## Commit-Strategie pro Agent

### IB Specialist

```
# Immer eigener Commit-Block für IB-Änderungen
git commit -m "feat(ib): add trailing stop order support"
git commit -m "test(ib): add fixtures for trailing stop"
git commit -m "docs(ib): document trailing stop behavior"
```

### Backend Specialist

```
git commit -m "feat(state): add PositionState"
git commit -m "feat(service): add position service"
git commit -m "test(state): add position state tests"
```

### Frontend Specialist

```
git commit -m "feat(ui): add position table component"
git commit -m "style(ui): improve position table layout"
```

---

## Commit-Anzahl Guidelines

| Size | Empfohlene Commits |
|------|-------------------|
| S | 1 (alles zusammen) |
| M | 2-4 (logisch gruppiert) |
| L | 4-8 (pro Slice/Stage) |

### Commit-Gruppierung (Size M/L)

```
Nicht:
- "WIP"
- "Fix"
- "More changes"
- "Update file.py"

Sondern:
- Logisch zusammenhängende Änderungen
- Ein Commit pro "Konzept"
- Tests mit zugehörigem Code
```

---

## Merge-Strategie

### Size S (Direct)

```bash
# Direkt committen
git add .
git commit -m "fix(ui): correct button alignment"
```

### Size M (Standard)

```bash
# Feature-Branch
git checkout -b feat/position-display

# Arbeiten...
git commit -m "feat(state): add PositionState"
git commit -m "feat(ui): add position display"
git commit -m "test(state): add position tests"

# Merge (squash optional)
git checkout main
git merge feat/position-display
# oder: git merge --squash feat/position-display
```

### Size L (Full)

```bash
# Feature-Branch
git checkout -b feat/order-management

# Stage 1
git commit -m "feat(ib): add order placement"
git commit -m "test(ib): add order placement tests"

# Stage 2
git commit -m "feat(state): add OrderState"
git commit -m "feat(ui): add order form"

# Vor Merge: Commits aufräumen falls nötig
git rebase -i main

# Merge
git checkout main
git merge feat/order-management
```

---

## Pre-Commit Checklist

Vor jedem Commit:

```
[ ] Commit-Message folgt Convention
[ ] Scope ist korrekt
[ ] Keine "WIP" oder vage Messages
[ ] Tests laufen durch (wenn vorhanden)
[ ] Keine Debug-Prints/Logs vergessen
[ ] Keine Secrets/Credentials
```

---

## Rollback

### Letzten Commit rückgängig

```bash
# Soft (behalte Änderungen)
git reset --soft HEAD~1

# Hard (verwerfe Änderungen)
git reset --hard HEAD~1
```

### Feature-Branch abbrechen

```bash
git checkout main
git branch -D feat/broken-feature
```
