"""
Bahamut v4.1 — Tuning, Walk-Forward, Monte Carlo Validation

Usage:
    python -m bahamut.backtesting.run_v41 [--sweep|--walkforward|--montecarlo|--all]
"""
import numpy as np
import warnings
import os
from itertools import product

warnings.filterwarnings("ignore")
os.environ.setdefault("STRUCTLOG_LEVEL", "ERROR")

import structlog
structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(40))

from bahamut.backtesting.replay_v4 import V4ReplayEngine, V4Config
from bahamut.backtesting.replay import ReplayEngine, BacktestConfig
from bahamut.backtesting.data_real import generate_realistic_btc


def run_v2(candles):
    cfg = BacktestConfig(asset="BTCUSD", asset_class="crypto",
                         disable_regime=True, disable_adaptive=True)
    return ReplayEngine(cfg).run(candles).metrics


def run_v4(candles, **kw):
    defaults = dict(asset="BTCUSD", asset_class="crypto")
    defaults.update(kw)
    return V4ReplayEngine(V4Config(**defaults)).run(candles)


# ═══════════════════════════════════════════════════════════
# PARAMETER SWEEP
# ═══════════════════════════════════════════════════════════

def parameter_sweep():
    candles = generate_realistic_btc(seed=42)
    print(f"  Data: {len(candles)} candles, ${candles[0]['close']:,.0f} → ${candles[-1]['close']:,.0f}")

    trail_atrs = [1.5, 2.0, 2.5, 3.0]
    be_rs = [1.0, 1.5, 2.0]
    structures = [True, False]

    results = []

    # v2 baseline first
    m2 = run_v2(candles)
    results.append(("v2_baseline", m2, {}))

    print(f"\n  {'Config':<35} {'Ret':>8} {'Sh':>6} {'DD%':>6} {'N':>5} {'WR':>5} "
          f"{'PF':>5} {'Exp':>7} {'MFE/MAE':>8}")
    print("  " + "─" * 92)
    print(f"  {'v2_baseline':<35} {m2['total_return_pct']:>+7.1f}% {m2.get('sharpe_ratio',0):>6.2f} "
          f"{m2['max_drawdown']*100:>5.1f}% {m2['total_trades']:>5} {m2['win_rate']*100:>4.0f}% "
          f"{m2['profit_factor']:>5.2f} {m2['expectancy']:>7.0f} {'n/a':>8}")

    for trail, be_r, struct in product(trail_atrs, be_rs, structures):
        label = f"t{trail}_be{be_r}_s{'Y' if struct else 'N'}"
        try:
            result = run_v4(candles,
                trail_atr_mult=trail,
                breakeven_r=be_r,
                trail_trigger_r=max(be_r, 1.5),
                enable_structure=struct,
                enable_exit_engine=True,
                enable_trailing=True,
                enable_breakeven=True,
                enable_partial_tp=False,
                enable_entry_engine=False,
            )
            m = result.metrics
            params = {"trail": trail, "be_r": be_r, "struct": struct}
            results.append((label, m, params))

            print(f"  {label:<35} {m['total_return_pct']:>+7.1f}% {m['sharpe_ratio']:>6.2f} "
                  f"{m['max_drawdown']*100:>5.1f}% {m['total_trades']:>5} {m['win_rate']*100:>4.0f}% "
                  f"{m['profit_factor']:>5.2f} {m['expectancy']:>7.0f} {m.get('mfe_mae_ratio',0):>8.2f}")
        except Exception as e:
            print(f"  {label:<35} ERROR: {str(e)[:50]}")

    # Find best configs
    valid = [(n, m, p) for n, m, p in results if m.get('total_trades', 0) > 10 and n != "v2_baseline"]

    if valid:
        by_return = max(valid, key=lambda x: x[1]['total_return_pct'])
        by_sharpe = max(valid, key=lambda x: x[1]['sharpe_ratio'])
        by_expect = max(valid, key=lambda x: x[1]['expectancy'])

        print(f"\n  Best return:  {by_return[0]} → {by_return[1]['total_return_pct']:+.1f}%")
        print(f"  Best Sharpe:  {by_sharpe[0]} → {by_sharpe[1]['sharpe_ratio']:.2f}")
        print(f"  Best expect:  {by_expect[0]} → ${by_expect[1]['expectancy']:,.0f}")
        print(f"\n  v2 baseline:  {m2['total_return_pct']:+.1f}%, Sharpe {m2['sharpe_ratio']:.2f}")

    return results


