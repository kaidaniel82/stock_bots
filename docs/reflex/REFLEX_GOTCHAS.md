# Reflex Framework - Kritische Gotchas

Diese Dokumentation beschreibt häufige Fehlerquellen bei Reflex-Anwendungen, die zu schwer zu debuggenden Problemen führen können.

## Problem 1: State-Variablen NIEMALS in-place modifizieren

### Symptom
- UI aktualisiert sich nicht nach Änderungen
- State geht verloren oder wird inkonsistent
- Frontend-Verbindung bricht ab

### Ursache
Reflex erkennt Änderungen nur bei **vollständiger Neuzuweisung** von State-Variablen.

### FALSCH
```python
class AppState(rx.State):
    data: dict[str, list] = {}
    items: list[int] = []

    def add_item(self, key: str):
        # FALSCH - In-place Modifikation
        self.data[key] = []
        self.items.append(42)
        del self.data["old_key"]
```

### RICHTIG
```python
class AppState(rx.State):
    data: dict[str, list] = {}
    items: list[int] = []

    def add_item(self, key: str):
        # RICHTIG - Vollständige Neuzuweisung
        new_data = dict(self.data)
        new_data[key] = []
        self.data = new_data

        # RICHTIG - Neue Liste erstellen
        self.items = self.items + [42]

        # RICHTIG - Dict ohne Key erstellen
        self.data = {k: v for k, v in self.data.items() if k != "old_key"}
```

---

## Problem 2: Nicht-serialisierbare Objekte im State

### Symptom
- Handler läuft erfolgreich durch (Logs zeigen Erfolg)
- Frontend zeigt keine Daten oder verliert Verbindung
- Keine offensichtliche Fehlermeldung

### Ursache
Reflex serialisiert State-Variablen als JSON für Frontend-Sync. Objekte wie:
- Custom Classes (z.B. ib_insync `ComboLeg`, `Contract`)
- Dataclasses ohne `to_dict()`
- Funktionen, Lambdas
- NaN/Infinity floats

...können nicht serialisiert werden und brechen die Synchronisation.

### FALSCH
```python
def _refresh_positions(self):
    for p in broker_positions:
        result.append({
            "con_id": p.con_id,
            "contract": p.raw_contract,  # FALSCH - TWS Contract Objekt
            "combo_legs": p.combo_legs,  # FALSCH - Liste von ComboLeg Objekten
        })
    self.positions = result
```

### RICHTIG
```python
def _refresh_positions(self):
    for p in broker_positions:
        result.append({
            "con_id": p.con_id,
            # Nur primitive Typen speichern
            "contract_id": p.raw_contract.conId if p.raw_contract else None,
            "combo_legs": [],  # Oder: [leg.conId for leg in p.combo_legs]
        })
    self.positions = result
```

### NaN-Werte behandeln
```python
import math

def safe_float(value: float) -> float:
    """Convert NaN/Inf to 0.0 for JSON serialization."""
    if math.isnan(value) or math.isinf(value):
        return 0.0
    return value
```

---

## Problem 3: Dateien im Projekt-Ordner triggern Hot Reload

### Symptom
- App kompiliert neu nach bestimmten Aktionen
- `Compiling: 100%` erscheint in Logs
- `on_mount` wird erneut aufgerufen
- Frontend-State geht verloren

### Ursache
Reflex's File Watcher überwacht den gesamten Projekt-Ordner. Wenn die App Dateien schreibt (z.B. JSON-Persistenz), triggert das einen Hot Reload.

### FALSCH
```python
# Datei im Projekt-Ordner
DATA_DIR = Path(__file__).parent / "data"
GROUPS_FILE = DATA_DIR / "groups.json"
```

### RICHTIG
```python
# Datei AUSSERHALB des Projekt-Ordners
DATA_DIR = Path.home() / ".myapp"
GROUPS_FILE = DATA_DIR / "groups.json"
```

Alternative: In `rxconfig.py` Ordner vom Watching ausschließen (falls unterstützt).

---

## Problem 4: Type Annotations bei Event Handlers

### Symptom
- `TypeError` oder Validierungsfehler bei Event-Aufruf
- Handler wird nicht korrekt aufgerufen

### Ursache
Reflex validiert Typen strikt. Bei Checkboxen z.B. kann der Wert als verschiedene Typen ankommen.

