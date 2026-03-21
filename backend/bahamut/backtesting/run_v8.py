"""
Bahamut v8 — Multi-Regime Backtester

Runs regime detection on each bar, routes to the appropriate strategy,
and tracks performance by regime and strategy.

Usage:
    python -m bahamut.backtesting.run_v8
"""
import numpy as np
import warnings
import os

warnings.filterwarnings("ignore")
os.environ.setdefault("STRUCTLOG_LEVEL", "ERROR")
import structlog
structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(40))

from bahamut.features.indicators import compute_indicators
from bahamut.regime.v8_detector import detect_regime
from bahamut.strategies.v5_base import V5Base
from bahamut.strategies.v5_tuned import V5Tuned
from bahamut.strategies.v8_range import V8Range
from bahamut.strategies.v8_defensive import V8Defensive
from bahamut.backtesting.data_real import generate_realistic_btc


# ── Regime → active strategies mapping ──
REGIME_MAP = {
    "TREND": ["v5_base", "v5_tuned"],
    "RANGE": ["v8_range"],
    "CRASH": [],  # No trading
}


class V8Backtester:
    """Multi-regime backtester with per-strategy sleeves."""

    def __init__(self, total_capital=100000, warmup=250,
                 slippage_bps=8, spread_bps=12):
        self.total = total_capital
        self.warmup = warmup
        self.slip_bps = slippage_bps
        self.spread_bps = spread_bps

        self.strategies = {
            "v5_base": V5Base(),
            "v5_tuned": V5Tuned(),
            "v8_range": V8Range(),
        }

        # Per-strategy tracking
        self.sleeve_balance = {
            "v5_base": total_capital * 0.5,
            "v5_tuned": total_capital * 0.5,
            "v8_range": total_capital * 0.5,  # Gets capital when RANGE
        }
        self.trades = []
        self.regime_log = []
        self.open_trade = {}  # strategy_name → trade dict
        self.peak = total_capital
        self.equity_curve = []

    def run(self, candles):
        prev_ind = None
        pending = {}  # strategy → signal for next-bar entry

        for i in range(self.warmup, len(candles)):
            hist = candles[:i + 1]
            ind = compute_indicators(hist)
            if not ind:
                continue

            close = ind["close"]

            # 1. Detect regime
            regime = detect_regime(ind, hist[-15:])
            active_strats = REGIME_MAP.get(regime.regime, [])

            self.regime_log.append({
                "idx": i, "regime": regime.regime,
                "confidence": regime.confidence,
            })

            # 2. Fill pending orders at this bar's open
            for sname, sig in list(pending.items()):
                if sname not in active_strats:
                    del pending[sname]
                    continue
                if sname in self.open_trade:
                    del pending[sname]
                    continue
                self._fill(sname, sig, candles[i], i)
                del pending[sname]

            # 3. Check open trades for SL/TP/timeout
            bar = candles[i]
            for sname in list(self.open_trade.keys()):
                t = self.open_trade[sname]
                t["bars"] += 1
                closed = self._check_exit(t, bar)
                if closed:
                    self.trades.append(t)
                    del self.open_trade[sname]

            # 4. Evaluate active strategies for signals
            for sname in active_strats:
                if sname in self.open_trade or sname in pending:
                    continue
                strat = self.strategies.get(sname)
                if not strat:
                    continue
                signal = strat.evaluate(hist, ind, prev_ind)
                if signal:
                    pending[sname] = signal

            # 5. Track equity
            total_eq = sum(self.sleeve_balance.values())
            for t in self.open_trade.values():
                if t["dir"] == "LONG":
                    total_eq += (close - t["entry"]) * t["size"]
                else:
                    total_eq += (t["entry"] - close) * t["size"]
            self.peak = max(self.peak, total_eq)
            dd = 1 - total_eq / self.peak if self.peak > 0 else 0
            self.equity_curve.append({"idx": i, "eq": round(total_eq, 2),
                                       "dd": round(dd, 4), "regime": regime.regime})

            prev_ind = ind

        # Force close remaining
        if candles:
            for sname in list(self.open_trade.keys()):
                t = self.open_trade[sname]
                self._close(t, candles[-1]["close"], "END")
                self.trades.append(t)
            self.open_trade.clear()

        return self._compute_metrics()

    def _fill(self, sname, signal, bar, idx):
        meta = self.strategies[sname].meta
        entry = bar["open"]
        slip = entry * (self.slip_bps / 10000)
        spread = entry * (self.spread_bps / 10000)

        if signal.direction == "LONG":
            entry = entry + slip + spread / 2
            sl = entry * (1 - meta.sl_pct)
            tp = entry * (1 + meta.tp_pct)
        else:
            entry = entry - slip - spread / 2
            sl = entry * (1 + meta.sl_pct)
            tp = entry * (1 - meta.tp_pct)

        # Risk-based sizing
        sleeve_eq = self.sleeve_balance.get(sname, 0)
        if sleeve_eq <= 0:
            sleeve_eq = self.total * 0.5  # Fallback
        risk = sleeve_eq * meta.risk_pct
        sl_dist = abs(entry - sl)
        size = risk / sl_dist if sl_dist > 0 else 0

        self.open_trade[sname] = {
            "strategy": sname, "dir": signal.direction,
            "entry": round(entry, 2), "sl": round(sl, 2), "tp": round(tp, 2),
            "size": size, "risk": risk, "entry_idx": idx,
            "bars": 0, "max_hold": meta.max_hold_bars,
            "regime": self.regime_log[-1]["regime"] if self.regime_log else "?",
        }

    def _check_exit(self, t, bar):
        h, l, c = bar["high"], bar["low"], bar["close"]
        if t["dir"] == "LONG":
            sl_hit = l <= t["sl"]
            tp_hit = h >= t["tp"]
        else:
            sl_hit = h >= t["sl"]
            tp_hit = l <= t["tp"]

        if sl_hit and tp_hit:
            self._close(t, t["sl"], "SL")
            return True
        if sl_hit:
            self._close(t, t["sl"], "SL")
            return True
        if tp_hit:
            self._close(t, t["tp"], "TP")
            return True
        if t["bars"] >= t["max_hold"]:
            self._close(t, c, "TIMEOUT")
            return True
        return False

    def _close(self, t, exit_price, reason):
        if t["dir"] == "LONG":
            pnl = (exit_price - t["entry"]) * t["size"]
        else:
            pnl = (t["entry"] - exit_price) * t["size"]
        t["exit"] = round(exit_price, 2)
        t["pnl"] = round(pnl, 2)
        t["reason"] = reason

        sname = t["strategy"]
        if sname in self.sleeve_balance:
            self.sleeve_balance[sname] += pnl

    def _compute_metrics(self):
        trades = self.trades
        if not trades:
            return {"total_trades": 0, "total_return_pct": 0}

        total_pnl = sum(t["pnl"] for t in trades)
        total_eq = sum(self.sleeve_balance.values())
        ret = total_pnl / self.total * 100
        wins = [t for t in trades if t["pnl"] > 0]
        losses = [t for t in trades if t["pnl"] <= 0]
        max_dd = max((e["dd"] for e in self.equity_curve), default=0)

        pnls = [t["pnl"] for t in trades]
        r = np.array(pnls) / self.total
        sh = float(np.mean(r) / (np.std(r) + 1e-10) * np.sqrt(len(r))) if len(r) > 1 else 0

        gp = sum(t["pnl"] for t in wins) if wins else 0
        gl = abs(sum(t["pnl"] for t in losses)) if losses else 1

        # By strategy
        by_strat = {}
        for t in trades:
            s = t["strategy"]
            if s not in by_strat:
                by_strat[s] = {"count": 0, "wins": 0, "pnl": 0}
            by_strat[s]["count"] += 1
            if t["pnl"] > 0: by_strat[s]["wins"] += 1
            by_strat[s]["pnl"] += t["pnl"]

        # By regime
        by_regime = {}
        for t in trades:
            r_name = t.get("regime", "?")
            if r_name not in by_regime:
                by_regime[r_name] = {"count": 0, "wins": 0, "pnl": 0}
            by_regime[r_name]["count"] += 1
            if t["pnl"] > 0: by_regime[r_name]["wins"] += 1
            by_regime[r_name]["pnl"] += t["pnl"]

        # Regime time distribution
        regime_bars = {}
        for entry in self.regime_log:
            r_name = entry["regime"]
            regime_bars[r_name] = regime_bars.get(r_name, 0) + 1
        total_bars = sum(regime_bars.values()) or 1

        return {
            "total_trades": len(trades),
            "wins": len(wins), "losses": len(losses),
            "win_rate": round(len(wins) / len(trades), 4),
            "profit_factor": round(gp / gl, 3) if gl > 0 else 0,
            "sharpe_ratio": round(sh, 3),
            "max_drawdown": round(max_dd, 4),
            "total_return_pct": round(ret, 2),
            "total_pnl": round(total_pnl, 2),
            "by_strategy": by_strat,
            "by_regime": by_regime,
            "regime_distribution": {k: round(v / total_bars * 100, 1)
                                     for k, v in regime_bars.items()},
        }


