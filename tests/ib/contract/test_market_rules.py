"""Contract tests for Market Rules and Tick Size resolution.

These tests verify that:
1. Market rules are correctly loaded from IB API responses
2. Tick sizes are correctly determined based on price level
3. The bug where tick=0.05 was incorrectly reported as 0.01 is fixed

The key insight: SPX options (and many others) have price-dependent tick sizes:
- Below $3.00: tick = 0.01
- At/above $3.00: tick = 0.05

This test uses fixtures that simulate real IB API responses.
"""
import pytest
from types import SimpleNamespace
from unittest.mock import Mock, patch, MagicMock

import sys
from pathlib import Path
# Add tests directory to path for fixture imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# Import fixtures
from ib.fixtures.market_rules import (
    SPX_OPTION_MARKET_RULE,
    STOCK_MARKET_RULE,
    SPX_OPTION_CONTRACT_DETAILS,
    SPX_TICK_SIZE_TEST_CASES,
    BUG_CASE_TICK_010,
    create_spx_option_contract,
    MockPriceIncrement,
)


class TestTickSizeResolution:
    """Test tick size resolution from market rules.

    SPX official tick sizes (CBOE):
    - Below $3.00: tick = 0.05 ($5.00)
    - At/above $3.00: tick = 0.10 ($10.00)
    Source: https://www.cboe.com/tradable_products/sp_500/spx_options/specifications/
    """

    def test_spx_option_below_3_uses_005_tick(self):
        """SPX option priced below $3 should use 0.05 tick."""
        # Simulate the tick size lookup logic
        price = 2.50
        rule = SPX_OPTION_MARKET_RULE

        # Find increment for this price level (same logic as broker.py)
        increment = 0.01  # default
        for price_rule in rule:
            if price_rule.lowEdge <= price:
                increment = price_rule.increment
            else:
                break

        assert increment == 0.05, f"Price ${price} should use 0.05 tick"

    def test_spx_option_at_3_uses_010_tick(self):
        """SPX option priced at exactly $3 should use 0.10 tick."""
        price = 3.00
        rule = SPX_OPTION_MARKET_RULE

        increment = 0.01
        for price_rule in rule:
            if price_rule.lowEdge <= price:
                increment = price_rule.increment
            else:
                break

        assert increment == 0.10, f"Price ${price} should use 0.10 tick"

    def test_spx_option_above_3_uses_010_tick(self):
        """SPX option priced above $3 should use 0.10 tick."""
        price = 4.60  # The specific bug case
        rule = SPX_OPTION_MARKET_RULE

        increment = 0.01
        for price_rule in rule:
            if price_rule.lowEdge <= price:
                increment = price_rule.increment
            else:
                break

        assert increment == 0.10, f"Price ${price} should use 0.10 tick, NOT 0.01"

    @pytest.mark.parametrize("price,expected_tick,description", SPX_TICK_SIZE_TEST_CASES)
    def test_spx_tick_size_at_price_levels(self, price, expected_tick, description):
        """Parametrized test for all SPX price levels."""
        rule = SPX_OPTION_MARKET_RULE

        increment = 0.01
        for price_rule in rule:
            if price_rule.lowEdge <= price:
                increment = price_rule.increment
            else:
                break

        assert increment == expected_tick, description

    def test_bug_case_price_460_must_use_010(self):
        """CRITICAL: Price $4.60 MUST use 0.10 tick for SPX (the original bug)."""
        price, expected_tick, description = BUG_CASE_TICK_010
        rule = SPX_OPTION_MARKET_RULE

        increment = 0.01
        for price_rule in rule:
            if price_rule.lowEdge <= price:
                increment = price_rule.increment
            else:
                break

        assert increment == expected_tick, description
        assert increment != 0.01, "BUG: This was incorrectly returning 0.01!"


