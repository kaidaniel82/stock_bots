# Nuitka Deployment - Socket.IO Issues

## Überblick

Dieses Dokument beschreibt die Probleme beim Deployment der Reflex-App als Nuitka-Bundle, speziell bezüglich Socket.IO und der WebSocket-Kommunikation zwischen Frontend und Backend.

---

## Problem 1: Transport Mismatch

### Symptom
```
Invalid transport
```
Der Server akzeptiert nur WebSocket, aber das Frontend (pre-exported) startet mit Polling.

### Ursache
Reflex konfiguriert den Socket.IO Server mit:
```python
transports=[config.transport]  # nur 'websocket'
allow_upgrades=False
```

Das pre-exportierte Frontend verwendet jedoch standardmäßig Polling zuerst und upgradet dann zu WebSocket.

### Lösung (implementiert in deploy.py)
```python
import socketio

_original_async_server_init = socketio.AsyncServer.__init__

def _patched_async_server_init(self, *args, **kwargs):
    kwargs['transports'] = ['polling', 'websocket']
    kwargs['allow_upgrades'] = True
    kwargs['cors_allowed_origins'] = '*'
    kwargs['cors_credentials'] = True
    return _original_async_server_init(self, *args, **kwargs)

socketio.AsyncServer.__init__ = _patched_async_server_init
```

**Wichtig:** Dieser Patch muss VOR dem Import des App-Moduls angewendet werden, da `rx.App()` beim Modul-Import erstellt wird.

---

## Problem 2: Socket.IO Environ Race Condition

### Symptom
```
RuntimeError: Socket.IO environ is not initialized.
```
Tritt als "Task exception was never retrieved" auf, verhindert Event-Verarbeitung.

### Ursache
Bei Polling-Transport können Events ankommen BEVOR die Session vollständig registriert ist:

1. Client sendet HTTP Polling Request
2. Server erstellt Engine.IO Session
3. `_handle_eio_connect` wird aufgerufen → `self.environ[eio_sid] = environ`
4. **Race Condition:** Event kommt an bevor Schritt 3 abgeschlossen ist
5. `get_environ(sid, namespace)` gibt `None` zurück
6. Reflex wirft RuntimeError

### Code-Pfad (socketio + reflex)
```
socketio/base_server.py:213
    def get_environ(self, sid, namespace=None):
        eio_sid = self.manager.eio_sid_from_sid(sid, namespace or '/')
        return self.environ.get(eio_sid)  # Returns None if race condition

reflex/app.py:2193-2196
    environ = self.app.sio.get_environ(sid, self.namespace)
    if environ is None:
        msg = "Socket.IO environ is not initialized."
        raise RuntimeError(msg)  # Crashes the event handler
```

### Lösung (implementiert in deploy.py)
Patch für `EventNamespace.on_event` mit Retry-Logik:

```python
import reflex.app

_original_event_namespace_on_event = reflex.app.EventNamespace.on_event

async def _patched_on_event(self, sid, data):
    """Patched on_event with retry logic for environ race condition."""
    import asyncio
    max_retries = 5
    retry_delay = 0.1  # 100ms

    for attempt in range(max_retries):
        if self.app.sio is not None:
            environ = self.app.sio.get_environ(sid, self.namespace)
            if environ is not None:
                return await _original_event_namespace_on_event(self, sid, data)

        if attempt < max_retries - 1:
            await asyncio.sleep(retry_delay)

    # After all retries, skip event silently instead of crashing
    logger.warning(f"on_event: environ not initialized after {max_retries} retries, skipping")
    return None

reflex.app.EventNamespace.on_event = _patched_on_event
```

---

## Problem 3: UI zeigt keine Daten trotz WebSocket-Verbindung

### Symptom
- WebSocket-Verbindung funktioniert (Status 101)
- Events werden gesendet (`tick_update` alle 500ms)
- Server antwortet mit vollständigen Daten (`positions_rx_state_` mit 6 Positionen)
- **Aber:** UI zeigt leeres Portfolio

### Beobachtungen (Browser DevTools → Network → WS → Messages)
```json
// Server sendet korrekte Daten:
{
  "positions_rx_state_": [
    {"con_id": 788328046, "symbol": "MES", "bid_str": "44.90", ...},
    // ... 5 weitere Positionen
  ],
  "status_message_rx_state_": "Monitoring... (12:33:24)",
  "refresh_tick_rx_state_": 1547
}
```

### Mögliche Ursachen (noch zu untersuchen)
1. **State Variable Naming Mismatch:** Frontend erwartet andere Namen als Backend sendet
2. **Computed Vars nicht berechnet:** `position_rows` ist eine `@rx.var` computed property
3. **React State nicht aktualisiert:** Delta-Updates werden nicht korrekt angewendet
4. **Hydration Problem:** Initial State stimmt nicht mit Server State überein

