# Nova Inventory Service — Test Cases & Edge Cases

This document maps every automated test to the business rule it validates, including concurrency and edge cases.

---

## Unit Tests (`tests/unit/`)

### Config & Settings (`test_config.py`)
| # | Test | Rule |
|---|---|---|
| U01 | `test_settings_has_required_fields` | Settings exposes `database_url`, `environment`, `log_level` |
| U02 | `test_environment_default` | `environment` is one of `development / production / test` |
| U03 | `test_database_url_built_from_parts` | `database_url` contains `asyncpg`, the configured host, and DB name |
| U04 | `test_local_defaults_are_set` | Default host = `localhost`, port = `5432`, name = `nova_inventory` |
| U05 | `test_redis_url_has_default` | `redis_url` starts with `redis://` |
| U06 | `test_auth_disabled_by_default` | `require_auth` defaults to `False` |
| U07 | `test_valid_api_keys_parsing` | `API_KEYS` is split, stripped, and stored as a frozenset |
| U08 | `test_empty_api_keys_returns_empty_frozenset` | Empty `API_KEYS` string → empty frozenset (no crash) |

### Constants (`test_constants.py`)
| # | Test | Rule |
|---|---|---|
| U09 | `test_stock_cache_key_format` | Cache keys are namespaced: `nova:stock:{uuid}` |
| U10 | `test_stock_cache_key_is_consistent` | Same `item_id` always produces the same cache key |
| U11 | `test_different_items_have_different_keys` | Different `item_id` values produce different cache keys |
| U12 | `test_headers_defined` | `X-API-Key`, `X-Request-ID` header names are stable constants |
| U13 | `test_rate_limits_are_slowapi_format` | Rate limit strings follow slowapi `"N/period"` format |
| U14 | `test_log_fields_are_strings` | All `LogFields` constants are plain strings |

### Enums (`test_enums.py`)
| # | Test | Rule |
|---|---|---|
| U15 | `test_order_status_terminal_states` | REJECTED, DELIVERED, CANCELLED are terminal (no further transitions) |
| U16 | `test_order_status_stock_holding_states` | Stock was deducted in CONFIRMED, SHIPPED, DELIVERED states |
| U17 | `test_movement_type_values` | Only DEDUCTION, RESTORATION, ADJUSTMENT exist |
| U18–U31 | _(state-machine transitions — duplicated in `test_order_state_machine.py`)_ | see below |

### Order State Machine (`test_order_state_machine.py`)
| # | Test | Rule |
|---|---|---|
| U18 | `test_pending_can_confirm` | PENDING → CONFIRMED is valid |
| U19 | `test_pending_can_reject` | PENDING → REJECTED is valid |
| U20 | `test_pending_can_cancel` | PENDING → CANCELLED is valid |
| U21 | `test_pending_cannot_ship` | PENDING → SHIPPED is invalid |
| U22 | `test_confirmed_can_ship` | CONFIRMED → SHIPPED is valid |
| U23 | `test_confirmed_can_cancel` | CONFIRMED → CANCELLED is valid (restores stock) |
| U24 | `test_confirmed_cannot_deliver` | CONFIRMED → DELIVERED is invalid (must go via SHIPPED) |
| U25 | `test_shipped_can_deliver` | SHIPPED → DELIVERED is valid |
| U26 | `test_shipped_can_cancel` | SHIPPED → CANCELLED is valid (restores stock) |
| U27 | `test_delivered_is_terminal` | No transitions out of DELIVERED |
| U28 | `test_cancelled_is_terminal` | No transitions out of CANCELLED |
| U29 | `test_rejected_is_terminal` | No transitions out of REJECTED |
| U30 | `test_stock_holding_states_require_restoration` | CONFIRMED/SHIPPED/DELIVERED states held stock at time of cancel |