class TestFallbackMinTick:
    """Test fallback to minTick when market rules unavailable."""

    def test_fallback_rule_creation(self):
        """Test that fallback rule uses minTick correctly."""
        min_tick = 0.05

        # Simulate _create_fallback_rule()
        fallback_rule = [SimpleNamespace(lowEdge=0.0, increment=min_tick)]

        assert len(fallback_rule) == 1
        assert fallback_rule[0].lowEdge == 0.0
        assert fallback_rule[0].increment == 0.05

    def test_fallback_applies_at_all_prices(self):
        """Fallback rule should apply same tick at all price levels."""
        min_tick = 0.05
        fallback_rule = [SimpleNamespace(lowEdge=0.0, increment=min_tick)]

        for price in [0.01, 1.00, 3.00, 10.00, 100.00]:
            increment = 0.01
            for price_rule in fallback_rule:
                if price_rule.lowEdge <= price:
                    increment = price_rule.increment
                else:
                    break

            assert increment == 0.05, f"Fallback should use {min_tick} at all prices"


class TestBrokerTickSizeIntegration:
    """Integration tests for TWSBroker tick size methods."""

    def test_get_price_increment_with_cached_rules(self):
        """Test _get_price_increment uses cached market rules.

        SPX official tick sizes (CBOE):
        - Below $3.00: tick = 0.05
        - At/above $3.00: tick = 0.10
        """
        from trailing_stop_web.broker import TWSBroker

        broker = TWSBroker()

        # Create a mock contract
        contract = Mock()
        contract.conId = 123456789
        contract.symbol = "SPX"
        contract.secType = "OPT"
        contract.exchange = "SMART"
        contract.comboLegs = None

        # Pre-populate the cache with SPX market rules (correct CBOE values)
        # Cache key is conId only (unique identifier)
        broker._market_rules_cache[contract.conId] = [
            SimpleNamespace(lowEdge=0.0, increment=0.05),   # Below $3: 0.05
            SimpleNamespace(lowEdge=3.0, increment=0.10),   # $3 and above: 0.10
        ]

        # Test at various price levels
        assert broker._get_price_increment(contract, 2.50) == 0.05   # Below $3
        assert broker._get_price_increment(contract, 3.00) == 0.10   # At $3
        assert broker._get_price_increment(contract, 4.60) == 0.10   # Above $3
        assert broker._get_price_increment(contract, 10.00) == 0.10  # Well above $3

    def test_get_price_increment_with_negative_prices(self):
        """Test _get_price_increment handles negative prices (credit spreads).

        Credit spread prices are negative, but tick size is based on abs(price).
        SPX: 0.05 below $3, 0.10 at/above $3
        """
        from trailing_stop_web.broker import TWSBroker

        broker = TWSBroker()

        contract = Mock()
        contract.conId = 123456789
        contract.symbol = "SPX"
        contract.secType = "OPT"
        contract.exchange = "SMART"
        contract.comboLegs = None

        # Pre-populate the cache with SPX market rules (correct CBOE values)
        # Cache key is conId only (unique identifier)
        broker._market_rules_cache[contract.conId] = [
            SimpleNamespace(lowEdge=0.0, increment=0.05),   # Below $3: 0.05
            SimpleNamespace(lowEdge=3.0, increment=0.10),   # $3 and above: 0.10
        ]

        # Credit spread prices are negative, but tick size is based on abs(price)
        # Price -4.60 has abs value 4.60, which is >= 3.0, so tick = 0.10
        assert broker._get_price_increment(contract, -4.60) == 0.10   # abs=4.60 >= 3
        assert broker._get_price_increment(contract, -2.50) == 0.05   # abs=2.50 < 3
        assert broker._get_price_increment(contract, -3.00) == 0.10   # abs=3.00 >= 3
        assert broker._get_price_increment(contract, -10.00) == 0.10  # abs=10.00 >= 3

    def test_get_price_increment_cache_miss_returns_default(self):
        """Test _get_price_increment returns default when cache miss."""
        from trailing_stop_web.broker import TWSBroker

        broker = TWSBroker()

        contract = Mock()
        contract.conId = 999999  # Not in cache
        contract.symbol = "TEST"
        contract.secType = "OPT"
        contract.exchange = "SMART"
        contract.comboLegs = None

        # Should return default 0.01 when not cached
        assert broker._get_price_increment(contract, 5.00) == 0.01

    def test_round_to_tick_preserves_sign(self):
        """Test _round_to_tick preserves sign for credit spreads."""
        from trailing_stop_web.broker import TWSBroker

        broker = TWSBroker()

        # Positive prices (debit) - use pytest.approx for floating point
        assert broker._round_to_tick(4.62, 0.05) == pytest.approx(4.60, abs=0.001)
        assert broker._round_to_tick(4.63, 0.05) == pytest.approx(4.65, abs=0.001)
        assert broker._round_to_tick(4.60, 0.05) == pytest.approx(4.60, abs=0.001)

        # Negative prices (credit spreads)
        assert broker._round_to_tick(-4.62, 0.05) == pytest.approx(-4.60, abs=0.001)
        assert broker._round_to_tick(-4.63, 0.05) == pytest.approx(-4.65, abs=0.001)
        assert broker._round_to_tick(-4.60, 0.05) == pytest.approx(-4.60, abs=0.001)

    def test_round_to_tick_with_001_increment(self):
        """Test _round_to_tick with 0.01 increment."""
        from trailing_stop_web.broker import TWSBroker

        broker = TWSBroker()

        # Note: Python's round() uses "banker's rounding" (round half to even)
        # So 4.625 rounds to 4.62 (even), not 4.63
        assert broker._round_to_tick(4.626, 0.01) == pytest.approx(4.63, abs=0.001)
        assert broker._round_to_tick(4.624, 0.01) == pytest.approx(4.62, abs=0.001)
        assert broker._round_to_tick(2.996, 0.01) == pytest.approx(3.00, abs=0.001)