# ═══════════════════════════════════════════════════════════
# WALK-FORWARD VALIDATION
# ═══════════════════════════════════════════════════════════

def walk_forward(best_params=None):
    candles = generate_realistic_btc(seed=42)

    if best_params is None:
        best_params = dict(trail_atr_mult=2.5, breakeven_r=1.5, trail_trigger_r=1.5,
                          enable_structure=True, enable_exit_engine=True,
                          enable_trailing=True, enable_breakeven=True,
                          enable_partial_tp=False, enable_entry_engine=False)

    # 6-month train (~1080 candles), 3-month test (~540 candles)
    train_size = 1080
    test_size = 540
    step = 540  # Roll by 3 months

    print(f"  Data: {len(candles)} candles")
    print(f"  Window: {train_size} train + {test_size} test, step {step}")

    print(f"\n  {'Window':<16} {'v2_Train':>9} {'v2_Test':>9} {'v4_Train':>9} {'v4_Test':>9} "
          f"{'Δ_Test':>7} {'v4_Sh':>6} {'v4_N':>5}")
    print("  " + "─" * 75)

    v2_tests, v4_tests = [], []
    start = 0
    win_num = 1

    while start + train_size + test_size <= len(candles):
        train = candles[start:start + train_size]
        test_start = max(0, start + train_size - 200)  # Overlap warmup
        test = candles[test_start:start + train_size + test_size]

        # v2
        try:
            m2_train = run_v2(train)
            m2_test = run_v2(test)
        except:
            m2_train = m2_test = {"total_return_pct": 0, "sharpe_ratio": 0, "total_trades": 0}

        # v4
        v4kw = dict(asset="BTCUSD", asset_class="crypto")
        v4kw.update(best_params)
        try:
            m4_train = V4ReplayEngine(V4Config(**v4kw)).run(train).metrics
            m4_test = V4ReplayEngine(V4Config(**v4kw)).run(test).metrics
        except:
            m4_train = m4_test = {"total_return_pct": 0, "sharpe_ratio": 0, "total_trades": 0}

        delta = m4_test["total_return_pct"] - m2_test["total_return_pct"]
        v2_tests.append(m2_test["total_return_pct"])
        v4_tests.append(m4_test["total_return_pct"])

        label = f"W{win_num} ({start//180}m-{(start+train_size+test_size)//180}m)"
        print(f"  {label:<16} {m2_train['total_return_pct']:>+8.1f}% {m2_test['total_return_pct']:>+8.1f}% "
              f"{m4_train['total_return_pct']:>+8.1f}% {m4_test['total_return_pct']:>+8.1f}% "
              f"{delta:>+6.1f}% {m4_test.get('sharpe_ratio',0):>6.2f} {m4_test['total_trades']:>5}")

        start += step
        win_num += 1

    v2a, v4a = np.array(v2_tests), np.array(v4_tests)
    v4_wins = sum(1 for a, b in zip(v2_tests, v4_tests) if b > a)
    print(f"\n  v2 avg test: {v2a.mean():+.2f}%  |  v4 avg test: {v4a.mean():+.2f}%")
    print(f"  v4 wins: {v4_wins}/{len(v2_tests)} windows")
    print(f"  v4 avg improvement: {(v4a-v2a).mean():+.2f}%")

    return v2_tests, v4_tests


# ═══════════════════════════════════════════════════════════
# MONTE CARLO ROBUSTNESS
# ═══════════════════════════════════════════════════════════

