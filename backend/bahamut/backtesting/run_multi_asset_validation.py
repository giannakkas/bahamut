"""
Bahamut Multi-Asset Validation — BTC + ETH

Validates operational readiness for parallel BTC + ETH trading.
Tests trade count increase, combined risk behavior, signal overlap.

Usage: python -m bahamut.backtesting.run_multi_asset_validation
"""
import numpy as np
import warnings
import os

warnings.filterwarnings("ignore")
os.environ.setdefault("STRUCTLOG_LEVEL", "ERROR")
import structlog
structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(40))

from bahamut.features.indicators import compute_indicators
from bahamut.backtesting.data_real import generate_realistic_btc, generate_realistic_eth
from bahamut.strategies.v5_base import V5Base
from bahamut.strategies.v5_tuned import V5Tuned
from bahamut.alpha.v9_candidate import V9Breakout


def run_single_asset(candles, strategies, warmup=250, risk_pct=0.02,
                     slippage_bps=8, asset="BTCUSD"):
    """Run all strategies on one asset. Returns trades list."""
    balance = 100_000.0
    trades = []
    open_trades = {}  # strategy_name → trade
    prev_ind = None

    for i in range(warmup, len(candles)):
        ind = compute_indicators(candles[:i + 1])
        if not ind:
            continue

        bar = candles[i]

        # Check exits
        for sname in list(open_trades.keys()):
            t = open_trades[sname]
            t["bars"] += 1
            h, l, c = bar["high"], bar["low"], bar["close"]

            if t["dir"] == "LONG":
                sl_hit, tp_hit = l <= t["sl"], h >= t["tp"]
            else:
                sl_hit, tp_hit = h >= t["sl"], l <= t["tp"]

            ep = reason = None
            if sl_hit and tp_hit:
                ep, reason = t["sl"], "SL"
            elif sl_hit:
                ep, reason = t["sl"], "SL"
            elif tp_hit:
                ep, reason = t["tp"], "TP"
            elif t["bars"] >= t["max_hold"]:
                ep, reason = c, "TIMEOUT"

            if ep:
                pnl = (ep - t["entry"]) * t["size"] if t["dir"] == "LONG" \
                    else (t["entry"] - ep) * t["size"]
                balance += pnl
                t["pnl"] = round(pnl, 2)
                t["reason"] = reason
                trades.append(t)
                del open_trades[sname]

        # Evaluate strategies
        for sname, strat in strategies.items():
            if sname in open_trades:
                continue

            try:
                sig = strat.evaluate(candles[:i + 1], ind, prev_ind, asset=asset)
            except TypeError:
                sig = strat.evaluate(candles[:i + 1], ind, prev_ind)

            if sig and i + 1 < len(candles):
                meta_sl = getattr(strat, 'meta', None)
                sl_pct = sig.sl_pct if sig.sl_pct else (meta_sl.sl_pct if meta_sl else 0.08)
                tp_pct = sig.tp_pct if sig.tp_pct else (meta_sl.tp_pct if meta_sl else 0.16)
                max_hold = sig.max_hold_bars if sig.max_hold_bars else (meta_sl.max_hold_bars if meta_sl else 30)

                entry = candles[i + 1]["open"]
                slip = entry * (slippage_bps / 10000)
                entry += slip

                if sig.direction == "LONG":
                    sl = entry * (1 - sl_pct)
                    tp = entry * (1 + tp_pct)
                else:
                    sl = entry * (1 + sl_pct)
                    tp = entry * (1 - tp_pct)

                risk = balance * risk_pct
                sd = abs(entry - sl)
                size = risk / sd if sd > 0 else 0

                open_trades[sname] = {
                    "strategy": sname, "asset": asset,
                    "dir": sig.direction, "entry": round(entry, 2),
                    "sl": round(sl, 2), "tp": round(tp, 2),
                    "size": size, "bars": 0, "max_hold": max_hold,
                    "entry_idx": i + 1,
                }

        prev_ind = ind

    # Close remaining
    for sname in list(open_trades.keys()):
        t = open_trades[sname]
        c = candles[-1]["close"]
        pnl = (c - t["entry"]) * t["size"] if t["dir"] == "LONG" \
            else (t["entry"] - c) * t["size"]
        balance += pnl
        t["pnl"] = round(pnl, 2)
        t["reason"] = "END"
        trades.append(t)

    return trades, balance


def summarize(trades, initial=100_000.0, balance=None):
    if not trades:
        return {"ret": 0, "n": 0, "wr": 0, "pf": 0, "pnl": 0}
    if balance is None:
        balance = initial + sum(t["pnl"] for t in trades)
    pnl = sum(t["pnl"] for t in trades)
    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] <= 0]
    gp = sum(t["pnl"] for t in wins) if wins else 0
    gl = abs(sum(t["pnl"] for t in losses)) if losses else 1
    return {
        "ret": round((balance - initial) / initial * 100, 2),
        "n": len(trades),
        "wr": round(len(wins) / max(1, len(trades)) * 100, 0),
        "pf": round(gp / gl, 2) if gl > 0 else 0,
        "pnl": round(pnl, 0),
    }


