"""Unit tests for strategy classification.

Tests all 26+ option strategies:
- Single Leg (4): Long/Short Call/Put
- Vertical Spreads (4): Bull/Bear Call/Put Spreads
- Straddles/Strangles (4): Long/Short Straddle/Strangle
- Butterflies (4): Long/Short Call/Put Butterfly
- Iron Strategies (4): Long/Short Iron Condor/Butterfly
- Calendar/Diagonal (4): Call/Put Calendar/Diagonal
- Ratio Spreads (4): Call/Put Ratio Spread/Backspread
- Edge Cases: mixed expiry, unknown combos
"""
import pytest
from trailing_stop_web.strategy_classifier import (
    LegInfo,
    classify_strategy,
    classify_from_leg_data,
)


def leg(strike: float, right: str, quantity: int, expiry: str = "20251220") -> LegInfo:
    """Helper to create LegInfo."""
    return LegInfo(strike=strike, right=right, quantity=quantity, expiry=expiry)


# =============================================================================
# SINGLE LEG STRATEGIES (4)
# =============================================================================

class TestSingleLeg:
    """Test single-leg strategies."""

    def test_long_call(self):
        legs = [leg(100, "C", 1)]
        assert classify_strategy(legs) == "Long Call"

    def test_short_call(self):
        legs = [leg(100, "C", -1)]
        assert classify_strategy(legs) == "Short Call"

    def test_long_put(self):
        legs = [leg(100, "P", 1)]
        assert classify_strategy(legs) == "Long Put"

    def test_short_put(self):
        legs = [leg(100, "P", -1)]
        assert classify_strategy(legs) == "Short Put"

    def test_long_call_multiple_qty(self):
        """Multiple quantity should still be classified correctly."""
        legs = [leg(100, "C", 5)]
        assert classify_strategy(legs) == "Long Call"


# =============================================================================
# VERTICAL SPREADS (4)
# =============================================================================

class TestVerticalSpreads:
    """Test vertical spread strategies (same expiry, same right, different strikes)."""

    def test_bull_call_spread(self):
        """Long lower strike call, short higher strike call."""
        legs = [leg(100, "C", 1), leg(105, "C", -1)]
        assert classify_strategy(legs) == "Bull Call Spread"

    def test_bear_call_spread(self):
        """Short lower strike call, long higher strike call."""
        legs = [leg(100, "C", -1), leg(105, "C", 1)]
        assert classify_strategy(legs) == "Bear Call Spread"

    def test_bull_put_spread(self):
        """Long lower strike put, short higher strike put."""
        legs = [leg(95, "P", 1), leg(100, "P", -1)]
        assert classify_strategy(legs) == "Bull Put Spread"

    def test_bear_put_spread(self):
        """Short lower strike put, long higher strike put."""
        legs = [leg(95, "P", -1), leg(100, "P", 1)]
        assert classify_strategy(legs) == "Bear Put Spread"

    def test_bull_call_spread_reversed_order(self):
        """Order of legs shouldn't matter."""
        legs = [leg(105, "C", -1), leg(100, "C", 1)]
        assert classify_strategy(legs) == "Bull Call Spread"

    def test_vertical_spread_multiple_qty(self):
        """Multiple quantity spreads."""
        legs = [leg(100, "C", 2), leg(105, "C", -2)]
        assert classify_strategy(legs) == "Bull Call Spread"


# =============================================================================
# STRADDLES AND STRANGLES (4)
# =============================================================================

class TestStraddlesStrangles:
    """Test straddle and strangle strategies (same expiry, C+P)."""

    def test_long_straddle(self):
        """Long call + long put at same strike."""
        legs = [leg(100, "C", 1), leg(100, "P", 1)]
        assert classify_strategy(legs) == "Long Straddle"

    def test_short_straddle(self):
        """Short call + short put at same strike."""
        legs = [leg(100, "C", -1), leg(100, "P", -1)]
        assert classify_strategy(legs) == "Short Straddle"

    def test_long_strangle(self):
        """Long call + long put at different strikes."""
        legs = [leg(105, "C", 1), leg(95, "P", 1)]
        assert classify_strategy(legs) == "Long Strangle"

    def test_short_strangle(self):
        """Short call + short put at different strikes."""
        legs = [leg(105, "C", -1), leg(95, "P", -1)]
        assert classify_strategy(legs) == "Short Strangle"

    def test_straddle_order_independent(self):
        """Order of legs shouldn't matter."""
        legs = [leg(100, "P", 1), leg(100, "C", 1)]
        assert classify_strategy(legs) == "Long Straddle"


# =============================================================================
# BUTTERFLIES (4) - 3 legs
# =============================================================================

