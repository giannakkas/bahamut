"""
Bahamut v9 — Edge Discovery Validation

Tests:
1. v9 standalone performance
2. v5 vs v9 comparison
3. v5 + v9 combined portfolio
4. Independence test (trade overlap, return correlation)
5. Multi-seed robustness
6. Monte Carlo stability
"""
import numpy as np
import warnings
import os

warnings.filterwarnings("ignore")
os.environ.setdefault("STRUCTLOG_LEVEL", "ERROR")
import structlog
structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(40))

from bahamut.features.indicators import compute_indicators
from bahamut.alpha.v9_candidate import V9Breakout
from bahamut.alpha.signal_engine import generate_signal  # v5 signal
from bahamut.backtesting.data_real import generate_realistic_btc


def run_strategy(candles, strategy_fn, sl_pct, tp_pct, max_hold,
                 risk_pct=0.02, warmup=250, slippage_bps=8):
    """Generic single-strategy backtester. Returns trades list + final balance."""
    balance = 100_000.0
    trades = []
    open_t = None
    prev_ind = None

    for i in range(warmup, len(candles)):
        ind = compute_indicators(candles[:i + 1])
        if not ind:
            continue

        bar = candles[i]
        close = ind["close"]

        # Check open trade
        if open_t:
            open_t["bars"] += 1
            h, l, c = bar["high"], bar["low"], bar["close"]

            if open_t["dir"] == "LONG":
                sl_hit = l <= open_t["sl"]
                tp_hit = h >= open_t["tp"]
            else:
                sl_hit = h >= open_t["sl"]
                tp_hit = l <= open_t["tp"]

            ep = reason = None
            if sl_hit and tp_hit:
                ep, reason = open_t["sl"], "SL"
            elif sl_hit:
                ep, reason = open_t["sl"], "SL"
            elif tp_hit:
                ep, reason = open_t["tp"], "TP"
            elif open_t["bars"] >= max_hold:
                ep, reason = c, "TO"

            if ep:
                if open_t["dir"] == "LONG":
                    pnl = (ep - open_t["entry"]) * open_t["size"]
                else:
                    pnl = (open_t["entry"] - ep) * open_t["size"]
                balance += pnl
                open_t["pnl"] = round(pnl, 2)
                open_t["reason"] = reason
                open_t["exit_idx"] = i
                trades.append(open_t)
                open_t = None

        # Generate signal
        if open_t is None and prev_ind is not None:
            sig = strategy_fn(candles[:i + 1], ind, prev_ind)
            if sig and i + 1 < len(candles):
                entry = candles[i + 1]["open"]
                slip = entry * (slippage_bps / 10000)
                entry += slip  # LONG slippage

                if sig.direction == "LONG":
                    sl = entry * (1 - sl_pct)
                    tp = entry * (1 + tp_pct)
                else:
                    sl = entry * (1 + sl_pct)
                    tp = entry * (1 - tp_pct)

                risk = balance * risk_pct
                sd = abs(entry - sl)
                size = risk / sd if sd > 0 else 0

                open_t = {
                    "dir": sig.direction, "entry": round(entry, 2),
                    "sl": round(sl, 2), "tp": round(tp, 2),
                    "size": size, "bars": 0,
                    "entry_idx": i + 1,
                }

        prev_ind = ind

    # Close remaining
    if open_t and candles:
        c = candles[-1]["close"]
        pnl = (c - open_t["entry"]) * open_t["size"] if open_t["dir"] == "LONG" \
            else (open_t["entry"] - c) * open_t["size"]
        balance += pnl
        open_t["pnl"] = round(pnl, 2)
        open_t["reason"] = "END"
        open_t["exit_idx"] = len(candles) - 1
        trades.append(open_t)

    return trades, balance