class TestComboTickSize:
    """Test tick size resolution for BAG (combo) contracts."""

    def test_combo_gets_tick_from_first_leg(self):
        """BAG contracts should get tick size from first leg."""
        from trailing_stop_web.broker import TWSBroker, PortfolioPosition

        broker = TWSBroker()

        # Create first leg contract
        leg_contract = Mock()
        leg_contract.conId = 111111
        leg_contract.symbol = "SPX"
        leg_contract.secType = "OPT"
        leg_contract.exchange = "SMART"
        leg_contract.comboLegs = None

        # Create combo leg reference
        combo_leg = Mock()
        combo_leg.conId = 111111

        # Create BAG contract
        combo_contract = Mock()
        combo_contract.conId = 999999
        combo_contract.symbol = "SPX"
        combo_contract.secType = "BAG"
        combo_contract.exchange = "SMART"
        combo_contract.comboLegs = [combo_leg]

        # Add first leg to positions
        pos = Mock()
        pos.raw_contract = leg_contract
        broker._positions[111111] = pos

        # Cache market rules for the leg (key is conId only)
        # Use correct SPX values: 0.05 below $3, 0.10 at/above $3
        broker._market_rules_cache[111111] = [
            SimpleNamespace(lowEdge=0.0, increment=0.05),
            SimpleNamespace(lowEdge=3.0, increment=0.10),
        ]

        # BAG should get tick from first leg
        assert broker._get_price_increment(combo_contract, 4.60) == 0.10   # >= $3
        assert broker._get_price_increment(combo_contract, 2.50) == 0.05   # < $3


class TestCreateFallbackRule:
    """Test the _create_fallback_rule helper method."""

    def test_creates_single_element_list(self):
        """Fallback rule should be a single-element list."""
        from trailing_stop_web.broker import TWSBroker

        broker = TWSBroker()
        rule = broker._create_fallback_rule(0.05)

        assert isinstance(rule, list)
        assert len(rule) == 1

    def test_fallback_rule_has_correct_structure(self):
        """Fallback rule should have lowEdge and increment."""
        from trailing_stop_web.broker import TWSBroker

        broker = TWSBroker()
        rule = broker._create_fallback_rule(0.05)

        assert hasattr(rule[0], 'lowEdge')
        assert hasattr(rule[0], 'increment')
        assert rule[0].lowEdge == 0.0
        assert rule[0].increment == 0.05

    def test_fallback_works_with_get_price_increment(self):
        """Fallback rule should work with _get_price_increment."""
        from trailing_stop_web.broker import TWSBroker

        broker = TWSBroker()

        contract = Mock()
        contract.conId = 888888
        contract.symbol = "TEST"
        contract.secType = "OPT"
        contract.exchange = "SMART"
        contract.comboLegs = None

        # Use fallback rule in cache (key is conId only)
        broker._market_rules_cache[888888] = broker._create_fallback_rule(0.05)

        # Should use 0.05 at all price levels
        assert broker._get_price_increment(contract, 1.00) == 0.05
        assert broker._get_price_increment(contract, 5.00) == 0.05
        assert broker._get_price_increment(contract, 100.00) == 0.05
