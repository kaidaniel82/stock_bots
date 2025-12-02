"""TWS Broker - connects to Interactive Brokers TWS with real-time events."""
from dataclasses import dataclass, field
from datetime import datetime
from threading import Thread
from typing import Callable, Optional
import asyncio
from ib_insync import IB, Contract, Option, Stock, ComboLeg, PortfolioItem, Ticker, util

from .config import (
    TWS_HOST, TWS_PORT, TWS_CLIENT_ID,
    BROKER_UPDATE_INTERVAL, VERBOSE_PORTFOLIO_UPDATES, LOG_ONLY_CHANGES
)
from .logger import logger


@dataclass
class PortfolioPosition:
    """Position from TWS portfolio."""
    con_id: int
    symbol: str
    sec_type: str  # "STK", "OPT", "BAG" (combo), "FUT", etc.
    expiry: str
    strike: float
    right: str  # "C", "P", or ""
    quantity: float
    avg_cost: float
    market_price: float
    market_value: float
    unrealized_pnl: float
    # For combos
    is_combo: bool = False
    combo_legs: list = field(default_factory=list)
    # Raw contract for debugging
    raw_contract: Contract = None

    @property
    def display_name(self) -> str:
        if self.sec_type == "BAG":
            return f"{self.symbol} COMBO ({len(self.combo_legs)} legs)"
        elif self.sec_type == "OPT":
            return f"{self.symbol} {self.expiry} {self.strike}{self.right}"
        elif self.sec_type == "STK":
            return f"{self.symbol} Stock"
        else:
            return f"{self.symbol} {self.sec_type}"


class PriceCache:
    """Lock-free price cache for fast tick updates.

    Python GIL protects dict operations for single-writer pattern.
    """

    def __init__(self):
        self._prices: dict[int, float] = {}  # conId -> last price
        self._timestamps: dict[int, float] = {}  # conId -> timestamp

    def update(self, con_id: int, price: float) -> None:
        """Update price - MUST BE FAST (no logging here)."""
        self._prices[con_id] = price

    def get(self, con_id: int) -> float:
        """Get current price for conId."""
        return self._prices.get(con_id, 0.0)

    def get_many(self, con_ids: list[int]) -> list[float]:
        """Get prices for multiple conIds."""
        return [self._prices.get(cid, 0.0) for cid in con_ids]

    def has(self, con_id: int) -> bool:
        """Check if we have a price for this conId."""
        return con_id in self._prices


