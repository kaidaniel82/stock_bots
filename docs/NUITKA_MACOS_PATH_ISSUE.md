# Nuitka macOS App Bundle - Path Resolution Issue

## Status: LÖSUNG GEFUNDEN

**Root Cause**: `sys.executable.parent` liefert im macOS App Bundle `Contents/` statt `Contents/MacOS/`

**Lösung**: Nuitka's `__compiled__.containing_dir` Feature verwenden

---

## Problem Summary

When building a Reflex app with Nuitka for macOS using `--macos-create-app-bundle`, the compiled executable fails to find the `.web/` directory containing the static frontend files.

## Error Output

```
09:01:59 - INFO - Working directory set to: /Users/kai/.../TrailingStopManager.app/Contents
09:01:59 - ERROR - Uvicorn server error: Directory '.web/build/client' does not exist
```

## Expected vs Actual

| Aspect | Expected | Actual |
|--------|----------|--------|
| Working Directory | `Contents/MacOS/` | `Contents/` |
| `.web/` Location | `Contents/MacOS/.web/` | `Contents/MacOS/.web/` (correct) |
| Result | App finds `.web/` | App fails - wrong CWD |

## Bundle Structure

```
TrailingStopManager.app/
└── Contents/
    ├── Info.plist
    ├── MacOS/
    │   ├── TrailingStopManager    (executable)
    │   ├── .web/                  (static frontend - EXISTS HERE)
    │   │   └── build/
    │   │       └── client/        (HTML/JS/CSS)
    │   ├── *.so                   (Python extensions)
    │   └── trailing_stop_web/     (app module)
    └── Resources/
```

## Root Cause Analysis

### Das Problem

Die bisherige `get_app_dir()` Funktion basiert auf `sys.executable`:

```python
def get_app_dir() -> Path:
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).parent  # Liefert Contents/ statt Contents/MacOS/
```

Im macOS App Bundle liefert `sys.executable.parent` unerwartet `Contents/` statt `Contents/MacOS/`.

---

## DIE LÖSUNG: `__compiled__.containing_dir`

Nuitka bietet seit einiger Zeit das Feature `__compiled__.containing_dir`, das explizit für dieses Problem designed wurde. Es abstrahiert das verschachtelte Layout von `--macos-create-app-bundle` und zeigt direkt auf das Verzeichnis, wo die "dist"-Files neben dem Binary liegen.

### Korrekte `get_app_dir()` Implementation

```python
def get_app_dir() -> Path:
    """Get the application directory (handles Nuitka + dev mode).

    Reihenfolge:
    1. Nuitka: __compiled__.containing_dir (empfohlen von Nuitka)
    2. Fallback: sys.executable-Heuristiken
    3. Dev-Mode: __file__-basierter Pfad
    """
    # 1. Bevorzugt: Nuitka-Spezialattribut verwenden
    compiled_obj = globals().get("__compiled__", None)
    containing_dir = getattr(compiled_obj, "containing_dir", None) if compiled_obj else None

    if containing_dir:
        base = Path(containing_dir).resolve()

        # Für macOS-App-Bundle:
        # - base kann bereits Contents/MacOS sein
        # - oder Contents, dann suchen wir MacOS davon
        candidates = [
            base,
            base / "MacOS",
            base.parent / "MacOS",
        ]

        for cand in candidates:
            if (cand / ".web").exists():
                logger.info(f"Using app dir from __compiled__.containing_dir: {cand}")
                return cand

        logger.warning(
            f"__compiled__.containing_dir gefunden ({base}), "
            f"aber keine .web/ in erwarteten Pfaden: {[str(c) for c in candidates]}"
        )
        return base

    # 2. Fallback für andere Frozen-Umgebungen (oder ältere Nuitka-Versionen)
    if getattr(sys, "frozen", False):
        exe_path = Path(sys.executable).resolve()
        exe_dir = exe_path.parent

        candidates = [
            exe_dir,
            exe_dir / "MacOS",
            exe_dir.parent / "MacOS",
        ]

        for cand in candidates:
            if (cand / ".web").exists():
                logger.info(f"Using app dir from sys.executable heuristic: {cand}")
                return cand

        logger.warning(
            f"Could not find .web via sys.executable. exe_path={exe_path}, "
            f"tried: {[str(c) for c in candidates]}"
        )
        return exe_dir

    # 3. Dev-Mode (direkt aus dem Source-Checkout)
    return Path(__file__).parent.parent
```

### Warum das funktioniert

1. **Nuitka setzt `__compiled__`** mit Attribut `containing_dir`, das genau dort hinzeigt, wo die "Payload" liegt (im App-Bundle-Fall effektiv `Contents/MacOS`)

2. **Systematische Prüfung** der Kandidaten:
   - `base`
   - `base / "MacOS"`
   - `base.parent / "MacOS"`

3. **Wählt ersten Pfad** unter dem `.web/` existiert

4. **`os.chdir(APP_DIR)`** sorgt dafür, dass CWD immer ein Verzeichnis ist, in dem `.web/build/client` existiert

### Debug-Logging (optional)

```python
logger.info(f"sys.executable = {sys.executable}")
logger.info(f"__file__ = {__file__}")
logger.info(f"os.getcwd() before chdir = {os.getcwd()}")

compiled_obj = globals().get("__compiled__", None)
if compiled_obj is not None:
    logger.info(f"__compiled__ present: {compiled_obj}")
    logger.info(f"getattr(__compiled__, 'containing_dir', None) = "
                f"{getattr(compiled_obj, 'containing_dir', None)}")
```

---

## Implementation

### Änderung in `scripts/deploy.py`

Die `get_app_dir()` Funktion im `prod_code` Template (Zeile ~195) muss durch die obige Version ersetzt werden.

### Build & Test

```bash
# Clean build
rm -rf build dist

# Build
python scripts/deploy.py --target macos -v

# Test
dist/TrailingStopManager.app/Contents/MacOS/TrailingStopManager
```

### Erwartetes Log nach Fix

```
sys.executable = .../Contents/MacOS/TrailingStopManager
__compiled__.containing_dir = .../Contents/MacOS
Using app dir from __compiled__.containing_dir: .../Contents/MacOS
Working directory set to: .../Contents/MacOS
Server ready!
```

---

## Related Files

- `scripts/deploy.py:154` - `_create_production_entry_point()` mit `prod_code` Template
- `build/main_prod.py` - Generierter Entry Point (wird nach Build gelöscht)
- `dist/TrailingStopManager.app/` - Output Bundle

## Environment

- macOS 15 (Darwin 26.1)
- Python 3.11.13
- Nuitka 2.8.9
- Reflex 0.8.x
- Architecture: arm64 (Apple Silicon)

## Referenzen

- [Nuitka Docs: `__compiled__` Object](https://nuitka.net/doc/user-manual.html#compiled-object)
