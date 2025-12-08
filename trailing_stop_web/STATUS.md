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
- [x] **Market Rules Pre-Loading** beim Connect (siehe unten)
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
- [x] Market Rules Cache für Tick-Sizes

---

## Trading Hours Cache System (2025-12-08)

### Problem

Trading Hours müssen für `is_market_open()` bekannt sein, aber `reqContractDetails()` ist teuer und kann nicht während async Handlers aufgerufen werden.

### Architektur

```
Connect
   ↓
_attempt_connection()
   ↓
self._trading_hours_cache.clear()        ← Cache leeren
   ↓
_fetch_portfolio()
   ↓
Für jede Position: _fetch_trading_hours()  ← Trading Hours laden
   ↓
_trading_hours_cache = {
    "ES_FOP": {date: "20251208", trading_hours: "...", time_zone_id: "US/Central"},
    "SPX_OPT": {date: "20251208", trading_hours: "...", time_zone_id: "US/Central"},
    ...
}

Laufend (alle 0.5s im TWS Thread):
   ↓
_check_midnight_cache_clear()            ← Bei Datumswechsel: Cache leeren + neu laden
```

### Cache-Struktur

```python
_trading_hours_cache: dict[str, dict]
# Key: "SYMBOL_SECTYPE" (z.B. "ES_FOP", "SPX_OPT", "DAX_OPT")
# Value: {
#     date: "20251208",           # Für Invalidierung
#     trading_hours: "...",       # Raw TWS String
#     liquid_hours: "...",        # Liquid Hours
#     time_zone_id: "US/Central"  # Zeitzone
# }
```

### Wann wird geladen?

| Event | Aktion |
|-------|--------|
| Connect | Cache leeren, alle Positionen laden |
| Mitternacht | Cache leeren (wird bei nächstem Zugriff neu geladen) |
| Neue Position | Falls nicht gecached → laden |

### Dateien

| Datei | Funktion | Zeilen |
|-------|----------|--------|
| `broker.py` | `_trading_hours_cache` | ~259-262 |
| `broker.py` | `_fetch_trading_hours()` | ~559-620 |
| `broker.py` | `_check_midnight_cache_clear()` | ~345-351 |
| `broker.py` | `is_market_open()` | ~622-680 |

### Logging

```
Trading hours cache cleared on connect
Fetched trading hours for ES FOP: tz=US/Central
[MARKET] ES: OPEN via TradingHours (tz=US/Central)
Trading hours cache cleared at midnight (new day: 20251209)
```

---

## Market Rules & Tick-Size System (2025-12-08)

### Problem

IBKR erfordert, dass Order-Preise auf gültige Tick-Sizes gerundet werden. Die Tick-Size variiert je nach:
- **Instrument** (SPX, ES, DAX, TSLA, etc.)
- **Preisniveau** (z.B. ES FOP: $0.05 unter $5, $0.25 ab $5)

Für **BAG (Combo) Contracts** kann `reqContractDetails` nicht direkt aufgerufen werden - die Market Rules müssen vom ersten Leg geholt werden.

### Architektur

```
Connect
   ↓
_attempt_connection()
   ↓
_fetch_portfolio()           ← Positionen laden
   ↓
_preload_market_rules()      ← Market Rules für ALLE Positionen cachen
   ↓
_market_rules_cache = {
    (conId, exchange): [PriceIncrement(lowEdge=0, increment=0.05),
                        PriceIncrement(lowEdge=5, increment=0.25), ...]
}

Order Placement
   ↓
place_stop_order(contract, stop_price)
   ↓
_get_price_increment(contract, abs(stop_price))
   ↓
[BAG?] → Rekursiv mit erstem Leg Contract
   ↓
Cache Lookup: _market_rules_cache[(conId, exchange)]
   ↓
Preisniveau-Lookup: Finde increment für stop_price
   ↓
_round_to_tick(stop_price, increment)
```

### Wichtige Details

**1. Sync vs Async Context:**
- `reqContractDetails()` und `reqMarketRule()` können NICHT während async Event-Handlers aufgerufen werden (Event Loop Konflikt)
- Daher: **Pre-Loading bei Connect** (sync context im TWS Thread)

