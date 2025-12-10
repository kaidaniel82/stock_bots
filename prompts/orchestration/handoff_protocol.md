# Hand-off Protocol

> Definiert wie Agents strukturiert Arbeit übergeben.
> Pflicht für jeden Agent am Ende seiner Arbeit.

---

## Warum strukturierte Hand-offs?

- Kein Wissen geht verloren
- Nächster Agent weiß genau was er bekommt
- Blocker werden sofort sichtbar
- Contracts sind explizit
- Debugging wird einfacher

---

## Hand-off Varianten

### Light Hand-off (Size S)

Für Direct Pipeline (Size S) reicht eine vereinfachte Version:

```
[HANDOFF-LIGHT]
Agent: <n>
Status: done | blocked
Files: <file1>, <file2>
Summary: <1-2 Sätze was gemacht wurde>
[/HANDOFF-LIGHT]
```

### Full Hand-off (Size M/L)

Für Standard/Full Pipeline ist das volle Format Pflicht:

```
╔═══════════════════════════════════════════════════════════════╗
║                         HAND-OFF                               ║
╠═══════════════════════════════════════════════════════════════╣
║ From:    <agent_name>                                          ║
║ To:      <next_agent_name>                                     ║
║ Status:  complete | partial | blocked                          ║
║ Time:    <optional: wie lange gedauert>                        ║
╠═══════════════════════════════════════════════════════════════╣
║ TASK COMPLETED                                                 ║
╠═══════════════════════════════════════════════════════════════╣
║ <1-2 Sätze: Was wurde erreicht>                                ║
╠═══════════════════════════════════════════════════════════════╣
║ ARTIFACTS CHANGED                                              ║
╠═══════════════════════════════════════════════════════════════╣
║ - path/to/file.py                                              ║
║   └→ <was wurde gemacht, 1 Zeile>                              ║
║   └→ Lines: +<added> / -<removed>                              ║
║ - path/to/other.py                                             ║
║   └→ <was wurde gemacht, 1 Zeile>                              ║
╠═══════════════════════════════════════════════════════════════╣
║ CONTRACTS EXPOSED (für nächsten Agent)                         ║
╠═══════════════════════════════════════════════════════════════╣
║ - ClassName.method(args) → return_type                         ║
║ - StateClass.field: type                                       ║
║ - function_name(args) → return_type                            ║
║ - ExceptionClass (wann geworfen)                               ║
╠═══════════════════════════════════════════════════════════════╣
║ CONTRACTS CONSUMED (vom vorherigen Agent)                      ║
╠═══════════════════════════════════════════════════════════════╣
║ - broker.get_positions() → list[Position]                      ║
║   └→ Funktioniert wie erwartet ✓                               ║
╠═══════════════════════════════════════════════════════════════╣
║ TESTS ADDED/CHANGED                                            ║
╠═══════════════════════════════════════════════════════════════╣
║ - tests/path/test_file.py::test_name                           ║
║   └→ Status: passing | pending                                 ║
╠═══════════════════════════════════════════════════════════════╣
║ OPEN QUESTIONS (optional, für Awareness)                       ║
╠═══════════════════════════════════════════════════════════════╣
║ - "Soll X auch Y behandeln?"                                   ║
║   └→ Impact: low | medium | high                               ║
╠═══════════════════════════════════════════════════════════════╣
║ BLOCKERS (nur wenn status=blocked/partial)                     ║
╠═══════════════════════════════════════════════════════════════╣
║ - "Benötige Entscheidung zu Z"                                 ║
║   └→ Blocking: <next agent> | pipeline                         ║
║   └→ Options: a) ... b) ...                                    ║
╚═══════════════════════════════════════════════════════════════╝
```

---

## Status Definitionen

### `complete`
- Alle geplanten Arbeiten erledigt
- Keine offenen Blocker
- Nächster Agent kann starten

### `partial`
- Teil der Arbeit erledigt
- Rest ist klar dokumentiert
- Nächster Agent kann parallel starten ODER
- Arbeit wird später fortgesetzt

### `blocked`
- Kann nicht weitermachen
- Blocker muss gelöst werden
- Pipeline pausiert bis Resolution

---

## Blocker Resolution

Wenn ein Agent `blocked` meldet:

```
[BLOCKER-RESOLUTION]
Blocker: <beschreibung>
Owner: <wer kann lösen>
Options:
  a) <option 1>
  b) <option 2>
Decision needed from: Architect | Human
[/BLOCKER-RESOLUTION]
```

Architect (oder Human) entscheidet:
- Option wählen
- Workaround definieren
- Task abbrechen

---

## Beispiele

### Backend → Frontend Hand-off

