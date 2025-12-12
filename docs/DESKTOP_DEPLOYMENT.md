# Desktop Deployment Guide

Dieses Dokument beschreibt den Installer-basierten Deployment-Ansatz für die Trailing Stop Manager Desktop-App mit Nuitka-Kompilierung und gebündeltem Bun-Runtime.

## Architektur

```
TrailingStopManager.app/
└── Contents/
    └── MacOS/
        ├── main_desktop        # Nuitka-kompiliertes Python (282MB)
        ├── bun                 # Bun JavaScript Runtime (60MB)
        ├── .web/               # Reflex Frontend (ohne node_modules)
        │   ├── app/
        │   ├── components/
        │   ├── package.json
        │   └── ...
        ├── trailing_stop_web/  # Python App-Module
        ├── assets/             # Icons
        └── *.so, *.dylib       # Native Libraries
```

### Komponenten

| Komponente | Aufgabe | Port |
|------------|---------|------|
| `main_desktop` | Backend (uvicorn + Reflex) | 8000 |
| `bun run dev` | Frontend (Vite Dev Server) | 5173 |
| System Tray | App-Kontrolle | - |

## Warum dieser Ansatz?

### Problem mit statischem Frontend-Export

Der ursprüngliche Ansatz (`reflex export --frontend-only`) hatte mehrere Probleme:

1. **Socket.IO Transport Mismatch**: Statisches Frontend verwendet Polling, Backend nur WebSocket
2. **Race Conditions**: Events kamen an bevor Session initialisiert war
3. **State nicht aktualisiert**: UI zeigte keine Daten trotz funktionierender Verbindung

### Lösung: Live Frontend mit Bun

Statt das Frontend statisch zu exportieren, führen wir `bun run dev` aus:

- Frontend entwickelt sich dynamisch mit Backend
- Keine Transport-Mismatches
- Keine Race Conditions bei der Initialisierung
- Volle HMR-Unterstützung (Hot Module Replacement)

**Trade-off**: ~60MB zusätzlich für Bun Runtime

---

## Build-Prozess (macOS)

### Voraussetzungen

```bash
# Python Dependencies
pip install nuitka pystray pillow

# Icons generieren (einmalig)
python scripts/generate_icons.py
```

### Build-Schritte

```bash
# Schritt 1: Nuitka-Kompilierung (10-30 Min beim ersten Mal)
./scripts/mac/1_nuitka.sh

# Schritt 2: .web Verzeichnis kopieren (ohne node_modules)
./scripts/mac/2_copy_web.sh

# Schritt 3: Bun Runtime hinzufügen
./scripts/mac/3_add_bun.sh

# Schritt 4: (Optional) .pkg Installer erstellen
./scripts/mac/4_create_pkg.sh
```

Oder alle Schritte auf einmal:

```bash
./scripts/mac/build.sh
```

### Testen

```bash
open dist/TrailingStopManager.app
```

---

## Kritische Code-Änderungen

### main_desktop.py - Backend Patches

**Wichtig**: Nur minimale Patches anwenden!

```python
def _apply_backend_patches(self):
    """Apply necessary patches for production mode."""
    import reflex.utils.js_runtimes

    # ONLY disable frontend package installation since we run Bun separately
    # Let Reflex compile normally - no _compile patch needed!
    reflex.utils.js_runtimes.install_frontend_packages = lambda *a, **kw: None

    logger.info("Applied minimal production patches (frontend handled by Bun)")
```

### Fehler, der vermieden werden muss

Der ursprüngliche `_backend_only_compile` Patch brach die State-Registrierung:

```python
# NICHT VERWENDEN - bricht Positions-Anzeige!
def _backend_only_compile(self, *args, **kwargs):
    self._apply_decorated_pages()
    self._pages = {}
    for route in self._unevaluated_pages:
        self._compile_page(route, save_page=False)
    self._add_optional_endpoints()
```

