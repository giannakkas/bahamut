"""
V5 Strategy Parameter Sweep — Candle-Level Replay

Sweeps: TP%, hold bars, window size, confirmation filters.
Uses 15m candles from Binance for all non-suppressed crypto assets.

Run: python backend/scripts/v5_strategy_sweep.py

Output: single table sorted by expectancy descending.
"""
import sys, time
import numpy as np
import httpx

SYMBOL_MAP = {
    "ETHUSD": "ETHUSDT", "BNBUSD": "BNBUSDT",
    "SOLUSD": "SOLUSDT", "XRPUSD": "XRPUSDT", "ADAUSD": "ADAUSDT",
    "DOGEUSD": "DOGEUSDT", "AVAXUSD": "AVAXUSDT", "LINKUSD": "LINKUSDT",
    "DOTUSD": "DOTUSDT", "ATOMUSD": "ATOMUSDT", "UNIUSD": "UNIUSDT",
    "LTCUSD": "LTCUSDT", "NEARUSD": "NEARUSDT",
    "OPUSD": "OPUSDT", "APTUSD": "APTUSDT",
    "INJUSD": "INJUSDT", "PEPEUSD": "PEPEUSDT", "SUIUSD": "SUIUSDT",
    "SEIUSD": "SEIUSDT", "JUPUSD": "JUPUSDT", "ENAUSD": "ENAUSDT",
    "TIAUSD": "TIAUSDT",
}

SL_PCT = 0.025  # Fixed at 2.5% — not sweeping SL
RISK_USD = 500


def _ema_series(data, period):
    result = np.empty(len(data))
    k = 2.0 / (period + 1)
    result[0] = float(data[0])
    for i in range(1, len(data)):
        result[i] = (float(data[i]) - result[i - 1]) * k + result[i - 1]
    return result


def _sma(data, period):
    if len(data) < period:
        return np.full(len(data), np.nan)
    result = np.full(len(data), np.nan)
    for i in range(period - 1, len(data)):
        result[i] = np.mean(data[i - period + 1:i + 1])
    return result


def _adx(highs, lows, closes, period=14):
    """ADX series (simplified Wilder smoothing)."""
    n = len(closes)
    if n < period + 1:
        return np.full(n, np.nan)
    result = np.full(n, np.nan)
    # True range
    tr = np.zeros(n)
    tr[0] = highs[0] - lows[0]
    for i in range(1, n):
        tr[i] = max(highs[i] - lows[i],
                    abs(highs[i] - closes[i - 1]),
                    abs(lows[i] - closes[i - 1]))
    # +DM / -DM
    pdm = np.zeros(n)
    mdm = np.zeros(n)
    for i in range(1, n):
        up = highs[i] - highs[i - 1]
        down = lows[i - 1] - lows[i]
        pdm[i] = up if up > down and up > 0 else 0
        mdm[i] = down if down > up and down > 0 else 0
    # Wilder smoothing
    atr_s = np.sum(tr[1:period + 1])
    pdm_s = np.sum(pdm[1:period + 1])
    mdm_s = np.sum(mdm[1:period + 1])
    dx_vals = []
    for i in range(period + 1, n):
        atr_s = atr_s - (atr_s / period) + tr[i]
        pdm_s = pdm_s - (pdm_s / period) + pdm[i]
        mdm_s = mdm_s - (mdm_s / period) + mdm[i]
        if atr_s == 0:
            continue
        pdi = 100 * pdm_s / atr_s
        mdi = 100 * mdm_s / atr_s
        denom = pdi + mdi
        dx = 100 * abs(pdi - mdi) / denom if denom > 0 else 0
        dx_vals.append(dx)
        if len(dx_vals) >= period:
            if len(dx_vals) == period:
                adx_val = np.mean(dx_vals)
            else:
                adx_val = (adx_val * (period - 1) + dx) / period
            result[i] = adx_val
    return result


