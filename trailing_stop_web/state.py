"""Application state management."""
from dataclasses import dataclass
from datetime import datetime
from threading import Lock
import reflex as rx

from .broker import BROKER
from .groups import GROUP_MANAGER, calculate_stop_price
from .metrics import LegData, GroupMetrics, compute_group_metrics
from .config import (
    UI_UPDATE_INTERVAL,
    DEFAULT_TRAIL_PERCENT, DEFAULT_STOP_TYPE, DEFAULT_LIMIT_OFFSET
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

    # Price history for charts
    group_price_history: dict[str, list[dict]] = {}

    # Chart data for monitor page
    underlying_history: dict[str, list[dict]] = {}  # symbol -> OHLC bars (3D, 3min)
    combo_history: dict[str, list[dict]] = {}       # group_id -> price bars
    live_ticks: dict[str, list[dict]] = {}          # group_id -> rolling live data
    position_price_ticks: dict[str, list[dict]] = {}  # group_id -> mid price rolling (1D, 3min equivalent)
    _chart_loaded_for_group: str = ""               # Track which group has loaded chart data

    # UI State
    active_tab: str = "setup"  # "setup" or "monitor"
    delete_confirm_group_id: str = ""  # Group ID pending delete confirmation
    selected_group_id: str = ""  # Currently selected group in monitor tab

    @rx.var
    def position_rows(self) -> list[list[str]]:
        """Computed var - returns position data as simple list of lists for table.

        Column order: [con_id, symbol, type, expiry, strike, qty, fill_price,
                       bid, mid, ask, last, mark, net_cost, net_value, pnl, pnl_color,
                       is_selected, qty_usage_str, is_fully_used, selected_qty]
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
                p["quantity_str"],      # 5
                p["fill_price_str"],    # 6 - Fill Price
                p["bid_str"],           # 7 - Bid
                p["mid_str"],           # 8 - Mid
                p["ask_str"],           # 9 - Ask
                p["last_str"],          # 10 - Last
                p["mark_str"],          # 11 - Mark (portfolio price, sync)
                p["net_cost_str"],      # 12 - Net Cost
                p["net_value_str"],     # 13 - Net Value
                p["pnl_str"],           # 14 - PnL
                "green" if pnl_val >= 0 else "red",  # 15 - pnl_color
                "true" if is_selected else "false",  # 16 - is_selected (as string for frontend)
                p.get("qty_usage_str", "0/0"),       # 17 - qty_usage_str (e.g., "2/3")
                "true" if is_fully_used else "false",  # 18 - is_fully_used
                str(selected_qty),      # 19 - selected_qty for this group
                str(p.get("available_qty", 0)),  # 20 - available_qty for dropdown
                ",".join(p.get("qty_options", ["0"])),  # 21 - qty_options as comma-separated string
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
        logger.info(f"create_group called: selected_quantities={self.selected_quantities}, positions_count={len(self.positions)}")

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
        logger.info(f"create_group: calculated value={value}, positions still={len(self.positions)}")

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
        logger.info(f"create_group: before refresh, positions={len(self.positions)}, broker_connected={BROKER.is_connected()}")
        if BROKER.is_connected():
            self._refresh_positions()
        logger.info(f"create_group: after refresh, positions={len(self.positions)}")
        self._load_groups_from_manager()
        logger.info(f"create_group: after _load_groups, positions={len(self.positions)}")
        # Reflex requires full reassignment, not in-place modification
        new_history = dict(self.group_price_history)
        new_history[group.id] = []
        self.group_price_history = new_history
        self.selected_quantities = {}
        self.new_group_name = ""
        self.status_message = f"Group '{group.name}' created"
        logger.info(f"create_group: DONE, final positions={len(self.positions)}")

    def _load_groups_from_manager(self):
        """Load groups from GroupManager into state for UI."""
        self.groups = []
        for g in GROUP_MANAGER.get_all():
            # Calculate current value (simple)
            value = self._calc_group_value(g.con_ids)
            # Calculate detailed metrics with allocated quantities
            metrics = self._calc_group_metrics(g.con_ids, g.position_quantities)
            # Calculate total allocated quantity
            total_allocated_qty = sum(g.position_quantities.values())

            # Format trail value display based on mode
            if g.trail_mode == "percent":
                trail_display = f"{g.trail_value}%"
            else:
                trail_display = f"${g.trail_value}"

            self.groups.append({
                "id": g.id,
                "name": g.name,
                "con_ids": g.con_ids,
                "positions_str": ", ".join(str(c) for c in g.con_ids),
                "total_qty": total_allocated_qty,
                "total_qty_str": f"{total_allocated_qty} qty",
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
                "high_water_mark": g.high_water_mark,
                "hwm_str": f"${g.high_water_mark:.2f}",
                "stop_price": g.stop_price,
                "stop_str": f"${g.stop_price:.2f}",
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

    def _calc_group_metrics(self, con_ids: list[int], position_quantities: dict = None) -> dict:
        """Calculate detailed metrics for a group.

        Args:
            con_ids: List of contract IDs in the group
            position_quantities: Optional dict mapping con_id_str -> allocated qty
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
        }

    def delete_group(self, group_id: str):
        """Delete a group."""
        GROUP_MANAGER.delete(group_id)
        # Sync connection state and refresh positions
        self._sync_broker_state()
        self._load_groups_from_manager()
        # Reflex requires full reassignment, not in-place modification
        if group_id in self.group_price_history:
            new_history = {k: v for k, v in self.group_price_history.items() if k != group_id}
            self.group_price_history = new_history
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
        logger.info(f"update_group_time_exit_enabled: group_id={group_id}, checked={checked}")
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

            # Calculate net cost (fill_price * qty * multiplier)
            net_cost = fill_price * abs(p.quantity) * multiplier

            # Calculate net value using mark price (same as TWS)
            net_value = mark * p.quantity * multiplier

            # Calculate PnL
            pnl = net_value - net_cost

            # Calculate quantity usage across groups
            total_qty = abs(p.quantity)
            used_qty = used_quantities.get(p.con_id, 0)
            available_qty = max(0, total_qty - used_qty)
            is_fully_used = available_qty <= 0

            # Format based on position type
            if p.is_combo:
                type_str = f"COMBO ({len(p.combo_legs)} legs)"
                strike_str = "-"
            elif p.sec_type == "OPT":
                type_str = "OPT"
                strike_str = f"{p.strike}{p.right}"
            elif p.sec_type == "FOP":
                type_str = "FOP"
                strike_str = f"{p.strike}{p.right}"
            elif p.sec_type == "STK":
                type_str = "STK"
                strike_str = "-"
            else:
                type_str = p.sec_type
                strike_str = "-"

            # Use dict instead of PositionData for proper Reflex serialization
            result.append({
                "con_id": p.con_id,
                "symbol": p.symbol,
                "sec_type": p.sec_type,
                "type_str": type_str,
                "expiry": p.expiry or "-",
                "strike_str": strike_str,
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
        """Called by frontend interval - refresh positions and force UI update."""
        # Always sync connection status from broker (may have changed async)
        broker_connected = BROKER.is_connected()
        if broker_connected != self.is_connected:
            self.is_connected = broker_connected
            if broker_connected:
                self.connection_status = "Connected"
                self.is_monitoring = True
                self.status_message = f"Connected - refreshing positions..."
                # Load chart data if a group was selected before connection
                if self.selected_group_id:
                    self._load_group_chart_data(self.selected_group_id)
            else:
                self.connection_status = "Disconnected"

        if not self.is_connected or not self.is_monitoring:
            return

        self._refresh_positions()
        self.refresh_tick += 1

        # Load chart data once positions are available (deferred loading) - only once per group
        if self.selected_group_id and self.positions and self._chart_loaded_for_group != self.selected_group_id:
            group = GROUP_MANAGER.get(self.selected_group_id)
            if group:
                symbol = self.selected_underlying_symbol
                if symbol and symbol not in self.underlying_history:
                    logger.info(f"Deferred chart loading for {symbol}")
                    self._load_group_chart_data(self.selected_group_id)
                    self._chart_loaded_for_group = self.selected_group_id

        now = datetime.now()
        now_str = now.strftime("%H:%M:%S")
        self.status_message = f"Monitoring... ({now_str})"

        # Update live_ticks for Chart C (rolling window of ~120 data points = ~1 min at 0.5s interval)
        new_live_ticks = dict(self.live_ticks)
        new_position_ticks = dict(self.position_price_ticks)

        # Every 12 ticks (~6 sec at 0.5s interval), record position price for Chart B
        # Use 360 for real 3-min bars, 12 for faster demo
        record_position_tick = (self.refresh_tick % 12) == 0

        # Update groups via GroupManager
        for g in GROUP_MANAGER.get_all():
            value = self._calc_group_value(g.con_ids)
            metrics = self._calc_group_metrics(g.con_ids, g.position_quantities)

            # Record live tick for oscillator chart (every tick)
            if g.id not in new_live_ticks:
                new_live_ticks[g.id] = []
            ticks = list(new_live_ticks[g.id])
            ticks.append({
                "time": now_str,
                "timestamp": now.timestamp(),
                "mark": metrics["mark_value"],
                "pnl": metrics["pnl_mark"],
                "stop_price": g.stop_price,
                "hwm": g.high_water_mark,
            })
            # Keep rolling window of 120 ticks (~1 min)
            if len(ticks) > 120:
                ticks = ticks[-120:]
            new_live_ticks[g.id] = ticks

            # Record position price tick for Chart B (every 3 min)
            if record_position_tick:
                if g.id not in new_position_ticks:
                    new_position_ticks[g.id] = []
                pos_ticks = list(new_position_ticks[g.id])
                pos_ticks.append({
                    "time": now_str,
                    "timestamp": now.timestamp(),
                    "mid": metrics["mid_value"],
                    "mark": metrics["mark_value"],
                    "bid": metrics["spread_bid"],
                    "ask": metrics["spread_ask"],
                    "stop_price": g.stop_price,
                })
                # Keep max 200 ticks (~10 hours of 3-min bars)
                if len(pos_ticks) > 200:
                    pos_ticks = pos_ticks[-200:]
                new_position_ticks[g.id] = pos_ticks

            if g.is_active:
                # Update HWM if value increased
                GROUP_MANAGER.update_hwm(g.id, value)

                # Check if stop triggered
                if GROUP_MANAGER.check_stop_triggered(g.id, value):
                    self.status_message = f"STOP TRIGGERED: {g.name} at ${value:.2f}!"
                    GROUP_MANAGER.deactivate(g.id)
                    # Optional: Auto-remove group when triggered
                    # GROUP_MANAGER.remove_if_order_triggered(g.id)

        self.live_ticks = new_live_ticks
        self.position_price_ticks = new_position_ticks

        # Reload groups to reflect changes
        self._load_groups_from_manager()

    # === UI Navigation ===

    def set_active_tab(self, tab: str):
        """Switch between setup and monitor tabs."""
        self.active_tab = tab

    def select_group(self, group_id: str):
        """Select a group in monitor view and load chart data."""
        logger.info(f"select_group called with group_id={group_id}")
        self.selected_group_id = group_id
        # Only reload chart data if this is a different group
        if self._chart_loaded_for_group != group_id:
            self._load_group_chart_data(group_id)
            self._chart_loaded_for_group = group_id

    def _load_group_chart_data(self, group_id: str):
        """Load historical chart data for a group."""
        group = GROUP_MANAGER.get(group_id)
        logger.info(f"_load_group_chart_data: group={group}, is_connected={self.is_connected}")
        if not group or not self.is_connected:
            logger.warning(f"_load_group_chart_data: early return - group={group is not None}, connected={self.is_connected}")
            return

        logger.info(f"_load_group_chart_data: group.con_ids={group.con_ids}, positions count={len(self.positions)}")
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
                    logger.info(f"Loaded {len(bars)} underlying bars for {symbol}")

            # Fetch combo/position history for each leg
            for con_id in group.con_ids:
                if str(con_id) not in self.combo_history:
                    bars = BROKER.fetch_historical_bars(con_id, "3 D", "3 mins", "MIDPOINT")
                    if bars:
                        new_hist = dict(self.combo_history)
                        new_hist[str(con_id)] = bars
                        self.combo_history = new_hist

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
            # Remove from price history
            if group_id in self.group_price_history:
                new_history = {k: v for k, v in self.group_price_history.items() if k != group_id}
                self.group_price_history = new_history

        self.delete_confirm_group_id = ""
        self._sync_broker_state()
        self._load_groups_from_manager()
        self.status_message = "Group deleted"
