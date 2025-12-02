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

## Zusammenfassung

| Problem | Symptom | Lösung |
|---------|---------|--------|
| In-place Modifikation | State-Verlust, keine UI-Updates | Immer neu zuweisen |
| Nicht-serialisierbar | Verbindungsabbruch nach Handler | Nur primitive Typen |
| Datei im Projekt | Hot Reload, "Compiling:" | Dateien außerhalb speichern |
| Type Annotations | Handler-Fehler | Annotations weglassen |
| Checkbox mit Label | Checkbox nicht klickbar | Label separat als rx.text() |
| Partial Application | Argumente vertauscht | `handler(partial_arg, event_value)` |