def fetch_candles(symbol):
    for base in ["https://api.binance.com/api/v3/klines",
                  "https://fapi.binance.com/fapi/v1/klines"]:
        try:
            r = httpx.get(base, params={
                "symbol": symbol, "interval": "15m", "limit": 1000
            }, timeout=15)
            if r.status_code == 200:
                raw = r.json()
                if raw and len(raw) > 10:
                    return [{
                        "open": float(k[1]), "high": float(k[2]),
                        "low": float(k[3]), "close": float(k[4]),
                        "volume": float(k[5]), "ts": k[0]
                    } for k in raw]
        except Exception:
            pass
    return []


def simulate(candles, idx, direction, sl_pct, tp_pct, max_hold):
    entry = candles[idx]["close"]
    sl = entry * (1 - sl_pct) if direction == "LONG" else entry * (1 + sl_pct)
    tp = entry * (1 + tp_pct) if direction == "LONG" else entry * (1 - tp_pct)
    for b in range(1, max_hold + 1):
        i = idx + b
        if i >= len(candles):
            break
        h, l = candles[i]["high"], candles[i]["low"]
        if direction == "LONG":
            if l <= sl:
                return {"exit": "SL", "pnl_pct": -sl_pct, "bars": b}
            if h >= tp:
                return {"exit": "TP", "pnl_pct": tp_pct, "bars": b}
        else:
            if h >= sl:
                return {"exit": "SL", "pnl_pct": -sl_pct, "bars": b}
            if l <= tp:
                return {"exit": "TP", "pnl_pct": tp_pct, "bars": b}
    exit_p = candles[min(idx + max_hold, len(candles) - 1)]["close"]
    if direction == "LONG":
        pnl = (exit_p - entry) / entry
    else:
        pnl = (entry - exit_p) / entry
    return {"exit": "TIMEOUT", "pnl_pct": pnl, "bars": max_hold}


def run_variant(all_data, tp_pct, hold, window, filters, sl_pct=SL_PCT):
    """Run one sweep variant across all assets. Returns list of trades."""
    trades = []
    for asset, data in all_data.items():
        candles = data["candles"]
        closes = data["closes"]
        highs = data["highs"]
        lows = data["lows"]
        volumes = data["volumes"]
        ema20 = data["ema20"]
        ema50 = data["ema50"]
        ema200 = data["ema200"]
        adx_s = data["adx"]
        vol_sma20 = data["vol_sma20"]

        used = set()
        for bi in range(210, len(candles) - hold):
            c = closes[bi]
            e200 = ema200[bi]
            if c <= 0 or np.isnan(e200):
                continue
            # ATR filter
            atr_slice = np.maximum(
                highs[bi - 13:bi + 1] - lows[bi - 13:bi + 1],
                np.maximum(
                    np.abs(highs[bi - 13:bi + 1] - closes[bi - 14:bi]),
                    np.abs(lows[bi - 13:bi + 1] - closes[bi - 14:bi])
                )
            )
            if len(atr_slice) < 14:
                continue
            atr_v = float(np.mean(atr_slice))
            if atr_v / c < 0.008:
                continue
            # EMA gap
            gap = abs(ema20[bi] - ema50[bi]) / ema50[bi] if ema50[bi] > 0 else 0
            if gap < 0.001:
                continue

            # Cross detection with window
            for ago in range(window):
                ci = bi - ago
                if ci < 51:
                    continue

                is_long_cross = (ema20[ci - 1] <= ema50[ci - 1] and
                                 ema20[ci] > ema50[ci] and c > e200)
                is_short_cross = (ema20[ci - 1] >= ema50[ci - 1] and
                                  ema20[ci] < ema50[ci] and c < e200)

                if not is_long_cross and not is_short_cross:
                    continue

                direction = "LONG" if is_long_cross else "SHORT"
                cid = f"{direction[0]}:{ci}"
                if cid in used:
                    break  # dedup — same cross already traded

                # Apply confirmation filters at the CROSS bar (ci)
                skip = False
                for f in filters:
                    if f == "adx20" and (np.isnan(adx_s[ci]) or adx_s[ci] < 20):
                        skip = True
                    elif f == "adx25" and (np.isnan(adx_s[ci]) or adx_s[ci] < 25):
                        skip = True
                    elif f == "vol15x":
                        if (np.isnan(vol_sma20[ci]) or vol_sma20[ci] <= 0 or
                                volumes[ci] < 1.5 * vol_sma20[ci]):
                            skip = True
                    elif f == "ema200_1pct":
                        if direction == "LONG" and c <= e200 * 1.01:
                            skip = True
                        elif direction == "SHORT" and c >= e200 * 0.99:
                            skip = True
                    elif f == "cross_lower_half":
                        bar_range = highs[ci] - lows[ci]
                        if bar_range > 0:
                            cross_pos = (closes[ci] - lows[ci]) / bar_range
                            if direction == "LONG" and cross_pos > 0.5:
                                skip = True
                            elif direction == "SHORT" and cross_pos < 0.5:
                                skip = True
                if skip:
                    break

                used.add(cid)
                result = simulate(candles, bi, direction, sl_pct, tp_pct, hold)
                result["asset"] = asset
                result["bars_ago"] = ago
                result["pnl_usd"] = result["pnl_pct"] * RISK_USD / sl_pct
                trades.append(result)
                break  # found cross, stop looking back

    return trades


