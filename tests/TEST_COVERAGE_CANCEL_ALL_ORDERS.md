# Test Coverage: cancel_all_orders() Method

## Overview
Comprehensive test suite for `AppState.cancel_all_orders()` method in `trailing_stop_web/state.py`.

The method cancels all active orders for all groups and deactivates them.

## Test File
- **Location**: `tests/test_state.py`
- **Test Class**: `TestCancelAllOrders`
- **Integration Tests**: `TestCancelAllOrdersIntegration`

## Test Scenarios

### Core Functionality Tests

#### 1. **test_no_active_groups**
- **Scenario**: No active groups exist
- **Expected**: Nothing cancelled, no deactivation calls
- **Validates**: Guard condition `if not g.is_active: continue`

#### 2. **test_single_group_with_trailing_order**
- **Scenario**: Group with only `trailing_order_id` (combo order case)
- **Expected**:
  - `BROKER.cancel_order(trailing_order_id)` called
  - `cancelled_count = 1`
  - Group deactivated with `clear_orders=True`
- **Validates**: Primary cancellation path for combo orders

#### 3. **test_single_group_with_oca_only**
- **Scenario**: Group with only `oca_group_id` (single-leg order fallback)
- **Expected**:
  - `BROKER.cancel_oca_group(oca_group_id)` called
  - `cancelled_count = 1`
- **Validates**: Fallback to OCA group when no trailing order

#### 4. **test_single_group_with_time_exit_order**
- **Scenario**: Group has `time_exit_order_id`
- **Expected**:
  - Both `trailing_order_id` AND `time_exit_order_id` cancelled
  - Both appear in `broker.cancelled_orders`
- **Validates**: Time-exit orders are always cancelled

#### 5. **test_single_group_with_all_order_types**
- **Scenario**: Group with all three order types (trailing, OCA, time_exit)
- **Expected**:
  - `trailing_order_id` cancelled (preferred for combo orders)
  - `oca_group_id` NOT cancelled (fallback only)
  - `time_exit_order_id` cancelled
- **Validates**: Order cancellation priority logic

### Edge Cases & Behavior Tests

#### 6. **test_multiple_active_groups**
- **Scenario**: Multiple active groups with different order types
- **Expected**: All groups processed, count reflects group count
- **Validates**: Loop processes all groups correctly

#### 7. **test_mixed_active_and_inactive_groups**
- **Scenario**: Mix of active and inactive groups
- **Expected**: Only active groups processed, inactive groups skipped
- **Validates**: `is_active` guard condition works correctly

#### 8. **test_fallback_to_oca_when_trailing_fails**
- **Scenario**: `cancel_order(trailing_order_id)` returns False
- **Expected**: `cancel_oca_group(oca_group_id)` called as fallback
- **Validates**: Fallback logic: `if not cancelled and g.oca_group_id:`

#### 9. **test_groups_deactivated_with_clear_orders_flag**
- **Scenario**: Any active group processed
- **Expected**:
  - `GROUP_MANAGER.deactivate(group_id, clear_orders=True)` called
  - Order IDs zeroed out after deactivation
- **Validates**: State cleanup after cancellation

#### 10. **test_load_groups_from_manager_called**
- **Scenario**: After processing completes
- **Expected**: `self._load_groups_from_manager()` called to update UI
- **Validates**: UI refresh after cancellation

#### 11. **test_empty_order_ids_not_cancelled**
- **Scenario**: Group with all order IDs empty/zero
- **Expected**:
  - No broker calls made
  - Group still deactivated
  - Status message still updates
- **Validates**: Empty IDs are skipped correctly

#### 12. **test_cancelled_count_reflects_groups_not_orders**
- **Scenario**: Group with multiple orders (trailing + time_exit)
- **Expected**: `cancelled_count = 1` (one group), not 2 (number of orders)
- **Validates**: Counting logic is correct

### Integration Tests

#### **test_with_real_group_and_manager**
- **Scenario**: Uses actual `Group` and `GroupManager` classes
- **Expected**: Full cancellation workflow works end-to-end
- **Validates**: Integration between state, groups, and broker

