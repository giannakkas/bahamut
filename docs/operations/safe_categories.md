# safe_execute Categories

Listed in order of alert importance.

## CRITICAL (alerts on failure)
- `order_manager_transition` — OrderManager state machine writes
- `risk_budget` — cross-worker risk budget claims/releases

## TRACKED (counted, logged, no alert)
- `telegram_*` — all Telegram sends
- `ws_publish_*` — all WebSocket publishes
- `cache_invalidate` — risk engine cache invalidation
- `cache_invalidate_platform` — per-platform cache invalidation
- `redis_counter` — counter increments
- `rejection_tracker` — rejection tracker writes
- `order_manager_read` — OrderManager reads
- `broker_poll` — position/order status polls

## MIGRATION STATUS
- Framework: `backend/bahamut/shared/safe.py` — complete
- Daily report: `backend/bahamut/monitoring/safe_report.py` — complete (8am UTC via Celery Beat)
- `trading/engine.py` — 2 of ~66 sites migrated (cache_invalidate pattern)
- `trading/orchestrator.py` — 0 of ~31 sites migrated
- `trading/router.py` — 0 of ~91 sites migrated
- `execution/*` — 0 sites migrated
- Remaining sites: ~495 — to be migrated in future batches

## NOTES
- New code should use `safe_execute` or `safe_call` decorator from `bahamut.shared.safe`
- Existing `try: ... except Exception: pass` blocks are functional but invisible
- Migration priority: order_manager > rejection_tracker > telegram > cache > redis_counter
