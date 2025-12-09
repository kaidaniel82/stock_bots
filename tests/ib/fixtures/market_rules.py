"""IB Market Rules fixtures for testing tick size resolution.

These fixtures simulate real IB API responses for reqMarketRule() and
reqContractDetails(). They're based on actual IB data structures.

Key insight: Many options (especially SPX) have price-dependent tick sizes:
- Prices below $3.00: tick = 0.01
- Prices at/above $3.00: tick = 0.05

This is the root cause of the bug where we incorrectly used 0.01 for all prices.
"""
from types import SimpleNamespace
from dataclasses import dataclass
from typing import Optional


@dataclass
class MockPriceIncrement:
    """Mimics ib_insync PriceIncrement from reqMarketRule()."""
    lowEdge: float
    increment: float


@dataclass
class MockContractDetails:
    """Mimics ib_insync ContractDetails."""
    minTick: float
    validExchanges: str
    marketRuleIds: str
    tradingHours: str = ""
    liquidHours: str = ""
    timeZoneId: str = "US/Eastern"


@dataclass
class MockContract:
    """Mimics ib_insync Contract."""
    conId: int
    symbol: str
    secType: str
    exchange: str = "SMART"
    primaryExchange: str = ""
    currency: str = "USD"
    lastTradeDateOrContractMonth: str = ""
    strike: float = 0.0
    right: str = ""
    multiplier: str = "100"
    comboLegs: Optional[list] = None


# =============================================================================
# MARKET RULE FIXTURES
# =============================================================================

# SPX Option Market Rule (Rule ID 110 from IB)
# CBOE official tick sizes for SPX:
# - Below $3.00: tick = 0.05 ($5.00)
# - At/above $3.00: tick = 0.10 ($10.00)
# Source: https://www.cboe.com/tradable_products/sp_500/spx_options/specifications/
SPX_OPTION_MARKET_RULE = [
    MockPriceIncrement(lowEdge=0.0, increment=0.05),   # Below $3: tick=0.05
    MockPriceIncrement(lowEdge=3.0, increment=0.10),   # $3 and above: tick=0.10
]

# Stock Market Rule (typical US equities)
# Simple: always 0.01 tick
STOCK_MARKET_RULE = [
    MockPriceIncrement(lowEdge=0.0, increment=0.01),
]

# Penny Pilot Options (many equity options)
# Similar to SPX but different threshold
PENNY_PILOT_OPTION_RULE = [
    MockPriceIncrement(lowEdge=0.0, increment=0.01),   # Below $3: tick=0.01
    MockPriceIncrement(lowEdge=3.0, increment=0.05),   # $3 and above: tick=0.05
]

# ES Future Option (CME)
# Tick size is always 0.25 for ES options
ES_OPTION_MARKET_RULE = [
    MockPriceIncrement(lowEdge=0.0, increment=0.25),
]


# =============================================================================
# CONTRACT DETAILS FIXTURES
# =============================================================================

SPX_OPTION_CONTRACT_DETAILS = MockContractDetails(
    minTick=0.05,  # Default minTick (for prices >= $3)
    validExchanges="SMART,CBOE",
    marketRuleIds="239,239",  # Rule 239 for both exchanges
    tradingHours="20241209:0930-20241209:1615;20241210:0930-20241210:1615",
    liquidHours="20241209:0930-20241209:1615;20241210:0930-20241210:1615",
    timeZoneId="US/Eastern",
)

AAPL_STOCK_CONTRACT_DETAILS = MockContractDetails(
    minTick=0.01,
    validExchanges="SMART,NASDAQ,NYSE",
    marketRuleIds="26,26,26",
    tradingHours="20241209:0400-20241209:2000",
    liquidHours="20241209:0930-20241209:1600",
    timeZoneId="US/Eastern",
)


# =============================================================================
# CONTRACT FIXTURES
# =============================================================================

def create_spx_option_contract(
    con_id: int = 123456789,
    strike: float = 6000.0,
    right: str = "C",
    expiry: str = "20241220"
) -> MockContract:
    """Create a mock SPX option contract."""
    return MockContract(
        conId=con_id,
        symbol="SPX",
        secType="OPT",
        exchange="SMART",
        primaryExchange="CBOE",
        lastTradeDateOrContractMonth=expiry,
        strike=strike,
        right=right,
        multiplier="100",
    )


def create_stock_contract(
    con_id: int = 265598,
    symbol: str = "AAPL"
) -> MockContract:
    """Create a mock stock contract."""
    return MockContract(
        conId=con_id,
        symbol=symbol,
        secType="STK",
        exchange="SMART",
        primaryExchange="NASDAQ",
    )


# =============================================================================
# TEST CASES FOR TICK SIZE VERIFICATION
# =============================================================================

# These test cases verify the tick size at different price levels
# Format: (price, expected_tick, description)
# SPX official: 0.05 below $3, 0.10 at/above $3
SPX_TICK_SIZE_TEST_CASES = [
    (0.50, 0.05, "SPX option below $3 should use 0.05 tick"),
    (1.00, 0.05, "SPX option at $1 should use 0.05 tick"),
    (2.99, 0.05, "SPX option just below $3 should use 0.05 tick"),
    (3.00, 0.10, "SPX option at exactly $3 should use 0.10 tick"),
    (3.01, 0.10, "SPX option just above $3 should use 0.10 tick"),
    (5.00, 0.10, "SPX option at $5 should use 0.10 tick"),
    (10.00, 0.10, "SPX option at $10 should use 0.10 tick"),
    (50.00, 0.10, "SPX option at $50 should use 0.10 tick"),
]

# This is the specific bug case: price >= $3 was incorrectly using 0.01
# The correct tick for SPX at $4.60 is 0.10 (not 0.01, not 0.05)
BUG_CASE_TICK_010 = (4.60, 0.10, "Price $4.60 MUST use 0.10 tick for SPX")
