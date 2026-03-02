class NotFoundError(Exception):
    """Resource does not exist."""
    def __init__(self, resource: str, resource_id: object) -> None:
        self.resource = resource
        self.resource_id = resource_id
        super().__init__(f"{resource} {resource_id} not found")


class InsufficientStockError(Exception):
    """Stock is too low to fulfil the order."""
    def __init__(self, item_id: object, requested: int, available: int) -> None:
        self.item_id = item_id
        self.requested = requested
        self.available = available
        super().__init__(
            f"Insufficient stock for item {item_id}: "
            f"requested {requested}, available {available}"
        )


class InvalidTransitionError(Exception):
    """Order state machine transition is not allowed."""
    def __init__(self, current: str, requested: str) -> None:
        self.current = current
        self.requested = requested
        super().__init__(f"Cannot transition order from {current} to {requested}")


class ConflictError(Exception):
    """Concurrent modification detected (optimistic lock failure)."""
    def __init__(self, resource: str, resource_id: object) -> None:
        self.resource = resource
        self.resource_id = resource_id
        super().__init__(f"Concurrent update conflict on {resource} {resource_id}")
