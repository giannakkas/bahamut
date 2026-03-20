"""
Bahamut v4 — Ablation Test Runner

Usage:
    python -m bahamut.backtesting.run_v4 [--ablation|--walkforward|--signal|--all]
"""
import numpy as np
import warnings
import os

warnings.filterwarnings("ignore")
os.environ.setdefault("STRUCTLOG_LEVEL", "ERROR")

import structlog
structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(40))

from bahamut.backtesting.replay_v4 import V4ReplayEngine, V4Config
from bahamut.backtesting.replay import ReplayEngine, BacktestConfig


def gen_regime(seed=42, count=900):
    np.random.seed(seed)
    candles, price = [], 65000
    for n, drift, vol in [(250, 0.002, 0.008), (100, -0.005, 0.025),
                          (250, 0.001, 0.010), (200, 0.000, 0.006),
                          (100, -0.001, 0.015)]:
        for i in range(n):
            r = np.random.normal(drift, vol)
            o = price; c = price * (1 + r)
            h = max(o, c) * (1 + abs(np.random.normal(0, vol * 0.5)))
            lo = min(o, c) * (1 - abs(np.random.normal(0, vol * 0.5)))
            candles.append({"datetime": f"2025-{len(candles):05d}",
                "open": round(o, 2), "high": round(h, 2),
                "low": round(lo, 2), "close": round(c, 2), "volume": 10000})
            price = c
    return candles


def gen_zero_drift(seed=0, count=500):
    np.random.seed(seed)
    candles, price = [], 65000
    for i in range(count):
        r = np.random.normal(0, 0.015)
        o = price; c = price * (1 + r)
        h = max(o, c) * (1 + abs(np.random.normal(0, 0.0075)))
        lo = min(o, c) * (1 - abs(np.random.normal(0, 0.0075)))
        candles.append({"datetime": f"{i}", "open": round(o, 2),
            "high": round(h, 2), "low": round(lo, 2),
            "close": round(c, 2), "volume": 10000})
        price = c
    return candles


def run_v2_baseline(candles):
    """v2 baseline with v3 disabled."""
    cfg = BacktestConfig(asset="BTCUSD", asset_class="crypto",
                         disable_regime=True, disable_adaptive=True)
    return ReplayEngine(cfg).run(candles).metrics


def run_v4(candles, **overrides):
    """Full v4 with optional feature disabling."""
    kw = dict(asset="BTCUSD", asset_class="crypto")
    kw.update(overrides)
    return V4ReplayEngine(V4Config(**kw)).run(candles).metrics


def print_row(name, m):
    print(f"  {name:<24} {m.get('total_return_pct',0):>+8.1f}% "
          f"{m.get('sharpe_ratio',0):>7.2f} {m.get('max_drawdown',0)*100:>6.1f}% "
          f"{m.get('total_trades',0):>5} {m.get('win_rate',0)*100:>5.1f}% "
          f"{m.get('profit_factor',0):>5.2f} "
          f"{m.get('expectancy',0):>8.0f} "
          f"{m.get('avg_mfe_r','-'):>6} "
          f"{m.get('avg_mae_r','-'):>6} "
          f"{m.get('mfe_mae_ratio','-'):>6}")


