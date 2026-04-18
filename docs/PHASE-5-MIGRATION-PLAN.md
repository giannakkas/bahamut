# Phase 5 — Four-Engine Consolidation: Migration Plan

**Author:** Bahamut audit process
**Date:** 2026-04-18
**Status:** DRAFT — awaiting human review before implementation
**Prerequisite:** Phase 4 (schema discipline) stable for ≥ 2 weeks

---

## 1. Current State Inventory

Bahamut has four parallel execution engines with different schemas, different thresholds, different exit logic, and different frontend consumers. No single view of "what am I trading and what is my exposure" exists.

### Engine 1 — Training Engine (PRIMARY)

**Code:** `backend/bahamut/training/engine.py`
**Tables:**
- `training_positions` — open positions (Postgres + Redis hot-cache via `hset`/`hgetall`)
- `training_trades` — closed trades (Postgres)
- `order_intents` / `order_events` — used as idempotency gate and state machine (Postgres)

**Authoritative for:** All 50-asset universe, Binance Futures + Alpaca Paper, SL/TP/TIMEOUT exits, risk sizing, sentiment/news gating, all three strategies (v5_base, v9_breakout, v10_mean_reversion).

**Writers:**
- `training/engine.py` → `_save_position()`, `_remove_position()`, `_persist_trade()`
- `training/orchestrator.py` → `run_training_cycle()` drives the full loop
- `execution/order_manager.py` → `create_intent()`, `record_fill()`, `transition()`

**Readers (backend):**
- `training/router.py` → `/api/v1/training/operations` (positions, trades, diagnostics)
- `training/router.py` → `/api/v1/training/execution-decisions`, `/adaptive`, `/candidates`
- `monitoring/dashboard_api.py` → `/api/v1/monitoring/dashboard` (positions, trades, health for v7-ops)
- `execution/router.py` → `get_execution_status()` (training_positions section)
- `execution/reconciliation.py` → `_load_positions()` for broker reconciliation
- `monitoring/performance.py` → win rate, Sharpe, drawdown calculations

**Readers (frontend):**
- `v7-operations/page.tsx` — headline dashboard (positions table, recent trades, PnL, kill switch)
- `training-operations/page.tsx` — detailed training dashboard (all positions, execution decisions, adaptive state, diagnostics)
- `trade-journal/page.tsx` — closed trade journal (reads paper_positions but also shows training context)

**Config:** `MAX_OPEN_POSITIONS=10` (set at boot in `main.py`), pct-based SL/TP, 30-bar timeout default.

---

### Engine 2 — Paper Trading Engine

**Code:** `backend/bahamut/paper_trading/engine.py` + `paper_trading/sync_executor.py`
**Tables:**
- `paper_portfolios` — portfolio-level equity, PnL, trade counts
- `paper_positions` — individual positions with ATR-based SL/TP

**Authoritative for:** Consumer-facing paper trading experience. Driven by consensus/agent-vote signals, not the training orchestrator.

**Writers:**
- `paper_trading/engine.py` → `open_position()`, `close_position()`, `update_portfolio()`
- `paper_trading/sync_executor.py` → `execute_reallocation()` (closes paper positions to make room for broker-backed trades)
- `paper_trading/tasks.py` → Celery tasks for position monitoring, SL/TP checks

**Readers (backend):**
- `paper_trading/router.py` → `/api/v1/paper-trading/portfolio`, `/positions`, `/leaderboard`, `/stats`
- `monitoring/dashboard_api.py` → paper position counts for main dashboard
- `admin/router.py` → admin overview (paper portfolio balance, open count)
- `consensus/system_confidence.py` → paper position PnL for system confidence scoring
- `learning/calibration.py` → paper trade outcomes for calibration
- `ingestion/market_data.py` → assets with open paper positions for data fetching

**Readers (frontend):**
- `paper-trading/page.tsx` — portfolio overview, open/closed positions, leaderboard, learning log
- `dashboard/page.tsx` — summary widget showing recent paper positions
- `trade-journal/page.tsx` — closed paper trades

**Config:** `MAX_OPEN_POSITIONS=5`, ATR-multiplier SL/TP, 48-hour hold limit.

---

### Engine 3 — Legacy Execution Engine (IN-MEMORY)

**Code:** `backend/bahamut/execution/engine.py`
**Tables:** None — pure in-memory `open_positions[]` and `closed_trades[]` lists on a singleton.

**Authoritative for:** Nothing meaningful in current production. Legacy v5/v9 signal submission path via `v7_orchestrator.py`.

