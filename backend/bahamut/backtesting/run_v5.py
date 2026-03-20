"""
Bahamut v5 — Validation Runner

Compares v2 baseline, v2 long-only, v5 pullback, v5+exit on realistic BTC data.
"""
import numpy as np, warnings, os
warnings.filterwarnings("ignore")
os.environ.setdefault("STRUCTLOG_LEVEL", "ERROR")
import structlog
structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(40))

from bahamut.backtesting.replay import ReplayEngine, BacktestConfig
from bahamut.backtesting.replay_v5 import V5ReplayEngine, V5Config
from bahamut.backtesting.data_real import generate_realistic_btc


def run_v2(candles, **kw):
    cfg = BacktestConfig(asset="BTCUSD", asset_class="crypto",
                         disable_regime=True, disable_adaptive=True, **kw)
    return ReplayEngine(cfg).run(candles)


def run_v5(candles, **kw):
    defaults = dict(asset="BTCUSD", asset_class="crypto")
    defaults.update(kw)
    return V5ReplayEngine(V5Config(**defaults)).run(candles)


def print_row(label, m, extra=""):
    lp = m.get("long_pnl", "?")
    sp = m.get("short_pnl", "?")
    lp_s = f"${lp:>+8,.0f}" if isinstance(lp, (int, float)) else f"{'?':>9}"
    sp_s = f"${sp:>+8,.0f}" if isinstance(sp, (int, float)) else f"{'?':>9}"
    print(f"  {label:<26} {m.get('total_return_pct',0):>+7.1f}% {m.get('sharpe_ratio',0):>6.2f} "
          f"{m.get('max_drawdown',0)*100:>5.1f}% {m.get('total_trades',0):>4} "
          f"{m.get('win_rate',0)*100:>5.1f}% {m.get('profit_factor',0):>5.2f} "
          f"{m.get('expectancy',0):>8.0f} {m.get('mfe_mae_ratio','n/a'):>6} "
          f"{lp_s} {sp_s} {extra}")


def comparison_test():
    """Main comparison on full realistic BTC data."""
    candles = generate_realistic_btc(seed=42)
    bnh = (candles[-1]["close"] / candles[0]["close"] - 1) * 100
    print(f"\n  Data: {len(candles)} BTC 4H candles, ${candles[0]['close']:,.0f} → ${candles[-1]['close']:,.0f}")
    print(f"  Buy-and-hold: {bnh:+.1f}%")

    print(f"\n  {'Config':<26} {'Ret':>8} {'Sh':>6} {'DD%':>6} {'N':>4} "
          f"{'WR':>6} {'PF':>6} {'Exp':>8} {'MFE/M':>6} {'Long$':>9} {'Short$':>9}")
    print("  " + "─" * 105)

    # 1. v2 baseline
    r = run_v2(candles)
    m = r.metrics
    longs = [t for t in r.trades if t["direction"] == "LONG"]
    shorts = [t for t in r.trades if t["direction"] == "SHORT"]
    m["long_pnl"] = sum(t["pnl"] for t in longs)
    m["short_pnl"] = sum(t["pnl"] for t in shorts)
    m["long_trades"] = len(longs)
    m["short_trades"] = len(shorts)
    print_row("v2_baseline", m)

    # 2. v2 wider SL
    r = run_v2(candles, sl_atr_mult=3.0, tp_atr_mult=4.5)
    m = r.metrics
    longs = [t for t in r.trades if t["direction"] == "LONG"]
    shorts = [t for t in r.trades if t["direction"] == "SHORT"]
    m["long_pnl"] = sum(t["pnl"] for t in longs)
    m["short_pnl"] = sum(t["pnl"] for t in shorts)
    print_row("v2_wide_sl3", m)

    # 3. v5 default
    m = run_v5(candles)
    print_row("v5_pullback_default", m)

    # 4. v5 no exit engine
    m = run_v5(candles, enable_exit_engine=False)
    print_row("v5_no_exit_engine", m)

    # 5. v5 no structure
    m = run_v5(candles, enable_structure=False)
    print_row("v5_no_structure", m)

    # 6. v5 wider trail
    m = run_v5(candles, trail_atr_mult=3.0, breakeven_r=2.0)
    print_row("v5_wide_trail_3.0", m)

    # 7. v5 tighter quality
    m = run_v5(candles, min_pullback_quality=0.45, full_size_quality=0.60)
    print_row("v5_quality_0.45", m)

    # 8. v5 looser quality
    m = run_v5(candles, min_pullback_quality=0.30)
    print_row("v5_quality_0.30", m)

    return m


