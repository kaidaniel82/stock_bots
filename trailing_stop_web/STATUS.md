# Trailing Stop Web - Status & TODOs

## Aktueller Stand (2025-12-08)

### Architektur

Die App verwendet **app-kontrollierte Trailing Stops** statt TWS-native TRAIL Orders, da diese nicht mit BAG (Combo) Contracts funktionieren.

**Datenfluss:**
```
metrics.py (Berechnung) → state.py (Koordination) → broker.py (IBKR Orders)
                              ↓
                        components.py (UI)
```

### Module

| Modul | Funktion |
|-------|----------|
| `metrics.py` | Zentrale Berechnungen: `compute_group_metrics()`, `LegData`, `GroupMetrics` |
| `groups.py` | Persistenz (JSON), Group Dataclass, `GroupManager` |
| `state.py` | Reflex State, UI-Koordination, Tick-Updates |
| `broker.py` | TWS-Verbindung, Order-Platzierung/-Modifikation |
| `components.py` | UI-Komponenten (Radix UI) |

### Implementierte Features

#### Trailing Stop Logik
- [x] Credit/Debit Position Erkennung
- [x] High Water Mark (HWM) / Low Water Mark (LWM) Tracking
- [x] Prozentuale und absolute Trail-Werte
- [x] Stop-Market und Stop-Limit Orders
- [x] Trigger Price Types: mark, mid, bid, ask, last
- [x] Dynamische Stop-Preis Modifikation via `modify_stop_order()`

#### Order Management
- [x] Single-Leg Orders (direkt Contract)
- [x] Multi-Leg BAG (Combo) Orders
- [x] OCA Groups für Time Exit
- [x] Dynamische Preis-Increments via `_get_price_increment()` (MarketRules)
- [x] **Vorzeichen-Konsistenz:** `auxPrice`/`lmtPrice` IMMER positiv für IBKR (Action bestimmt Richtung)
- [x] Leg Action Inversion für BAG SELL Orders (`invert_leg_actions=True`)

#### UI
- [x] Position OHLC Chart mit HWM/LWM/Stop Linien
- [x] Underlying Chart
- [x] Gruppen-Karten mit Live-Metriken
- [x] Leg-Info mit Monospace-Formatierung
- [x] Credit/Debit Badge
- [x] Market Status (Open/Closed)

#### Broker
- [x] Auto-Reconnect mit Exponential Backoff
- [x] Trading Hours Cache (bei Connect und Mitternacht geleert)
- [x] Entry Price aus Fills (7 Tage Historie)
- [x] Market Data Subscriptions (reqMktData)

---

## TODO: Kritisch - Order Management Tests

**PRIORITÄT: HOCH** - Diese Tests müssen vor Production-Einsatz durchgeführt werden!

### 1. Multi-Leg Strategien testen

Bisher nur mit einfachen Spreads getestet. Folgende Strukturen müssen validiert werden:

| Strategie | Legs | Besonderheiten |
|-----------|------|----------------|
| **Straddle** | 2 (Call + Put, gleicher Strike) | Beide Legs long oder short |
| **Strangle** | 2 (Call + Put, verschiedene Strikes) | OTM Options |
| **Butterfly** | 3 (oder 4 bei Iron) | Ungleiche Ratios (1:-2:1) |
| **Iron Condor** | 4 | 2 Credit Spreads kombiniert |
| **Calendar Spread** | 2 | Verschiedene Expiries |
| **Ratio Spread** | 2 | Ungleiche Quantities (1:2, 1:3) |

**Test-Checkliste für jede Strategie:**

- [ ] Gruppe erstellt korrekt (position_quantities)
- [ ] `is_credit` korrekt erkannt
- [ ] `num_units` (GCD) korrekt berechnet
- [ ] BAG Contract korrekt aufgebaut
- [ ] Leg Actions korrekt (BUY/SELL)
- [ ] Order wird von TWS akzeptiert
- [ ] Stop-Preis korrekt (Vorzeichen)
- [ ] Limit-Preis korrekt (wenn Stop-Limit)
- [ ] Order-Modifikation funktioniert bei HWM-Änderung
- [ ] Order wird bei Stop-Trigger ausgeführt

### 2. Order Execution Tests

#### 2.1 Stop-Market Order
```
Szenario: Debit Spread, HWM=$5.00, Trail=15%
- Initial Stop: $4.25
- Preis steigt auf $6.00 → HWM=$6.00, Stop=$5.10
- Preis fällt auf $5.05 → Stop triggered!
- [ ] Order wird als Market Order ausgeführt
```

#### 2.2 Stop-Limit Order
```
Szenario: Credit Spread, LWM=-$3.00, Trail=20%, Limit Offset=$0.10
- Initial Stop: -$3.60 (BUY Stop)
- [ ] Limit Price = Stop + Offset = -$3.50
- [ ] Bei Trigger: Limit Order bei -$3.50
```

