"""Group metrics calculation - pure math engine for group valuations."""
from dataclasses import dataclass
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

    @property
    def display_name(self) -> str:
        """Display name for the leg."""
        if self.sec_type == "OPT":
            return f"{self.symbol} {self.expiry} {self.strike}{self.right}"
        elif self.sec_type == "STK":
            return f"{self.symbol}"
        else:
            return f"{self.symbol} {self.sec_type}"

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
    """Calculated metrics for a group of positions."""
    # Leg info
    legs: list[LegData]

    # Value calculations (per-leg basis, summed)
    group_mark_value: float      # Sum of mark * qty * mult
    group_mid_value: float       # Sum of mid * qty * mult

    # Spread-level bid/ask (Natural Price for closing)
    # Spread Bid = what you get if you close now (sell longs @ bid, buy shorts @ ask)
    # Spread Ask = what you pay to enter (buy longs @ ask, sell shorts @ bid)
    spread_bid: float            # Natural exit price (close value)
    spread_ask: float            # Natural entry price

    # Cost basis
    total_cost: float            # Sum of fill_price * abs(qty) * mult

    # PnL
    pnl_mark: float              # group_mark_value - total_cost
    pnl_mid: float               # group_mid_value - total_cost
    pnl_close: float             # spread_bid - total_cost (realistic exit PnL)

    # Formatted strings for UI
    @property
    def mark_str(self) -> str:
        return f"${self.group_mark_value:.2f}"

    @property
    def mid_str(self) -> str:
        return f"${self.group_mid_value:.2f}"

    @property
    def spread_bid_str(self) -> str:
        return f"${self.spread_bid:.2f}"

    @property
    def spread_ask_str(self) -> str:
        return f"${self.spread_ask:.2f}"

    @property
    def cost_str(self) -> str:
        return f"${self.total_cost:.2f}"

    @property
    def pnl_mark_str(self) -> str:
        return f"${self.pnl_mark:.2f}"

    @property
    def pnl_mid_str(self) -> str:
        return f"${self.pnl_mid:.2f}"

    @property
    def pnl_close_str(self) -> str:
        return f"${self.pnl_close:.2f}"


def compute_group_metrics(legs: list[LegData]) -> GroupMetrics:
    """
    Compute group metrics from leg data.

    Two levels of pricing:
    1. Per-leg: Mark and Mid for each individual contract
    2. Spread-level: Natural Bid/Ask for the entire spread
       - Spread Bid = Sum(Long @ Bid) + Sum(Short @ Ask)  [what you get to close]
       - Spread Ask = Sum(Long @ Ask) + Sum(Short @ Bid)  [what you pay to enter]
    """
    if not legs:
        return GroupMetrics(
            legs=[],
            group_mark_value=0.0,
            group_mid_value=0.0,
            spread_bid=0.0,
            spread_ask=0.0,
            total_cost=0.0,
            pnl_mark=0.0,
            pnl_mid=0.0,
            pnl_close=0.0,
        )

    group_mark_value = 0.0  # WITHOUT multiplier for display (like option chain)
    group_mid_value = 0.0   # WITHOUT multiplier for display
    mark_value_pos = 0.0    # WITH multiplier for PnL calculation
    mid_value_pos = 0.0     # WITH multiplier for PnL calculation
    spread_bid = 0.0  # Natural exit price (close) - WITHOUT multiplier for display
    spread_ask = 0.0  # Natural entry price - WITHOUT multiplier for display
    close_value = 0.0  # Exit value WITH multiplier for pnl_close calculation
    total_cost = 0.0

    for leg in legs:
        qty = leg.quantity
        mult = leg.multiplier
        abs_qty = abs(qty)

        # Mark value - WITHOUT multiplier for display (like option chain)
        mark_display = leg.mark * qty  # No multiplier
        group_mark_value += mark_display
        # WITH multiplier for PnL
        mark_value_pos += leg.mark * qty * mult

        # Mid value - WITHOUT multiplier for display
        if leg.mid > 0:
            mid_display = leg.mid * qty  # No multiplier
            group_mid_value += mid_display
            mid_value_pos += leg.mid * qty * mult
        else:
            group_mid_value += mark_display
            mid_value_pos += leg.mark * qty * mult

        # Spread-level Natural Price calculation
        # For closing the spread:
        #   Long legs: sell at bid
        #   Short legs: buy back at ask
        leg_bid = leg.bid if leg.bid > 0 else leg.mark
        leg_ask = leg.ask if leg.ask > 0 else leg.mark

        if leg.is_long:
            # Long: to close, sell at bid
            spread_bid += leg_bid * abs_qty  # No multiplier - option chain price
            spread_ask += leg_ask * abs_qty
            close_value += leg_bid * abs_qty * mult  # WITH multiplier for PnL
        else:
            # Short: to close, buy at ask (cost us money, so subtract)
            spread_bid -= leg_ask * abs_qty  # No multiplier
            spread_ask -= leg_bid * abs_qty
            close_value -= leg_ask * abs_qty * mult  # WITH multiplier for PnL

        # Cost basis: what we paid to enter
        # Long: paid fill_price, Short: received fill_price (negative cost)
        if leg.is_long:
            total_cost += leg.fill_price * abs_qty * mult
        else:
            total_cost -= leg.fill_price * abs_qty * mult  # Credit received

    # Calculate PnL (all with multiplier for position value)
    pnl_mark = mark_value_pos - total_cost
    pnl_mid = mid_value_pos - total_cost
    pnl_close = close_value - total_cost  # Realistic exit PnL (with multiplier)

    logger.debug(
        f"Group metrics: mark=${group_mark_value:.2f} mid=${group_mid_value:.2f} "
        f"spread_bid=${spread_bid:.2f} spread_ask=${spread_ask:.2f} cost=${total_cost:.2f} "
        f"pnl_mark=${pnl_mark:.2f} pnl_close=${pnl_close:.2f}"
    )

    return GroupMetrics(
        legs=legs,
        group_mark_value=round(group_mark_value, 2),
        group_mid_value=round(group_mid_value, 2),
        spread_bid=round(spread_bid, 2),
        spread_ask=round(spread_ask, 2),
        total_cost=round(total_cost, 2),
        pnl_mark=round(pnl_mark, 2),
        pnl_mid=round(pnl_mid, 2),
        pnl_close=round(pnl_close, 2),
    )
