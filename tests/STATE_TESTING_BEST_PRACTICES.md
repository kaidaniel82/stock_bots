# State Testing Best Practices

## Overview
This document outlines best practices for testing the `AppState` class and similar stateful components in the trailing_stop_web application.

## Design Principles

### 1. Mock External Dependencies
Never test real dependencies; isolate the unit under test.

**Bad:**
```python
def test_cancel_all_orders(self):
    state = AppState()  # Uses real BROKER
    state.cancel_all_orders()  # Makes real TWS calls
```

**Good:**
```python
def test_cancel_all_orders(self, mock_broker, mock_group_manager):
    app_state_obj.cancel_all_orders()  # Uses mocked dependencies
    assert mock_broker.cancelled_orders == [101]
```

### 2. Test Behavior, Not Implementation Details
Focus on observable outcomes, not internal implementation.

**Bad:**
```python
def test_cancel_all_orders(self):
    # Testing HOW it cancels (implementation detail)
    assert state.for_loop_executed
    assert state.temp_variable == 5
```

**Good:**
```python
def test_cancel_all_orders(self):
    # Testing WHAT it does (observable behavior)
    assert 101 in broker.cancelled_orders
    assert group.is_active == False
    assert "Cancelled 1" in state.status_message
```

### 3. Use Fixtures for Reusable Setup

**Pattern:**
```python
@pytest.fixture
def mock_broker(self):
    """Provides mock broker."""
    return MockBroker()

@pytest.fixture
def app_state(self, mock_broker, mock_group_manager):
    """Fixture with dependencies injected."""
    app_state = AppState()
    # Patch dependencies
    return app_state
```

**Benefits:**
- Reusable across tests
- Clear dependencies
- Easy to modify setup

### 4. One Assertion Focus Per Test

**Pattern:**
```python
def test_trailing_order_cancelled(self, app_state):
    """Test ONLY that trailing orders are cancelled."""
    # Setup only what's needed
    group_manager.groups['g1'] = MockGroup(
        id='g1', trailing_order_id=101, oca_group_id=""
    )

    # Execute
    app_state.cancel_all_orders()

    # Assert ONLY one thing (trailing order cancelled)
    assert 101 in broker.cancelled_orders
```

### 5. Clear Test Names = Clear Documentation

**Bad:**
```python
def test_cancel(self):  # What does this test?

def test_1(self):  # Meaningless

def test_works(self):  # Too vague
```

**Good:**
```python
def test_trailing_order_cancelled_for_combo_orders(self):
    """Test trailing order is preferred for combo order cancellation."""

def test_oca_group_fallback_when_no_trailing_order(self):
    """Test OCA group is used only when trailing_order_id is empty."""

def test_only_active_groups_processed(self):
    """Test inactive groups are skipped during cancellation."""
```

### 6. Test Edge Cases & Boundaries

**Example Edge Cases:**
```python
# Empty collections
test_no_active_groups()

# Null/zero values
test_empty_order_ids_not_cancelled()

# Multiple items
test_multiple_active_groups()

# Mixed valid/invalid
test_mixed_active_and_inactive_groups()

# Fallback paths
test_fallback_to_oca_when_trailing_fails()
```

## Mock Design Patterns

### Pattern 1: Track Method Calls

```python
class MockBroker:
    def __init__(self):
        self.cancelled_orders = []

    def cancel_order(self, order_id: int) -> bool:
        self.cancelled_orders.append(order_id)
        return True
```

**Test:**
```python
assert 101 in broker.cancelled_orders
assert broker.cancel_order.call_count == 2
```

### Pattern 2: Return Values Based on State

```python
class MockBroker:
    def cancel_order(self, order_id: int) -> bool:
        if order_id == 999:
            return False  # Simulate failure
        return True
```

**Test:**
```python
def test_fallback_behavior_on_failure(self):
    group.trailing_order_id = 999
    group.oca_group_id = "oca_123"

    app_state.cancel_all_orders()

    # Should fallback to OCA
    assert "oca_123" in broker.cancelled_oca_groups
```

### Pattern 3: Verify Call Arguments

```python
def test_deactivate_called_with_correct_args(self):
    app_state.cancel_all_orders()

    # Verify exact arguments
    assert (group_id, True) in group_manager._deactivate_calls
    # Specifically: clear_orders=True
```

## Test Organization

### File Structure
```
tests/
├── test_state.py                          # State class tests
├── TEST_COVERAGE_CANCEL_ALL_ORDERS.md     # Coverage documentation
├── STATE_TESTING_BEST_PRACTICES.md        # This file
├── ib/                                    # Broker integration tests
│   ├── test_broker.py
│   └── fixtures/
└── conftest.py                            # Shared pytest config
```

### Test Class Organization
```python
class TestCancelAllOrders:
    """Core functionality tests."""
    # Main tests here

class TestCancelAllOrdersIntegration:
    """Integration with real classes."""
    # Integration tests here

class TestCancelAllOrdersErrorHandling:
    """Error scenarios."""
    # Error tests here (future)
```