**Writers:**
- `execution/engine.py` → `submit_signal()`, `_check_exits()`
- `execution/v7_orchestrator.py` → `process_signal()` calls engine

**Readers (backend):**
- `execution/v7_router.py` → `/api/v1/v7/execution/open-positions`, `/closed-trades`, `/orders`, `/stats`
- `execution/v7_router.py` → `/api/v1/v7/portfolio/kill-switch`, `/resume`

**Readers (frontend):**
- None directly (v7-operations reads from monitoring/dashboard which reads training engine, not this)

**Config:** `MAX_OPEN_POSITIONS=10`, separate kill switch (`ExecutionEngine._kill_switch`).

**Status:** Effectively dead code. The training engine + orchestrator took over signal generation and execution. The v7_router endpoints still return data from this engine but nothing writes to it in the current training-cycle flow.

---

### Engine 4 — Order Manager (STATE MACHINE)

**Code:** `backend/bahamut/execution/order_manager.py`
**Tables:**
- `order_intents` — order lifecycle state machine (INTENT_CREATED → SUBMITTED → FILLED → CLOSED)
- `order_events` — audit trail of state transitions

**Authoritative for:** Idempotency (signal_id UNIQUE constraint), order lifecycle state. After Phase 2 patches, now wired into the open/close paths of Engine 1.

**Writers:**
- `execution/order_manager.py` → `create_intent()`, `record_fill()`, `record_close()`, `transition()`
- `training/engine.py` → calls the above after exec_open/exec_close (Phase 2 wiring)

**Readers (backend):**
- `execution/reconciliation.py` → `get_open_intents()` for orphan/missing detection
- `execution/shutdown.py` → queries for positions in flight during SIGTERM

**Readers (frontend):**
- None directly.

**Status:** Serves as the idempotency and audit layer for Engine 1. Not a standalone engine — it's a supporting subsystem.

---

### Summary of Divergences

| Property | Training (E1) | Paper (E2) | Legacy (E3) | OrderMgr (E4) |
|---|---|---|---|---|
| Persistence | Postgres + Redis | Postgres | In-memory | Postgres |
| SL/TP model | pct-based | ATR-multiplier | pct-based | N/A (stores targets) |
| MAX_POSITIONS | 10 | 5 | 10 | N/A |
| Exit logic | candle-based + broker | candle-based (paper only) | candle-based | N/A |
| Broker integration | Binance Futures + Alpaca | None (paper broker) | None | Stores broker_order_id |
| Signal source | Training orchestrator | Consensus/agent vote | v7_orchestrator | Receives from E1 |
| State machine | No (ad-hoc status field) | No | No | Yes (12-state) |
| Reconciliation | Yes (Phase 2) | No | No | Supports E1 reconciliation |

---

## 2. Target State

A **single execution service** with one unified schema, one set of endpoints, and one source of truth for every position and trade.

### Unified Schema

```
┌─────────────────────┐
│ unified_orders      │  ← replaces order_intents + v7_orders
│   id, signal_id,    │
│   asset, direction, │
│   strategy, mode,   │  ← mode: live_broker | paper_broker | backtest
│   state, ...        │
├─────────────────────┤
│ unified_fills       │  ← new: broker fill records
│   order_id,         │
│   fill_price, qty,  │
│   commission, ...   │
├─────────────────────┤
│ unified_positions   │  ← replaces training_positions + paper_positions
│   order_id, asset,  │
│   entry_price, sl,  │
│   tp, size, mode,   │
│   status, ...       │
├─────────────────────┤
│ unified_trades      │  ← replaces training_trades + paper closed positions
│   position_id,      │
│   entry/exit price, │
│   pnl, exit_reason, │
│   mode, ...         │
├─────────────────────┤
│ unified_events      │  ← replaces order_events
│   order_id,         │
│   event_type,       │
│   from/to state,    │
│   broker_response   │
└─────────────────────┘
```

### Mode Parameter

Every row carries a `mode` column:

- **`live_broker`** — real broker orders (Binance Futures, Alpaca). Broker is source of truth. Reconciliation active.
- **`paper_broker`** — simulated fills using paper broker. No real money. Candle-derived PnL acceptable.
- **`backtest`** — historical replay. Stored for analysis only.

### Single Endpoint Surface

