"""
Bahamut v3 — Walk-Forward Validation & Ablation Framework

Usage:
    python -m bahamut.backtesting.walkforward [--regime|--zero-drift|--ablation|--all]
"""
import numpy as np
import warnings
import os
from dataclasses import dataclass

warnings.filterwarnings("ignore")
os.environ.setdefault("STRUCTLOG_LEVEL", "ERROR")

import structlog
structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(40))

from bahamut.backtesting.replay import ReplayEngine, BacktestConfig


def generate_zero_drift(base_price=65000, count=500, volatility=0.015, seed=0):
    np.random.seed(seed)
    candles, price = [], base_price
    for i in range(count):
        ret = np.random.normal(0, volatility)
        o = price; c = price * (1 + ret)
        h = max(o, c) * (1 + abs(np.random.normal(0, volatility * 0.5)))
        l = min(o, c) * (1 - abs(np.random.normal(0, volatility * 0.5)))
        candles.append({"datetime": f"2025-{i:05d}", "open": round(o, 2),
            "high": round(h, 2), "low": round(l, 2), "close": round(c, 2), "volume": 10000})
        price = c
    return candles


def generate_regime_data(seed=42, count=1200):
    np.random.seed(seed)
    candles, price = [], 65000
    regimes = [(300, 0.002, 0.008), (150, -0.005, 0.025),
               (300, 0.001, 0.010), (250, 0.000, 0.006), (200, -0.001, 0.015)]
    for n, drift, vol in regimes:
        for i in range(n):
            ret = np.random.normal(drift, vol)
            o = price; c = price * (1 + ret)
            h = max(o, c) * (1 + abs(np.random.normal(0, vol * 0.5)))
            l = min(o, c) * (1 - abs(np.random.normal(0, vol * 0.5)))
            candles.append({"datetime": f"2025-{len(candles):05d}", "open": round(o, 2),
                "high": round(h, 2), "low": round(l, 2), "close": round(c, 2), "volume": 10000})
            price = c
    return candles


def _safe_run(cfg, data):
    default = {"total_return_pct": 0, "sharpe_ratio": 0, "max_drawdown": 0,
               "total_trades": 0, "win_rate": 0, "profit_factor": 0}
    if len(data) < cfg.min_candles_warmup + 10:
        return default
    try:
        return ReplayEngine(cfg).run(data).metrics
    except Exception:
        return default


def run_walk_forward(candles, window_size=600, step=150, train_pct=0.6, warmup=200):
    results, start = [], 0
    while start + window_size <= len(candles):
        window = candles[start:start + window_size]
        split = int(len(window) * train_pct)
        cfg = BacktestConfig(asset="BTCUSD", asset_class="crypto", min_candles_warmup=warmup)
        m_train = _safe_run(cfg, window[:split])
        m_test = _safe_run(cfg, window[max(0, split - warmup):])
        results.append({
            "window": f"{start}-{start+window_size}",
            "train_ret": m_train["total_return_pct"],
            "test_ret": m_test["total_return_pct"],
            "train_sharpe": m_train["sharpe_ratio"],
            "test_sharpe": m_test["sharpe_ratio"],
            "test_dd": m_test["max_drawdown"] * 100,
            "test_trades": m_test["total_trades"],
            "test_wr": m_test["win_rate"] * 100,
        })
        start += step
    return results


def run_ablation(candles):
    import bahamut.intelligence.regime as regime_mod
    import bahamut.strategy.adaptive as adaptive_mod

    orig_detect = regime_mod.regime_detector.detect
    orig_compute = adaptive_mod.adaptive_strategy.compute
    results = []

    def _run(name, regime_on, adaptive_on, cfg=None):
        nonlocal orig_detect, orig_compute
        if cfg is None:
            cfg = BacktestConfig(asset="BTCUSD", asset_class="crypto")
        regime_mod.regime_detector.detect = orig_detect if regime_on else (
            lambda *a, **kw: regime_mod.CompositeRegime())
        adaptive_mod.adaptive_strategy.compute = orig_compute if adaptive_on else (
            lambda *a, **kw: adaptive_mod.AdaptiveParams(sl_multiplier=cfg.sl_atr_mult, tp_multiplier=cfg.tp_atr_mult))
        try:
            m = _safe_run(cfg, candles)
            results.append((name, m))
        finally:
            regime_mod.regime_detector.detect = orig_detect
            adaptive_mod.adaptive_strategy.compute = orig_compute

    _run("v2_baseline", False, False)
    _run("v2+adaptive", False, True)
    _run("v2+regime", True, False)
    _run("full_v3", True, True)
    _run("v3_high_cost", True, True,
         BacktestConfig(asset="BTCUSD", asset_class="crypto", slippage_bps=20, spread_bps=30))
    return results


def run_zero_drift_mc(n_seeds=30, count=500):
    returns, sharpes, wrs = [], [], []
    for seed in range(n_seeds):
        m = _safe_run(BacktestConfig(asset="BTCUSD", asset_class="crypto"),
                      generate_zero_drift(seed=seed, count=count))
        if m["total_trades"] > 0:
            returns.append(m["total_return_pct"])
            sharpes.append(m["sharpe_ratio"])
            wrs.append(m["win_rate"])
    r = np.array(returns) if returns else np.array([0])
    from scipy import stats
    t, p = stats.ttest_1samp(r, 0) if len(r) > 2 else (0, 1)
    return {"n": len(returns), "mean": float(r.mean()), "std": float(r.std()),
            "positive_pct": float(np.mean(r > 0) * 100),
            "sharpe": float(np.mean(sharpes)) if sharpes else 0,
            "wr": float(np.mean(wrs)) if wrs else 0,
            "t": float(t), "p": float(p),
            "min": float(r.min()), "max": float(r.max())}