## Common Pitfalls & Solutions

### Pitfall 1: Over-Mocking

**Bad:**
```python
# Mocking too much - loses test value
state = MagicMock()
group_manager = MagicMock()
broker = MagicMock()
# Now we're testing nothing about real behavior
```

**Good:**
```python
# Mock only external dependencies, test real logic
MockBroker()      # Track calls but behave like real broker
MockGroupManager  # Simplified but realistic behavior
AppState()        # Real class with mocked dependencies
```

### Pitfall 2: Fragile Tests

**Bad:**
```python
def test_cancel_all_orders(self):
    # Depends on implementation detail (variable names)
    app_state.cancel_all_orders()
    assert app_state._internal_loop_counter == 5  # Bad!
```

**Good:**
```python
def test_cancel_all_orders(self):
    # Depends only on observable behavior
    app_state.cancel_all_orders()
    assert "Cancelled 5 order groups" in app_state.status_message
```

### Pitfall 3: Insufficient Setup

**Bad:**
```python
def test_time_exit_order_cancelled(self):
    # Missing group setup!
    app_state.cancel_all_orders()
    assert 102 in broker.cancelled_orders  # Will fail silently
```

**Good:**
```python
def test_time_exit_order_cancelled(self):
    group = MockGroup(id='g1', trailing_order_id=101, time_exit_order_id=102)
    group_manager.groups['g1'] = group

    app_state.cancel_all_orders()
    assert 102 in broker.cancelled_orders
```

### Pitfall 4: Side Effects in Fixtures

**Bad:**
```python
@pytest.fixture
def app_state(self):
    # Fixture with side effects - violates isolation
    app_state = AppState()
    app_state.cancel_all_orders()  # Side effect!
    return app_state
```

**Good:**
```python
@pytest.fixture
def app_state(self):
    # Pure setup, no side effects
    return AppState()
```

## Test Maintenance

### When to Update Tests

1. **Behavior Changes**: Update assertions if behavior intentionally changes
2. **Bug Fixes**: Add regression test first, then fix
3. **Refactoring**: Update if test implementation details change, NOT if behavior stays same
4. **New Edge Cases**: Add new tests for new edge cases

### When NOT to Update Tests

- Implementation details change (internal algorithm optimization)
- Variable names change
- Function is refactored but behavior stays same

## Performance Considerations

### For Fast Tests
- Use simple mock objects instead of real instances
- Minimize setup/teardown
- Avoid file I/O, network calls, sleep statements

### Benchmark (Expected)
```
Tests should run in < 100ms total
Each test should be < 10ms
```

### Slow Test Detection
```bash
pytest tests/test_state.py -v --durations=10
```

## Continuous Improvement

### Add Tests For:
- Every bug fix (regression test)
- New code paths
- Edge cases discovered in production
- Customer-reported issues

### Review Tests For:
- Clarity of intent
- Completeness of coverage
- Maintenance burden
- Execution speed

## Resources

### Related Documentation
- `docs/reflex/REFLEX_GOTCHAS.md` - Reflex framework issues
- `docs/ib/ib_bible.md` - IB integration details
- `CLAUDE.md` - Project structure and agent assignments

### Testing Tools
- `pytest` - Test framework
- `unittest.mock` - Mocking library
- `pytest-cov` - Coverage reports

## Example: Complete Test Pattern

```python
class TestCompleteExample:
    """Example showing all best practices."""

    @pytest.fixture
    def mocks(self):
        """Setup all mocks."""
        return {
            'broker': MockBroker(),
            'group_manager': MockGroupManager(),
        }

    @pytest.fixture
    def app_state(self, mocks):
        """Create state with mocked dependencies."""
        state = AppState()
        state.broker = mocks['broker']
        state.group_manager = mocks['group_manager']
        return state

    def test_descriptive_name_following_pattern(self, app_state, mocks):
        """Clear description of what scenario is tested.

        GIVEN: Initial conditions
        WHEN: Action performed
        THEN: Expected outcome
        """
        # GIVEN: Group with trailing order
        group = MockGroup(id='g1', trailing_order_id=101, is_active=True)
        mocks['group_manager'].groups['g1'] = group

        # WHEN: Cancellation triggered
        app_state.cancel_all_orders()

        # THEN: Order is cancelled and group deactivated
        assert 101 in mocks['broker'].cancelled_orders
        assert group.is_active == False
        assert "Cancelled 1" in app_state.status_message
```

## Summary Checklist

- [ ] Clear, descriptive test names
- [ ] One focus per test
- [ ] Proper fixture usage
- [ ] Mock only external dependencies
- [ ] Test behavior, not implementation
- [ ] Cover edge cases and boundaries
- [ ] Fast execution (< 10ms per test)
- [ ] No side effects in fixtures
- [ ] Assertions are specific
- [ ] Documentation/comments where needed
