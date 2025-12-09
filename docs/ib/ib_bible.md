# IB / TWS Bible (Project)

Diese Datei ist die **kurz kuratierte Wahrheit** für unsere IB/TWS-Integration.
Sie ergänzt die offizielle Doku durch **unsere realen Erfahrungen**,
Edge Cases und konkrete Implementierungsregeln.

Primäre Integrationsdatei:
- `broker.py`

---

## 1) Architektur (Ist-Zustand)

- IB/TWS Zugriff konzentriert in `trailing_stop_web/broker.py`.
- `trailing_stop_web/broker.py` ist die zentrale Fassade für:
  - Verbindung
  - Orders
  - Status-Auswertung
  - Market Data
  - Fehlerbehandlung

**Regel:**  
Keine direkte IB-Nutzung außerhalb von `trailing_stop_web/broker.py`.

---

## 2) Verbindung / Reconnect

### Ziele
- stabile Verbindung
- nachvollziehbare Logs
- definierte Retry-Policy

### TODO: Unsere konkrete Policy
- Ports / Client IDs:
- Backoff-Strategie:
- Health-Check Mechanismus:

---

## 3) Order-Platzierung

### Unterstützte Ordertypen
- (TODO) Limit, Market, Stop, Combo/Options multi-leg, ...

### Interne Normalisierung
Wir definieren in `broker.py` eine Funktion(en) wie:
- `normalize_order_status(...)`
- `classify_ib_error(...)`

**Regel:**  
IB-Statusstrings werden **nur dort** interpretiert.

---

## 4) Order-Status / State-Mapping

IB liefert Status wie:
- PendingSubmit
- PreSubmitted
- Submitted
- Filled
- Cancelled
- Inactive
- ...

### TODO: Mapping-Tabelle
| IB Status | Interner Status | Notes |
|----------|------------------|------|
| ...      | ...              | ...  |

---

## 5) Fills / Executions

### TODO
- Wie wir Partial Fills aggregieren
- Welche Felder wir als canonical betrachten

---

## 6) Market Data & Market Depth

### TODO
- Unterschiedliche Subscriptions
- Umgang mit fehlenden Daten
- throttling / aggregation

---

## 6b) Market Rules & Tick Sizes

### Kernkonzept

**Tick Size ist PREIS-ABHÄNGIG!**

Viele Instrumente (besonders SPX-Optionen) haben unterschiedliche Tick-Sizes je nach Preisniveau:

| Preisniveau | Tick Size | Beispiel |
|-------------|-----------|----------|
| < $3.00     | 0.01      | $2.50 → gültige Preise: 2.50, 2.51, 2.52 |
| ≥ $3.00     | 0.05      | $4.60 → gültige Preise: 4.55, 4.60, 4.65 |

### Bug-Hintergrund (Fix Dezember 2024)

**Problem:** Trailing Stops verwendeten fälschlich `tick=0.01` für alle Preise.
Bei SPX-Optionen mit Preis ≥ $3.00 muss aber `tick=0.05` verwendet werden.

**Symptom:** Order-Rejection oder falsche Stop-Preise.

**Lösung:** Market Rules werden beim Connect geladen und gecacht.

### Implementierung in broker.py

```python
# 1. Cache-Initialisierung (Instanz-Variable!)
self._market_rules_cache: dict[tuple[int, str], list] = {}

# 2. Pre-Loading beim Connect
def _preload_market_rules(self):
    # Lädt reqMarketRule() für alle Positionen
    # Fallback: minTick aus ContractDetails

# 3. Tick-Size-Auflösung
def _get_price_increment(self, contract, price) -> float:
    # Sucht korrekte Tick-Size für gegebenen Preis
    # BAG (Combo): Holt Tick vom ersten Leg
```

### IB API Details

**Quelle der Wahrheit:**
1. `reqContractDetails()` → liefert `marketRuleIds` und `validExchanges`
2. `reqMarketRule(rule_id)` → liefert Liste von `PriceIncrement(lowEdge, increment)`

**Mapping:** `marketRuleIds` und `validExchanges` sind **positional gemappt**:
- `marketRuleIds[0]` gilt für `validExchanges[0]`
- `marketRuleIds[1]` gilt für `validExchanges[1]`
- usw.

**Fallback:** Wenn `reqMarketRule` leer zurückkommt → `minTick` aus ContractDetails verwenden.

### Beispiel: SPX Option Market Rule (ID 239)

```
lowEdge=0.0  → increment=0.01  (unter $3)
lowEdge=3.0  → increment=0.05  (ab $3)
```

### Testabdeckung

```
tests/ib/contract/test_market_rules.py  # Contract-Tests
tests/ib/fixtures/market_rules.py       # Fixtures mit echten IB-Daten
```

**Kritischer Test-Case:**
```python
def test_bug_case_price_460_must_use_005(self):
    """CRITICAL: Price $4.60 MUST use 0.05 tick (the original bug)."""
    assert get_tick_for_price(4.60) == 0.05  # NOT 0.01!
```

---

## 7) Fehler & Error-Codes

### Ziel
Fehler in Kategorien überführen, z. B.:
- CONFIG
- NETWORK
- ORDER_REJECTED
- RATE_LIMIT
- UNKNOWN

### TODO: Unsere häufigen Codes
| Code | Kategorie | Interpretation | Fix |
|------|----------|----------------|-----|
| ...  | ...      | ...            | ... |

---

## 8) Tests & Fixtures

Pflichtpfade:
- `tests/ib/contract/`
- `tests/ib/fixtures/`

**Regel:**  
Neue beobachtete IB-Strukturen → Fixture + Test + Bible-Notiz.

---

## 9) Pitfalls (unsere echten Stolpersteine)

Hier gehört rein, was euch schon Zeit gekostet hat.

### 9.1 Tick Size ist PREIS-ABHÄNGIG (Dezember 2024)

**Problem:** Hardcoded `tick=0.01` für alle Options-Preise.
**Realität:** SPX-Optionen (und viele andere) haben `tick=0.05` ab $3.00.
**Fix:** Market Rules beim Connect laden, Tick dynamisch nach Preis auflösen.
**Siehe:** Sektion 6b für Details.

### 9.2 Klassen-Variable vs. Instanz-Variable

**Problem:** `_market_rules_cache` war als Klassen-Variable definiert.
**Realität:** Instanz-Variablen MÜSSEN in `__init__` initialisiert werden.
**Fix:** Cache in `__init__` als `self._market_rules_cache = {}` initialisieren.

### 9.3 BAG (Combo) Contracts haben keine eigenen Market Rules

**Problem:** `reqMarketRule` für BAG-Contract liefert nichts Sinnvolles.
**Lösung:** Tick-Size vom **ersten Leg** des Combos verwenden.

### 9.4 Trading Hours Cache muss täglich invalidiert werden

**Problem:** Trading Hours ändern sich je nach Handelstag.
**Lösung:** Cache bei Datumswechsel (Mitternacht) leeren.

---

## 10) Offene Fragen / Risiken

- (TODO) Alles, was noch nicht 100% verlässlich verstanden ist
