# Nova Inventory Service — Test Cases & Edge Cases

This document maps every automated test to the business rule it validates, including concurrency and edge cases.

---

## Unit Tests (`tests/unit/`)

### Config & Settings (`test_config.py`)
| # | Test | Rule |
|---|---|---|
| U01 | `test_database_url_assembled_from_parts` | `database_url` property builds asyncpg URL from individual env vars |
| U02 | `test_default_values_work_without_env_file` | Server starts with zero configuration |
| U03 | `test_valid_api_keys_parses_comma_separated` | `API_KEYS` is split, stripped, deduplicated |
| U04 | `test_enable_cache_defaults_true` | `ENABLE_CACHE=true` by default |

### Constants (`test_constants.py`)
| # | Test | Rule |
|---|---|---|
| U05 | `test_cache_key_includes_item_id` | Cache keys are namespaced: `nova:stock:{uuid}` |
| U06 | `test_headers_defined` | `X-API-Key`, `X-Request-ID` header names are stable constants |
| U07 | `test_rate_limits_are_strings` | slowapi format: `"N/period"` |

### Enums (`test_enums.py`)
| # | Test | Rule |
|---|---|---|
| U08 | `test_order_status_terminal_states` | REJECTED, DELIVERED, CANCELLED are terminal |
| U09 | `test_order_status_stock_restore_states` | Stock restored only from CONFIRMED, SHIPPED, DELIVERED |
| U10 | `test_movement_type_values` | DEDUCTION, RESTORATION, ADJUSTMENT are the only types |

### Order State Machine (`test_order_state_machine.py`)
| # | Test | Rule |
|---|---|---|
| U11 | `test_pending_can_confirm` | PENDING → CONFIRMED is valid |
| U12 | `test_pending_can_reject` | PENDING → REJECTED is valid |
| U13 | `test_pending_can_cancel` | PENDING → CANCELLED is valid |
| U14 | `test_pending_cannot_ship` | PENDING → SHIPPED is invalid |
| U15 | `test_confirmed_can_ship` | CONFIRMED → SHIPPED is valid |
| U16 | `test_confirmed_can_cancel` | CONFIRMED → CANCELLED is valid (restores stock) |
| U17 | `test_confirmed_cannot_deliver` | CONFIRMED → DELIVERED is invalid (must go via SHIPPED) |
| U18 | `test_shipped_can_deliver` | SHIPPED → DELIVERED is valid |
| U19 | `test_shipped_can_cancel` | SHIPPED → CANCELLED is valid (restores stock) |
| U20 | `test_delivered_is_terminal` | No transitions out of DELIVERED |
| U21 | `test_cancelled_is_terminal` | No transitions out of CANCELLED |
| U22 | `test_rejected_is_terminal` | No transitions out of REJECTED |
| U23 | `test_stock_holding_states_require_restoration` | Only CONFIRMED/SHIPPED/DELIVERED states held stock |

### Domain Models (`test_models.py`)
| # | Test | Rule |
|---|---|---|
| U24 | `test_menu_item_is_low_stock_true` | `stock_quantity <= threshold` → `is_low_stock = True` |
| U25 | `test_menu_item_is_low_stock_false` | `stock_quantity > threshold` → `is_low_stock = False` |
| U26 | `test_menu_item_is_low_stock_at_threshold` | `stock_quantity == threshold` → `is_low_stock = True` (boundary) |

### Schemas (`test_schemas.py`)
| # | Test | Rule |
|---|---|---|
| U27 | `test_item_create_validation` | `ItemCreate` validates price > 0, stock_quantity ≥ 0 |
| U28 | `test_order_create_validation` | `OrderCreate` validates quantity > 0 |
| U29 | `test_stock_response_from_attributes` | `ItemResponse.model_validate` reads ORM `is_low_stock` property |
| U30 | `test_analytics_summary` | Analytics schemas accept correct Decimal types |

### Exceptions (`test_exceptions.py`)
| # | Test | Rule |
|---|---|---|
| U31 | `test_not_found_error_message` | NotFoundError includes resource type and ID |
| U32 | `test_insufficient_stock_error` | InsufficientStockError captures requested vs available |
| U33 | `test_invalid_transition_error` | InvalidTransitionError names the bad transition |
| U34 | `test_conflict_error` | ConflictError identifies the resource in contention |