def monte_carlo(n_sims=100, drop_pct_range=(0.10, 0.30), best_params=None):
    candles = generate_realistic_btc(seed=42)

    if best_params is None:
        best_params = dict(trail_atr_mult=2.5, breakeven_r=1.5, trail_trigger_r=1.5,
                          enable_structure=True, enable_exit_engine=True,
                          enable_trailing=True, enable_breakeven=True,
                          enable_partial_tp=False, enable_entry_engine=False)

    # Run full backtest to get trade list
    v4kw = dict(asset="BTCUSD", asset_class="crypto")
    v4kw.update(best_params)
    result = V4ReplayEngine(V4Config(**v4kw)).run(candles)
    trades = result.trades
    n_trades = len(trades)

    print(f"  Base: {n_trades} trades, return={result.metrics['total_return_pct']:+.1f}%")

    mc_returns, mc_sharpes, mc_max_dds = [], [], []

    for sim in range(n_sims):
        np.random.seed(sim)
        drop_pct = np.random.uniform(*drop_pct_range)
        n_drop = int(n_trades * drop_pct)
        drop_indices = set(np.random.choice(n_trades, n_drop, replace=False))

        # Simulate equity from remaining trades
        balance = 100_000.0
        peak = balance
        max_dd = 0.0
        pnls = []

        for idx, t in enumerate(trades):
            if idx in drop_indices:
                continue
            balance += t["pnl"]
            pnls.append(t["pnl"])
            peak = max(peak, balance)
            dd = 1 - balance / peak if peak > 0 else 0
            max_dd = max(max_dd, dd)

        ret = (balance - 100_000) / 100_000 * 100
        pnl_arr = np.array(pnls) if pnls else np.array([0])
        sharpe = float(np.mean(pnl_arr) / (np.std(pnl_arr) + 1e-10) * np.sqrt(len(pnl_arr)))

        mc_returns.append(ret)
        mc_sharpes.append(sharpe)
        mc_max_dds.append(max_dd * 100)

    r = np.array(mc_returns)
    s = np.array(mc_sharpes)
    d = np.array(mc_max_dds)

    print(f"\n  Monte Carlo ({n_sims} sims, dropping {drop_pct_range[0]*100:.0f}-{drop_pct_range[1]*100:.0f}% of trades):")
    print(f"  Return:  mean={r.mean():+.1f}%, median={np.median(r):+.1f}%, "
          f"5th={np.percentile(r,5):+.1f}%, 95th={np.percentile(r,95):+.1f}%")
    print(f"  Sharpe:  mean={s.mean():.2f}, 5th={np.percentile(s,5):.2f}, 95th={np.percentile(s,95):.2f}")
    print(f"  Max DD:  mean={d.mean():.1f}%, worst={d.max():.1f}%")
    print(f"  Positive runs: {np.sum(r > 0)}/{n_sims} ({np.sum(r > 0)/n_sims*100:.0f}%)")

    collapse = np.sum(r < -10)
    print(f"  Collapse (<-10%): {collapse}/{n_sims}")

    if np.sum(r > 0) / n_sims > 0.80:
        print("  → ROBUST: profitable in 80%+ of Monte Carlo runs")
    elif np.sum(r > 0) / n_sims > 0.60:
        print("  → MODERATE: profitable in 60-80% of runs")
    else:
        print("  → FRAGILE: profitable in <60% of runs")

    return mc_returns, mc_sharpes, mc_max_dds


if __name__ == "__main__":
    import sys
    args = set(sys.argv[1:])
    run_all = "--all" in args or len(args) == 0

    if run_all or "--sweep" in args:
        print("\n" + "="*95)
        print("  PARAMETER SWEEP (4680 realistic BTC candles, Jan 2023 — Mar 2025)")
        print("="*95)
        sweep_results = parameter_sweep()

    if run_all or "--walkforward" in args:
        print("\n" + "="*80)
        print("  WALK-FORWARD VALIDATION (6mo train / 3mo test / 3mo step)")
        print("="*80)
        walk_forward()

    if run_all or "--montecarlo" in args:
        print("\n" + "="*80)
        print("  MONTE CARLO ROBUSTNESS (100 sims)")
        print("="*80)
        monte_carlo()

    print("\n" + "="*80)