### Zusammenhang mit Problem 2
Wenn die ersten Events wegen der Race Condition verloren gehen, könnte die initiale Hydration fehlschlagen. Das würde erklären, warum spätere Daten nicht angezeigt werden.

---

## Problem 4: Nuitka Build Fehler

### Symptom 1: Symlink-Fehler
```
FileExistsError: [Errno 17] File exists: '../acorn/bin/acorn' -> 'dist/.../.web/node_modules/.bin/acorn'
```

### Ursache
`node_modules/.bin/` enthält Symlinks. Nuitka kann diese nicht korrekt kopieren.

### Lösung
`.web` ohne Symlinks kopieren:
```bash
cp -RL .web /tmp/web_for_nuitka/.web
```

### Symptom 2: Argument list too long
```
OSError: [Errno 7] Argument list too long: '/usr/bin/codesign'
```

### Ursache
29539 Dateien in `.web` (hauptsächlich `node_modules`) - zu viele für macOS codesign.

### Lösung
Minimale `.web` Version ohne `node_modules`:
```bash
# Nur Runtime-relevante Dateien kopieren:
mkdir -p /tmp/web_minimal/.web
cp -r .web/app /tmp/web_minimal/.web/
cp -r .web/build /tmp/web_minimal/.web/
cp -r .web/public /tmp/web_minimal/.web/
cp -r .web/styles /tmp/web_minimal/.web/
cp -r .web/utils /tmp/web_minimal/.web/
cp .web/*.json .web/*.js /tmp/web_minimal/.web/
```

`node_modules` wird nur für `reflex run` (Development) und `reflex export` (Build) benötigt, nicht für Runtime.

---

## Aktuelle Patch-Reihenfolge in deploy.py

```python
# 1. Backend-only compile (skip frontend generation)
reflex.app.App._compile = _backend_only_compile

# 2. Disable frontend package installation
reflex.utils.js_runtimes.install_frontend_packages = lambda *args, **kwargs: None

# 3. Patch Socket.IO transports (BEFORE app import!)
socketio.AsyncServer.__init__ = _patched_async_server_init

# 4. Patch get_environ for race condition debugging
socketio.base_server.BaseServer.get_environ = _patched_get_environ

# 5. Patch on_event with retry logic
reflex.app.EventNamespace.on_event = _patched_on_event

# 6. Import app module (creates rx.App instance)
import trailing_stop_web.trailing_stop_web as app_module

# 7. Patch get_app() to return pre-imported module
reflex.utils.prerequisites.get_app = patched_get_app
```

---

## Status

| Problem | Status | Lösung |
|---------|--------|--------|
| Transport Mismatch | ✅ Gelöst | Nicht mehr relevant - Bun-basiertes Frontend |
| Environ Race Condition | ✅ Gelöst | Nicht mehr relevant - Bun-basiertes Frontend |
| UI zeigt keine Daten | ✅ Gelöst | `_backend_only_compile` Patch entfernt |
| Nuitka Symlinks | ✅ Gelöst | .web ohne node_modules kopieren |
| Nuitka Codesign | ✅ Gelöst | .web separat kopieren nach Nuitka-Build |
| **@rx.var nicht in Nuitka** | ✅ Gelöst | Reguläre State-Vars + manuelle `_compute_*()` Methoden |

---

## Lösung: Neuer Ansatz

**Statt statischem Frontend-Export verwenden wir jetzt Bun als gebündelten Runtime.**

Siehe [DESKTOP_DEPLOYMENT.md](./DESKTOP_DEPLOYMENT.md) für Details.

### Kernänderung in main_desktop.py

```python
def _apply_backend_patches(self):
    """Apply necessary patches for production mode."""
    import reflex.utils.js_runtimes

    # ONLY disable frontend package installation since we run Bun separately
    # Let Reflex compile normally - no _compile patch needed!
    reflex.utils.js_runtimes.install_frontend_packages = lambda *a, **kw: None
```

**Wichtig**: Der `_backend_only_compile` Patch wurde entfernt, da er die State-Registrierung brach.

---

## Relevante Dateien

- `scripts/deploy.py` - Alle Monkey-Patches für Production
- `trailing_stop_web/state.py` - AppState mit `positions`, `position_rows`
- `.web/utils/context.js` - Frontend State Definitionen
- `.web/app/routes/_index.jsx` - React Components
- `docs/NUITKA_DEPLOYMENT_STATUS.md` - Allgemeiner Deployment Status