def run_comparison():
    """Compare v5-only vs v8 multi-regime system."""
    from bahamut.backtesting.replay_v5 import V5Engine

    candles = generate_realistic_btc(seed=42)[:2500]
    bnh = (candles[-1]["close"] / candles[0]["close"] - 1) * 100
    print(f"Data: {len(candles)} candles, ${candles[0]['close']:,.0f} → ${candles[-1]['close']:,.0f}, BnH={bnh:+.0f}%\n")

    def pr(label, m, extra=""):
        bs = m.get("by_strategy", {})
        br = m.get("by_regime", {})
        print(f"  {label:<28} {m.get('total_return_pct',0):>+7.1f}% "
              f"Sh={m.get('sharpe_ratio',0):>5.2f} "
              f"DD={m.get('max_drawdown',0)*100:>5.1f}% "
              f"N={m.get('total_trades',0):>3} "
              f"WR={m.get('win_rate',0)*100:>4.0f}% "
              f"PF={m.get('profit_factor',0):>5.2f} {extra}")

    print(f"{'Config':<28} {'Ret':>8} {'Sh':>7} {'DD%':>6} {'N':>3} {'WR':>5} {'PF':>7}")
    print("─" * 70)

    # v5 base
    m5b = V5Engine(sl_pct=0.08, tp_pct=0.16, max_hold=30).run(candles)
    pr("v5_base", m5b)

    # v5 tuned
    m5t = V5Engine(sl_pct=0.10, tp_pct=0.25, max_hold=60).run(candles)
    pr("v5_tuned", m5t)

    # v8 multi-regime
    bt8 = V8Backtester()
    m8 = bt8.run(candles)
    pr("v8_multi_regime", m8)

    # Breakdown
    print(f"\n--- v8 By Strategy ---")
    for s, d in m8.get("by_strategy", {}).items():
        wr = d["wins"] / max(1, d["count"]) * 100
        print(f"  {s:<14} {d['count']:>3} trades, WR={wr:.0f}%, PnL=${d['pnl']:+,.0f}")

    print(f"\n--- v8 By Regime ---")
    for r, d in m8.get("by_regime", {}).items():
        wr = d["wins"] / max(1, d["count"]) * 100
        print(f"  {r:<10} {d['count']:>3} trades, WR={wr:.0f}%, PnL=${d['pnl']:+,.0f}")

    print(f"\n--- Regime Time Distribution ---")
    for r, pct in m8.get("regime_distribution", {}).items():
        print(f"  {r:<10} {pct:.1f}%")

    return m5b, m5t, m8


