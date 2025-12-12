"""Application state management."""
import json
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from threading import Lock
import reflex as rx
import plotly.graph_objects as go

from .broker import BROKER
from .groups import GROUP_MANAGER
from .metrics import LegData, GroupMetrics, compute_group_metrics, calculate_stop_price
from .config import (
    UI_UPDATE_INTERVAL,
    DEFAULT_TRAIL_PERCENT, DEFAULT_STOP_TYPE, DEFAULT_LIMIT_OFFSET,
    BAR_INTERVAL_TICKS, CHART_RENDER_INTERVAL,
    UI_POSITION_THROTTLE_INTERVAL,
    TWS_PORT, TWS_CLIENT_ID
)
from .logger import logger
from .paths import DATA_DIR

# Connection config file in platform-specific data directory
CONNECTION_CONFIG_PATH = DATA_DIR / "connection_config.json"


def load_connection_config() -> dict:
    """Load connection config from JSON file."""
    if CONNECTION_CONFIG_PATH.exists():
        try:
            with open(CONNECTION_CONFIG_PATH) as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"Failed to load connection config: {e}")
    return {"port": TWS_PORT, "client_id": TWS_CLIENT_ID}


def save_connection_config(port: int, client_id: int) -> None:
    """Save connection config to JSON file."""
    try:
        CONNECTION_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(CONNECTION_CONFIG_PATH, "w") as f:
            json.dump({"port": port, "client_id": client_id}, f, indent=2)
        logger.debug(f"Saved connection config: port={port}, client_id={client_id}")
    except IOError as e:
        logger.error(f"Failed to save connection config: {e}")


class UIUpdateQueue:
    """Thread-safe queue for UI price updates."""

    def __init__(self):
        self._pending: dict[int, float] = {}
        self._lock = Lock()

    def queue(self, con_id: int, price: float) -> None:
        """Queue a price update."""
        with self._lock:
            self._pending[con_id] = price

    def flush(self) -> dict[int, float]:
        """Get and clear all pending updates."""
        with self._lock:
            updates = self._pending.copy()
            self._pending.clear()
            return updates


# Global UI update queue
UI_QUEUE = UIUpdateQueue()


@dataclass
class PositionData:
    """Position data for UI display."""
    con_id: int
    symbol: str
    sec_type: str
    type_str: str
    expiry: str
    strike_str: str
    quantity: float
    quantity_str: str
    # Price fields: Fill, Bid, Mid, Ask, Last, Mark (from portfolio)
    fill_price: float
    fill_price_str: str
    bid: float
    bid_str: str
    mid: float
    mid_str: str
    ask: float
    ask_str: str
    last: float
    last_str: str
    mark: float  # Market price from portfolio (synchronous)
    mark_str: str
    # Calculated fields
    net_cost: float
    net_cost_str: str
    net_value: float
    net_value_str: str
    pnl: float
    pnl_str: str
    pnl_color: str
    # Metadata
    multiplier: int
    is_combo: bool
    combo_legs: list