def multi_seed_test():
    """Test across multiple data seeds."""
    print(f"\n  {'Seed':<6} {'BnH':>8} {'v2':>8} {'v5':>8} {'v5_N':>5} {'v5_WR':>6} {'Winner':>8}")
    print("  " + "─" * 52)

    v2_sum, v5_sum = [], []
    for seed in [42, 7, 123, 999, 2025, 314, 55, 77]:
        candles = generate_realistic_btc(seed=seed)
        bnh = (candles[-1]["close"] / candles[0]["close"] - 1) * 100

        m2 = run_v2(candles).metrics
        m5 = run_v5(candles)

        v2_sum.append(m2["total_return_pct"])
        v5_sum.append(m5["total_return_pct"])

        winner = "v5" if m5["total_return_pct"] > m2["total_return_pct"] else "v2"
        print(f"  {seed:<6} {bnh:>+7.0f}% {m2['total_return_pct']:>+7.1f}% {m5['total_return_pct']:>+7.1f}% "
              f"{m5['total_trades']:>5} {m5['win_rate']*100:>5.1f}% {winner:>8}")

    print(f"\n  v2 avg: {np.mean(v2_sum):+.1f}%  |  v5 avg: {np.mean(v5_sum):+.1f}%")
    print(f"  v5 wins: {sum(1 for a,b in zip(v2_sum,v5_sum) if b>a)}/{len(v2_sum)} seeds")


def walk_forward_test():
    """Rolling walk-forward on full data."""
    candles = generate_realistic_btc(seed=42)
    train = 1080  # 6 months
    test = 540    # 3 months
    step = 540

    print(f"\n  {'Window':<20} {'v2_Test':>9} {'v5_Test':>9} {'Δ':>7} {'v5_N':>5} {'v5_WR':>6}")
    print("  " + "─" * 56)

    v2_t, v5_t = [], []
    start, w = 0, 1
    while start + train + test <= len(candles):
        test_data = candles[max(0, start+train-250):start+train+test]
        try:
            m2 = run_v2(test_data).metrics["total_return_pct"]
        except:
            m2 = 0
        try:
            m5 = run_v5(test_data)
            m5r = m5["total_return_pct"]
            m5n = m5["total_trades"]
            m5w = m5["win_rate"] * 100
        except:
            m5r, m5n, m5w = 0, 0, 0

        v2_t.append(m2)
        v5_t.append(m5r)
        d = m5r - m2
        print(f"  W{w} ({start//180}m-{(start+train+test)//180}m) {m2:>+8.1f}% {m5r:>+8.1f}% "
              f"{d:>+6.1f}% {m5n:>5} {m5w:>5.1f}%")
        start += step
        w += 1

    print(f"\n  v2 avg: {np.mean(v2_t):+.1f}%  |  v5 avg: {np.mean(v5_t):+.1f}%")
    print(f"  v5 wins: {sum(1 for a,b in zip(v2_t,v5_t) if b>a)}/{len(v2_t)} windows")


def monte_carlo_test():
    """Monte Carlo robustness test."""
    candles = generate_realistic_btc(seed=42)
    m_full = run_v5(candles)
    trades = [t.to_dict() for t in V5ReplayEngine(V5Config()).closed_trades] if False else None

    # Re-run to get trades
    engine = V5ReplayEngine(V5Config())
    engine.run(candles)
    trades_list = engine.closed_trades

    n = len(trades_list)
    print(f"  Base: {n} trades, return={m_full['total_return_pct']:+.1f}%")

    mc_rets = []
    for sim in range(200):
        np.random.seed(sim)
        drop = int(n * np.random.uniform(0.10, 0.30))
        keep = set(range(n)) - set(np.random.choice(n, drop, replace=False))
        bal = 100_000.0
        peak = bal
        max_dd = 0.0
        for idx in sorted(keep):
            t = trades_list[idx]
            bal += t.pnl
            peak = max(peak, bal)
            dd = 1 - bal / peak if peak > 0 else 0
            max_dd = max(max_dd, dd)
        mc_rets.append((bal - 100_000) / 100_000 * 100)

    r = np.array(mc_rets)
    print(f"\n  Monte Carlo (200 sims, drop 10-30%):")
    print(f"  Mean: {r.mean():+.1f}%, 5th: {np.percentile(r,5):+.1f}%, 95th: {np.percentile(r,95):+.1f}%")
    print(f"  Positive: {np.sum(r>0)}/{len(r)} ({np.sum(r>0)/len(r)*100:.0f}%)")
    if np.sum(r > 0) / len(r) > 0.80:
        print("  → ROBUST")
    elif np.sum(r > 0) / len(r) > 0.60:
        print("  → MODERATE")
    else:
        print("  → FRAGILE")


if __name__ == "__main__":
    import sys
    args = set(sys.argv[1:])
    run_all = "--all" in args or len(args) == 0

    if run_all or "--compare" in args:
        print("\n" + "="*110)
        print("  V5 COMPARISON TEST (realistic BTC, Jan 2023 — Mar 2025)")
        print("="*110)
        comparison_test()

    if run_all or "--seeds" in args:
        print("\n" + "="*60)
        print("  MULTI-SEED ROBUSTNESS")
        print("="*60)
        multi_seed_test()

    if run_all or "--walkforward" in args:
        print("\n" + "="*60)
        print("  WALK-FORWARD VALIDATION")
        print("="*60)
        walk_forward_test()

    if run_all or "--montecarlo" in args:
        print("\n" + "="*60)
        print("  MONTE CARLO ROBUSTNESS")
        print("="*60)
        monte_carlo_test()

    print("\n" + "="*60)
