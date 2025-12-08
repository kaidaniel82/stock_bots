"""Group metrics calculation - pure math engine for group valuations.

SEMANTICS - Position Value Perspective:
========================================
All values represent what we OWN (positive) or OWE (negative).

- Long position: We OWN an asset → current_value is POSITIVE (we receive money when closing)
- Short position: We OWE an asset → current_value is NEGATIVE (we pay money when closing)
- Credit spread: Net credit received → entry_value POSITIVE, current_value NEGATIVE (pay to close)
- Debit spread: Net debit paid → entry_value NEGATIVE, current_value POSITIVE (receive to close)

P&L = current_value - entry_cost
    = what we get now - what we paid/received at entry

Examples:
---------
1. Long +5 calls @ $10, now worth $12:
   - entry_cost = -$5000 (we paid)
   - current_value = +$6000 (we receive if we close)
   - P&L = $6000 - (-$5000) = $6000 + $5000 = +$1000 ❌ WRONG
   - Actually: P&L = current - paid = $6000 - $5000 = +$1000 ✓

2. Short -3 puts @ $42, now worth $41:
   - entry_cost = +$12600 (we received credit)
   - current_value = -$12300 (we pay to close)
   - P&L = -$12300 - (+$12600) = -$24900 ❌ WRONG
   - Actually: P&L = received - pay_to_close = $12600 - $12300 = +$300 ✓

CORRECTED SEMANTICS:
====================
- entry_cost: What we PAID (positive for long, negative for short/credit)
- current_value: What position is worth NOW (positive for long, negative for short)
- P&L = current_value - entry_cost (for long) OR entry_credit + current_value (for short)

SIMPLER APPROACH - Cash Flow:
=============================
- total_cash_out: Money we spent (always positive or zero)
- total_cash_in: Money we received (always positive or zero)
- current_close_value: What we'd get/pay to close (positive = receive, negative = pay)
- P&L = current_close_value + (total_cash_in - total_cash_out)
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from .logger import logger


@dataclass
class LegData:
    """Data for a single leg in a group."""
    con_id: int
    symbol: str
    sec_type: str
    expiry: str
    strike: float
    right: str  # "C", "P", ""
    quantity: float
    multiplier: int
    fill_price: float
    bid: float
    ask: float
    mid: float
    mark: float
    # Greeks (per contract)
    delta: float = 0.0
    gamma: float = 0.0
    theta: float = 0.0
    vega: float = 0.0

    @property
    def expiry_fmt(self) -> str:
        """Formatted expiry: 20251209 -> DEC09'25."""
        if len(self.expiry) == 8:
            try:
                dt = datetime.strptime(self.expiry, "%Y%m%d")
                return dt.strftime("%b%d'%y").upper()
            except ValueError:
                pass
        return self.expiry

    @property
    def expiry_iso(self) -> str:
        """ISO formatted expiry: 20251209 -> 2025-12-09."""
        if len(self.expiry) == 8:
            try:
                dt = datetime.strptime(self.expiry, "%Y%m%d")
                return dt.strftime("%Y-%m-%d")
            except ValueError:
                pass
        return self.expiry

    @property
    def strike_str(self) -> str:
        """Formatted strike price."""
        return f"{self.strike:g}" if self.strike > 0 else "-"

    @property
    def side_str(self) -> str:
        """Call/Put indicator: C, P, or -."""
        return self.right if self.right in ("C", "P") else "-"

    @property
    def qty_str(self) -> str:
        """Quantity with sign: +1, -2."""
        return f"{self.quantity:+g}"

    @property
    def qty_abs(self) -> int:
        """Absolute quantity."""
        return abs(int(self.quantity))

    @property
    def fill_str(self) -> str:
        """Formatted fill price (static - entry price)."""
        return f"${self.fill_price:.2f}"

    @property
    def display_name(self) -> str:
        """Display name for the leg: ES DEC09'25 6850P."""
        if self.sec_type in ("OPT", "FOP"):
            return f"{self.symbol} {self.expiry_fmt} {self.strike:g}{self.right}"
        elif self.sec_type == "STK":
            return f"{self.symbol}"
        elif self.sec_type == "FUT":
            return f"{self.symbol} {self.expiry_fmt}"
        else:
            return f"{self.symbol} {self.sec_type}"

    @property
    def info_line(self) -> str:
        """Formatted info line with live data."""
        name = f"{self.display_name:<22}"[:22]
        sign = "+" if self.quantity > 0 else "-"
        fill = f"${self.fill_price:.2f}".rjust(7)
        mark = f"${self.mark:.2f}".rjust(7)
        delta = f"{self.delta:+.2f}".rjust(6)
        return f" {sign}{self.qty_abs}x {name} ⋮ Fill {fill}  Mark {mark}  Δ {delta}"

    @property
    def is_long(self) -> bool:
        """True if long position (positive quantity)."""
        return self.quantity > 0

    @property
    def position_type(self) -> str:
        """Return 'LONG' or 'SHORT'."""
        return "LONG" if self.is_long else "SHORT"


