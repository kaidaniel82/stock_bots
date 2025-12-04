"""Unit tests for group metrics calculations.

Tests all position variants:
- Single Long
- Single Short
- Debit Spread (Long + Short, net debit)
- Credit Spread (Long + Short, net credit)
- Ratio spread (unequal quantities)
"""
import pytest
from trailing_stop_web.metrics import compute_group_metrics, LegData, GroupMetrics


def make_leg(
    con_id: int = 1,
    symbol: str = "SPX",
    sec_type: str = "OPT",
    expiry: str = "20251209",
    strike: float = 6800.0,
    right: str = "C",
    quantity: float = 1,
    multiplier: int = 100,
    fill_price: float = 10.0,
    bid: float = 9.90,
    ask: float = 10.10,
    mid: float = 10.0,
    mark: float = 10.0,
    delta: float = 0.5,
    gamma: float = 0.01,
    theta: float = -5.0,
    vega: float = 10.0,
) -> LegData:
    """Helper to create LegData with defaults."""
    return LegData(
        con_id=con_id,
        symbol=symbol,
        sec_type=sec_type,
        expiry=expiry,
        strike=strike,
        right=right,
        quantity=quantity,
        multiplier=multiplier,
        fill_price=fill_price,
        bid=bid,
        ask=ask,
        mid=mid,
        mark=mark,
        delta=delta,
        gamma=gamma,
        theta=theta,
        vega=vega,
    )


class TestSingleLong:
    """Tests for single long positions."""

    def test_single_long_position_type(self):
        """Single long should be classified as LONG."""
        leg = make_leg(quantity=5)
        metrics = compute_group_metrics([leg], "mark")
        assert metrics.position_type == "LONG"
        assert not metrics.is_credit

    def test_single_long_prices_are_actual_instrument_prices(self):
        """Single long should show actual instrument bid/ask, not spread-calculated."""
        leg = make_leg(
            quantity=5,
            bid=16.40,
            ask=16.60,
            mid=16.50,
            mark=16.55,
            fill_price=16.60,
        )
        metrics = compute_group_metrics([leg], "mark")

        assert metrics.bid == 16.40, "Bid should be actual leg bid"
        assert metrics.ask == 16.60, "Ask should be actual leg ask"
        assert metrics.mid == 16.50, "Mid should be actual leg mid"
        assert metrics.mark == 16.55, "Mark should be actual leg mark"
        assert metrics.entry == 16.60, "Entry should be fill price"

    def test_single_long_pnl_calculation(self):
        """Single long P&L: current value (at mark) - entry cost."""
        # Long +5 @ $16.60, now mark=$16.50
        # Entry: paid $16.60 * 5 * 100 = $8300
        # Current: mark $16.50 * 5 * 100 = $8250
        # P&L: $8250 - $8300 = -$50
        leg = make_leg(
            quantity=5,
            multiplier=100,
            fill_price=16.60,
            bid=16.40,
            ask=16.60,
            mid=16.50,
            mark=16.50,
        )
        metrics = compute_group_metrics([leg], "mark")

        assert metrics.total_entry_cost == 8300.0, "Entry cost should be 16.60 * 5 * 100"
        assert metrics.total_current_value == 8250.0, "Current value should be mark * 5 * 100"
        assert metrics.pnl == -50.0, "P&L should be -$50"

    def test_single_long_greeks(self):
        """Greeks should be position-weighted (greek * qty * mult)."""
        leg = make_leg(
            quantity=5,
            multiplier=100,
            delta=0.5,
            gamma=0.01,
            theta=-5.0,
            vega=10.0,
        )
        metrics = compute_group_metrics([leg], "mark")

        # 5 contracts * 100 multiplier * greek
        assert metrics.delta == 250.0  # 0.5 * 5 * 100
        assert metrics.gamma == 5.0     # 0.01 * 5 * 100
        assert metrics.theta == -2500.0 # -5 * 5 * 100
        assert metrics.vega == 5000.0   # 10 * 5 * 100


