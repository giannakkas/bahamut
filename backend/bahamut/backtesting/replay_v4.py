"""
Bahamut v4 — Enhanced Replay Engine

Integrates:
- Structure engine (market structure analysis per bar)
- Entry engine (entry quality scoring, type classification)
- Exit engine (trailing stops, break-even, partial TP, momentum exit)
- Trade manager (state machine with MFE/MAE tracking)

Preserves v2 baseline signal generation.
v4 layers are additive — they improve entry timing and exit management.
"""
import numpy as np
from uuid import uuid4
from dataclasses import dataclass, field
from typing import Optional
import structlog

from bahamut.features.indicators import compute_indicators
from bahamut.alpha.structure_engine import analyze_structure, StructureResult
from bahamut.alpha.entry_engine import score_entry, EntryQuality
from bahamut.alpha.exit_engine import evaluate_exit, ExitDecision
from bahamut.alpha.trade_manager import (
    ManagedTrade, STATE_NEW, STATE_OPEN, STATE_PARTIAL,
    STATE_BREAKEVEN, STATE_TRAILING, STATE_CLOSED
)

logger = structlog.get_logger()


@dataclass
class V4Config:
    asset: str = "BTCUSD"
    asset_class: str = "crypto"
    timeframe: str = "4H"
    initial_balance: float = 100_000.0
    risk_per_trade_pct: float = 2.0
    sl_atr_mult: float = 2.0
    tp_atr_mult: float = 3.0
    max_hold_candles: int = 12
    max_concurrent: int = 3
    slippage_bps: float = 5.0
    spread_bps: float = 10.0
    min_candles_warmup: int = 200
    # v4 feature flags
    enable_structure: bool = True
    enable_entry_engine: bool = True
    enable_exit_engine: bool = True
    enable_trailing: bool = True
    enable_partial_tp: bool = True
    enable_breakeven: bool = True


@dataclass
class V4Result:
    config: V4Config
    trades: list
    metrics: dict
    equity_curve: list
    signals: list


