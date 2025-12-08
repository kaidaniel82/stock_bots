"""Group management with JSON persistence."""
import json
from pathlib import Path
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional

from .logger import logger
from .metrics import calculate_stop_price

# Data directory for persistence - in project folder (hot-reload excluded via REFLEX_HOT_RELOAD_EXCLUDE_PATHS)
DATA_DIR = Path(__file__).parent.parent / "data"
GROUPS_FILE = DATA_DIR / "groups.json"


@dataclass
class Group:
    """A trailing stop group containing multiple positions."""
    # === BASIS ===
    id: str
    name: str
    # Position quantities: {con_id_str: quantity} - JSON uses string keys
    position_quantities: dict[str, int] = field(default_factory=dict)
    created_at: str = ""
    is_active: bool = False

    @property
    def con_ids(self) -> list[int]:
        """Backwards compatibility: return list of con_ids."""
        return [int(k) for k in self.position_quantities.keys()]

    # === TRAILING STOP ===
    trail_enabled: bool = True
    trail_mode: str = "percent"           # "percent" or "absolute"
    trail_value: float = 10.0             # 10% or $10 depending on mode
    trigger_price_type: str = "mark"      # mark, mid, bid, ask, last
    stop_type: str = "market"             # "market" or "limit"
    limit_offset: float = 0.0             # Offset for limit orders

    # === TIME EXIT ===
    time_exit_enabled: bool = False
    time_exit_time: str = "15:55"         # HH:MM format (ET)

    # === POSITION TYPE (set at creation, immutable) ===
    is_credit: bool = False               # True for credit/short positions
    entry_price: float = 0.0              # Entry price per unit at creation

    # === RUNTIME STATE ===
    high_water_mark: float = 0.0
    stop_price: float = 0.0

    # === ORDER TRACKING (Phase 2) ===
    oca_group_id: str = ""                # TWS OCA Group ID
    trailing_order_id: int = 0            # TWS Order ID
    time_exit_order_id: int = 0           # TWS Order ID

    # === STATISTICS ===
    modification_count: int = 0           # Number of stop price modifications

    # Backwards compatibility: alias for trail_value
    @property
    def trail_percent(self) -> float:
        """Backwards compatibility alias."""
        return self.trail_value if self.trail_mode == "percent" else 0.0

    def to_dict(self) -> dict:
        """Convert to dict for JSON serialization."""
        d = asdict(self)
        # Remove con_ids from serialization (it's a computed property)
        # Actually asdict doesn't include properties, but let's be explicit
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "Group":
        """Create from dict. Supports old format (con_ids) for backwards compat."""
        # Handle old format: con_ids as list
        if "con_ids" in data and "position_quantities" not in data:
            # Convert old format to new format (1 qty per position)
            con_ids = data.pop("con_ids")
            data["position_quantities"] = {str(cid): 1 for cid in con_ids}
        return cls(**data)