```
GET  /api/v1/execution/positions?mode=live_broker      ← all open positions
GET  /api/v1/execution/positions?mode=paper_broker
GET  /api/v1/execution/trades?mode=live_broker&limit=50 ← closed trades
GET  /api/v1/execution/trades?mode=paper_broker
GET  /api/v1/execution/orders?status=open               ← order lifecycle
GET  /api/v1/execution/stats?mode=live_broker            ← win rate, PnL, etc.
POST /api/v1/execution/kill-switch
POST /api/v1/execution/resume
```

### Frontend

Every dashboard tab reads from the same `/api/v1/execution/*` endpoints with a `mode` query parameter. No more tab-specific backends.

---

## 3. Migration Path — 10 Independent PRs

### PR A — Unified schema (Alembic migration, keep old tables)

**What:** Add `unified_orders`, `unified_fills`, `unified_positions`, `unified_trades`, `unified_events` tables via Alembic migration. Old tables remain untouched and fully operational.

**Files:** `backend/alembic/versions/003_unified_schema.py`

**Rollback:** `alembic downgrade -1` drops the new tables. Zero impact on running system since nothing reads them yet.

**Risk:** Low. Additive-only schema change.

---

### PR B — Dual-write in training engine

**What:** After every `_save_position()`, `_remove_position()`, `_persist_trade()` in `training/engine.py`, also write to the corresponding `unified_*` table. Wrapped in try/except so failures don't block the primary path.

**Files:** `backend/bahamut/training/engine.py` (add `_dual_write_position()`, `_dual_write_trade()`)

**Rollback:** Remove the dual-write calls. Old tables are still the source of truth — no data loss.

**Risk:** Medium. Performance impact of double-writes. Mitigated by: async/fire-and-forget for non-critical path, or batch INSERT after cycle completes.

---

### PR C — v7-operations reads from unified tables

**What:** Switch `monitoring/dashboard_api.py` → `dashboard_all()` to query `unified_positions` and `unified_trades` instead of `training_positions` / `training_trades`. Add a feature flag (`UNIFIED_DASHBOARD=true`) to toggle between old and new reads.

**Files:**
- `backend/bahamut/monitoring/dashboard_api.py`
- `admin-panel/app/(admin)/v7-operations/page.tsx` (if response shape changes)

**Rollback:** Set `UNIFIED_DASHBOARD=false`. Dashboard reverts to old tables instantly.

**Risk:** Medium. If dual-write has gaps, dashboard shows stale/missing data. Mitigated by feature flag + parity checking.

---

### PR D — Data parity validation (1 week soak)

**What:** Add a Celery Beat task `validate_data_parity()` that runs every cycle and compares:
- `SELECT COUNT(*) FROM training_positions WHERE status='OPEN'` vs `unified_positions WHERE status='OPEN' AND mode='live_broker'`
- `SELECT COUNT(*) FROM training_trades WHERE created_at > NOW() - INTERVAL '24h'` vs equivalent unified query
- Row-level hash comparison on position_id/trade_id

Log discrepancies. Telegram alert if count differs by > 0.

**Files:** `backend/bahamut/monitoring/parity_check.py`, `backend/bahamut/celery_app.py` (add beat task)

**Rollback:** Remove the beat task. No production impact — it's read-only.

**Risk:** Low. Pure validation.

**Exit criterion:** 7 consecutive days with zero discrepancies.

---

### PR E — Paper trading reads from unified tables

**What:** Switch `paper_trading/router.py` endpoints to query `unified_positions` / `unified_trades` with `mode='paper_broker'`. Add dual-write to `paper_trading/engine.py`.

**Files:**
- `backend/bahamut/paper_trading/engine.py` (dual-write)
- `backend/bahamut/paper_trading/router.py` (read switch)
- `admin-panel/app/(admin)/paper-trading/page.tsx` (if response shape changes)

**Rollback:** Revert router reads to old tables. Dual-write removal is safe since old tables are still authoritative.

**Risk:** Medium. Paper trading is consumer-facing. Feature flag recommended.

---

### PR F — Drop old-table writes from training engine

**What:** Remove `_save_position()`, `_persist_trade()` writes to `training_positions` / `training_trades`. The `unified_*` tables become the sole write target. Keep old tables populated via a one-way sync job for 1 week as safety net.

**Files:**
- `backend/bahamut/training/engine.py` (remove old writes)
- `backend/bahamut/monitoring/parity_check.py` (reverse: sync unified → old for safety)

**Rollback:** Re-enable old-table writes from the previous commit.

**Risk:** High. This is the point of no return for Engine 1. Must have 7+ days of parity validation (PR D) clean before proceeding.

---

### PR G — Remove paper_trading engine + sync_executor

