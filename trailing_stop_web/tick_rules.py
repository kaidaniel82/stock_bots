"""
Tick size rules for combo/spread orders.

IB does NOT provide ContractDetails for BAG (combo) contracts.
Error 321: 'BAG' isn't supported for contract data request.

Therefore we need a lookup table for combo tick sizes based on exchange rules.

Sources:
- SPX/SPXW: https://www.cboe.com/tradable_products/sp_500/spx_options/specifications/
  "For complex orders, legs may trade in $.01 increments, but net package
   price must be in $.05 increments"
- ES: CME rules (to be researched)
- TSLA/Equities: Penny Pilot program allows $0.01 for most spreads
"""
from dataclasses import dataclass
from typing import Optional


@dataclass
class TickRule:
    """Tick size rule for a symbol."""
    combo_tick: float          # Tick size for combo/spread orders
    single_tick_default: float # Default single-leg tick (if not using market rules)
    exchange: str              # Primary exchange
    notes: str = ""            # Documentation


# Combo tick size overrides by symbol
# Key: symbol (uppercase)
# Value: TickRule with combo-specific tick size
COMBO_TICK_RULES: dict[str, TickRule] = {
    # SPX Index Options (CBOE)
    # Single-leg: $0.05 below $3, $0.10 at/above $3
    # Combo/Spread: Always $0.05 net price
    "SPX": TickRule(
        combo_tick=0.05,
        single_tick_default=0.10,
        exchange="CBOE",
        notes="CBOE: Complex orders net price must be in $0.05 increments"
    ),
    "SPXW": TickRule(
        combo_tick=0.05,
        single_tick_default=0.10,
        exchange="CBOE",
        notes="Weekly SPX, same rules as SPX"
    ),

    # ES Futures Options (CME)
    # Single-leg: $0.05 below $10, $0.25 at/above $10
    # Combo: Need to verify CME rules - using $0.05 conservatively
    "ES": TickRule(
        combo_tick=0.05,
        single_tick_default=0.05,
        exchange="CME",
        notes="CME E-mini S&P 500 options - combo tick TBD"
    ),

    # VIX Options (CBOE)
    # Similar structure to SPX
    "VIX": TickRule(
        combo_tick=0.05,
        single_tick_default=0.05,
        exchange="CBOE",
        notes="CBOE VIX options"
    ),

    # NDX/QQQ Index Options
    "NDX": TickRule(
        combo_tick=0.05,
        single_tick_default=0.10,
        exchange="CBOE",
        notes="Nasdaq-100 Index options"
    ),

    # RUT (Russell 2000)
    "RUT": TickRule(
        combo_tick=0.05,
        single_tick_default=0.10,
        exchange="CBOE",
        notes="Russell 2000 Index options"
    ),
}

# Penny Pilot symbols - equity options that allow $0.01 tick for spreads
# Most liquid equity options are in the Penny Pilot program
PENNY_PILOT_SYMBOLS: set[str] = {
    "AAPL", "AMZN", "AMD", "GOOGL", "GOOG", "META", "MSFT", "NVDA",
    "TSLA", "SPY", "QQQ", "IWM", "DIA", "XLF", "GLD", "SLV",
    "NFLX", "BABA", "BA", "JPM", "BAC", "C", "WFC", "GS",
    "XOM", "CVX", "PFE", "JNJ", "UNH", "MRK", "ABBV",
    # Add more as needed...
}


def get_combo_tick(symbol: str) -> Optional[float]:
    """Get combo/spread tick size for a symbol.

    Args:
        symbol: The underlying symbol (e.g., 'SPX', 'TSLA')

    Returns:
        Tick size for combo orders, or None if not defined (use single-leg rules)
    """
    symbol = symbol.upper()

    # Check explicit combo rules first
    if symbol in COMBO_TICK_RULES:
        return COMBO_TICK_RULES[symbol].combo_tick

    # Penny Pilot symbols use $0.01 for spreads
    if symbol in PENNY_PILOT_SYMBOLS:
        return 0.01

    # Unknown symbol - return None to signal "use single-leg rules"
    return None


def get_tick_rule(symbol: str) -> Optional[TickRule]:
    """Get full tick rule for a symbol.

    Args:
        symbol: The underlying symbol

    Returns:
        TickRule if defined, None otherwise
    """
    return COMBO_TICK_RULES.get(symbol.upper())


def is_penny_pilot(symbol: str) -> bool:
    """Check if symbol is in Penny Pilot program."""
    return symbol.upper() in PENNY_PILOT_SYMBOLS