class TestSingleShort:
    """Tests for single short positions."""

    def test_single_short_position_type(self):
        """Single short should be classified as SHORT with credit."""
        leg = make_leg(quantity=-3)
        metrics = compute_group_metrics([leg], "mark")
        assert metrics.position_type == "SHORT"
        assert metrics.is_credit  # Received premium

    def test_single_short_prices_are_actual_instrument_prices(self):
        """Single short should show actual instrument bid/ask."""
        leg = make_leg(
            quantity=-3,
            bid=41.10,
            ask=41.40,
            mid=41.25,
            mark=41.40,
            fill_price=42.00,
        )
        metrics = compute_group_metrics([leg], "mark")

        assert metrics.bid == 41.10, "Bid should be actual leg bid"
        assert metrics.ask == 41.40, "Ask should be actual leg ask"
        assert metrics.mid == 41.25, "Mid should be actual leg mid"
        assert metrics.mark == 41.40, "Mark should be actual leg mark"
        assert metrics.entry == 42.00, "Entry should be fill price"

    def test_single_short_pnl_calculation(self):
        """Single short P&L: credit received - current value at mark."""
        # Short -3 @ $42, now mark=$41.40
        # Entry: received $42 * 3 * 100 = $12,600 (credit, so negative cost)
        # Current: mark $41.40 * 3 * 100 = $12,420 (negative for short)
        # P&L: -12420 - (-12600) = +$180
        leg = make_leg(
            quantity=-3,
            multiplier=100,
            fill_price=42.00,
            bid=41.10,
            ask=41.40,
            mid=41.25,
            mark=41.40,
        )
        metrics = compute_group_metrics([leg], "mark")

        assert metrics.total_entry_cost == -12600.0, "Entry cost should be negative (credit)"
        assert metrics.total_current_value == -12420.0, "Current value should be negative (mark)"
        assert metrics.pnl == 180.0, "P&L should be +$180 profit"

    def test_single_short_greeks_are_negative(self):
        """Short position Greeks should be negative (sold delta)."""
        leg = make_leg(
            quantity=-3,
            multiplier=100,
            delta=0.5,
            gamma=0.01,
            theta=-5.0,
            vega=10.0,
        )
        metrics = compute_group_metrics([leg], "mark")

        # -3 contracts * 100 multiplier * greek
        assert metrics.delta == -150.0   # 0.5 * -3 * 100
        assert metrics.gamma == -3.0     # 0.01 * -3 * 100
        assert metrics.theta == 1500.0   # -5 * -3 * 100 (positive theta for short)
        assert metrics.vega == -3000.0   # 10 * -3 * 100


class TestDebitSpread:
    """Tests for debit spreads (pay to enter, receive to close)."""

    def test_debit_spread_position_type(self):
        """Debit spread should be classified as SPREAD, not credit."""
        # Buy 6800C @ $16.60, Sell 6850C @ $12.00 = $4.60 debit
        long_leg = make_leg(con_id=1, strike=6800, quantity=5, fill_price=16.60)
        short_leg = make_leg(con_id=2, strike=6850, quantity=-5, fill_price=12.00)
        metrics = compute_group_metrics([long_leg, short_leg], "mark")

        assert metrics.position_type == "SPREAD"
        assert not metrics.is_credit  # Paid debit

    def test_debit_spread_prices(self):
        """Spread prices should be long - short."""
        # Long: bid=16.40, ask=16.60
        # Short: bid=11.90, ask=12.10
        long_leg = make_leg(
            con_id=1, strike=6800, quantity=5,
            bid=16.40, ask=16.60, mid=16.50, mark=16.50, fill_price=16.60
        )
        short_leg = make_leg(
            con_id=2, strike=6850, quantity=-5,
            bid=11.90, ask=12.10, mid=12.00, mark=12.00, fill_price=12.00
        )
        metrics = compute_group_metrics([long_leg, short_leg], "mark")

        # Spread bid = long bid - short ask = 16.40 - 12.10 = 4.30
        assert metrics.bid == 4.30, "Spread bid = long bid - short ask"
        # Spread ask = long ask - short bid = 16.60 - 11.90 = 4.70
        assert metrics.ask == 4.70, "Spread ask = long ask - short bid"
        # Spread mark = 16.50 - 12.00 = 4.50
        assert metrics.mark == 4.50, "Spread mark = long mark - short mark"
        # Entry = 16.60 - 12.00 = 4.60
        assert metrics.entry == 4.60, "Spread entry = long fill - short fill"

    def test_debit_spread_pnl_calculation(self):
        """Debit spread P&L calculation using mark."""
        # +5 6800C @ $16.60, -5 6850C @ $12.00
        # Entry: (16.60 * 5 * 100) - (12.00 * 5 * 100) = 8300 - 6000 = $2300 debit
        # Current at mark: (16.50 * 5 * 100) - (12.00 * 5 * 100) = 8250 - 6000 = $2250
        # P&L: 2250 - 2300 = -$50
        long_leg = make_leg(
            con_id=1, strike=6800, quantity=5, multiplier=100,
            bid=16.40, ask=16.60, mid=16.50, mark=16.50, fill_price=16.60
        )
        short_leg = make_leg(
            con_id=2, strike=6850, quantity=-5, multiplier=100,
            bid=11.90, ask=12.10, mid=12.00, mark=12.00, fill_price=12.00
        )
        metrics = compute_group_metrics([long_leg, short_leg], "mark")

        assert metrics.total_entry_cost == 2300.0, "Entry = long cost - short credit"
        assert metrics.total_current_value == 2250.0, "Current = long mark - short mark"
        assert metrics.pnl == -50.0, "P&L = current - entry"


