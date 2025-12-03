"""TWS Broker - connects to Interactive Brokers TWS with real-time events."""
from dataclasses import dataclass, field
from datetime import datetime
from threading import Thread
from typing import Callable, Optional
import asyncio
from ib_insync import IB, Contract, Option, Stock, Index, Future, ComboLeg, PortfolioItem, Ticker, util, Order, Trade
import uuid

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

            # Initialize/reinitialize MarketDataManager
            self._market_data = MarketDataManager(self.ib, self.price_cache)
            logger.info("MarketDataManager initialized")

            # Wait for initial data
            self.ib.sleep(2.0)

            # Fetch portfolio
            self._fetch_portfolio()

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

    # =========================================================================
    # ORDER PLACEMENT
    # =========================================================================

    def create_oca_group_id(self, group_name: str) -> str:
        """Generate unique OCA group identifier."""
        return f"TSM_{group_name}_{uuid.uuid4().hex[:8]}"

    def build_combo_contract(self, position_quantities: dict[int, int]) -> Optional[Contract]:
        """Build BAG (combo) contract from multiple positions.

        Args:
            position_quantities: {con_id: quantity} mapping

        Returns:
            Contract object for the combo, or None if failed
        """
        if not position_quantities:
            logger.error("No positions provided for combo contract")
            return None

        if len(position_quantities) == 1:
            # Single leg - return the position's contract
            con_id = list(position_quantities.keys())[0]
            pos = self._positions.get(con_id)
            if pos and pos.raw_contract:
                return pos.raw_contract
            logger.error(f"Position {con_id} not found")
            return None

        # Multi-leg combo
        combo_legs = []
        symbol = None

        for con_id, qty in position_quantities.items():
            pos = self._positions.get(con_id)
            if not pos:
                logger.error(f"Position {con_id} not found")
                return None

            if symbol is None:
                symbol = pos.symbol
            elif pos.symbol != symbol:
                logger.error(f"All legs must have same underlying: {symbol} vs {pos.symbol}")
                return None

            # Determine action based on position sign (closing the position)
            # If we're long (qty > 0), we SELL to close
            # If we're short (qty < 0), we BUY to close
            action = "SELL" if qty > 0 else "BUY"

            leg = ComboLeg(
                conId=con_id,
                ratio=abs(qty),
                action=action,
                exchange="SMART"
            )
            combo_legs.append(leg)

        combo = Contract(
            secType="BAG",
            symbol=symbol,
            exchange="SMART",
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
        action: str = "SELL"  # SELL to close long, BUY to close short
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
            else:  # absolute
                order.orderType = "TRAIL" if stop_type == "market" else "TRAIL LIMIT"
                order.auxPrice = trail_amount  # Trail amount in dollars
                if stop_type == "limit":
                    order.lmtPriceOffset = limit_offset

            trade = self.ib.placeOrder(contract, order)

            logger.info(f"Placed trailing stop: orderId={trade.order.orderId} "
                       f"type={order.orderType} trail={trail_amount} mode={trail_mode}")

            return trade

        except Exception as e:
            logger.error(f"Failed to place trailing stop: {e}")
            return None

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
            order.ocaGroup = oca_group
            order.ocaType = 1

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
        trail_value: float,
        trail_mode: str,
        stop_type: str,
        limit_offset: float,
        time_exit_enabled: bool,
        time_exit_time: str
    ) -> Optional[dict]:
        """Place complete OCA order group (trailing stop + optional time exit).

        Returns:
            Dict with oca_group_id, trailing_order_id, time_exit_order_id
            or None if failed
        """
        try:
            # Build contract
            contract = self.build_combo_contract(position_quantities)
            if not contract:
                return None

            total_qty = sum(abs(q) for q in position_quantities.values())

            # Determine action: if net position is long, SELL to close
            net_qty = sum(position_quantities.values())
            action = "SELL" if net_qty > 0 else "BUY"

            # Create OCA group
            oca_group = self.create_oca_group_id(group_name)

            # Place trailing stop
            trailing_trade = self.place_trailing_stop_order(
                contract=contract,
                quantity=total_qty,
                trail_amount=trail_value,
                trail_mode=trail_mode,
                stop_type=stop_type,
                limit_offset=limit_offset,
                oca_group=oca_group,
                action=action
            )

            if not trailing_trade:
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

            logger.info(f"OCA group placed: {oca_group} trailing={trailing_trade.order.orderId} time_exit={time_exit_order_id}")

            return {
                "oca_group_id": oca_group,
                "trailing_order_id": trailing_trade.order.orderId,
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
        if not self.is_connected():
            return False

        try:
            trades = [t for t in self.ib.openTrades() if t.order.orderId == order_id]
            if trades:
                self.ib.cancelOrder(trades[0].order)
                logger.info(f"Cancelled order {order_id}")
                return True
            logger.warning(f"Order {order_id} not found")
            return False
        except Exception as e:
            logger.error(f"Failed to cancel order {order_id}: {e}")
            return False

    def cancel_oca_group(self, oca_group: str) -> bool:
        """Cancel all orders in an OCA group."""
        if not self.is_connected():
            return False

        try:
            cancelled = 0
            for trade in self.ib.openTrades():
                if trade.order.ocaGroup == oca_group:
                    self.ib.cancelOrder(trade.order)
                    cancelled += 1

            if cancelled > 0:
                logger.info(f"Cancelled {cancelled} orders in OCA group {oca_group}")
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

                # Request just the latest bar (5 mins duration for 3-min bar)
                bars = await self.ib.reqHistoricalDataAsync(
                    contract,
                    endDateTime="",
                    durationStr="5 mins",
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