class V4ReplayEngine:
    """v4 backtesting engine with alpha layers."""

    def __init__(self, config: V4Config):
        self.config = config
        self.balance = config.initial_balance
        self.peak_balance = config.initial_balance
        self.open_trades: list[ManagedTrade] = []
        self.closed_trades: list[ManagedTrade] = []
        self.equity_curve: list[dict] = []
        self.signals: list[dict] = []
        self._all_candles: list[dict] = []

    def run(self, candles: list[dict]) -> V4Result:
        cfg = self.config
        self._all_candles = candles

        if len(candles) < cfg.min_candles_warmup + 10:
            raise ValueError(f"Need {cfg.min_candles_warmup + 10}+ candles")

        for i in range(cfg.min_candles_warmup, len(candles)):
            candle = candles[i]
            history = candles[:i + 1]

            # 1. Indicators
            indicators = compute_indicators(history)
            if not indicators:
                continue

            # 2. Structure analysis (v4)
            structure = None
            if cfg.enable_structure:
                structure = analyze_structure(history[-50:], indicators, lookback=40)

            # 3. Manage open trades (exits, trailing, partial TP)
            self._manage_trades(candle, i, indicators, structure, history)

            # 4. Generate v2 directional signal
            signal = self._generate_v2_signal(indicators, history[-30:])

            # 5. Entry quality scoring (v4)
            entry_q = None
            if cfg.enable_entry_engine and signal["direction"] in ("LONG", "SHORT"):
                entry_q = score_entry(signal["direction"], indicators,
                                      structure, history[-25:])
                # Apply entry quality adjustments
                signal["confidence"] = min(0.95, max(0.1,
                    signal["confidence"] + entry_q.confidence_adjustment))
                signal["entry_type"] = entry_q.entry_type
                signal["entry_quality"] = entry_q.entry_quality
                signal["size_adjustment"] = entry_q.size_adjustment
                # Re-evaluate decision after confidence adjustment
                if signal["confidence"] >= 0.65 and signal["direction"] != "NO_TRADE":
                    signal["decision"] = "STRONG_SIGNAL"
                elif signal["confidence"] >= 0.50 and signal["direction"] != "NO_TRADE":
                    signal["decision"] = "SIGNAL"
                else:
                    signal["decision"] = "NO_TRADE"
            else:
                signal["entry_type"] = "momentum"
                signal["entry_quality"] = 0.5
                signal["size_adjustment"] = 1.0

            # 6. Execute
            if signal["decision"] in ("SIGNAL", "STRONG_SIGNAL"):
                if len(self.open_trades) < cfg.max_concurrent:
                    existing = [t for t in self.open_trades
                                if t.direction == signal["direction"]]
                    if not existing:
                        # Delay entry if entry engine says so (skip this bar)
                        if entry_q and entry_q.should_delay_entry:
                            pass  # Don't enter — wait for next bar
                        else:
                            self._open_trade(signal, indicators, i)

            # 7. Equity
            unrealized = self._calc_unrealized(candle["close"])
            equity = self.balance + unrealized
            self.peak_balance = max(self.peak_balance, equity)
            self.equity_curve.append({
                "candle_idx": i, "close": candle["close"],
                "equity": round(equity, 2), "balance": round(self.balance, 2),
                "drawdown": round(1 - equity / self.peak_balance, 4) if self.peak_balance > 0 else 0,
            })

        # Force close remaining
        if candles:
            last = candles[-1]
            for t in list(self.open_trades):
                self._close_trade(t, last["close"], len(candles) - 1, "END_OF_DATA")

        metrics = self._compute_metrics()
        return V4Result(
            config=cfg,
            trades=[t.to_dict() for t in self.closed_trades],
            metrics=metrics,
            equity_curve=self.equity_curve,
            signals=self.signals,
        )

    # ═══════════════════════════════════════════════════════════
    # V2 SIGNAL GENERATION (preserved exactly)
    # ═══════════════════════════════════════════════════════════

    def _generate_v2_signal(self, indicators: dict, recent_candles: list) -> dict:
        """Pure v2 directional scoring — no regime filtering."""
        close = indicators.get("close", 0)
        rsi = indicators.get("rsi_14", 50)
        macd_hist = indicators.get("macd_histogram", 0)
        adx = indicators.get("adx_14", 20)
        ema_20 = indicators.get("ema_20", 0)
        ema_50 = indicators.get("ema_50", 0)
        ema_200 = indicators.get("ema_200", 0)
        atr = indicators.get("atr_14", 0)
        stoch_k = indicators.get("stoch_k", 50)
        bb_upper = indicators.get("bollinger_upper", close)
        bb_lower = indicators.get("bollinger_lower", close)

        score = 0

        # Market structure
        if recent_candles and len(recent_candles) >= 10:
            highs = [c.get("high", c.get("close", 0)) for c in recent_candles]
            lows = [c.get("low", c.get("close", 0)) for c in recent_candles]
            sh, sl_pts = [], []
            for j in range(1, len(highs) - 1):
                if highs[j] > highs[j-1] and highs[j] > highs[j+1]:
                    sh.append(highs[j])
                if lows[j] < lows[j-1] and lows[j] < lows[j+1]:
                    sl_pts.append(lows[j])
            if len(sh) >= 2 and len(sl_pts) >= 2:
                if sh[-1] > sh[-2] and sl_pts[-1] > sl_pts[-2]: score += 20
                elif sh[-1] < sh[-2] and sl_pts[-1] < sl_pts[-2]: score -= 20

        # EMA
        if close > 0 and ema_20 > 0 and ema_50 > 0 and ema_200 > 0:
            if close > ema_20 > ema_50 > ema_200: score += 20
            elif close < ema_20 < ema_50 < ema_200: score -= 20
            else:
                if close > ema_200: score += 5
                else: score -= 5
                if close > ema_50: score += 5
                else: score -= 5
                if close > ema_20: score += 5
                else: score -= 5

        # RSI
        if rsi > 65: score += 10
        elif rsi < 35: score -= 10

        # Exhaustion
        if score > 15 and rsi > 75 and stoch_k > 85: score -= 10
        elif score < -15 and rsi < 25 and stoch_k < 15: score += 10

        # MACD
        if macd_hist > 0: score += 10
        elif macd_hist < 0: score -= 10

        # ADX
        if adx > 25: score = int(score * 1.10)
        elif adx < 15: score = int(score * 0.85)

        # Stochastic timing
        if stoch_k > 80 and score > 0: score -= 5
        elif stoch_k < 20 and score < 0: score += 5

        # Direction + confidence
        neutral_zone = 15
        if score > neutral_zone:
            direction = "LONG"
            confidence = min(0.90, 0.45 + (score / 120) * 0.45)
        elif score < -neutral_zone:
            direction = "SHORT"
            confidence = min(0.90, 0.45 + (abs(score) / 120) * 0.45)
        else:
            direction = "NO_TRADE"
            confidence = 0.25

        if confidence >= 0.65 and direction != "NO_TRADE":
            decision = "STRONG_SIGNAL"
        elif confidence >= 0.50 and direction != "NO_TRADE":
            decision = "SIGNAL"
        else:
            decision = "NO_TRADE"

        sig = {
            "direction": direction, "confidence": confidence,
            "decision": decision, "score": score, "atr": atr,
        }
        self.signals.append(sig)
        return sig

    # ═══════════════════════════════════════════════════════════
    # TRADE MANAGEMENT (v4 exit engine integration)
    # ═══════════════════════════════════════════════════════════

    def _manage_trades(self, candle: dict, candle_idx: int,
                       indicators: dict, structure, history: list):
        """Check exits + v4 exit intelligence for all open trades."""
        high, low, close = candle["high"], candle["low"], candle["close"]
        cfg = self.config

        for trade in list(self.open_trades):
            trade.bars_held = candle_idx - trade.entry_time

            # Update MFE / MAE
            if trade.direction == "LONG":
                fav = high - trade.entry_price
                adv = trade.entry_price - low
            else:
                fav = trade.entry_price - low
                adv = high - trade.entry_price

            trade.mfe = max(trade.mfe, fav)
            trade.mae = max(trade.mae, adv)
            if trade.sl_distance > 0:
                trade.mfe_r = trade.mfe / trade.sl_distance
                trade.mae_r = trade.mae / trade.sl_distance

            # ── v4 Exit Engine ──
            if cfg.enable_exit_engine:
                candles_since = self._all_candles[trade.entry_time:candle_idx + 1]
                exit_decision = evaluate_exit(
                    trade=trade.to_dict(),
                    candle=candle,
                    indicators=indicators,
                    candles_since_entry=candles_since,
                    structure=structure,
                )

                # Apply break-even
                if cfg.enable_breakeven and exit_decision.move_to_breakeven:
                    if exit_decision.new_stop_loss > 0:
                        if trade.direction == "LONG" and exit_decision.new_stop_loss > trade.stop_loss:
                            trade.stop_loss = exit_decision.new_stop_loss
                            if trade.state in (STATE_NEW, STATE_OPEN):
                                trade.state = STATE_BREAKEVEN

                        elif trade.direction == "SHORT" and exit_decision.new_stop_loss < trade.stop_loss:
                            trade.stop_loss = exit_decision.new_stop_loss
                            if trade.state in (STATE_NEW, STATE_OPEN):
                                trade.state = STATE_BREAKEVEN

                # Apply trailing stop
                if cfg.enable_trailing and exit_decision.trail_active:
                    ns = exit_decision.new_stop_loss
                    if ns > 0:
                        if trade.direction == "LONG" and ns > trade.stop_loss:
                            trade.stop_loss = ns
                            trade.state = STATE_TRAILING
                        elif trade.direction == "SHORT" and ns < trade.stop_loss:
                            trade.stop_loss = ns
                            trade.state = STATE_TRAILING

                # Apply partial TP
                if cfg.enable_partial_tp and exit_decision.partial_take_profit > 0:
                    if trade.remaining_size > 0.5:  # Only partial once
                        frac = exit_decision.partial_take_profit
                        partial_pnl = self._compute_partial_pnl(trade, close, frac)
                        trade.partial_pnl += partial_pnl
                        self.balance += partial_pnl
                        trade.remaining_size -= frac
                        trade.state = STATE_PARTIAL

                # Force exit
                if exit_decision.force_exit:
                    reason = exit_decision.reason.strip("; ") or "exit_engine"
                    self._close_trade(trade, close, candle_idx, reason)
                    continue

            # ── Standard SL/TP/Timeout check ──
            max_h = trade.max_hold if trade.max_hold > 0 else cfg.max_hold_candles
            if trade.bars_held >= max_h:
                self._close_trade(trade, close, candle_idx, "TIMEOUT")
                continue

            if trade.direction == "LONG":
                if low <= trade.stop_loss:
                    reason = "TRAIL_SL" if trade.state == STATE_TRAILING else (
                        "BE_SL" if trade.state == STATE_BREAKEVEN else "SL")
                    self._close_trade(trade, trade.stop_loss, candle_idx, reason)
                elif high >= trade.take_profit:
                    self._close_trade(trade, trade.take_profit, candle_idx, "TP")
            else:
                if high >= trade.stop_loss:
                    reason = "TRAIL_SL" if trade.state == STATE_TRAILING else (
                        "BE_SL" if trade.state == STATE_BREAKEVEN else "SL")
                    self._close_trade(trade, trade.stop_loss, candle_idx, reason)
                elif low <= trade.take_profit:
                    self._close_trade(trade, trade.take_profit, candle_idx, "TP")

            # Mark as OPEN if still NEW
            if trade.state == STATE_NEW:
                trade.state = STATE_OPEN

    # ═══════════════════════════════════════════════════════════
    # EXECUTION
    # ═══════════════════════════════════════════════════════════

    def _open_trade(self, signal: dict, indicators: dict, candle_idx: int):
        cfg = self.config
        close = indicators["close"]
        atr = signal["atr"] or close * 0.01

        slip = close * (cfg.slippage_bps / 10000)
        spread = close * (cfg.spread_bps / 10000)
        size_adj = signal.get("size_adjustment", 1.0)

        if signal["direction"] == "LONG":
            entry = close + slip + spread / 2
            sl = entry - atr * cfg.sl_atr_mult
            tp = entry + atr * cfg.tp_atr_mult
        else:
            entry = close - slip - spread / 2
            sl = entry + atr * cfg.sl_atr_mult
            tp = entry - atr * cfg.tp_atr_mult

        trade = ManagedTrade(
            trade_id=str(uuid4())[:8],
            asset=cfg.asset,
            direction=signal["direction"],
            entry_price=round(entry, 8),
            entry_time=candle_idx,
            stop_loss=round(sl, 8),
            take_profit=round(tp, 8),
            original_stop_loss=round(sl, 8),
            original_take_profit=round(tp, 8),
            size_multiplier=round(size_adj, 3),
            max_hold=cfg.max_hold_candles,
            entry_type=signal.get("entry_type", "momentum"),
            entry_quality=signal.get("entry_quality", 0.5),
            state=STATE_NEW,
        )
        self.open_trades.append(trade)

    def _close_trade(self, trade: ManagedTrade, exit_price: float,
                     candle_idx: int, reason: str):
        trade.exit_price = round(exit_price, 8)
        trade.exit_time = candle_idx
        trade.exit_reason = reason
        trade.state = STATE_CLOSED

        if trade.direction == "LONG":
            trade.pnl_pct = (exit_price - trade.entry_price) / trade.entry_price
        else:
            trade.pnl_pct = (trade.entry_price - exit_price) / trade.entry_price

        risk_amount = self.balance * (self.config.risk_per_trade_pct / 100)
        sl_frac = abs(trade.entry_price - trade.original_stop_loss) / trade.entry_price
        if sl_frac > 0:
            position_value = risk_amount / sl_frac * trade.size_multiplier * trade.remaining_size
            trade.pnl = round(position_value * trade.pnl_pct + trade.partial_pnl, 2)
        else:
            trade.pnl = round(trade.partial_pnl, 2)

        self.balance += trade.pnl - trade.partial_pnl  # partial already added
        self.open_trades.remove(trade)
        self.closed_trades.append(trade)

    def _compute_partial_pnl(self, trade: ManagedTrade, current_price: float,
                             fraction: float) -> float:
        """Compute PnL for a partial exit."""
        if trade.direction == "LONG":
            pnl_pct = (current_price - trade.entry_price) / trade.entry_price
        else:
            pnl_pct = (trade.entry_price - current_price) / trade.entry_price

        risk_amount = self.balance * (self.config.risk_per_trade_pct / 100)
        sl_frac = abs(trade.entry_price - trade.original_stop_loss) / trade.entry_price
        if sl_frac > 0:
            position_value = risk_amount / sl_frac * trade.size_multiplier
            return round(position_value * fraction * pnl_pct, 2)
        return 0

    def _calc_unrealized(self, current_price: float) -> float:
        total = 0
        for trade in self.open_trades:
            if trade.direction == "LONG":
                pnl_pct = (current_price - trade.entry_price) / trade.entry_price
            else:
                pnl_pct = (trade.entry_price - current_price) / trade.entry_price
            sl_frac = abs(trade.entry_price - trade.original_stop_loss) / trade.entry_price
            if sl_frac > 0:
                risk = self.balance * (self.config.risk_per_trade_pct / 100)
                pos = risk / sl_frac * trade.size_multiplier * trade.remaining_size
                total += pos * pnl_pct
        return total

    # ═══════════════════════════════════════════════════════════
    # METRICS
    # ═══════════════════════════════════════════════════════════

    def _compute_metrics(self) -> dict:
        trades = self.closed_trades
        if not trades:
            return {"total_trades": 0, "win_rate": 0, "sharpe_ratio": 0,
                    "max_drawdown": 0, "total_return_pct": 0, "expectancy": 0,
                    "profit_factor": 0}

        wins = [t for t in trades if t.pnl > 0]
        losses = [t for t in trades if t.pnl <= 0]
        pnls = [t.pnl for t in trades]

        total_return = self.balance - self.config.initial_balance
        total_return_pct = total_return / self.config.initial_balance * 100

        max_dd = max((e["drawdown"] for e in self.equity_curve), default=0)

        if len(pnls) > 1:
            rets = np.array(pnls) / self.config.initial_balance
            sharpe = float(np.mean(rets) / (np.std(rets) + 1e-10) * np.sqrt(len(pnls)))
        else:
            sharpe = 0

        gross_profit = sum(t.pnl for t in wins) if wins else 0
        gross_loss = abs(sum(t.pnl for t in losses)) if losses else 1
        pf = gross_profit / gross_loss if gross_loss > 0 else 0

        avg_win = float(np.mean([t.pnl for t in wins])) if wins else 0
        avg_loss = float(abs(np.mean([t.pnl for t in losses]))) if losses else 0
        wr = len(wins) / len(trades)
        expectancy = (wr * avg_win) - ((1 - wr) * avg_loss)

        # v4 metrics
        mfe_rs = [t.mfe_r for t in trades if t.mfe_r > 0]
        mae_rs = [t.mae_r for t in trades if t.mae_r > 0]
        avg_mfe_r = float(np.mean(mfe_rs)) if mfe_rs else 0
        avg_mae_r = float(np.mean(mae_rs)) if mae_rs else 0

        # MFE capture: how much of max favorable did we actually realize?
        mfe_captures = []
        for t in trades:
            if t.mfe > 0 and t.sl_distance > 0:
                realized_r = t.pnl / (self.config.initial_balance * self.config.risk_per_trade_pct / 100) if True else 0
                mfe_captures.append(min(1.0, max(-1.0, realized_r / (t.mfe_r + 0.001))))
        avg_mfe_capture = float(np.mean(mfe_captures)) if mfe_captures else 0

        # By exit reason
        exit_reasons = {}
        for t in trades:
            r = t.exit_reason or "UNKNOWN"
            if r not in exit_reasons:
                exit_reasons[r] = {"count": 0, "wins": 0, "total_pnl": 0}
            exit_reasons[r]["count"] += 1
            if t.pnl > 0: exit_reasons[r]["wins"] += 1
            exit_reasons[r]["total_pnl"] += t.pnl

        # By entry type
        entry_types = {}
        for t in trades:
            et = t.entry_type or "momentum"
            if et not in entry_types:
                entry_types[et] = {"count": 0, "wins": 0, "total_pnl": 0, "avg_quality": 0}
            entry_types[et]["count"] += 1
            if t.pnl > 0: entry_types[et]["wins"] += 1
            entry_types[et]["total_pnl"] += t.pnl
        for et in entry_types:
            quals = [t.entry_quality for t in trades if t.entry_type == et]
            entry_types[et]["avg_quality"] = round(float(np.mean(quals)), 3) if quals else 0

        return {
            "total_trades": len(trades),
            "wins": len(wins), "losses": len(losses),
            "win_rate": round(wr, 4),
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
            "profit_factor": round(pf, 3),
            "expectancy": round(expectancy, 2),
            "sharpe_ratio": round(sharpe, 3),
            "max_drawdown": round(max_dd, 4),
            "total_return": round(total_return, 2),
            "total_return_pct": round(total_return_pct, 2),
            "final_balance": round(self.balance, 2),
            # v4 metrics
            "avg_mfe_r": round(avg_mfe_r, 3),
            "avg_mae_r": round(avg_mae_r, 3),
            "mfe_mae_ratio": round(avg_mfe_r / max(0.001, avg_mae_r), 3),
            "avg_mfe_capture": round(avg_mfe_capture, 3),
            "exit_reasons": exit_reasons,
            "entry_types": entry_types,
        }