#### 2.3 Preis-Rounding
```
- [ ] SPX Options: $0.05 unter $3, $0.10 ab $3
- [ ] Andere Options: $0.01 oder $0.05
- [ ] Futures: Contract-spezifisch
```

### 3. Edge Cases

- [ ] Markt geschlossen → Keine Stop-Trigger
- [ ] Zero/Invalid Preise → Keine HWM-Updates
- [ ] Order bereits gefüllt → modify_stop_order() graceful fail
- [ ] TWS Disconnect während Order aktiv → Reconnect + Order-Status prüfen
- [ ] Position geschlossen außerhalb der App → Gruppe entfernen

### 4. Leg Action Inversion (KRITISCH!)

Bei SELL Orders auf BAG Contracts invertiert IBKR alle Leg Actions.

**Beispiel Debit Spread (Long Call Spread):**
- Position: +1 6000C, -1 6050C
- Zum Schließen: SELL der Position
- Ohne Inversion: Leg Actions = SELL 6000C, BUY 6050C
- IBKR invertiert bei SELL Order: BUY 6000C, SELL 6050C ← FALSCH!

**Lösung implementiert in `build_combo_contract(invert_leg_actions=True)`:**
- Wir pre-invertieren bei SELL: Leg Actions = BUY 6000C, SELL 6050C
- IBKR invertiert nochmal: SELL 6000C, BUY 6050C ← RICHTIG!

**WICHTIG (2025-12-08 Update):**
Durch manuelles Testen in TWS wurde festgestellt:
- **ALLE Combo Closing Orders verwenden SELL**
- **Preis-Vorzeichen bestimmt Credit/Debit:**
  - Debit Spread: SELL @ +$X.XX (positiver Preis = erhalten)
  - Credit Spread: SELL @ -$X.XX (negativer Preis = zahlen)

**Test:**
- [x] Debit Spread SELL Order → Legs korrekt, positiver Preis
- [x] Credit Spread SELL Order → Legs korrekt, negativer Preis

---

## TODO: Sonstige

### Nice-to-Have
- [ ] Order-Status Anzeige in UI (Submitted, Working, Filled, Cancelled)
- [ ] Fill-Bestätigung mit Sound/Notification
- [ ] Historische Trades Log
- [ ] Performance-Metriken (Win Rate, Avg P&L)

### Refactoring (nach Tests)
- [x] `calculate_stop_price()` - bereits korrekt importiert aus metrics.py in groups.py
- [x] Vorzeichen-Konsistenz in broker.py - `abs()` ENTFERNT für auxPrice/lmtPrice (Combos brauchen negative Preise!)
- [x] Combo Orders: Immer SELL, Preis-Vorzeichen bestimmt Credit/Debit
- [ ] Display-Funktionen vereinfachen (nur `abs()` bei String-Formatierung)

---

## Test-Protokoll

### Unit Tests (2025-12-08)

**70 Tests bestanden** (`tests/test_broker.py` + `tests/test_metrics.py`)

| Test-Kategorie | Status | Beschreibung |
|----------------|--------|--------------|
| `calculate_stop_price` | ✅ | Stop-Preis immer positiv (für IBKR) |
| Order Action - Single | ✅ | Long→SELL, Short→BUY |
| Order Action - Combo | ✅ | IMMER SELL, Preis-Vorzeichen bestimmt Credit/Debit |
| Leg Action Inversion | ✅ | IMMER pre-invertiert für Multi-Leg (alle SELL) |
| Stop Trigger Direction | ✅ | Debit: below HWM, Credit: above LWM |
| P&L Calculations | ✅ | Single legs, spreads, ratios |
| Greek Aggregation | ✅ | Position-weighted deltas |

### E2E Tests (2025-12-08)

**23 Tests bestanden, 1 übersprungen** (`tests/test_ui.py`)

| Test-Kategorie | Status | Beschreibung |
|----------------|--------|--------------|
| Page Load | ✅ | Hauptseite lädt korrekt |
| Tab Navigation | ✅ | Setup/Monitor Tab-Wechsel |
| TWS Connection | ✅ | Connect Button, Status Updates |
| Order Flow | ✅ | Positionen laden, Gruppe erstellen, Aktivieren/Deaktivieren |
| Stop Price Display | ✅ | Stop-Preis in UI angezeigt |

### Manuelle TWS Tests

| Datum | Strategie | Legs | Credit/Debit | Order Type | Ergebnis | Notizen |
|-------|-----------|------|--------------|------------|----------|---------|
| | | | | | | |

---

## Bekannte Einschränkungen

1. **OCA Groups funktionieren nicht mit BAG Contracts** - Time Exit Orders werden ohne OCA platziert
2. **Trading Hours nur für Positionen** - Neue Contracts müssen erst geladen werden
3. **Entry Price aus Fills** - Nur 7 Tage Historie, danach avg_cost Fallback