def run_multi_seed():
    """Multi-seed validation."""
    from bahamut.backtesting.replay_v5 import V5Engine

    print(f"\n{'Seed':<6} {'BnH':>7} {'v5_base':>8} {'v5_tuned':>9} {'v8':>8} {'v8_N':>5} {'Best':>8}")
    print("─" * 55)

    v5b_all, v5t_all, v8_all = [], [], []
    for seed in [42, 7, 123, 999, 2025]:
        candles = generate_realistic_btc(seed=seed)[:1500]
        bnh = (candles[-1]["close"] / candles[0]["close"] - 1) * 100

        m5b = V5Engine(sl_pct=0.08, tp_pct=0.16, max_hold=30).run(candles)
        m5t = V5Engine(sl_pct=0.10, tp_pct=0.25, max_hold=60).run(candles)
        m8 = V8Backtester().run(candles)

        v5b_all.append(m5b["total_return_pct"])
        v5t_all.append(m5t["total_return_pct"])
        v8_all.append(m8["total_return_pct"])

        rets = {"v5_base": m5b["total_return_pct"], "v5_tuned": m5t["total_return_pct"], "v8": m8["total_return_pct"]}
        best = max(rets, key=rets.get)
        print(f"{seed:<6} {bnh:>+6.0f}% {m5b['total_return_pct']:>+7.1f}% "
              f"{m5t['total_return_pct']:>+8.1f}% {m8['total_return_pct']:>+7.1f}% "
              f"{m8['total_trades']:>5} {best:>8}")

    print(f"\nAvg: v5_base={np.mean(v5b_all):+.1f}%, v5_tuned={np.mean(v5t_all):+.1f}%, v8={np.mean(v8_all):+.1f}%")


if __name__ == "__main__":
    import sys
    args = set(sys.argv[1:])

    if "--all" in args or len(args) == 0:
        print("=" * 70)
        print("  V8 MULTI-REGIME COMPARISON")
        print("=" * 70)
        run_comparison()

        print("\n" + "=" * 60)
        print("  MULTI-SEED VALIDATION")
        print("=" * 60)
        run_multi_seed()

    elif "--seeds" in args:
        run_multi_seed()

    print("\n" + "=" * 60)