class GroupManager:
    """Groups CRUD with JSON persistence."""

    def __init__(self):
        self._groups: dict[str, Group] = {}
        self._last_mtime: float = 0.0  # Track file modification time
        self._load()

    def _check_reload(self):
        """Reload groups if JSON file was modified externally (e.g., by another worker)."""
        if GROUPS_FILE.exists():
            try:
                current_mtime = GROUPS_FILE.stat().st_mtime
                if current_mtime > self._last_mtime:
                    logger.debug(f"Groups file changed, reloading...")
                    self._load()
            except Exception as e:
                logger.error(f"Error checking groups file: {e}")

    def _load(self):
        """Load groups from JSON file."""
        if GROUPS_FILE.exists():
            try:
                # Clear existing groups before reloading
                self._groups.clear()
                data = json.loads(GROUPS_FILE.read_text())
                for g in data.get("groups", []):
                    group = Group.from_dict(g)
                    self._groups[group.id] = group
                # Track modification time to detect external changes
                self._last_mtime = GROUPS_FILE.stat().st_mtime
                logger.info(f"Loaded {len(self._groups)} groups from {GROUPS_FILE}")
            except Exception as e:
                logger.error(f"Error loading groups: {e}")
        else:
            logger.info("No existing groups file, starting fresh")

    def _save(self):
        """Save groups to JSON file."""
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            data = {"groups": [g.to_dict() for g in self._groups.values()]}
            # Atomic write: write to temp file, then rename
            temp_file = GROUPS_FILE.with_suffix(".tmp")
            temp_file.write_text(json.dumps(data, indent=2))
            temp_file.rename(GROUPS_FILE)
            # Update mtime to avoid unnecessary reloads in this worker
            self._last_mtime = GROUPS_FILE.stat().st_mtime
            logger.debug(f"Saved {len(self._groups)} groups")
        except Exception as e:
            logger.error(f"Error saving groups: {e}")

    def create(
        self,
        name: str,
        position_quantities: dict[int, int],  # {con_id: quantity}
        trail_value: float = 10.0,
        trail_mode: str = "percent",
        trigger_price_type: str = "mark",
        stop_type: str = "market",
        limit_offset: float = 0.0,
        time_exit_enabled: bool = False,
        time_exit_time: str = "15:55",
        initial_value: float = 0.0,
        is_credit: bool = False,
        entry_price: float = 0.0,
    ) -> Group:
        """Create a new group.

        Args:
            name: Group name
            position_quantities: dict mapping con_id -> quantity to allocate
            is_credit: True for credit/short positions (immutable after creation)
            entry_price: Entry price per unit at creation (immutable after creation)
        """
        group_id = f"grp_{len(self._groups) + 1}_{datetime.now().strftime('%H%M%S')}"
        stop_price = calculate_stop_price(initial_value, trail_mode, trail_value, is_credit=is_credit)

        # Convert int keys to str for JSON serialization
        pos_qty_str = {str(k): v for k, v in position_quantities.items()}

        group = Group(
            id=group_id,
            name=name,
            position_quantities=pos_qty_str,
            created_at=datetime.now().isoformat(),
            is_active=False,
            trail_enabled=True,
            trail_mode=trail_mode,
            trail_value=trail_value,
            trigger_price_type=trigger_price_type,
            stop_type=stop_type,
            limit_offset=limit_offset,
            time_exit_enabled=time_exit_enabled,
            time_exit_time=time_exit_time,
            is_credit=is_credit,
            entry_price=entry_price,
            high_water_mark=initial_value,
            stop_price=stop_price,
        )
        self._groups[group.id] = group
        self._save()
        # Logical unit count: GCD of quantities (e.g., +2/-2 → 2 units)
        from math import gcd
        from functools import reduce
        abs_qtys = [abs(q) for q in position_quantities.values()]
        unit_qty = reduce(gcd, abs_qtys) if abs_qtys else 0
        logger.info(f"Group created: {group.name} ({group.id}) with {len(position_quantities)} legs, {unit_qty} units, credit={is_credit}")
        return group

    def delete(self, group_id: str) -> bool:
        """Delete a group."""
        if group_id in self._groups:
            name = self._groups[group_id].name
            del self._groups[group_id]
            self._save()
            logger.info(f"Group deleted: {name} ({group_id})")
            return True
        return False

    def get(self, group_id: str) -> Optional[Group]:
        """Get a group by ID."""
        self._check_reload()  # Ensure we have latest data
        return self._groups.get(group_id)

    def get_all(self) -> list[Group]:
        """Get all groups."""
        self._check_reload()  # Ensure we have latest data
        return list(self._groups.values())

    def update(self, group_id: str, **kwargs) -> bool:
        """Update group fields."""
        if group_id not in self._groups:
            return False

        group = self._groups[group_id]
        for key, value in kwargs.items():
            if hasattr(group, key):
                setattr(group, key, value)

        self._save()
        return True

    def activate(self, group_id: str, current_value: float = None, order_result: dict = None,
                 is_credit: bool = False) -> bool:
        """Activate group monitoring and store order IDs.

        Args:
            group_id: The group to activate
            current_value: Initial value for high water mark
            order_result: Dict with oca_group_id, trailing_order_id, time_exit_order_id from broker
            is_credit: True for SHORT/credit positions (stop is ABOVE HWM)
        """
        if group_id in self._groups:
            group = self._groups[group_id]
            group.is_active = True
            if current_value is not None:
                group.high_water_mark = current_value
                group.stop_price = calculate_stop_price(
                    current_value, group.trail_mode, group.trail_value, is_credit=is_credit
                )

            # Store order IDs if provided
            if order_result:
                group.oca_group_id = order_result.get("oca_group_id", "")
                group.trailing_order_id = order_result.get("trailing_order_id", 0)
                group.time_exit_order_id = order_result.get("time_exit_order_id", 0)

            self._save()
            logger.info(f"Group activated: {group.name} HWM=${group.high_water_mark:.2f} "
                       f"Stop=${group.stop_price:.2f} OCA={group.oca_group_id}")
            return True
        return False

    def deactivate(self, group_id: str, clear_orders: bool = False) -> bool:
        """Deactivate group monitoring.

        Args:
            group_id: The group to deactivate
            clear_orders: If True, clear order IDs (use when orders are cancelled)
        """
        if group_id in self._groups:
            group = self._groups[group_id]

            # Log stack trace for debugging auto-deactivation mystery
            import traceback
            logger.info(f"deactivate() called for group '{group.name}' (was_active={group.is_active}, "
                       f"clear_orders={clear_orders})")
            logger.debug(f"deactivate() call stack:\n{''.join(traceback.format_stack())}")

            group.is_active = False

            if clear_orders:
                logger.info(f"Clearing order IDs: oca={group.oca_group_id}, "
                           f"trailing={group.trailing_order_id}, time_exit={group.time_exit_order_id}")
                group.oca_group_id = ""
                group.trailing_order_id = 0
                group.time_exit_order_id = 0

            self._save()
            logger.info(f"Group deactivated: {group.name}")
            return True
        return False

    def update_hwm(self, group_id: str, new_value: float, is_credit: bool = False) -> bool:
        """Update high water mark if value is better (higher for debit, lower for credit).

        Args:
            group_id: Group ID
            new_value: Current trigger value
            is_credit: True for credit positions (short, credit spreads)
                       Credit: better = more negative (lower)
                       Debit: better = higher

        Returns:
            True if HWM was updated
        """
        if group_id not in self._groups:
            return False

        group = self._groups[group_id]

        # Determine if this is a "better" value (new HWM/LWM)
        # Debit: higher is better (profit when value goes up)
        # Credit with positive value (Single Short): lower is better
        # Credit with negative value (Credit Spread): higher (closer to 0) is better
        if is_credit:
            if new_value >= 0:
                # Single short: lower is better
                is_better = new_value < group.high_water_mark or group.high_water_mark == 0
            else:
                # Credit spread (negative values): higher (closer to 0) is better
                is_better = new_value > group.high_water_mark or group.high_water_mark == 0
        else:
            is_better = new_value > group.high_water_mark

        if is_better:
            old_hwm = group.high_water_mark
            group.high_water_mark = new_value
            group.stop_price = calculate_stop_price(
                new_value, group.trail_mode, group.trail_value, is_credit=is_credit
            )
            self._save()
            logger.debug(f"Group {group.name} new HWM=${new_value:.2f} (was ${old_hwm:.2f}) "
                        f"Stop=${group.stop_price:.2f} credit={is_credit}")
            return True
        return False

    def check_stop_triggered(self, group_id: str, current_value: float,
                             is_credit: bool = False) -> bool:
        """Check if stop price was breached. Returns True if triggered.

        IMPORTANT: stop_price is always stored as POSITIVE (for IBKR BAG orders).
        We use abs(current_value) for comparison with credit positions.

        Credit positions (short/credit spread):
        - stop_price = $5.20 (positive, the "bad" absolute price)
        - current = -$4.20 → abs = $4.20 < $5.20 → NOT triggered
        - current = -$5.50 → abs = $5.50 >= $5.20 → TRIGGERED!
        - Triggered when abs(current) >= stop (cost to close is too high)

        Debit positions (long/debit spread):
        - stop_price = $8.50 (the minimum acceptable value)
        - Triggered when current <= stop (value dropped too much)
        """
        if group_id not in self._groups:
            return False

        group = self._groups[group_id]
        if not group.is_active:
            return False

        # IMPORTANT: Don't trigger on invalid/zero prices
        if current_value == 0 or group.stop_price == 0:
            logger.debug(f"Skipping stop check for {group.name}: current={current_value}, stop={group.stop_price}")
            return False

        # NOTE: stop_price is ALWAYS stored as positive (for IBKR BAG orders)
        # For comparison, we need to use abs(current_value) vs stop_price
        #
        # Credit: Stop triggers when price moves AGAINST us (higher absolute cost to close)
        #   - Credit spread: current=-4.20, stop=5.20 → abs(-4.20)=4.20 < 5.20 → NOT triggered
        #   - Trigger when abs(current) >= stop (cost to close increased)
        # Debit: Stop triggers when price DROPS below stop
        #   - current=8.00, stop=8.50 → 8.00 < 8.50 → triggered

        if is_credit:
            # Credit positions: triggered when abs(current) >= stop
            # (cost to close has risen to or above stop level)
            triggered = abs(current_value) >= group.stop_price
        else:
            # Debit: triggered when current <= stop (value dropped)
            triggered = current_value <= group.stop_price

        if triggered:
            logger.warning(f"STOP TRIGGERED: {group.name} at ${current_value:.2f} "
                          f"(stop=${group.stop_price:.2f}, credit={is_credit})")
        return triggered

    def remove_if_order_triggered(self, group_id: str):
        """Auto-cleanup: Remove group when order is triggered."""
        if group_id in self._groups:
            name = self._groups[group_id].name
            self.delete(group_id)
            logger.info(f"Auto-removed group after order triggered: {name}")

    def get_used_quantities(self) -> dict[int, int]:
        """Calculate total quantity used for each con_id across all groups.

        Returns:
            dict mapping con_id -> total absolute quantity allocated across all groups
        """
        usage: dict[int, int] = {}
        for group in self._groups.values():
            for con_id_str, qty in group.position_quantities.items():
                con_id = int(con_id_str)
                usage[con_id] = usage.get(con_id, 0) + abs(qty)
        return usage

    def can_use_position(self, con_id: int, position_qty: float) -> bool:
        """Check if a position can still be added to a new group.

        Args:
            con_id: The position's contract ID
            position_qty: The position's total quantity

        Returns:
            True if there's still available quantity (used < total qty)
        """
        usage = self.get_used_quantities()
        used = usage.get(con_id, 0)
        return used < abs(position_qty)

    def get_available_quantity(self, con_id: int, position_qty: float) -> float:
        """Get remaining available quantity for a position.

        Args:
            con_id: The position's contract ID
            position_qty: The position's total quantity

        Returns:
            Available quantity (total - used)
        """
        usage = self.get_used_quantities()
        used = usage.get(con_id, 0)
        return abs(position_qty) - used


# Global instance
GROUP_MANAGER = GroupManager()
