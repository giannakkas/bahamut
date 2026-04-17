"""
Bahamut v6 — Backtester with pyramiding and trend capture.

Base: v5 signal (EMA20×50 cross, bull regime)
Add: pyramid positions, trend-state exits, profit locks
"""
import numpy as np
from uuid import uuid4
from dataclasses import dataclass, field
from typing import Optional

from bahamut.features.indicators import compute_indicators
from bahamut.alpha.signal_engine import generate_signal
from bahamut.alpha.pyramid_engine import check_pyramid
from bahamut.alpha.trend_capture import classify_trend, compute_profit_lock_stop


@dataclass
class V6Config:
    sl_pct: float = 0.08
    tp_pct: float = 0.16
    max_hold: int = 30
    risk_pct: float = 0.02
    initial: float = 100_000.0
    slippage_bps: float = 8.0
    spread_bps: float = 12.0
    commission_rate: float = 0.0004  # 0.04% per side (Binance taker)
    warmup: int = 250
    # Pyramid
    enable_pyramid: bool = True
    max_layers: int = 3
    min_profit_r_for_add: float = 1.0  # Min R before first add allowed
    # Trend capture
    enable_trend_capture: bool = True
    # Profit lock
    enable_profit_lock: bool = True
    # Trailing (delayed)
    enable_trailing: bool = True
    trail_atr_mult: float = 2.5
    trail_min_r: float = 2.0       # Don't trail until 2R profit


@dataclass
class Position:
    """A single layer in a position."""
    layer_id: str
    layer_num: int        # 0=base, 1=first add, 2=second add
    entry_price: float
    stop_loss: float
    original_sl: float
    size_fraction: float  # 1.0, 0.5, 0.25
    entry_idx: int
    add_type: str = "base"

    @property
    def sl_distance(self):
        return abs(self.entry_price - self.original_sl)


