# Marketplace Agent Integration

> Anleitung zur Nutzung von Marketplace Agents (wshobson/agents).
> Diese Agents können NICHT modifiziert werden, nur gesteuert.

---

## Verfügbare Marketplace Agents

| Agent | Zweck | Stärken | Limitationen |
|-------|-------|---------|--------------|
| `backend-specialist` | Backend Code | Generisch, breit | Kennt Reflex nicht spezifisch |
| `frontend-specialist` | Frontend Code | Generisch, breit | Kennt Reflex nicht spezifisch |
| `code-review-ai` | Code Review | Gründlich | Kennt Projekt-Kontext nicht |
| `full-stack-orchestration` | Orchestration | Plan-Erstellung | Kann eigene Agents überschreiben |

---

## Grundprinzip: Context Injection

Da wir Marketplace Agents nicht modifizieren können, steuern wir sie über **präzise Kontextgabe**.

### Context Template

```markdown
═══════════════════════════════════════════════════════════════
CONTEXT FOR: <agent-name>
═══════════════════════════════════════════════════════════════

## PROJECT CONTEXT

Stack: Reflex.dev (Python full-stack, UI + Backend in Python)
Pattern: rx.State classes for state, rx.Component for UI
Solo-Dev project, Quality + Speed priority

## CRITICAL CONSTRAINTS

1. **DO NOT TOUCH:**
   - broker.py (IB Specialist only)
   - tests/ib/ (IB Specialist only)
   - docs/ib/ (IB Specialist only)

2. **SCOPE FOR THIS TASK:**
   <specific files/directories>

3. **PATTERNS TO FOLLOW:**
   - Typed everything (type hints required)
   - Docstrings for public APIs
   - Tests for non-trivial logic

## YOUR TASK

<präzise Beschreibung vom Architect Plan>

## CONTRACTS AVAILABLE

<aus vorherigen Hand-offs>
- ClassName.method() → return_type
- StateClass.field: type

## EXPECTED OUTPUT

<was genau erwartet wird>
- Files to create/modify
- Tests expected
- Hand-off format expected

═══════════════════════════════════════════════════════════════
```

---

## Agent-spezifische Hinweise

### backend-specialist

**Gut für:**
- Generische Python Backend-Logik
- Service-Klassen
- Data Models
- API-Integrationen (nicht IB)

**Context-Ergänzung:**
```markdown
## REFLEX SPECIFICS

- States inherit from rx.State
- Event handlers are methods on State classes
- Use @rx.var for computed properties
- Event handlers can be async

Example pattern:
```python
class MyState(rx.State):
    items: list[Item] = []
    is_loading: bool = False
    
    async def load_items(self):
        self.is_loading = True
        self.items = await service.get_items()
        self.is_loading = False
```
```

### frontend-specialist

**Gut für:**
- Generische UI-Komponenten
- Layout-Strukturen
- Styling-Anpassungen

**Context-Ergänzung:**
```markdown
## REFLEX SPECIFICS

- Components are Python functions returning rx.Component
- Use rx.cond() for conditional rendering
- Use rx.foreach() for lists
- State access via StateClass.field

Example pattern:
```python
def item_list() -> rx.Component:
    return rx.vstack(
        rx.foreach(MyState.items, item_card),
        rx.cond(
            MyState.is_loading,
            rx.spinner(),
            rx.text("Loaded"),
        ),
    )
```
```

### code-review-ai

**Gut für:**
- Code Quality Check
- Bug Detection
- Best Practice Enforcement

**Context-Ergänzung:**
```markdown
## REVIEW FOCUS

Please focus on:
1. Type safety (all functions should have type hints)
2. Error handling (no silent failures)
3. Scope compliance (changes only in allowed files)
4. Test coverage (critical paths tested)

## ALLOWED FILES FOR THIS CHANGE

<liste der erlaubten files>

## THINGS TO IGNORE

- broker.py style (managed by IB Specialist)
- Existing tech debt outside scope
```

---

## Output-Normalisierung

Marketplace Agents liefern nicht immer im Hand-off Format.
Der Orchestrator muss deren Output **normalisieren**:

### Schritt 1: Output parsen

```
Nach Marketplace Agent:
1. Identifiziere geänderte/erstellte Files
2. Extrahiere neue Funktionen/Klassen
3. Notiere erwähnte Tests
4. Finde offene Fragen/Concerns
```

### Schritt 2: In Hand-off übersetzen

```
[HANDOFF-NORMALIZED]
Original Agent: backend-specialist (marketplace)
Normalized by: Orchestrator

Files Changed:
- <extrahiert aus output>

Contracts Exposed:
- <extrahiert aus code>

Tests:
- <extrahiert oder "none mentioned">

Quality Notes:
- <concerns aus review>
[/HANDOFF-NORMALIZED]
```

---

## Fehlerbehandlung

### Agent versteht Task nicht

**Symptom:** Output ist off-topic oder zu generisch

**Lösung:**
1. Task noch präziser formulieren
2. Konkretes Beispiel geben
3. Expected Output Format zeigen

### Agent verletzt Constraints

**Symptom:** Ändert Files außerhalb Scope

**Lösung:**
1. Änderungen ignorieren
2. Task neu formulieren mit explizitem "DO NOT TOUCH"
3. Bei Wiederholung: Custom Agent nutzen

### Agent-Output nicht parsebar

**Symptom:** Kein klarer Code/Struktur

**Lösung:**
1. Explizit nach Code-Blöcken fragen
2. Format vorgeben (z.B. "Respond with only the Python code")
3. Manuell extrahieren

---

## Best Practices

1. **Immer Context Injection** - nie "nackt" aufrufen
2. **Scope explizit nennen** - "You may ONLY modify..."
3. **Expected Output definieren** - "I expect you to produce..."
4. **Constraints wiederholen** - wichtige Limits mehrfach nennen
5. **Output validieren** - prüfe ob Scope eingehalten wurde
6. **Normalize zu Hand-off** - für Pipeline-Konsistenz