Dieser Patch übersprang kritische Initialisierungsschritte, wodurch State-Variablen nicht korrekt registriert wurden.

---

## Startup-Ablauf

```
1. main_desktop startet
   ├── Backend-Thread: uvicorn auf Port 8000
   │   └── Reflex kompiliert normal (20 pages)
   ├── Frontend-Thread: bun install && bun run dev
   │   └── Vite Dev Server auf Port 5173
   └── Main-Thread: System Tray

2. Nach ~30 Sekunden
   ├── Backend ready (8000)
   ├── Frontend ready (5173)
   └── Browser öffnet http://localhost:5173
```

---

## Bekannte Issues

### Port bereits belegt

Wenn Port 5173 belegt ist, wechselt Vite auf 5174. Die App wartet dann auf den falschen Port.

**Lösung**: Ports vor dem Start freigeben:
```bash
lsof -ti :5173 | xargs kill -9
lsof -ti :8000 | xargs kill -9
```

### SitemapPlugin Warnung

```
Warning: `reflex.plugins.sitemap.SitemapPlugin` plugin is enabled by default...
```

Harmlos - kann in `rxconfig.py` deaktiviert werden:
```python
config = rx.Config(
    disable_plugins=['reflex.plugins.sitemap.SitemapPlugin']
)
```

---

## Dateistruktur

```
scripts/
├── mac/
│   ├── config.sh           # Gemeinsame Konfiguration
│   ├── 1_nuitka.sh         # Nuitka-Kompilierung
│   ├── 2_copy_web.sh       # .web kopieren
│   ├── 3_add_bun.sh        # Bun hinzufügen
│   ├── 4_create_pkg.sh     # .pkg Installer
│   └── build.sh            # Alle Schritte
├── generate_icons.py       # Icon-Generierung
└── deploy.py               # (Legacy, nicht mehr verwendet)

assets/
├── AppIcon.icns            # macOS App Icon
├── AppIcon.ico             # Windows App Icon
├── TrayIconTemplate.png    # macOS Tray (weiß)
├── TrayIconTemplate@2x.png # macOS Tray @2x
└── EdgeSeeker-Icon.png     # Quell-Icon

installer/
└── mac/
    └── distribution.xml    # .pkg Konfiguration
```

---

## Windows (TODO)

Windows-Deployment folgt dem gleichen Konzept:

1. Nuitka mit `--windows-console-mode=disable`
2. Bun für Windows herunterladen
3. Inno Setup für Installer

---

## Troubleshooting

### App startet nicht

```bash
# Logs anzeigen
/path/to/TrailingStopManager.app/Contents/MacOS/main_desktop 2>&1
```

### Positionen werden nicht angezeigt

1. TWS/IB Gateway läuft?
2. Verbindung hergestellt? (Grüner Status)
3. Backend-Logs prüfen auf Errors

### Frontend lädt nicht

1. Port 5173 frei?
2. `bun install` erfolgreich?
3. `.web/node_modules` vorhanden?

---

## Legacy: Development Mode

Für Entwicklung ohne Nuitka:

```bash
# Standard Reflex development (hot reload)
reflex run

# Oder mit System Tray
python main.py
```

---

## Changelog

### 2024-12-12

- **Fix**: `@rx.var` computed properties funktionieren nicht in Nuitka Bundles
  - `position_rows` → reguläre State-Variable + `_compute_position_rows()`
  - `groups_sorted` → reguläre State-Variable + `_compute_groups_sorted()`
  - `selected_underlying_symbol` → reguläre State-Variable + `_compute_selected_underlying_symbol()`
- **Dokumentation**: Problem 7 in `docs/reflex/REFLEX_GOTCHAS.md` hinzugefügt

### 2024-12-11

- **Fix**: `_backend_only_compile` Patch entfernt - brach State-Registrierung
- **Refactored**: Minimale Patches in `_apply_backend_patches()`
- **Neu**: Modulare Build-Skripte für macOS
- **Neu**: Bun-basiertes Frontend statt statischem Export