class V6Engine:
    def __init__(self, config: V6Config = None):
        self.cfg = config or V6Config()
        self.balance = self.cfg.initial
        self.peak = self.cfg.initial
        self.trades = []
        self.equity = []
        # Active position state
        self.layers: list[Position] = []
        self.base_entry: float = 0
        self.base_direction: str = ""
        self.base_entry_idx: int = 0
        self.base_sl_distance: float = 0
        self.base_tp: float = 0
        self.add_on_pnl: float = 0  # Track add-on contribution

    def run(self, candles: list) -> dict:
        cfg = self.cfg
        prev_ind = None
        pending_signal = None
        all_candles = candles

        for i in range(cfg.warmup, len(candles)):
            candle = candles[i]
            ind = compute_indicators(candles[:i + 1])
            if not ind:
                continue

            close = ind["close"]
            atr = ind.get("atr_14", close * 0.02)

            # ── EXECUTE PENDING SIGNAL ──
            if pending_signal is not None:
                self._open_base(pending_signal, candle, ind, i)
                pending_signal = None

            # ── MANAGE OPEN POSITION ──
            if self.layers:
                self._manage_position(candle, i, ind, candles)

                # ── CHECK PYRAMID ──
                if cfg.enable_pyramid and self.layers and self.base_entry > 0:
                    n_layers = len(self.layers)
                    profit_r = (close - self.base_entry) / self.base_sl_distance \
                        if self.base_sl_distance > 0 else 0

                    if profit_r >= cfg.min_profit_r_for_add and n_layers < cfg.max_layers:
                        psig = check_pyramid(
                            trade_entry=self.base_entry,
                            trade_direction="LONG",
                            current_price=close,
                            current_layers=n_layers,
                            indicators=ind,
                            candles=candles[max(0, i - 25):i + 1],
                            max_layers=cfg.max_layers,
                        )
                        if psig.should_add:
                            self._add_layer(psig, candle, ind, i)

            # ── GENERATE NEW SIGNAL (only if no position open) ──
            if not self.layers and prev_ind is not None:
                sig = generate_signal(candles[:i + 1], ind, prev_ind)
                if sig.valid and sig.direction == "LONG" and i + 1 < len(candles):
                    pending_signal = sig

            # ── EQUITY ──
            unrealized = self._calc_unrealized(close)
            eq = self.balance + unrealized
            self.peak = max(self.peak, eq)
            dd = 1 - eq / self.peak if self.peak > 0 else 0
            self.equity.append({"idx": i, "eq": round(eq, 2), "dd": round(dd, 4)})

            prev_ind = ind

        # Force close
        if self.layers and candles:
            self._close_all(candles[-1]["close"], len(candles) - 1, "END")

        return self._metrics()

    # ═══════════════════════════════════════════════════════
    # POSITION MANAGEMENT
    # ═══════════════════════════════════════════════════════

    def _open_base(self, sig, candle, ind, idx):
        cfg = self.cfg
        entry = candle["open"]
        slip = entry * (cfg.slippage_bps / 10000)
        spread = entry * (cfg.spread_bps / 10000)
        entry = entry + slip + spread / 2

        sl = entry * (1 - cfg.sl_pct)
        tp = entry * (1 + cfg.tp_pct)

        self.base_entry = entry
        self.base_direction = "LONG"
        self.base_entry_idx = idx
        self.base_sl_distance = entry - sl
        self.base_tp = tp

        layer = Position(
            layer_id=str(uuid4())[:6], layer_num=0,
            entry_price=round(entry, 2), stop_loss=round(sl, 2),
            original_sl=round(sl, 2), size_fraction=1.0,
            entry_idx=idx, add_type="base",
        )
        self.layers = [layer]

    def _add_layer(self, psig, candle, ind, idx):
        entry = candle["close"]
        slip = entry * (self.cfg.slippage_bps / 10000)
        entry = entry + slip

        sl = psig.stop_level if psig.stop_level > 0 else entry * (1 - self.cfg.sl_pct * 0.7)
        # Add-on SL is tighter than base

        layer = Position(
            layer_id=str(uuid4())[:6], layer_num=len(self.layers),
            entry_price=round(entry, 2), stop_loss=round(sl, 2),
            original_sl=round(sl, 2), size_fraction=round(psig.size_fraction, 2),
            entry_idx=idx, add_type=psig.add_type,
        )
        self.layers.append(layer)

    def _manage_position(self, candle, idx, ind, all_candles):
        cfg = self.cfg
        high, low, close = candle["high"], candle["low"], candle["close"]
        atr = ind.get("atr_14", close * 0.02)

        bars_held = idx - self.base_entry_idx
        profit_r = (close - self.base_entry) / self.base_sl_distance \
            if self.base_sl_distance > 0 else 0

        # ── TREND CAPTURE STATE ──
        trend_state = None
        if cfg.enable_trend_capture and self.base_sl_distance > 0:
            candles_since = all_candles[self.base_entry_idx:idx + 1]
            trend_state = classify_trend(
                self.base_entry, close, self.base_sl_distance,
                ind, bars_held, candles_since,
            )

        # ── PROFIT LOCK ──
        if cfg.enable_profit_lock and trend_state and trend_state.profit_lock_r > 0:
            lock_stop = compute_profit_lock_stop(
                self.base_entry, self.base_sl_distance, trend_state.profit_lock_r)
            if lock_stop > 0:
                for layer in self.layers:
                    if lock_stop > layer.stop_loss:
                        layer.stop_loss = round(lock_stop, 2)

        # ── DELAYED TRAILING ──
        if cfg.enable_trailing and profit_r >= cfg.trail_min_r:
            # Only trail if trend state allows it
            should_trail = True
            if trend_state and trend_state.state == "EARLY_TREND":
                should_trail = False  # Don't trail too early

            if should_trail:
                trail_stop = close - atr * cfg.trail_atr_mult
                for layer in self.layers:
                    if trail_stop > layer.stop_loss:
                        layer.stop_loss = round(trail_stop, 2)

        # ── EXTENDED TREND TIGHTENING ──
        if trend_state and trend_state.tighten_stop:
            tight = close - atr * 1.5  # Tighter trail for extended trends
            for layer in self.layers:
                if tight > layer.stop_loss:
                    layer.stop_loss = round(tight, 2)

        # ── CHECK SL/TP PER LAYER ──
        layers_to_close = []
        for layer in self.layers:
            sl_hit = low <= layer.stop_loss
            tp_hit = high >= self.base_tp

            if sl_hit and tp_hit:
                layers_to_close.append((layer, layer.stop_loss, "SL"))
            elif sl_hit:
                layers_to_close.append((layer, layer.stop_loss, "SL"))
            elif tp_hit:
                layers_to_close.append((layer, self.base_tp, "TP"))

        for layer, price, reason in layers_to_close:
            self._close_layer(layer, price, idx, reason)

        # ── TIMEOUT ──
        if bars_held >= cfg.max_hold and self.layers:
            self._close_all(close, idx, "TIMEOUT")

        # ── Check if add-on SL hit but base still alive ──
        # (handled above per-layer)

    def _close_layer(self, layer, exit_price, idx, reason):
        pnl_pct = (exit_price - layer.entry_price) / layer.entry_price
        risk = self.balance * self.cfg.risk_pct
        sl_frac = abs(layer.entry_price - layer.original_sl) / layer.entry_price
        pos = (risk / sl_frac * layer.size_fraction) if sl_frac > 0 else 0
        pnl = pos * pnl_pct

        # Commission: charged on entry + exit notional
        commission = (pos + pos * (1 + pnl_pct)) * self.cfg.commission_rate
        pnl -= commission

        self.balance += pnl

        # Track MFE/MAE would need candle history - skip for speed
        self.trades.append({
            "direction": "LONG", "layer": layer.layer_num,
            "add_type": layer.add_type,
            "entry": layer.entry_price, "exit": round(exit_price, 2),
            "reason": reason, "pnl": round(pnl, 2),
            "pnl_pct": round(pnl_pct, 4),
            "size_fraction": layer.size_fraction,
            "bars": idx - layer.entry_idx,
        })

        if layer.layer_num > 0:
            self.add_on_pnl += pnl

        if layer in self.layers:
            self.layers.remove(layer)

        # If no layers left, reset
        if not self.layers:
            self.base_entry = 0
            self.base_direction = ""

    def _close_all(self, price, idx, reason):
        for layer in list(self.layers):
            self._close_layer(layer, price, idx, reason)

    def _calc_unrealized(self, price):
        total = 0
        for layer in self.layers:
            pnl_pct = (price - layer.entry_price) / layer.entry_price
            sf = abs(layer.entry_price - layer.original_sl) / layer.entry_price
            if sf > 0:
                pos = self.balance * self.cfg.risk_pct / sf * layer.size_fraction
                total += pos * pnl_pct
        return total

    # ═══════════════════════════════════════════════════════
    # METRICS
    # ═══════════════════════════════════════════════════════

    def _metrics(self):
        trades = self.trades
        if not trades:
            return {"total_trades": 0, "total_return_pct": 0, "sharpe_ratio": 0,
                    "max_drawdown": 0, "win_rate": 0, "profit_factor": 0,
                    "expectancy": 0}

        wins = [t for t in trades if t["pnl"] > 0]
        losses = [t for t in trades if t["pnl"] <= 0]
        pnls = [t["pnl"] for t in trades]
        ret = (self.balance - self.cfg.initial) / self.cfg.initial * 100
        max_dd = max((e["dd"] for e in self.equity), default=0)

        r = np.array(pnls) / self.cfg.initial
        # Sharpe: annualized using equity curve returns, not sqrt(trade_count)
        # Previous: sqrt(len(r)) made Sharpe grow with trade count (meaningless)
        # Now: estimate trades per year from average bars held × bar duration
        avg_bars_held = np.mean([t.get("bars", 10) for t in trades]) if trades else 10
        # Estimate bar duration: 4H = 6/day, but we don't know interval here
        # Use equity curve if available; fallback to trade-based with 252-day year
        if len(self.equity) > 20:
            # Daily-ish equity returns (sample every ~6 equity points for 4H bars)
            step = max(1, len(self.equity) // 60)  # ~60 samples
            eq_vals = [e["equity"] for e in self.equity[::step]]
            eq_returns = np.diff(eq_vals) / np.array(eq_vals[:-1])
            sh = float(np.mean(eq_returns) / (np.std(eq_returns) + 1e-10) * np.sqrt(252)) if len(eq_returns) > 1 else 0
        else:
            # Fallback: assume ~120 trades/year for 3-day avg hold
            trades_per_year = min(252, max(12, 365 / max(1, avg_bars_held * 4 / 24)))
            sh = float(np.mean(r) / (np.std(r) + 1e-10) * np.sqrt(trades_per_year)) if len(r) > 1 else 0

        gp = sum(t["pnl"] for t in wins) if wins else 0
        gl = abs(sum(t["pnl"] for t in losses)) if losses else 1
        pf = gp / gl if gl > 0 else 0

        aw = float(np.mean([t["pnl"] for t in wins])) if wins else 0
        al = float(abs(np.mean([t["pnl"] for t in losses]))) if losses else 0
        wr = len(wins) / len(trades)
        exp = (wr * aw) - ((1 - wr) * al)

        # Base vs add-on breakdown
        base_trades = [t for t in trades if t["layer"] == 0]
        addon_trades = [t for t in trades if t["layer"] > 0]
        base_pnl = sum(t["pnl"] for t in base_trades)
        addon_pnl = sum(t["pnl"] for t in addon_trades)

        # Exit reasons
        exit_r = {}
        for t in trades:
            r_name = t["reason"]
            if r_name not in exit_r:
                exit_r[r_name] = {"count": 0, "wins": 0, "pnl": 0}
            exit_r[r_name]["count"] += 1
            if t["pnl"] > 0: exit_r[r_name]["wins"] += 1
            exit_r[r_name]["pnl"] += t["pnl"]

        # Add-on types
        addon_types = {}
        for t in addon_trades:
            at = t.get("add_type", "?")
            if at not in addon_types:
                addon_types[at] = {"count": 0, "wins": 0, "pnl": 0}
            addon_types[at]["count"] += 1
            if t["pnl"] > 0: addon_types[at]["wins"] += 1
            addon_types[at]["pnl"] += t["pnl"]

        return {
            "total_trades": len(trades),
            "base_trades": len(base_trades),
            "addon_trades": len(addon_trades),
            "wins": len(wins), "losses": len(losses),
            "win_rate": round(wr, 4),
            "avg_win": round(aw, 2), "avg_loss": round(al, 2),
            "profit_factor": round(pf, 3),
            "expectancy": round(exp, 2),
            "sharpe_ratio": round(sh, 3),
            "max_drawdown": round(max_dd, 4),
            "total_return_pct": round(ret, 2),
            "final_balance": round(self.balance, 2),
            "base_pnl": round(base_pnl, 2),
            "addon_pnl": round(addon_pnl, 2),
            "addon_pnl_pct": round(addon_pnl / max(1, abs(base_pnl + addon_pnl)) * 100, 1) if (base_pnl + addon_pnl) != 0 else 0,
            "exit_reasons": exit_r,
            "addon_types": addon_types,
        }
