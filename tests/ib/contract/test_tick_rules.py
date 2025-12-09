"""Tests for combo tick size lookup table.

The tick_rules module provides centralized combo/spread tick sizes that
cannot be queried from IB API (IB returns Error 321 for BAG contract details).
"""
import pytest
from trailing_stop_web.tick_rules import (
    get_combo_tick,
    get_tick_rule,
    is_penny_pilot,
    COMBO_TICK_RULES,
    PENNY_PILOT_SYMBOLS,
)


class TestGetComboTick:
    """Test the get_combo_tick function."""

    def test_spx_returns_005(self):
        """SPX combos should use 0.05 tick (CBOE rule)."""
        assert get_combo_tick("SPX") == 0.05

    def test_spxw_returns_005(self):
        """SPXW (weekly) combos should use 0.05 tick."""
        assert get_combo_tick("SPXW") == 0.05

    def test_vix_returns_005(self):
        """VIX combos should use 0.05 tick."""
        assert get_combo_tick("VIX") == 0.05

    def test_ndx_returns_005(self):
        """NDX combos should use 0.05 tick."""
        assert get_combo_tick("NDX") == 0.05

    def test_rut_returns_005(self):
        """RUT combos should use 0.05 tick."""
        assert get_combo_tick("RUT") == 0.05

    def test_es_returns_005(self):
        """ES (E-mini S&P) combos should use 0.05 tick."""
        assert get_combo_tick("ES") == 0.05

    def test_case_insensitive(self):
        """Symbol lookup should be case-insensitive."""
        assert get_combo_tick("spx") == 0.05
        assert get_combo_tick("Spx") == 0.05
        assert get_combo_tick("tsla") == 0.01


class TestPennyPilotSymbols:
    """Test Penny Pilot program symbols."""

    def test_tsla_is_penny_pilot(self):
        """TSLA should be in Penny Pilot program."""
        assert is_penny_pilot("TSLA")
        assert get_combo_tick("TSLA") == 0.01

    def test_aapl_is_penny_pilot(self):
        """AAPL should be in Penny Pilot program."""
        assert is_penny_pilot("AAPL")
        assert get_combo_tick("AAPL") == 0.01

    def test_spy_is_penny_pilot(self):
        """SPY should be in Penny Pilot program."""
        assert is_penny_pilot("SPY")
        assert get_combo_tick("SPY") == 0.01

    def test_qqq_is_penny_pilot(self):
        """QQQ should be in Penny Pilot program."""
        assert is_penny_pilot("QQQ")
        assert get_combo_tick("QQQ") == 0.01

    def test_nvda_is_penny_pilot(self):
        """NVDA should be in Penny Pilot program."""
        assert is_penny_pilot("NVDA")
        assert get_combo_tick("NVDA") == 0.01

    def test_penny_pilot_case_insensitive(self):
        """Penny Pilot check should be case-insensitive."""
        assert is_penny_pilot("tsla")
        assert is_penny_pilot("Aapl")


class TestUnknownSymbols:
    """Test behavior for unknown symbols."""

    def test_unknown_symbol_returns_none(self):
        """Unknown symbols should return None."""
        assert get_combo_tick("UNKNOWN_SYMBOL") is None

    def test_unknown_is_not_penny_pilot(self):
        """Unknown symbols should not be Penny Pilot."""
        assert not is_penny_pilot("UNKNOWN_SYMBOL")

    def test_known_non_penny_pilot(self):
        """SPX should not be in Penny Pilot (has explicit combo rule)."""
        assert not is_penny_pilot("SPX")


class TestGetTickRule:
    """Test the get_tick_rule function."""

    def test_spx_tick_rule(self):
        """SPX should have a full TickRule with exchange info."""
        rule = get_tick_rule("SPX")
        assert rule is not None
        assert rule.combo_tick == 0.05
        assert rule.single_tick_default == 0.10
        assert rule.exchange == "CBOE"
        assert "Complex orders" in rule.notes or "complex" in rule.notes.lower()

    def test_es_tick_rule(self):
        """ES should have CME exchange."""
        rule = get_tick_rule("ES")
        assert rule is not None
        assert rule.exchange == "CME"

    def test_penny_pilot_no_tick_rule(self):
        """Penny Pilot symbols should not have explicit TickRule."""
        rule = get_tick_rule("TSLA")
        assert rule is None  # TSLA is only in PENNY_PILOT_SYMBOLS


class TestDataIntegrity:
    """Test the integrity of the lookup tables."""

    def test_combo_tick_rules_not_empty(self):
        """COMBO_TICK_RULES should have entries."""
        assert len(COMBO_TICK_RULES) >= 5

    def test_penny_pilot_not_empty(self):
        """PENNY_PILOT_SYMBOLS should have entries."""
        assert len(PENNY_PILOT_SYMBOLS) >= 10

    def test_no_overlap_between_rules_and_penny_pilot(self):
        """Symbols should not be in both COMBO_TICK_RULES and PENNY_PILOT."""
        overlap = set(COMBO_TICK_RULES.keys()) & PENNY_PILOT_SYMBOLS
        assert len(overlap) == 0, f"Overlapping symbols: {overlap}"

    def test_all_combo_ticks_are_positive(self):
        """All combo tick values should be positive."""
        for symbol, rule in COMBO_TICK_RULES.items():
            assert rule.combo_tick > 0, f"{symbol} has invalid combo_tick"
            assert rule.single_tick_default > 0, f"{symbol} has invalid single_tick_default"