@dataclass
class GroupMetrics:
    """Calculated metrics for a group of positions.

    All prices (mark, mid, bid, ask, entry, trigger) are PER-UNIT prices,
    meaning the price for 1 contract of the spread/position.

    For display, these match what you'd see in an option chain.
    For P&L calculation, we multiply by quantity and multiplier internally.
    """
    # Leg info
    legs: list[LegData]

    # Position type info
    position_type: str           # "LONG", "SHORT", "SPREAD_LONG", "SPREAD_SHORT", "RATIO"
    is_credit: bool              # True if net credit position (received money at entry)

    # Per-unit prices (what you'd see in option chain)
    # These are ALWAYS POSITIVE - they represent the price of the instrument
    mark: float                  # Current mark price per unit
    mid: float                   # Current mid price per unit
    bid: float                   # Current bid price per unit (what we get to sell)
    ask: float                   # Current ask price per unit (what we pay to buy)
    entry: float                 # Entry price per unit (fill price)

    # Trigger value for trailing stop (based on trigger_price_type)
    trigger_value: float         # Current trigger price for trailing stop

    # Total position value (with qty * multiplier)
    # Positive = we receive money, Negative = we pay money
    total_current_value: float   # Current position value (to close)
    total_entry_cost: float      # What we paid (positive) or received (negative) at entry

    # P&L
    pnl: float                   # Unrealized P&L

    # Number of logical units (spreads/ratios) - GCD of quantities
    num_units: int = 1

    # Greeks (aggregated for entire group, position-weighted)
    delta: float = 0.0
    gamma: float = 0.0
    theta: float = 0.0
    vega: float = 0.0

    # Trailing Stop fields (calculated when trail_mode is provided)
    current_hwm: float = 0.0      # Input HWM (before update check)
    updated_hwm: float = 0.0      # Output HWM (after update logic)
    hwm_updated: bool = False     # True if HWM changed this tick
    trail_stop_price: float = 0.0 # Calculated stop price from HWM
    trail_limit_price: float = 0.0  # Calculated limit price (if stop_type="limit")
    stop_pnl: float = 0.0         # P&L if stop is triggered

    # Formatted strings for UI (use absolute values for display)
    @property
    def mark_str(self) -> str:
        return f"${abs(self.mark):.2f}"

    @property
    def mid_str(self) -> str:
        return f"${abs(self.mid):.2f}"

    @property
    def bid_str(self) -> str:
        return f"${abs(self.bid):.2f}"

    @property
    def ask_str(self) -> str:
        return f"${abs(self.ask):.2f}"

    @property
    def entry_str(self) -> str:
        return f"${abs(self.entry):.2f}"

    @property
    def trigger_value_str(self) -> str:
        return f"${abs(self.trigger_value):.2f}"

    @property
    def pnl_str(self) -> str:
        return f"${self.pnl:.2f}"

    @property
    def stop_pnl_str(self) -> str:
        return f"${self.stop_pnl:.2f}"

    @property
    def delta_str(self) -> str:
        return f"{self.delta:+.2f}"

    @property
    def gamma_str(self) -> str:
        return f"{self.gamma:.4f}"

    @property
    def theta_str(self) -> str:
        return f"{self.theta:+.2f}"

    @property
    def vega_str(self) -> str:
        return f"{self.vega:+.2f}"

    # Legacy compatibility
    @property
    def group_mark_value(self) -> float:
        return self.mark

    @property
    def group_mid_value(self) -> float:
        return self.mid

    @property
    def spread_bid(self) -> float:
        return self.bid

    @property
    def spread_ask(self) -> float:
        return self.ask

    @property
    def spread_bid_str(self) -> str:
        return self.bid_str

    @property
    def spread_ask_str(self) -> str:
        return self.ask_str

    @property
    def entry_price(self) -> float:
        return self.entry

    @property
    def entry_price_str(self) -> str:
        return self.entry_str

    @property
    def cost_str(self) -> str:
        return self.entry_str

    @property
    def total_cost(self) -> float:
        return self.total_entry_cost

    @property
    def pnl_mark(self) -> float:
        return self.pnl

    @property
    def pnl_mid(self) -> float:
        return self.pnl

    @property
    def pnl_close(self) -> float:
        return self.pnl

    @property
    def pnl_mark_str(self) -> str:
        return self.pnl_str

    @property
    def group_delta(self) -> float:
        return self.delta

    @property
    def group_gamma(self) -> float:
        return self.gamma

    @property
    def group_theta(self) -> float:
        return self.theta

    @property
    def group_vega(self) -> float:
        return self.vega


