# Hand-off Protocol

## Wann?

| Size | Handoff |
|------|---------|
| S | Nein |
| M | Ja |
| L | Ja (je Stage) |

---

## Format

```
[HANDOFF]
From: @agent
To: @agent
Status: complete | partial | blocked

FILES:
- <datei>: <was gemacht>

CONTRACTS:
- <function/class>: <signature>

NEXT:
- @agent: <aufgabe>
```

---

## Beispiel

```
[HANDOFF]
From: @ib-specialist
To: @backend-architect
Status: complete

FILES:
- broker.py: place_trailing_stop_order() hinzugefügt

CONTRACTS:
- broker.place_trailing_stop_order(symbol, qty, trail_pct) → Order

NEXT:
- @backend-architect: state.py Event Handler hinzufügen
```
