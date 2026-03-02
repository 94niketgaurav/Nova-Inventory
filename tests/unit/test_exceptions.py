from app.core.exceptions import (
    NotFoundError, InsufficientStockError, InvalidTransitionError, ConflictError
)
import uuid


def test_not_found_error_message():
    item_id = uuid.uuid4()
    err = NotFoundError("MenuItem", item_id)
    assert str(item_id) in str(err)
    assert "MenuItem" in str(err)


def test_insufficient_stock_error():
    item_id = uuid.uuid4()
    err = InsufficientStockError(item_id, requested=10, available=3)
    assert err.requested == 10
    assert err.available == 3


def test_invalid_transition_error():
    err = InvalidTransitionError("DELIVERED", "CONFIRMED")
    assert "DELIVERED" in str(err)


def test_conflict_error():
    order_id = uuid.uuid4()
    err = ConflictError("Order", order_id)
    assert "Order" in str(err)