**What:** Delete `paper_trading/engine.py` and `paper_trading/sync_executor.py`. Move any remaining paper-trading-specific logic (portfolio reset, leaderboard) into the unified execution service. Update `paper_trading/tasks.py` to use unified tables.

**Files:**
- Delete: `backend/bahamut/paper_trading/engine.py`, `backend/bahamut/paper_trading/sync_executor.py`
- Modify: `backend/bahamut/paper_trading/router.py`, `backend/bahamut/paper_trading/tasks.py`

**Rollback:** `git revert`. Old tables still have data. Re-import `engine.py` from git history.

**Risk:** Medium. Paper trading tasks and consensus integration must be verified.

---

### PR H — Archive old tables

**What:** Rename old tables:
- `training_positions` → `_archive_training_positions`
- `training_trades` → `_archive_training_trades`
- `paper_portfolios` → `_archive_paper_portfolios`
- `paper_positions` → `_archive_paper_positions`

Via Alembic migration. Schedule a follow-up PR to drop `_archive_*` after 30 days.

**Files:** `backend/alembic/versions/004_archive_old_tables.py`

**Rollback:** `alembic downgrade -1` renames them back.

**Risk:** Low (just renames). Any code still referencing old table names will fail loudly.

---

### PR I — Remove legacy execution engine + finalize endpoints

**What:**
- Delete `execution/engine.py` (in-memory singleton)
- Delete or gut `execution/v7_orchestrator.py`
- Update `execution/v7_router.py` to read from unified tables (or deprecate entirely in favor of `/api/v1/execution/*`)
- Remove `binance-trades` and `alpaca-trades` frontend pages (data now in unified trades with platform filter)
- Deprecate `/api/v1/v7/*` endpoints with 301 redirects to `/api/v1/execution/*`

**Files:**
- Delete: `backend/bahamut/execution/engine.py`, `backend/bahamut/execution/v7_orchestrator.py`
- Modify: `backend/bahamut/execution/v7_router.py`, `backend/bahamut/main.py` (route mounting)
- Delete: `admin-panel/app/(admin)/binance-trades/`, `admin-panel/app/(admin)/alpaca-trades/`

**Rollback:** `git revert`. v7_router was already a dead-data path; removing it has no production consequence.

**Risk:** Low. Engine 3 is already dead code.

---

### PR J — Documentation + runbook updates

**What:**
- Update `docs/operations/runbook.md` with new table names, new endpoints, new reconciliation flow
- Update `README.md` architecture section
- Add `docs/UNIFIED-SCHEMA.md` describing the new schema, mode parameter, and query patterns
- Update `docs/AUDIT-2026-04-17.md` §2.3 to mark engine consolidation as COMPLETE
- Add admin panel navigation cleanup (remove dead tabs)

**Files:** `docs/`, `admin-panel/`

**Rollback:** N/A (documentation only).

**Risk:** None.

---

## 4. Rollback Plan per PR

| PR | Rollback Method | Data Impact | Time to Rollback |
|---|---|---|---|
| A | `alembic downgrade -1` | None (additive) | 1 min |
| B | Remove dual-write calls, deploy | None (old tables still authoritative) | 5 min |
| C | Set `UNIFIED_DASHBOARD=false` | None | 1 min (env var) |
| D | Remove parity task from beat schedule | None (read-only) | 2 min |
| E | Revert router reads + remove dual-write | None | 5 min |
| F | Re-enable old-table writes from git history | Data gap during rollback window — resync from unified | 15 min |
| G | `git revert` + redeploy | Paper engine state restorable from unified tables | 10 min |
| H | `alembic downgrade -1` (renames back) | None | 1 min |
| I | `git revert` + redeploy | None (dead code) | 5 min |
| J | N/A | N/A | N/A |

**PR F is the highest-risk rollback.** If rolled back, the gap between "old writes stopped" and "old writes restarted" means the old tables are missing trades. Recovery: backfill from unified tables with `INSERT INTO training_trades SELECT ... FROM unified_trades WHERE created_at > :gap_start`.

---

## 5. Specific Risks

### 5.1 Data loss during dual-write (PRs B, E, F)

**Risk:** If the dual-write to unified tables fails silently, the new tables have gaps. When PR F removes old-table writes, those gaps become permanent.

**Mitigation:**
- Dual-write failures must log at ERROR level, not be swallowed.
- PR D's parity checker catches gaps before PR F is attempted.
- PR F includes a one-way sync job as a safety net for 1 week.