def calculate_stop_price(hwm: float, trail_mode: str, trail_value: float,
                         is_credit: bool = False) -> float:
    """
    Calculate stop price based on HWM/LWM and trail settings.

    DEBIT positions (long, debit spreads): HWM is positive, tracks HIGHEST value
    - We profit when value goes UP
    - Stop should be BELOW HWM (trigger when value drops)
    - Formula: hwm * (1 - trail%) or hwm - trail_value

    CREDIT positions: LWM tracks "best" value (closest to $0)
    - Single short: LWM is positive (lowest option price = best)
      Stop should be ABOVE LWM (trigger when price rises)
      Example: LWM=$8, trail=15% → stop = $8 * 1.15 = $9.20

    - Credit spread: LWM is NEGATIVE but closer to $0 = better
      e.g., LWM=-$4.30 means we pay $4.30 to close (good!)
      Stop should be MORE NEGATIVE (worse = we'd pay more)
      Example: LWM=-4.30, trail=15% → stop = -4.30 - |4.30|*0.15 = -4.30 - 0.645 = -4.95
      Triggered when value drops to -$4.95 (we'd pay $4.95 = bad)
    """
    # For Credit positions, stop is FURTHER from $0 (worse price = higher cost to close)
    # For Debit positions, stop is LOWER than HWM (value dropped)
    #
    # IMPORTANT: For IBKR BAG orders, we need POSITIVE stop prices!
    # - Credit Spread: internal value is negative, but order uses positive price
    # - The stop order triggers when spread price rises above stop
    #
    abs_hwm = abs(hwm)

    if trail_mode == "percent":
        if is_credit:
            # Credit: stop is abs(LWM) + trail% (higher = worse for us)
            # LWM=±$3.30, trail=15% → stop = $3.30 * 1.15 = $3.80
            return round(abs_hwm * (1 + trail_value / 100), 2)
        else:
            # Debit: stop is trail% BELOW HWM
            return round(abs_hwm * (1 - trail_value / 100), 2)
    else:  # absolute
        if is_credit:
            # Credit: stop is abs(LWM) + trail (higher = worse for us)
            # LWM=±$3.30, trail=$1.00 → stop = $3.30 + $1.00 = $4.30
            return round(abs_hwm + trail_value, 2)
        else:
            # Debit: stop is trail_value BELOW
            return round(abs_hwm - trail_value, 2)


