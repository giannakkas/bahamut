# TICKET: Cycle/Bar Phasing Audit

**Filed:** 2026-04-23
**Priority:** Medium (not blocking V5 fix, but affects future strategies)
**Component:** orchestrator.py, signal generation pipeline

## Problem

The trading cycle runs every 10 minutes. Crypto candle bars close every 15 minutes.
This creates a phasing mismatch where one-bar event signals (signals that fire on
exactly one candle and never again) have a ~33% probability of being dropped.

### Timeline Example

```
Bar closes:  :00   :15   :30   :45   :00   :15
Cycle runs:  :00   :10   :20   :30   :40   :50
                    ↑ stale       ↑ stale
```

If a crossover event happens at bar :15, the cycle at :10 sees the old bar (no cross),
the cycle at :20 sees the :15 bar as `is_new_bar=True` → signal fires → OK.

But if the :00 cycle already processed the previous bar and marked it, and the
crossover happens at :15, the :10 cycle sees `is_new_bar=False` → signal dropped.

### Impact

- V5 EMA20×50 cross: one-bar event → ~33% miss rate (FIXED via 3-bar window in v5_base.py)
- Any future event-based strategy would have the same problem
- V9 breakout is not affected (breakout holds for multiple bars)
- V10 mean reversion is not affected (ongoing condition, not event)

### Root Cause

The `is_new_bar` gate in orchestrator.py (lines 920-940) drops LONG signals
when `is_new_bar=False` unless they have readiness >= 90 (early execution).
SHORT signals bypass this via the crash_short path.

```python
elif not is_new_bar:
    continue   # ← one-bar LONG events die here
```

### Options

1. **Per-strategy fix** (current approach): widen the signal window at the strategy
   level. V5 now uses a 3-bar window. Future strategies can do the same.

2. **Cycle alignment**: change cycle interval to 5 minutes (guarantees at least one
   cycle per 15-min bar). Cost: 3× more API calls, 3× more Celery task overhead.

3. **Signal buffering**: when a signal fires on `is_new_bar=False`, buffer it in
   Redis and re-emit on the next `is_new_bar=True` cycle. Cost: new Redis key per
   buffered signal, dedup complexity.

4. **Remove `is_new_bar` gate for standard LONGs**: let all signals through, rely
   on order_intent dedup (signal_id) to prevent duplicates. Cost: more selector
   evaluations per cycle, but no functional change.

### Recommendation

Option 1 (per-strategy fix) is the safest short-term approach. Option 4 is the
cleanest long-term fix but requires verifying that signal_id dedup is bulletproof.

### Affected Code

- `backend/bahamut/trading/orchestrator.py` lines 920-940
- `backend/bahamut/trading/engine.py` `create_intent()` (dedup layer)
- Any future strategy with event-based signals
