"""Unit tests for cancel_all_orders logic.

Tests the cancel logic with various group configurations:
1. No active groups - nothing to cancel
2. Group with only trailing_order_id (combo order case)
3. Group with oca_group_id (single-leg order case)
4. Group with time_exit_order_id (time-based exit)
5. Multiple active groups - all processed
6. Mixed active/inactive groups - only active ones processed

Note: We test the core logic directly, not through Reflex event handlers,
because Reflex's @rx.event decorator doesn't support mocking well.
"""
import pytest
from unittest.mock import MagicMock, patch
from dataclasses import dataclass


@dataclass
class MockGroup:
    """Mock Group class matching trailing_stop_web.groups.Group structure."""
    id: str
    name: str
    is_active: bool
    trailing_order_id: int = 0
    oca_group_id: str = ""
    time_exit_order_id: int = 0


class MockGroupManager:
    """Mock GroupManager for testing."""
    def __init__(self):
        self.groups = {}
        self._deactivate_calls = []

    def get_all(self):
        """Return all groups."""
        return list(self.groups.values())

    def deactivate(self, group_id: str, clear_orders: bool = False):
        """Track deactivate calls."""
        self._deactivate_calls.append((group_id, clear_orders))
        if group_id in self.groups:
            self.groups[group_id].is_active = False


class MockBroker:
    """Mock Broker for testing."""
    def __init__(self):
        self.cancelled_orders = []
        self.cancelled_oca_groups = []
        self._fail_orders = set()  # Order IDs that should fail

    def cancel_order(self, order_id: int) -> bool:
        """Track and return success for order cancellation."""
        if order_id > 0 and order_id not in self._fail_orders:
            self.cancelled_orders.append(order_id)
            return True
        return False

    def cancel_oca_group(self, oca_group: str) -> bool:
        """Track and return success for OCA group cancellation."""
        if oca_group:
            self.cancelled_oca_groups.append(oca_group)
            return True
        return False


def cancel_all_orders_logic(group_manager, broker):
    """
    Extract of the cancel_all_orders logic from state.py for testing.

    This mirrors the implementation in AppState.cancel_all_orders() but
    without Reflex dependencies, making it testable.
    """
    cancelled_count = 0

    for g in group_manager.get_all():
        if not g.is_active:
            continue

        cancelled = False

        # For combo orders: OCA is not supported, use trailing_order_id directly
        if g.trailing_order_id:
            if broker.cancel_order(g.trailing_order_id):
                cancelled = True

        # Try OCA group as fallback (only works for single-leg orders)
        if not cancelled and g.oca_group_id:
            if broker.cancel_oca_group(g.oca_group_id):
                cancelled = True

        # Also try to cancel time exit order if present
        if g.time_exit_order_id:
            broker.cancel_order(g.time_exit_order_id)

        if cancelled:
            cancelled_count += 1

        # Deactivate group and clear orders
        group_manager.deactivate(g.id, clear_orders=True)

    return cancelled_count


