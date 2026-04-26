# V5 Strategy Retirement — 2026-04-26

## Decision

V5 (v5_base, EMA20×50 cross) is retired from production routing on 15m crypto.
Debug exploration continues collecting research data.

## What the bug was

V5 evaluate() generates a signal on the **exact bar** where EMA20 crosses EMA50.
This is a one-bar event lasting 15 minutes. The trading cycle runs every 10 minutes.
Due to the 10min/15min phasing mismatch, ~33% of cross events are missed when the
cycle polls during a stale bar (`is_new_bar=False`), and the `elif not is_new_bar:
continue` gate drops the LONG signal entirely.

Result: V5 produced **zero** `standard` execution_type trades in its entire history.
All 154 V5 trades were `debug_exploration` (which bypasses the new-bar gate).

## What fix was attempted

Branch `v5-window-fix` (commit `3862a3a`):
- Widened cross detection from 1-bar to 3-bar window via `_find_recent_cross()`
- Added `_ema_series()` matching canonical EMA math exactly (verified)
- Added Redis signal cooldown (`bahamut:signal_executed:{signal_id}`, 2h TTL)
  to prevent re-entry after SL close within the cross window
- signal_id keyed on `cross_bar_ts` for dedup across bars T, T+1, T+2

The fix worked mechanically: backtest detected 7 trades (vs 0 with old logic),
dedup blocked 5 re-fires, bars_ago distribution was {1: 5, 2: 2}.

## What backtest showed

10 days of 15m candles, 22 crypto assets, production SL/TP (2.5%/5%):

```
OLD (1-bar): 0 trades
NEW (3-bar): 7 trades, WR=28.6%, PnL=-$760, Avg=-$108.59/trade
```

## Parameter sweep results

Branch `v5-strategy-sweep` (commit `39c15b3`): ~70 variants tested.

Dimensions swept:
- TP%: 2.0, 2.5, 3.0, 3.5, 4.0, 5.0 (SL fixed at 2.5%)
- Hold bars: 10, 20, 40, 80
- Window: 1, 2, 3, 4
- Filters: ADX>20, ADX>25, vol>1.5x, EMA200+1%, cross_lower_half, combinations

**Result: No variant achieved positive expectancy with ≥15 trades.**

The EMA20×50 cross on 15-minute crypto candles does not produce a tradeable edge
under any tested parameter combination.

## Why we retired (not paused)

1. Zero historical production trades — strategy has never been validated in production
2. Debug exploration data (154 trades, 47% WR, +$7.53 avg) used wider SL (4.9% avg)
   and proximity-based entry (not actual crosses) — not representative of production
3. Stock-class V5 shows promise (55% WR, +$1,395 on 4h bars) but was not tested in
   this sweep (4h candle backtest requires different infrastructure)
4. Keeping V5 in production routing would pollute trust scores, expectancy tracking,
   and suppress maps with -EV signals

## Implementation

- `orchestrator.py`: V5 signals blocked from production path when
  `V5_PRODUCTION_ENABLED` env var is unset or `"0"` (default)
- V5 evaluate() unchanged — strategy code is intact
- Debug exploration continues — research trust keys still updated
- Re-enable: set `V5_PRODUCTION_ENABLED=1` in Railway env vars

## Branches (historical record, do not merge)

- `v5-window-fix`: 3-bar window + Redis dedup (mechanically correct, strategy has no edge)
- `v5-strategy-sweep`: 70-variant parameter sweep script + results

## Research data caveats

V5 debug_exploration trades are **not a random sample** of V5's signal universe.
The debug_exploration path only runs when `strategy_signals_found == 0` — meaning
no strategy (V5, V9, or V10) produced a production-routed signal for that asset on
that cycle. With V5 gated off, the condition becomes: debug_exploration runs only
when V9 and V10 are both silent on the asset.

This creates a **selection bias**: V5 research data is conditioned on V9/V10
silence. Assets and market conditions where V9 breakout or V10 mean-reversion
fire are systematically excluded from V5's debug dataset. In practice:

- Assets in strong TREND regime (V9 fires) → V5 debug underrepresented
- Assets in RANGE/CRASH regime (V10 fires) → V5 debug underrepresented
- Assets in quiet/transitional regimes (neither fires) → V5 debug overrepresented

If we ever revive V5 based on debug_exploration performance, the dataset must be
understood as "V5 edge in markets where V9/V10 see nothing interesting" — not
"V5 edge across all conditions." A proper re-evaluation would require running V5
in a standalone backtest against all assets regardless of V9/V10 signal state.

## Future work

- **V5 stocks-only experiment**: run parameter sweep on 4h stock candles (see TICKET)
- If stock sweep shows edge, re-enable V5 for stocks only via asset_class gate
- Consider V5 on higher timeframes (1h, 4h) where EMA crosses are more meaningful