def summarize(trades):
    if not trades:
        return {"n": 0, "wr": 0, "avg": 0, "total": 0, "exp": 0,
                "sl": 0, "tp": 0, "to": 0, "ago": {}}
    w = sum(1 for t in trades if t["pnl_usd"] > 1)
    l = sum(1 for t in trades if t["pnl_usd"] < -1)
    total = sum(t["pnl_usd"] for t in trades)
    wr = 100 * w / len(trades)
    avg = total / len(trades)
    exits = {"SL": 0, "TP": 0, "TIMEOUT": 0}
    ago = {}
    for t in trades:
        exits[t["exit"]] = exits.get(t["exit"], 0) + 1
        a = t.get("bars_ago", 0)
        ago[a] = ago.get(a, 0) + 1
    # Expectancy
    avg_win = np.mean([t["pnl_usd"] for t in trades if t["pnl_usd"] > 1]) if w else 0
    avg_loss = abs(np.mean([t["pnl_usd"] for t in trades if t["pnl_usd"] < -1])) if l else 1
    exp = (wr / 100 * avg_win - (1 - wr / 100) * avg_loss) if len(trades) > 0 else 0
    return {"n": len(trades), "wr": round(wr, 1), "avg": round(avg, 2),
            "total": round(total, 2), "exp": round(exp, 2),
            "sl": exits["SL"], "tp": exits["TP"], "to": exits["TIMEOUT"],
            "ago": ago}


