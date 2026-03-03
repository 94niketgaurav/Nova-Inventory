# Copyright (c) 2026 Nova Inventory Service. All Rights Reserved.
import enum


class OrderStatus(enum.StrEnum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"

    @classmethod
    def terminal_states(cls) -> frozenset["OrderStatus"]:
        return frozenset({cls.REJECTED, cls.DELIVERED, cls.CANCELLED})

    @classmethod
    def stock_holding_states(cls) -> frozenset["OrderStatus"]:
        """States where stock has been deducted and must be restored on cancel."""
        return frozenset({cls.CONFIRMED, cls.SHIPPED, cls.DELIVERED})

    @classmethod
    def valid_transitions(cls) -> dict["OrderStatus", frozenset["OrderStatus"]]:
        return {
            cls.PENDING: frozenset({cls.CONFIRMED, cls.REJECTED, cls.CANCELLED}),
            cls.CONFIRMED: frozenset({cls.SHIPPED, cls.CANCELLED}),
            cls.SHIPPED: frozenset({cls.DELIVERED, cls.CANCELLED}),
            cls.DELIVERED: frozenset(),
            cls.CANCELLED: frozenset(),
            cls.REJECTED: frozenset(),
        }

    def can_transition_to(self, next_status: "OrderStatus") -> bool:
        return next_status in self.valid_transitions().get(self, frozenset())


class MovementType(enum.StrEnum):
    DEDUCTION = "DEDUCTION"
    RESTORATION = "RESTORATION"
    ADJUSTMENT = "ADJUSTMENT"