```
╔═══════════════════════════════════════════════════════════════╗
║                         HAND-OFF                               ║
╠═══════════════════════════════════════════════════════════════╣
║ From:    Backend Specialist                                    ║
║ To:      Frontend Specialist                                   ║
║ Status:  complete                                              ║
╠═══════════════════════════════════════════════════════════════╣
║ ARTIFACTS CHANGED                                              ║
╠═══════════════════════════════════════════════════════════════╣
║ - states/portfolio.py                                          ║
║   └→ Added PositionState with refresh logic                    ║
║ - services/position_service.py                                 ║
║   └→ New service for position calculations                     ║
╠═══════════════════════════════════════════════════════════════╣
║ CONTRACTS EXPOSED                                              ║
╠═══════════════════════════════════════════════════════════════╣
║ - PositionState.positions: list[Position]                      ║
║ - PositionState.refresh() → None (triggers API call)           ║
║ - PositionState.is_loading: bool                               ║
║ - PositionState.error: str | None                              ║
╠═══════════════════════════════════════════════════════════════╣
║ TESTS ADDED/CHANGED                                            ║
╠═══════════════════════════════════════════════════════════════╣
║ - tests/states/test_portfolio.py::test_refresh_positions       ║
║ - tests/states/test_portfolio.py::test_error_handling          ║
╠═══════════════════════════════════════════════════════════════╣
║ OPEN QUESTIONS                                                 ║
╠═══════════════════════════════════════════════════════════════╣
║ - none                                                         ║
╚═══════════════════════════════════════════════════════════════╝
```

### IB Specialist → Backend Hand-off

```
╔═══════════════════════════════════════════════════════════════╗
║                         HAND-OFF                               ║
╠═══════════════════════════════════════════════════════════════╣
║ From:    IB Specialist                                         ║
║ To:      Backend Specialist                                    ║
║ Status:  complete                                              ║
╠═══════════════════════════════════════════════════════════════╣
║ ARTIFACTS CHANGED                                              ║
╠═══════════════════════════════════════════════════════════════╣
║ - broker.py                                                    ║
║   └→ Added get_positions() with proper error handling          ║
║ - docs/ib/ib_bible.md                                          ║
║   └→ Documented position sync edge case                        ║
╠═══════════════════════════════════════════════════════════════╣
║ CONTRACTS EXPOSED                                              ║
╠═══════════════════════════════════════════════════════════════╣
║ - broker.get_positions() → list[Position]                      ║
║ - broker.BrokerError (exception class)                         ║
║ - Position dataclass: symbol, qty, avg_cost, market_value      ║
╠═══════════════════════════════════════════════════════════════╣
║ TESTS ADDED/CHANGED                                            ║
╠═══════════════════════════════════════════════════════════════╣
║ - tests/ib/contract/test_positions.py::test_get_positions      ║
║ - tests/ib/contract/test_positions.py::test_empty_portfolio    ║
║ - tests/ib/fixtures/position_response.json (new)               ║
╠═══════════════════════════════════════════════════════════════╣
║ OPEN QUESTIONS                                                 ║
╠═══════════════════════════════════════════════════════════════╣
║ - "Position.market_value kann None sein wenn Market closed"    ║
║   → Backend muss damit umgehen                                 ║
╚═══════════════════════════════════════════════════════════════╝
```

### Blocked Example

```
╔═══════════════════════════════════════════════════════════════╗
║                         HAND-OFF                               ║
╠═══════════════════════════════════════════════════════════════╣
║ From:    Frontend Specialist                                   ║
║ To:      Architect                                             ║
║ Status:  blocked                                               ║
╠═══════════════════════════════════════════════════════════════╣
║ ARTIFACTS CHANGED                                              ║
╠═══════════════════════════════════════════════════════════════╣
║ - components/position_table.py                                 ║
║   └→ Partial: table structure done, actions pending            ║
╠═══════════════════════════════════════════════════════════════╣
║ BLOCKERS                                                       ║
╠═══════════════════════════════════════════════════════════════╣
║ - "PositionState.close_position() nicht im Contract"           ║
║   → Benötige Backend-Erweiterung oder Design-Entscheidung      ║
║   → Optionen:                                                  ║
║     a) Backend fügt close_position() hinzu                     ║
║     b) UI zeigt nur read-only Daten                            ║
╚═══════════════════════════════════════════════════════════════╝
```

---

## Validation Checklist

Vor Abgabe des Hand-offs, prüfe:

- [ ] Status ist korrekt gesetzt
- [ ] Alle geänderten Dateien gelistet
- [ ] Contracts sind vollständig (Typen!)
- [ ] Tests sind referenziert
- [ ] Open Questions sind actionable
- [ ] Bei `blocked`: Optionen angegeben