def metrics(trades, initial=100_000.0, balance=None):
    if not trades:
        return {"ret": 0, "sh": 0, "dd": 0, "n": 0, "wr": 0, "pf": 0}
    if balance is None:
        balance = initial + sum(t["pnl"] for t in trades)
    pnls = [t["pnl"] for t in trades]
    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] <= 0]
    ret = (balance - initial) / initial * 100
    r = np.array(pnls) / initial
    sh = float(np.mean(r) / (np.std(r) + 1e-10) * np.sqrt(len(r))) if len(r) > 1 else 0
    gp = sum(t["pnl"] for t in wins) if wins else 0
    gl = abs(sum(t["pnl"] for t in losses)) if losses else 1
    return {
        "ret": round(ret, 2), "sh": round(sh, 2),
        "n": len(trades), "wr": round(len(wins) / len(trades) * 100, 0),
        "pf": round(gp / gl, 2) if gl > 0 else 0,
    }


def v5_signal_fn(candles, ind, prev_ind):
    sig = generate_signal(candles, ind, prev_ind)
    if sig and sig.valid and sig.direction == "LONG":
        return sig
    return None


def v9_signal_fn(candles, ind, prev_ind):
    v9 = V9Breakout()
    return v9.evaluate(candles, ind, prev_ind)


def run_comparison(seed=42, n_candles=1500):
    candles = generate_realistic_btc(seed=seed)[:n_candles]
    bnh = (candles[-1]["close"] / candles[0]["close"] - 1) * 100

    # v5
    t5, b5 = run_strategy(candles, v5_signal_fn, 0.08, 0.16, 30)
    m5 = metrics(t5, balance=b5)

    # v9
    t9, b9 = run_strategy(candles, v9_signal_fn, 0.06, 0.12, 20)
    m9 = metrics(t9, balance=b9)

    # Combined: run both, share capital 50/50
    # Simplified: just sum PnL (they'd run on separate sleeves)
    combined_pnl = sum(t["pnl"] for t in t5) * 0.5 + sum(t["pnl"] for t in t9) * 0.5
    combined_ret = combined_pnl / 100_000 * 100
    combined_n = len(t5) + len(t9)

    return {
        "seed": seed, "bnh": bnh, "n_candles": n_candles,
        "v5": m5, "v9": m9,
        "combined_ret": round(combined_ret, 2),
        "combined_n": combined_n,
        "t5": t5, "t9": t9,
    }


def independence_test(result):
    """Check if v9 trades are independent from v5."""
    t5_entries = set(t["entry_idx"] for t in result["t5"])
    t9_entries = set(t["entry_idx"] for t in result["t9"])

    overlap = t5_entries & t9_entries
    total = len(t5_entries | t9_entries) or 1

    # Return correlation: compare PnL sequences
    # Align by time (pad to same length)
    if result["t5"] and result["t9"]:
        pnl5 = np.array([t["pnl"] for t in result["t5"]])
        pnl9 = np.array([t["pnl"] for t in result["t9"]])
        # Simple: correlation of trade PnLs (padded)
        min_len = min(len(pnl5), len(pnl9))
        if min_len >= 3:
            corr = np.corrcoef(pnl5[:min_len], pnl9[:min_len])[0, 1]
        else:
            corr = 0.0
    else:
        corr = 0.0

    return {
        "entry_overlap": len(overlap),
        "total_unique_entries": len(t5_entries | t9_entries),
        "overlap_pct": round(len(overlap) / total * 100, 1),
        "return_correlation": round(corr, 3) if not np.isnan(corr) else 0.0,
    }


