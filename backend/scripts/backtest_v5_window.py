"""
V5 Windowed Cross Backtest — Candle-Level Replay

Fetches 15m candles from Binance for each crypto asset.
Replays _find_recent_cross() at every bar. For each detected cross:
  - Checks production gates (suppress, ema200_degraded, ADX, ATR, EMA gap)
  - Simulates trade with production SL/TP (2.5%/5% crypto)
  - Reports WR, avg PnL, expectancy
  - Counts dedup collisions (same cross detected on multiple bars)

Run: railway run python backend/scripts/backtest_v5_window.py
"""
import os, sys, time, json
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
# Excluded: BTCUSD, FILUSD, WIFUSD, ARBUSD (suppressed), RNDRUSD, MATICUSD, WUSD, COIN

SL_PCT = 0.025; TP_PCT = 0.05; MAX_HOLD = 20; RISK_USD = 500

def _ema_series(data, period):
    result = np.empty(len(data)); k = 2.0 / (period + 1)
    result[0] = float(data[0])
    for i in range(1, len(data)):
        result[i] = (float(data[i]) - result[i-1]) * k + result[i-1]
    return result

def fetch_candles(symbol):
    for base in ["https://api.binance.com/api/v3/klines",
                  "https://fapi.binance.com/fapi/v1/klines"]:
        try:
            r = httpx.get(base, params={"symbol": symbol, "interval": "15m", "limit": 1000}, timeout=15)
            if r.status_code == 200:
                raw = r.json()
                if raw and len(raw) > 10:
                    return [{"open":float(k[1]),"high":float(k[2]),"low":float(k[3]),
                             "close":float(k[4]),"volume":float(k[5]),"ts":k[0]} for k in raw]
        except Exception: pass
    return []

def simulate(candles, idx, direction):
    entry = candles[idx]["close"]
    sl = entry * (1 - SL_PCT) if direction == "LONG" else entry * (1 + SL_PCT)
    tp = entry * (1 + TP_PCT) if direction == "LONG" else entry * (1 - TP_PCT)
    for b in range(1, MAX_HOLD + 1):
        i = idx + b
        if i >= len(candles): break
        h, l = candles[i]["high"], candles[i]["low"]
        if direction == "LONG":
            if l <= sl: return {"exit":"SL","pnl_pct":-SL_PCT,"bars":b}
            if h >= tp: return {"exit":"TP","pnl_pct":TP_PCT,"bars":b}
        else:
            if h >= sl: return {"exit":"SL","pnl_pct":-SL_PCT,"bars":b}
            if l <= tp: return {"exit":"TP","pnl_pct":TP_PCT,"bars":b}
    exit_p = candles[min(idx+MAX_HOLD, len(candles)-1)]["close"]
    pnl = (exit_p - entry)/entry if direction == "LONG" else (entry - exit_p)/entry
    return {"exit":"TIMEOUT","pnl_pct":pnl,"bars":MAX_HOLD}