### Cache (`test_cache.py`)
| # | Test | Rule |
|---|---|---|
| U35 | `test_set_stock_stores_with_ttl` | `set_stock` calls Redis SETEX with TTL |
| U36 | `test_get_stock_returns_int_on_hit` | Cache hit returns `int`, not bytes |
| U37 | `test_get_stock_returns_none_on_miss` | Cache miss returns `None` (caller falls back to DB) |
| U38 | `test_cache_degrades_gracefully_on_read_error` | Redis read error → `None`, no exception raised |
| U39 | `test_cache_degrades_gracefully_on_write_error` | Redis write error → silent, no exception raised |
| U40 | `test_disabled_get_stock_returns_none` | `CacheService(None).get_stock()` → `None` (straight to DB) |
| U41 | `test_disabled_set_stock_is_noop` | `CacheService(None).set_stock()` → silent no-op |
| U42 | `test_disabled_invalidate_is_noop` | `CacheService(None).invalidate_stock()` → silent no-op |

### Auth Middleware (`test_auth_middleware.py`)
| # | Test | Rule |
|---|---|---|
| U43 | `test_auth_disabled_allows_all_requests` | `REQUIRE_AUTH=false` → all requests pass |
| U44 | `test_auth_enabled_rejects_missing_key_on_write` | Missing `X-API-Key` on POST → 401 |
| U45 | `test_auth_enabled_rejects_wrong_key` | Invalid `X-API-Key` → 403 |
| U46 | `test_auth_enabled_accepts_valid_key` | Valid `X-API-Key` → 200 |
| U47 | `test_get_requests_always_public_when_auth_enabled` | GET routes bypass auth even when enabled |

---

## Integration Tests (`tests/integration/`)

### Order Lifecycle (`test_order_lifecycle.py`)
| # | Test | Rule |
|---|---|---|
| I01 | `test_full_happy_path` | PENDING→CONFIRMED→SHIPPED→DELIVERED; stock deducted on confirm |
| I02 | `test_cancel_confirmed_order_restores_stock` | Cancelling CONFIRMED order restores stock exactly |
| I03 | `test_cancel_pending_order_does_not_restore_stock` | Cancelling PENDING order (no deduction) leaves stock unchanged |
| I04 | `test_reject_order_when_insufficient_stock` | Confirm with insufficient stock → 422, order REJECTED, stock unchanged |
| I05 | `test_delivered_order_cannot_be_cancelled` | DELIVERED is terminal → cancel returns 422 |
| I06 | `test_stock_movement_audit_trail` | Audit log has DEDUCTION on confirm, RESTORATION on cancel |

### Concurrent Orders (`test_concurrent_orders.py`)
| # | Test | Rule / Locking Mechanism |
|---|---|---|
| I07 | `test_concurrent_orders_no_oversell` | **SELECT FOR UPDATE** — 10 concurrent confirms against stock=5 → exactly 5 succeed, stock=0, never negative |
| I08 | `test_concurrent_cancellations_no_double_restore` | **Optimistic locking (version field)** — 2 concurrent cancels → exactly 1 succeeds, stock restored once |

### Stock Alerts (`test_stock_alerts.py`)
| # | Test | Rule |
|---|---|---|
| I09 | `test_low_stock_alert_returns_items_below_threshold` | `GET /stock/alerts/low` returns only items with `stock_quantity < threshold` |
| I10 | `test_item_at_threshold_is_included_in_alerts` | Boundary: `stock_quantity == threshold` IS included in alerts |
| I11 | `test_stock_level_endpoint` | `GET /stock/{id}` returns correct `stock_quantity` and `is_low_stock` |
| I12 | `test_manual_stock_adjustment_reflected_in_stock_level` | PATCH stock adjustment appears in stock level AND movement audit |

### Analytics (`test_analytics.py`)
| # | Test | Rule |
|---|---|---|
| I13 | `test_stock_analytics_endpoint` | `/analytics/stock` returns total items, units, value, low/out counts |
| I14 | `test_order_analytics_endpoint` | `/analytics/orders` returns status breakdown and revenue |
| I15 | `test_movement_analytics_endpoint` | `/analytics/movements` shows deductions, restorations, net change |
| I16 | `test_summary_endpoint` | `/analytics/summary` nests stock + orders + movements |

---