def compute_group_metrics(
    legs: list[LegData],
    trigger_price_type: str = "mark",
    # Trailing Stop parameters (optional)
    trail_mode: str = None,
    trail_value: float = 0.0,
    current_hwm: float = 0.0,
    stop_type: str = "market",
    limit_offset: float = 0.0,
    market_open: bool = True,
) -> GroupMetrics:
    """
    Compute group metrics from leg data.

    Args:
        legs: List of position legs
        trigger_price_type: Which price to use for trailing stop trigger
                           ("mark", "mid", "bid", "ask", "last")
        trail_mode: "percent" or "absolute" (optional, enables HWM/stop calculation)
        trail_value: Trail amount (10 = 10% or $10 depending on mode)
        current_hwm: Current high water mark (passed in from state)
        stop_type: "market" or "limit"
        limit_offset: Offset for limit orders
        market_open: Whether market is open (HWM only updates when open)

    Returns:
        GroupMetrics with all calculated values including trailing stop fields

    Calculation Logic:
    ==================
    1. Determine position type (single long/short, spread, ratio)
    2. Calculate per-unit prices (always positive, like option chain)
    3. Calculate total position value with qty * multiplier
    4. Calculate P&L
    5. Update HWM if new best value and market is open
    6. Calculate stop/limit prices from HWM
    """
    if not legs:
        return GroupMetrics(
            legs=[],
            position_type="EMPTY",
            is_credit=False,
            mark=0.0,
            mid=0.0,
            bid=0.0,
            ask=0.0,
            entry=0.0,
            trigger_value=0.0,
            total_current_value=0.0,
            total_entry_cost=0.0,
            pnl=0.0,
            delta=0.0,
            gamma=0.0,
            theta=0.0,
            vega=0.0,
        )

    # === STEP 1: Determine position type and calculate GCD for per-unit pricing ===
    long_legs = [l for l in legs if l.is_long]
    short_legs = [l for l in legs if not l.is_long]

    if len(legs) == 1:
        position_type = "LONG" if legs[0].is_long else "SHORT"
    elif len(long_legs) > 0 and len(short_legs) > 0:
        # Multi-leg spread
        long_qty = sum(abs(l.quantity) for l in long_legs)
        short_qty = sum(abs(l.quantity) for l in short_legs)
        if long_qty == short_qty:
            position_type = "SPREAD"
        else:
            position_type = "RATIO"
    elif len(long_legs) > 0:
        position_type = "LONG"  # All long legs
    else:
        position_type = "SHORT"  # All short legs

    # Calculate GCD of all quantities to find "1 unit" of the position
    # e.g., +6/-2 has GCD=2, so 1 unit = +3/-1
    # e.g., +5/-5 has GCD=5, so 1 unit = +1/-1
    from math import gcd
    from functools import reduce
    all_qtys = [abs(int(l.quantity)) for l in legs]
    position_gcd = reduce(gcd, all_qtys) if all_qtys else 1

    # === STEP 2: Calculate per-unit and total values ===
    # Per-unit accumulators - weighted by unit_qty (qty / gcd)
    unit_mark = 0.0
    unit_mid = 0.0
    unit_bid = 0.0  # What we get if we close (sell longs @ bid, buy shorts @ ask)
    unit_ask = 0.0  # What we pay if we enter (buy longs @ ask, sell shorts @ bid)
    unit_entry = 0.0

    # Total position value accumulators
    total_current = 0.0  # Current value to close position
    total_entry = 0.0    # What we paid/received at entry

    # Greeks
    total_delta = 0.0
    total_gamma = 0.0
    total_theta = 0.0
    total_vega = 0.0

    for leg in legs:
        qty = leg.quantity  # Signed quantity
        abs_qty = abs(qty)
        mult = leg.multiplier
        is_long = leg.is_long

        # Unit quantity for per-unit pricing (qty / gcd)
        unit_qty = abs_qty // position_gcd

        # Get prices with fallbacks
        leg_mark = leg.mark if leg.mark > 0 else leg.mid
        leg_mid = leg.mid if leg.mid > 0 else leg.mark
        leg_bid = leg.bid if leg.bid > 0 else leg_mark
        leg_ask = leg.ask if leg.ask > 0 else leg_mark

        # === Per-unit prices (weighted by unit_qty) ===
        # For a 2:1 ratio (+2/-1), unit_qty for long=2, short=1
        # Mark per unit = (long_mark * 2) - (short_mark * 1)
        if is_long:
            unit_mark += leg_mark * unit_qty
            unit_mid += leg_mid * unit_qty
            unit_bid += leg_bid * unit_qty   # Sell long @ bid
            unit_ask += leg_ask * unit_qty   # Buy long @ ask
            unit_entry += leg.fill_price * unit_qty
        else:
            unit_mark -= leg_mark * unit_qty
            unit_mid -= leg_mid * unit_qty
            unit_bid -= leg_ask * unit_qty   # Buy back short @ ask (costs us)
            unit_ask -= leg_bid * unit_qty   # Sell short @ bid (we receive)
            unit_entry -= leg.fill_price * unit_qty

        # === Total position value (with qty * multiplier) ===
        # Use MARK for current value (like broker does), not bid/ask
        if is_long:
            total_current += leg_mark * abs_qty * mult  # Current value at mark
            total_entry += leg.fill_price * abs_qty * mult  # Paid at entry
        else:
            total_current -= leg_mark * abs_qty * mult  # Current value at mark (negative for short)
            total_entry -= leg.fill_price * abs_qty * mult  # Received at entry (credit)

        # Greeks (position-weighted)
        total_delta += leg.delta * qty * mult
        total_gamma += leg.gamma * qty * mult
        total_theta += leg.theta * qty * mult
        total_vega += leg.vega * qty * mult

    # === STEP 3: Normalize per-unit prices ===
    # For single positions, we want to show the actual instrument prices
    # For spreads, the calculated spread prices

    if position_type in ("LONG", "SHORT") and len(legs) == 1:
        # Single position: show the actual instrument prices (not spread-calculated)
        leg = legs[0]
        unit_mark = leg.mark if leg.mark > 0 else leg.mid
        unit_mid = leg.mid if leg.mid > 0 else leg.mark
        unit_bid = leg.bid if leg.bid > 0 else unit_mark
        unit_ask = leg.ask if leg.ask > 0 else unit_mark
        unit_entry = leg.fill_price

    # Determine if credit or debit
    is_credit = total_entry < 0  # Negative entry = received credit

    # === STEP 4: Calculate P&L ===
    # P&L = Current value - Entry cost
    # If we paid $1000 (total_entry = 1000) and now worth $1200 (total_current = 1200)
    #   P&L = 1200 - 1000 = +$200
    # If we received $500 credit (total_entry = -500) and now costs $300 to close (total_current = -300)
    #   P&L = -300 - (-500) = -300 + 500 = +$200
    pnl = total_current - total_entry

    # === STEP 5: Calculate trigger value ===
    # Use the appropriate price based on trigger_price_type
    if trigger_price_type == "bid":
        trigger_value = unit_bid
    elif trigger_price_type == "ask":
        trigger_value = unit_ask
    elif trigger_price_type == "mid":
        trigger_value = unit_mid
    else:  # "mark" or "last"
        trigger_value = unit_mark

    # === STEP 6: Calculate HWM and Stop prices (if trail_mode provided) ===
    updated_hwm = current_hwm
    hwm_updated = False
    trail_stop_price = 0.0
    trail_limit_price = 0.0

    if trail_mode:
        # Determine if this is a new "best" value
        # The logic depends on position type and value sign:
        #
        # DEBIT (is_credit=False): Higher value is better (we profit when value goes up)
        #   - Long call/put: value goes up = profit
        #   - Debit spread: value goes up = profit
        #
        # CREDIT (is_credit=True): Lower absolute value is better (closer to $0)
        #   - Single short: sold at $10, now $8 = good (lower)
        #   - Credit spread (positive): sold for credit, now costs $3.30 to close
        #     Lower is better ($3.20 < $3.30 = good)
        #   - Credit spread (negative): -$4.00 entry, -$3.40 current = good
        #     Higher (closer to 0) is better (-$3.40 > -$4.00 = good)
        #
        # CREDIT with POSITIVE trigger_value (Single Short, Credit Spread):
        #   - Lower price is better (option decays, we keep premium)
        #   - e.g., sold at $10, now $8 = good, now $12 = bad
        #
        # CREDIT with NEGATIVE trigger_value (Credit Spread negative):
        #   - Closer to $0 (HIGHER/less negative) is better
        #   - e.g., -$4.00 entry, -$3.40 current = good (pay less to close)
        #
        if is_credit:
            if trigger_value >= 0:
                # Single short OR Credit spread (positive): lower is better
                is_new_best = trigger_value < current_hwm or current_hwm == 0
            else:
                # Credit spread (negative values): higher (closer to 0) is better
                is_new_best = trigger_value > current_hwm or current_hwm == 0
        else:
            # Debit: higher is better
            is_new_best = trigger_value > current_hwm

        # Update HWM only when market is open
        if market_open and is_new_best:
            updated_hwm = trigger_value
            hwm_updated = True
            direction = "down" if is_credit else "up"
            logger.debug(f"Trailing: HWM updated {direction} ${current_hwm:.2f} -> ${trigger_value:.2f}")

        # Calculate stop price from HWM
        if updated_hwm != 0:
            trail_stop_price = calculate_stop_price(updated_hwm, trail_mode, trail_value, is_credit)

            # Calculate limit price if limit order type
            # Credit (BUY to close): limit = stop + offset (willing to pay more)
            # Debit (SELL to close): limit = stop - offset (willing to accept less)
            if stop_type == "limit" and trail_stop_price != 0:
                if is_credit:
                    trail_limit_price = round(trail_stop_price + limit_offset, 2)
                else:
                    trail_limit_price = round(trail_stop_price - limit_offset, 2)

    # === STEP 7: Calculate Stop P&L ===
    # P&L if stop is triggered at trail_stop_price
    # For credit spreads, both unit_entry and trail_stop_price can be negative
    # Use absolute values: profit = |entry| - |stop| for credits
    # For debit: profit = stop - entry (both positive)
    stop_pnl = 0.0
    if trail_stop_price != 0 and unit_entry != 0:
        if is_credit:
            # Credit: profit if |stop| < |entry| (bought back cheaper)
            per_contract_pnl = abs(unit_entry) - abs(trail_stop_price)
        else:
            # Debit: profit if stop > entry (sold higher)
            per_contract_pnl = trail_stop_price - unit_entry
        # Scale by position size (qty * multiplier = total_entry / unit_entry)
        scale = abs(total_entry / unit_entry) if unit_entry != 0 else 0
        stop_pnl = round(per_contract_pnl * scale, 2)

    logger.info(
        f"Group metrics [{position_type}]: entry=${unit_entry:.2f} bid=${unit_bid:.2f} "
        f"ask=${unit_ask:.2f} mark=${unit_mark:.2f} trigger={trigger_price_type}=${trigger_value:.2f} "
        f"total_entry=${total_entry:.2f} total_current=${total_current:.2f} P&L=${pnl:.2f}"
        f"{f' HWM=${updated_hwm:.2f} Stop=${trail_stop_price:.2f}' if trail_mode else ''}"
    )

    return GroupMetrics(
        legs=legs,
        position_type=position_type,
        is_credit=is_credit,
        num_units=position_gcd,
        mark=round(unit_mark, 2),
        mid=round(unit_mid, 2),
        bid=round(unit_bid, 2),
        ask=round(unit_ask, 2),
        entry=round(unit_entry, 2),
        trigger_value=round(trigger_value, 2),
        total_current_value=round(total_current, 2),
        total_entry_cost=round(total_entry, 2),
        pnl=round(pnl, 2),
        delta=round(total_delta, 2),
        gamma=round(total_gamma, 4),
        theta=round(total_theta, 2),
        vega=round(total_vega, 2),
        # Trailing stop fields
        current_hwm=round(current_hwm, 2),
        updated_hwm=round(updated_hwm, 2),
        hwm_updated=hwm_updated,
        trail_stop_price=trail_stop_price,
        trail_limit_price=trail_limit_price,
        stop_pnl=stop_pnl,
    )