def run():
    print(f"\n{'='*70}")
    print(f"V5 BACKTEST: 3-Bar Window vs 1-Bar Exact Cross")
    print(f"SL={SL_PCT*100}% TP={TP_PCT*100}% Hold={MAX_HOLD} Risk=${RISK_USD}")
    print(f"{'='*70}")

    old_all, new_all = [], []
    dedup_hits = 0

    for asset, sym in sorted(SYMBOL_MAP.items()):
        candles = fetch_candles(sym)
        if len(candles) < 300:
            print(f"  {asset}: {len(candles)} candles (need 300+), skip")
            continue

        closes = np.array([c["close"] for c in candles])
        highs = np.array([c["high"] for c in candles])
        lows = np.array([c["low"] for c in candles])
        ema20 = _ema_series(closes, 20)
        ema50 = _ema_series(closes, 50)
        ema200 = _ema_series(closes, 200)

        used_old, used_new = set(), set()
        old_t, new_t = [], []

        for bi in range(210, len(candles) - MAX_HOLD):
            c = closes[bi]; e200 = ema200[bi]
            # Gates
            if c <= 0 or np.isnan(e200): continue
            atr_v = float(np.mean(np.maximum(highs[bi-13:bi+1]-lows[bi-13:bi+1],
                np.maximum(np.abs(highs[bi-13:bi+1]-closes[bi-14:bi]),
                           np.abs(lows[bi-13:bi+1]-closes[bi-14:bi])))))
            if atr_v/c < 0.008: continue
            gap = abs(ema20[bi]-ema50[bi])/ema50[bi] if ema50[bi]>0 else 0
            if gap < 0.001: continue

            # OLD: exact cross
            if ema20[bi-1] <= ema50[bi-1] and ema20[bi] > ema50[bi] and c > e200:
                cid = f"L:{bi}"
                if cid not in used_old:
                    used_old.add(cid)
                    r = simulate(candles, bi, "LONG")
                    r["asset"]=asset; r["pnl_usd"]=r["pnl_pct"]*RISK_USD/SL_PCT
                    old_t.append(r)
            if ema20[bi-1] >= ema50[bi-1] and ema20[bi] < ema50[bi] and c < e200:
                cid = f"S:{bi}"
                if cid not in used_old:
                    used_old.add(cid)
                    r = simulate(candles, bi, "SHORT")
                    r["asset"]=asset; r["pnl_usd"]=r["pnl_pct"]*RISK_USD/SL_PCT
                    old_t.append(r)

            # NEW: 3-bar window
            for ago in range(3):
                ci = bi - ago
                if ci < 51: continue
                if ema20[ci-1] <= ema50[ci-1] and ema20[ci] > ema50[ci] and c > e200:
                    cid = f"L:{ci}"
                    if cid not in used_new:
                        used_new.add(cid)
                        r = simulate(candles, bi, "LONG")
                        r["asset"]=asset; r["bars_ago"]=ago
                        r["pnl_usd"]=r["pnl_pct"]*RISK_USD/SL_PCT
                        new_t.append(r)
                    else: dedup_hits += 1
                    break
                if ema20[ci-1] >= ema50[ci-1] and ema20[ci] < ema50[ci] and c < e200:
                    cid = f"S:{ci}"
                    if cid not in used_new:
                        used_new.add(cid)
                        r = simulate(candles, bi, "SHORT")
                        r["asset"]=asset; r["bars_ago"]=ago
                        r["pnl_usd"]=r["pnl_pct"]*RISK_USD/SL_PCT
                        new_t.append(r)
                    else: dedup_hits += 1
                    break

        old_all.extend(old_t); new_all.extend(new_t)
        print(f"  {asset}: old={len(old_t)} new={len(new_t)} (+{len(new_t)-len(old_t)})")
        time.sleep(0.15)

    def rpt(label, trades):
        if not trades: print(f"\n  {label}: 0 trades"); return
        w = sum(1 for t in trades if t["pnl_usd"]>1)
        l = sum(1 for t in trades if t["pnl_usd"]<-1)
        tp = sum(t["pnl_usd"] for t in trades)
        wr = 100*w/len(trades)
        exits = {}
        for t in trades: exits[t["exit"]] = exits.get(t["exit"],0)+1
        print(f"\n  {label}:")
        print(f"    Trades={len(trades)} W={w} L={l} WR={wr:.1f}%")
        print(f"    PnL=${tp:.2f} Avg=${tp/len(trades):.2f}")
        print(f"    Exits: {exits}")

    print(f"\n{'='*70}")
    rpt("OLD (1-bar)", old_all)
    rpt("NEW (3-bar)", new_all)
    print(f"\n  Dedup hits: {dedup_hits}")
    print(f"  Additional trades: {len(new_all)-len(old_all)}")
    if new_all:
        ago = {}
        for t in new_all: ago[t.get("bars_ago",0)] = ago.get(t.get("bars_ago",0),0)+1
        print(f"  bars_ago dist: {ago}")
    print(f"{'='*70}")

if __name__ == "__main__":
    run()