## E2E / Edge Case Tests (`tests/e2e/`)

### Input Validation Edge Cases (`test_edge_cases.py`)
| # | Test | Edge Case |
|---|---|---|
| E01 | `test_create_item_zero_price_rejected` | Price = 0 → Pydantic 422 (must be > 0) |
| E02 | `test_create_item_negative_price_rejected` | Negative price → 422 |
| E03 | `test_create_item_negative_stock_rejected` | Negative initial stock → 422 |
| E04 | `test_create_item_empty_name_rejected` | Empty name → 422 |
| E05 | `test_create_item_duplicate_name_rejected` | Duplicate name → 409 (UNIQUE constraint) |
| E06 | `test_place_order_zero_quantity_rejected` | Quantity = 0 → 422 |
| E07 | `test_place_order_negative_quantity_rejected` | Negative quantity → 422 |
| E08 | `test_place_order_nonexistent_item` | Item UUID not in DB → 404 |
| E09 | `test_confirm_nonexistent_order` | Order UUID not in DB → 404 |
| E10 | `test_get_stock_nonexistent_item` | Item UUID not in DB → 404 |
| E11 | `test_adjust_stock_negative_beyond_available` | Delta would make stock negative → 422 |
| E12 | `test_invalid_uuid_in_path` | Non-UUID path param → 422 |

### State Machine Edge Cases (`test_edge_cases.py` cont.)
| # | Test | Edge Case |
|---|---|---|
| E13 | `test_cannot_confirm_already_confirmed_order` | Double-confirm same order → 422 |
| E14 | `test_cannot_ship_pending_order` | PENDING → SHIPPED skips CONFIRMED → 422 |
| E15 | `test_cannot_deliver_pending_order` | PENDING → DELIVERED → 422 |
| E16 | `test_cannot_confirm_cancelled_order` | Terminal state → 422 |
| E17 | `test_cannot_confirm_rejected_order` | Terminal state → 422 |
| E18 | `test_cancel_shipped_order_restores_stock` | SHIPPED → CANCELLED restores stock (stock was held) |

### Stock Boundary Edge Cases
| # | Test | Edge Case |
|---|---|---|
| E19 | `test_order_exactly_equal_to_stock` | Order qty == stock → confirms, stock = 0 |
| E20 | `test_order_one_more_than_stock_rejected` | Order qty == stock + 1 → rejected |
| E21 | `test_zero_stock_item_rejects_any_order` | Item with stock=0 → any order confirm → rejected immediately |
| E22 | `test_sequential_orders_deplete_stock_correctly` | Two orders each qty=3 against stock=5 → first confirms, second rejected |

---

## Locking Mechanism Summary

| Scenario | Mechanism | Location |
|---|---|---|
| Concurrent `confirm_order` | `SELECT FOR UPDATE` on `menu_items` row | `ItemRepository.get_by_id_with_lock()` |
| Concurrent `cancel_order` / state transitions | Optimistic lock on `orders.version` | `OrderRepository.transition_status()` |
| Manual stock adjustment | `SELECT FOR UPDATE` on `menu_items` row | `ItemService.adjust_stock()` |

**Why two strategies?**
- Stock writes need absolute safety (no oversell) → pessimistic lock holds row for duration
- State transitions are low-contention — optimistic locking avoids queue serialization while still detecting races

---

## Running Tests

```bash
# All unit tests (no DB/Redis required)
uv run pytest tests/unit/ -v

# All integration tests (requires local Postgres at localhost/nova_test)
uv run pytest tests/integration/ -v --tb=short

# Edge case tests
uv run pytest tests/e2e/ -v --tb=short

# Critical race condition test (verbose output)
uv run pytest tests/integration/test_concurrent_orders.py -v -s

# Full test suite with coverage
uv run pytest tests/ --cov=app --cov-report=html -v
```

---

## Database Test Isolation

Each integration test runs inside a **rolled-back transaction**: the test gets a real DB connection, all operations are visible within that connection, but nothing is committed — the transaction rolls back after every test. This means:
- Tests are fully isolated from each other
- No cleanup fixtures needed
- DB state is predictable at the start of every test

Concurrent tests (`test_concurrent_orders.py`) use **separate connections** (separate sessions per goroutine) because `SELECT FOR UPDATE` requires separate transactions to demonstrate the locking behaviour.