### FALSCH
```python
def update_checkbox(self, checked: bool, item_id: str):
    # Kann fehlschlagen wenn Reflex andere Typen sendet
    ...
```

### RICHTIG
```python
def update_checkbox(self, checked, item_id):
    # Keine Type Annotations - flexibler
    GROUP_MANAGER.update(str(item_id), enabled=bool(checked))
```

---

## Problem 5: Checkbox Label blockiert on_change Event

### Symptom
- Checkbox lässt sich nicht anklicken
- Kein Event im Backend-Log bei Klick
- Handler wird nie aufgerufen

### Ursache
Bei `rx.checkbox("Label", checked=..., on_change=...)` kann das Label als erstes Argument das Event-Handling stören.

### FALSCH
```python
rx.checkbox(
    "Time Exit",  # Label als erstes Argument
    checked=group["time_exit_enabled"],
    on_change=AppState.update_time_exit(group_id),
)
```

### RICHTIG
```python
rx.hstack(
    rx.checkbox(
        checked=group["time_exit_enabled"],
        on_change=AppState.update_time_exit(group_id),
    ),
    rx.text("Time Exit"),  # Label separat
)
```

---

## Problem 6: Partial Application - Argument-Reihenfolge

### Symptom
- Handler wird aufgerufen aber Argumente sind vertauscht
- `checked=grp_123, group_id=True` statt `group_id=grp_123, checked=True`
- Falsches Verhalten trotz korrekter Handler-Logik

### Ursache
Bei Reflex Partial Application `handler(arg)` werden die vordefinierten Argumente ZUERST übergeben, dann der Event-Wert.

```python
on_change=AppState.handler(group_id)
# Bei Klick wird aufgerufen: handler(group_id, event_value)
# NICHT: handler(event_value, group_id)
```

### FALSCH
```python
def update_time_exit(self, checked, group_id):
    # checked bekommt die group_id!
    # group_id bekommt den boolean!
    ...
```

### RICHTIG
```python
def update_time_exit(self, group_id, checked):
    # Reihenfolge: zuerst partial-Argumente, dann Event-Wert
    GROUP_MANAGER.update(str(group_id), enabled=bool(checked))
```

---

## Debugging-Checkliste

Wenn die App nach einer Aktion "kaputt geht":

1. **Backend-Logs prüfen** - Läuft der Handler durch?
   - Ja → Problem ist Serialisierung oder Hot Reload
   - Nein → Exception im Handler

2. **Auf "Compiling:" in Logs achten**
   - Erscheint nach Aktion → Datei im Projekt-Ordner wurde geschrieben

3. **State-Modifikationen prüfen**
   - Wird `self.dict[key] = value` verwendet? → In-place!
   - Wird `self.list.append()` verwendet? → In-place!

4. **Objekte im State prüfen**
   - Sind alle Werte primitive Typen (str, int, float, bool, list, dict)?
   - Gibt es NaN/Infinity Werte?

---

## Problem 7: @rx.var Computed Properties funktionieren NICHT in Nuitka Bundles

### Symptom
- App funktioniert in Entwicklung (`python main.py` oder `reflex run`)
- Nach Nuitka-Kompilierung fehlen Daten im Frontend
- WebSocket-Messages zeigen, dass computed vars (z.B. `position_rows_rx_state_`) **fehlen** im Delta
- Normale State-Variablen (z.B. `status_message_rx_state_`) funktionieren

### Ursache
`@rx.var` dekorierte computed properties werden zur Laufzeit berechnet und in den State-Delta eingefügt.
In Nuitka-kompilierten Bundles funktioniert dieser Mechanismus nicht korrekt - die computed vars werden
nie berechnet oder nie zum Delta hinzugefügt.

### FALSCH (funktioniert nicht in Nuitka)
```python
class AppState(rx.State):
    positions: list[dict] = []
    groups: list[dict] = []
    selected_group_id: str = ""

    @rx.var
    def position_rows(self) -> list[list[str]]:
        """Computed property - FUNKTIONIERT NICHT IN NUITKA!"""
        rows = []
        for p in self.positions:
            rows.append([p["symbol"], p["price"], ...])
        return rows

    @rx.var
    def groups_sorted(self) -> list[dict]:
        """Computed property - FUNKTIONIERT NICHT IN NUITKA!"""
        return sorted(self.groups, key=lambda g: g["name"])

    @rx.var
    def selected_underlying_symbol(self) -> str:
        """Computed property - FUNKTIONIERT NICHT IN NUITKA!"""
        if not self.selected_group_id:
            return ""
        # ... Berechnung ...
        return symbol
```