**2. Cache-Struktur:**
```python
_market_rules_cache: dict[tuple[int, str], list[PriceIncrement]]
# Key: (conId, exchange)
# Value: Liste von PriceIncrement mit lowEdge und increment
```

**3. BAG Contract Handling:**
```python
if contract.secType == "BAG":
    first_leg_id = contract.comboLegs[0].conId
    pos = self._positions.get(first_leg_id)
    return self._get_price_increment(pos.raw_contract, price)
    #                                                  ↑ ORDER Preis durchreichen!
```

**4. Preisniveau-Lookup:**
```python
for price_rule in rule:
    if price_rule.lowEdge <= price:
        increment = price_rule.increment
    else:
        break
```

### Beispiele

| Instrument | Preis | Tick-Size | Quelle |
|------------|-------|-----------|--------|
| ES FOP | $5.51 | 0.05 | MarketRule |
| ES FOP | $13.11 | 0.25 | MarketRule |
| SPX OPT | $2.50 | 0.05 | MarketRule |
| SPX OPT | $5.00 | 0.10 | MarketRule |
| DAX OPT | $66.00 | 0.50 | MarketRule |
| TSLA OPT | $0.05 | 0.01 | MarketRule |

### Dateien

| Datei | Funktion | Zeilen |
|-------|----------|--------|
| `broker.py` | `_preload_market_rules()` | ~1052-1111 |
| `broker.py` | `_get_price_increment()` | ~1110-1165 |
| `broker.py` | `_round_to_tick()` | ~1175-1190 |
| `broker.py` | `_market_rules_cache` | ~1050 |

### Logging

Bei Connect:
```
Pre-loading market rules for 14 positions...
Loaded market rule 239 for ES FOP: 2 price levels
Pre-loaded 14 market rules
```

Bei Order:
```
[TICK] ES FOP at $5.51: increment=0.05
[BROKER] Price rounding: $-5.5100 -> $-5.50 (tick=0.05)
```

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
- [x] SPX Options: $0.05 unter $3, $0.10 ab $3 (via MarketRules)
- [x] ES FOP: $0.05 unter $5, $0.25 ab $5 (via MarketRules)
- [x] DAX Options: $0.50 (via MarketRules)
- [x] TSLA Options: $0.01 (via MarketRules)
- [x] BAG Contracts: Tick vom ersten Leg
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
| 2025-12-08 | ES Put Spread | 2 | Credit | STP | ✅ | Tick=0.25 korrekt via MarketRules |
| 2025-12-08 | DAX Put | 1 | Debit | STP | ✅ | Tick=0.50 korrekt |
| 2025-12-08 | SPX Spread | 2 | Credit | STP | ✅ | Tick=0.10 korrekt |

---

## Bekannte Einschränkungen

1. **OCA Groups funktionieren nicht mit BAG Contracts** - Time Exit Orders werden ohne OCA platziert
2. **Trading Hours nur für Positionen** - Neue Contracts müssen erst geladen werden
3. **Entry Price aus Fills** - Nur 7 Tage Historie, danach avg_cost Fallback

---

## Changelog

### 2025-12-08 (Nachmittag)

**Market Rules Fix:**
- **Problem:** `reqContractDetails`/`reqMarketRule` schlugen fehl mit "This event loop is already running" während Order-Platzierung (async context)
- **Lösung:** Market Rules werden jetzt bei Connect vorgeladen (`_preload_market_rules()`)
- **Dateien:** `broker.py:328` (Aufruf), `broker.py:1052-1111` (Implementierung)

**BAG Tick-Size:**
- **Problem:** BAG Contracts haben keine eigenen ContractDetails
- **Lösung:** Tick-Size vom ersten Leg holen, ORDER-Preis für Level-Lookup verwenden
- **Datei:** `broker.py:1128-1138`

**Weitere Fixes:**
- Market Status zeigt jetzt korrekt "Open" via TradingHours Cache
- Trading Hours werden bei Connect für alle Positionen geladen
- Modification Counter in UI implementiert
- Cancel-Button verwendet jetzt `trailing_order_id`

### 2025-12-08 (Vormittag)

- App-kontrollierte Trailing Stops implementiert
- Dynamische Stop-Preis Modifikation via `modify_stop_order()`
- Entry Price aus 7-Tage Fills Historie