### Domain Models (`test_models.py`)
| # | Test | Rule |
|---|---|---|
| U31 | `test_menu_item_is_low_stock_true` | `stock_quantity < threshold` → `is_low_stock = True` |
| U32 | `test_menu_item_is_low_stock_false` | `stock_quantity > threshold` → `is_low_stock = False` |
| U33 | `test_menu_item_is_low_stock_at_threshold` | `stock_quantity == threshold` → `is_low_stock = True` (boundary) |
| U34 | `test_order_status_is_str_enum` | `OrderStatus` values are strings — e.g. `OrderStatus.PENDING == "PENDING"` |
| U35 | `test_menu_item_has_version_default` | New `MenuItem` starts with `version = 1` |

### Schemas (`test_schemas.py`)
| # | Test | Rule |
|---|---|---|
| U36 | `test_item_create_validation` | `ItemCreate` validates price > 0, stock_quantity ≥ 0 |
| U37 | `test_order_create_validation` | `OrderCreate` validates quantity > 0 |
| U38 | `test_stock_response_from_attributes` | `ItemResponse.model_validate` reads ORM `is_low_stock` property |
| U39 | `test_analytics_summary` | Analytics schemas accept correct Decimal types |

### Exceptions (`test_exceptions.py`)
| # | Test | Rule |
|---|---|---|
| U40 | `test_not_found_error_message` | NotFoundError includes resource type and ID |
| U41 | `test_insufficient_stock_error` | InsufficientStockError captures requested vs available |
| U42 | `test_invalid_transition_error` | InvalidTransitionError names the bad transition |
| U43 | `test_conflict_error` | ConflictError identifies the resource in contention |

### Cache (`test_cache.py`)
| # | Test | Rule |
|---|---|---|
| U44 | `test_set_stock_stores_with_ttl` | `set_stock` calls Redis SETEX with TTL |
| U45 | `test_get_stock_returns_int_on_hit` | Cache hit returns `int`, not bytes |
| U46 | `test_get_stock_returns_none_on_miss` | Cache miss returns `None` (caller falls back to DB) |
| U47 | `test_cache_degrades_gracefully_on_read_error` | Redis read error → `None`, no exception raised |
| U48 | `test_cache_degrades_gracefully_on_write_error` | Redis write error → silent, no exception raised |
| U49 | `test_disabled_get_stock_returns_none` | `CacheService(None).get_stock()` → `None` (straight to DB) |
| U50 | `test_disabled_set_stock_is_noop` | `CacheService(None).set_stock()` → silent no-op |
| U51 | `test_disabled_invalidate_is_noop` | `CacheService(None).invalidate_stock()` → silent no-op |

### Auth Middleware (`test_auth_middleware.py`)
| # | Test | Rule |
|---|---|---|
| U52 | `test_auth_disabled_allows_all_requests` | `REQUIRE_AUTH=false` → all requests pass |
| U53 | `test_auth_enabled_rejects_missing_key_on_write` | Missing `X-API-Key` on POST → 401 |
| U54 | `test_auth_enabled_rejects_wrong_key` | Invalid `X-API-Key` → 403 |
| U55 | `test_auth_enabled_accepts_valid_key` | Valid `X-API-Key` → 200 |
| U56 | `test_get_requests_always_public_when_auth_enabled` | GET routes bypass auth even when auth is enabled |

---

## Integration Tests (`tests/integration/`)

### Order Lifecycle (`test_order_lifecycle.py`)
| # | Test | Rule |
|---|---|---|
| I01 | `test_full_happy_path` | PENDING→CONFIRMED→SHIPPED→DELIVERED; stock deducted on confirm |
| I02 | `test_cancel_confirmed_order_restores_stock` | Cancelling CONFIRMED order restores stock exactly |
| I03 | `test_cancel_pending_order_does_not_restore_stock` | Cancelling PENDING order (no deduction) leaves stock unchanged |
| I04 | `test_reject_order_when_insufficient_stock` | Confirm with insufficient stock → 422, stock unchanged |
| I05 | `test_delivered_order_cannot_be_cancelled` | DELIVERED is terminal → cancel returns 422 |
| I06 | `test_stock_movement_audit_trail` | Audit log has DEDUCTION on confirm, RESTORATION on cancel |
| I07 | `test_rejected_order_status_is_persisted` | After insufficient-stock 422, order status = **REJECTED** not PENDING — verifies `get_db()` commits on HTTPException |
| I08 | `test_cancel_shipped_order_creates_restoration_movement` | Cancelling a SHIPPED order creates a RESTORATION movement with correct `quantity_delta` and `stock_after` |

