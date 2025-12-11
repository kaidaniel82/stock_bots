# Nuitka Desktop Deployment - Aktueller Stand

**Datum:** 2025-12-11
**Status:** TEILWEISE FUNKTIONAL

---

## Zusammenfassung

Das macOS App Bundle wird erfolgreich gebaut und startet. Der Server läuft auf Port 8000.
Die IB-Verbindung funktioniert. **Einige App-Aspekte funktionieren noch nicht vollständig.**

---

## Was funktioniert

| Feature | Status | Details |
|---------|--------|---------|
| Nuitka Build | ✅ | Kompiliert in ~7 Minuten |
| App Bundle Struktur | ✅ | `TrailingStopManager.app/Contents/MacOS/` |
| Pfad-Erkennung | ✅ | `sys.executable.parent` für macOS Bundle |
| Server Start | ✅ | uvicorn auf Port 8000 |
| Static Frontend | ✅ | `.web/build/client/` wird gefunden |
| System Tray | ✅ | Icon erscheint, Menü funktioniert |
| IB Verbindung | ✅ | Positionen und Account-Daten werden geladen |
| Browser öffnet | ✅ | Automatisch bei Start |
| Monkey-Patches | ✅ | `get_app()`, `_compile()`, `install_frontend_packages()` |

---

## Was NICHT funktioniert (bekannte Probleme)

| Feature | Status | Details |
|---------|--------|---------|
| ??? | ❓ | Bitte spezifizieren was nicht klappt |

---

## Gelöste Probleme

### 1. Path Resolution (GELÖST)

**Problem:** `sys.executable.parent` lieferte `Contents/` statt `Contents/MacOS/`

**Lösung:** Für macOS App Bundles direkt `sys.executable.parent` verwenden (nicht `__compiled__.containing_dir`):

```python
def get_app_dir() -> Path:
    compiled_obj = globals().get("__compiled__", None)
    macos_bundle = getattr(compiled_obj, "macos_bundle_mode", False) if compiled_obj else False

    if macos_bundle:
        # macOS Bundle: sys.executable ist in Contents/MacOS/
        exe_path = Path(sys.executable).resolve()
        app_dir = exe_path.parent
        logger.info(f"Using app dir from sys.executable.parent: {app_dir}")
        return app_dir
    # ... weitere Fallbacks
```

### 2. rxconfig.py fehlte (GELÖST)

**Problem:** Reflex braucht `rxconfig.py` im CWD

**Lösung:** `rxconfig.py` wird ins Bundle kopiert (`scripts/deploy.py:_copy_assets()`)

### 3. Dynamic Module Import (GELÖST)

**Problem:** `ModuleNotFoundError: Module trailing_stop_web.trailing_stop_web not found`

Reflex's `get_app()` Funktion ruft `__import__()` auf, was in Nuitka nicht funktioniert.

**Lösung:** Monkey-Patch von `get_app()`:

```python
import trailing_stop_web.trailing_stop_web as app_module

def patched_get_app(reload: bool = False):
    return app_module
reflex.utils.prerequisites.get_app = patched_get_app
```

### 4. config.app_module ist read-only (GELÖST)

**Problem:** `property 'app_module' of 'Config' object has no setter`

**Lösung:** Statt `config.app_module` zu setzen, die `get_app()` Funktion direkt patchen (siehe oben).

---

## Architektur

### Bundle-Struktur

```
dist/TrailingStopManager.app/
└── Contents/
    ├── Info.plist
    ├── MacOS/
    │   ├── TrailingStopManager      # Executable
    │   ├── .web/                    # Frontend Build
    │   │   └── build/client/
    │   ├── rxconfig.py              # Reflex Config
    │   ├── trailing_stop_web/       # App Module Data
    │   │   └── EdgeSeeker-Icon.png
    │   └── *.so                     # Compiled Extensions
    └── Resources/
```

### Monkey-Patches im prod_code

1. **`App._compile`** - Deaktiviert Frontend-Build
2. **`install_frontend_packages`** - Deaktiviert npm/bun
3. **`get_app`** - Gibt pre-importiertes Modul zurück
4. **`config._app_name_is_valid`** - Überspringt Filesystem-Validierung

---

## Build-Kommandos

```bash
# Vollständiger Build (mit Frontend Export)
python scripts/deploy.py -v

# Build ohne Frontend Export (wenn .web/ bereits existiert)
python scripts/deploy.py -v --skip-export

# Nur für macOS
python scripts/deploy.py --target macos -v
```

---

## Test-Kommandos

```bash
# App starten
dist/TrailingStopManager.app/Contents/MacOS/TrailingStopManager

# Oder via open
open dist/TrailingStopManager.app

# Logs prüfen
dist/TrailingStopManager.app/Contents/MacOS/TrailingStopManager 2>&1 | head -50
```

---

## Erwartete Log-Ausgabe (funktionierend)

```
10:47:30 - INFO - sys.executable = .../Contents/MacOS/TrailingStopManager
10:47:30 - INFO - macos_bundle_mode = True
10:47:30 - INFO - Using app dir from sys.executable.parent: .../Contents/MacOS
10:47:30 - INFO - Working directory set to: .../Contents/MacOS
10:47:30 - INFO - Starting server...
10:47:31 - INFO - Disabled frontend compilation via monkey-patches
10:47:31 - INFO - Patched get_app() to return pre-imported module
10:47:31 - INFO - Server ready!
10:47:31 - INFO - System tray started
10:48:23 - INFO - Connecting to 127.0.0.1:7497 with clientId 50...
10:48:23 - INFO - Connected
10:48:23 - INFO - API connection ready
```

---

## Offene Fragen / TODO

- [ ] Welche App-Features funktionieren nicht? (User Feedback erforderlich)
- [ ] Windows Build testen
- [ ] Code Signing für Distribution
- [ ] Auto-Update Mechanismus

---

## Relevante Dateien

| Datei | Zweck |
|-------|-------|
| `scripts/deploy.py` | Build-Script mit prod_code Template |
| `trailing_stop_web/tray.py` | System Tray Integration |
| `rxconfig.py` | Reflex Konfiguration |
| `docs/NUITKA_MACOS_PATH_ISSUE.md` | Alte Dokumentation (veraltet) |

---

## Environment

- macOS 15.1 (Darwin 25.1.0)
- Python 3.11.13
- Nuitka 2.8.9
- Reflex 0.8.21
- Architecture: arm64 (Apple Silicon)