### RICHTIG (funktioniert in Nuitka)
```python
class AppState(rx.State):
    positions: list[dict] = []
    groups: list[dict] = []
    selected_group_id: str = ""

    # Computed vars als REGULÄRE State-Variablen
    position_rows: list[list[str]] = []
    groups_sorted: list[dict] = []
    selected_underlying_symbol: str = ""

    def _compute_position_rows(self):
        """Manuell aufrufen nach _refresh_positions()."""
        rows = []
        for p in self.positions:
            rows.append([p["symbol"], p["price"], ...])
        self.position_rows = rows  # State-Variable setzen!

    def _compute_groups_sorted(self):
        """Manuell aufrufen nach _load_groups_from_manager()."""
        self.groups_sorted = sorted(self.groups, key=lambda g: g["name"])

    def _compute_selected_underlying_symbol(self):
        """Manuell aufrufen bei select_group() und _render_all_charts()."""
        if not self.selected_group_id:
            self.selected_underlying_symbol = ""
            return
        # ... Berechnung ...
        self.selected_underlying_symbol = symbol

    def _refresh_positions(self):
        # ... Position-Logik ...
        self.positions = result
        self._compute_position_rows()  # WICHTIG: Manuell aufrufen!

    def _load_groups_from_manager(self):
        # ... Groups laden ...
        self.groups = result
        self._compute_groups_sorted()  # WICHTIG: Manuell aufrufen!
```

### Debugging
1. **Browser DevTools → Network → WS → Messages**
2. Suche nach dem State-Variable-Namen mit `_rx_state_` Suffix
3. Wenn es **fehlt** im Delta aber andere vars da sind → Computed var Problem

### Betroffene Dateien (dieses Projekt)
- `trailing_stop_web/state.py`:
  - `position_rows` → `_compute_position_rows()`
  - `groups_sorted` → `_compute_groups_sorted()`
  - `selected_underlying_symbol` → `_compute_selected_underlying_symbol()`

---

## Problem 8: Threading & Event Loop bei ib_insync Integration

### Symptom
- Buttons funktionieren in Dev-Mode (`reflex run`)
- Im Nuitka Bundle: Klick auf Button → keine Reaktion
- Logs zeigen: **`There is no current event loop in thread 'Thread-1 (start_backend)'`**
- Handler wird aufgerufen (Logs zeigen z.B. `toggle_group_active called`), aber IB-Operation schlägt fehl

### Ursache

**WICHTIG: Das Problem ist NICHT rx.foreach oder Partial Application!**

Das Problem ist Thread-Isolation bei asyncio Event Loops:

```
┌─────────────────────────┐     ┌─────────────────────────┐
│  Broker Thread          │     │  Reflex Backend Thread  │
│  (hat self._loop)       │     │  (KEIN Event Loop!)     │
│                         │     │                         │
│  self.ib.placeOrder()   │ ←── │  place_stop_order()     │
│  funktioniert hier!     │     │  CRASH! ❌               │
└─────────────────────────┘     └─────────────────────────┘
```

- **Dev-Mode:** Reflex/Uvicorn verwaltet Threads flexibler, Event Loops können geteilt werden
- **Nuitka Bundle:** Strikte Thread-Isolation, Backend-Thread hat keinen Zugriff auf Broker's Event Loop

### FALSCH (funktioniert nur in Dev)
```python
class TWSBroker:
    def __init__(self):
        self.ib = IB()
        self._loop = None  # Broker's event loop

    def place_stop_order(self, contract, quantity, stop_price, ...):
        # FALSCH: Direkter Aufruf - funktioniert NUR wenn
        # der aufrufende Thread einen Event Loop hat
        order = Order(...)
        trade = self.ib.placeOrder(contract, order)  # ❌ Crash in Nuitka!
        return trade
```

