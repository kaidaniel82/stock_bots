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
# LOGGING
# =============================================================================

# Ausfuehrliche Portfolio-Updates im Terminal anzeigen
VERBOSE_PORTFOLIO_UPDATES = True

# Nur Aenderungen loggen (nicht jeden Poll)
LOG_ONLY_CHANGES = True