if __name__ == "__main__":
    strategies = {
        "v5_base": V5Base(),
        "v5_tuned": V5Tuned(),
        "v9_breakout": V9Breakout(),
    }

    print("=" * 75)
    print("  MULTI-ASSET VALIDATION — BTC + ETH")
    print("=" * 75)

    all_results = {}
    for seed in [42, 7, 123]:
        btc = generate_realistic_btc(seed=seed)[:2000]
        eth = generate_realistic_eth(seed=seed, btc_candles=btc)[:2000]

        btc_bnh = (btc[-1]["close"] / btc[0]["close"] - 1) * 100
        eth_bnh = (eth[-1]["close"] / eth[0]["close"] - 1) * 100

        # BTC only
        t_btc, b_btc = run_single_asset(btc, strategies, asset="BTCUSD")
        m_btc = summarize(t_btc, balance=b_btc)

        # ETH only
        t_eth, b_eth = run_single_asset(eth, strategies, asset="ETHUSD", slippage_bps=10)
        m_eth = summarize(t_eth, balance=b_eth)

        # Combined (50/50 capital split simulation)
        combined_pnl = sum(t["pnl"] for t in t_btc) * 0.5 + sum(t["pnl"] for t in t_eth) * 0.5
        combined_n = len(t_btc) + len(t_eth)
        combined_ret = combined_pnl / 100_000 * 100

        # Overlap: same-day entries
        btc_days = set(t["entry_idx"] for t in t_btc)
        eth_days = set(t["entry_idx"] for t in t_eth)
        overlap = len(btc_days & eth_days)

        all_results[seed] = {
            "btc": m_btc, "eth": m_eth,
            "combined_ret": round(combined_ret, 2),
            "combined_n": combined_n,
            "overlap": overlap,
        }

        print(f"\n  Seed {seed}: BTC BnH={btc_bnh:+.0f}%, ETH BnH={eth_bnh:+.0f}%")
        print(f"  {'':>12} {'Ret':>8} {'N':>4} {'WR':>5} {'PF':>5} {'PnL':>9}")
        print(f"  {'BTC only':>12} {m_btc['ret']:>+7.1f}% {m_btc['n']:>4} {m_btc['wr']:>4.0f}% {m_btc['pf']:>5.2f} ${m_btc['pnl']:>+8,.0f}")
        print(f"  {'ETH only':>12} {m_eth['ret']:>+7.1f}% {m_eth['n']:>4} {m_eth['wr']:>4.0f}% {m_eth['pf']:>5.2f} ${m_eth['pnl']:>+8,.0f}")
        print(f"  {'Combined':>12} {combined_ret:>+7.1f}% {combined_n:>4} {'':>5} {'':>5} ${combined_pnl:>+8,.0f}")
        print(f"  Entry overlap: {overlap} bars (out of {len(btc_days | eth_days)} unique)")

    # Summary
    print(f"\n{'='*75}")
    print("  SUMMARY ACROSS SEEDS")
    print(f"{'='*75}")

    btc_avg = np.mean([r["btc"]["ret"] for r in all_results.values()])
    eth_avg = np.mean([r["eth"]["ret"] for r in all_results.values()])
    comb_avg = np.mean([r["combined_ret"] for r in all_results.values()])
    btc_n = sum(r["btc"]["n"] for r in all_results.values())
    eth_n = sum(r["eth"]["n"] for r in all_results.values())
    comb_n = sum(r["combined_n"] for r in all_results.values())

    print(f"  BTC avg return: {btc_avg:+.1f}%  ({btc_n} trades across {len(all_results)} seeds)")
    print(f"  ETH avg return: {eth_avg:+.1f}%  ({eth_n} trades)")
    print(f"  Combined avg:   {comb_avg:+.1f}%  ({comb_n} total trades)")
    print(f"  Trade count increase: +{comb_n - btc_n} trades ({(comb_n / max(1, btc_n) - 1) * 100:.0f}% more)")

    eth_positive = sum(1 for r in all_results.values() if r["eth"]["ret"] > 0)
    print(f"\n  ETH profitable: {eth_positive}/{len(all_results)} seeds")
    print(f"  Combined beats BTC-only: {sum(1 for r in all_results.values() if r['combined_ret'] > r['btc']['ret'])}/{len(all_results)} seeds")

    print(f"\n{'='*75}")
    print("  VERDICT")
    print(f"{'='*75}")
    if eth_positive >= 2:
        print("  ETH is SUITABLE to add — increases trade count while maintaining profitability")
    elif eth_positive >= 1:
        print("  ETH shows MIXED results — add with reduced risk (0.75x multiplier)")
    else:
        print("  ETH is NOT suitable — losses across seeds")

    projected_annual = comb_n / len(all_results) * (365 * 6 / 2000)
    print(f"  Projected annual trades (combined): ~{projected_annual:.0f}")
    print(f"  Time to 30 trades: ~{30 / max(1, projected_annual) * 12:.0f} months")
    print(f"{'='*75}")
