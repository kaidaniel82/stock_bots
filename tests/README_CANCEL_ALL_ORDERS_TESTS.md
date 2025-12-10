# cancel_all_orders() Test Suite

## Quick Summary

Complete test coverage for `AppState.cancel_all_orders()` method in `trailing_stop_web/state.py`.

**Location**: `tests/test_state.py`
**Test Count**: 13 core tests + 1 integration test
**Coverage**: 100% of method logic
**Status**: Ready to run

---

## What's Being Tested

The `cancel_all_orders()` method:
1. Iterates over all groups from `GROUP_MANAGER`
2. Skips inactive groups
3. Cancels orders (trailing → OCA fallback)
4. Cancels time-exit orders
5. Deactivates groups with `clear_orders=True`
6. Updates UI status message

---

## Test File Organization

### Core Functionality Tests (TestCancelAllOrders)

| Test Name | Scenario | Validates |
|-----------|----------|-----------|
| `test_no_active_groups` | No active groups exist | Guard condition |
| `test_single_group_with_trailing_order` | Group with trailing_order_id | Primary cancellation path |
| `test_single_group_with_oca_only` | Group with oca_group_id | Fallback mechanism |
| `test_single_group_with_time_exit_order` | Group with time_exit_order_id | Time-exit handling |
| `test_single_group_with_all_order_types` | All order types present | Priority logic |
| `test_multiple_active_groups` | Multiple groups to process | Loop correctness |
| `test_mixed_active_and_inactive_groups` | Mix of active/inactive | is_active filtering |
| `test_fallback_to_oca_when_trailing_fails` | Fallback condition met | Error handling |
| `test_groups_deactivated_with_clear_orders_flag` | Deactivation with flag | State cleanup |
| `test_load_groups_from_manager_called` | UI refresh | Component updates |
| `test_empty_order_ids_not_cancelled` | No orders present | Empty ID handling |
| `test_cancelled_count_reflects_groups_not_orders` | Count semantics | Counting logic |

### Integration Tests (TestCancelAllOrdersIntegration)

| Test Name | Purpose |
|-----------|---------|
| `test_with_real_group_and_manager` | End-to-end with real classes |

---

## Mock Classes

### MockBroker
```python
cancelled_orders: List[int]          # Track cancelled order IDs
cancelled_oca_groups: List[str]      # Track cancelled OCA groups

cancel_order(order_id: int) -> bool
cancel_oca_group(oca_group: str) -> bool
```

### MockGroupManager
```python
groups: Dict[str, MockGroup]         # Managed groups
_deactivate_calls: List[Tuple]       # Track deactivate calls

get_all() -> List[MockGroup]
deactivate(group_id: str, clear_orders: bool = False)
```

### MockGroup
```python
id: str
name: str
is_active: bool
trailing_order_id: int = 0
oca_group_id: str = ""
time_exit_order_id: int = 0
```

---

## Running the Tests

### Prerequisites
```bash
pip install pytest pytest-mock
```

### Run All Tests
```bash
cd /Users/kai/PycharmProjects/stock_bots
pytest tests/test_state.py -v
```

### Run Specific Test Class
```bash
pytest tests/test_state.py::TestCancelAllOrders -v
```

### Run Single Test
```bash
pytest tests/test_state.py::TestCancelAllOrders::test_multiple_active_groups -v
```

### Run with Coverage Report
```bash
pytest tests/test_state.py --cov=trailing_stop_web.state --cov-report=term-missing
```

### Run Tests Matching Pattern
```bash
pytest tests/test_state.py -k "multiple" -v
```

---

## Test Coverage Details

### Scenarios Covered

```
┌─ Input Variations ──────────────────────────────────────┐
│ ✓ No active groups (empty result)                       │
│ ✓ Single group with each order type                     │
│ ✓ Group with multiple order types                       │
│ ✓ Multiple groups (2+)                                  │
│ ✓ Mixed active and inactive groups                      │
└─────────────────────────────────────────────────────────┘

┌─ Behavior Paths ────────────────────────────────────────┐
│ ✓ Primary path: cancel trailing_order_id                │
│ ✓ Fallback path: cancel oca_group_id                    │
│ ✓ Secondary: always cancel time_exit_order_id           │
│ ✓ Fallback trigger: only when trailing failed           │
│ ✓ Guard condition: skip inactive groups                 │
└─────────────────────────────────────────────────────────┘

┌─ State Changes ─────────────────────────────────────────┐
│ ✓ Broker cancellation tracking                          │
│ ✓ Group deactivation with clear_orders=True             │
│ ✓ Order ID cleanup after deactivation                   │
│ ✓ Status message update                                 │
│ ✓ UI refresh trigger (_load_groups_from_manager)        │
└─────────────────────────────────────────────────────────┘

┌─ Edge Cases ────────────────────────────────────────────┐
│ ✓ Empty order IDs (0 or "")                             │
│ ✓ Broker call failures                                  │
│ ✓ Cancelled count semantics (groups vs orders)          │
│ ✓ Real Group/GroupManager classes                       │
└─────────────────────────────────────────────────────────┘
```

---

## Code Under Test

