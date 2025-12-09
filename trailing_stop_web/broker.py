"""TWS Broker - connects to Interactive Brokers TWS with real-time events."""
from dataclasses import dataclass, field
from datetime import datetime
from threading import Thread
from typing import Callable, Optional
import asyncio
import logging
from pathlib import Path
from ib_insync import IB, Contract, Option, Stock, Index, Future, ComboLeg, PortfolioItem, Ticker, util, Order, Trade
import uuid

# Enable ib_insync debug logging to file
IB_LOG_FILE = Path.home() / ".trailing_stop_web" / "ib_insync.log"
IB_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
util.logToFile(str(IB_LOG_FILE), level=logging.DEBUG)

from .config import (
    TWS_HOST, TWS_PORT, TWS_CLIENT_ID,
    BROKER_UPDATE_INTERVAL, VERBOSE_PORTFOLIO_UPDATES, LOG_ONLY_CHANGES,
    RECONNECT_INITIAL_DELAY, RECONNECT_MAX_DELAY, RECONNECT_BACKOFF_FACTOR, RECONNECT_MAX_ATTEMPTS
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
    # Exchange for order routing (from contract)
    exchange: str = "SMART"
    # Trading hours info (from ContractDetails)
    trading_hours: str = ""  # Raw string from TWS
    liquid_hours: str = ""   # Liquid hours from TWS
    time_zone_id: str = ""   # e.g. "US/Eastern"

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

        # Reconnection state
        self._reconnect_attempt = 0
        self._reconnect_delay = RECONNECT_INITIAL_DELAY
        self._auto_reconnect = True
        self._connection_status_callback: Optional[Callable[[str], None]] = None

        # Trading hours cache: {symbol: {date: str, trading_hours: str, liquid_hours: str, time_zone_id: str}}
        # Cached per symbol (not per position) and invalidated on date change or at midnight
        self._trading_hours_cache: dict[str, dict] = {}
        self._last_cache_date: str = ""  # Track date for midnight cache clear

        # Market rules cache: {(conId, exchange): [PriceIncrement, ...]}
        # Stores tick size rules loaded from reqMarketRule() for each contract
        # Used by _get_price_increment() to determine correct tick size at any price level
        self._market_rules_cache: dict[tuple[int, str], list] = {}

    def _run_loop(self):
        """Run ib_insync event loop in separate thread with reconnection support."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

        while not self._stop_requested:
            try:
                if self._attempt_connection():
                    self._run_connected_loop()

                # If we get here, connection was lost
                if not self._stop_requested and self._auto_reconnect:
                    self._handle_reconnection()
                else:
                    break

            except Exception as e:
                logger.error(f"TWS connection error: {e}")
                self._connected = False
                if not self._stop_requested and self._auto_reconnect:
                    self._handle_reconnection()
                else:
                    break

        logger.info("TWS thread stopped")

    def _attempt_connection(self) -> bool:
        """Attempt to connect to TWS. Returns True if successful."""
        import time

        attempt_str = f" (attempt {self._reconnect_attempt + 1})" if self._reconnect_attempt > 0 else ""
        status = f"Connecting{attempt_str}..."
        self._notify_status(status)
        logger.info(f"Connecting to TWS at {self.host}:{self.port}{attempt_str}")

        try:
            self.ib.connect(self.host, self.port, clientId=self.client_id)
            self._connected = True
            self._reconnect_attempt = 0
            self._reconnect_delay = RECONNECT_INITIAL_DELAY
            self._notify_status("Connected")
            logger.success("Connected to TWS")

            # Register error event handler to capture TWS error messages
            def on_error(reqId, errorCode, errorString, contract):
                logger.warning(f"TWS Error [{errorCode}]: {errorString} (reqId={reqId}, contract={contract})")
            self.ib.errorEvent += on_error

            # Clear trading hours cache on connect (force refresh)
            self._trading_hours_cache.clear()
            self._last_cache_date = datetime.now().strftime('%Y%m%d')
            logger.debug("Trading hours cache cleared on connect")

            # Initialize/reinitialize MarketDataManager
            self._market_data = MarketDataManager(self.ib, self.price_cache)
            logger.info("MarketDataManager initialized")

            # Wait for initial data
            self.ib.sleep(2.0)

            # Fetch portfolio
            self._fetch_portfolio()

            # Pre-load market rules for tick sizes (must happen in sync context)
            self._preload_market_rules()

            # Re-subscribe to market data for all positions
            if self._market_data and self._positions:
                count = self._market_data.subscribe_all(list(self._positions.values()))
                logger.info(f"Subscribed to {count} market data streams")

            # Load entry prices
            self._load_entry_prices()

            return True

        except Exception as e:
            logger.error(f"Connection attempt failed: {e}")
            self._connected = False
            return False

    def _check_midnight_cache_clear(self):
        """Clear trading hours cache at midnight (date change)."""
        today = datetime.now().strftime('%Y%m%d')
        if self._last_cache_date and self._last_cache_date != today:
            self._trading_hours_cache.clear()
            logger.info(f"Trading hours cache cleared at midnight (new day: {today})")
        self._last_cache_date = today

    def _run_connected_loop(self):
        """Main loop while connected - monitors connection and fetches data."""
        import time
        last_fetch = time.time()

        while self._connected and not self._stop_requested:
            self.ib.sleep(0.1)  # Process IB events

            if not self.ib.isConnected():
                logger.warning("TWS connection lost")
                self._connected = False
                self._notify_status("Connection lost")
                break

            # Check for midnight and clear trading hours cache
            self._check_midnight_cache_clear()

            # Fetch portfolio at interval
            now = time.time()
            if now - last_fetch >= BROKER_UPDATE_INTERVAL:
                self._fetch_portfolio()
                last_fetch = now

    def _handle_reconnection(self):
        """Handle reconnection with exponential backoff."""
        import time

        self._reconnect_attempt += 1
        delay = min(self._reconnect_delay, RECONNECT_MAX_DELAY)

        # Check max attempts (0 = unlimited)
        if RECONNECT_MAX_ATTEMPTS > 0 and self._reconnect_attempt > RECONNECT_MAX_ATTEMPTS:
            logger.error(f"Max reconnection attempts ({RECONNECT_MAX_ATTEMPTS}) reached")
            self._notify_status("Reconnection failed - max attempts")
            self._stop_requested = True
            return

        logger.info(f"Reconnecting in {delay}s (attempt {self._reconnect_attempt})...")

        # Wait with countdown (check stop_requested periodically)
        start = time.time()
        while time.time() - start < delay:
            if self._stop_requested:
                return
            remaining = int(delay - (time.time() - start))
            self._notify_status(f"Reconnecting in {remaining}s...")
            time.sleep(1)

        # Disconnect cleanly before reconnecting
        try:
            self.ib.disconnect()
        except Exception:
            pass

        # Create new IB instance for clean reconnect
        self.ib = IB()

        # Update backoff delay for next attempt
        self._reconnect_delay = min(
            self._reconnect_delay * RECONNECT_BACKOFF_FACTOR,
            RECONNECT_MAX_DELAY
        )

    def _notify_status(self, status: str) -> None:
        """Notify status change via callback."""
        if self._connection_status_callback:
            try:
                self._connection_status_callback(status)
            except Exception as e:
                logger.error(f"Status callback error: {e}")

    def set_connection_status_callback(self, callback: Callable[[str], None]) -> None:
        """Set callback for connection status changes."""
        self._connection_status_callback = callback

    def request_reconnect(self) -> None:
        """Request manual reconnection (can be called from UI)."""
        if self._connected:
            logger.info("Already connected, ignoring reconnect request")
            return

        logger.info("Manual reconnect requested")
        self._reconnect_attempt = 0
        self._reconnect_delay = RECONNECT_INITIAL_DELAY
        self._stop_requested = False
        self._auto_reconnect = True

        if self._thread is None or not self._thread.is_alive():
            self._thread = Thread(target=self._run_loop, daemon=True)
            self._thread.start()

    def _fetch_portfolio(self):
        """Fetch portfolio and process updates."""
        try:
            portfolio = self.ib.portfolio()
            # Log all position conIds for debugging
            if portfolio:
                con_ids = [item.contract.conId for item in portfolio]
                logger.debug(f"Broker fetching: {len(portfolio)} positions, conIds: {con_ids}")

            # Track which conIds we saw (empty set if no portfolio)
            seen_ids = set()

            if portfolio:
                for item in portfolio:
                    self._process_portfolio_item(item)
                    seen_ids.add(item.contract.conId)

            # Remove positions that are no longer in portfolio
            # This also handles the case when portfolio becomes empty
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

        # Determine exchange for order routing (prefer primaryExchange)
        position_exchange = contract.primaryExchange or contract.exchange or "SMART"

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
            exchange=position_exchange,
        )
        self._positions[contract.conId] = pos

        # Subscribe new positions to market data automatically
        if is_new and self._market_data and pos.raw_contract:
            if self._market_data.subscribe(contract.conId, pos.raw_contract):
                logger.info(f"Subscribed new position to market data: {contract.symbol} (conId={contract.conId})")

        # Fetch trading hours for new positions (independent of market data)
        if is_new and pos.raw_contract:
            self._fetch_trading_hours(contract.conId, contract)

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
        self._auto_reconnect = True  # Enable auto-reconnect on connect
        self._reconnect_attempt = 0
        self._reconnect_delay = RECONNECT_INITIAL_DELAY

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

    def _fetch_trading_hours(self, con_id: int, contract: Contract):
        """Fetch trading hours for a contract from TWS ContractDetails.

        Uses a cache per symbol+secType to avoid repeated API calls. Cache is invalidated
        when the date changes (to handle day transitions correctly).

        Cache key is symbol_secType (e.g. "TSLA_STK", "TSLA_OPT") because:
        - Stocks and options on same underlying can have different trading hours
        - All options on same underlying share the same trading hours
        """
        cache_key = f"{contract.symbol}_{contract.secType}"
        today = datetime.now().strftime('%Y%m%d')

        # Check cache first
        cached = self._trading_hours_cache.get(cache_key)
        if cached and cached.get('date') == today:
            # Use cached data
            pos = self._positions.get(con_id)
            if pos:
                pos.trading_hours = cached.get('trading_hours', '')
                pos.liquid_hours = cached.get('liquid_hours', '')
                pos.time_zone_id = cached.get('time_zone_id', '')
                logger.debug(f"Trading hours for {cache_key}: tz={pos.time_zone_id} (cached)")
            return

        # Fetch from TWS
        try:
            details = self.ib.reqContractDetails(contract)
            if details:
                detail = details[0]
                trading_hours = getattr(detail, 'tradingHours', '') or ''
                liquid_hours = getattr(detail, 'liquidHours', '') or ''
                time_zone_id = getattr(detail, 'timeZoneId', '') or ''

                logger.debug(f"Trading hours for {cache_key}: tz={time_zone_id}")

                # Update cache
                self._trading_hours_cache[cache_key] = {
                    'date': today,
                    'trading_hours': trading_hours,
                    'liquid_hours': liquid_hours,
                    'time_zone_id': time_zone_id,
                }

                # Update position
                pos = self._positions.get(con_id)
                if pos:
                    pos.trading_hours = trading_hours
                    pos.liquid_hours = liquid_hours
                    pos.time_zone_id = time_zone_id
        except Exception as e:
            logger.debug(f"Could not fetch trading hours for {cache_key}: {e}")

    def is_market_open(self, con_id: int) -> bool:
        """Check if market is currently open for this contract.

        Uses trading hours from ContractDetails if available,
        otherwise falls back to heuristic (bid/ask > 0).
        """
        from datetime import datetime
        import pytz

        pos = self._positions.get(con_id)
        if not pos:
            return False

        # If trading hours missing, try to apply from cache
        if not pos.trading_hours and pos.raw_contract:
            cache_key = f"{pos.symbol}_{pos.raw_contract.secType}"
            today = datetime.now().strftime('%Y%m%d')
            cached = self._trading_hours_cache.get(cache_key)
            if cached and cached.get('date') == today:
                pos.trading_hours = cached.get('trading_hours', '')
                pos.liquid_hours = cached.get('liquid_hours', '')
                pos.time_zone_id = cached.get('time_zone_id', '')

        # If we have trading hours, parse them
        if pos.trading_hours and pos.time_zone_id:
            try:
                tz = pytz.timezone(pos.time_zone_id)
                now = datetime.now(tz)

                # Parse trading hours format: "20241204:0930-20241204:1600;20241205:0930-..."
                for session in pos.trading_hours.split(';'):
                    if 'CLOSED' in session or not session.strip():
                        continue
                    # Parse session: "20241204:0930-20241204:1600"
                    if '-' in session:
                        start_str, end_str = session.split('-')
                        start = datetime.strptime(start_str, '%Y%m%d:%H%M')
                        end = datetime.strptime(end_str, '%Y%m%d:%H%M')
                        start = tz.localize(start)
                        end = tz.localize(end)
                        if start <= now <= end:
                            logger.info(f"[MARKET] {pos.symbol}: OPEN via TradingHours (tz={pos.time_zone_id})")
                            return True
                logger.info(f"[MARKET] {pos.symbol}: CLOSED via TradingHours")
                return False
            except Exception as e:
                logger.debug(f"Error parsing trading hours: {e}")

        # Fallback: Check if bid/ask are valid
        quote = self.get_quote_data(con_id)
        is_open = quote.get('bid', 0) > 0 and quote.get('ask', 0) > 0
        logger.info(f"[MARKET] {pos.symbol}: {'OPEN' if is_open else 'CLOSED'} via FALLBACK (bid/ask)")
        return is_open

    def get_market_status(self, con_id: int) -> str:
        """Get human-readable market status for a contract.

        Returns: "Open", "Closed", or "Unknown"

        Note: is_market_open() uses cached trading hours (loaded once per day)
        but checks current time against those hours on every call.
        This is efficient - no API calls, just time comparison.
        """
        pos = self._positions.get(con_id)
        if not pos:
            return "Unknown"

        if self.is_market_open(con_id):
            return "Open"

        return "Closed"

    def disconnect(self):
        """Disconnect from TWS and stop reconnection attempts."""
        logger.info("Disconnecting from TWS...")
        self._stop_requested = True
        self._auto_reconnect = False  # Disable auto-reconnect on manual disconnect

        # Unsubscribe from market data
        if self._market_data:
            self._market_data.unsubscribe_all()

        try:
            self.ib.disconnect()
        except Exception as e:
            logger.error(f"Error disconnecting: {e}")

        self._connected = False
        self._notify_status("Disconnected")
        # Note: We keep _positions for state preservation during reconnect attempts
        # Only clear when explicitly disconnected by user
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

        # Fetch trading hours for all positions that don't have them
        for con_id, pos in self._positions.items():
            if not pos.trading_hours and pos.raw_contract:
                self._fetch_trading_hours(con_id, pos.raw_contract)

        # Pre-load market rules for all positions (needed for tick sizes)
        # This must happen here during sync load, not during async order placement
        self._preload_market_rules()

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
        """Load entry prices from recent executions (7 day history).

        Only considers OPENING trades (BUY for long, SELL for short).
        Uses weighted average if multiple opening fills exist.
        """
        try:
            self.ib.sleep(0.1)
            self.ib.reqExecutions()
            self.ib.sleep(0.2)
            fills = self.ib.fills()

            if not fills:
                logger.info("No recent executions found for entry prices")
                return

            # Group fills by contract and calculate weighted average for opening trades
            # Key: con_id -> {"buys": [(qty, price), ...], "sells": [(qty, price), ...]}
            fill_data: dict[int, dict] = {}

            for fill in fills:
                con_id = fill.contract.conId
                action = fill.execution.side  # "BOT" or "SLD"
                qty = fill.execution.shares
                price = fill.execution.price

                if con_id not in fill_data:
                    fill_data[con_id] = {"buys": [], "sells": []}

                if action == "BOT":
                    fill_data[con_id]["buys"].append((qty, price))
                else:  # SLD
                    fill_data[con_id]["sells"].append((qty, price))

            # For each position, determine entry price based on current position
            for con_id, data in fill_data.items():
                pos = self._positions.get(con_id)
                if not pos:
                    continue

                # Determine which fills are "opening" based on position direction
                if pos.quantity > 0:
                    # Long position - BUY fills are opening trades
                    opening_fills = data["buys"]
                else:
                    # Short position - SELL fills are opening trades
                    opening_fills = data["sells"]

                if opening_fills:
                    # Calculate weighted average price from opening fills
                    total_qty = sum(qty for qty, _ in opening_fills)
                    total_value = sum(qty * price for qty, price in opening_fills)
                    if total_qty > 0:
                        avg_price = total_value / total_qty
                        self._entry_prices[con_id] = avg_price
                        logger.debug(f"Entry price for {con_id}: ${avg_price:.2f} "
                                    f"(from {len(opening_fills)} fills, {total_qty} shares)")
                else:
                    # Fallback: use avg_cost from portfolio if no opening fills found
                    # This handles cases where fills are older than 7 days
                    multiplier = 1
                    if pos.raw_contract and hasattr(pos.raw_contract, 'multiplier') and pos.raw_contract.multiplier:
                        try:
                            multiplier = int(pos.raw_contract.multiplier)
                        except (ValueError, TypeError):
                            multiplier = 100 if pos.sec_type in ("OPT", "FOP") else 1
                    else:
                        multiplier = 100 if pos.sec_type in ("OPT", "FOP") else 1

                    avg_price = pos.avg_cost / multiplier if multiplier > 0 else pos.avg_cost
                    self._entry_prices[con_id] = avg_price
                    logger.debug(f"Entry price for {con_id}: ${avg_price:.2f} (from avg_cost fallback)")

            # Also add positions without any fills (using avg_cost fallback)
            for con_id, pos in self._positions.items():
                if con_id not in self._entry_prices:
                    multiplier = 1
                    if pos.raw_contract and hasattr(pos.raw_contract, 'multiplier') and pos.raw_contract.multiplier:
                        try:
                            multiplier = int(pos.raw_contract.multiplier)
                        except (ValueError, TypeError):
                            multiplier = 100 if pos.sec_type in ("OPT", "FOP") else 1
                    else:
                        multiplier = 100 if pos.sec_type in ("OPT", "FOP") else 1

                    avg_price = pos.avg_cost / multiplier if multiplier > 0 else pos.avg_cost
                    self._entry_prices[con_id] = avg_price
                    logger.debug(f"Entry price for {con_id}: ${avg_price:.2f} (avg_cost, no fills)")

            logger.info(f"Loaded entry prices for {len(self._entry_prices)} positions")
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

    # =========================================================================
    # ORDER PLACEMENT
    # =========================================================================

    def create_oca_group_id(self, group_name: str) -> str:
        """Generate unique OCA group identifier."""
        return f"TSM_{group_name}_{uuid.uuid4().hex[:8]}"

    def build_combo_contract(self, position_quantities: dict[int, int], invert_leg_actions: bool = False) -> Optional[Contract]:
        """Build BAG (combo) contract from multiple positions.

        Args:
            position_quantities: {con_id: quantity} mapping
            invert_leg_actions: If True, invert leg actions (for SELL order on BAG)

        Returns:
            Contract object for the combo, or None if failed
        """
        if not position_quantities:
            logger.error("No positions provided for combo contract")
            return None

        # Log available vs requested positions for debugging
        available_ids = list(self._positions.keys())
        requested_ids = list(position_quantities.keys())
        logger.debug(f"build_combo_contract: requested={requested_ids}, available={available_ids}")

        if len(position_quantities) == 1:
            # Single leg - return the position's contract
            con_id = list(position_quantities.keys())[0]
            print(f"[BROKER] Single-leg: looking for con_id={con_id} (type={type(con_id)})")
            print(f"[BROKER] Available positions: {list(self._positions.keys())}")
            pos = self._positions.get(con_id)
            if pos and pos.raw_contract:
                contract = pos.raw_contract
                # Ensure exchange is set (required for orders)
                if not contract.exchange and contract.primaryExchange:
                    contract.exchange = contract.primaryExchange
                elif not contract.exchange:
                    contract.exchange = "SMART"
                print(f"[BROKER] Found single-leg contract: {contract.localSymbol} conId={con_id} exchange={contract.exchange}")
                logger.debug(f"Using single-leg contract: {contract.localSymbol} conId={con_id}")
                return contract
            print(f"[BROKER] ERROR: Position {con_id} not found! pos={pos}")
            logger.error(f"Position {con_id} not found in available positions: {available_ids}")
            return None

        # Multi-leg combo
        combo_legs = []
        symbol = None
        exchange = None  # Will be determined from first leg's position

        for con_id, qty in position_quantities.items():
            pos = self._positions.get(con_id)
            if not pos:
                logger.error(f"Position {con_id} not found")
                return None

            if symbol is None:
                symbol = pos.symbol
                # Get exchange from position (set during portfolio load)
                exchange = pos.exchange or "SMART"
                logger.debug(f"Using exchange from position: {exchange}")
            elif pos.symbol != symbol:
                logger.error(f"All legs must have same underlying: {symbol} vs {pos.symbol}")
                return None

            # Determine action based on position sign (closing the position)
            # If we're long (qty > 0), we SELL to close
            # If we're short (qty < 0), we BUY to close
            #
            # IMPORTANT: If order action is SELL (for debit spread), IBKR inverts
            # all leg actions. So we pre-invert them here to get correct behavior.
            if invert_leg_actions:
                # For SELL order: invert leg actions
                action = "BUY" if qty > 0 else "SELL"
            else:
                # For BUY order: normal leg actions
                action = "SELL" if qty > 0 else "BUY"

            # Use the determined exchange for all legs
            leg = ComboLeg(
                conId=con_id,
                ratio=abs(qty),
                action=action,
                exchange=exchange
            )
            combo_legs.append(leg)
            logger.info(f"ComboLeg: conId={con_id} qty={qty} ratio={abs(qty)} action={action} exchange={exchange}")

        combo = Contract(
            secType="BAG",
            symbol=symbol,
            exchange=exchange,
            currency="USD",
            comboLegs=combo_legs
        )

        return combo

    def place_trailing_stop_order(
        self,
        contract: Contract,
        quantity: int,
        trail_amount: float,
        trail_mode: str,  # "percent" or "absolute"
        stop_type: str,   # "market" or "limit"
        limit_offset: float,
        oca_group: str,
        action: str = "SELL",  # SELL to close long, BUY to close short
        initial_stop_price: float = 0.0  # Required for TRAIL LIMIT
    ) -> Optional[Trade]:
        """Place a trailing stop order.

        Args:
            contract: Contract or BAG contract for combo
            quantity: Total quantity to trade
            trail_amount: Trail value (percent or absolute)
            trail_mode: "percent" or "absolute"
            stop_type: "market" for TRAIL or "limit" for TRAIL LIMIT
            limit_offset: Offset for limit orders
            oca_group: OCA group identifier
            action: "SELL" or "BUY"
            initial_stop_price: Initial stop price (required for TRAIL LIMIT)

        Returns:
            Trade object or None if failed
        """
        if not self.is_connected():
            logger.error("Cannot place order: not connected")
            return None

        try:
            order = Order()
            order.action = action
            order.totalQuantity = abs(quantity)
            order.transmit = True

            # OCA group settings
            order.ocaGroup = oca_group
            order.ocaType = 1  # Cancel all remaining on fill

            if trail_mode == "percent":
                order.orderType = "TRAIL" if stop_type == "market" else "TRAIL LIMIT"
                order.trailingPercent = trail_amount
                if stop_type == "limit":
                    order.lmtPriceOffset = limit_offset
                    if initial_stop_price > 0:
                        order.trailStopPrice = initial_stop_price
            else:  # absolute
                order.orderType = "TRAIL" if stop_type == "market" else "TRAIL LIMIT"
                order.auxPrice = trail_amount  # Trail amount in dollars
                if stop_type == "limit":
                    order.lmtPriceOffset = limit_offset
                    if initial_stop_price > 0:
                        order.trailStopPrice = initial_stop_price

            trade = self.ib.placeOrder(contract, order)

            logger.info(f"Placed trailing stop: orderId={trade.order.orderId} "
                       f"type={order.orderType} trail={trail_amount} mode={trail_mode}")

            return trade

        except Exception as e:
            logger.error(f"Failed to place trailing stop: {e}")
            return None

    # ==========================================================================
    # TRIGGER METHOD MAPPING
    # ==========================================================================

    # Map UI trigger_price_type to IB triggerMethod for stop orders
    # See: https://interactivebrokers.github.io/tws-api/trigger_method_limit.html
    TRIGGER_METHOD_MAP = {
        "mark": 0,    # Default (IB decides based on instrument)
        "mid": 8,     # Mid-point
        "bid": 4,     # Bid/Ask
        "ask": 4,     # Bid/Ask
        "last": 2,    # Last price
    }

    def get_trigger_method(self, trigger_price_type: str) -> int:
        """Map UI trigger price type to IB triggerMethod.

        Args:
            trigger_price_type: "mark", "mid", "bid", "ask", or "last"

        Returns:
            IB triggerMethod value (0=default, 2=last, 4=bid/ask, 8=mid)
        """
        return self.TRIGGER_METHOD_MAP.get(trigger_price_type, 0)

    # ==========================================================================
    # APP-CONTROLLED STOP ORDERS (replaces TWS-native TRAIL orders for combos)
    # ==========================================================================

    def _preload_market_rules(self):
        """Pre-load market rules for all positions during sync load.

        This is called from load_portfolio() and _attempt_connection() to ensure
        market rules are cached BEFORE order placement. The reqContractDetails/
        reqMarketRule calls can't run during async handlers (event loop conflict).

        Market rules define price increments (tick sizes) that can vary by price level.
        For example, SPX options use 0.05 tick for prices >= $3.00, but 0.01 below.

        The cache stores either:
        - Full market rules from reqMarketRule() (list of PriceIncrement objects)
        - Fallback minTick from ContractDetails if rules unavailable (single-element list)
        """
        logger.info(f"Pre-loading market rules for {len(self._positions)} positions...")
        loaded = 0
        fallback_count = 0

        for con_id, pos in self._positions.items():
            if not pos.raw_contract:
                continue

            contract = pos.raw_contract
            cache_key = (contract.conId, contract.exchange or "SMART")

            # Skip if already cached
            if cache_key in self._market_rules_cache:
                continue

            try:
                details = self.ib.reqContractDetails(contract)
                if not details:
                    logger.debug(f"No contract details for {contract.symbol} {contract.secType}")
                    continue

                cd = details[0]

                # Extract minTick as fallback (always available in ContractDetails)
                min_tick = getattr(cd, 'minTick', 0.01) or 0.01

                # Try to get full market rules for price-dependent tick sizes
                exchanges = (cd.validExchanges or "").split(",")
                rule_ids = (cd.marketRuleIds or "").split(",")

                # Find the rule ID for our exchange (positional mapping)
                exchange = contract.exchange or "SMART"
                rule_id_to_use = None

                if exchange in exchanges:
                    idx = exchanges.index(exchange)
                    if idx < len(rule_ids) and rule_ids[idx]:
                        try:
                            rule_id_to_use = int(rule_ids[idx])
                        except ValueError:
                            pass

                # Fallback: use first rule if exchange not found
                if rule_id_to_use is None and rule_ids and rule_ids[0]:
                    try:
                        rule_id_to_use = int(rule_ids[0])
                    except ValueError:
                        pass

                if rule_id_to_use is not None:
                    rule = self.ib.reqMarketRule(rule_id_to_use)
                    if rule:
                        self._market_rules_cache[cache_key] = rule
                        loaded += 1
                        # Log actual tick sizes from the rule
                        tick_info = ", ".join(f"≥${r.lowEdge}→{r.increment}" for r in rule[:3])
                        if len(rule) > 3:
                            tick_info += f", ...({len(rule)} levels)"
                        logger.info(f"[TICK] {contract.symbol} {contract.secType}: {tick_info}")
                    else:
                        # reqMarketRule returned empty - use minTick fallback
                        self._market_rules_cache[cache_key] = self._create_fallback_rule(min_tick)
                        fallback_count += 1
                        logger.debug(f"[TICK] {contract.symbol}: market rule empty, using minTick={min_tick}")
                else:
                    # No rule ID found - use minTick fallback
                    self._market_rules_cache[cache_key] = self._create_fallback_rule(min_tick)
                    fallback_count += 1
                    logger.debug(f"[TICK] {contract.symbol}: no rule ID, using minTick={min_tick}")

            except Exception as e:
                logger.warning(f"Failed to load market rule for {contract.symbol}: {e}")

        logger.info(f"Pre-loaded {loaded} market rules ({fallback_count} using minTick fallback)")

    def _create_fallback_rule(self, min_tick: float) -> list:
        """Create a fallback market rule using minTick from ContractDetails.

        Returns a list with a single SimpleNamespace object that mimics
        the PriceIncrement structure from reqMarketRule().
        """
        from types import SimpleNamespace
        return [SimpleNamespace(lowEdge=0.0, increment=min_tick)]

    def _get_price_increment(self, contract: Contract, price: float) -> float:
        """Get price increment for a contract at a given price using MarketRules.

        The tick size can vary based on the price level (e.g., SPX options have
        different increments for prices above/below $3).

        According to IB docs: marketRuleIds and validExchanges are positionally mapped.
        marketRuleIds[n] corresponds to validExchanges[n].

        Args:
            contract: IB Contract
            price: Current price to determine increment for

        Returns:
            Price increment (e.g., 0.01, 0.05, 0.10)
        """
        default_tick = 0.01

        # BAG (combo) contracts: get tick from first leg (no fallback - must read from contract)
        if contract.secType == "BAG":
            if contract.comboLegs:
                first_leg_id = contract.comboLegs[0].conId
                pos = self._positions.get(first_leg_id)
                if pos and pos.raw_contract:
                    logger.debug(f"BAG contract: getting tick from first leg {first_leg_id}")
                    return self._get_price_increment(pos.raw_contract, price)
            logger.warning(f"BAG contract {contract.symbol}: could not get tick from legs!")
            return default_tick

        cache_key = (contract.conId, contract.exchange or "SMART")

        # Use pre-loaded cache only (no API calls during async handlers)
        # Market rules are loaded in _preload_market_rules() during load_portfolio()
        rule = self._market_rules_cache.get(cache_key, [])

        if not rule:
            # Cache miss - market rules weren't pre-loaded for this contract
            logger.warning(f"No cached market rules for {contract.symbol} {contract.secType} "
                          f"conId={contract.conId} - using default tick")
            return default_tick

        # Find increment for this price level
        increment = default_tick
        for price_rule in rule:
            if price_rule.lowEdge <= price:
                increment = float(price_rule.increment)
            else:
                break

        logger.debug(f"[TICK] {contract.symbol} {contract.secType} at ${price:.2f}: increment={increment}")
        return increment

    def _get_min_tick(self, contract: Contract) -> float:
        """Get minTick (fallback, uses default price of 10).

        For backwards compatibility. Prefer _get_price_increment() with actual price.
        """
        return self._get_price_increment(contract, 10.0)

    def _round_to_tick(self, price: float, increment: float) -> float:
        """Round price to valid tick size, preserving sign.

        Args:
            price: Price to round (can be negative for credit spreads)
            increment: Price increment

        Returns:
            Rounded price with preserved sign
        """
        if increment <= 0:
            increment = 0.01  # Fallback

        # Preserve sign for negative prices (credit spreads)
        sign = 1 if price >= 0 else -1
        return sign * round(abs(price) / increment) * increment

    def place_stop_order(
        self,
        contract: Contract,
        quantity: int,
        stop_price: float,
        limit_price: float = 0.0,  # 0 = Stop-Market, >0 = Stop-Limit
        oca_group: str = "",
        action: str = "SELL",
        trigger_method: int = 0,
    ) -> Optional[Trade]:
        """Place a Stop or Stop-Limit order (App controls trailing).

        This replaces TWS-native TRAIL/TRAIL LIMIT orders which don't work
        with BAG contracts (multi-leg combos). The app calculates the stop price
        and modifies it dynamically via modify_stop_order().

        Args:
            contract: Contract or BAG contract for combo
            quantity: Total quantity to trade
            stop_price: Trigger price (auxPrice in TWS)
            limit_price: Limit price for execution. If 0, places STP (market) order.
            oca_group: OCA group identifier
            action: "SELL" or "BUY"
            trigger_method: IB trigger method (0=default, 2=last, 4=bid/ask, 8=mid)

        Returns:
            Trade object or None if failed
        """
        if not self.is_connected():
            logger.error("Cannot place order: not connected")
            return None

        try:
            order = Order()
            order.action = action
            order.totalQuantity = abs(quantity)

            # Get price increment based on actual price level and round
            # For combos: auxPrice can be NEGATIVE (credit spreads use SELL @ negative price)
            stop_increment = self._get_price_increment(contract, abs(stop_price))
            stop_price_rounded = self._round_to_tick(stop_price, stop_increment)
            print(f"[BROKER] Price rounding: ${stop_price:.4f} -> ${stop_price_rounded:.2f} (tick={stop_increment})")

            if limit_price == 0 or limit_price is None:
                # Stop-Market Order
                order.orderType = "STP"
                order.auxPrice = stop_price_rounded
            else:
                # Stop-Limit Order - limit price may have different increment
                # For combos: lmtPrice can be NEGATIVE (credit spreads use SELL @ negative price)
                limit_increment = self._get_price_increment(contract, abs(limit_price))
                limit_price_rounded = self._round_to_tick(limit_price, limit_increment)
                order.orderType = "STP LMT"
                order.auxPrice = stop_price_rounded
                order.lmtPrice = limit_price_rounded

            order.triggerMethod = trigger_method
            order.transmit = True
            order.tif = "GTC"  # Good Till Cancelled

            # OCA group settings
            # Note: BAG (combo) orders do NOT support OCA groups for stop orders
            # Only set OCA for single-leg orders
            if oca_group and contract.secType != "BAG":
                order.ocaGroup = oca_group
                order.ocaType = 1  # Cancel all remaining on fill

            # Log contract details for debugging
            print(f"[BROKER] place_stop_order: Placing {order.orderType} {order.action} order on "
                  f"{contract.secType} {contract.symbol} conId={contract.conId} "
                  f"exchange={contract.exchange} stop=${stop_price_rounded:.2f}")
            logger.debug(f"Placing order on contract: {contract.secType} {contract.symbol} "
                        f"conId={contract.conId} exchange={contract.exchange}")

            trade = self.ib.placeOrder(contract, order)

            # Brief wait to receive order status update from TWS
            import time as time_module
            time_module.sleep(0.2)  # Simple sync wait - avoid asyncio issues

            # Check order status
            status = trade.orderStatus.status if trade.orderStatus else "Unknown"
            print(f"[BROKER] Order placed: orderId={trade.order.orderId} status={status}")
            logger.info(f"Placed {order.orderType} order: orderId={trade.order.orderId} "
                       f"status={status} stop=${stop_price:.2f} action={action} "
                       f"contract={contract.localSymbol or contract.symbol}")

            # Warn if order rejected (PendingSubmit is normal - order in transit to TWS)
            if status in ("ApiCancelled", "Cancelled", "Inactive"):
                print(f"[BROKER] WARNING: Order {trade.order.orderId} REJECTED: {status}")
                logger.warning(f"Order {trade.order.orderId} rejected: {status}")

            return trade

        except Exception as e:
            logger.error(f"Failed to place stop order: {e}")
            return None

    def modify_stop_order(
        self,
        order_id: int,
        new_stop_price: float,
        new_limit_price: float = 0.0,
    ) -> bool:
        """Modify an existing Stop or Stop-Limit order's prices.

        Called by state.py tick_update() when HWM changes.

        Args:
            order_id: TWS Order ID
            new_stop_price: New trigger price
            new_limit_price: New limit price (0 for Stop-Market)

        Returns:
            True if modification successful, False otherwise
        """
        if not self.is_connected():
            logger.warning("Cannot modify order: not connected")
            return False

        try:
            # Find the existing trade
            trades = [t for t in self.ib.openTrades() if t.order.orderId == order_id]
            if not trades:
                logger.warning(f"Order {order_id} not found in open trades - may have been filled")
                return False

            trade = trades[0]
            order = trade.order

            # Check if order is in a modifiable state
            # Skip modification if order is still being submitted or already cancelled/filled
            status = trade.orderStatus.status if trade.orderStatus else ""
            if status in ("PendingSubmit", "PendingCancel", "Cancelled", "Filled"):
                logger.debug(f"Order {order_id} not modifiable (status={status})")
                return False

            # Check if prices actually changed (avoid unnecessary modifications)
            # For combos, new_stop_price may be negative (credit spreads)
            stop_changed = abs(order.auxPrice - new_stop_price) >= 0.01
            limit_changed = (new_limit_price != 0 and
                           hasattr(order, 'lmtPrice') and
                           abs(order.lmtPrice - new_limit_price) >= 0.01)

            if not stop_changed and not limit_changed:
                return True  # No change needed

            # Get price increment based on actual price level and round
            # Preserve sign for combo credit spreads
            stop_increment = self._get_price_increment(trade.contract, abs(new_stop_price))

            # Update prices (preserve sign for combos)
            order.auxPrice = self._round_to_tick(new_stop_price, stop_increment)
            if new_limit_price != 0:
                limit_increment = self._get_price_increment(trade.contract, abs(new_limit_price))
                order.lmtPrice = self._round_to_tick(new_limit_price, limit_increment)

            # Re-place the order (ib_insync handles modification)
            self.ib.placeOrder(trade.contract, order)

            limit_str = f"${new_limit_price:.2f}" if new_limit_price else "N/A"
            logger.debug(f"Modified order {order_id}: stop=${new_stop_price:.2f} limit={limit_str}")
            return True

        except Exception as e:
            logger.error(f"Failed to modify order {order_id}: {e}")
            return False

    def place_time_exit_order(
        self,
        contract: Contract,
        quantity: int,
        exit_time: str,  # "HH:MM" format
        oca_group: str,
        action: str = "SELL"
    ) -> Optional[Trade]:
        """Place a time-based market order (Good After Time).

        Args:
            contract: Contract to trade
            quantity: Quantity
            exit_time: Time in HH:MM format (ET)
            oca_group: OCA group identifier
            action: "SELL" or "BUY"

        Returns:
            Trade object or None if failed
        """
        if not self.is_connected():
            logger.error("Cannot place order: not connected")
            return None

        try:
            # Convert HH:MM to TWS format (YYYYMMDD HH:MM:SS timezone)
            today = datetime.now().strftime("%Y%m%d")
            gat_time = f"{today} {exit_time}:00 US/Eastern"

            order = Order()
            order.action = action
            order.totalQuantity = abs(quantity)
            order.orderType = "MKT"
            order.goodAfterTime = gat_time
            order.tif = "DAY"
            order.transmit = True

            # OCA group settings
            # Note: BAG (combo) orders do NOT support OCA groups
            if contract.secType != "BAG":
                order.ocaGroup = oca_group
                order.ocaType = 1  # Cancel all remaining on fill

            trade = self.ib.placeOrder(contract, order)

            logger.info(f"Placed time exit: orderId={trade.order.orderId} at {exit_time}")

            return trade

        except Exception as e:
            logger.error(f"Failed to place time exit: {e}")
            return None

    def place_oca_group(
        self,
        group_name: str,
        position_quantities: dict[int, int],
        stop_type: str,
        limit_offset: float,
        time_exit_enabled: bool,
        time_exit_time: str,
        initial_stop_price: float,
        initial_limit_price: float = 0.0,
        trigger_price_type: str = "mark",
        is_credit: bool = False,
    ) -> Optional[dict]:
        """Place complete OCA order group (stop order + optional time exit).

        NOTE: This now uses app-controlled STP/STP LMT orders instead of
        TWS-native TRAIL orders, because TRAIL doesn't work with BAG contracts.
        The app will modify stop prices dynamically via modify_stop_order().

        Args:
            group_name: Name for logging and OCA group ID
            position_quantities: {con_id: quantity} mapping
            stop_type: "market" (STP) or "limit" (STP LMT)
            limit_offset: Offset for limit price (only used if stop_type="limit")
            time_exit_enabled: Whether to place time exit order
            time_exit_time: Time for exit in HH:MM format
            initial_stop_price: Initial stop trigger price
            initial_limit_price: Initial limit price (0 for stop-market)
            trigger_price_type: "mark", "mid", "bid", "ask", "last"
            is_credit: True for credit/short positions (action=BUY to close)

        Returns:
            Dict with oca_group_id, trailing_order_id, time_exit_order_id
            or None if failed
        """
        try:
            # Log input for debugging
            logger.info(f"place_oca_group: position_quantities={position_quantities} is_credit={is_credit}")

            # Determine order action
            # For combos: ALWAYS use SELL with price sign determining direction:
            # - Debit spread: SELL @ +positive price (receive money)
            # - Credit spread: SELL @ -negative price (pay money to close)
            #
            # For single-leg: use traditional BUY/SELL based on position
            is_multi_leg = len(position_quantities) > 1

            if is_multi_leg:
                # Combos: Always SELL, price sign determines credit/debit
                action = "SELL"
                # Always invert leg actions for SELL order (IBKR inverts them back)
                invert_legs = True
                print(f"[BROKER] Multi-leg order: action=SELL, invert_legs=True")
                logger.info(f"Multi-leg order: action=SELL, invert_legs=True")
            else:
                # Single leg: BUY to close short, SELL to close long
                action = "BUY" if is_credit else "SELL"
                invert_legs = False
                print(f"[BROKER] Single-leg order: action={action}, is_credit={is_credit}")
                logger.info(f"Single-leg order: action={action}, is_credit={is_credit}")

            # Build contract
            print(f"[BROKER] Building contract for position_quantities={position_quantities}")
            contract = self.build_combo_contract(position_quantities, invert_leg_actions=invert_legs)
            if not contract:
                print(f"[BROKER] ERROR: Failed to build contract!")
                logger.error(f"Failed to build contract for position_quantities={position_quantities}")
                return None

            print(f"[BROKER] Contract built: secType={contract.secType}, symbol={contract.symbol}, "
                  f"conId={contract.conId}, exchange={contract.exchange}, localSymbol={contract.localSymbol}")
            logger.info(f"Contract built: secType={contract.secType}, symbol={contract.symbol}, "
                       f"conId={contract.conId}, exchange={contract.exchange}, localSymbol={contract.localSymbol}")

            # For BAG contracts, the ratios are encoded in ComboLegs
            # Order quantity should be 1 (meaning: 1 unit of the combo)
            # For single-leg orders, use the actual quantity
            if len(position_quantities) == 1:
                total_qty = abs(list(position_quantities.values())[0])
            else:
                # Multi-leg combo: quantity = 1 (ratios are in legs)
                total_qty = 1

            # Create OCA group
            oca_group = self.create_oca_group_id(group_name)

            # Get trigger method from trigger_price_type
            trigger_method = self.get_trigger_method(trigger_price_type)

            # For combos: price sign determines direction
            # Credit spread: SELL @ -negative price (pay to close)
            # Debit spread: SELL @ +positive price (receive to close)
            if is_multi_leg and is_credit:
                # Credit combo: use negative price
                stop_price_for_order = -abs(initial_stop_price)
            else:
                # Debit combo or single leg: use positive price
                stop_price_for_order = abs(initial_stop_price)

            # Calculate limit price based on stop_type
            if stop_type == "market":
                limit_price = 0.0  # STP order (no limit)
            else:
                # STP LMT order - use provided limit price or calculate fallback
                # For combos, limit follows same sign convention as stop
                if initial_limit_price > 0:
                    base_limit = initial_limit_price
                elif is_credit:
                    # Credit: limit worse than stop (pay more) = more negative
                    base_limit = abs(initial_stop_price) + limit_offset
                else:
                    # Debit: limit worse than stop (receive less) = less positive
                    base_limit = abs(initial_stop_price) - limit_offset

                # Apply sign for combos
                if is_multi_leg and is_credit:
                    limit_price = -abs(base_limit)
                else:
                    limit_price = abs(base_limit)

            # Place app-controlled stop order (STP or STP LMT)
            stop_trade = self.place_stop_order(
                contract=contract,
                quantity=total_qty,
                stop_price=stop_price_for_order,
                limit_price=limit_price,
                oca_group=oca_group,
                action=action,
                trigger_method=trigger_method,
            )

            if not stop_trade:
                return None

            time_exit_order_id = 0

            # Place time exit if enabled
            if time_exit_enabled and time_exit_time:
                time_trade = self.place_time_exit_order(
                    contract=contract,
                    quantity=total_qty,
                    exit_time=time_exit_time,
                    oca_group=oca_group,
                    action=action
                )
                if time_trade:
                    time_exit_order_id = time_trade.order.orderId

            logger.info(f"OCA group placed: {oca_group} action={action} stop={stop_trade.order.orderId} "
                       f"type={stop_trade.order.orderType} time_exit={time_exit_order_id}")

            return {
                "oca_group_id": oca_group,
                "trailing_order_id": stop_trade.order.orderId,  # Keep field name for compatibility
                "time_exit_order_id": time_exit_order_id
            }

        except Exception as e:
            logger.error(f"Failed to place OCA group: {e}")
            return None

    def modify_trailing_stop(
        self,
        order_id: int,
        trail_amount: float,
        trail_mode: str,
        stop_type: str,
        limit_offset: float
    ) -> bool:
        """Modify an existing trailing stop order."""
        if not self.is_connected():
            return False

        try:
            # Find the existing trade
            trades = [t for t in self.ib.openTrades() if t.order.orderId == order_id]
            if not trades:
                logger.error(f"Order {order_id} not found in open trades")
                return False

            trade = trades[0]
            order = trade.order

            # Modify only the trail parameters
            if trail_mode == "percent":
                order.trailingPercent = trail_amount
                order.auxPrice = 0  # Clear absolute trail
            else:
                order.auxPrice = trail_amount
                order.trailingPercent = 0  # Clear percent trail

            if stop_type == "limit":
                order.lmtPriceOffset = limit_offset

            # Re-place the order (ib_insync handles modification)
            self.ib.placeOrder(trade.contract, order)

            logger.info(f"Modified order {order_id}: trail={trail_amount} mode={trail_mode}")
            return True

        except Exception as e:
            logger.error(f"Failed to modify order {order_id}: {e}")
            return False

    def cancel_order(self, order_id: int) -> bool:
        """Cancel a single order."""
        logger.info(f"cancel_order called with order_id={order_id}")

        if not self.is_connected():
            logger.warning("cancel_order: not connected to TWS")
            return False

        try:
            open_trades = self.ib.openTrades()
            logger.debug(f"Open trades: {[t.order.orderId for t in open_trades]}")

            trades = [t for t in open_trades if t.order.orderId == order_id]
            if trades:
                trade = trades[0]
                logger.info(f"Found order {order_id}: status={trade.orderStatus.status}, "
                           f"type={trade.order.orderType}, action={trade.order.action}")
                self.ib.cancelOrder(trade.order)
                logger.info(f"Cancel request sent for order {order_id}")
                return True

            logger.warning(f"Order {order_id} not found in open trades: {[t.order.orderId for t in open_trades]}")
            return False
        except Exception as e:
            logger.error(f"Failed to cancel order {order_id}: {e}")
            return False

    def cancel_oca_group(self, oca_group: str) -> bool:
        """Cancel all orders in an OCA group."""
        logger.info(f"cancel_oca_group called with oca_group={oca_group}")

        if not self.is_connected():
            logger.warning("cancel_oca_group: not connected to TWS")
            return False

        try:
            open_trades = self.ib.openTrades()
            logger.debug(f"Searching for OCA group '{oca_group}' in {len(open_trades)} open trades")

            # Log all OCA groups found
            oca_groups_found = set(t.order.ocaGroup for t in open_trades if t.order.ocaGroup)
            logger.debug(f"OCA groups in open trades: {oca_groups_found}")

            cancelled = 0
            for trade in open_trades:
                if trade.order.ocaGroup == oca_group:
                    logger.info(f"Found matching order: {trade.order.orderId} in OCA group {oca_group}")
                    self.ib.cancelOrder(trade.order)
                    cancelled += 1

            if cancelled > 0:
                logger.info(f"Cancelled {cancelled} orders in OCA group {oca_group}")
            else:
                logger.warning(f"No orders found in OCA group '{oca_group}'. "
                              f"Available OCA groups: {oca_groups_found}")
            return cancelled > 0
        except Exception as e:
            logger.error(f"Failed to cancel OCA group {oca_group}: {e}")
            return False

    # =========================================================================
    # HISTORICAL DATA
    # =========================================================================

    def fetch_historical_bars(
        self,
        con_id: int,
        duration: str = "3 D",
        bar_size: str = "3 mins",
        what_to_show: str = "TRADES"
    ) -> list[dict]:
        """Fetch historical OHLC bars for a contract.

        Args:
            con_id: Contract ID
            duration: Duration string (e.g., "3 D", "1 W", "1 M")
            bar_size: Bar size (e.g., "3 mins", "5 mins", "1 hour")
            what_to_show: Data type ("TRADES", "MIDPOINT", "BID", "ASK")

        Returns:
            List of dicts with: date, open, high, low, close, volume
        """
        if not self.is_connected():
            logger.error("Cannot fetch historical data: not connected")
            return []

        if not self._loop:
            logger.error("fetch_historical_bars: no event loop available")
            return []

        pos = self._positions.get(con_id)
        if not pos or not pos.raw_contract:
            logger.error(f"Position {con_id} not found")
            return []

        contract = pos.raw_contract

        async def _fetch_async():
            try:
                bars = await self.ib.reqHistoricalDataAsync(
                    contract,
                    endDateTime="",  # Now
                    durationStr=duration,
                    barSizeSetting=bar_size,
                    whatToShow=what_to_show,
                    useRTH=False,  # Include extended hours
                    formatDate=1   # String format
                )

                if not bars:
                    logger.warning(f"No historical data for {contract.symbol}")
                    return []

                result = []
                for bar in bars:
                    result.append({
                        "date": bar.date.isoformat() if hasattr(bar.date, 'isoformat') else str(bar.date),
                        "open": bar.open,
                        "high": bar.high,
                        "low": bar.low,
                        "close": bar.close,
                        "volume": bar.volume
                    })

                logger.info(f"Fetched {len(result)} historical bars for {contract.symbol}")
                return result

            except Exception as e:
                logger.error(f"Async fetch error for {contract.symbol}: {e}")
                return []

        try:
            # Schedule coroutine in broker's event loop and wait for result
            future = asyncio.run_coroutine_threadsafe(_fetch_async(), self._loop)
            return future.result(timeout=30)

        except Exception as e:
            logger.error(f"Failed to fetch historical data: {e}")
            return []

    def fetch_underlying_history(self, symbol: str, duration: str = "3 D", bar_size: str = "3 mins") -> list[dict]:
        """Fetch historical data for underlying stock/index/future.

        Args:
            symbol: Symbol (e.g., "AAPL", "SPY", "SPX", "ES", "DAX")
            duration: Duration string
            bar_size: Bar size string

        Returns:
            List of OHLC bar dicts
        """
        if not self.is_connected():
            logger.debug("fetch_underlying_history: not connected")
            return []

        if not self._loop:
            logger.error("fetch_underlying_history: no event loop available")
            return []

        # Define async fetch logic
        async def _fetch_async():
            try:
                # Detect contract type based on symbol
                indices = {"SPX", "NDX", "RUT", "VIX", "DJX", "DAX", "ESTX50"}
                futures = {"ES", "NQ", "YM", "RTY", "CL", "GC", "SI", "ZB", "ZN"}

                if symbol in indices:
                    # Index contract - use correct exchange
                    if symbol == "DAX":
                        contract = Index(symbol, "EUREX", "EUR")
                    elif symbol in {"SPX", "NDX", "VIX", "RUT", "DJX"}:
                        contract = Index(symbol, "CBOE", "USD")
                    else:
                        contract = Index(symbol, "EUREX", "EUR")
                    await self.ib.qualifyContractsAsync(contract)

                elif symbol in futures:
                    # Future - get front month contract
                    if symbol in {"ES", "NQ", "RTY"}:
                        contract = Future(symbol, exchange="CME")
                    elif symbol in {"CL", "GC", "SI"}:
                        contract = Future(symbol, exchange="NYMEX")
                    else:
                        contract = Future(symbol, exchange="CME")

                    contracts = await self.ib.reqContractDetailsAsync(contract)
                    if contracts:
                        # Get front month (first contract by expiry)
                        contract = sorted(contracts, key=lambda c: c.contract.lastTradeDateOrContractMonth)[0].contract
                        await self.ib.qualifyContractsAsync(contract)
                    else:
                        logger.warning(f"No future contracts found for {symbol}")
                        return []
                else:
                    # Stock contract
                    contract = Stock(symbol, "SMART", "USD")
                    await self.ib.qualifyContractsAsync(contract)

                logger.debug(f"Requesting historical data for {symbol} ({type(contract).__name__})")

                bars = await self.ib.reqHistoricalDataAsync(
                    contract,
                    endDateTime="",
                    durationStr=duration,
                    barSizeSetting=bar_size,
                    whatToShow="TRADES",
                    useRTH=False,
                    formatDate=1
                )

                if not bars:
                    logger.warning(f"No historical data returned for {symbol}")
                    return []

                result = []
                for bar in bars:
                    result.append({
                        "date": bar.date.isoformat() if hasattr(bar.date, 'isoformat') else str(bar.date),
                        "open": bar.open,
                        "high": bar.high,
                        "low": bar.low,
                        "close": bar.close,
                        "volume": bar.volume
                    })

                logger.info(f"Fetched {len(result)} underlying bars for {symbol}")
                return result

            except Exception as e:
                logger.error(f"Async fetch error for {symbol}: {e}")
                return []

        try:
            # Schedule coroutine in broker's event loop and wait for result
            future = asyncio.run_coroutine_threadsafe(_fetch_async(), self._loop)
            return future.result(timeout=30)  # 30 second timeout

        except Exception as e:
            logger.error(f"Failed to fetch underlying history for {symbol}: {e}")
            return []

    def fetch_latest_underlying_bar(self, symbol: str, bar_size: str = "3 mins") -> dict | None:
        """Fetch only the most recent bar for live updates.

        Args:
            symbol: Symbol (e.g., "AAPL", "SPY", "SPX", "ES", "DAX")
            bar_size: Bar size string (default "3 mins")

        Returns:
            Single bar dict or None
        """
        if not self.is_connected():
            return None

        if not self._loop:
            return None

        async def _fetch_async():
            try:
                # Detect contract type based on symbol
                indices = {"SPX", "NDX", "RUT", "VIX", "DJX", "DAX", "ESTX50"}
                futures = {"ES", "NQ", "YM", "RTY", "CL", "GC", "SI", "ZB", "ZN"}

                if symbol in indices:
                    if symbol == "DAX":
                        contract = Index(symbol, "EUREX", "EUR")
                    elif symbol in {"SPX", "NDX", "VIX", "RUT", "DJX"}:
                        contract = Index(symbol, "CBOE", "USD")
                    else:
                        contract = Index(symbol, "EUREX", "EUR")
                    await self.ib.qualifyContractsAsync(contract)

                elif symbol in futures:
                    if symbol in {"ES", "NQ", "RTY"}:
                        contract = Future(symbol, exchange="CME")
                    elif symbol in {"CL", "GC", "SI"}:
                        contract = Future(symbol, exchange="NYMEX")
                    else:
                        contract = Future(symbol, exchange="CME")

                    contracts = await self.ib.reqContractDetailsAsync(contract)
                    if contracts:
                        contract = sorted(contracts, key=lambda c: c.contract.lastTradeDateOrContractMonth)[0].contract
                        await self.ib.qualifyContractsAsync(contract)
                    else:
                        return None
                else:
                    contract = Stock(symbol, "SMART", "USD")
                    await self.ib.qualifyContractsAsync(contract)

                # Request just the latest bar (300 seconds = 5 mins duration for 3-min bar)
                bars = await self.ib.reqHistoricalDataAsync(
                    contract,
                    endDateTime="",
                    durationStr="300 S",
                    barSizeSetting=bar_size,
                    whatToShow="TRADES",
                    useRTH=False,
                    formatDate=1
                )

                if bars:
                    bar = bars[-1]  # Get the most recent bar
                    return {
                        "date": bar.date.isoformat() if hasattr(bar.date, 'isoformat') else str(bar.date),
                        "open": bar.open,
                        "high": bar.high,
                        "low": bar.low,
                        "close": bar.close,
                        "volume": bar.volume
                    }
                return None

            except Exception as e:
                logger.error(f"Error fetching latest bar for {symbol}: {e}")
                return None

        try:
            future = asyncio.run_coroutine_threadsafe(_fetch_async(), self._loop)
            return future.result(timeout=10)
        except Exception as e:
            logger.error(f"Failed to fetch latest bar for {symbol}: {e}")
            return None


# Global broker instance
BROKER = TWSBroker()