class TestCreditSpread:
    """Tests for credit spreads (receive to enter, pay to close)."""

    def test_credit_spread_position_type(self):
        """Credit spread should be classified as SPREAD with credit."""
        # Sell 6800C @ $16.60, Buy 6850C @ $12.00 = $4.60 credit
        short_leg = make_leg(con_id=1, strike=6800, quantity=-5, fill_price=16.60)
        long_leg = make_leg(con_id=2, strike=6850, quantity=5, fill_price=12.00)
        metrics = compute_group_metrics([short_leg, long_leg], "mark")

        assert metrics.position_type == "SPREAD"
        assert metrics.is_credit  # Received credit

    def test_credit_spread_pnl_calculation(self):
        """Credit spread P&L calculation using mark."""
        # -5 6800C @ $16.60, +5 6850C @ $12.00
        # Entry: (12.00 * 5 * 100) - (16.60 * 5 * 100) = 6000 - 8300 = -$2300 (credit)
        # Current at mark: (12.20 * 5 * 100) - (16.50 * 5 * 100) = 6100 - 8250 = -$2150
        # P&L = -2150 - (-2300) = +$150
        short_leg = make_leg(
            con_id=1, strike=6800, quantity=-5, multiplier=100,
            bid=16.40, ask=16.60, mid=16.50, mark=16.50, fill_price=16.60
        )
        long_leg = make_leg(
            con_id=2, strike=6850, quantity=5, multiplier=100,
            bid=12.00, ask=12.40, mid=12.20, mark=12.20, fill_price=12.00
        )
        metrics = compute_group_metrics([short_leg, long_leg], "mark")

        # Entry: long paid 12.00, short received 16.60 = 6000 - 8300 = -2300 (net credit)
        assert metrics.total_entry_cost == -2300.0, "Entry should be negative (credit)"
        # Current at mark: long 12.20 * 500 = 6100, short 16.50 * 500 = 8250 => 6100 - 8250 = -2150
        assert metrics.total_current_value == -2150.0, "Current = long mark - short mark"
        # P&L = -2150 - (-2300) = 150
        assert metrics.pnl == 150.0, "P&L = credit position improved"


