"""Strategy classification for options groups.

Classifies a group of option legs into a named strategy (e.g., "Bull Put Spread", "Iron Condor").

Supported Strategies (26):
==========================
SINGLE LEG (4):
- Long Call, Short Call, Long Put, Short Put

VERTICAL SPREADS (4):
- Bull Call Spread, Bear Call Spread, Bull Put Spread, Bear Put Spread

STRADDLES/STRANGLES (4):
- Long Straddle, Short Straddle, Long Strangle, Short Strangle

BUTTERFLIES (4):
- Long Call Butterfly, Short Call Butterfly, Long Put Butterfly, Short Put Butterfly

IRON STRATEGIES (4):
- Short Iron Condor, Long Iron Condor, Short Iron Butterfly, Long Iron Butterfly

CALENDAR/DIAGONAL (4):
- Call Calendar Spread, Put Calendar Spread, Call Diagonal Spread, Put Diagonal Spread

RATIO SPREADS (4):
- Call Ratio Spread, Put Ratio Spread, Call Backspread, Put Backspread

FALLBACK (1):
- Custom
"""
from dataclasses import dataclass
from typing import Optional


@dataclass
class LegInfo:
    """Minimal leg info needed for classification."""
    strike: float
    right: str  # "C" or "P"
    quantity: int  # positive = long, negative = short
    expiry: str  # "20251209" format


def classify_strategy(legs: list[LegInfo]) -> str:
    """Classify a list of option legs into a strategy name.

    Args:
        legs: List of LegInfo objects representing the group's legs

    Returns:
        Strategy name string (e.g., "Bull Put Spread", "Custom")
    """
    if not legs:
        return "Empty"

    n = len(legs)

    # Sort legs by strike for consistent analysis
    sorted_legs = sorted(legs, key=lambda x: x.strike)

    # Check if all legs have same expiry
    expiries = set(leg.expiry for leg in legs)
    same_expiry = len(expiries) == 1

    # Get rights
    rights = set(leg.right for leg in legs)
    all_calls = rights == {"C"}
    all_puts = rights == {"P"}
    mixed_rights = len(rights) == 2  # Both C and P

    # === 1-LEG STRATEGIES ===
    if n == 1:
        return _classify_single_leg(legs[0])

    # === 2-LEG STRATEGIES ===
    if n == 2:
        return _classify_two_leg(sorted_legs, same_expiry, all_calls, all_puts, mixed_rights)

    # === 3-LEG STRATEGIES (Butterflies) ===
    if n == 3:
        return _classify_three_leg(sorted_legs, same_expiry, all_calls, all_puts)

    # === 4-LEG STRATEGIES ===
    if n == 4:
        return _classify_four_leg(sorted_legs, same_expiry, all_calls, all_puts, mixed_rights)

    return "Custom"


def _classify_single_leg(leg: LegInfo) -> str:
    """Classify single-leg strategies."""
    is_long = leg.quantity > 0
    is_call = leg.right == "C"

    if is_call:
        return "Long Call" if is_long else "Short Call"
    else:
        return "Long Put" if is_long else "Short Put"


def _classify_two_leg(
    legs: list[LegInfo],
    same_expiry: bool,
    all_calls: bool,
    all_puts: bool,
    mixed_rights: bool
) -> str:
    """Classify two-leg strategies."""
    low, high = legs[0], legs[1]
    same_strike = low.strike == high.strike

    # Get net quantities
    total_qty = sum(leg.quantity for leg in legs)

    # === DIFFERENT EXPIRY: Calendar/Diagonal ===
    if not same_expiry:
        if all_calls:
            return "Call Calendar Spread" if same_strike else "Call Diagonal Spread"
        elif all_puts:
            return "Put Calendar Spread" if same_strike else "Put Diagonal Spread"
        return "Custom"

    # === SAME EXPIRY, MIXED RIGHTS: Straddle/Strangle ===
    if mixed_rights:
        # Both long or both short?
        both_long = low.quantity > 0 and high.quantity > 0
        both_short = low.quantity < 0 and high.quantity < 0

        # Straddle/Strangle requires equal absolute quantities
        if abs(low.quantity) != abs(high.quantity):
            return "Custom"

        if same_strike:
            if both_long:
                return "Long Straddle"
            elif both_short:
                return "Short Straddle"
        else:
            if both_long:
                return "Long Strangle"
            elif both_short:
                return "Short Strangle"
        return "Custom"

    # === SAME EXPIRY, SAME RIGHT: Vertical/Ratio ===
    # Check for ratio spread (unequal absolute quantities)
    abs_qty_low = abs(low.quantity)
    abs_qty_high = abs(high.quantity)

    if abs_qty_low != abs_qty_high:
        # Ratio spread or backspread
        net_qty = low.quantity + high.quantity
        if all_calls:
            # Backspread: more long than short (positive net qty)
            return "Call Backspread" if net_qty > 0 else "Call Ratio Spread"
        else:
            return "Put Backspread" if net_qty > 0 else "Put Ratio Spread"

    # Equal quantities - vertical spread
    low_long = low.quantity > 0
    high_long = high.quantity > 0

    if all_calls:
        # Bull Call: long low strike, short high strike
        if low_long and not high_long:
            return "Bull Call Spread"
        # Bear Call: short low strike, long high strike
        elif not low_long and high_long:
            return "Bear Call Spread"

    elif all_puts:
        # Bull Put: short high strike, long low strike
        if low_long and not high_long:
            return "Bull Put Spread"
        # Bear Put: long high strike, short low strike
        elif not low_long and high_long:
            return "Bear Put Spread"

    return "Custom"


