# Trailing Stop Web - TODOs

## Stand: 2025-12-03

### Erledigt heute:
- [x] Stop P&L Berechnung gefixt (war falsch mit Multiplikator)
- [x] Horizontale Linien: solid mit Transparenz statt gestrichelt
- [x] Chart-Höhe auf 230px erhöht, X-Achsen Labels flacher (-25°)
- [x] Header-Ausrichtung mit `align="center"` gefixt
- [x] Label "extremum bundling" → "3-min bars"

### Erledigt (2025-12-04):
- [x] **Connect-Button absichern** - disabled statt hidden während connecting
- [x] **Datenspeicherung verschoben** - von `~/.trailing_stop_web/` nach `./data/`
- [x] **Performance-Logging** - tick_update() misst jetzt Dauer, warnt bei >100ms
- [x] **Trigger-Preis UI** - Dropdown für bid/ask/mid/mark/last existiert bereits
- [x] **Zahlen validiert** - Mid, Mark, P&L, Stop, Greeks korrekt implementiert
- [x] **Order Management (IB)** - BEREITS VOLLSTÄNDIG IMPLEMENTIERT in broker.py:599-927

### Offen (optional):

#### UI/UX Verbesserungen
- [ ] **Farben einheitlich machen** - konsistentes Farbschema durchziehen
- [ ] **Gruppen-Kachel optisch verbessern** - Layout, Abstände, Lesbarkeit
- [ ] **Portfolio-Filter** - Suchfeld für Symbol-Filter (z.B. "ES", "SPY", "S*" mit Wildcard-Support)

---

## Architektur Übersicht

```
trailing_stop_web/
├── state.py          # Reflex State, Broker-Integration
├── components.py     # UI Komponenten (Cards, Tables, etc.)
├── broker.py         # TWS Verbindung, Market Data
├── groups.py         # Group Management, JSON Persistence
├── metrics.py        # Greeks Berechnung, Group Valuations
├── config.py         # Konfiguration
└── logger.py         # Logging
```

## Wichtige Dateien

- **Groups JSON**: `./data/groups.json` (Projektordner)
- **App starten**: `.venv/bin/reflex run`
- **Tests**: `.venv/bin/pytest tests/test_ui.py -v`

## App URL
http://localhost:3000/ (oder nächster freier Port)