class TestRatioSpread:
    """Tests for ratio spreads (unequal quantities)."""

    def test_ratio_spread_position_type(self):
        """Ratio spread should be classified as RATIO."""
        # +2 6800C, -1 6850C (unequal)
        long_leg = make_leg(con_id=1, strike=6800, quantity=2)
        short_leg = make_leg(con_id=2, strike=6850, quantity=-1)
        metrics = compute_group_metrics([long_leg, short_leg], "mark")

        assert metrics.position_type == "RATIO"

    def test_ratio_per_unit_prices(self):
        """Ratio per-unit prices should be weighted by unit quantities."""
        # +2 6810C @ mark=$44.50, -1 6835C @ mark=$52.70
        # GCD(2,1) = 1, so 1 unit = +2/-1
        # Per-unit mark = (44.50 * 2) - (52.70 * 1) = 89.00 - 52.70 = 36.30
        long_leg = make_leg(
            con_id=1, strike=6810, quantity=2, multiplier=100,
            bid=44.30, ask=44.80, mid=44.55, mark=44.50, fill_price=44.00
        )
        short_leg = make_leg(
            con_id=2, strike=6835, quantity=-1, multiplier=100,
            bid=52.50, ask=52.90, mid=52.70, mark=52.70, fill_price=53.00
        )
        metrics = compute_group_metrics([long_leg, short_leg], "mark")

        # Per-unit prices (1 unit = +2 long, -1 short)
        assert metrics.mark == 36.30, "Mark = (44.50*2) - (52.70*1) = 36.30"
        assert metrics.mid == 36.40, "Mid = (44.55*2) - (52.70*1) = 36.40"
        # Bid = sell longs @ bid, buy short @ ask = (44.30*2) - (52.90*1) = 35.70
        assert metrics.bid == 35.70, "Bid = (44.30*2) - (52.90*1) = 35.70"
        # Ask = buy longs @ ask, sell short @ bid = (44.80*2) - (52.50*1) = 37.10
        assert metrics.ask == 37.10, "Ask = (44.80*2) - (52.50*1) = 37.10"
        # Entry = (44.00*2) - (53.00*1) = 35.00
        assert metrics.entry == 35.00, "Entry = (44.00*2) - (53.00*1) = 35.00"

    def test_ratio_with_gcd_greater_than_1(self):
        """Ratio with GCD > 1 should normalize to smallest unit."""
        # +6 6810C, -2 6835C => GCD(6,2) = 2 => 1 unit = +3/-1
        # Per-unit mark = (44.50 * 3) - (52.70 * 1) = 133.50 - 52.70 = 80.80
        long_leg = make_leg(
            con_id=1, strike=6810, quantity=6, multiplier=100,
            mark=44.50, fill_price=44.00
        )
        short_leg = make_leg(
            con_id=2, strike=6835, quantity=-2, multiplier=100,
            mark=52.70, fill_price=53.00
        )
        metrics = compute_group_metrics([long_leg, short_leg], "mark")

        # Per-unit = +3/-1 after GCD normalization
        assert metrics.mark == 80.80, "Mark = (44.50*3) - (52.70*1) = 80.80"


class TestTriggerValue:
    """Tests for trigger value calculation."""

    def test_trigger_value_mark(self):
        """Trigger value should be mark when trigger_price_type='mark'."""
        leg = make_leg(bid=10.0, ask=10.20, mid=10.10, mark=10.15)
        metrics = compute_group_metrics([leg], "mark")
        assert metrics.trigger_value == 10.15

    def test_trigger_value_mid(self):
        """Trigger value should be mid when trigger_price_type='mid'."""
        leg = make_leg(bid=10.0, ask=10.20, mid=10.10, mark=10.15)
        metrics = compute_group_metrics([leg], "mid")
        assert metrics.trigger_value == 10.10

    def test_trigger_value_bid(self):
        """Trigger value should be bid when trigger_price_type='bid'."""
        leg = make_leg(bid=10.0, ask=10.20, mid=10.10, mark=10.15)
        metrics = compute_group_metrics([leg], "bid")
        assert metrics.trigger_value == 10.0

    def test_trigger_value_ask(self):
        """Trigger value should be ask when trigger_price_type='ask'."""
        leg = make_leg(bid=10.0, ask=10.20, mid=10.10, mark=10.15)
        metrics = compute_group_metrics([leg], "ask")
        assert metrics.trigger_value == 10.20


class TestEmptyLegs:
    """Tests for edge case with no legs."""

    def test_empty_legs_returns_zero_metrics(self):
        """Empty legs should return zero metrics."""
        metrics = compute_group_metrics([], "mark")

        assert metrics.position_type == "EMPTY"
        assert metrics.pnl == 0.0
        assert metrics.delta == 0.0
        assert len(metrics.legs) == 0


class TestLegacyCompatibility:
    """Tests for legacy field compatibility."""

    def test_legacy_fields_exist(self):
        """Legacy property names should still work."""
        leg = make_leg()
        metrics = compute_group_metrics([leg], "mark")

        # These should all work via @property aliases
        assert metrics.group_mark_value == metrics.mark
        assert metrics.group_mid_value == metrics.mid
        assert metrics.spread_bid == metrics.bid
        assert metrics.spread_ask == metrics.ask
        assert metrics.entry_price == metrics.entry
        assert metrics.total_cost == metrics.total_entry_cost
        assert metrics.pnl_mark == metrics.pnl
        assert metrics.group_delta == metrics.delta