class TestButterflies:
    """Test butterfly strategies (3 legs, same expiry, same right)."""

    def test_long_call_butterfly(self):
        """Long low + 2x short mid + long high call."""
        legs = [leg(95, "C", 1), leg(100, "C", -2), leg(105, "C", 1)]
        assert classify_strategy(legs) == "Long Call Butterfly"

    def test_short_call_butterfly(self):
        """Short low + 2x long mid + short high call."""
        legs = [leg(95, "C", -1), leg(100, "C", 2), leg(105, "C", -1)]
        assert classify_strategy(legs) == "Short Call Butterfly"

    def test_long_put_butterfly(self):
        """Long low + 2x short mid + long high put."""
        legs = [leg(95, "P", 1), leg(100, "P", -2), leg(105, "P", 1)]
        assert classify_strategy(legs) == "Long Put Butterfly"

    def test_short_put_butterfly(self):
        """Short low + 2x long mid + short high put."""
        legs = [leg(95, "P", -1), leg(100, "P", 2), leg(105, "P", -1)]
        assert classify_strategy(legs) == "Short Put Butterfly"

    def test_butterfly_unequal_wings_is_custom(self):
        """Unequal wing distances should be Custom."""
        legs = [leg(95, "C", 1), leg(100, "C", -2), leg(110, "C", 1)]  # 5 vs 10 gap
        assert classify_strategy(legs) == "Custom"

    def test_butterfly_wrong_body_qty_is_custom(self):
        """Body quantity not 2x wings should be Custom."""
        legs = [leg(95, "C", 1), leg(100, "C", -1), leg(105, "C", 1)]  # body is 1x not 2x
        assert classify_strategy(legs) == "Custom"


# =============================================================================
# IRON CONDORS (4 legs)
# =============================================================================

class TestIronCondors:
    """Test iron condor strategies (4 legs, same expiry, C+P)."""

    def test_short_iron_condor(self):
        """Bull put spread + bear call spread = net credit."""
        # Bull Put: +P_low, -P_high | Bear Call: -C_low, +C_high
        legs = [
            leg(90, "P", 1),   # long put (wing)
            leg(95, "P", -1),  # short put
            leg(105, "C", -1), # short call
            leg(110, "C", 1),  # long call (wing)
        ]
        assert classify_strategy(legs) == "Short Iron Condor"

    def test_long_iron_condor(self):
        """Bear put spread + bull call spread = net debit."""
        # Bear Put: -P_low, +P_high | Bull Call: +C_low, -C_high
        legs = [
            leg(90, "P", -1),  # short put (wing)
            leg(95, "P", 1),   # long put
            leg(105, "C", 1),  # long call
            leg(110, "C", -1), # short call (wing)
        ]
        assert classify_strategy(legs) == "Long Iron Condor"

    def test_iron_condor_order_independent(self):
        """Order of legs shouldn't matter."""
        legs = [
            leg(110, "C", 1),
            leg(90, "P", 1),
            leg(105, "C", -1),
            leg(95, "P", -1),
        ]
        assert classify_strategy(legs) == "Short Iron Condor"


# =============================================================================
# IRON BUTTERFLIES (4 legs)
# =============================================================================

class TestIronButterflies:
    """Test iron butterfly strategies (4 legs, same expiry, C+P, inner strikes equal)."""

    def test_short_iron_butterfly(self):
        """Short straddle at middle + long strangle wings = net credit."""
        # Middle: -C, -P at same strike | Wings: +P lower, +C higher
        legs = [
            leg(95, "P", 1),    # long put wing
            leg(100, "P", -1),  # short put (middle)
            leg(100, "C", -1),  # short call (middle)
            leg(105, "C", 1),   # long call wing
        ]
        assert classify_strategy(legs) == "Short Iron Butterfly"

    def test_long_iron_butterfly(self):
        """Long straddle at middle + short strangle wings = net debit."""
        # Middle: +C, +P at same strike | Wings: -P lower, -C higher
        legs = [
            leg(95, "P", -1),   # short put wing
            leg(100, "P", 1),   # long put (middle)
            leg(100, "C", 1),   # long call (middle)
            leg(105, "C", -1),  # short call wing
        ]
        assert classify_strategy(legs) == "Long Iron Butterfly"


# =============================================================================
# CALENDAR AND DIAGONAL SPREADS (4)
# =============================================================================

