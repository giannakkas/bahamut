# TICKET: V5 Stocks-Only Experiment

**Filed:** 2026-04-26
**Priority:** Low (not blocking)
**Depends on:** Stocks 4h candle backtest infrastructure
**Component:** strategies/v5_base.py, scripts/

## Context

V5 was retired from 15m crypto production routing after a 70-variant parameter
sweep showed no positive-expectancy configuration. However, V5 stock performance
in debug_exploration is promising:

- 45 stock trades, 55.2% WR, +$1,394 total PnL
- Best combos: NFLX+v5 LONG (11 trades, 72.7% WR, +$1,404)
- 4h bars give EMA crosses more significance than 15m bars

## Proposed Work

1. Build 4h stock candle backtest dataset (TwelveData or Alpaca historical)
2. Run same parameter sweep as v5-strategy-sweep but on 4h stock data
3. Test SL/TP values: 3.5%/7% (current), plus 2%/5%, 3%/6%, 4%/8%
4. Test hold periods: 10, 20, 30 (current), 40 bars (= 2-7 NYSE trading days)
5. If positive expectancy found, re-enable V5 for stocks only via:
   ```python
   if "v5" in strat_name and asset_class != "stock":
       continue  # V5 only runs on stocks
   ```

## Acceptance Criteria

- ≥30 trades in backtest (10-day minimum, preferably 30-day)
- Positive expectancy (>$0/trade)
- WR ≥ 50%
- Not dependent on a single asset (edge must exist across ≥3 stocks)
