from app.domain.models.item import MenuItem
from app.domain.enums import OrderStatus


def test_menu_item_is_low_stock_true():
    item = MenuItem(name="Burger", price=10.0, stock_quantity=5, low_stock_threshold=10)
    assert item.is_low_stock is True


def test_menu_item_is_low_stock_false():
    item = MenuItem(name="Burger", price=10.0, stock_quantity=15, low_stock_threshold=10)
    assert item.is_low_stock is False


def test_menu_item_is_low_stock_at_threshold():
    """At the threshold itself counts as low stock."""
    item = MenuItem(name="Burger", price=10.0, stock_quantity=10, low_stock_threshold=10)
    assert item.is_low_stock is True


def test_order_status_is_str_enum():
    assert isinstance(OrderStatus.PENDING, str)
    assert OrderStatus.PENDING == "PENDING"


def test_menu_item_has_version_default():
    item = MenuItem(name="X", price=5.0, stock_quantity=0)
    assert item.version == 1