### Concurrent Orders (`test_concurrent_orders.py`)
| # | Test | Rule / Locking Mechanism |
|---|---|---|
| I09 | `test_concurrent_orders_no_oversell` | **SELECT FOR UPDATE** — 10 concurrent confirms against stock=5 → exactly 5 succeed, stock=0, never negative |
| I10 | `test_concurrent_cancellations_no_double_restore` | **Optimistic locking (version field)** — 2 concurrent cancels → exactly 1 succeeds, stock restored once |

### Stock Alerts (`test_stock_alerts.py`)
| # | Test | Rule |
|---|---|---|
| I11 | `test_low_stock_alert_returns_items_below_threshold` | `GET /stock/alerts/low` returns only items with `stock_quantity ≤ threshold` |
| I12 | `test_item_at_threshold_is_included_in_alerts` | Boundary: `stock_quantity == threshold` IS included in alerts |
| I13 | `test_stock_level_endpoint` | `GET /stock/{id}` returns correct `stock_quantity` and `is_low_stock` |
| I14 | `test_manual_stock_adjustment_reflected_in_stock_level` | PATCH stock adjustment appears in stock level AND movement audit |

### Analytics (`test_analytics.py`)
| # | Test | Rule |
|---|---|---|
| I15 | `test_stock_analytics_endpoint` | `/analytics/stock` returns total items, units, value, low/out counts |
| I16 | `test_order_analytics_endpoint` | `/analytics/orders` returns status breakdown and revenue |
| I17 | `test_movement_analytics_endpoint` | `/analytics/movements` shows deductions, restorations, net change |
| I18 | `test_summary_endpoint` | `/analytics/summary` nests stock + orders + movements |

---

## E2E / Edge Case Tests (`tests/e2e/`)

### Input Validation (`test_edge_cases.py`)
| # | Test | Edge Case |
|---|---|---|
| E01 | `test_create_item_zero_price_rejected` | Price = 0 → 422 (must be > 0) |
| E02 | `test_create_item_negative_price_rejected` | Negative price → 422 |
| E03 | `test_create_item_negative_stock_rejected` | Negative initial stock → 422 |
| E04 | `test_create_item_empty_name_rejected` | Empty name → 422 |
| E05 | `test_create_item_duplicate_name_rejected` | Duplicate name → 409/422/500 (UNIQUE constraint) |
| E06 | `test_place_order_zero_quantity_rejected` | Quantity = 0 → 422 |
| E07 | `test_place_order_negative_quantity_rejected` | Negative quantity → 422 |
| E08 | `test_place_order_nonexistent_item` | Item UUID not in DB → 404 |
| E09 | `test_confirm_nonexistent_order` | Order UUID not in DB → 404 |
| E10 | `test_get_stock_nonexistent_item` | Item UUID not in DB → 404 |
| E11 | `test_adjust_stock_negative_beyond_available` | Delta would make stock negative → 422 |
| E12 | `test_invalid_uuid_in_path` | Non-UUID path param → 422 |

### State Machine Edge Cases
| # | Test | Edge Case |
|---|---|---|
| E13 | `test_cannot_confirm_already_confirmed_order` | Double-confirm same order → 422 |
| E14 | `test_cannot_ship_pending_order` | PENDING → SHIPPED skips CONFIRMED → 422 |
| E15 | `test_cannot_deliver_pending_order` | PENDING → DELIVERED → 422 |
| E16 | `test_cannot_confirm_cancelled_order` | Terminal state → 422 |
| E17 | `test_cannot_confirm_rejected_order` | Terminal state → 422 |
| E18 | `test_cancel_shipped_order_restores_stock` | SHIPPED → CANCELLED restores stock to pre-confirm level |