class MarketDataManager:
    """Manages reqMktData subscriptions for real-time tick updates."""

    def __init__(self, ib: IB, price_cache: PriceCache):
        self._ib = ib
        self._cache = price_cache
        self._subscriptions: dict[int, Ticker] = {}  # conId -> Ticker
        self._contracts: dict[int, Contract] = {}    # conId -> Contract
        self._on_price_callback: Optional[Callable[[int, float], None]] = None

    def set_price_callback(self, callback: Callable[[int, float], None]) -> None:
        """Set callback for price updates."""
        self._on_price_callback = callback

    def subscribe(self, con_id: int, contract: Contract) -> bool:
        """Subscribe to market data for a contract."""
        if con_id in self._subscriptions:
            return True  # Already subscribed

        try:
            # Fix: Set exchange from primaryExchange if not set
            if not contract.exchange and contract.primaryExchange:
                contract.exchange = contract.primaryExchange

            # Request mark price (221) explicitly
            ticker = self._ib.reqMktData(contract, '221', False, False)
            ticker.updateEvent += self._on_tick
            self._subscriptions[con_id] = ticker
            self._contracts[con_id] = contract
            logger.debug(f"Subscribed to market data: {contract.symbol} (conId={con_id})")
            return True
        except Exception as e:
            logger.error(f"Failed to subscribe market data for {contract.symbol}: {e}")
            return False

    def subscribe_all(self, positions: list[PortfolioPosition]) -> int:
        """Subscribe to market data for all positions. Returns count of subscriptions."""
        count = 0
        for pos in positions:
            if pos.raw_contract and self.subscribe(pos.con_id, pos.raw_contract):
                count += 1
        logger.info(f"Subscribed to {count} market data streams")
        return count

    def _on_tick(self, ticker: Ticker) -> None:
        """HOT PATH - Called on every tick. No logging here!"""
        con_id = ticker.contract.conId

        # Get best available price
        price = ticker.last or ticker.close or 0
        if price <= 0 and ticker.bid and ticker.ask:
            price = (ticker.bid + ticker.ask) / 2
        if price <= 0:
            return

        # Update cache (fast)
        self._cache.update(con_id, price)

        # Notify callback if set
        if self._on_price_callback:
            self._on_price_callback(con_id, price)

    def unsubscribe(self, con_id: int) -> None:
        """Unsubscribe from market data."""
        if con_id in self._subscriptions:
            ticker = self._subscriptions.pop(con_id)
            try:
                ticker.updateEvent -= self._on_tick
                self._ib.cancelMktData(ticker.contract)
            except Exception:
                pass
            self._contracts.pop(con_id, None)

    def unsubscribe_all(self) -> None:
        """Unsubscribe from all market data."""
        for con_id in list(self._subscriptions.keys()):
            self.unsubscribe(con_id)

    def get_subscription_count(self) -> int:
        """Get number of active subscriptions."""
        return len(self._subscriptions)

    def get_quote_data(self, con_id: int) -> dict:
        """Get full quote data (bid, ask, last, mid, mark, greeks) for a contract."""
        import math

        def safe_float(val) -> float:
            """Convert to float, handling nan/None."""
            if val is None:
                return 0.0
            try:
                f = float(val)
                return f if not math.isnan(f) else 0.0
            except (ValueError, TypeError):
                return 0.0

        def safe_greek(val) -> float:
            """Convert Greek to float, allowing negative values."""
            if val is None:
                return 0.0
            try:
                f = float(val)
                return f if not math.isnan(f) else 0.0
            except (ValueError, TypeError):
                return 0.0

        if con_id not in self._subscriptions:
            return {"bid": 0.0, "ask": 0.0, "last": 0.0, "mid": 0.0, "mark": 0.0,
                    "delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0}

        ticker = self._subscriptions[con_id]

        # Log raw ticker values for debugging
        from .logger import logger
        logger.debug(f"RAW ticker {ticker.contract.symbol}: bid={ticker.bid} ask={ticker.ask} last={ticker.last} mark={ticker.markPrice} close={ticker.close}")

        bid = safe_float(ticker.bid)
        ask = safe_float(ticker.ask)
        last = safe_float(ticker.last)
        mark = safe_float(ticker.markPrice)

        # Calculate mid if we have bid/ask
        mid = (bid + ask) / 2 if bid > 0 and ask > 0 else 0.0

        # If markPrice not available, use mid (same as TWS for options)
        if mark <= 0 and mid > 0:
            mark = mid

        # Get Greeks from modelGreeks (available for options)
        delta = 0.0
        gamma = 0.0
        theta = 0.0
        vega = 0.0
        if ticker.modelGreeks:
            delta = safe_greek(ticker.modelGreeks.delta)
            gamma = safe_greek(ticker.modelGreeks.gamma)
            theta = safe_greek(ticker.modelGreeks.theta)
            vega = safe_greek(ticker.modelGreeks.vega)

        return {"bid": bid, "ask": ask, "last": last, "mid": mid, "mark": mark,
                "delta": delta, "gamma": gamma, "theta": theta, "vega": vega}


class TWSBroker:
    """Broker connecting to TWS for real portfolio data with event-based updates."""

    def __init__(self, host: str = TWS_HOST, port: int = TWS_PORT, client_id: int = TWS_CLIENT_ID):
        self.host = host
        self.port = port
        self.client_id = client_id
        self.ib = IB()
        self._connected = False
        self._positions: dict[int, PortfolioPosition] = {}  # keyed by conId
        self._entry_prices: dict[int, float] = {}  # conId -> entry price from fills
        self._update_callbacks = []  # callbacks for position updates
        self._thread = None
        self._loop = None
        self._stop_requested = False

        # Performance: PriceCache + MarketDataManager
        self.price_cache = PriceCache()
        self._market_data: Optional[MarketDataManager] = None

    def _run_loop(self):
        """Run ib_insync event loop in separate thread."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

        try:
            logger.info(f"Connecting to TWS at {self.host}:{self.port} (client_id={self.client_id})")
            self.ib.connect(self.host, self.port, clientId=self.client_id)
            self._connected = True
            logger.success(f"Connected to TWS")

            # Initialize MarketDataManager
            self._market_data = MarketDataManager(self.ib, self.price_cache)
            logger.info("MarketDataManager initialized")

            # Wait for initial data to arrive
            self.ib.sleep(2.0)

            # Initial portfolio load
            self._fetch_portfolio()

            # Subscribe to market data for all positions
            if self._market_data and self._positions:
                count = self._market_data.subscribe_all(list(self._positions.values()))
                logger.info(f"Subscribed to {count} market data streams")

            # Load entry prices from recent executions
            self._load_entry_prices()

            # Run loop - poll portfolio frequently
            import time
            last_fetch = time.time()
            while self._connected and not self._stop_requested:
                self.ib.sleep(0.1)  # Process IB events

                if not self.ib.isConnected():
                    logger.warning("TWS connection lost")
                    self._connected = False
                    break

                # Fetch portfolio at interval
                now = time.time()
                if now - last_fetch >= BROKER_UPDATE_INTERVAL:
                    self._fetch_portfolio()
                    last_fetch = now

        except Exception as e:
            logger.error(f"TWS connection error: {e}")
            self._connected = False

        logger.info("TWS thread stopped")

    def _fetch_portfolio(self):
        """Fetch portfolio and process updates."""
        try:
            portfolio = self.ib.portfolio()
            logger.debug(f"Broker fetching: {len(portfolio) if portfolio else 0} positions")

            if not portfolio:
                return

            # Track which conIds we saw
            seen_ids = set()

            for item in portfolio:
                self._process_portfolio_item(item)
                seen_ids.add(item.contract.conId)

            # Remove positions that are no longer in portfolio
            removed = [cid for cid in self._positions if cid not in seen_ids]
            for cid in removed:
                logger.info(f"Position removed: {self._positions[cid].symbol}")
                del self._positions[cid]

        except Exception as e:
            logger.error(f"Error fetching portfolio: {e}")

    def _process_portfolio_item(self, item):
        """Process a single portfolio item."""
        contract = item.contract

        # Check if this is new or changed
        existing = self._positions.get(contract.conId)
        is_changed = not existing or existing.market_price != item.marketPrice
        is_new = existing is None

        # Build combo legs
        is_combo = contract.secType == "BAG"
        combo_legs = []
        if is_combo and hasattr(contract, 'comboLegs') and contract.comboLegs:
            for leg in contract.comboLegs:
                combo_legs.append({
                    "con_id": leg.conId,
                    "ratio": leg.ratio,
                    "action": leg.action,
                })

        # Always update position
        pos = PortfolioPosition(
            con_id=contract.conId,
            symbol=contract.symbol,
            sec_type=contract.secType,
            expiry=getattr(contract, 'lastTradeDateOrContractMonth', ''),
            strike=getattr(contract, 'strike', 0.0),
            right=getattr(contract, 'right', ''),
            quantity=item.position,
            avg_cost=item.averageCost,
            market_price=item.marketPrice,
            market_value=item.marketValue,
            unrealized_pnl=item.unrealizedPNL,
            is_combo=is_combo,
            combo_legs=combo_legs,
            raw_contract=contract,
        )
        self._positions[contract.conId] = pos

        # Subscribe new positions to market data automatically
        if is_new and self._market_data and pos.raw_contract:
            if self._market_data.subscribe(contract.conId, pos.raw_contract):
                logger.info(f"Subscribed new position to market data: {contract.symbol} (conId={contract.conId})")

        # Log if enabled - always log first position for debugging
        if VERBOSE_PORTFOLIO_UPDATES:
            if not LOG_ONLY_CHANGES or is_changed or is_new:
                status = "NEW" if is_new else "UPD"
                msg = f"{status} {contract.symbol} {contract.secType}"
                if contract.secType in ("OPT", "FOP"):
                    msg += f" {contract.lastTradeDateOrContractMonth} {contract.strike}{contract.right}"
                if is_combo:
                    msg += f" COMBO({len(combo_legs)} legs)"
                msg += f" qty={item.position} price=${item.marketPrice:.2f} value=${item.marketValue:.2f} pnl=${item.unrealizedPNL:.2f}"
                logger.debug(msg)

    def connect(self) -> bool:
        """Connect to TWS in background thread."""
        if self._connected:
            logger.warning("Already connected")
            return True

        self._stop_requested = False

        if self._thread is None or not self._thread.is_alive():
            self._thread = Thread(target=self._run_loop, daemon=True)
            self._thread.start()

            # Wait a bit for connection
            import time
            for _ in range(30):  # Wait up to 3 seconds
                time.sleep(0.1)
                if self._connected:
                    return True

        return self._connected

    def disconnect(self):
        """Disconnect from TWS."""
        if self._connected:
            logger.info("Disconnecting from TWS...")
            self._stop_requested = True
            try:
                self.ib.disconnect()
            except Exception as e:
                logger.error(f"Error disconnecting: {e}")
            self._connected = False
            self._positions.clear()
            logger.success("Disconnected from TWS")

    def is_connected(self) -> bool:
        return self._connected and self.ib.isConnected()

    def load_portfolio(self) -> list[PortfolioPosition]:
        """Initial portfolio load."""
        if not self.is_connected():
            logger.warning("Not connected to TWS")
            return []

        # Wait for positions to load
        import time
        time.sleep(0.3)

        return list(self._positions.values())

    def get_positions(self) -> list[PortfolioPosition]:
        """Get current positions."""
        return list(self._positions.values())

    def get_quote(self, con_id: int) -> float:
        """Get current market price for a position."""
        # First try PriceCache (fastest, from reqMktData ticks)
        cached = self.price_cache.get(con_id)
        if cached > 0:
            return cached
        # Fallback to portfolio price
        pos = self._positions.get(con_id)
        return pos.market_price if pos else 0.0

    def _load_entry_prices(self):
        """Load entry prices from recent executions (7 day history)."""
        try:
            self.ib.sleep(0.1)
            self.ib.reqExecutions()
            self.ib.sleep(0.2)
            fills = self.ib.fills()

            if fills:
                for fill in fills:
                    con_id = fill.contract.conId
                    # Store the fill price as entry price
                    self._entry_prices[con_id] = fill.execution.price
                logger.info(f"Loaded {len(fills)} entry prices from executions")
            else:
                logger.info("No recent executions found for entry prices")
        except Exception as e:
            logger.error(f"Error loading entry prices: {e}")

    def get_entry_price(self, con_id: int) -> float:
        """Get entry price for a position (from recent fills)."""
        return self._entry_prices.get(con_id, 0.0)

    def get_all_entry_prices(self) -> dict[int, float]:
        """Get all entry prices."""
        return dict(self._entry_prices)

    def tick(self):
        """No-op, events are handled by background thread."""
        pass

    def get_quote_data(self, con_id: int) -> dict:
        """Get full quote data (bid, ask, last, mid) for a contract."""
        if self._market_data:
            return self._market_data.get_quote_data(con_id)
        return {"bid": 0.0, "ask": 0.0, "last": 0.0, "mid": 0.0}


# Global broker instance
BROKER = TWSBroker()
