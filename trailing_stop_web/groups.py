"""Group management with JSON persistence."""
import json
from pathlib import Path
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional

from .logger import logger

# Data directory for persistence - OUTSIDE project to avoid Reflex hot reload
DATA_DIR = Path.home() / ".trailing_stop_web"
GROUPS_FILE = DATA_DIR / "groups.json"


@dataclass
class Group:
    """A trailing stop group containing multiple positions."""
    # === BASIS ===
    id: str
    name: str
    con_ids: list[int]           # Position ConIDs in this group
    created_at: str = ""
    is_active: bool = False

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

    # === RUNTIME STATE ===
    high_water_mark: float = 0.0
    stop_price: float = 0.0

    # === ORDER TRACKING (Phase 2) ===
    oca_group_id: str = ""                # TWS OCA Group ID
    trailing_order_id: int = 0            # TWS Order ID
    time_exit_order_id: int = 0           # TWS Order ID

    # Backwards compatibility: alias for trail_value
    @property
    def trail_percent(self) -> float:
        """Backwards compatibility alias."""
        return self.trail_value if self.trail_mode == "percent" else 0.0

    def to_dict(self) -> dict:
        """Convert to dict for JSON serialization."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Group":
        """Create from dict."""
        return cls(**data)


def calculate_stop_price(hwm: float, trail_mode: str, trail_value: float) -> float:
    """Calculate stop price based on mode and value.

    Args:
        hwm: High water mark (current value)
        trail_mode: "percent" or "absolute"
        trail_value: Trail amount (10 = 10% or $10)

    Returns:
        Calculated stop price
    """
    if trail_mode == "percent":
        return round(hwm * (1 - trail_value / 100), 2)
    else:  # absolute
        return round(hwm - trail_value, 2)


class GroupManager:
    """Groups CRUD with JSON persistence."""

    def __init__(self):
        self._groups: dict[str, Group] = {}
        self._load()

    def _load(self):
        """Load groups from JSON file."""
        if GROUPS_FILE.exists():
            try:
                data = json.loads(GROUPS_FILE.read_text())
                for g in data.get("groups", []):
                    group = Group.from_dict(g)
                    self._groups[group.id] = group
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
            logger.debug(f"Saved {len(self._groups)} groups")
        except Exception as e:
            logger.error(f"Error saving groups: {e}")

    def create(
        self,
        name: str,
        con_ids: list[int],
        trail_value: float = 10.0,
        trail_mode: str = "percent",
        trigger_price_type: str = "mark",
        stop_type: str = "market",
        limit_offset: float = 0.0,
        time_exit_enabled: bool = False,
        time_exit_time: str = "15:55",
        initial_value: float = 0.0,
    ) -> Group:
        """Create a new group."""
        group_id = f"grp_{len(self._groups) + 1}_{datetime.now().strftime('%H%M%S')}"
        stop_price = calculate_stop_price(initial_value, trail_mode, trail_value)

        group = Group(
            id=group_id,
            name=name,
            con_ids=con_ids,
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
            high_water_mark=initial_value,
            stop_price=stop_price,
        )
        self._groups[group.id] = group
        self._save()
        logger.info(f"Group created: {group.name} ({group.id}) with {len(con_ids)} positions")
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
        return self._groups.get(group_id)

    def get_all(self) -> list[Group]:
        """Get all groups."""
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

    def activate(self, group_id: str, current_value: float = None) -> bool:
        """Activate group monitoring."""
        if group_id in self._groups:
            group = self._groups[group_id]
            group.is_active = True
            if current_value is not None:
                group.high_water_mark = current_value
                group.stop_price = calculate_stop_price(
                    current_value, group.trail_mode, group.trail_value
                )
            self._save()
            logger.info(f"Group activated: {group.name} HWM=${group.high_water_mark:.2f} Stop=${group.stop_price:.2f}")
            return True
        return False

    def deactivate(self, group_id: str) -> bool:
        """Deactivate group monitoring."""
        if group_id in self._groups:
            group = self._groups[group_id]
            group.is_active = False
            self._save()
            logger.info(f"Group deactivated: {group.name}")
            return True
        return False

    def update_hwm(self, group_id: str, new_value: float) -> bool:
        """Update high water mark if value is higher."""
        if group_id not in self._groups:
            return False

        group = self._groups[group_id]
        if new_value > group.high_water_mark:
            group.high_water_mark = new_value
            group.stop_price = calculate_stop_price(
                new_value, group.trail_mode, group.trail_value
            )
            self._save()
            logger.debug(f"Group {group.name} new HWM=${new_value:.2f} Stop=${group.stop_price:.2f}")
            return True
        return False

    def check_stop_triggered(self, group_id: str, current_value: float) -> bool:
        """Check if stop price was breached. Returns True if triggered."""
        if group_id not in self._groups:
            return False

        group = self._groups[group_id]
        if not group.is_active:
            return False

        if current_value <= group.stop_price:
            logger.warning(f"STOP TRIGGERED: {group.name} at ${current_value:.2f} (stop=${group.stop_price:.2f})")
            return True
        return False

    def remove_if_order_triggered(self, group_id: str):
        """Auto-cleanup: Remove group when order is triggered."""
        if group_id in self._groups:
            name = self._groups[group_id].name
            self.delete(group_id)
            logger.info(f"Auto-removed group after order triggered: {name}")


# Global instance
GROUP_MANAGER = GroupManager()