class TestTrailingStopDebit:
    """Tests for trailing stop calculations on debit positions."""

    def test_debit_hwm_update_when_value_higher(self):
        """Debit: HWM should update when trigger_value > current_hwm."""
        leg = make_leg(quantity=5, mark=12.0)  # trigger_value=12.0
        metrics = compute_group_metrics(
            [leg], "mark",
            trail_mode="percent", trail_value=15.0,
            current_hwm=10.0, market_open=True
        )
        assert metrics.hwm_updated is True
        assert metrics.updated_hwm == 12.0  # New high

    def test_debit_hwm_no_update_when_value_lower(self):
        """Debit: HWM should NOT update when trigger_value < current_hwm."""
        leg = make_leg(quantity=5, mark=8.0)  # trigger_value=8.0
        metrics = compute_group_metrics(
            [leg], "mark",
            trail_mode="percent", trail_value=15.0,
            current_hwm=10.0, market_open=True
        )
        assert metrics.hwm_updated is False
        assert metrics.updated_hwm == 10.0  # Unchanged

    def test_debit_hwm_no_update_when_market_closed(self):
        """Debit: HWM should NOT update when market is closed."""
        leg = make_leg(quantity=5, mark=15.0)  # Higher value
        metrics = compute_group_metrics(
            [leg], "mark",
            trail_mode="percent", trail_value=15.0,
            current_hwm=10.0, market_open=False  # Market closed!
        )
        assert metrics.hwm_updated is False
        assert metrics.updated_hwm == 10.0  # Unchanged

    def test_debit_stop_price_percent(self):
        """Debit: stop = hwm * (1 - trail%) for percent mode."""
        leg = make_leg(quantity=5, mark=100.0)
        metrics = compute_group_metrics(
            [leg], "mark",
            trail_mode="percent", trail_value=15.0,
            current_hwm=100.0, market_open=True
        )
        # 100 * (1 - 0.15) = 85.0
        assert metrics.trail_stop_price == 85.0

    def test_debit_stop_price_absolute(self):
        """Debit: stop = hwm - trail_value for absolute mode."""
        leg = make_leg(quantity=5, mark=100.0)
        metrics = compute_group_metrics(
            [leg], "mark",
            trail_mode="absolute", trail_value=10.0,
            current_hwm=100.0, market_open=True
        )
        # 100 - 10 = 90.0
        assert metrics.trail_stop_price == 90.0

    def test_debit_limit_price_calculation(self):
        """Debit: limit_price = stop_price - limit_offset."""
        leg = make_leg(quantity=5, mark=100.0)
        metrics = compute_group_metrics(
            [leg], "mark",
            trail_mode="percent", trail_value=15.0,
            current_hwm=100.0, stop_type="limit", limit_offset=2.0,
            market_open=True
        )
        # stop=85, limit=85-2=83
        assert metrics.trail_stop_price == 85.0
        assert metrics.trail_limit_price == 83.0