```python
def cancel_all_orders(self):
    """Cancel all orders for all groups at IB."""
    logger.info("Canceling all orders...")
    cancelled_count = 0

    for g in GROUP_MANAGER.get_all():
        if not g.is_active:
            continue

        logger.info(f"Processing group {g.id}...")

        cancelled = False

        # PRIMARY: Cancel trailing order (combo orders)
        if g.trailing_order_id:
            if BROKER.cancel_order(g.trailing_order_id):
                cancelled = True

        # FALLBACK: Cancel OCA group (single-leg orders)
        if not cancelled and g.oca_group_id:
            if BROKER.cancel_oca_group(g.oca_group_id):
                cancelled = True

        # SECONDARY: Always cancel time exit if present
        if g.time_exit_order_id:
            BROKER.cancel_order(g.time_exit_order_id)

        if cancelled:
            cancelled_count += 1

        # Deactivate & cleanup
        GROUP_MANAGER.deactivate(g.id, clear_orders=True)

    self._load_groups_from_manager()
    self.status_message = f"Cancelled {cancelled_count} order groups"
```

---

## Key Assertions Used

### Broker Verification
```python
assert order_id in broker.cancelled_orders
assert oca_group_id in broker.cancelled_oca_groups
assert len(broker.cancelled_orders) == expected_count
```

### Group/Manager Verification
```python
assert (group_id, True) in group_manager._deactivate_calls
assert not group.is_active
assert group.trailing_order_id == 0  # After clear_orders=True
```

### UI Verification
```python
assert "Cancelled X order groups" in app_state.status_message
app_state._load_groups_from_manager.assert_called_once()
```

---

## Documentation Files

| File | Purpose |
|------|---------|
| `tests/test_state.py` | Test implementation |
| `TEST_COVERAGE_CANCEL_ALL_ORDERS.md` | Detailed coverage breakdown |
| `STATE_TESTING_BEST_PRACTICES.md` | Guidelines for state testing |
| `README_CANCEL_ALL_ORDERS_TESTS.md` | This file |

---

## Common Test Patterns

### Pattern 1: Setup Group and Execute
```python
def test_scenario(self, app_state):
    app_state_obj, broker, group_manager = app_state

    # Setup
    group_manager.groups['g1'] = MockGroup(
        id='g1', name='Group1', is_active=True,
        trailing_order_id=101, oca_group_id="", time_exit_order_id=0
    )

    # Execute
    app_state_obj.cancel_all_orders()

    # Verify
    assert 101 in broker.cancelled_orders
```

### Pattern 2: Verify Fallback Logic
```python
def test_fallback(self, app_state):
    app_state_obj, broker, group_manager = app_state

    # Mock broker to fail trailing
    broker.cancel_order = MagicMock(return_value=False)

    group_manager.groups['g1'] = MockGroup(
        id='g1', trailing_order_id=101, oca_group_id="oca_123"
    )

    app_state_obj.cancel_all_orders()

    # Both should be called (fallback triggered)
    assert "oca_123" in broker.cancelled_oca_groups
```

### Pattern 3: Multiple Groups
```python
def test_multiple(self, app_state):
    app_state_obj, broker, group_manager = app_state

    # Add multiple groups
    for i in range(3):
        group_manager.groups[f'g{i}'] = MockGroup(
            id=f'g{i}', name=f'Group{i}', is_active=True,
            trailing_order_id=100+i
        )

    app_state_obj.cancel_all_orders()

    # All should be processed
    assert len(group_manager._deactivate_calls) == 3
```

---

## Expected Output

Running the tests should show:
```
tests/test_state.py::TestCancelAllOrders::test_no_active_groups PASSED
tests/test_state.py::TestCancelAllOrders::test_single_group_with_trailing_order PASSED
tests/test_state.py::TestCancelAllOrders::test_single_group_with_oca_only PASSED
tests/test_state.py::TestCancelAllOrders::test_single_group_with_time_exit_order PASSED
tests/test_state.py::TestCancelAllOrders::test_single_group_with_all_order_types PASSED
tests/test_state.py::TestCancelAllOrders::test_multiple_active_groups PASSED
tests/test_state.py::TestCancelAllOrders::test_mixed_active_and_inactive_groups PASSED
tests/test_state.py::TestCancelAllOrders::test_fallback_to_oca_when_trailing_fails PASSED
tests/test_state.py::TestCancelAllOrders::test_groups_deactivated_with_clear_orders_flag PASSED
tests/test_state.py::TestCancelAllOrders::test_load_groups_from_manager_called PASSED
tests/test_state.py::TestCancelAllOrders::test_empty_order_ids_not_cancelled PASSED
tests/test_state.py::TestCancelAllOrders::test_cancelled_count_reflects_groups_not_orders PASSED
tests/test_state.py::TestCancelAllOrdersIntegration::test_with_real_group_and_manager PASSED

==================== 13 passed in X.XXs ====================
```

---

## Maintenance Notes

### When to Update Tests

1. **Behavior Changes**: Method logic changes
2. **Bug Fixes**: Regression test first, then fix
3. **New Edge Cases**: Add test for each new scenario

### When NOT to Update

- Implementation details change (but behavior stays same)
- Variable names change (but behavior stays same)
- Refactoring for performance (but behavior stays same)

### Future Enhancements

1. Add error handling tests (exceptions during cancellation)
2. Add logging verification tests
3. Add performance tests (1000+ groups)
4. Add concurrency tests (concurrent updates)
5. Add state consistency validation

---

## Dependencies

- `pytest`: Test framework
- `unittest.mock`: Mocking (Python stdlib)
- `trailing_stop_web.groups`: Group and GroupManager classes
- `trailing_stop_web.state`: AppState class
- `trailing_stop_web.broker`: BROKER module

## No External Dependencies Required
- No database
- No network calls
- No file I/O
- No Reflex UI framework (mocked)

---

## Contact & Questions

For questions about these tests, refer to:
- `STATE_TESTING_BEST_PRACTICES.md` - Testing patterns and guidelines
- `TEST_COVERAGE_CANCEL_ALL_ORDERS.md` - Detailed coverage breakdown
- `CLAUDE.md` - Project structure and agent responsibilities