def run():
    print(f"\n{'=' * 90}")
    print(f"V5 STRATEGY SWEEP — 15m crypto, SL=2.5% fixed, 22 assets")
    print(f"{'=' * 90}")

    # Fetch all candle data once
    all_data = {}
    for asset, sym in sorted(SYMBOL_MAP.items()):
        candles = fetch_candles(sym)
        if len(candles) < 300:
            print(f"  {asset}: {len(candles)} candles, skip")
            continue
        closes = np.array([c["close"] for c in candles])
        highs = np.array([c["high"] for c in candles])
        lows = np.array([c["low"] for c in candles])
        volumes = np.array([c["volume"] for c in candles])
        all_data[asset] = {
            "candles": candles,
            "closes": closes,
            "highs": highs,
            "lows": lows,
            "volumes": volumes,
            "ema20": _ema_series(closes, 20),
            "ema50": _ema_series(closes, 50),
            "ema200": _ema_series(closes, 200),
            "adx": _adx(highs, lows, closes),
            "vol_sma20": _sma(volumes, 20),
        }
        print(f"  {asset}: {len(candles)} candles loaded")
        time.sleep(0.15)

    print(f"\n  {len(all_data)} assets loaded. Running sweep...\n")

    results = []

    # Phase 1: TP × Hold sweep (window=3, no filters)
    for tp in [0.02, 0.025, 0.03, 0.035, 0.04, 0.05]:
        for hold in [10, 20, 40, 80]:
            trades = run_variant(all_data, tp, hold, window=3, filters=[])
            s = summarize(trades)
            label = f"TP={tp * 100:.1f}% H={hold} W=3"
            results.append((label, s))

    # Phase 2: Window sweep (best TP/hold TBD — use all combos with TP=3%, H=40 as reference)
    for win in [1, 2, 3, 4]:
        trades = run_variant(all_data, 0.03, 40, window=win, filters=[])
        s = summarize(trades)
        label = f"TP=3.0% H=40 W={win}"
        results.append((label, s))

    # Phase 3: Confirmation filters (window=3, TP=3%, H=40 as reference)
    for fname, flist in [
        ("adx20", ["adx20"]),
        ("adx25", ["adx25"]),
        ("vol15x", ["vol15x"]),
        ("ema200_1pct", ["ema200_1pct"]),
        ("cross_lower_half", ["cross_lower_half"]),
        ("adx20+vol15x", ["adx20", "vol15x"]),
        ("adx25+ema200_1pct", ["adx25", "ema200_1pct"]),
    ]:
        trades = run_variant(all_data, 0.03, 40, window=3, filters=flist)
        s = summarize(trades)
        label = f"TP=3.0% H=40 W=3 F={fname}"
        results.append((label, s))

    # Phase 4: Best filter combos applied to other TP/hold values
    for tp in [0.025, 0.03, 0.035]:
        for hold in [20, 40, 80]:
            for fname, flist in [("adx20", ["adx20"]), ("vol15x", ["vol15x"])]:
                trades = run_variant(all_data, tp, hold, window=3, filters=flist)
                s = summarize(trades)
                label = f"TP={tp * 100:.1f}% H={hold} W=3 F={fname}"
                results.append((label, s))

    # Deduplicate results (some combos appear in multiple phases)
    seen = set()
    unique = []
    for label, s in results:
        if label not in seen:
            seen.add(label)
            unique.append((label, s))

    # Sort by expectancy descending
    unique.sort(key=lambda x: x[1]["exp"], reverse=True)

    # Print table
    print(f"{'Variant':<45} {'N':>4} {'WR%':>6} {'AvgPnL':>9} {'TotalPnL':>10} {'Exp$/tr':>8} {'SL':>3} {'TP':>3} {'TO':>3} {'bars_ago'}")
    print("-" * 120)
    for label, s in unique:
        ago_str = str(s["ago"]) if s["ago"] else ""
        marker = " ★" if s["exp"] > 0 and s["n"] >= 15 else ""
        print(f"{label:<45} {s['n']:>4} {s['wr']:>6} {s['avg']:>9} {s['total']:>10} {s['exp']:>8} {s['sl']:>3} {s['tp']:>3} {s['to']:>3} {ago_str}{marker}")

    # Highlight winners
    winners = [(l, s) for l, s in unique if s["exp"] > 0 and s["n"] >= 15]
    print(f"\n{'=' * 90}")
    if winners:
        print(f"POSITIVE EXPECTANCY VARIANTS (≥15 trades):")
        for l, s in winners:
            print(f"  ★ {l}: {s['n']} trades, WR={s['wr']}%, Exp=${s['exp']}/trade, Total=${s['total']}")
        best = winners[0]
        print(f"\n  RECOMMENDED: {best[0]}")
        print(f"  {best[1]}")
    else:
        print(f"NO VARIANT HAS POSITIVE EXPECTANCY WITH ≥15 TRADES.")
        print(f"V5 crypto under current market conditions has no edge.")
        marginal = [(l, s) for l, s in unique if s["exp"] > 0 and s["n"] >= 5]
        if marginal:
            print(f"\n  Marginal (5+ trades, positive exp):")
            for l, s in marginal:
                print(f"    {l}: {s['n']} trades, Exp=${s['exp']}/trade")
    print(f"{'=' * 90}")


if __name__ == "__main__":
    run()