class TestCancelAllOrdersLogic:
    """Test suite for cancel_all_orders logic."""

    @pytest.fixture
    def broker(self):
        """Provide mock broker."""
        return MockBroker()

    @pytest.fixture
    def group_manager(self):
        """Provide mock group manager."""
        return MockGroupManager()

    def test_no_active_groups(self, broker, group_manager):
        """Scenario 1: No active groups - nothing should be cancelled."""
        # Add inactive group
        group_manager.groups['g1'] = MockGroup(
            id='g1', name='Group1', is_active=False,
            trailing_order_id=101
        )

        count = cancel_all_orders_logic(group_manager, broker)

        assert count == 0
        assert len(broker.cancelled_orders) == 0
        assert len(broker.cancelled_oca_groups) == 0
        assert len(group_manager._deactivate_calls) == 0

    def test_single_group_with_trailing_order(self, broker, group_manager):
        """Scenario 2: Group with only trailing_order_id (combo order case)."""
        group_manager.groups['g1'] = MockGroup(
            id='g1', name='Group1', is_active=True,
            trailing_order_id=101, oca_group_id="", time_exit_order_id=0
        )

        count = cancel_all_orders_logic(group_manager, broker)

        assert count == 1
        assert 101 in broker.cancelled_orders
        assert len(broker.cancelled_oca_groups) == 0
        assert ('g1', True) in group_manager._deactivate_calls

    def test_single_group_with_oca_only(self, broker, group_manager):
        """Scenario 3: Group with oca_group_id only (single-leg order fallback)."""
        group_manager.groups['g1'] = MockGroup(
            id='g1', name='Group1', is_active=True,
            trailing_order_id=0, oca_group_id="oca_123", time_exit_order_id=0
        )

        count = cancel_all_orders_logic(group_manager, broker)

        assert count == 1
        assert len(broker.cancelled_orders) == 0
        assert "oca_123" in broker.cancelled_oca_groups
        assert ('g1', True) in group_manager._deactivate_calls

    def test_single_group_with_time_exit_order(self, broker, group_manager):
        """Scenario 4: Time exit order is also cancelled."""
        group_manager.groups['g1'] = MockGroup(
            id='g1', name='Group1', is_active=True,
            trailing_order_id=101, oca_group_id="", time_exit_order_id=201
        )

        count = cancel_all_orders_logic(group_manager, broker)

        assert count == 1
        assert 101 in broker.cancelled_orders
        assert 201 in broker.cancelled_orders
        assert ('g1', True) in group_manager._deactivate_calls

    def test_single_group_with_all_order_types(self, broker, group_manager):
        """Group with all order types - trailing takes priority, time exit also cancelled."""
        group_manager.groups['g1'] = MockGroup(
            id='g1', name='Group1', is_active=True,
            trailing_order_id=101, oca_group_id="oca_123", time_exit_order_id=201
        )

        count = cancel_all_orders_logic(group_manager, broker)

        assert count == 1
        # Trailing order cancelled first
        assert 101 in broker.cancelled_orders
        # OCA NOT called because trailing succeeded
        assert "oca_123" not in broker.cancelled_oca_groups
        # Time exit also cancelled
        assert 201 in broker.cancelled_orders
        assert ('g1', True) in group_manager._deactivate_calls

    def test_multiple_active_groups(self, broker, group_manager):
        """Scenario 5: Multiple active groups - all processed."""
        group_manager.groups['g1'] = MockGroup(
            id='g1', name='Group1', is_active=True,
            trailing_order_id=101
        )
        group_manager.groups['g2'] = MockGroup(
            id='g2', name='Group2', is_active=True,
            trailing_order_id=102
        )
        group_manager.groups['g3'] = MockGroup(
            id='g3', name='Group3', is_active=True,
            oca_group_id="oca_456"
        )

        count = cancel_all_orders_logic(group_manager, broker)

        assert count == 3
        assert 101 in broker.cancelled_orders
        assert 102 in broker.cancelled_orders
        assert "oca_456" in broker.cancelled_oca_groups
        assert len(group_manager._deactivate_calls) == 3

    def test_mixed_active_and_inactive_groups(self, broker, group_manager):
        """Scenario 6: Only active groups are cancelled."""
        group_manager.groups['g1'] = MockGroup(
            id='g1', name='Group1', is_active=True,
            trailing_order_id=101
        )
        group_manager.groups['g2'] = MockGroup(
            id='g2', name='Group2', is_active=False,
            trailing_order_id=102
        )
        group_manager.groups['g3'] = MockGroup(
            id='g3', name='Group3', is_active=True,
            oca_group_id="oca_456"
        )

        count = cancel_all_orders_logic(group_manager, broker)

        assert count == 2
        assert 101 in broker.cancelled_orders
        assert 102 not in broker.cancelled_orders  # Inactive, not cancelled
        assert "oca_456" in broker.cancelled_oca_groups
        # Only 2 deactivate calls (for active groups)
        assert len(group_manager._deactivate_calls) == 2
        assert ('g1', True) in group_manager._deactivate_calls
        assert ('g2', True) not in group_manager._deactivate_calls
        assert ('g3', True) in group_manager._deactivate_calls

    def test_fallback_to_oca_when_trailing_fails(self, broker, group_manager):
        """When trailing_order cancel fails, fallback to OCA."""
        broker._fail_orders.add(101)  # Make trailing order fail

        group_manager.groups['g1'] = MockGroup(
            id='g1', name='Group1', is_active=True,
            trailing_order_id=101, oca_group_id="oca_123"
        )

        count = cancel_all_orders_logic(group_manager, broker)

        assert count == 1
        assert 101 not in broker.cancelled_orders  # Failed
        assert "oca_123" in broker.cancelled_oca_groups  # Fallback worked
        assert ('g1', True) in group_manager._deactivate_calls

    def test_groups_deactivated_with_clear_orders_flag(self, broker, group_manager):
        """All deactivations use clear_orders=True."""
        group_manager.groups['g1'] = MockGroup(
            id='g1', name='Group1', is_active=True,
            trailing_order_id=101
        )
        group_manager.groups['g2'] = MockGroup(
            id='g2', name='Group2', is_active=True,
            oca_group_id="oca_123"
        )

        cancel_all_orders_logic(group_manager, broker)

        # All deactivations should have clear_orders=True
        for group_id, clear_orders in group_manager._deactivate_calls:
            assert clear_orders is True, f"Group {group_id} was deactivated without clear_orders=True"

    def test_empty_order_ids_not_cancelled(self, broker, group_manager):
        """Groups with empty/zero order IDs don't call broker."""
        group_manager.groups['g1'] = MockGroup(
            id='g1', name='Group1', is_active=True,
            trailing_order_id=0, oca_group_id="", time_exit_order_id=0
        )

        count = cancel_all_orders_logic(group_manager, broker)

        assert count == 0
        assert len(broker.cancelled_orders) == 0
        assert len(broker.cancelled_oca_groups) == 0
        # Group still gets deactivated
        assert ('g1', True) in group_manager._deactivate_calls

    def test_cancelled_count_reflects_successful_cancels(self, broker, group_manager):
        """cancelled_count only counts groups where cancel succeeded."""
        broker._fail_orders.add(101)  # Make this one fail

        group_manager.groups['g1'] = MockGroup(
            id='g1', name='Group1', is_active=True,
            trailing_order_id=101, oca_group_id=""  # No fallback
        )
        group_manager.groups['g2'] = MockGroup(
            id='g2', name='Group2', is_active=True,
            trailing_order_id=102  # Will succeed
        )

        count = cancel_all_orders_logic(group_manager, broker)

        assert count == 1  # Only g2 succeeded
        # But both groups are still deactivated
        assert len(group_manager._deactivate_calls) == 2


class TestCancelAllOrdersIntegration:
    """Integration test with real Group and GroupManager classes."""

    def test_with_real_group_and_manager(self):
        """Test using actual Group and GroupManager classes."""
        from trailing_stop_web.groups import Group, GroupManager
        import tempfile
        import os

        # Create temp file for GroupManager persistence
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            f.write('{}')
            temp_file = f.name

        try:
            # Create real GroupManager with temp file
            manager = GroupManager()
            manager._file_path = temp_file

            # Create groups directly
            group1 = Group(
                id='test1',
                name='Test Group 1',
                is_active=True,
            )
            group1.trailing_order_id = 101

            group2 = Group(
                id='test2',
                name='Test Group 2',
                is_active=True,
            )
            group2.oca_group_id = "oca_test"

            manager._groups['test1'] = group1
            manager._groups['test2'] = group2

            # Mock broker
            broker = MockBroker()

            # Run cancel logic
            count = cancel_all_orders_logic(manager, broker)

            assert count == 2
            assert 101 in broker.cancelled_orders
            assert "oca_test" in broker.cancelled_oca_groups

            # Verify groups are deactivated
            assert manager._groups['test1'].is_active is False
            assert manager._groups['test2'].is_active is False

        finally:
            os.unlink(temp_file)
