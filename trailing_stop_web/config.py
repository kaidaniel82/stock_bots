"""
Zentrale Konfiguration fuer Trailing Stop Manager
==================================================

Alle Einstellungen hier anpassen.
"""

# =============================================================================
# TWS VERBINDUNG
# =============================================================================

# TWS Host (normalerweise localhost)
TWS_HOST = "127.0.0.1"

# TWS Port
#   - 7497 = Paper Trading (Simulation)
#   - 7496 = Live Trading
TWS_PORT = 7497

# Client ID (muss eindeutig sein wenn mehrere Verbindungen)
TWS_CLIENT_ID = 1

# Account Nummer (leer = automatisch erster Account)
TWS_ACCOUNT = ""


# =============================================================================
# UPDATE INTERVALLE (in Sekunden)
# =============================================================================

# Wie oft der Broker das Portfolio von TWS holt
BROKER_UPDATE_INTERVAL = 0.5

# Wie oft die Web-UI aktualisiert wird
UI_UPDATE_INTERVAL = 0.5

# Chart Bar-Intervall: Anzahl Ticks bis ein neuer 3-min Bar erstellt wird
# Bei 500ms UI_UPDATE_INTERVAL: 360 ticks = 3 Minuten
BAR_INTERVAL_TICKS = 360

# Chart-Rendering: Alle N Ticks rendern (2 = jede Sekunde bei 500ms interval)
CHART_RENDER_INTERVAL = 2

# UI Position Table Throttle: Alle N Ticks die position_rows aktualisieren
# Bei 500ms UI_UPDATE_INTERVAL: 3 ticks = 1.5 Sekunden
# Reduziert CPU-Last für UI-Rendering, Trading-Logik läuft weiterhin jeden Tick!
UI_POSITION_THROTTLE_INTERVAL = 3


# =============================================================================
# TRAILING STOP DEFAULTS
# =============================================================================

# Standard Trail-Prozent fuer neue Gruppen
DEFAULT_TRAIL_PERCENT = 15.0

# Standard Stop-Typ: "market" oder "limit"
DEFAULT_STOP_TYPE = "market"

# Standard Limit-Offset (nur bei limit orders)
DEFAULT_LIMIT_OFFSET = 0.10


# =============================================================================
# TWS RECONNECTION
# =============================================================================

# Initial delay before first reconnection attempt (seconds)
RECONNECT_INITIAL_DELAY = 5

# Maximum delay between reconnection attempts (seconds)
RECONNECT_MAX_DELAY = 60

# Backoff multiplier (delay doubles each attempt until max)
RECONNECT_BACKOFF_FACTOR = 2

# Maximum reconnection attempts (0 = unlimited)
RECONNECT_MAX_ATTEMPTS = 0

# Heartbeat interval for watchdog (seconds)
# Sends reqCurrentTime() to detect silent disconnects
HEARTBEAT_INTERVAL = 10

# Heartbeat timeout (seconds) - if no response within this time, consider disconnected
HEARTBEAT_TIMEOUT = 5


# =============================================================================
# LOGGING
# =============================================================================

# Ausfuehrliche Portfolio-Updates im Terminal anzeigen
VERBOSE_PORTFOLIO_UPDATES = True

# Nur Aenderungen loggen (nicht jeden Poll)
LOG_ONLY_CHANGES = True
