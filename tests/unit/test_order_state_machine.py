# Copyright (c) 2026 Nova Inventory Service. All Rights Reserved.
from app.domain.enums import OrderStatus


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

def test_confirmed_cannot_deliver():
    assert OrderStatus.CONFIRMED.can_transition_to(OrderStatus.DELIVERED) is False

def test_shipped_can_deliver():
    assert OrderStatus.SHIPPED.can_transition_to(OrderStatus.DELIVERED) is True

def test_shipped_can_cancel():
    assert OrderStatus.SHIPPED.can_transition_to(OrderStatus.CANCELLED) is True

def test_delivered_is_terminal():
    for status in OrderStatus:
        assert OrderStatus.DELIVERED.can_transition_to(status) is False

def test_cancelled_is_terminal():
    for status in OrderStatus:
        assert OrderStatus.CANCELLED.can_transition_to(status) is False

def test_rejected_is_terminal():
    for status in OrderStatus:
        assert OrderStatus.REJECTED.can_transition_to(status) is False

def test_stock_holding_states_require_restoration():
    holding = OrderStatus.stock_holding_states()
    assert OrderStatus.CONFIRMED in holding
    assert OrderStatus.SHIPPED in holding
    assert OrderStatus.DELIVERED in holding
    assert OrderStatus.PENDING not in holding
    assert OrderStatus.REJECTED not in holding
