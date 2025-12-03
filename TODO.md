# Trailing Stop Web - TODOs

## Stand: 2025-12-03

### Erledigt heute:
- [x] Stop P&L Berechnung gefixt (war falsch mit Multiplikator)
- [x] Horizontale Linien: solid mit Transparenz statt gestrichelt
- [x] Chart-Höhe auf 230px erhöht, X-Achsen Labels flacher (-25°)
- [x] Header-Ausrichtung mit `align="center"` gefixt
- [x] Label "extremum bundling" → "3-min bars"

### Morgen zu erledigen (2025-12-04):

#### 1. UI/UX Verbesserungen
- [ ] **Farben einheitlich machen** - konsistentes Farbschema durchziehen
- [ ] **Gruppen-Kachel optisch verbessern** - Layout, Abstände, Lesbarkeit
- [ ] **Connect-Button absichern** - verhindern dass man mehrmals klicken kann (disabled während connecting)
- [ ] **Portfolio-Filter** - Suchfeld für Symbol-Filter (z.B. "ES", "SPY", "S*" mit Wildcard-Support)

#### 2. Performance
- [ ] **Speed checken** - tick_update() Dauer messen
- [ ] Identifizieren wo Zeit verloren geht
- [ ] Optimierungen implementieren falls nötig

#### 3. Validierung & Testing
- [ ] **End-to-End alle Zahlen validieren**
  - Mid, Mark, Bid, Ask korrekt?
  - P&L Berechnungen stimmen?
  - Stop-Preis Berechnung korrekt?
  - Greeks richtig aggregiert?

#### 4. Trailing Stop Erweiterungen
- [ ] **Trigger-Preis anpassbar machen**
  - Aktuell fest auf "mark"
  - UI: Dropdown für bid/ask/mid/mark/last
  - Backend: trigger_price_type aus Group verwenden

#### 5. Order Management (IB)
- [ ] **Orders bei IB platzieren**
  - OCA Group für Trailing Stop + Time Exit
  - Order Status monitoren
- [ ] **Orders anpassen bei HWM-Änderung**
  - Modify existing order vs Cancel/New
  - Trailing Order Preis updaten

#### 6. Refactoring
- [ ] **Datenspeicherung in Projektordner verschieben**
  - Aktuell: `~/.trailing_stop_web/groups.json` (User-Home)
  - Ziel: `./data/groups.json` (Projektordner)
  - Vorteil: Alles zusammen, einfacher zu backupen/versionieren
  - `.gitignore` für `data/` Ordner ergänzen

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

- **Groups JSON**: `~/.trailing_stop_web/groups.json`
- **App starten**: `.venv/bin/reflex run`
- **Tests**: `.venv/bin/pytest tests/test_ui.py -v`

## App URL
http://localhost:3000/ (oder nächster freier Port)