def analyze_signal_quality(candles):
    cfg = BacktestConfig(asset="BTCUSD", asset_class="crypto")
    result = ReplayEngine(cfg).run(candles)
    trades = result.trades
    mfe, mae, tte = [], [], []
    lpnl, spnl, lc, sc = 0, 0, 0, 0
    for t in trades:
        ei, xi, ep, d = t["entry_time"], t["exit_time"], t["entry_price"], t["direction"]
        mf, ma = 0, 0
        for j in range(ei+1, min(xi+1, len(candles))):
            c = candles[j]
            f = ((c["high"] - ep) if d == "LONG" else (ep - c["low"])) / ep * 100
            a = ((ep - c["low"]) if d == "LONG" else (c["high"] - ep)) / ep * 100
            mf, ma = max(mf, f), max(ma, a)
        mfe.append(mf); mae.append(ma); tte.append(xi - ei)
        if d == "LONG": lpnl += t["pnl"]; lc += 1
        else: spnl += t["pnl"]; sc += 1
    mfe, mae, tte = np.array(mfe or [0]), np.array(mae or [0]), np.array(tte or [0])
    return {"trades": len(trades), "mfe": float(mfe.mean()), "mae": float(mae.mean()),
            "ratio": float(mfe.mean() / max(0.001, mae.mean())), "tte": float(tte.mean()),
            "lc": lc, "sc": sc, "lpnl": lpnl, "spnl": spnl, "metrics": result.metrics}


if __name__ == "__main__":
    import sys
    args = set(sys.argv[1:])
    run_all = "--all" in args or len(args) == 0

    if run_all or "--zero-drift" in args:
        print("\n" + "="*70)
        print("  ZERO-DRIFT MONTE CARLO (30 seeds)")
        print("="*70)
        zd = run_zero_drift_mc(30)
        print(f"\n  Seeds w/ trades: {zd['n']}/30")
        print(f"  Mean return: {zd['mean']:+.2f}% ± {zd['std']:.2f}%")
        print(f"  Positive: {zd['positive_pct']:.0f}%  |  Mean WR: {zd['wr']*100:.1f}%  |  Sharpe: {zd['sharpe']:.3f}")
        print(f"  T-test: t={zd['t']:.3f}, p={zd['p']:.4f} {'← BIASED!' if zd['p']<0.05 else '← FAIR'}")

    if run_all or "--regime" in args:
        print("\n" + "="*70)
        print("  WALK-FORWARD: REGIME DATA (1200 candles)")
        print("="*70)
        wf = run_walk_forward(generate_regime_data(count=1200))
        print(f"\n  {'Window':<14} {'Train%':>8} {'Test%':>8} {'TrSh':>7} {'TeSh':>7} {'DD%':>6} {'N':>4} {'WR%':>5}")
        print("  " + "─" * 57)
        for r in wf:
            print(f"  {r['window']:<14} {r['train_ret']:>+7.1f}% {r['test_ret']:>+7.1f}% {r['train_sharpe']:>7.2f} {r['test_sharpe']:>7.2f} {r['test_dd']:>5.1f}% {r['test_trades']:>4} {r['test_wr']:>4.0f}%")
        tr = [r["train_ret"] for r in wf]; te = [r["test_ret"] for r in wf]
        print(f"\n  Avg train: {np.mean(tr):+.2f}%  |  Avg test: {np.mean(te):+.2f}%  |  Gap: {np.mean(tr)-np.mean(te):+.2f}%")

    if run_all or "--ablation" in args:
        print("\n" + "="*70)
        print("  ABLATION TEST")
        print("="*70)
        ab = run_ablation(generate_regime_data(count=900))
        print(f"\n  {'Config':<18} {'Return':>10} {'Sharpe':>8} {'DD%':>7} {'N':>5} {'WR':>5} {'PF':>5}")
        print("  " + "─" * 55)
        for name, m in ab:
            print(f"  {name:<18} {m.get('total_return_pct',0):>+9.1f}% {m.get('sharpe_ratio',0):>8.2f} {m.get('max_drawdown',0)*100:>6.1f}% {m.get('total_trades',0):>5} {m.get('win_rate',0)*100:>4.0f}% {m.get('profit_factor',0):>5.2f}")

    if run_all or "--signal" in args:
        print("\n" + "="*70)
        print("  SIGNAL QUALITY")
        print("="*70)
        sq = analyze_signal_quality(generate_regime_data(count=900))
        print(f"\n  Trades: {sq['trades']}")
        print(f"  MFE: {sq['mfe']:.2f}%  |  MAE: {sq['mae']:.2f}%  |  Ratio: {sq['ratio']:.2f}")
        print(f"  Time to exit: {sq['tte']:.1f} bars")
        print(f"  LONG: {sq['lc']} (${sq['lpnl']:+,.0f})  |  SHORT: {sq['sc']} (${sq['spnl']:+,.0f})")

    print("\n" + "="*70)