### Stock Boundary Cases
| # | Test | Edge Case |
|---|---|---|
| E19 | `test_order_exactly_equal_to_stock` | Order qty == stock → confirms, stock = 0 |
| E20 | `test_order_one_more_than_stock_rejected` | Order qty == stock + 1 → rejected, stock unchanged |
| E21 | `test_zero_stock_item_rejects_any_order` | Item with stock=0 → any order confirm → rejected |
| E22 | `test_sequential_orders_deplete_stock_correctly` | Two orders each qty=3 against stock=5 → first confirms, second rejected |

### List Orders Endpoint (`GET /api/v1/orders`)
| # | Test | Edge Case |
|---|---|---|
| E23 | `test_list_orders_no_filter_returns_all` | No query params → response includes all orders created in this test |
| E24 | `test_list_orders_filter_by_status` | `?status=CONFIRMED` returns only confirmed orders; confirmed/pending in correct buckets |
| E25 | `test_list_orders_filter_by_customer_ref` | `?customer_ref=X` returns exactly the orders for that customer (UUID-unique per run) |
| E26 | `test_list_orders_empty_result_returns_empty_list` | Non-existent `customer_ref` → `[]` not 404 |
| E27 | `test_list_orders_combined_filters` | `?status=PENDING&customer_ref=X` narrows to single matching order |

### Order Detail Endpoint (`GET /api/v1/orders/{id}`)
| # | Test | Edge Case |
|---|---|---|
| E28 | `test_get_order_detail_includes_item_info` | Response has `item_name`, `item_price`, `total_value = price × qty` |
| E29 | `test_get_order_detail_movements_populated_after_confirm` | After confirm: `movements[]` has exactly 1 DEDUCTION entry |
| E30 | `test_get_order_detail_movements_after_cancel` | After confirm + cancel: `movements[]` has both DEDUCTION and RESTORATION |
| E31 | `test_get_order_detail_pending_has_no_movements` | Newly placed (PENDING) order has `movements = []` |

---

## Locking Mechanism Summary

| Scenario | Mechanism | Location |
|---|---|---|
| Concurrent `confirm_order` | `SELECT FOR UPDATE` on `menu_items` row | `ItemRepository.get_by_id_with_lock()` |
| Concurrent `cancel_order` / state transitions | Optimistic lock on `orders.version` | `OrderRepository.transition_status()` |
| Manual stock adjustment | `SELECT FOR UPDATE` on `menu_items` row | `ItemService.adjust_stock()` |

**Why two strategies?**
- Stock writes need absolute safety (no oversell) → pessimistic lock holds row for duration
- State transitions are low-contention — optimistic locking avoids queue serialisation while still detecting races

### `version` field on MenuItem vs Order

| Field | Pattern | Mechanism |
|---|---|---|
| `Order.version` | **Optimistic lock** | `UPDATE orders WHERE version = :expected` — 0 rows updated = concurrent conflict → `ConflictError` |
| `MenuItem.version` | **Mutation counter** | Incremented by `+1` on every stock change (confirm, cancel, adjust); actual concurrency safety comes from `SELECT FOR UPDATE` |

---

## Running Tests

```bash
# All unit tests (no DB/Redis required)
uv run pytest tests/unit/ -v

# Integration tests (requires local Postgres at localhost/nova_test)
uv run pytest tests/integration/ -v --tb=short

# Edge case / E2E tests
uv run pytest tests/e2e/ -v --tb=short

# Critical race condition tests
uv run pytest tests/integration/test_concurrent_orders.py -v -s

# Full suite with coverage
uv run pytest tests/ --cov=app --cov-report=html -v
```

---

## Database Test Isolation

**`db_session` fixture** (used by all E2E and most integration tests): each test gets a real DB connection with an open transaction that is **rolled back** after the test. No cleanup needed; state is clean at the start of every test.

**`db_engine` fixture** (used by concurrent tests only): creates separate sessions per goroutine so `SELECT FOR UPDATE` can demonstrate cross-transaction locking. Tables are **truncated** at fixture start to guarantee a clean slate, because concurrent tests commit real rows.

> Note: `db_session` tests run with READ COMMITTED isolation, so they can see rows committed by `db_engine` tests in previous runs. List-endpoint tests use UUID-unique `customer_ref` values to avoid count mismatches from pre-existing rows.