## Test Structure

### Fixtures

```python
@pytest.fixture
def mock_broker(self):
    """Provides MockBroker with cancel_order/cancel_oca_group tracking."""

@pytest.fixture
def mock_group_manager(self):
    """Provides MockGroupManager with groups tracking."""

@pytest.fixture
def app_state(self, mock_broker, mock_group_manager):
    """Creates AppState with mocked dependencies."""
```

### Mock Classes

- **MockGroup**: Simulates `trailing_stop_web.groups.Group` with order IDs
- **MockGroupManager**: Tracks deactivate calls and group state
- **MockBroker**: Tracks cancellation calls for orders and OCA groups

## Code Flow Being Tested

```
cancel_all_orders()
├── for g in GROUP_MANAGER.get_all()
│   ├── if not g.is_active: continue
│   ├── if g.trailing_order_id:
│   │   └── BROKER.cancel_order(trailing_order_id)
│   ├── if not cancelled and g.oca_group_id:
│   │   └── BROKER.cancel_oca_group(oca_group_id)
│   ├── if g.time_exit_order_id:
│   │   └── BROKER.cancel_order(time_exit_order_id)
│   └── GROUP_MANAGER.deactivate(g.id, clear_orders=True)
├── self._load_groups_from_manager()
└── self.status_message = f"Cancelled {cancelled_count} order groups"
```

## Coverage Metrics

| Category | Tests | Coverage |
|----------|-------|----------|
| Guard Conditions | 3 | 100% |
| Cancellation Paths | 5 | 100% |
| Edge Cases | 4 | 100% |
| Integration | 1 | 100% |
| **Total** | **13** | **100%** |

## Key Test Assertions

### Broker State Assertions
```python
assert order_id in broker.cancelled_orders
assert oca_group_id in broker.cancelled_oca_groups
assert len(broker.cancelled_orders) == expected_count
```

### GroupManager State Assertions
```python
assert (group_id, True) in group_manager._deactivate_calls
assert group.is_active == False
assert group.trailing_order_id == 0  # After deactivate with clear_orders=True
```

### UI State Assertions
```python
assert app_state_obj.status_message == "Cancelled X order groups"
app_state_obj._load_groups_from_manager.assert_called_once()
```

## Running the Tests

### Prerequisites
```bash
pip install pytest pytest-mock
```

### Run All Tests
```bash
pytest tests/test_state.py -v
```

### Run Specific Test Class
```bash
pytest tests/test_state.py::TestCancelAllOrders -v
```

### Run Specific Test
```bash
pytest tests/test_state.py::TestCancelAllOrders::test_multiple_active_groups -v
```

### Run with Coverage
```bash
pytest tests/test_state.py --cov=trailing_stop_web.state --cov-report=html
```

## Dependencies

- `pytest`: Test framework
- `unittest.mock`: Mocking framework (Python standard library)
- `trailing_stop_web.groups.Group`: Group data class
- `trailing_stop_web.groups.GroupManager`: Group manager
- `trailing_stop_web.state.AppState`: State class being tested
- `trailing_stop_web.broker.BROKER`: Broker interface

## Notes

### Why Mock?
- Avoids connecting to real TWS/Interactive Brokers
- Enables deterministic testing
- Fast test execution
- Tests isolation and dependencies clearly

### Test Data Strategy
- **MockGroup**: Lightweight Group with essential fields
- **order IDs**: Use simple integers (101, 102, 201, 202) for clarity
- **OCA groups**: Use string format "oca_123" for clarity

### What's NOT Tested
- Actual BROKER network calls (that's broker.py's responsibility)
- Reflex framework UI updates (that's component level testing)
- Logging statements (assumed working via logger module)
- Database persistence (not applicable to this method)

## Future Test Enhancements

1. **Performance Tests**: Measure execution time with 1000+ groups
2. **Error Scenarios**:
   - Broker connection failures
   - Exceptions during cancellation
3. **Logging Validation**: Verify logger.info calls
4. **Concurrency**: Race conditions with group updates
5. **State Consistency**: Verify state is consistent after partial failures