def run_ablation():
    candles = gen_regime()
    print(f"\n  Data: {len(candles)} candles, multi-regime (bull→crash→recovery→range→bear)")

    print(f"\n  {'Config':<24} {'Return':>9} {'Sharpe':>7} {'DD%':>6} "
          f"{'Trades':>5} {'WR':>6} {'PF':>6} {'Expect':>8} "
          f"{'MFE_R':>6} {'MAE_R':>6} {'Ratio':>6}")
    print("  " + "─" * 100)

    results = []

    # 1. v2 baseline
    m = run_v2_baseline(candles)
    print_row("v2_baseline", m)
    results.append(("v2_baseline", m))

    # 2. v4 structure only (no entry/exit engine)
    m = run_v4(candles, enable_entry_engine=False, enable_exit_engine=False,
               enable_trailing=False, enable_partial_tp=False, enable_breakeven=False)
    print_row("v4_structure_only", m)
    results.append(("v4_structure", m))

    # 3. v4 entry engine only (no exit engine)
    m = run_v4(candles, enable_exit_engine=False, enable_trailing=False,
               enable_partial_tp=False, enable_breakeven=False)
    print_row("v4_entry_only", m)
    results.append(("v4_entry", m))

    # 4. v4 exit engine only (no entry engine)
    m = run_v4(candles, enable_entry_engine=False)
    print_row("v4_exit_only", m)
    results.append(("v4_exit", m))

    # 5. v4 entry + exit (no partial TP)
    m = run_v4(candles, enable_partial_tp=False)
    print_row("v4_entry+exit_nopartial", m)
    results.append(("v4_no_partial", m))

    # 6. Full v4
    m = run_v4(candles)
    print_row("full_v4", m)
    results.append(("full_v4", m))

    # 7. v4 high cost
    m = run_v4(candles, slippage_bps=20, spread_bps=30)
    print_row("v4_high_cost", m)
    results.append(("v4_high_cost", m))

    return results


def run_zero_drift_test(n_seeds=20):
    returns_v2, returns_v4 = [], []
    for seed in range(n_seeds):
        candles = gen_zero_drift(seed=seed)
        try:
            m2 = run_v2_baseline(candles)
            m4 = run_v4(candles)
            returns_v2.append(m2["total_return_pct"])
            returns_v4.append(m4["total_return_pct"])
        except Exception:
            pass

    r2 = np.array(returns_v2)
    r4 = np.array(returns_v4)
    from scipy import stats
    _, p2 = stats.ttest_1samp(r2, 0) if len(r2) > 2 else (0, 1)
    _, p4 = stats.ttest_1samp(r4, 0) if len(r4) > 2 else (0, 1)

    print(f"  v2: mean={r2.mean():+.2f}%, std={r2.std():.2f}%, p={p2:.3f}")
    print(f"  v4: mean={r4.mean():+.2f}%, std={r4.std():.2f}%, p={p4:.3f}")
    print(f"  v4 vs v2 mean diff: {r4.mean()-r2.mean():+.2f}%")


def run_entry_type_analysis():
    candles = gen_regime()
    m = run_v4(candles)
    et = m.get("entry_types", {})
    if et:
        print(f"\n  {'Entry Type':<14} {'Count':>6} {'Wins':>5} {'WR%':>6} {'PnL':>10} {'AvgQ':>6}")
        print("  " + "─" * 50)
        for name, stats in sorted(et.items(), key=lambda x: -x[1]["total_pnl"]):
            wr = stats["wins"] / max(1, stats["count"]) * 100
            print(f"  {name:<14} {stats['count']:>6} {stats['wins']:>5} {wr:>5.1f}% "
                  f"${stats['total_pnl']:>+9,.0f} {stats['avg_quality']:>5.2f}")

    er = m.get("exit_reasons", {})
    if er:
        print(f"\n  {'Exit Reason':<20} {'Count':>6} {'Wins':>5} {'WR%':>6} {'PnL':>10}")
        print("  " + "─" * 50)
        for name, stats in sorted(er.items(), key=lambda x: -x[1]["total_pnl"]):
            wr = stats["wins"] / max(1, stats["count"]) * 100
            print(f"  {name:<20} {stats['count']:>6} {stats['wins']:>5} {wr:>5.1f}% "
                  f"${stats['total_pnl']:>+9,.0f}")


if __name__ == "__main__":
    import sys
    args = set(sys.argv[1:])
    run_all = "--all" in args or len(args) == 0

    if run_all or "--ablation" in args:
        print("\n" + "="*70)
        print("  V4 ABLATION TEST")
        print("="*70)
        run_ablation()

    if run_all or "--zero-drift" in args:
        print("\n" + "="*70)
        print("  ZERO-DRIFT BIAS TEST (20 seeds)")
        print("="*70)
        run_zero_drift_test()

    if run_all or "--signal" in args:
        print("\n" + "="*70)
        print("  ENTRY TYPE & EXIT REASON ANALYSIS")
        print("="*70)
        run_entry_type_analysis()

    print("\n" + "="*70)