if __name__ == "__main__":
    print("=" * 75)
    print("  V9 EDGE DISCOVERY — CONFIRMED BREAKOUT STRATEGY")
    print("=" * 75)

    # ── 1. Primary comparison (seed 42) ──
    print("\n--- Primary Test (seed 42, 1500 candles) ---")
    r = run_comparison(42, 1500)
    print(f"  BnH: {r['bnh']:+.0f}%")
    print(f"  v5:       {r['v5']['ret']:>+7.1f}%  Sh={r['v5']['sh']:>5.2f}  N={r['v5']['n']:>3}  WR={r['v5']['wr']:.0f}%  PF={r['v5']['pf']:.2f}")
    print(f"  v9:       {r['v9']['ret']:>+7.1f}%  Sh={r['v9']['sh']:>5.2f}  N={r['v9']['n']:>3}  WR={r['v9']['wr']:.0f}%  PF={r['v9']['pf']:.2f}")
    print(f"  combined: {r['combined_ret']:>+7.1f}%  (50/50 capital split, N={r['combined_n']})")

    # ── 2. Independence test ──
    print("\n--- Independence Test ---")
    ind = independence_test(r)
    print(f"  Entry overlap: {ind['entry_overlap']}/{ind['total_unique_entries']} ({ind['overlap_pct']}%)")
    print(f"  Return correlation: {ind['return_correlation']:.3f}")
    print(f"  Independent: {'YES' if abs(ind['return_correlation']) < 0.5 else 'NO'}")

    # ── 3. Multi-seed ──
    print("\n--- Multi-Seed Validation ---")
    print(f"  {'Seed':<6} {'BnH':>7} {'v5':>8} {'v9':>8} {'Comb':>8} {'v5_N':>5} {'v9_N':>5}")
    print("  " + "─" * 50)

    v5_all, v9_all, comb_all = [], [], []
    for seed in [42, 7, 123, 999, 2025]:
        r = run_comparison(seed, 1200)
        v5_all.append(r["v5"]["ret"])
        v9_all.append(r["v9"]["ret"])
        comb_all.append(r["combined_ret"])
        print(f"  {seed:<6} {r['bnh']:>+6.0f}% {r['v5']['ret']:>+7.1f}% {r['v9']['ret']:>+7.1f}% "
              f"{r['combined_ret']:>+7.1f}% {r['v5']['n']:>5} {r['v9']['n']:>5}")

    print(f"\n  Avg: v5={np.mean(v5_all):+.1f}%  v9={np.mean(v9_all):+.1f}%  combined={np.mean(comb_all):+.1f}%")
    print(f"  v9 positive: {sum(1 for x in v9_all if x > 0)}/{len(v9_all)} seeds")
    print(f"  v9 beats v5: {sum(1 for a, b in zip(v5_all, v9_all) if b > a)}/{len(v5_all)} seeds")

    # ── 4. Monte Carlo (seed 42) ──
    print("\n--- Monte Carlo (seed 42, v9 only) ---")
    r = run_comparison(42, 1500)
    t9 = r["t9"]
    n = len(t9)
    mc_rets = []
    for sim in range(100):
        np.random.seed(sim)
        drop = int(n * np.random.uniform(0.1, 0.3))
        keep = sorted(set(range(n)) - set(np.random.choice(n, max(1, drop), replace=False)))
        bal = 100_000.0
        for idx in keep:
            bal += t9[idx]["pnl"]
        mc_rets.append((bal - 100_000) / 100_000 * 100)

    mc = np.array(mc_rets)
    print(f"  Mean: {mc.mean():+.1f}%  5th: {np.percentile(mc, 5):+.1f}%  "
          f"95th: {np.percentile(mc, 95):+.1f}%  Positive: {np.sum(mc > 0)}/100")

    # ── 5. Verdict ──
    print("\n" + "=" * 75)
    print("  VERDICT")
    print("=" * 75)

    v9_avg = np.mean(v9_all)
    v9_pos = sum(1 for x in v9_all if x > 0)
    mc_pos = np.sum(mc > 0)

    if v9_pos >= 3 and mc_pos >= 60 and v9_avg > 0:
        print("  v9 HAS REAL EDGE: positive avg return, majority of seeds profitable")
    elif v9_pos >= 2 and mc_pos >= 50:
        print("  v9 SHOWS PROMISE: some evidence of edge, needs more data")
    else:
        print("  v9 DOES NOT HAVE RELIABLE EDGE: insufficient evidence")

    print(f"\n  Source: Confirmed breakout (20-bar high + 3-bar hold)")
    print(f"  Independent from v5: {'YES' if abs(ind['return_correlation']) < 0.5 else 'NO'}")
    print("=" * 75)