### RICHTIG (funktioniert in Dev UND Nuitka)
```python
class TWSBroker:
    def __init__(self):
        self.ib = IB()
        self._loop = None  # Broker's event loop, wird in connect() gesetzt

    def place_stop_order(self, contract, quantity, stop_price, ...):
        if not self._loop:
            logger.error("Cannot place order: no event loop available")
            return None

        # RICHTIG: Async-Funktion im Broker's Event Loop ausführen
        async def _place_async():
            try:
                trade = self.ib.placeOrder(contract, order)
                await asyncio.sleep(0.2)  # Warten auf Order-Status
                return trade
            except Exception as e:
                logger.error(f"Async place order error: {e}")
                return None

        try:
            # Thread-safe: Coroutine im richtigen Thread ausführen
            future = asyncio.run_coroutine_threadsafe(_place_async(), self._loop)
            trade = future.result(timeout=10)
            return trade
        except Exception as e:
            logger.error(f"Place order failed: {e}")
            return None
```

### Betroffene Methoden (müssen alle gefixt werden)
- `place_stop_order()`
- `modify_stop_order()`
- `place_time_exit_order()`
- `place_trailing_stop_order()`
- `modify_trailing_stop()`
- `cancel_order()`
- `cancel_oca_group()`

### Debugging
1. Suche nach `There is no current event loop` in Logs
2. Prüfe ob `self._loop` gesetzt ist beim Broker
3. Alle IB-Operationen die von Reflex-Handlern aufgerufen werden müssen `asyncio.run_coroutine_threadsafe()` verwenden

---

## ⚠️ WARNUNG: rx.foreach funktioniert in Nuitka!

### KEINE Static Slots implementieren!

Es gab einen Fehlschluss, dass `rx.foreach` mit Partial Application in Nuitka nicht funktioniert.
**Das war FALSCH.** Das eigentliche Problem war immer der Event Loop (siehe oben).

### RICHTIG (verwenden!)
```python
# rx.foreach mit partial application funktioniert PERFEKT in Nuitka
rx.foreach(AppState.groups, group_config_card)

def group_config_card(group: dict) -> rx.Component:
    group_id = group["id"]
    return rx.box(
        rx.button(
            "Activate",
            on_click=AppState.toggle_group_active(group_id),  # ✅ Funktioniert!
        ),
    )
```

### FALSCH (unnötige Komplexität!)
```python
# NICHT MACHEN - Static Slots sind unnötig und verkomplizieren den Code!
MAX_GROUPS = 10
SLOT_BUTTONS = [_make_slot_buttons(i) for i in range(MAX_GROUPS)]

def static_setup_groups():
    return rx.grid(
        *[_render_slot(i) for i in range(MAX_GROUPS)],  # ❌ Unnötig!
    )
```

### Warum der Fehlschluss entstand
1. Button-Klick → Handler wird aufgerufen (funktioniert!)
2. Handler ruft Broker-Methode auf → Event Loop Crash
3. **Falsche Annahme:** "Button funktioniert nicht" → "rx.foreach ist kaputt"
4. **Richtige Analyse:** Logs zeigen Handler wurde aufgerufen, Problem ist downstream

### Lehre
**IMMER die Logs prüfen bevor Workarounds implementiert werden!**
- Wenn Handler aufgerufen wird → Problem ist NICHT im UI/Component
- Wenn Handler NICHT aufgerufen wird → Dann UI/Component prüfen

---

## Zusammenfassung

| Problem | Symptom | Lösung |
|---------|---------|--------|
| In-place Modifikation | State-Verlust, keine UI-Updates | Immer neu zuweisen |
| Nicht-serialisierbar | Verbindungsabbruch nach Handler | Nur primitive Typen |
| Datei im Projekt | Hot Reload, "Compiling:" | Dateien außerhalb speichern |
| Type Annotations | Handler-Fehler | Annotations weglassen |
| Checkbox mit Label | Checkbox nicht klickbar | Label separat als rx.text() |
| Partial Application | Argumente vertauscht | `handler(partial_arg, event_value)` |
| @rx.var in Nuitka | Computed vars fehlen im Bundle | Reguläre State-Vars + manuelle Berechnung |
| **ib_insync Threading** | **"No current event loop" in Nuitka** | **`asyncio.run_coroutine_threadsafe()`** |
