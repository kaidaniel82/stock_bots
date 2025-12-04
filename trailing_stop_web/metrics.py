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
    # Greeks (per contract)
    delta: float = 0.0
    gamma: float = 0.0
    theta: float = 0.0
    vega: float = 0.0

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
    entry_price: float           # Per-contract entry price (for display, like spread_bid)
    total_cost: float            # Sum of fill_price * abs(qty) * mult (for PnL calc)

    # PnL
    pnl_mark: float              # group_mark_value - total_cost
    pnl_mid: float               # group_mid_value - total_cost
    pnl_close: float             # spread_bid - total_cost (realistic exit PnL)

    # Greeks (aggregated for entire group, position-weighted)
    group_delta: float = 0.0     # Sum of delta * qty * mult
    group_gamma: float = 0.0     # Sum of gamma * qty * mult
    group_theta: float = 0.0     # Sum of theta * qty * mult
    group_vega: float = 0.0      # Sum of vega * qty * mult

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
    def entry_price_str(self) -> str:
        return f"${self.entry_price:.2f}"

    @property
    def cost_str(self) -> str:
        return f"${self.entry_price:.2f}"  # Use per-contract price for display

    @property
    def pnl_mark_str(self) -> str:
        return f"${self.pnl_mark:.2f}"

    @property
    def pnl_mid_str(self) -> str:
        return f"${self.pnl_mid:.2f}"

    @property
    def pnl_close_str(self) -> str:
        return f"${self.pnl_close:.2f}"

    @property
    def delta_str(self) -> str:
        return f"{self.group_delta:+.2f}"

    @property
    def gamma_str(self) -> str:
        return f"{self.group_gamma:.4f}"

    @property
    def theta_str(self) -> str:
        return f"{self.group_theta:+.2f}"

    @property
    def vega_str(self) -> str:
        return f"{self.group_vega:+.2f}"


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
            entry_price=0.0,
            total_cost=0.0,
            pnl_mark=0.0,
            pnl_mid=0.0,
            pnl_close=0.0,
            group_delta=0.0,
            group_gamma=0.0,
            group_theta=0.0,
            group_vega=0.0,
        )

    # For display: per-contract prices (like option chain shows)
    # For PnL: total position value with multiplier
    group_mark_value = 0.0  # Per-contract mark (no qty, no mult)
    group_mid_value = 0.0   # Per-contract mid
    spread_bid = 0.0        # Per-contract natural exit price
    spread_ask = 0.0        # Per-contract natural entry price
    entry_price = 0.0       # Per-contract fill/entry price

    mark_value_pos = 0.0    # Total position mark value (WITH qty * mult) for PnL
    mid_value_pos = 0.0     # Total position mid value for PnL
    close_value = 0.0       # Total exit value for pnl_close calculation
    total_cost = 0.0

    # Greeks aggregated (position-weighted)
    group_delta = 0.0
    group_gamma = 0.0
    group_theta = 0.0
    group_vega = 0.0

    for leg in legs:
        qty = leg.quantity
        mult = leg.multiplier
        abs_qty = abs(qty)
        # Sign: +1 for long, -1 for short
        sign = 1 if leg.is_long else -1

        # Per-contract Mark value (no qty multiplier for display)
        # Long adds value, short subtracts (spread pricing)
        group_mark_value += leg.mark * sign
        # Total position value with qty and mult for PnL
        mark_value_pos += leg.mark * qty * mult

        # Per-contract Mid value
        mid = leg.mid if leg.mid > 0 else leg.mark
        group_mid_value += mid * sign
        mid_value_pos += mid * qty * mult

        # Spread-level Natural Price calculation (per-contract)
        # For closing the spread:
        #   Long legs: sell at bid
        #   Short legs: buy back at ask
        leg_bid = leg.bid if leg.bid > 0 else leg.mark
        leg_ask = leg.ask if leg.ask > 0 else leg.mark

        if leg.is_long:
            # Long: to close, sell at bid
            spread_bid += leg_bid      # Per-contract
            spread_ask += leg_ask
            close_value += leg_bid * abs_qty * mult  # Total for PnL
        else:
            # Short: to close, buy at ask (cost us money, so subtract)
            spread_bid -= leg_ask      # Per-contract
            spread_ask -= leg_bid
            close_value -= leg_ask * abs_qty * mult  # Total for PnL

        # Cost basis
        # Per-contract entry price (like spread_bid/ask - for display)
        if leg.is_long:
            entry_price += leg.fill_price  # Long: paid this
        else:
            entry_price -= leg.fill_price  # Short: received this (credit)

        # Total cost with qty and mult (for PnL calculation)
        if leg.is_long:
            total_cost += leg.fill_price * abs_qty * mult
        else:
            total_cost -= leg.fill_price * abs_qty * mult  # Credit received

        # Aggregate Greeks (position-weighted: greek * qty * mult)
        group_delta += leg.delta * qty * mult
        group_gamma += leg.gamma * qty * mult
        group_theta += leg.theta * qty * mult
        group_vega += leg.vega * qty * mult

    # Calculate PnL (all with multiplier for position value)
    pnl_mark = mark_value_pos - total_cost
    pnl_mid = mid_value_pos - total_cost
    pnl_close = close_value - total_cost  # Realistic exit PnL (with multiplier)

    logger.info(
        f"Group metrics: entry_price=${entry_price:.2f} spread_bid=${spread_bid:.2f} "
        f"spread_ask=${spread_ask:.2f} total_cost=${total_cost:.2f}"
    )

    return GroupMetrics(
        legs=legs,
        group_mark_value=round(group_mark_value, 2),
        group_mid_value=round(group_mid_value, 2),
        spread_bid=round(spread_bid, 2),
        spread_ask=round(spread_ask, 2),
        entry_price=round(entry_price, 2),
        total_cost=round(total_cost, 2),
        pnl_mark=round(pnl_mark, 2),
        pnl_mid=round(pnl_mid, 2),
        pnl_close=round(pnl_close, 2),
        group_delta=round(group_delta, 2),
        group_gamma=round(group_gamma, 4),
        group_theta=round(group_theta, 2),
        group_vega=round(group_vega, 2),
    )
