from app.domain.enums import OrderStatus, MovementType


def test_order_status_terminal_states():
    assert OrderStatus.REJECTED in OrderStatus.terminal_states()
    assert OrderStatus.DELIVERED in OrderStatus.terminal_states()
    assert OrderStatus.CANCELLED in OrderStatus.terminal_states()
    assert OrderStatus.PENDING not in OrderStatus.terminal_states()
    assert OrderStatus.CONFIRMED not in OrderStatus.terminal_states()


def test_order_status_stock_holding_states():
    restore = OrderStatus.stock_holding_states()
    assert OrderStatus.CONFIRMED in restore
    assert OrderStatus.SHIPPED in restore
    assert OrderStatus.DELIVERED in restore
    assert OrderStatus.PENDING not in restore
    assert OrderStatus.REJECTED not in restore


def test_movement_type_values():
    assert MovementType.DEDUCTION.value == "DEDUCTION"
    assert MovementType.RESTORATION.value == "RESTORATION"
    assert MovementType.ADJUSTMENT.value == "ADJUSTMENT"


def test_pending_can_confirm():
    assert OrderStatus.PENDING.can_transition_to(OrderStatus.CONFIRMED) is True

def test_pending_can_reject():
    assert OrderStatus.PENDING.can_transition_to(OrderStatus.REJECTED) is True

def test_pending_can_cancel():
    assert OrderStatus.PENDING.can_transition_to(OrderStatus.CANCELLED) is True

def test_pending_cannot_ship():
    assert OrderStatus.PENDING.can_transition_to(OrderStatus.SHIPPED) is False

def test_confirmed_can_ship():
    assert OrderStatus.CONFIRMED.can_transition_to(OrderStatus.SHIPPED) is True

def test_confirmed_can_cancel():
    assert OrderStatus.CONFIRMED.can_transition_to(OrderStatus.CANCELLED) is True

def test_confirmed_cannot_deliver_directly():
    assert OrderStatus.CONFIRMED.can_transition_to(OrderStatus.DELIVERED) is False

def test_shipped_can_deliver():
    assert OrderStatus.SHIPPED.can_transition_to(OrderStatus.DELIVERED) is True

def test_delivered_is_terminal():
    for status in OrderStatus:
        assert OrderStatus.DELIVERED.can_transition_to(status) is False

def test_cancelled_is_terminal():
    for status in OrderStatus:
        assert OrderStatus.CANCELLED.can_transition_to(status) is False

def test_rejected_is_terminal():
    for status in OrderStatus:
        assert OrderStatus.REJECTED.can_transition_to(status) is False