### 5.2 Frontend regressions (PRs C, E, I)

**Risk:** Response shape changes between old and new endpoints break frontend rendering.

**Mitigation:**
- PRs C and E use feature flags for instant rollback.
- Response shape should be kept identical to old format with a serialization adapter.
- Test each frontend page end-to-end before removing the feature flag.

### 5.3 Broker reconciliation breakage during cutover (PR F)

**Risk:** Reconciliation currently reads `_load_positions()` from `training_positions`. If writes switch to `unified_positions` but reconciliation still reads old tables, orphans are missed.

**Mitigation:**
- PR F must update `execution/reconciliation.py` to read from `unified_positions` simultaneously.
- During the dual-write phase (PRs B–E), reconciliation should check BOTH tables and log any "found in unified but not in old" discrepancies.

### 5.4 admin_audit_log continuity

**Risk:** If `admin_config` or `admin_audit_log` are affected by the table rename, config reads break.

**Mitigation:** These tables are NOT part of the engine consolidation. They stay exactly where they are. PR H only renames `training_*` and `paper_*` tables.

### 5.5 Redis hot-cache coherence

**Risk:** Engine 1 uses Redis `hset`/`hgetall` for training positions alongside Postgres. If unified tables are the new source of truth, the Redis cache must either be updated or eliminated.

**Mitigation:**
- PR B: dual-write to both unified Postgres AND Redis (same pattern as today).
- PR F: Redis cache keys change to `bahamut:unified_positions:{id}`. Old keys are deleted.
- Long-term: evaluate whether Redis cache is still needed given unified Postgres is the source of truth.

### 5.6 Celery task references

**Risk:** `paper_trading/tasks.py` and other Celery tasks reference old table names directly.

**Mitigation:** PR G explicitly updates all Celery tasks. Pre-deployment grep for old table names as a CI check.

---

## 6. Success Criteria

The consolidation is complete when ALL of the following are true:

1. **Single source of truth:** Every open position and closed trade exists in exactly one place — the `unified_*` tables. No data in `training_positions`, `training_trades`, `paper_positions`, or in-memory `ExecutionEngine.open_positions`.

2. **Single endpoint surface:** Every frontend page reads from `/api/v1/execution/*` endpoints. No page reads from `/api/v1/training/*`, `/api/v1/paper-trading/*`, or `/api/v1/v7/*` for position/trade data.

3. **Reconciliation zero discrepancies:** 14 consecutive days with zero reconciliation mismatches between unified tables and broker state.

4. **Parity validation clean:** PR D's parity checker reports zero discrepancies for 14 consecutive days before old tables are archived.

5. **No dead engines:** `execution/engine.py` (in-memory singleton) deleted. `paper_trading/engine.py` deleted. `paper_trading/sync_executor.py` deleted.

6. **Mode parameter working:** `mode=live_broker` and `mode=paper_broker` return correct, isolated datasets from the same endpoints.

7. **Operator trust:** The v7-operations dashboard shows ONE coherent view of all positions across all brokers, with per-position `execution_confirmed` badges and `broker_order_id` click-through.

8. **Backtest compatibility:** `mode=backtest` writes work for `backtesting/replay_v6.py` without a separate table structure.

---

## Timeline Estimate

| PR | Effort | Prerequisite | Calendar |
|---|---|---|---|
| A | 1 day | Phase 4 stable 2 weeks | Week 1 |
| B | 2 days | PR A deployed | Week 1 |
| C | 1 day | PR B deployed | Week 2 |
| D | 1 day + 7-day soak | PR B deployed | Weeks 2–3 |
| E | 2 days | PR D clean for 7 days | Week 3 |
| F | 1 day | PR D clean + PR E stable | Week 4 |
| G | 2 days | PR F stable 3 days | Week 4 |
| H | 0.5 day | PR G stable 7 days | Week 5 |
| I | 1 day | PR H deployed | Week 5 |
| J | 1 day | PR I deployed | Week 5 |

**Total:** ~5 weeks from first PR to completion. The 7-day soak periods are the bottleneck, not the code.

---

## Non-Goals for Phase 5

These are explicitly out of scope:

- Strategy changes (v5/v9/v10 logic stays identical)
- Broker-side bracket orders (separate Phase 5b or Phase 6)
- Multi-venue execution (Bybit, OKX)
- Real-time WebSocket user-data stream
- Funding-rate accrual
- Correlation-aware portfolio sizing

Phase 5 is purely structural — same strategies, same brokers, same signals, one engine instead of four.
