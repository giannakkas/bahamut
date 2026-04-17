"""
Bahamut v5 — Clean backtester using validated signal.
EMA20×50 cross in bull regime. Simple. Honest.
"""
import numpy as np
from uuid import uuid4
from bahamut.features.indicators import compute_indicators
from bahamut.alpha.signal_engine import generate_signal

class V5Engine:
    def __init__(self, sl_pct=0.08, tp_pct=0.16, max_hold=30,
                 risk_pct=0.02, initial=100000, slippage_bps=8, spread_bps=12,
                 commission_rate=0.0004, warmup=250):
        self.sl_pct = sl_pct
        self.tp_pct = tp_pct
        self.max_hold = max_hold
        self.risk_pct = risk_pct
        self.balance = initial
        self.initial = initial
        self.slippage_bps = slippage_bps
        self.spread_bps = spread_bps
        self.commission_rate = commission_rate
        self.warmup = warmup
        self.trades = []
        self.equity = []
        self.peak = initial

    def run(self, candles):
        open_trade = None
        prev_ind = None

        for i in range(self.warmup, len(candles)):
            candle = candles[i]
            ind = compute_indicators(candles[:i+1])
            if not ind:
                continue

            close = ind["close"]

            # ── CHECK OPEN TRADE ──
            if open_trade:
                t = open_trade
                bars = i - t["entry_idx"]

                hit_sl = hit_tp = False
                if t["direction"] == "LONG":
                    hit_sl = candle["low"] <= t["sl"]
                    hit_tp = candle["high"] >= t["tp"]
                else:
                    hit_sl = candle["high"] >= t["sl"]
                    hit_tp = candle["low"] <= t["tp"]

                exit_price = reason = None
                if hit_sl and hit_tp:
                    exit_price, reason = t["sl"], "SL"  # Worst case
                elif hit_sl:
                    exit_price, reason = t["sl"], "SL"
                elif hit_tp:
                    exit_price, reason = t["tp"], "TP"
                elif bars >= self.max_hold:
                    exit_price, reason = close, "TIMEOUT"

                if exit_price is not None:
                    if t["direction"] == "LONG":
                        pnl_pct = (exit_price - t["entry"]) / t["entry"]
                    else:
                        pnl_pct = (t["entry"] - exit_price) / t["entry"]

                    sl_frac = abs(t["entry"] - t["sl"]) / t["entry"]
                    pos = (self.balance * self.risk_pct) / sl_frac if sl_frac > 0 else 0
                    pnl = pos * pnl_pct

                    # Commission: entry + exit notional
                    commission = (pos + pos * (1 + pnl_pct)) * self.commission_rate
                    pnl -= commission

                    # MFE/MAE from bars held
                    mfe = mae = 0
                    for j in range(t["entry_idx"]+1, i+1):
                        c = candles[j]
                        if t["direction"] == "LONG":
                            mfe = max(mfe, c["high"] - t["entry"])
                            mae = max(mae, t["entry"] - c["low"])
                        else:
                            mfe = max(mfe, t["entry"] - c["low"])
                            mae = max(mae, c["high"] - t["entry"])

                    self.balance += pnl
                    self.trades.append({
                        "direction": t["direction"], "entry": t["entry"],
                        "exit": exit_price, "reason": reason,
                        "pnl": round(pnl, 2), "pnl_pct": round(pnl_pct, 4),
                        "bars": bars, "signal_type": t.get("signal_type", ""),
                        "mfe": mfe, "mae": mae,
                        "mfe_r": mfe / (sl_frac * t["entry"]) if sl_frac > 0 else 0,
                        "mae_r": mae / (sl_frac * t["entry"]) if sl_frac > 0 else 0,
                    })
                    open_trade = None

            # ── GENERATE SIGNAL ──
            if open_trade is None and prev_ind is not None:
                sig = generate_signal(candles[:i+1], ind, prev_ind)

                if sig.valid and i + 1 < len(candles):
                    next_open = candles[i+1]["open"]
                    slip = next_open * (self.slippage_bps / 10000)
                    spread = next_open * (self.spread_bps / 10000)

                    if sig.direction == "LONG":
                        entry = next_open + slip + spread/2
                        sl = entry * (1 - sig.sl_pct)
                        tp = entry * (1 + sig.tp_pct)
                    else:
                        entry = next_open - slip - spread/2
                        sl = entry * (1 + sig.sl_pct)
                        tp = entry * (1 - sig.tp_pct)

                    open_trade = {
                        "direction": sig.direction,
                        "entry": round(entry, 2),
                        "sl": round(sl, 2),
                        "tp": round(tp, 2),
                        "entry_idx": i + 1,
                        "signal_type": sig.signal_type,
                    }

            # ── EQUITY ──
            self.peak = max(self.peak, self.balance)
            dd = 1 - self.balance / self.peak if self.peak > 0 else 0
            self.equity.append({"idx": i, "balance": round(self.balance, 2),
                               "dd": round(dd, 4)})

            prev_ind = ind

        # Force close
        if open_trade and candles:
            close = candles[-1]["close"]
            t = open_trade
            if t["direction"] == "LONG":
                pnl_pct = (close - t["entry"]) / t["entry"]
            else:
                pnl_pct = (t["entry"] - close) / t["entry"]
            sf = abs(t["entry"] - t["sl"]) / t["entry"]
            pos = (self.balance * self.risk_pct) / sf if sf > 0 else 0
            self.balance += pos * pnl_pct
            self.trades.append({"direction": t["direction"], "entry": t["entry"],
                "exit": close, "reason": "END", "pnl": round(pos*pnl_pct, 2),
                "pnl_pct": round(pnl_pct, 4), "bars": 0, "mfe": 0, "mae": 0,
                "mfe_r": 0, "mae_r": 0, "signal_type": t.get("signal_type","")})

        return self.metrics()

    def metrics(self):
        trades = self.trades
        if not trades:
            return {"total_trades": 0, "total_return_pct": 0, "sharpe_ratio": 0,
                    "max_drawdown": 0, "win_rate": 0, "profit_factor": 0,
                    "expectancy": 0, "mfe_mae_ratio": 0}

        wins = [t for t in trades if t["pnl"] > 0]
        losses = [t for t in trades if t["pnl"] <= 0]
        pnls = [t["pnl"] for t in trades]
        ret = (self.balance - self.initial) / self.initial * 100
        max_dd = max((e["dd"] for e in self.equity), default=0)

        r = np.array(pnls) / self.initial
        sh = float(np.mean(r) / (np.std(r) + 1e-10) * np.sqrt(len(r))) if len(r) > 1 else 0

        gp = sum(t["pnl"] for t in wins) if wins else 0
        gl = abs(sum(t["pnl"] for t in losses)) if losses else 1
        pf = gp / gl if gl > 0 else 0

        aw = float(np.mean([t["pnl"] for t in wins])) if wins else 0
        al = float(abs(np.mean([t["pnl"] for t in losses]))) if losses else 0
        wr = len(wins) / len(trades)
        exp = (wr * aw) - ((1 - wr) * al)

        mfe_rs = [t["mfe_r"] for t in trades if t["mfe_r"] > 0]
        mae_rs = [t["mae_r"] for t in trades if t["mae_r"] > 0]
        avg_mfe = float(np.mean(mfe_rs)) if mfe_rs else 0
        avg_mae = float(np.mean(mae_rs)) if mae_rs else 0

        longs = [t for t in trades if t["direction"] == "LONG"]
        shorts = [t for t in trades if t["direction"] == "SHORT"]

        exit_r = {}
        for t in trades:
            r_name = t["reason"]
            if r_name not in exit_r:
                exit_r[r_name] = {"count": 0, "wins": 0, "pnl": 0}
            exit_r[r_name]["count"] += 1
            if t["pnl"] > 0: exit_r[r_name]["wins"] += 1
            exit_r[r_name]["pnl"] += t["pnl"]

        return {
            "total_trades": len(trades), "wins": len(wins), "losses": len(losses),
            "win_rate": round(wr, 4),
            "avg_win": round(aw, 2), "avg_loss": round(al, 2),
            "profit_factor": round(pf, 3), "expectancy": round(exp, 2),
            "sharpe_ratio": round(sh, 3), "max_drawdown": round(max_dd, 4),
            "total_return_pct": round(ret, 2), "final_balance": round(self.balance, 2),
            "avg_mfe_r": round(avg_mfe, 3), "avg_mae_r": round(avg_mae, 3),
            "mfe_mae_ratio": round(avg_mfe / max(0.001, avg_mae), 3),
            "long_trades": len(longs), "short_trades": len(shorts),
            "long_pnl": round(sum(t["pnl"] for t in longs), 2),
            "short_pnl": round(sum(t["pnl"] for t in shorts), 2),
            "exit_reasons": exit_r,
        }
