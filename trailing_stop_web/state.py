"""Application state management."""
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from threading import Lock
import reflex as rx
import plotly.graph_objects as go

from .broker import BROKER
from .groups import GROUP_MANAGER, calculate_stop_price
from .metrics import LegData, GroupMetrics, compute_group_metrics
from .config import (
    UI_UPDATE_INTERVAL,
    DEFAULT_TRAIL_PERCENT, DEFAULT_STOP_TYPE, DEFAULT_LIMIT_OFFSET,
    BAR_INTERVAL_TICKS, CHART_RENDER_INTERVAL
)
from .logger import logger


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

    # Connection status
    is_connected: bool = False
    connection_status: str = "Disconnected"

    # Portfolio - use list[dict] for proper Reflex serialization (not dataclass)
    positions: list[dict] = []
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

    # === Chart Header Info (updated every render cycle) ===
    # Position OHLC Header: Trigger value (based on trigger_price_type), Stop, Limit, HWM
    chart_trigger_label: str = "Mid"  # "Mark", "Mid", "Bid", "Ask", "Last"
    chart_pos_close: str = "-"
    chart_pos_stop: str = "-"
    chart_pos_limit: str = "-"
    chart_pos_hwm: str = "-"
    # P&L History Header: Current P&L, Stop P&L
    chart_pnl_current: str = "-"
    chart_pnl_stop: str = "-"

    @rx.var
    def position_rows(self) -> list[list[str]]:
        """Computed var - returns position data as simple list of lists for table.

        Column order: [con_id, symbol, type, expiry, strike, side, qty, fill_price,
                       bid, mid, ask, last, mark, net_cost, net_value, pnl, pnl_color,
                       is_selected, qty_usage_str, is_fully_used, selected_qty,
                       available_qty, qty_options, market_status]
        """
        # Access refresh_tick to force recomputation on every tick
        _ = self.refresh_tick
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
        return rows

    def on_mount(self):
        """Called when page mounts - just initialize UI, don't auto-connect."""
        logger.info("App mounted")
        # Load persisted groups
        self._load_groups_from_manager()
        self.status_message = "Click 'Connect' to connect to TWS"

    def connect_tws(self):
        """Connect to TWS."""
        logger.info("Connecting to TWS...")
        self.connection_status = "Connecting..."
        self.status_message = "Connecting to TWS..."

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

    def toggle_position(self, con_id):
        """Toggle position selection (selects with default qty=1 or deselects)."""
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

    def set_position_quantity(self, con_id, qty):
        """Set the quantity for a selected position.

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

        # Convert string keys to int for GroupManager (it will convert back to str for JSON)
        position_quantities = {int(k): v for k, v in self.selected_quantities.items()}

        # Calculate initial value (using con_ids list for compatibility)
        con_ids = list(position_quantities.keys())
        value = self._calc_group_value(con_ids)

        # Create via GroupManager (persisted to JSON)
        group = GROUP_MANAGER.create(
            name=self.new_group_name.strip(),
            position_quantities=position_quantities,
            trail_value=self.trail_percent,  # Use state default
            trail_mode="percent",  # Default mode
            stop_type=self.stop_type,
            limit_offset=self.limit_offset,
            initial_value=value,
        )

        # Refresh positions if connected (don't clear if disconnected)
        if BROKER.is_connected():
            self._refresh_positions()
        self._load_groups_from_manager()

        # Initialize chart state for new group
        self._init_chart_state(group.id)

        self.selected_quantities = {}
        self.new_group_name = ""
        self.status_message = f"Group '{group.name}' created"
        logger.info(f"Group created: '{group.name}' with {len(position_quantities)} positions, value=${value:.2f}")

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
                metrics = self._calc_group_metrics(g.con_ids, g.position_quantities, g.trigger_price_type)
            # Calculate total allocated quantity
            total_allocated_qty = sum(g.position_quantities.values())

            # Format trail value display based on mode
            if g.trail_mode == "percent":
                trail_display = f"{g.trail_value}%"
            else:
                trail_display = f"${g.trail_value}"

            # Calculate group market status (worst case of all positions)
            group_market_status = "Open"
            for pos in self.positions:
                if pos["con_id"] in g.con_ids:
                    pos_status = pos.get("market_status", "Unknown")
                    if pos_status == "Closed":
                        group_market_status = "Closed"
                        break
                    elif pos_status == "Unknown" and group_market_status == "Open":
                        group_market_status = "Unknown"

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
                # HWM and Stop from chart_data (trigger-based) or fallback to metrics trigger_value
                "high_water_mark": self._get_group_hwm(g.id, metrics.get("trigger_value", 0)),
                "hwm_str": f"${self._get_group_hwm(g.id, metrics.get('trigger_value', 0)):.2f}",
                "stop_price": self._get_group_stop(g.id, g.trail_mode, g.trail_value, metrics.get("trigger_value", 0)),
                "stop_str": f"${self._get_group_stop(g.id, g.trail_mode, g.trail_value, metrics.get('trigger_value', 0)):.2f}",
                # Trigger value for highlighting in UI
                "trigger_value": metrics.get("trigger_value", 0),
                "trigger_value_str": f"${metrics.get('trigger_value', 0):.2f}",
                "current_value": value,
                "value_str": f"${value:.2f}",
                # Metrics - Legs info
                "legs_str": metrics["legs_str"],
                # Per-leg aggregated values
                "mark_value_str": metrics["mark_value_str"],
                "mid_value_str": metrics["mid_value_str"],
                # Spread-level Natural Bid/Ask
                "spread_bid_str": metrics["spread_bid_str"],
                "spread_ask_str": metrics["spread_ask_str"],
                # Cost and PnL
                "cost_str": metrics["cost_str"],
                "pnl_mark": metrics["pnl_mark"],
                "pnl_mark_str": metrics["pnl_mark_str"],
                "pnl_color": "green" if metrics["pnl_mark"] >= 0 else "red",
                "pnl_close": metrics["pnl_close"],
                "pnl_close_str": metrics["pnl_close_str"],
                # Greeks (aggregated for group)
                "delta": metrics["delta"],
                "delta_str": metrics["delta_str"],
                "gamma": metrics["gamma"],
                "gamma_str": metrics["gamma_str"],
                "theta": metrics["theta"],
                "theta_str": metrics["theta_str"],
                "vega": metrics["vega"],
                "vega_str": metrics["vega_str"],
            })

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
            if hwm > 0:
                return hwm
        return fallback_value

    def _get_group_stop(self, group_id: str, trail_mode: str, trail_value: float, fallback_value: float = 0) -> float:
        """Get trigger-based stop price from chart_data HWM."""
        hwm = self._get_group_hwm(group_id, fallback_value)
        if hwm > 0:
            return calculate_stop_price(hwm, trail_mode, trail_value)
        return 0.0

    def _calc_group_metrics(self, con_ids: list[int], position_quantities: dict = None, trigger_price_type: str = "mid") -> dict:
        """Calculate detailed metrics for a group.

        Args:
            con_ids: List of contract IDs in the group
            position_quantities: Optional dict mapping con_id_str -> allocated qty
            trigger_price_type: Price type for trailing stop trigger (mark, mid, bid, ask, last)
        """
        # Build leg data from positions
        legs = []
        for pos in self.positions:
            if pos["con_id"] in con_ids:
                strike_str = pos["strike_str"]
                # Use allocated quantity if provided, else use portfolio quantity
                con_id_str = str(pos["con_id"])
                if position_quantities:
                    allocated_qty = position_quantities.get(con_id_str, abs(pos["quantity"]))
                    # Preserve sign from portfolio position (long/short)
                    if pos["quantity"] < 0:
                        allocated_qty = -allocated_qty
                else:
                    allocated_qty = pos["quantity"]

                leg = LegData(
                    con_id=pos["con_id"],
                    symbol=pos["symbol"],
                    sec_type=pos["sec_type"],
                    expiry=pos["expiry"] if pos["expiry"] != "-" else "",
                    strike=float(strike_str.rstrip("CP")) if strike_str not in ("-", "") else 0.0,
                    right=strike_str[-1] if strike_str not in ("-", "") and strike_str[-1] in ("C", "P") else "",
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

        # Compute metrics
        metrics = compute_group_metrics(legs)

        # Build leg info for UI display - per-leg Mark and Mid
        leg_infos = []
        for leg in legs:
            leg_infos.append({
                "name": leg.display_name,
                "qty": f"{leg.quantity:+g}",  # +1 or -1
                "type": leg.position_type,
                "fill": f"${leg.fill_price:.2f}",
                "mark": f"${leg.mark:.2f}",
                "mid": f"${leg.mid:.2f}" if leg.mid > 0 else "-",
                "bid": f"${leg.bid:.2f}" if leg.bid > 0 else "-",
                "ask": f"${leg.ask:.2f}" if leg.ask > 0 else "-",
            })

        # Format legs as string for display (avoids nested foreach issue)
        # Show: Qty, Name, Bid/Ask (simplified view)
        legs_lines = []
        for info in leg_infos:
            legs_lines.append(
                f"{info['qty']:>3}  {info['name']}  Bid:{info['bid']} Ask:{info['ask']}"
            )
        legs_str = "\n".join(legs_lines) if legs_lines else "No legs"

        return {
            "legs": leg_infos,
            "legs_str": legs_str,
            # Per-leg aggregated values
            "mark_value": metrics.group_mark_value,
            "mark_value_str": metrics.mark_str,
            "mid_value": metrics.group_mid_value,
            "mid_value_str": metrics.mid_str,
            # Spread-level Natural Bid/Ask
            "spread_bid": metrics.spread_bid,
            "spread_bid_str": metrics.spread_bid_str,
            "spread_ask": metrics.spread_ask,
            "spread_ask_str": metrics.spread_ask_str,
            # Cost and PnL
            "total_cost": metrics.total_cost,
            "cost_str": metrics.cost_str,
            "pnl_mark": metrics.pnl_mark,
            "pnl_mark_str": metrics.pnl_mark_str,
            "pnl_mid": metrics.pnl_mid,
            "pnl_mid_str": metrics.pnl_mid_str,
            "pnl_close": metrics.pnl_close,
            "pnl_close_str": metrics.pnl_close_str,
            # Greeks (aggregated for group)
            "delta": metrics.group_delta,
            "delta_str": metrics.delta_str,
            "gamma": metrics.group_gamma,
            "gamma_str": metrics.gamma_str,
            "theta": metrics.group_theta,
            "theta_str": metrics.theta_str,
            "vega": metrics.group_vega,
            "vega_str": metrics.vega_str,
            # Trigger value based on trigger_price_type
            "trigger_value": self._get_trigger_value(metrics, trigger_price_type),
            "trigger_price_type": trigger_price_type,
        }

    def _get_trigger_value(self, metrics, trigger_price_type: str) -> float:
        """Get the trigger value based on trigger_price_type.

        Args:
            metrics: GroupMetrics object from compute_group_metrics()
            trigger_price_type: One of "mark", "mid", "bid", "ask", "last"

        Returns:
            The appropriate value for trailing stop calculations
        """
        if trigger_price_type == "mark":
            return metrics.group_mark_value
        elif trigger_price_type == "mid":
            return metrics.group_mid_value
        elif trigger_price_type == "bid":
            return metrics.spread_bid
        elif trigger_price_type == "ask":
            return metrics.spread_ask
        elif trigger_price_type == "last":
            # For "last", use mid as fallback (last not aggregated in metrics)
            return metrics.group_mid_value
        else:
            return metrics.group_mid_value

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

    def toggle_group_active(self, group_id: str):
        """Toggle group monitoring on/off - places/cancels orders at TWS."""
        # Sync connection state and refresh positions
        self._sync_broker_state()
        group = GROUP_MANAGER.get(group_id)
        if group:
            if group.is_active:
                # Deactivating - cancel orders at TWS
                if group.oca_group_id:
                    BROKER.cancel_oca_group(group.oca_group_id)
                GROUP_MANAGER.deactivate(group_id, clear_orders=True)
                self.status_message = f"Deactivated: {group.name}"
            else:
                # Activating - place orders at TWS
                value = self._calc_group_value(group.con_ids)

                # Place OCA order group
                order_result = BROKER.place_oca_group(
                    group_name=group.name,
                    position_quantities={int(k): v for k, v in group.position_quantities.items()},
                    trail_value=group.trail_value,
                    trail_mode=group.trail_mode,
                    stop_type=group.stop_type,
                    limit_offset=group.limit_offset,
                    time_exit_enabled=group.time_exit_enabled,
                    time_exit_time=group.time_exit_time
                )

                if order_result:
                    GROUP_MANAGER.activate(group_id, value, order_result)
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
                # Recalculate stop price based on new trail value and mode
                group = GROUP_MANAGER.get(group_id)
                if group and group.high_water_mark > 0:
                    new_stop = calculate_stop_price(
                        group.high_water_mark, group.trail_mode, trail
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
            if group and group.high_water_mark > 0:
                new_stop = calculate_stop_price(
                    group.high_water_mark, value, group.trail_value
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
        else:
            self.connection_status = "Disconnected"
            self.positions = []

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
        if broker_connected != self.is_connected:
            self.is_connected = broker_connected
            if broker_connected:
                self.connection_status = "Connected"
                self.is_monitoring = True
                self.status_message = "Connected - refreshing positions..."
                # Initialize chart states for all groups
                self._init_all_chart_states()
                # Load underlying history if group selected
                if self.selected_group_id:
                    self._load_group_chart_data(self.selected_group_id)
            else:
                self.connection_status = "Disconnected"
        timings["1_broker_sync"] = (time.perf_counter() - t0) * 1000

        if not self.is_connected or not self.is_monitoring:
            return

        # 2. Refresh positions (necessary for price data)
        t0 = time.perf_counter()
        self._refresh_positions()
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
            metrics = self._calc_group_metrics(g.con_ids, g.position_quantities, g.trigger_price_type)
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
                    GROUP_MANAGER.update_hwm(g.id, value)
                    if GROUP_MANAGER.check_stop_triggered(g.id, value):
                        self.status_message = f"STOP TRIGGERED: {g.name} at ${value:.2f}!"
                        GROUP_MANAGER.deactivate(g.id)
        timings["3_groups_metrics"] = (time.perf_counter() - t0) * 1000

        # 4. Bar completion every 3 min (BAR_INTERVAL_TICKS = 360)
        t0 = time.perf_counter()
        if self.refresh_tick > 0 and (self.refresh_tick % BAR_INTERVAL_TICKS) == 0:
            self._complete_bars()

            # Update underlying history on bar completion
            if self.selected_group_id:
                symbol = self.selected_underlying_symbol
                if symbol and symbol in self.underlying_history:
                    new_bar = BROKER.fetch_latest_underlying_bar(symbol)
                    if new_bar:
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

    def select_group(self, group_id: str):
        """Select a group in monitor view and load chart data."""
        logger.debug(f"select_group called with group_id={group_id}")
        self.selected_group_id = group_id
        # Initialize chart state if not exists
        if group_id not in self.chart_data:
            self._init_chart_state(group_id)
        # Load underlying history for Chart 1
        self._load_group_chart_data(group_id)

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

            # Fetch underlying history if not already loaded
            if symbol not in self.underlying_history:
                bars = BROKER.fetch_underlying_history(symbol, "3 D", "3 mins")
                if bars:
                    new_hist = dict(self.underlying_history)
                    new_hist[symbol] = bars
                    self.underlying_history = new_hist
                    logger.debug(f"Loaded {len(bars)} underlying bars for {symbol}")

    # NOTE: _build_position_ohlc_from_history and _build_pnl_history_from_position
    # are no longer used - data is collected from connect time using _accumulate_tick

    # Placeholder for backwards compatibility (remove if not referenced elsewhere)
    def _build_position_ohlc_from_history(self, group, all_leg_bars: dict[int, list[dict]]):
        """DEPRECATED: Position OHLC now collected live from connect time."""
        pass

    def _build_pnl_history_from_position(self, group):
        """DEPRECATED: PnL history now collected live from connect time."""
        pass

    @rx.var
    def selected_underlying_symbol(self) -> str:
        """Get the underlying symbol for the selected group."""
        if not self.selected_group_id:
            return ""
        group = GROUP_MANAGER.get(self.selected_group_id)
        if not group or not group.con_ids:
            return ""
        first_con_id = group.con_ids[0]
        for p in self.positions:
            if p["con_id"] == first_con_id:
                return p["symbol"]
        return ""

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

        Also implements the trailing mechanism:
        - Track HWM (High Water Mark) which only moves UP
        - Calculate stop price based on trail settings
        - Update GROUP_MANAGER with new HWM (for persistence)

        IMPORTANT: HWM is only updated when ALL markets for the group are open.
        This prevents false triggers due to stale prices during market closed hours.

        Uses trigger_value (based on trigger_price_type: mark, mid, bid, ask, last)
        for OHLC candlesticks and HWM tracking.
        """
        trigger_value = metrics.get("trigger_value", 0)
        pnl = metrics.get("pnl_mark", 0)

        # Skip if no valid trigger value (positions not loaded yet)
        if trigger_value == 0:
            return

        if group_id not in self.chart_data:
            self._init_chart_state(group_id)

        # Check if all markets for this group are open
        group = GROUP_MANAGER.get(group_id)
        market_open = True
        if group:
            for pos in self.positions:
                if pos["con_id"] in group.con_ids:
                    if pos.get("market_status") == "Closed":
                        market_open = False
                        break

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
        # Track HWM based on trigger_value (mark, mid, bid, ask, or last)
        # IMPORTANT: Only update HWM when market is OPEN to prevent false triggers
        current_hwm = state.get("current_hwm", 0)
        if market_open and trigger_value > current_hwm:
            # New high water mark!
            state["current_hwm"] = trigger_value
            trigger_type = metrics.get("trigger_price_type", "mid")
            logger.debug(f"Trailing: HWM ({trigger_type}) updated ${current_hwm:.2f} -> ${trigger_value:.2f}")
        elif not market_open and trigger_value > current_hwm:
            # Market closed - log but don't update HWM
            logger.debug(f"Trailing: Market CLOSED - HWM NOT updated (value=${trigger_value:.2f}, current HWM=${current_hwm:.2f})")

        # === LIVE UPDATE: Store current HWM/Stop/Limit in current slot ===
        # This creates the time-series history for visualization
        slot = state["current_slot"]
        time_label = self._slot_to_time_label(state["start_timestamp"], slot)
        hwm = state.get("current_hwm", 0)

        if hwm > 0:
            # Get group settings for stop calculation
            group = GROUP_MANAGER.get(group_id)
            if group:
                stop_price = calculate_stop_price(hwm, group.trail_mode, group.trail_value)
                state["hwm_bars"][slot] = {"time": time_label, "hwm": hwm}
                state["stop_bars"][slot] = {"time": time_label, "stop": stop_price}

                # Limit price (only for limit orders)
                if group.stop_type == "limit":
                    limit_price = stop_price - group.limit_offset
                    state["limit_bars"][slot] = {"time": time_label, "limit": limit_price}

                # Stop P&L calculation (for P&L chart)
                # Convert stop_price to P&L: What would P&L be if trigger_value dropped to stop_price?
                total_cost = metrics.get("total_cost", 0)

                if total_cost > 0:
                    # stop_price is already a VALUE (not price), so stop_pnl is simply:
                    stop_pnl = stop_price - total_cost
                    state["stop_pnl_bars"][slot] = {"time": time_label, "stop_pnl": stop_pnl}

        state["tick_count"] += 1

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
                if hwm > 0:
                    stop_price = calculate_stop_price(hwm, group.trail_mode, group.trail_value)
                    state["hwm_bars"][slot] = {"time": time_label, "hwm": hwm}
                    state["stop_bars"][slot] = {"time": time_label, "stop": stop_price}

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
        if group_id not in self.chart_data:
            self._init_chart_state(group_id)

        state = self.chart_data[group_id]

        # Get group data for stop/limit visualization
        group = GROUP_MANAGER.get(group_id)
        group_info = None
        if group:
            # Get trigger-price based HWM from chart state
            hwm = state.get("current_hwm", 0)
            # Calculate stop price based on trigger-price HWM
            stop_price = calculate_stop_price(hwm, group.trail_mode, group.trail_value) if hwm > 0 else 0

            # Get metrics for P&L calculation
            metrics = self._calc_group_metrics(group.con_ids, group.position_quantities, group.trigger_price_type)

            group_info = {
                # Position OHLC uses trigger-price based values
                "stop_price": stop_price,
                "high_water_mark": hwm,
                "trail_mode": group.trail_mode,
                "trail_value": group.trail_value,
                "stop_type": group.stop_type,
                "limit_offset": group.limit_offset,
                "trigger_price_type": group.trigger_price_type,
                # P&L chart calculation values
                "total_cost": metrics.get("total_cost", 0.0),
                "pnl_mark": metrics.get("pnl_mark", 0.0),
                "trigger_value": metrics.get("trigger_value", 0.0),  # For stop_pnl calculation
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
            stop_price = group_info.get("stop_price", 0)
            hwm = group_info.get("high_water_mark", 0)
            limit_offset = group_info.get("limit_offset", 0)
            stop_type = group_info.get("stop_type", "market")
            trigger_type = group_info.get("trigger_price_type", "mid")

            # Set trigger label (capitalize first letter)
            self.chart_trigger_label = trigger_type.capitalize()

            self.chart_pos_close = f"${trigger_value:.2f}" if trigger_value > 0 else "-"
            self.chart_pos_stop = f"${stop_price:.2f}" if stop_price > 0 else "-"
            self.chart_pos_hwm = f"${hwm:.2f}" if hwm > 0 else "-"
            if stop_type == "limit" and stop_price > 0:
                limit_price = stop_price - limit_offset
                self.chart_pos_limit = f"${limit_price:.2f}"
            else:
                self.chart_pos_limit = "-"

            # P&L History header: Current P&L, Stop P&L
            pnl_mark = group_info.get("pnl_mark", 0)
            total_cost = group_info.get("total_cost", 0)
            self.chart_pnl_current = f"${pnl_mark:.2f}" if pnl_mark != 0 else "$0.00"

            # Calculate stop P&L: stop_price is already a VALUE, so stop_pnl = stop_price - total_cost
            if stop_price > 0 and total_cost > 0:
                stop_pnl = stop_price - total_cost
                self.chart_pnl_stop = f"${stop_pnl:.2f}"
            else:
                self.chart_pnl_stop = "-"
        else:
            # Reset headers
            self.chart_trigger_label = "Mid"
            self.chart_pos_close = "-"
            self.chart_pos_stop = "-"
            self.chart_pos_limit = "-"
            self.chart_pos_hwm = "-"
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
        open_vals = [None] * 240
        high_vals = [None] * 240
        low_vals = [None] * 240
        close_vals = [None] * 240

        # Fill in completed bars
        for i, bar in enumerate(state["position_bars"]):
            if bar is not None:
                open_vals[i] = bar["open"]
                high_vals[i] = bar["high"]
                low_vals[i] = bar["low"]
                close_vals[i] = bar["close"]

        # Add current (incomplete) bar at current_slot
        slot = state["current_slot"]
        if state["current_pos"]:
            open_vals[slot] = state["current_pos"]["open"]
            high_vals[slot] = state["current_pos"]["high"]
            low_vals[slot] = state["current_pos"]["low"]
            close_vals[slot] = state["current_pos"]["close"]

        # Check if we have any data
        if all(v is None for v in close_vals):
            return self._empty_figure("Collecting OHLC data...")

        # Create candlestick chart with ALL 240 x values
        fig = go.Figure(data=[go.Candlestick(
            x=x_labels,  # All 240 labels
            open=open_vals,
            high=high_vals,
            low=low_vals,
            close=close_vals,
            increasing_line_color='#00D26A',  # Profit green from theme
            decreasing_line_color='#FF3B30',  # Loss red from theme
            increasing_fillcolor='#00D26A',
            decreasing_fillcolor='#FF3B30',
            name="Position",
        )])

        # === HISTORICAL LINES: Stop, Limit, HWM as time-series ===
        # Build arrays from historical bars + extend to future with current value

        # Get current values for extending into future
        current_hwm = state.get("current_hwm_mid", 0)
        current_stop = 0
        current_limit = 0
        if group_info:
            current_stop = group_info.get("stop_price", 0)
            if group_info.get("stop_type") == "limit":
                current_limit = current_stop - group_info.get("limit_offset", 0)

        # HWM line (green dotted)
        hwm_vals = [None] * 240
        for i, bar in enumerate(state.get("hwm_bars", [])):
            if bar is not None:
                hwm_vals[i] = bar.get("hwm")
        # Fill future slots with current value
        for i in range(slot + 1, 240):
            if current_hwm > 0:
                hwm_vals[i] = current_hwm

        if any(v is not None for v in hwm_vals):
            fig.add_trace(go.Scatter(
                x=x_labels,
                y=hwm_vals,
                mode='lines',
                line=dict(color='rgba(0, 191, 255, 0.8)', width=2),  # Cyan #00BFFF
                name='HWM',
                hovertemplate='HWM: $%{y:.2f}<extra></extra>',
            ))

        # Stop line (red solid, semi-transparent)
        stop_vals = [None] * 240
        for i, bar in enumerate(state.get("stop_bars", [])):
            if bar is not None:
                stop_vals[i] = bar.get("stop")
        # Fill future slots with current value
        for i in range(slot + 1, 240):
            if current_stop > 0:
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
                    limit_vals[i] = bar.get("limit")
            # Fill future slots with current value
            for i in range(slot + 1, 240):
                if current_limit > 0:
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

        # Calculate stable Y-range with 10% padding
        all_y_vals = [v for v in low_vals + high_vals + hwm_vals + stop_vals + limit_vals if v is not None]
        if all_y_vals:
            y_min = min(all_y_vals)
            y_max = max(all_y_vals)
            y_padding = (y_max - y_min) * 0.1 if y_max > y_min else 1.0
            y_range = [y_min - y_padding, y_max + y_padding]
        else:
            y_range = None

        fig.update_layout(
            xaxis_rangeslider_visible=False,
            height=230,
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
        # stop_mid is already a VALUE (not price), so stop_pnl = stop_mid - total_cost
        current_stop_pnl = None
        if group_info and group_info.get("stop_price", 0) > 0:
            stop_mid = group_info["stop_price"]
            total_cost = group_info.get("total_cost", 0)

            if total_cost > 0:
                current_stop_pnl = stop_mid - total_cost

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
            height=230,
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
            height=230,
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

    def cancel_all_orders(self):
        """Cancel all orders for all groups at IB."""
        logger.info("Canceling all orders...")
        cancelled_count = 0

        for g in GROUP_MANAGER.get_all():
            if g.is_active and g.oca_group_id:
                if BROKER.cancel_oca_group(g.oca_group_id):
                    cancelled_count += 1
                GROUP_MANAGER.deactivate(g.id, clear_orders=True)

        self._load_groups_from_manager()
        self.status_message = f"Cancelled {cancelled_count} order groups"
        logger.info(f"Cancelled {cancelled_count} order groups")

    def cancel_group_order(self, group_id: str):
        """Cancel order for a specific group at IB and set to inactive."""
        logger.info(f"Canceling order for group {group_id}")
        group = GROUP_MANAGER.get(group_id)
        if group:
            if group.oca_group_id:
                BROKER.cancel_oca_group(group.oca_group_id)
            GROUP_MANAGER.deactivate(group_id, clear_orders=True)
            self._load_groups_from_manager()
            self.status_message = f"Order canceled: {group.name}"
            logger.info(f"Order canceled for group {group.name}")

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