class AppState(rx.State):
    """Main application state."""

    # Connection config (editable only when disconnected)
    tws_port: int = TWS_PORT
    tws_client_id: int = TWS_CLIENT_ID

    # Connection status
    is_connected: bool = False
    connection_status: str = "Disconnected"

    # Portfolio - use list[dict] for proper Reflex serialization (not dataclass)
    positions: list[dict] = []
    # Position rows for table rendering (computed from positions, stored as regular state var)
    # This replaces the @rx.var computed property which doesn't work in Nuitka bundles
    position_rows: list[list[str]] = []
    # Selected positions with quantities: {con_id_str: quantity} - JSON uses string keys
    selected_quantities: dict[str, int] = {}

    # Groups
    groups: list[dict] = []
    new_group_name: str = ""

    # Settings for new group
    trail_percent: float = DEFAULT_TRAIL_PERCENT
    stop_type: str = DEFAULT_STOP_TYPE
    limit_offset: float = DEFAULT_LIMIT_OFFSET

    # Monitoring
    is_monitoring: bool = False
    status_message: str = "Ready"
    refresh_tick: int = 0  # Force UI refresh

    # === UI Performance Optimization ===
    # Throttle UI updates to reduce CPU load while keeping trading logic in real-time
    _ui_tick_counter: int = 0  # Counter for UI update throttling
    _ui_dirty: bool = False  # Flag to indicate UI needs update (from event handlers)
    _groups_count_cache: int = 0  # Cache groups count to detect changes

    # === NEW: Unified Chart State (12h window, 240 x 3-min slots) ===
    # chart_data: group_id -> {
    #   "start_timestamp": float,     # Connect/create time
    #   "current_slot": int,          # 0-239
    #   "position_bars": list[240],   # OHLC bars (None or dict)
    #   "pnl_bars": list[240],        # PnL bars (None or dict)
    #   "current_pos": dict | None,   # Accumulator for current bar
    #   "current_pnl": dict | None,   # Accumulator for current bar
    # }
    chart_data: dict[str, dict] = {}

    # === Rate limiting for order modifications ===
    # Tracks last sent stop/limit prices to avoid excessive TWS API calls
    # {group_id: {"stop": float, "limit": float, "timestamp": float}}
    last_sent_stop_prices: dict[str, dict] = {}

    # === Double-click prevention ===
    # Tracks in-progress activations to prevent duplicate orders
    # {group_id: timestamp}
    _activation_in_progress: dict[str, float] = {}

    # Pre-rendered Plotly figures (stored as Figure, NOT @rx.var!)
    # Reflex serializes go.Figure to dict automatically
    underlying_figure: go.Figure = go.Figure()
    position_figure: go.Figure = go.Figure()
    pnl_figure: go.Figure = go.Figure()

    # Underlying history for Chart 1 (loaded from TWS)
    underlying_history: dict[str, list[dict]] = {}  # symbol -> OHLC bars

    # UI State
    active_tab: str = "setup"  # "setup" or "monitor"
    delete_confirm_group_id: str = ""  # Group ID pending delete confirmation
    selected_group_id: str = ""  # Currently selected group in monitor tab
    # Nuitka workaround: store group_id before action (partial application doesn't work in rx.foreach)
    pending_toggle_group_id: str = ""  # Group ID for pending toggle action
    pending_cancel_group_id: str = ""  # Group ID for pending cancel action
    pending_delete_group_id: str = ""  # Group ID for pending delete action
    # Computed vars converted to state vars for Nuitka compatibility
    groups_sorted: list[dict] = []  # Sorted groups for monitor tab
    selected_underlying_symbol: str = ""  # Underlying symbol for selected group

    # === Collapsed Groups (for Monitor tab) ===
    # Groups that are collapsed (showing only KPIs: Name, PnL, Mid, Stop)
    # Default: all collapsed on monitor tab
    collapsed_groups: list[str] = []  # List of group IDs that are collapsed

    # === Chart Header Info (updated every render cycle) ===
    # Position OHLC Header: Trigger value (based on trigger_price_type), Stop, Limit, HWM, Fill
    chart_trigger_label: str = "Mid"  # "Mark", "Mid", "Bid", "Ask", "Last"
    chart_pos_close: str = "-"
    chart_pos_stop: str = "-"
    chart_pos_limit: str = "-"
    chart_pos_hwm: str = "-"
    chart_hwm_label: str = "HWM"  # "HWM" for debit, "LWM" for credit
    chart_pos_fill: str = "-"  # Fill/Cost price
    # P&L History Header: Current P&L, Stop P&L
    chart_pnl_current: str = "-"
    chart_pnl_stop: str = "-"

    def _compute_position_rows(self):
        """Compute position_rows from positions and update state.

        This replaces the @rx.var computed property which doesn't work in Nuitka bundles.
        Called after _refresh_positions() to update the table data.

        Column order: [con_id, symbol, type, expiry, strike, side, qty, fill_price,
                       bid, mid, ask, last, mark, net_cost, net_value, pnl, pnl_color,
                       is_selected, qty_usage_str, is_fully_used, selected_qty,
                       available_qty, qty_options, market_status]
        """
        rows = []
        for p in self.positions:
            pnl_val = p.get("pnl", 0)
            con_id_str = str(p["con_id"])
            # Check if position is selected and get selected quantity
            selected_qty = self.selected_quantities.get(con_id_str, 0)
            is_selected = selected_qty > 0
            is_fully_used = p.get("is_fully_used", False)
            row = [
                str(p["con_id"]),       # 0
                p["symbol"],            # 1
                p["type_str"],          # 2
                p["expiry"],            # 3
                p["strike_str"],        # 4
                p.get("side_str", "-"), # 5 - Side (C/P)
                p["quantity_str"],      # 6
                p["fill_price_str"],    # 7 - Fill Price
                p["bid_str"],           # 8 - Bid
                p["mid_str"],           # 9 - Mid
                p["ask_str"],           # 10 - Ask
                p["last_str"],          # 11 - Last
                p["mark_str"],          # 12 - Mark (portfolio price, sync)
                p["net_cost_str"],      # 13 - Net Cost
                p["net_value_str"],     # 14 - Net Value
                p["pnl_str"],           # 15 - PnL
                "green" if pnl_val >= 0 else "red",  # 16 - pnl_color
                "true" if is_selected else "false",  # 17 - is_selected (as string for frontend)
                p.get("qty_usage_str", "0/0"),       # 18 - qty_usage_str (e.g., "2/3")
                "true" if is_fully_used else "false",  # 19 - is_fully_used
                str(selected_qty),      # 20 - selected_qty for this group
                str(p.get("available_qty", 0)),  # 21 - available_qty for dropdown
                ",".join(p.get("qty_options", ["0"])),  # 22 - qty_options as comma-separated string
                p.get("market_status", "Unknown"),  # 23 - market_status (Open/Closed/Unknown)
            ]
            rows.append(row)
        # Log first row to verify data
        if rows:
            logger.debug(f"UI row[0]: {rows[0][1]} fill={rows[0][6]} mark={rows[0][11]} pnl={rows[0][14]} selected={rows[0][16]} usage={rows[0][17]}")
        # Update state variable (triggers frontend update)
        self.position_rows = rows

    def on_mount(self):
        """Called when page mounts - just initialize UI, don't auto-connect."""
        logger.info("App mounted")
        # Load connection config
        config = load_connection_config()
        self.tws_port = config.get("port", TWS_PORT)
        self.tws_client_id = config.get("client_id", TWS_CLIENT_ID)
        logger.info(f"Loaded connection config: port={self.tws_port}, client_id={self.tws_client_id}")
        # Load persisted groups
        self._load_groups_from_manager()
        self.status_message = "Click 'Connect' to connect to TWS"

    def set_tws_port(self, value: str):
        """Set TWS port (only when disconnected)."""
        if self.is_connected:
            return
        try:
            port = int(value)
            if 1 <= port <= 65535:
                self.tws_port = port
                save_connection_config(self.tws_port, self.tws_client_id)
        except (ValueError, TypeError):
            pass

    def set_tws_client_id(self, value: str):
        """Set TWS client ID (only when disconnected)."""
        if self.is_connected:
            return
        try:
            client_id = int(value)
            if client_id >= 0:
                self.tws_client_id = client_id
                save_connection_config(self.tws_port, self.tws_client_id)
        except (ValueError, TypeError):
            pass

    def connect_tws(self):
        """Connect to TWS."""
        logger.info(f"Connecting to TWS at port={self.tws_port}, client_id={self.tws_client_id}...")
        self.connection_status = "Connecting..."
        self.status_message = "Connecting to TWS..."

        # Update broker config before connecting
        BROKER.port = self.tws_port
        BROKER.client_id = self.tws_client_id

        success = BROKER.connect()

        if success:
            self.is_connected = True
            self.connection_status = "Connected"
            self._load_positions()
            self.status_message = f"Connected - {len(self.positions)} positions loaded"
            logger.success(f"Connected, {len(self.positions)} positions")
            # Auto-start monitoring
            self.is_monitoring = True
            # Load chart data if a group was already selected
            if self.selected_group_id:
                self._load_group_chart_data(self.selected_group_id)
        else:
            self.is_connected = False
            # Auto-reconnect is happening, status will be updated via tick_update
            self.connection_status = "Connecting..."
            self.status_message = "Connection in progress (auto-reconnect enabled)..."
            logger.info("Initial connection pending, auto-reconnect enabled")

    def disconnect_tws(self):
        """Disconnect from TWS."""
        logger.info("Disconnecting from TWS...")
        self.is_monitoring = False
        BROKER.disconnect()
        self.is_connected = False
        self.connection_status = "Disconnected"
        self.positions = []
        self.status_message = "Disconnected from TWS"
        logger.success("Disconnected")

    def reconnect_tws(self):
        """Manually trigger reconnection."""
        logger.info("Manual reconnect requested...")
        self.connection_status = "Reconnecting..."
        self.status_message = "Manual reconnect requested..."
        BROKER.request_reconnect()

    def _load_positions(self):
        """Load positions from broker (uses live prices when available)."""
        self._refresh_positions()
        self._compute_position_rows()

    def toggle_position(self, con_id):
        """Toggle position selection (selects with default qty=1 or deselects).

        UI OPTIMIZATION: Updates state immediately for fast feedback, but defers
        _compute_position_rows() to next tick_update() via _ui_dirty flag.
        """
        # Ensure con_id is string for dict key
        con_id_str = str(con_id)
        logger.debug(f"toggle_position called with con_id={con_id_str}, current selected={self.selected_quantities}")

        new_selected = dict(self.selected_quantities)
        if con_id_str in new_selected:
            del new_selected[con_id_str]
            logger.debug(f"Removed {con_id_str}, now selected={new_selected}")
        else:
            # Default to 1 when toggling on, will be adjusted by set_position_quantity
            new_selected[con_id_str] = 1
            logger.debug(f"Added {con_id_str} with qty=1, now selected={new_selected}")
        self.selected_quantities = new_selected

        # Mark UI as dirty so next tick_update() refreshes position_rows
        self._ui_dirty = True

    def set_position_quantity(self, con_id, qty):
        """Set the quantity for a selected position.

        UI OPTIMIZATION: Updates state immediately for fast feedback, but defers
        _compute_position_rows() to next tick_update() via _ui_dirty flag.

        Args:
            con_id: Position contract ID (can be int or str)
            qty: Quantity to allocate (str from input, will be converted)
        """
        con_id_str = str(con_id)
        try:
            qty_int = int(qty)
        except (ValueError, TypeError):
            qty_int = 0

        new_selected = dict(self.selected_quantities)
        if qty_int <= 0:
            # Remove from selection if qty is 0 or negative
            if con_id_str in new_selected:
                del new_selected[con_id_str]
        else:
            new_selected[con_id_str] = qty_int

        self.selected_quantities = new_selected
        logger.debug(f"set_position_quantity: {con_id_str}={qty_int}, now selected={new_selected}")

        # Mark UI as dirty so next tick_update() refreshes position_rows
        self._ui_dirty = True

    def set_new_group_name(self, value: str):
        self.new_group_name = value

    def set_trail_percent(self, value: str):
        try:
            self.trail_percent = float(value)
        except ValueError:
            pass

    def set_stop_type(self, value: str):
        self.stop_type = value

    def set_limit_offset(self, value: str):
        try:
            self.limit_offset = float(value)
        except ValueError:
            pass

    def create_group(self):
        """Create a new group from selected positions with quantities."""
        logger.debug(f"create_group called: selected_quantities={self.selected_quantities}")

        if not self.selected_quantities:
            self.status_message = "No positions selected"
            return

        if not self.new_group_name.strip():
            self.status_message = "Enter a group name"
            return

        # Convert string keys to int and apply sign from portfolio positions
        # This ensures position_quantities stores SIGNED values (positive=long, negative=short)
        # Also extract leg data for strategy classification
        position_quantities = {}
        leg_data = []
        for k, v in self.selected_quantities.items():
            con_id = int(k)
            # Find portfolio position to get the sign and leg info
            portfolio_qty = 0
            pos_data = None
            for pos in self.positions:
                if pos["con_id"] == con_id:
                    portfolio_qty = pos["quantity"]
                    pos_data = pos
                    break
            # Apply sign: if portfolio is short (negative), make allocated qty negative
            signed_qty = -abs(v) if portfolio_qty < 0 else abs(v)
            position_quantities[con_id] = signed_qty
            logger.debug(f"Position {con_id}: portfolio_qty={portfolio_qty}, allocated={v}, signed={signed_qty}")

            # Extract leg data for strategy classification
            if pos_data:
                strike_str = pos_data.get("strike_str", "-")
                try:
                    strike = float(strike_str) if strike_str not in ("-", "") else 0.0
                except ValueError:
                    strike = 0.0
                side_str = pos_data.get("side_str", "-")
                right = side_str if side_str in ("C", "P") else ""
                expiry = pos_data.get("expiry", "-")
                if expiry == "-":
                    expiry = ""
                leg_data.append({
                    "strike": strike,
                    "right": right,
                    "quantity": signed_qty,
                    "expiry": expiry,
                })

        # Calculate initial value and determine if credit position
        con_ids = list(position_quantities.keys())
        metrics = self._calc_group_metrics(con_ids, position_quantities, "mark")
        is_credit = metrics.get("is_credit", False)
        # Use trigger_value (per-contract price) for HWM, NOT net_value (which includes multiplier)
        trigger_value = metrics.get("trigger_value", 0)
        # Entry price per unit (immutable after creation)
        entry_price = metrics.get("entry_price", 0)

        # Create via GroupManager (persisted to JSON)
        group = GROUP_MANAGER.create(
            name=self.new_group_name.strip(),
            position_quantities=position_quantities,
            trail_value=self.trail_percent,  # Use state default
            trail_mode="percent",  # Default mode
            stop_type=self.stop_type,
            limit_offset=self.limit_offset,
            initial_value=trigger_value,  # Per-contract price for correct stop calculation
            is_credit=is_credit,  # Immutable after creation
            entry_price=entry_price,  # Immutable after creation
            leg_data=leg_data,  # For strategy classification
        )

        # Refresh positions if connected (don't clear if disconnected)
        if BROKER.is_connected():
            self._refresh_positions()
            self._compute_position_rows()
        self._load_groups_from_manager()

        # Initialize chart state for new group
        self._init_chart_state(group.id)

        self.selected_quantities = {}
        self.new_group_name = ""
        self.status_message = f"Group '{group.name}' created"
        logger.info(f"Group created: '{group.name}' with {len(position_quantities)} positions, trigger=${trigger_value:.2f}")

    def _load_groups_from_manager(self, metrics_cache: dict = None):
        """Load groups from GroupManager into state for UI.

        Args:
            metrics_cache: Optional dict of pre-computed metrics {group_id: metrics}
                          to avoid double computation in tick_update()
        """
        self.groups = []
        for g in GROUP_MANAGER.get_all():
            # Calculate current value (simple)
            value = self._calc_group_value(g.con_ids)
            # Use cached metrics if available, otherwise compute
            if metrics_cache and g.id in metrics_cache:
                metrics = metrics_cache[g.id]
            else:
                metrics = self._calc_group_metrics(g.con_ids, g.position_quantities, g.trigger_price_type, group=g)
            # Get logical unit count from metrics (GCD of quantities)
            # e.g., 2 spreads with +2/-2 → num_units=2
            total_allocated_qty = metrics.get("num_units", 1)

            # Format trail value display based on mode
            if g.trail_mode == "percent":
                trail_display = f"{g.trail_value}%"
            else:
                trail_display = f"${g.trail_value}"

            # Calculate group market status (worst case of all positions)
            group_market_status = "Unknown"
            found_position = False
            for pos in self.positions:
                if pos["con_id"] in g.con_ids:
                    found_position = True
                    pos_status = pos.get("market_status", "Unknown")
                    if pos_status == "Open":
                        group_market_status = "Open"
                    elif pos_status == "Closed":
                        group_market_status = "Closed"
                        break
            # If positions found but none had status, default to Unknown
            if not found_position:
                group_market_status = "Unknown"

            # Use STORED values from group for immutable fields (is_credit, entry_price)
            # Use LIVE values from metrics for dynamic fields (bid, ask, mark, greeks, pnl)
            # Use STORED values from group for HWM/Stop (updated by trailing logic)
            self.groups.append({
                "id": g.id,
                "name": g.name,
                "con_ids": g.con_ids,
                "positions_str": ", ".join(str(c) for c in g.con_ids),
                "total_qty": total_allocated_qty,
                "total_qty_str": f"{total_allocated_qty} qty",
                "market_status": group_market_status,
                # Trailing Stop config
                "trail_enabled": g.trail_enabled,
                "trail_mode": g.trail_mode,
                "trail_value": g.trail_value,
                "trail_display": trail_display,
                "trail_percent": g.trail_value,  # Backwards compat for UI
                "trail_percent_str": trail_display,
                "trigger_price_type": g.trigger_price_type,
                "stop_type": g.stop_type,
                "limit_offset": g.limit_offset,
                "limit_offset_str": f"${g.limit_offset:.2f}",
                # Time Exit config
                "time_exit_enabled": g.time_exit_enabled,
                "time_exit_time": g.time_exit_time,
                # Runtime state
                "is_active": g.is_active,
                # HWM/Stop from STORED group (updated by trailing logic in tick_update)
                "high_water_mark": g.high_water_mark,
                "hwm_str": f"${abs(g.high_water_mark):.2f}" if g.high_water_mark != 0 else "-",
                "stop_price": g.stop_price,
                "stop_str": f"${abs(g.stop_price):.2f}" if g.stop_price != 0 else "-",
                # Limit price: calculated from stop + offset
                "trail_limit_price": g.stop_price + g.limit_offset if g.is_credit else g.stop_price - g.limit_offset if g.stop_price != 0 else 0,
                "limit_str": f"${abs(g.stop_price + g.limit_offset if g.is_credit else g.stop_price - g.limit_offset):.2f}" if g.stop_price != 0 else "-",
                # Trigger value from LIVE metrics (current price)
                "trigger_value": metrics.get("trigger_value", 0),
                "trigger_value_str": f"${abs(metrics.get('trigger_value', 0)):.2f}",
                "current_value": value,
                "value_str": f"${value:.2f}",
                # Metrics - Legs info from LIVE
                "legs_str": metrics["legs_str"],
                # Per-leg aggregated values from LIVE
                "mark_value_str": metrics["mark_value_str"],
                "mid_value_str": metrics["mid_value_str"],
                # Spread-level Natural Bid/Ask from LIVE
                "spread_bid_str": metrics["spread_bid_str"],
                "spread_ask_str": metrics["spread_ask_str"],
                # Entry price from STORED group (immutable)
                "entry_price": g.entry_price,
                "cost_str": f"${abs(g.entry_price):.2f}",
                # PnL from LIVE metrics
                "pnl_mark": metrics["pnl_mark"],
                "pnl_mark_str": metrics["pnl_mark_str"],
                "pnl_color": "green" if metrics["pnl_mark"] >= 0 else "red",
                "pnl_close": metrics["pnl_close"],
                "pnl_close_str": metrics["pnl_close_str"],
                # Greeks from LIVE metrics
                "delta": metrics["delta"],
                "delta_str": metrics["delta_str"],
                "gamma": metrics["gamma"],
                "gamma_str": metrics["gamma_str"],
                "theta": metrics["theta"],
                "theta_str": metrics["theta_str"],
                "vega": metrics["vega"],
                "vega_str": metrics["vega_str"],
                # Position type from STORED group (immutable)
                "is_credit": g.is_credit,
                # Strategy classification
                "strategy_tag": g.strategy_tag or "Custom",
                # Statistics
                "modification_count": g.modification_count,
            })

        # Always update groups_sorted - it's needed for Monitor tab display
        # The sorting itself is cheap, the expensive part was metrics computation (now cached)
        self._compute_groups_sorted()

    def _calc_group_value(self, con_ids: list[int]) -> float:
        """Calculate total value of positions in group."""
        total = 0.0
        for pos in self.positions:
            if pos["con_id"] in con_ids:
                # Use net_value which already includes multiplier
                total += pos["net_value"]
        return round(total, 2)

    def _get_group_hwm(self, group_id: str, fallback_value: float = 0) -> float:
        """Get trigger-based HWM from chart_data, or fallback to current trigger_value."""
        if group_id in self.chart_data:
            hwm = self.chart_data[group_id].get("current_hwm", 0)
            if hwm != 0:  # Allow negative HWM for credit spreads
                return hwm
        return fallback_value

    def _get_group_stop(self, group_id: str, trail_mode: str, trail_value: float,
                        fallback_value: float = 0, is_credit: bool = False) -> float:
        """Get trigger-based stop price from chart_data HWM."""
        hwm = self._get_group_hwm(group_id, fallback_value)
        if hwm != 0:  # Allow negative HWM for credit spreads
            return calculate_stop_price(hwm, trail_mode, trail_value, is_credit=is_credit)
        return 0.0

    def _is_group_market_open(self, con_ids: list[int]) -> bool:
        """Check if all markets for a group's positions are open."""
        for pos in self.positions:
            if pos["con_id"] in con_ids:
                if pos.get("market_status") == "Closed":
                    return False
        return True

    def _calc_group_metrics(self, con_ids: list[int], position_quantities: dict = None,
                            trigger_price_type: str = "mid", group=None) -> dict:
        """Calculate detailed metrics for a group including trailing stop values.

        Args:
            con_ids: List of contract IDs in the group
            position_quantities: Optional dict mapping con_id_str -> allocated qty
            trigger_price_type: Price type for trailing stop trigger (mark, mid, bid, ask, last)
            group: Optional Group object for trailing stop calculation
        """
        # Build leg data from positions
        legs = []
        for pos in self.positions:
            if pos["con_id"] in con_ids:
                strike_str = pos["strike_str"]
                side_str = pos.get("side_str", "")  # "C" or "P"
                # Use allocated quantity if provided (already signed), else use portfolio quantity
                con_id_str = str(pos["con_id"])
                if position_quantities:
                    # position_quantities is already signed (positive=long, negative=short)
                    allocated_qty = position_quantities.get(con_id_str, pos["quantity"])
                else:
                    allocated_qty = pos["quantity"]

                leg = LegData(
                    con_id=pos["con_id"],
                    symbol=pos["symbol"],
                    sec_type=pos["sec_type"],
                    expiry=pos["expiry"] if pos["expiry"] != "-" else "",
                    strike=float(strike_str) if strike_str not in ("-", "") else 0.0,
                    right=side_str if side_str in ("C", "P") else "",
                    quantity=allocated_qty,  # Use allocated qty
                    multiplier=pos["multiplier"],
                    fill_price=pos["fill_price"],
                    bid=pos["bid"],
                    ask=pos["ask"],
                    mid=pos["mid"],
                    mark=pos["mark"],
                    delta=pos.get("delta", 0.0),
                    gamma=pos.get("gamma", 0.0),
                    theta=pos.get("theta", 0.0),
                    vega=pos.get("vega", 0.0),
                )
                legs.append(leg)

        # Get current HWM from chart_data if group provided
        current_hwm = 0.0
        market_open = True
        if group and group.id in self.chart_data:
            current_hwm = self.chart_data[group.id].get("current_hwm", 0)
            # Check if markets are open for this group
            market_open = self._is_group_market_open(group.con_ids)

        # Compute metrics with trigger price type and trailing stop params
        metrics = compute_group_metrics(
            legs=legs,
            trigger_price_type=trigger_price_type,
            trail_mode=group.trail_mode if group else None,
            trail_value=group.trail_value if group else 0,
            current_hwm=current_hwm,
            stop_type=group.stop_type if group else "market",
            limit_offset=group.limit_offset if group else 0,
            market_open=market_open,
        )

        # Build leg info for UI display
        leg_infos = []
        for leg in legs:
            leg_infos.append({
                "name": leg.display_name,
                "info_line": leg.info_line,
                "qty": f"{leg.quantity:+g}",  # +1 or -1
                "type": leg.position_type,
                "fill": f"${leg.fill_price:.2f}",
                "mark": f"${leg.mark:.2f}",
                "mid": f"${leg.mid:.2f}" if leg.mid > 0 else "-",
                "bid": f"${leg.bid:.2f}" if leg.bid > 0 else "-",
                "ask": f"${leg.ask:.2f}" if leg.ask > 0 else "-",
                "delta": f"{leg.delta:.2f}",
            })

        # Format legs as string for display (use info_line from LegData)
        legs_str = "\n".join(leg.info_line for leg in legs) if legs else "No legs"

        return {
            "legs": leg_infos,
            "legs_str": legs_str,
            # Position type info
            "position_type": metrics.position_type,
            "is_credit": metrics.is_credit,
            # Per-unit prices (always positive, like option chain)
            "mark": metrics.mark,
            "mark_str": metrics.mark_str,
            "mid": metrics.mid,
            "mid_str": metrics.mid_str,
            "bid": metrics.bid,
            "bid_str": metrics.bid_str,
            "ask": metrics.ask,
            "ask_str": metrics.ask_str,
            "entry": metrics.entry,
            "entry_str": metrics.entry_str,
            # Trigger value for trailing stop
            "trigger_value": metrics.trigger_value,
            "trigger_value_str": metrics.trigger_value_str,
            "trigger_price_type": trigger_price_type,
            # Total position values (with qty * multiplier)
            "total_current_value": metrics.total_current_value,
            "total_entry_cost": metrics.total_entry_cost,
            # P&L
            "pnl": metrics.pnl,
            "pnl_str": metrics.pnl_str,
            # Greeks (aggregated for group)
            "delta": metrics.delta,
            "delta_str": metrics.delta_str,
            "gamma": metrics.gamma,
            "gamma_str": metrics.gamma_str,
            "theta": metrics.theta,
            "theta_str": metrics.theta_str,
            "vega": metrics.vega,
            "vega_str": metrics.vega_str,
            # Legacy compatibility (for existing code that uses old field names)
            "mark_value": metrics.mark,
            "mark_value_str": metrics.mark_str,
            "mid_value": metrics.mid,
            "mid_value_str": metrics.mid_str,
            "spread_bid": metrics.bid,
            "spread_bid_str": metrics.bid_str,
            "spread_ask": metrics.ask,
            "spread_ask_str": metrics.ask_str,
            "entry_price": metrics.entry,
            "entry_price_str": metrics.entry_str,
            "total_cost": metrics.total_entry_cost,
            "cost_str": metrics.entry_str,
            "pnl_mark": metrics.pnl,
            "pnl_mark_str": metrics.pnl_str,
            "pnl_mid": metrics.pnl,
            "pnl_close": metrics.pnl,
            "pnl_close_str": metrics.pnl_str,
            # Trailing Stop fields (from centralized calculation in metrics.py)
            "current_hwm": metrics.current_hwm,
            "updated_hwm": metrics.updated_hwm,
            "hwm_updated": metrics.hwm_updated,
            "trail_stop_price": metrics.trail_stop_price,
            "trail_limit_price": metrics.trail_limit_price,
            "stop_pnl": metrics.stop_pnl,
            "stop_pnl_str": metrics.stop_pnl_str,
        }

    def _get_trigger_value(self, metrics, trigger_price_type: str) -> float:
        """Get the trigger value based on trigger_price_type.

        Args:
            metrics: GroupMetrics object from compute_group_metrics()
            trigger_price_type: One of "mark", "mid", "bid", "ask", "last"

        Returns:
            The appropriate value for trailing stop calculations
        """
        # trigger_value is now calculated in compute_group_metrics()
        return metrics.trigger_value

    def delete_group(self, group_id: str):
        """Delete a group."""
        GROUP_MANAGER.delete(group_id)
        # Sync connection state and refresh positions
        self._sync_broker_state()
        self._load_groups_from_manager()
        # Remove chart data for deleted group
        if group_id in self.chart_data:
            new_data = {k: v for k, v in self.chart_data.items() if k != group_id}
            self.chart_data = new_data
        self.status_message = "Group deleted"

    # === Nuitka Workaround: Slot-based handlers for static button rendering ===
    # Partial application with Vars doesn't work in Nuitka bundles.
    # Instead, we use slot indices (Python ints) which are bound at compile time.

    def _get_group_id_for_slot(self, slot_idx: int) -> str | None:
        """Get the group_id for a slot index, or None if slot is empty."""
        if 0 <= slot_idx < len(self.groups):
            return self.groups[slot_idx].get("id")
        return None

    def toggle_slot(self, slot_idx: int):
        """Toggle group at slot index. Called from static slot buttons."""
        group_id = self._get_group_id_for_slot(slot_idx)
        if group_id:
            logger.info(f"toggle_slot({slot_idx}) -> group_id={group_id}")
            self.toggle_group_active(group_id)

    def cancel_slot(self, slot_idx: int):
        """Cancel order for group at slot index."""
        group_id = self._get_group_id_for_slot(slot_idx)
        if group_id:
            logger.info(f"cancel_slot({slot_idx}) -> group_id={group_id}")
            self.cancel_group_order(group_id)

    def delete_slot(self, slot_idx: int):
        """Delete group at slot index (shows confirmation dialog)."""
        group_id = self._get_group_id_for_slot(slot_idx)
        if group_id:
            logger.info(f"delete_slot({slot_idx}) -> group_id={group_id}")
            self.request_delete_group(group_id)

    def update_trail_slot(self, slot_idx: int, value):
        """Update trail value for group at slot index."""
        group_id = self._get_group_id_for_slot(slot_idx)
        if group_id:
            self.update_group_trail(group_id, value)

    def update_trail_mode_slot(self, slot_idx: int, value):
        """Update trail mode for group at slot index."""
        group_id = self._get_group_id_for_slot(slot_idx)
        if group_id:
            self.update_group_trail_mode(group_id, value)

    def update_trigger_price_type_slot(self, slot_idx: int, value):
        """Update trigger price type for group at slot index."""
        group_id = self._get_group_id_for_slot(slot_idx)
        if group_id:
            self.update_group_trigger_price_type(group_id, value)

    def update_stop_type_slot(self, slot_idx: int, value):
        """Update stop type for group at slot index."""
        group_id = self._get_group_id_for_slot(slot_idx)
        if group_id:
            self.update_group_stop_type(group_id, value)

    def update_limit_offset_slot(self, slot_idx: int, value):
        """Update limit offset for group at slot index."""
        group_id = self._get_group_id_for_slot(slot_idx)
        if group_id:
            self.update_group_limit_offset(group_id, value)

    def update_time_exit_enabled_slot(self, slot_idx: int, checked):
        """Update time exit enabled for group at slot index."""
        group_id = self._get_group_id_for_slot(slot_idx)
        if group_id:
            self.update_group_time_exit_enabled(group_id, checked)

    def update_time_exit_time_slot(self, slot_idx: int, value):
        """Update time exit time for group at slot index."""
        group_id = self._get_group_id_for_slot(slot_idx)
        if group_id:
            self.update_group_time_exit_time(group_id, value)

    def toggle_collapsed_slot(self, slot_idx: int):
        """Toggle collapsed state for group at slot index."""
        group_id = self._get_group_id_for_slot(slot_idx)
        if group_id:
            self.toggle_group_collapsed(group_id)

    def select_group_slot(self, slot_idx: int):
        """Select group at slot index for chart display."""
        group_id = self._get_group_id_for_slot(slot_idx)
        if group_id:
            self.select_group(group_id)

    def toggle_group_active(self, group_id: str):
        """Toggle group monitoring on/off - places/cancels orders at TWS."""
        import time as time_module

        # === DOUBLE-CLICK PREVENTION ===
        now = time_module.time()
        if group_id in self._activation_in_progress:
            last_activation = self._activation_in_progress[group_id]
            if now - last_activation < 2.0:  # 2 second cooldown
                logger.warning(f"Double-click prevented for group {group_id}")
                self.status_message = "Please wait..."
                return

        # Mark activation in progress
        new_progress = dict(self._activation_in_progress)
        new_progress[group_id] = now
        self._activation_in_progress = new_progress

        # Sync connection state and refresh positions
        self._sync_broker_state()
        group = GROUP_MANAGER.get(group_id)
        if group:
            if group.is_active:
                # Deactivating - cancel orders at TWS
                if group.oca_group_id:
                    BROKER.cancel_oca_group(group.oca_group_id)
                GROUP_MANAGER.deactivate(group_id, clear_orders=True)
                # Clear rate limiting state for this group
                if group_id in self.last_sent_stop_prices:
                    new_sent = dict(self.last_sent_stop_prices)
                    del new_sent[group_id]
                    self.last_sent_stop_prices = new_sent
                self.status_message = f"Deactivated: {group.name}"
            else:
                # Activating - place orders at TWS
                # SAFETY CHECK: Ensure group is not already active (prevent duplicate orders)
                if group.trailing_order_id != 0:
                    logger.warning(f"Group {group.name} already has order {group.trailing_order_id}, skipping activation")
                    self.status_message = f"Group {group.name} already has active order"
                    return

                # Get current metrics for proper stop price calculation
                metrics = self._calc_group_metrics(group.con_ids, group.position_quantities, group.trigger_price_type, group=group)
                trigger_value = metrics.get("trigger_value", 0)
                is_credit = metrics.get("is_credit", False)

                # At activation, ALWAYS use current trigger_value as HWM
                # This ensures the stop is placed relative to CURRENT price, not some old saved HWM
                # The trailing stop logic will update HWM as price moves favorably
                effective_hwm = trigger_value

                logger.info(f"Activation {group.name}: trigger=${trigger_value:.2f} -> HWM=${effective_hwm:.2f} "
                           f"credit={is_credit}")

                # Calculate initial stop and limit prices using effective HWM
                initial_stop_price = calculate_stop_price(
                    effective_hwm, group.trail_mode, group.trail_value, is_credit=is_credit
                )

                # Calculate limit price if using limit order type
                # Credit (BUY to close): limit = stop + offset (willing to pay more)
                # Debit (SELL to close): limit = stop - offset (willing to accept less)
                if group.stop_type == "limit":
                    if is_credit:
                        initial_limit_price = initial_stop_price + group.limit_offset
                    else:
                        initial_limit_price = initial_stop_price - group.limit_offset
                else:
                    initial_limit_price = 0.0  # Stop-Market has no limit

                # Place OCA order group (using new app-controlled stop order)
                # IMPORTANT: Keep sign for BAG contracts (credit spreads have negative prices)
                order_result = BROKER.place_oca_group(
                    group_name=group.name,
                    position_quantities={int(k): v for k, v in group.position_quantities.items()},
                    stop_type=group.stop_type,
                    limit_offset=group.limit_offset,
                    time_exit_enabled=group.time_exit_enabled,
                    time_exit_time=group.time_exit_time,
                    initial_stop_price=initial_stop_price,  # Keep sign for BAG contracts
                    initial_limit_price=initial_limit_price if initial_limit_price else 0.0,
                    trigger_price_type=group.trigger_price_type,
                    is_credit=is_credit,  # BUY to close short, SELL to close long
                )

                if order_result:
                    GROUP_MANAGER.activate(group_id, effective_hwm, order_result, is_credit=is_credit)
                    # Initialize rate limiting state
                    new_sent = dict(self.last_sent_stop_prices)
                    new_sent[group_id] = {
                        "stop": initial_stop_price,  # Keep sign
                        "limit": initial_limit_price if initial_limit_price else 0.0,
                        "timestamp": time.time()
                    }
                    self.last_sent_stop_prices = new_sent
                    self.status_message = f"Activated: {group.name} (Order #{order_result['trailing_order_id']})"
                else:
                    self.status_message = f"Failed to place orders for {group.name}"
                    logger.error(f"Failed to place orders for group {group.name}")

            self._load_groups_from_manager()

    def update_group_trail(self, group_id, value):
        """Update trail value for a group.

        Note: Signature is (group_id, value) for Reflex partial application.
        When called as AppState.update_group_trail(group_id), Reflex calls handler(group_id, event_value).
        """
        try:
            trail = float(value)
            if trail > 0:
                GROUP_MANAGER.update(str(group_id), trail_value=trail)
                # Recalculate stop price based on new trail value
                group = GROUP_MANAGER.get(group_id)
                if group and group.high_water_mark != 0:
                    # Get is_credit dynamically from metrics
                    metrics = self._calc_group_metrics(group.con_ids, group.position_quantities, group.trigger_price_type)
                    is_credit = metrics.get("is_credit", False)
                    new_stop = calculate_stop_price(
                        group.high_water_mark, group.trail_mode, trail, is_credit=is_credit
                    )
                    GROUP_MANAGER.update(group_id, stop_price=new_stop)
                # Sync connection state and refresh positions
                self._sync_broker_state()
                self._load_groups_from_manager()
        except ValueError:
            pass

    def update_group_trail_mode(self, group_id, value):
        """Update trail mode (percent/absolute) for a group.

        Note: Signature is (group_id, value) for Reflex partial application.
        """
        if value in ("percent", "absolute"):
            GROUP_MANAGER.update(str(group_id), trail_mode=value)
            # Recalculate stop price
            group = GROUP_MANAGER.get(group_id)
            if group and group.high_water_mark != 0:
                # Get is_credit dynamically from metrics
                metrics = self._calc_group_metrics(group.con_ids, group.position_quantities, group.trigger_price_type)
                is_credit = metrics.get("is_credit", False)
                new_stop = calculate_stop_price(
                    group.high_water_mark, value, group.trail_value, is_credit=is_credit
                )
                GROUP_MANAGER.update(group_id, stop_price=new_stop)
            self._sync_broker_state()
            self._load_groups_from_manager()

    def update_group_trigger_price_type(self, group_id, value):
        """Update trigger price type for a group.

        Note: Signature is (group_id, value) for Reflex partial application.
        """
        if value in ("mark", "mid", "bid", "ask", "last"):
            GROUP_MANAGER.update(str(group_id), trigger_price_type=value)
            self._sync_broker_state()
            self._load_groups_from_manager()

    def update_group_stop_type(self, group_id, value):
        """Update stop type for a group.

        Note: Signature is (group_id, value) for Reflex partial application.
        When called as AppState.update_group_stop_type(group_id), Reflex calls handler(group_id, event_value).
        """
        logger.debug(f"update_group_stop_type called: group_id={group_id}, value={value}")
        if value in ("market", "limit"):
            GROUP_MANAGER.update(str(group_id), stop_type=value)
            # Sync connection state and refresh positions
            self._sync_broker_state()
            self._load_groups_from_manager()
            logger.debug(f"Group {group_id} stop_type updated to {value}")

    def update_group_limit_offset(self, group_id, value):
        """Update limit offset for a group.

        Note: Signature is (group_id, value) for Reflex partial application.
        """
        logger.debug(f"update_group_limit_offset called: group_id={group_id}, value={value}")
        try:
            offset = float(value)
            if offset >= 0:
                GROUP_MANAGER.update(str(group_id), limit_offset=offset)
                self._sync_broker_state()
                self._load_groups_from_manager()
        except ValueError:
            pass

    def update_group_time_exit_enabled(self, group_id, checked):
        """Toggle time exit enabled for a group.

        Note: Signature is (group_id, value) for Reflex partial application.
        When on_change=handler(group_id), Reflex calls handler(group_id, event_value).
        No type annotations to avoid Reflex type validation issues.
        """
        logger.debug(f"update_group_time_exit_enabled: group_id={group_id}, checked={checked}")
        GROUP_MANAGER.update(str(group_id), time_exit_enabled=bool(checked))
        self._sync_broker_state()
        self._load_groups_from_manager()

    def update_group_time_exit_time(self, group_id, value):
        """Update time exit time for a group.

        Note: Signature is (group_id, value) for Reflex partial application.
        When on_change=handler(group_id), Reflex calls handler(group_id, event_value).
        No type annotations to avoid Reflex type validation issues.
        """
        # Validate HH:MM format
        import re
        if re.match(r'^\d{1,2}:\d{2}$', str(value)):
            GROUP_MANAGER.update(str(group_id), time_exit_time=str(value))
            self._sync_broker_state()
            self._load_groups_from_manager()

    def _sync_broker_state(self):
        """Sync state variables from broker singleton."""
        # Sync is_connected from broker (state var may not persist across handlers)
        self.is_connected = BROKER.is_connected()
        if self.is_connected:
            self.connection_status = "Connected"
            self._refresh_positions()
            self._compute_position_rows()
        else:
            self.connection_status = "Disconnected"
            self.positions = []
            self._compute_position_rows()

    def start_monitoring(self):
        """Start the price monitoring (driven by frontend interval)."""
        self.is_monitoring = True
        self.status_message = "Monitoring active..."
        logger.info("Monitoring started")

    def _refresh_positions(self):
        """Refresh positions from broker - calculate all values ourselves."""
        broker_positions = BROKER.get_positions()
        # Get usage counts from GroupManager
        used_quantities = GROUP_MANAGER.get_used_quantities()
        result = []
        for p in broker_positions:
            # Get multiplier from contract
            multiplier = 1
            if p.raw_contract and hasattr(p.raw_contract, 'multiplier') and p.raw_contract.multiplier:
                try:
                    multiplier = int(p.raw_contract.multiplier)
                except (ValueError, TypeError):
                    multiplier = 100 if p.sec_type in ("OPT", "FOP") else 1
            else:
                multiplier = 100 if p.sec_type in ("OPT", "FOP") else 1

            # Get fill price (entry price from recent executions)
            fill_price = BROKER.get_entry_price(p.con_id)
            # Fallback to avg_cost / multiplier if no fill price
            if fill_price <= 0:
                fill_price = p.avg_cost / multiplier if multiplier > 0 else p.avg_cost

            # Get live quote data (bid, ask, last, mid, mark, greeks) from reqMktData
            quote = BROKER.get_quote_data(p.con_id)
            bid = quote["bid"]
            ask = quote["ask"]
            last = quote["last"]
            mid = quote["mid"]
            # Mark price from ticker.markPrice, fallback to portfolio
            mark = quote["mark"] if quote["mark"] > 0 else p.market_price
            # Greeks
            delta = quote.get("delta", 0.0)
            gamma = quote.get("gamma", 0.0)
            theta = quote.get("theta", 0.0)
            vega = quote.get("vega", 0.0)

            # Calculate net cost (fill_price * abs(qty) * multiplier) - always positive
            net_cost = fill_price * abs(p.quantity) * multiplier

            # Calculate net value using mark price (same as TWS)
            # For Long: positive value, For Short: negative value
            net_value = mark * p.quantity * multiplier

            # Calculate PnL correctly for Long and Short positions:
            # Long (qty > 0):  P&L = (mark - fill) × qty × mult  (profit if mark > fill)
            # Short (qty < 0): P&L = (fill - mark) × |qty| × mult (profit if mark < fill)
            # Simplified: P&L = (mark - fill) × qty × mult (qty is negative for short)
            pnl = (mark - fill_price) * p.quantity * multiplier

            # Calculate quantity usage across groups
            total_qty = abs(p.quantity)
            used_qty = used_quantities.get(p.con_id, 0)
            available_qty = max(0, total_qty - used_qty)
            is_fully_used = available_qty <= 0

            # Format based on position type
            if p.is_combo:
                type_str = f"COMBO ({len(p.combo_legs)} legs)"
                strike_str = "-"
                side_str = "-"
            elif p.sec_type == "OPT":
                type_str = "OPT"
                strike_str = f"{p.strike:g}"
                side_str = p.right  # "C" or "P"
            elif p.sec_type == "FOP":
                type_str = "FOP"
                strike_str = f"{p.strike:g}"
                side_str = p.right  # "C" or "P"
            elif p.sec_type == "STK":
                type_str = "STK"
                strike_str = "-"
                side_str = "-"
            else:
                type_str = p.sec_type
                strike_str = "-"
                side_str = "-"

            # Use dict instead of PositionData for proper Reflex serialization
            result.append({
                "con_id": p.con_id,
                "symbol": p.symbol,
                "sec_type": p.sec_type,
                "type_str": type_str,
                "expiry": p.expiry or "-",
                "strike_str": strike_str,
                "side_str": side_str,
                "quantity": p.quantity,
                "quantity_str": f"{p.quantity:g}",
                "fill_price": fill_price,
                "fill_price_str": f"${fill_price:.2f}",
                "bid": bid,
                "bid_str": f"${bid:.2f}" if bid > 0 else "-",
                "mid": mid,
                "mid_str": f"${mid:.2f}" if mid > 0 else "-",
                "ask": ask,
                "ask_str": f"${ask:.2f}" if ask > 0 else "-",
                "last": last,
                "last_str": f"${last:.2f}" if last > 0 else "-",
                "mark": mark,
                "mark_str": f"${mark:.2f}",
                "net_cost": net_cost,
                "net_cost_str": f"${net_cost:.2f}",
                "net_value": net_value,
                "net_value_str": f"${net_value:.2f}",
                "pnl": pnl,
                "pnl_str": f"${pnl:.2f}",
                "pnl_color": "green" if pnl >= 0 else "red",
                "multiplier": multiplier,
                "is_combo": p.is_combo,
                # Don't store raw combo_legs - they're not JSON serializable
                "combo_legs": [],
                # Quantity tracking across groups
                "used_qty": used_qty,
                "available_qty": available_qty,
                "is_fully_used": is_fully_used,
                "qty_usage_str": f"{used_qty}/{int(total_qty)}",
                # Dropdown options for SEL (0 to available_qty as strings)
                "qty_options": [str(i) for i in range(0, int(available_qty) + 1)] if available_qty > 0 else ["0"],
                # Greeks
                "delta": delta,
                "gamma": gamma,
                "theta": theta,
                "vega": vega,
                # Market status
                "market_open": BROKER.is_market_open(p.con_id),
                "market_status": BROKER.get_market_status(p.con_id),
            })

        # Log first position to verify live data
        if result:
            pos = result[0]
            logger.debug(f"LIVE: {pos['symbol']} fill=${pos['fill_price']:.2f} bid={pos['bid_str']} ask={pos['ask_str']} last={pos['last_str']} mark=${pos['mark']:.2f} pnl=${pos['pnl']:.2f}")

        self.positions = result

    def stop_monitoring(self):
        """Stop the monitoring loop."""
        self.is_monitoring = False
        logger.info("Monitoring stop requested")

    def tick_update(self, _=None):
        """Called by frontend interval - refresh positions and force UI update.

        New optimized version:
        - Metrics cached to avoid double computation
        - Chart accumulation every tick (in-place)
        - Bar completion every 3 min (BAR_INTERVAL_TICKS)
        - Chart rendering every 1 sec (CHART_RENDER_INTERVAL)
        """
        tick_start = time.perf_counter()
        timings = {}  # Track timing for each step

        # 1. Sync connection status from broker
        t0 = time.perf_counter()
        broker_connected = BROKER.is_connected()
        broker_status = BROKER.get_connection_status()

        # Always sync status string (shows reconnect progress)
        if broker_status != self.connection_status:
            self.connection_status = broker_status
            # Log status changes for visibility
            logger.debug(f"Connection status: {broker_status}")

        if broker_connected != self.is_connected:
            self.is_connected = broker_connected
            if broker_connected:
                self.is_monitoring = True
                self.status_message = "Connected - refreshing positions..."
                # Initialize chart states for all groups
                self._init_all_chart_states()
                # Load underlying history if group selected
                if self.selected_group_id:
                    self._load_group_chart_data(self.selected_group_id)
        timings["1_broker_sync"] = (time.perf_counter() - t0) * 1000

        if not self.is_connected or not self.is_monitoring:
            return

        # 2. Refresh positions (necessary for price data)
        t0 = time.perf_counter()
        self._refresh_positions()

        # UI OPTIMIZATION: Throttle position_rows computation
        # Only update UI every UI_POSITION_THROTTLE_INTERVAL ticks OR when dirty flag set
        # Trading logic in _refresh_positions() still runs every tick!
        self._ui_tick_counter += 1
        should_update_position_ui = (self._ui_tick_counter % UI_POSITION_THROTTLE_INTERVAL == 0) or self._ui_dirty
        if should_update_position_ui:
            self._compute_position_rows()
            if self._ui_dirty:
                self._ui_dirty = False  # Clear dirty flag after update

        self.refresh_tick += 1
        timings["2_refresh_pos"] = (time.perf_counter() - t0) * 1000

        now = datetime.now()
        now_str = now.strftime("%H:%M:%S")
        self.status_message = f"Monitoring... ({now_str})"

        # 3. Process all groups with metrics cache
        t0 = time.perf_counter()
        metrics_cache = {}
        for g in GROUP_MANAGER.get_all():
            value = self._calc_group_value(g.con_ids)
            metrics = self._calc_group_metrics(g.con_ids, g.position_quantities, g.trigger_price_type, group=g)
            metrics_cache[g.id] = metrics

            # Accumulate tick into current bar (in-place, fast)
            self._accumulate_tick(g.id, metrics)

            # Check if all markets for this group are open
            group_market_open = True
            for pos in self.positions:
                if pos["con_id"] in g.con_ids:
                    if pos.get("market_status") == "Closed":
                        group_market_open = False
                        break

            # Check stop trigger for active groups
            # IMPORTANT: Only update HWM and check triggers when market is OPEN
            if g.is_active:
                if group_market_open:
                    is_credit = metrics.get("is_credit", False)
                    trigger_value = metrics.get("trigger_value", 0)

                    # NOTE: Use trigger_value (per-contract price) NOT value (total net value)
                    # trigger_value is based on trigger_price_type (mark/mid/bid/ask/last)
                    # value is net_value = price × qty × multiplier (much larger!)

                    # DEBUG: Log every check to track deactivation issue
                    logger.debug(f"TRAIL CHECK {g.name}: trigger_value=${trigger_value:.2f} "
                                f"HWM=${g.high_water_mark:.2f} Stop=${g.stop_price:.2f} "
                                f"credit={is_credit}")

                    # Update HWM with is_credit flag for proper comparison
                    GROUP_MANAGER.update_hwm(g.id, trigger_value, is_credit=is_credit)

                    # Check if stop triggered (for logging only)
                    # NOTE: We do NOT deactivate here! The IBKR order is the real stop.
                    # The app only monitors and logs. IBKR decides when to execute.
                    if GROUP_MANAGER.check_stop_triggered(g.id, trigger_value, is_credit=is_credit):
                        logger.warning(f"STOP NEAR: {g.name} trigger=${trigger_value:.2f} "
                                      f"stop=${g.stop_price:.2f} credit={is_credit}")
                        self.status_message = f"STOP NEAR: {g.name} at ${trigger_value:.2f}!"
                        # DO NOT deactivate - let IBKR order handle it

                    # === APP-CONTROLLED TRAILING: Sync TWS order with current stop price ===
                    # Always check (rate limiting is inside the method)
                    # This ensures TWS order stays in sync with groups.json
                    self._check_and_modify_orders(g.id, metrics)
        timings["3_groups_metrics"] = (time.perf_counter() - t0) * 1000

        # 4. Bar completion every 3 min (BAR_INTERVAL_TICKS = 360)
        t0 = time.perf_counter()
        if self.refresh_tick > 0 and (self.refresh_tick % BAR_INTERVAL_TICKS) == 0:
            self._complete_bars()

            # Update underlying history on bar completion
            if self.selected_group_id:
                symbol = self.selected_underlying_symbol
                logger.debug(f"Bar completion: updating underlying chart for {symbol}")
                if symbol and symbol in self.underlying_history:
                    new_bar = BROKER.fetch_latest_underlying_bar(symbol)
                    if new_bar:
                        logger.debug(f"Got new underlying bar: {new_bar.get('date')}")
                        new_hist = dict(self.underlying_history)
                        bars = list(new_hist.get(symbol, []))
                        if bars and bars[-1].get("date") == new_bar.get("date"):
                            bars[-1] = new_bar
                        else:
                            bars.append(new_bar)
                            if len(bars) > 500:
                                bars = bars[-500:]
                        new_hist[symbol] = bars
                        self.underlying_history = new_hist
        timings["4_bar_complete"] = (time.perf_counter() - t0) * 1000

        # 5. Chart rendering every 1 sec (CHART_RENDER_INTERVAL = 2 ticks)
        t0 = time.perf_counter()
        if (self.refresh_tick % CHART_RENDER_INTERVAL) == 0 and self.selected_group_id:
            self._render_all_charts()
        timings["5_chart_render"] = (time.perf_counter() - t0) * 1000

        # 6. Reload groups with cached metrics (no double computation)
        t0 = time.perf_counter()
        self._load_groups_from_manager(metrics_cache)
        timings["6_reload_groups"] = (time.perf_counter() - t0) * 1000

        # Performance logging
        elapsed_ms = (time.perf_counter() - tick_start) * 1000

        # DEBUG: Detailed breakdown every 20 ticks or when slow
        if self.refresh_tick % 20 == 0 or elapsed_ms > 200:
            breakdown = " | ".join(f"{k}:{v:.0f}" for k, v in timings.items() if v > 1)
            logger.debug(f"tick #{self.refresh_tick}: {elapsed_ms:.0f}ms | {breakdown}")

        # INFO: Summary every 60 ticks (~30s)
        if self.refresh_tick % 60 == 0:
            n_positions = len(self.positions)
            n_groups = len(GROUP_MANAGER.get_all())
            n_active = sum(1 for g in GROUP_MANAGER.get_all() if g.is_active)
            logger.info(
                f"Summary #{self.refresh_tick}: {n_positions} positions, "
                f"{n_groups} groups ({n_active} active), {elapsed_ms:.0f}ms/tick"
            )

    # === UI Navigation ===

    def set_active_tab(self, tab: str):
        """Switch between setup and monitor tabs."""
        self.active_tab = tab
        # Auto-collapse all groups when switching to monitor tab
        if tab == "monitor":
            self.collapsed_groups = [g["id"] for g in self.groups]

    def select_group(self, group_id: str):
        """Select a group in monitor view and load chart data."""
        logger.debug(f"select_group called with group_id={group_id}")
        self.selected_group_id = group_id
        # Update underlying symbol (replaces @rx.var)
        self._compute_selected_underlying_symbol()
        # Initialize chart state if not exists
        if group_id not in self.chart_data:
            self._init_chart_state(group_id)
        # Load underlying history for Chart 1
        self._load_group_chart_data(group_id)

    def toggle_group_collapsed(self, group_id: str):
        """Toggle collapsed state of a group card on monitor tab."""
        logger.debug(f"toggle_group_collapsed called with group_id={group_id}")
        new_collapsed = list(self.collapsed_groups)
        if group_id in new_collapsed:
            new_collapsed.remove(group_id)
        else:
            new_collapsed.append(group_id)
        self.collapsed_groups = new_collapsed

    def collapse_all_groups(self):
        """Collapse all groups on monitor tab."""
        all_group_ids = [g["id"] for g in self.groups]
        self.collapsed_groups = all_group_ids

    def expand_all_groups(self):
        """Expand all groups on monitor tab."""
        self.collapsed_groups = []

    def _load_group_chart_data(self, group_id: str):
        """Load underlying historical chart data for a group.

        Note: Position and PnL charts collect data from connect time,
        so we only load the underlying history here.
        """
        group = GROUP_MANAGER.get(group_id)
        logger.debug(f"_load_group_chart_data: group={group}, is_connected={self.is_connected}")
        if not group or not self.is_connected:
            logger.warning(f"_load_group_chart_data: early return - group={group is not None}, connected={self.is_connected}")
            return

        logger.debug(f"_load_group_chart_data: group.con_ids={group.con_ids}, positions count={len(self.positions)}")
        # Get underlying symbol from first position
        if group.con_ids:
            first_con_id = group.con_ids[0]
            for p in self.positions:
                if p["con_id"] == first_con_id:
                    symbol = p["symbol"]
                    break
            else:
                return

            # Fetch underlying history (always refresh to ensure fresh data)
            bars = BROKER.fetch_underlying_history(symbol, "3 D", "3 mins")
            if bars:
                new_hist = dict(self.underlying_history)
                new_hist[symbol] = bars
                self.underlying_history = new_hist
                logger.info(f"Loaded/refreshed {len(bars)} underlying bars for {symbol}")
            else:
                logger.warning(f"Failed to load underlying history for {symbol}")

    # NOTE: _build_position_ohlc_from_history and _build_pnl_history_from_position
    # are no longer used - data is collected from connect time using _accumulate_tick

    # Placeholder for backwards compatibility (remove if not referenced elsewhere)
    def _build_position_ohlc_from_history(self, group, all_leg_bars: dict[int, list[dict]]):
        """DEPRECATED: Position OHLC now collected live from connect time."""
        pass

    def _build_pnl_history_from_position(self, group):
        """DEPRECATED: PnL history now collected live from connect time."""
        pass

    def _compute_selected_underlying_symbol(self):
        """Compute the underlying symbol for the selected group.

        This replaces the @rx.var computed property which doesn't work in Nuitka bundles.
        """
        if not self.selected_group_id:
            self.selected_underlying_symbol = ""
            return
        group = GROUP_MANAGER.get(self.selected_group_id)
        if not group or not group.con_ids:
            self.selected_underlying_symbol = ""
            return
        first_con_id = group.con_ids[0]
        for p in self.positions:
            if p["con_id"] == first_con_id:
                self.selected_underlying_symbol = p["symbol"]
                return
        self.selected_underlying_symbol = ""

    def _compute_groups_sorted(self):
        """Compute groups sorted alphabetically by name for monitor tab.

        This replaces the @rx.var computed property which doesn't work in Nuitka bundles.
        """
        self.groups_sorted = sorted(self.groups, key=lambda g: g.get("name", "").lower())

    # === Chart Rendering Methods (NOT @rx.var - controlled updates) ===

    def _empty_figure(self, message: str) -> go.Figure:
        """Return empty placeholder chart as dict."""
        fig = go.Figure()
        fig.add_annotation(
            text=message,
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False,
            font=dict(size=14, color="#888")
        )
        fig.update_layout(
            height=200,
            margin=dict(l=5, r=50, t=5, b=10),
            paper_bgcolor='rgba(0,0,0,0)',
            plot_bgcolor='rgba(30,30,30,0.8)',
            xaxis=dict(visible=False),
            yaxis=dict(visible=False),
        )
        return fig

    def _generate_12h_labels(self, start_timestamp: float) -> list[str]:
        """Generate 240 time labels for fixed 12h X-axis."""
        labels = []
        start_dt = datetime.fromtimestamp(start_timestamp)
        for i in range(240):
            dt = start_dt + timedelta(minutes=i * 3)
            labels.append(dt.strftime("%H:%M"))
        return labels

    def _slot_to_time_label(self, start_timestamp: float, slot: int) -> str:
        """Convert slot index to time label matching categoryarray."""
        start_dt = datetime.fromtimestamp(start_timestamp)
        dt = start_dt + timedelta(minutes=slot * 3)
        return dt.strftime("%H:%M")

    def _init_chart_state(self, group_id: str):
        """Initialize 240-slot chart arrays for a group."""
        import time
        # HWM starts at 0 - will be set from first trigger_value tick
        # (based on trigger_price_type: mark, mid, bid, ask, or last)

        state = {
            "start_timestamp": time.time(),
            "current_slot": 0,
            "tick_count": 0,  # Ticks since last bar completion
            "position_bars": [None] * 240,  # OHLC bars
            "pnl_bars": [None] * 240,  # PnL bars
            "hwm_bars": [None] * 240,  # HWM per slot for visualization
            "stop_bars": [None] * 240,  # Stop price per slot for visualization
            "limit_bars": [None] * 240,  # Limit price per slot for visualization
            "stop_pnl_bars": [None] * 240,  # Stop P&L per slot for visualization
            "current_pos": None,  # Accumulator for current position bar
            "current_pnl": None,  # Accumulator for current PnL bar
            "current_hwm": 0.0,  # Track HWM based on trigger_value
        }
        new_data = dict(self.chart_data)
        new_data[group_id] = state
        self.chart_data = new_data
        logger.debug(f"Initialized chart state for group {group_id}")

    def _init_all_chart_states(self):
        """Initialize chart state for all groups at connect."""
        for g in GROUP_MANAGER.get_all():
            if g.id not in self.chart_data:
                self._init_chart_state(g.id)

    def _accumulate_tick(self, group_id: str, metrics: dict):
        """Accumulate tick into current bar (in-place update).

        Uses pre-calculated trailing stop values from metrics (computed in metrics.py):
        - updated_hwm: New HWM value (already handles credit/debit and market open check)
        - hwm_updated: True if HWM changed this tick
        - trail_stop_price: Calculated stop price
        - trail_limit_price: Calculated limit price

        Uses trigger_value (based on trigger_price_type: mark, mid, bid, ask, last)
        for OHLC candlesticks.
        """
        trigger_value = metrics.get("trigger_value", 0)
        pnl = metrics.get("pnl_mark", 0)

        # Skip if no valid trigger value (positions not loaded yet)
        if trigger_value == 0:
            return

        if group_id not in self.chart_data:
            self._init_chart_state(group_id)

        state = self.chart_data[group_id]

        # Position OHLC accumulator (uses trigger_value based on trigger_price_type)
        if state["current_pos"] is None:
            state["current_pos"] = {"open": trigger_value, "high": trigger_value, "low": trigger_value, "close": trigger_value}
        else:
            state["current_pos"]["high"] = max(state["current_pos"]["high"], trigger_value)
            state["current_pos"]["low"] = min(state["current_pos"]["low"], trigger_value)
            state["current_pos"]["close"] = trigger_value

        # PnL accumulator (track extremum) - PnL can be 0 or negative, so always update
        if state["current_pnl"] is None:
            state["current_pnl"] = {"pnl_min": pnl, "pnl_max": pnl, "close": pnl}
        else:
            state["current_pnl"]["pnl_min"] = min(state["current_pnl"]["pnl_min"], pnl)
            state["current_pnl"]["pnl_max"] = max(state["current_pnl"]["pnl_max"], pnl)
            state["current_pnl"]["close"] = pnl

        # === TRAILING MECHANISM ===
        # HWM update logic is now centralized in metrics.py
        # Just apply the pre-calculated values
        if metrics.get("hwm_updated", False):
            state["current_hwm"] = metrics["updated_hwm"]
            trigger_type = metrics.get("trigger_price_type", "mid")
            is_credit = metrics.get("is_credit", False)
            direction = "down" if is_credit else "up"
            logger.debug(f"Trailing: HWM ({trigger_type}) updated {direction} -> ${metrics['updated_hwm']:.2f}")

        # === LIVE UPDATE: Store current HWM/Stop/Limit in current slot ===
        # This creates the time-series history for visualization
        slot = state["current_slot"]
        time_label = self._slot_to_time_label(state["start_timestamp"], slot)

        # Use updated_hwm from metrics (falls back to current_hwm in state if not calculated)
        hwm = metrics.get("updated_hwm", 0) or state.get("current_hwm", 0)
        is_credit = metrics.get("is_credit", False)

        # Get group for trail settings
        group = GROUP_MANAGER.get(group_id)
        trail_mode = group.trail_mode if group else "percent"
        trail_value = group.trail_value if group else 10.0
        limit_offset = group.limit_offset if group else 0.0

        # Store DISPLAY values for chart (use abs() for positive display)
        if hwm != 0:
            state["hwm_bars"][slot] = {"time": time_label, "hwm": abs(hwm)}

            # Calculate stop/limit using central function, abs() for display
            stop_price = calculate_stop_price(hwm, trail_mode, trail_value, is_credit)
            if stop_price != 0:
                state["stop_bars"][slot] = {"time": time_label, "stop": abs(stop_price)}

                # Limit price (only for limit orders)
                if is_credit:
                    limit_price = stop_price + limit_offset
                else:
                    limit_price = stop_price - limit_offset
                if limit_price != 0:
                    state["limit_bars"][slot] = {"time": time_label, "limit": abs(limit_price)}

                # Stop P&L (calculated centrally in metrics)
                stop_pnl = metrics.get("stop_pnl", 0)
                if stop_pnl != 0:
                    state["stop_pnl_bars"][slot] = {"time": time_label, "stop_pnl": stop_pnl}

        state["tick_count"] += 1

    def _check_and_modify_orders(self, group_id: str, metrics: dict):
        """Check if order needs modification and send to TWS if changed.

        Rate limiting:
        - Only modify if stop price changed by >= $0.01
        - Minimum 1 second between modifications per group

        Args:
            group_id: Group ID
            metrics: Pre-computed metrics containing trail_stop_price, trail_limit_price
        """
        group = GROUP_MANAGER.get(group_id)
        if not group or not group.is_active or not group.trailing_order_id:
            return

        # Get new stop and limit prices from metrics
        new_stop = metrics.get("trail_stop_price", 0)
        new_limit = metrics.get("trail_limit_price", 0)

        if new_stop == 0:
            return  # No valid stop price calculated

        # For multi-leg combos: apply price sign
        # Credit spread: negative price (SELL @ -$X = pay to close)
        # Debit spread: positive price (SELL @ +$X = receive to close)
        is_multi_leg = len(group.position_quantities) > 1
        if is_multi_leg and group.is_credit:
            new_stop = -abs(new_stop)
            if new_limit:
                new_limit = -abs(new_limit)

        # Rate limiting: check last sent values
        last_sent = self.last_sent_stop_prices.get(group_id, {})
        last_stop = last_sent.get("stop", 0)
        last_limit = last_sent.get("limit", 0)
        last_time = last_sent.get("timestamp", 0)

        # Check if stop price changed significantly (>= $0.01)
        stop_changed = abs(new_stop - last_stop) >= 0.01
        limit_changed = new_limit > 0 and abs(new_limit - last_limit) >= 0.01

        if not stop_changed and not limit_changed:
            return  # No significant change

        # Check minimum time between modifications (1 second)
        now = time.time()
        if now - last_time < 1.0:
            return  # Too fast, skip this tick

        # Modify order at TWS
        # IMPORTANT: Keep sign for BAG contracts (credit spreads have negative prices)
        success = BROKER.modify_stop_order(
            group.trailing_order_id,
            new_stop,  # Keep sign
            new_limit if new_limit else 0.0
        )

        if success:
            # Increment modification counter
            group.modification_count += 1
            GROUP_MANAGER._save()  # Persist the counter

            # Update rate limiting state
            new_sent = dict(self.last_sent_stop_prices)
            new_sent[group_id] = {
                "stop": new_stop,  # Keep sign
                "limit": new_limit if new_limit else 0.0,
                "timestamp": now
            }
            self.last_sent_stop_prices = new_sent
            limit_str = f"${new_limit:.2f}" if new_limit else "N/A"
            logger.debug(f"Modified order for {group.name}: stop=${new_stop:.2f} limit={limit_str} "
                        f"(mod #{group.modification_count})")
        else:
            logger.warning(f"Failed to modify order for {group.name}")

    def _complete_bars(self):
        """Finalize bars, store, advance slot (called every 3 min)."""
        for group_id, state in self.chart_data.items():
            slot = state["current_slot"]
            # Calculate time label from slot (matches categoryarray!)
            time_label = self._slot_to_time_label(state["start_timestamp"], slot)

            # Finalize position bar
            if state["current_pos"]:
                state["position_bars"][slot] = {
                    "time": time_label,
                    "open": state["current_pos"]["open"],
                    "high": state["current_pos"]["high"],
                    "low": state["current_pos"]["low"],
                    "close": state["current_pos"]["close"],
                }

            # Finalize PnL bar (use extremum: min if negative, max if positive)
            if state["current_pnl"]:
                pnl_close = state["current_pnl"]["close"]
                extremum = state["current_pnl"]["pnl_min"] if pnl_close < 0 else state["current_pnl"]["pnl_max"]
                state["pnl_bars"][slot] = {
                    "time": time_label,
                    "pnl": extremum,
                }

            # Finalize HWM and Stop bars for historical visualization (trigger-price based)
            group = GROUP_MANAGER.get(group_id)
            if group:
                hwm = state.get("current_hwm", 0)
                if hwm != 0:
                    # Get is_credit dynamically from metrics
                    metrics = self._calc_group_metrics(group.con_ids, group.position_quantities, group.trigger_price_type)
                    is_credit = metrics.get("is_credit", False)
                    # Store DISPLAY values for chart (abs for positive display)
                    state["hwm_bars"][slot] = {"time": time_label, "hwm": abs(hwm)}
                    stop_price = calculate_stop_price(hwm, group.trail_mode, group.trail_value, is_credit)
                    state["stop_bars"][slot] = {"time": time_label, "stop": abs(stop_price)}

            # Advance slot (wrap around at 240)
            state["current_slot"] = (slot + 1) % 240
            state["tick_count"] = 0

            # Reset accumulators for next bar
            state["current_pos"] = None
            state["current_pnl"] = None

        # Trigger state update
        self.chart_data = dict(self.chart_data)

    def _render_all_charts(self):
        """Render all 3 charts for selected group (called every 1 second)."""
        if not self.selected_group_id:
            self.position_figure = self._empty_figure("Select a group")
            self.pnl_figure = self._empty_figure("Select a group")
            self.underlying_figure = self._empty_figure("Select a group")
            return

        group_id = self.selected_group_id
        # Update underlying symbol for render (replaces @rx.var)
        self._compute_selected_underlying_symbol()
        if group_id not in self.chart_data:
            self._init_chart_state(group_id)

        state = self.chart_data[group_id]

        # Get group data for stop/limit visualization
        group = GROUP_MANAGER.get(group_id)
        group_info = None
        if group:
            # Get metrics for P&L calculation (also provides is_credit)
            metrics = self._calc_group_metrics(group.con_ids, group.position_quantities, group.trigger_price_type, group=group)
            is_credit = metrics.get("is_credit", False)

            # Get trigger-price based HWM from chart state
            hwm = state.get("current_hwm", 0)
            # Calculate stop price based on trigger-price HWM (allow negative for credit spreads)
            stop_price = calculate_stop_price(hwm, group.trail_mode, group.trail_value, is_credit=is_credit) if hwm != 0 else 0

            group_info = {
                # Position OHLC uses trigger-price based values
                "stop_price": stop_price,
                "high_water_mark": hwm,
                "trail_mode": group.trail_mode,
                "trail_value": group.trail_value,
                "stop_type": group.stop_type,
                "limit_offset": group.limit_offset,
                "trigger_price_type": group.trigger_price_type,
                "is_credit": is_credit,
                # Values from centralized metrics calculation
                "total_cost": metrics.get("total_cost", 0.0),
                "pnl_mark": metrics.get("pnl_mark", 0.0),
                "entry_price": metrics.get("entry_price", 0.0),
                "stop_pnl": metrics.get("stop_pnl", 0.0),
                "trail_limit_price": metrics.get("trail_limit_price", 0.0),
                "trigger_value": metrics.get("trigger_value", 0.0),
                # Pre-formatted display strings (use abs for positive display)
                "hwm_str": f"${abs(hwm):.2f}" if hwm != 0 else "-",
                "stop_str": f"${abs(stop_price):.2f}" if stop_price != 0 else "-",
                "limit_str": f"${abs(metrics.get('trail_limit_price', 0)):.2f}" if metrics.get("trail_limit_price", 0) != 0 else "-",
            }

        # Render position chart with stop/limit lines
        self.position_figure = self._render_position_chart(state, group_info)

        # Render PnL chart with stop line
        self.pnl_figure = self._render_pnl_chart(state, group_info)

        # Render underlying chart
        self.underlying_figure = self._render_underlying_chart()

        # === Update chart header info ===
        if group_info:
            # Position OHLC header: Trigger value, Stop, Limit, HWM
            trigger_value = group_info.get("trigger_value", 0)
            hwm = group_info.get("high_water_mark", 0)
            stop_type = group_info.get("stop_type", "market")
            trigger_type = group_info.get("trigger_price_type", "mid")

            # Set trigger label (capitalize first letter)
            self.chart_trigger_label = trigger_type.capitalize()

            # Use display values from group_info (already formatted correctly)
            self.chart_pos_close = f"${abs(trigger_value):.2f}" if trigger_value != 0 else "-"
            self.chart_pos_stop = group_info.get("stop_str", "-")
            self.chart_pos_hwm = group_info.get("hwm_str", "-")
            # Set HWM/LWM label based on position type
            is_credit = group_info.get("is_credit", False)
            self.chart_hwm_label = "LWM" if is_credit else "HWM"
            if stop_type == "limit":
                self.chart_pos_limit = group_info.get("limit_str", "-")
            else:
                self.chart_pos_limit = "-"

            # P&L History header: Current P&L, Stop P&L
            pnl_mark = group_info.get("pnl_mark", 0)
            total_cost = group_info.get("total_cost", 0)
            entry_price = group_info.get("entry_price", 0)
            self.chart_pnl_current = f"${pnl_mark:.2f}" if pnl_mark != 0 else "$0.00"
            # Fill/Entry price (per-contract, like bid/ask) - use abs for display
            self.chart_pos_fill = f"${abs(entry_price):.2f}" if entry_price != 0 else "-"

            # Stop P&L (calculated centrally in metrics)
            stop_pnl = group_info.get("stop_pnl", 0)
            self.chart_pnl_stop = f"${stop_pnl:.2f}" if stop_pnl != 0 else "-"
        else:
            # Reset headers
            self.chart_trigger_label = "Mid"
            self.chart_pos_close = "-"
            self.chart_pos_stop = "-"
            self.chart_pos_limit = "-"
            self.chart_pos_hwm = "-"
            self.chart_hwm_label = "HWM"
            self.chart_pos_fill = "-"
            self.chart_pnl_current = "-"
            self.chart_pnl_stop = "-"

    def _render_position_chart(self, state: dict, group_info: dict = None) -> go.Figure:
        """Render position candlestick chart including current (incomplete) bar.

        Args:
            state: Chart state with bars and current accumulators
            group_info: Group data for stop/limit visualization:
                - stop_price: Current stop price
                - high_water_mark: Current HWM
                - stop_type: "market" or "limit"
                - limit_offset: Offset for limit orders
        """
        # Generate fixed 12h x-axis labels (all 240 slots)
        x_labels = self._generate_12h_labels(state["start_timestamp"])

        # Build arrays for ALL 240 slots (None for empty)
        # Use abs() for display - credit spreads have negative internal values but we show positive
        open_vals = [None] * 240
        high_vals = [None] * 240
        low_vals = [None] * 240
        close_vals = [None] * 240

        # Fill in completed bars
        for i, bar in enumerate(state["position_bars"]):
            if bar is not None:
                open_vals[i] = abs(bar["open"]) if bar["open"] is not None else None
                high_vals[i] = abs(bar["high"]) if bar["high"] is not None else None
                low_vals[i] = abs(bar["low"]) if bar["low"] is not None else None
                close_vals[i] = abs(bar["close"]) if bar["close"] is not None else None

        # Add current (incomplete) bar at current_slot
        slot = state["current_slot"]
        if state["current_pos"]:
            open_vals[slot] = abs(state["current_pos"]["open"]) if state["current_pos"]["open"] is not None else None
            high_vals[slot] = abs(state["current_pos"]["high"]) if state["current_pos"]["high"] is not None else None
            low_vals[slot] = abs(state["current_pos"]["low"]) if state["current_pos"]["low"] is not None else None
            close_vals[slot] = abs(state["current_pos"]["close"]) if state["current_pos"]["close"] is not None else None

        # Check if we have any data
        if all(v is None for v in close_vals):
            return self._empty_figure("Collecting OHLC data...")

        # Get fill price and position type for profit/loss coloring
        # Use abs() for comparison since display values are absolute
        fill_price = abs(group_info.get("entry_price", 0)) if group_info else 0
        is_credit = group_info.get("is_credit", False) if group_info else False

        # Determine colors per bar based on profit/loss vs fill price
        # All values are now positive (abs), so:
        # Credit: close < fill = profit (closer to 0 = we pay less to buy back)
        # Debit: close > fill = profit (value went up)
        # Blue = current incomplete bar
        colors = []
        for i in range(240):
            if close_vals[i] is None:
                colors.append(None)
            elif i == slot:
                # Current incomplete bar - blue
                colors.append('#3B82F6')  # Blue
            elif fill_price != 0:
                if is_credit:
                    # Credit: profit when close < fill (closer to $0 = cheaper to buy back)
                    # e.g., fill=$4.60, close=$3.00 → profit
                    if close_vals[i] <= fill_price:
                        colors.append('#00D26A')  # Green - profit
                    else:
                        colors.append('#FF3B30')  # Red - loss
                else:
                    # Debit: profit when close > fill (higher value)
                    if close_vals[i] >= fill_price:
                        colors.append('#00D26A')  # Green - profit
                    else:
                        colors.append('#FF3B30')  # Red - loss
            else:
                colors.append('#3B82F6')  # Blue - no fill price

        # Create OHLC chart with custom colors using separate traces per color
        fig = go.Figure()

        # Add bars grouped by color
        for color, color_name in [('#00D26A', 'Profit'), ('#FF3B30', 'Loss'), ('#3B82F6', 'Current')]:
            mask_x = []
            mask_open = []
            mask_high = []
            mask_low = []
            mask_close = []
            for i in range(240):
                if colors[i] == color:
                    mask_x.append(x_labels[i])
                    mask_open.append(open_vals[i])
                    mask_high.append(high_vals[i])
                    mask_low.append(low_vals[i])
                    mask_close.append(close_vals[i])

            if mask_x:
                fig.add_trace(go.Candlestick(
                    x=mask_x,
                    open=mask_open,
                    high=mask_high,
                    low=mask_low,
                    close=mask_close,
                    increasing_line_color=color,
                    decreasing_line_color=color,
                    increasing_fillcolor=color,
                    decreasing_fillcolor=color,
                    name=color_name,
                    showlegend=False,
                ))

        # === HISTORICAL LINES: Stop, Limit, HWM as time-series ===
        # Build arrays from historical bars + extend to future with current value

        # Get current values for extending into future
        # Use display values for chart (abs for positive display)
        current_hwm = abs(state.get("current_hwm", 0))
        current_stop = 0
        current_limit = 0
        is_credit = group_info.get("is_credit", False) if group_info else False
        hwm_label = "LWM" if is_credit else "HWM"
        if group_info:
            hwm = state.get("current_hwm", 0)
            trail_mode = group_info.get("trail_mode", "percent")
            trail_value = group_info.get("trail_value", 10.0)
            limit_offset = group_info.get("limit_offset", 0)
            stop_price = calculate_stop_price(hwm, trail_mode, trail_value, is_credit)
            current_stop = abs(stop_price)
            if group_info.get("stop_type") == "limit":
                if is_credit:
                    limit_price = stop_price + limit_offset
                else:
                    limit_price = stop_price - limit_offset
                current_limit = abs(limit_price)

        # HWM line (cyan solid)
        hwm_vals = [None] * 240
        for i, bar in enumerate(state.get("hwm_bars", [])):
            if bar is not None:
                # Values are already stored as abs() - just read them
                hwm_vals[i] = bar.get("hwm") if bar.get("hwm") else None
        # Fill future slots with current value
        for i in range(slot + 1, 240):
            if current_hwm != 0:
                hwm_vals[i] = current_hwm

        if any(v is not None for v in hwm_vals):
            fig.add_trace(go.Scatter(
                x=x_labels,
                y=hwm_vals,
                mode='lines',
                line=dict(color='rgba(0, 191, 255, 0.8)', width=2),  # Cyan #00BFFF
                name=hwm_label,
                hovertemplate=f'{hwm_label}: $%{{y:.2f}}<extra></extra>',
            ))

        # Stop line (red solid, semi-transparent)
        stop_vals = [None] * 240
        for i, bar in enumerate(state.get("stop_bars", [])):
            if bar is not None:
                # Values are already stored as abs() - just read them
                stop_vals[i] = bar.get("stop") if bar.get("stop") else None
        # Fill future slots with current value
        for i in range(slot + 1, 240):
            if current_stop != 0:
                stop_vals[i] = current_stop

        if any(v is not None for v in stop_vals):
            fig.add_trace(go.Scatter(
                x=x_labels,
                y=stop_vals,
                mode='lines',
                line=dict(color='rgba(255, 59, 48, 0.8)', width=2),  # Red #FF3B30
                name='Stop',
                hovertemplate='Stop: $%{y:.2f}<extra></extra>',
            ))

        # Limit line (orange solid, semi-transparent) - only if limit order type
        limit_vals = []  # Initialize empty, will be populated if limit order
        if group_info and group_info.get("stop_type") == "limit":
            limit_vals = [None] * 240
            for i, bar in enumerate(state.get("limit_bars", [])):
                if bar is not None:
                    # Values are already stored as abs() - just read them
                    limit_vals[i] = bar.get("limit") if bar.get("limit") else None
            # Fill future slots with current value
            for i in range(slot + 1, 240):
                if current_limit != 0:
                    limit_vals[i] = current_limit

            if any(v is not None for v in limit_vals):
                fig.add_trace(go.Scatter(
                    x=x_labels,
                    y=limit_vals,
                    mode='lines',
                    line=dict(color='rgba(255, 165, 0, 0.8)', width=2),  # Orange #FFA500
                    name='Limit',
                    hovertemplate='Limit: $%{y:.2f}<extra></extra>',
                ))

        # Fill price line (white dashed) - horizontal line at entry price
        fill_vals = []
        if fill_price != 0:
            fill_vals = [fill_price] * 240
            fig.add_trace(go.Scatter(
                x=x_labels,
                y=fill_vals,
                mode='lines',
                line=dict(color='rgba(255, 255, 255, 0.6)', width=1, dash='dash'),
                name='Fill',
                hovertemplate='Fill: $%{y:.2f}<extra></extra>',
            ))

        # Calculate stable Y-range with 10% padding
        all_y_vals = [v for v in low_vals + high_vals + hwm_vals + stop_vals + limit_vals + fill_vals if v is not None]
        if all_y_vals:
            y_min = min(all_y_vals)
            y_max = max(all_y_vals)
            y_padding = (y_max - y_min) * 0.1 if y_max > y_min else 1.0
            y_range = [y_min - y_padding, y_max + y_padding]
        else:
            y_range = None

        fig.update_layout(
            xaxis_rangeslider_visible=False,
            autosize=True,
            margin=dict(l=5, r=50, t=0, b=25),
            paper_bgcolor='rgba(0,0,0,0)',
            plot_bgcolor='rgba(30,30,30,0.8)',
            uirevision='position_chart',  # Prevents axis reset on data update
            xaxis=dict(
                type='category',
                categoryorder='array',
                categoryarray=x_labels,  # Fixed 12h axis
                showgrid=True,
                gridcolor='rgba(100,100,100,0.3)',
                tickfont=dict(size=10, color='#ccc', family='Arial Black, sans-serif'),
                tickangle=-25,
                nticks=24,
            ),
            yaxis=dict(
                showgrid=True,
                gridcolor='rgba(100,100,100,0.3)',
                tickfont=dict(size=11, color='#ccc', family='Arial Black, sans-serif'),
                side='right',
                range=y_range,
            ),
            showlegend=False,
        )
        return fig

    def _render_pnl_chart(self, state: dict, group_info: dict = None) -> go.Figure:
        """Render PnL bar chart including current (incomplete) bar.

        Args:
            state: Chart state with bars and current accumulators
            group_info: Group data for stop visualization:
                - stop_price: Current stop price (in net value terms)
                - total_cost: Total cost for P&L conversion
        """
        # Generate fixed 12h x-axis labels (all 240 slots)
        x_labels = self._generate_12h_labels(state["start_timestamp"])

        # Build arrays for ALL 240 slots (None for empty)
        pnl_vals = [None] * 240
        colors = ['rgba(0,0,0,0)'] * 240  # Transparent for empty

        # Fill in completed bars
        for i, bar in enumerate(state["pnl_bars"]):
            if bar is not None:
                pnl_vals[i] = bar["pnl"]
                colors[i] = '#00D26A' if bar["pnl"] >= 0 else '#FF3B30'  # Profit/loss from theme

        # Add current (incomplete) bar at current_slot
        slot = state["current_slot"]
        if state["current_pnl"]:
            pnl_close = state["current_pnl"]["close"]
            extremum = state["current_pnl"]["pnl_min"] if pnl_close < 0 else state["current_pnl"]["pnl_max"]
            pnl_vals[slot] = extremum
            colors[slot] = '#00D26A' if extremum >= 0 else '#FF3B30'  # Profit/loss from theme

        # Check if we have any data
        if all(v is None for v in pnl_vals):
            return self._empty_figure("Collecting P&L data...")

        fig = go.Figure(data=[go.Bar(
            x=x_labels,  # All 240 labels
            y=pnl_vals,
            marker_color=colors,
            name="P&L",
        )])

        # Zero line
        fig.add_hline(y=0, line_dash="dash", line_color="#666")

        # === HISTORICAL Stop P&L line (red dashed) ===
        # Build array from historical bars + extend to future with current value

        # Calculate current stop P&L for extending into future
        # Use same logic as metrics.py for consistency
        current_stop_pnl = None
        if group_info and group_info.get("stop_price", 0) != 0:
            stop_price = group_info["stop_price"]
            entry_price = group_info.get("entry_price", 0)
            total_cost = group_info.get("total_cost", 0)
            is_credit = group_info.get("is_credit", False)

            if entry_price != 0:
                if is_credit:
                    # Credit: profit if |stop| < |entry| (bought back cheaper)
                    per_contract_pnl = abs(entry_price) - abs(stop_price)
                else:
                    # Debit: profit if stop > entry (sold higher)
                    per_contract_pnl = stop_price - entry_price
                scale = abs(total_cost / entry_price)
                current_stop_pnl = per_contract_pnl * scale

        # Build historical Stop P&L array
        stop_pnl_vals = [None] * 240
        for i, bar in enumerate(state.get("stop_pnl_bars", [])):
            if bar is not None:
                stop_pnl_vals[i] = bar.get("stop_pnl")
        # Fill future slots with current value
        for i in range(slot + 1, 240):
            if current_stop_pnl is not None:
                stop_pnl_vals[i] = current_stop_pnl

        if any(v is not None for v in stop_pnl_vals):
            fig.add_trace(go.Scatter(
                x=x_labels,
                y=stop_pnl_vals,
                mode='lines',
                line=dict(color='rgba(255, 59, 48, 0.8)', width=2),  # Red #FF3B30
                name='Stop',
                hovertemplate='Stop P&L: $%{y:.2f}<extra></extra>',
            ))

        # Calculate stable Y-range with 15% padding (more for P&L which can swing)
        all_y_vals = [v for v in pnl_vals + stop_pnl_vals if v is not None]
        # Always include 0 in P&L range for reference
        all_y_vals.append(0)
        if all_y_vals:
            y_min = min(all_y_vals)
            y_max = max(all_y_vals)
            y_padding = (y_max - y_min) * 0.15 if y_max > y_min else 10.0
            y_range = [y_min - y_padding, y_max + y_padding]
        else:
            y_range = None

        fig.update_layout(
            autosize=True,
            margin=dict(l=5, r=50, t=0, b=25),
            paper_bgcolor='rgba(0,0,0,0)',
            plot_bgcolor='rgba(30,30,30,0.8)',
            uirevision='pnl_chart',  # Prevents axis reset on data update
            xaxis=dict(
                type='category',
                categoryorder='array',
                categoryarray=x_labels,  # Fixed 12h axis
                showgrid=True,
                gridcolor='rgba(100,100,100,0.3)',
                tickfont=dict(size=10, color='#ccc', family='Arial Black, sans-serif'),
                tickangle=-25,
                nticks=24,
            ),
            yaxis=dict(
                showgrid=True,
                gridcolor='rgba(100,100,100,0.3)',
                tickfont=dict(size=12, color='#ccc', family='Arial Black, sans-serif'),
                side='right',
                range=y_range,
            ),
            showlegend=False,
            bargap=0.1,
        )
        return fig

    def _find_session_breaks(self, data: list[dict], date_key: str = "date", gap_minutes: int = 30) -> list[int]:
        """Find indices where session breaks occur (gaps > gap_minutes)."""
        breaks = []
        for i in range(1, len(data)):
            try:
                prev_time = data[i-1].get(date_key, "")
                curr_time = data[i].get(date_key, "")
                if not prev_time or not curr_time or "T" not in str(prev_time):
                    continue
                prev_dt = datetime.fromisoformat(prev_time)
                curr_dt = datetime.fromisoformat(curr_time)
                gap = (curr_dt - prev_dt).total_seconds() / 60
                if gap > gap_minutes:
                    breaks.append(i)
            except Exception:
                continue
        return breaks

    def _format_relative_time(self, iso_date: str) -> str:
        """Format ISO date as compact relative time: 'T-1: 15:45' or 'T: 09:30'."""
        try:
            # Parse ISO datetime
            dt = datetime.fromisoformat(iso_date.replace('Z', '+00:00'))
            now = datetime.now()

            # Calculate days difference (based on date only)
            today = now.date()
            bar_date = dt.date()
            days_diff = (today - bar_date).days

            time_str = dt.strftime("%H:%M")

            if days_diff == 0:
                return f"T:{time_str}"
            elif days_diff == 1:
                return f"T-1:{time_str}"
            else:
                return f"T-{days_diff}:{time_str}"
        except Exception:
            # Fallback: just show time portion
            return iso_date[-8:-3] if len(iso_date) > 8 else iso_date

    def _render_underlying_chart(self) -> go.Figure:
        """Render underlying candlestick chart."""
        symbol = self.selected_underlying_symbol
        data = self.underlying_history.get(symbol, []) if symbol else []

        if not data:
            msg = "Loading underlying data..." if symbol else "Select a group"
            return self._empty_figure(msg)

        # Format x-axis labels as compact relative time
        x_labels = [self._format_relative_time(d["date"]) for d in data]

        fig = go.Figure(data=[go.Candlestick(
            x=x_labels,
            open=[d["open"] for d in data],
            high=[d["high"] for d in data],
            low=[d["low"] for d in data],
            close=[d["close"] for d in data],
            increasing_line_color='#00D26A',  # Profit green from theme
            decreasing_line_color='#FF3B30',  # Loss red from theme
            increasing_fillcolor='#00D26A',
            decreasing_fillcolor='#FF3B30',
            name=symbol,
        )])

        # Add session break lines
        session_breaks = self._find_session_breaks(data, "date", gap_minutes=30)
        for idx in session_breaks:
            if idx < len(x_labels):
                fig.add_vline(
                    x=x_labels[idx],
                    line_width=1,
                    line_dash="dot",
                    line_color="rgba(255,255,255,0.3)",
                )

        fig.update_layout(
            xaxis_rangeslider_visible=False,
            autosize=True,
            margin=dict(l=5, r=50, t=0, b=25),
            paper_bgcolor='rgba(0,0,0,0)',
            plot_bgcolor='rgba(30,30,30,0.8)',
            xaxis=dict(
                type='category',
                showgrid=True,
                gridcolor='rgba(100,100,100,0.3)',
                tickfont=dict(size=10, color='#ccc', family='Arial Black, sans-serif'),
                tickangle=-25,
                nticks=16,
            ),
            yaxis=dict(
                showgrid=True,
                gridcolor='rgba(100,100,100,0.3)',
                tickfont=dict(size=11, color='#ccc', family='Arial Black, sans-serif'),
                side='right',
            ),
            showlegend=False,
        )
        return fig

    # === Order Management ===

    @rx.event
    def cancel_all_orders(self):
        """Cancel all orders for all groups at IB."""
        logger.info("Canceling all orders...")
        cancelled_count = 0

        for g in GROUP_MANAGER.get_all():
            if not g.is_active:
                continue

            logger.info(f"Processing group {g.id} ({g.name}): trailing_order_id={g.trailing_order_id}, "
                       f"oca_group_id={g.oca_group_id}, time_exit_order_id={g.time_exit_order_id}")

            cancelled = False

            # For combo orders: OCA is not supported, use trailing_order_id directly
            if g.trailing_order_id:
                logger.info(f"Canceling trailing order: {g.trailing_order_id}")
                if BROKER.cancel_order(g.trailing_order_id):
                    cancelled = True
                    logger.info(f"Successfully cancelled trailing order {g.trailing_order_id}")
                else:
                    logger.warning(f"Failed to cancel trailing order {g.trailing_order_id}")

            # Try OCA group as fallback (only works for single-leg orders)
            if not cancelled and g.oca_group_id:
                logger.info(f"Canceling OCA group: {g.oca_group_id}")
                if BROKER.cancel_oca_group(g.oca_group_id):
                    cancelled = True
                    logger.info(f"Successfully cancelled OCA group {g.oca_group_id}")
                else:
                    logger.warning(f"Failed to cancel OCA group {g.oca_group_id}")

            # Also try to cancel time exit order if present
            if g.time_exit_order_id:
                logger.info(f"Canceling time exit order: {g.time_exit_order_id}")
                BROKER.cancel_order(g.time_exit_order_id)

            if cancelled:
                cancelled_count += 1

            # Deactivate group and clear orders
            GROUP_MANAGER.deactivate(g.id, clear_orders=True)

        self._load_groups_from_manager()
        self.status_message = f"Cancelled {cancelled_count} order groups"
        logger.info(f"Cancelled {cancelled_count} order groups")

    def cancel_group_order(self, group_id: str):
        """Cancel order for a specific group at IB and set to inactive."""
        logger.info(f"cancel_group_order called with group_id={group_id}")
        group = GROUP_MANAGER.get(group_id)
        if not group:
            logger.warning(f"Group {group_id} not found!")
            return

        logger.info(f"Group found: {group.name}, is_active={group.is_active}, "
                   f"oca_group_id={group.oca_group_id}, trailing_order_id={group.trailing_order_id}")

        cancelled = False

        # For combo orders: OCA is not supported, use trailing_order_id directly
        if group.trailing_order_id:
            logger.info(f"Canceling by order_id: {group.trailing_order_id}")
            cancelled = BROKER.cancel_order(group.trailing_order_id)
            if cancelled:
                logger.info(f"Successfully cancelled order {group.trailing_order_id}")
            else:
                logger.warning(f"Failed to cancel order {group.trailing_order_id}")

        # Try OCA group as fallback (only works for single-leg orders)
        if not cancelled and group.oca_group_id:
            logger.info(f"Trying OCA group cancel: {group.oca_group_id}")
            cancelled = BROKER.cancel_oca_group(group.oca_group_id)

        # Also try to cancel time exit order if present
        if group.time_exit_order_id:
            logger.info(f"Canceling time exit order: {group.time_exit_order_id}")
            BROKER.cancel_order(group.time_exit_order_id)

        GROUP_MANAGER.deactivate(group_id, clear_orders=True)
        self._load_groups_from_manager()
        self.status_message = f"Order canceled: {group.name}"
        logger.info(f"Order canceled for group {group.name}, cancelled={cancelled}")

    # === Delete with Confirmation ===

    def request_delete_group(self, group_id: str):
        """Request deletion of a group - shows confirmation dialog."""
        self.delete_confirm_group_id = group_id

    def cancel_delete(self):
        """Cancel the delete confirmation."""
        self.delete_confirm_group_id = ""

    def confirm_delete_group(self, cancel_order: bool):
        """Confirm deletion of a group.

        Args:
            cancel_order: If True, cancel the IB order. If False, leave order at IB.
        """
        group_id = self.delete_confirm_group_id
        if not group_id:
            return

        group = GROUP_MANAGER.get(group_id)
        if group:
            if cancel_order and group.oca_group_id:
                # Cancel IB order
                BROKER.cancel_oca_group(group.oca_group_id)
                logger.info(f"Deleting group {group.name} and canceling order")
            else:
                logger.info(f"Deleting group {group.name}, leaving order at IB")

            GROUP_MANAGER.delete(group_id)
            # Remove chart data for deleted group
            if group_id in self.chart_data:
                new_data = {k: v for k, v in self.chart_data.items() if k != group_id}
                self.chart_data = new_data

        self.delete_confirm_group_id = ""
        self._sync_broker_state()
        self._load_groups_from_manager()
        self.status_message = "Group deleted"