class TestCalendarDiagonalSpreads:
    """Test calendar and diagonal spreads (different expiry)."""

    def test_call_calendar_spread(self):
        """Same strike calls, different expiry."""
        legs = [
            leg(100, "C", 1, "20251220"),
            leg(100, "C", -1, "20251227"),
        ]
        assert classify_strategy(legs) == "Call Calendar Spread"

    def test_put_calendar_spread(self):
        """Same strike puts, different expiry."""
        legs = [
            leg(100, "P", 1, "20251220"),
            leg(100, "P", -1, "20251227"),
        ]
        assert classify_strategy(legs) == "Put Calendar Spread"

    def test_call_diagonal_spread(self):
        """Different strike calls, different expiry."""
        legs = [
            leg(100, "C", 1, "20251220"),
            leg(105, "C", -1, "20251227"),
        ]
        assert classify_strategy(legs) == "Call Diagonal Spread"

    def test_put_diagonal_spread(self):
        """Different strike puts, different expiry."""
        legs = [
            leg(100, "P", 1, "20251220"),
            leg(95, "P", -1, "20251227"),
        ]
        assert classify_strategy(legs) == "Put Diagonal Spread"


# =============================================================================
# RATIO SPREADS AND BACKSPREADS (4)
# =============================================================================

class TestRatioSpreads:
    """Test ratio spreads (unequal quantities)."""

    def test_call_ratio_spread(self):
        """More short than long calls (net short)."""
        legs = [leg(100, "C", 1), leg(105, "C", -2)]
        assert classify_strategy(legs) == "Call Ratio Spread"

    def test_put_ratio_spread(self):
        """More short than long puts (net short)."""
        legs = [leg(100, "P", 1), leg(95, "P", -2)]
        assert classify_strategy(legs) == "Put Ratio Spread"

    def test_call_backspread(self):
        """More long than short calls (net long)."""
        legs = [leg(100, "C", -1), leg(105, "C", 2)]
        assert classify_strategy(legs) == "Call Backspread"

    def test_put_backspread(self):
        """More long than short puts (net long)."""
        legs = [leg(100, "P", -1), leg(95, "P", 2)]
        assert classify_strategy(legs) == "Put Backspread"


# =============================================================================
# EDGE CASES
# =============================================================================

class TestEdgeCases:
    """Test edge cases and fallbacks."""

    def test_empty_legs(self):
        """Empty list should return Empty."""
        assert classify_strategy([]) == "Empty"

    def test_mixed_rights_different_expiry_is_custom(self):
        """Mixed rights with different expiry = Custom."""
        legs = [
            leg(100, "C", 1, "20251220"),
            leg(100, "P", -1, "20251227"),
        ]
        assert classify_strategy(legs) == "Custom"

    def test_five_legs_is_custom(self):
        """5+ legs = Custom."""
        legs = [
            leg(90, "P", 1),
            leg(95, "P", -1),
            leg(100, "C", -1),
            leg(105, "C", 1),
            leg(110, "C", 1),  # extra leg
        ]
        assert classify_strategy(legs) == "Custom"

    def test_unbalanced_straddle_is_custom(self):
        """Unequal qty straddle = Custom."""
        legs = [leg(100, "C", 1), leg(100, "P", 2)]
        assert classify_strategy(legs) == "Custom"

    def test_classify_from_leg_data_dict(self):
        """Test the dict-based convenience function."""
        leg_data = [
            {"strike": 100.0, "right": "C", "quantity": 1, "expiry": "20251220"},
            {"strike": 105.0, "right": "C", "quantity": -1, "expiry": "20251220"},
        ]
        assert classify_from_leg_data(leg_data) == "Bull Call Spread"

    def test_classify_from_leg_data_empty(self):
        """Empty leg_data list."""
        assert classify_from_leg_data([]) == "Empty"


# =============================================================================
# INTEGRATION: Real-world examples
# =============================================================================

class TestRealWorldExamples:
    """Test with realistic SPX options examples."""

    def test_spx_bull_put_spread(self):
        """SPX Bull Put Spread: Sell 6050P, Buy 6000P."""
        legs = [
            leg(6000, "P", 1),   # long put (protection)
            leg(6050, "P", -1),  # short put (premium)
        ]
        assert classify_strategy(legs) == "Bull Put Spread"

    def test_spx_short_iron_condor(self):
        """SPX Iron Condor: Bull Put + Bear Call."""
        legs = [
            leg(5900, "P", 1),   # long put wing
            leg(5950, "P", -1),  # short put
            leg(6100, "C", -1),  # short call
            leg(6150, "C", 1),   # long call wing
        ]
        assert classify_strategy(legs) == "Short Iron Condor"

    def test_spx_short_straddle(self):
        """SPX Short Straddle at 6000."""
        legs = [
            leg(6000, "C", -1),
            leg(6000, "P", -1),
        ]
        assert classify_strategy(legs) == "Short Straddle"

    def test_multi_unit_spread(self):
        """3-unit Bull Put Spread."""
        legs = [
            leg(6000, "P", 3),   # 3 long puts
            leg(6050, "P", -3),  # 3 short puts
        ]
        assert classify_strategy(legs) == "Bull Put Spread"