class TestTrailingStopCredit:
    """Tests for trailing stop calculations on credit positions.

    IMPORTANT: For CREDIT SPREADS, trigger_value is NEGATIVE (e.g., -$4.30 for a spread).
    For SINGLE SHORT positions, trigger_value is POSITIVE (the option price itself).

    The HWM logic tracks the "best" value:
    - Credit spread (is_credit=True, negative trigger_value): lower is better
    - Single short (is_credit=True, positive trigger_value): lower is better too (option price dropping)
    """

    def test_single_short_hwm_update_when_price_drops(self):
        """Single short: HWM should update when option price drops (lower is better)."""
        # Short position: we want the option price to go DOWN
        leg = make_leg(quantity=-5, mark=8.0)  # Option price dropped to $8
        metrics = compute_group_metrics(
            [leg], "mark",
            trail_mode="percent", trail_value=15.0,
            current_hwm=10.0, market_open=True  # Previous HWM was $10
        )
        # 8.0 < 10.0 so should update (lower price is better for short)
        assert metrics.is_credit is True  # Short position is credit
        assert metrics.hwm_updated is True
        assert metrics.updated_hwm == 8.0

    def test_single_short_hwm_no_update_when_price_rises(self):
        """Single short: HWM should NOT update when option price rises (bad for us)."""
        leg = make_leg(quantity=-5, mark=12.0)  # Option price rose to $12
        metrics = compute_group_metrics(
            [leg], "mark",
            trail_mode="percent", trail_value=15.0,
            current_hwm=10.0, market_open=True  # Previous HWM was $10
        )
        # 12.0 > 10.0 so should NOT update
        assert metrics.hwm_updated is False
        assert metrics.updated_hwm == 10.0

    def test_single_short_stop_price_percent(self):
        """Single short: stop triggers when price rises above stop level."""
        leg = make_leg(quantity=-5, mark=10.0)
        metrics = compute_group_metrics(
            [leg], "mark",
            trail_mode="percent", trail_value=15.0,
            current_hwm=10.0, market_open=True
        )
        # For short: HWM=$10 (lowest price we've seen)
        # Stop = HWM * (1 + 15%) = 10 * 1.15 = $11.50
        # If price rises above $11.50, we're losing too much -> trigger stop
        assert metrics.trail_stop_price == 11.5

    def test_single_short_stop_price_absolute(self):
        """Single short: absolute stop price calculation."""
        leg = make_leg(quantity=-5, mark=10.0)
        metrics = compute_group_metrics(
            [leg], "mark",
            trail_mode="absolute", trail_value=2.0,
            current_hwm=10.0, market_open=True
        )
        # For credit + absolute: hwm + trail_value = 10 + 2 = 12
        # Stop when price rises above $12
        assert metrics.trail_stop_price == 12.0

    def test_credit_spread_hwm_tracking(self):
        """Credit spread: HWM tracks the most negative (best) value."""
        # Credit spread: short near, long far = negative net value
        short_leg = make_leg(con_id=1, strike=6800, quantity=-5, mark=16.50, fill_price=16.60)
        long_leg = make_leg(con_id=2, strike=6850, quantity=5, mark=12.20, fill_price=12.00)

        # Current value = long - short = 12.20 - 16.50 = -4.30 per contract
        metrics = compute_group_metrics(
            [short_leg, long_leg], "mark",
            trail_mode="percent", trail_value=15.0,
            current_hwm=-5.00, market_open=True  # Previous best was -5.00
        )

        # -4.30 > -5.00 so HWM should NOT update (less negative = worse for credit)
        assert metrics.is_credit is True
        assert metrics.hwm_updated is False
        assert metrics.updated_hwm == -5.00

    def test_credit_spread_hwm_update_on_improvement(self):
        """Credit spread: HWM updates when value becomes more negative (better)."""
        short_leg = make_leg(con_id=1, strike=6800, quantity=-5, mark=17.00, fill_price=16.60)
        long_leg = make_leg(con_id=2, strike=6850, quantity=5, mark=11.50, fill_price=12.00)

        # Current value = 11.50 - 17.00 = -5.50 per contract
        metrics = compute_group_metrics(
            [short_leg, long_leg], "mark",
            trail_mode="percent", trail_value=15.0,
            current_hwm=-5.00, market_open=True
        )

        # -5.50 < -5.00 so HWM should update (more negative = better)
        assert metrics.is_credit is True
        assert metrics.hwm_updated is True
        assert metrics.updated_hwm == -5.50


class TestTrailingStopEdgeCases:
    """Edge cases for trailing stop calculations."""

    def test_no_trailing_when_trail_mode_none(self):
        """No trailing stop values when trail_mode is None."""
        leg = make_leg(quantity=5, mark=10.0)
        metrics = compute_group_metrics(
            [leg], "mark",
            trail_mode=None,  # No trailing mode
            current_hwm=10.0, market_open=True
        )
        assert metrics.trail_stop_price == 0.0
        assert metrics.trail_limit_price == 0.0
        assert metrics.hwm_updated is False

    def test_hwm_initial_zero_debit(self):
        """Debit: When HWM is 0, any positive value should update it."""
        leg = make_leg(quantity=5, mark=10.0)
        metrics = compute_group_metrics(
            [leg], "mark",
            trail_mode="percent", trail_value=15.0,
            current_hwm=0.0, market_open=True
        )
        assert metrics.hwm_updated is True
        assert metrics.updated_hwm == 10.0

    def test_hwm_initial_zero_credit(self):
        """Single short: When HWM is 0, any value should update it."""
        # Single short has POSITIVE trigger_value (the option price)
        leg = make_leg(quantity=-5, mark=10.0)  # trigger_value=10.0 (positive!)
        metrics = compute_group_metrics(
            [leg], "mark",
            trail_mode="percent", trail_value=15.0,
            current_hwm=0.0, market_open=True
        )
        assert metrics.hwm_updated is True
        assert metrics.updated_hwm == 10.0  # Positive for single short

    def test_limit_price_not_set_for_market_stop(self):
        """Limit price should be 0 when stop_type is 'market'."""
        leg = make_leg(quantity=5, mark=100.0)
        metrics = compute_group_metrics(
            [leg], "mark",
            trail_mode="percent", trail_value=15.0,
            current_hwm=100.0, stop_type="market", limit_offset=2.0,
            market_open=True
        )
        assert metrics.trail_stop_price == 85.0
        assert metrics.trail_limit_price == 0.0  # No limit for market orders