def _classify_three_leg(
    legs: list[LegInfo],
    same_expiry: bool,
    all_calls: bool,
    all_puts: bool
) -> str:
    """Classify three-leg strategies (butterflies)."""
    if not same_expiry:
        return "Custom"

    if not (all_calls or all_puts):
        return "Custom"

    low, mid, high = legs[0], legs[1], legs[2]

    # Butterfly structure: wings at low/high, body at mid
    # Long butterfly: +1 low, -2 mid, +1 high (net debit)
    # Short butterfly: -1 low, +2 mid, -1 high (net credit)

    # Check wing distances are equal
    low_to_mid = mid.strike - low.strike
    mid_to_high = high.strike - mid.strike
    if abs(low_to_mid - mid_to_high) > 0.01:  # Allow small float tolerance
        return "Custom"

    # Check quantities: wings should be equal, body double
    if abs(low.quantity) != abs(high.quantity):
        return "Custom"
    if abs(mid.quantity) != 2 * abs(low.quantity):
        return "Custom"

    # Determine long vs short butterfly
    # Long: wings are long (+), body is short (-)
    wings_long = low.quantity > 0 and high.quantity > 0
    body_short = mid.quantity < 0

    wings_short = low.quantity < 0 and high.quantity < 0
    body_long = mid.quantity > 0

    if wings_long and body_short:
        return "Long Call Butterfly" if all_calls else "Long Put Butterfly"
    elif wings_short and body_long:
        return "Short Call Butterfly" if all_calls else "Short Put Butterfly"

    return "Custom"


def _classify_four_leg(
    legs: list[LegInfo],
    same_expiry: bool,
    all_calls: bool,
    all_puts: bool,
    mixed_rights: bool
) -> str:
    """Classify four-leg strategies (iron condor, iron butterfly)."""
    if not same_expiry:
        return "Custom"

    # Iron strategies require mixed rights (calls and puts)
    if not mixed_rights:
        return "Custom"

    # Separate calls and puts
    calls = sorted([l for l in legs if l.right == "C"], key=lambda x: x.strike)
    puts = sorted([l for l in legs if l.right == "P"], key=lambda x: x.strike)

    if len(calls) != 2 or len(puts) != 2:
        return "Custom"

    # All legs should have same absolute quantity
    abs_qtys = [abs(l.quantity) for l in legs]
    if len(set(abs_qtys)) != 1:
        return "Custom"

    put_low, put_high = puts[0], puts[1]
    call_low, call_high = calls[0], calls[1]

    # === IRON CONDOR ===
    # Short Iron Condor (net credit):
    #   Bull Put Spread (short high P, long low P) + Bear Call Spread (short low C, long high C)
    #   Structure: +P_low, -P_high, -C_low, +C_high
    # Long Iron Condor (net debit):
    #   Bear Put Spread (long high P, short low P) + Bull Call Spread (long low C, short high C)
    #   Structure: -P_low, +P_high, +C_low, -C_high

    # === IRON BUTTERFLY ===
    # Short Iron Butterfly (net credit):
    #   Short straddle at middle + long wings
    #   Put and Call at same middle strike (short), wings outside (long)
    # Long Iron Butterfly (net debit):
    #   Long straddle at middle + short wings

    # Check if it's a butterfly (inner strikes are same)
    is_butterfly = put_high.strike == call_low.strike

    if is_butterfly:
        # Iron Butterfly
        # Short: short the middle (P_high and C_low), long the wings (P_low and C_high)
        middle_short = put_high.quantity < 0 and call_low.quantity < 0
        wings_long = put_low.quantity > 0 and call_high.quantity > 0

        middle_long = put_high.quantity > 0 and call_low.quantity > 0
        wings_short = put_low.quantity < 0 and call_high.quantity < 0

        if middle_short and wings_long:
            return "Short Iron Butterfly"
        elif middle_long and wings_short:
            return "Long Iron Butterfly"
    else:
        # Iron Condor (inner strikes different, put_high < call_low)
        if put_high.strike < call_low.strike:
            # Short Iron Condor: Bull Put + Bear Call
            # Bull Put: +P_low, -P_high | Bear Call: -C_low, +C_high
            bull_put = put_low.quantity > 0 and put_high.quantity < 0
            bear_call = call_low.quantity < 0 and call_high.quantity > 0

            # Long Iron Condor: Bear Put + Bull Call
            # Bear Put: -P_low, +P_high | Bull Call: +C_low, -C_high
            bear_put = put_low.quantity < 0 and put_high.quantity > 0
            bull_call = call_low.quantity > 0 and call_high.quantity < 0

            if bull_put and bear_call:
                return "Short Iron Condor"
            elif bear_put and bull_call:
                return "Long Iron Condor"

    return "Custom"


def classify_from_leg_data(legs: list[dict]) -> str:
    """Convenience function to classify from leg dictionaries.

    Args:
        legs: List of dicts with keys: strike, right, quantity, expiry

    Returns:
        Strategy name string
    """
    leg_infos = [
        LegInfo(
            strike=leg["strike"],
            right=leg["right"],
            quantity=leg["quantity"],
            expiry=leg["expiry"]
        )
        for leg in legs
    ]
    return classify_strategy(leg_infos)
