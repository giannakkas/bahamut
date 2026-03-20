"""
Candle-by-candle Replay Engine

Reconstructs features at each timestep, runs agents, consensus, and risk pipeline.
Simulates trade execution with configurable slippage/spread.
"""
import numpy as np
from datetime import datetime, timezone
from uuid import uuid4
from dataclasses import dataclass, field
from typing import Optional
import structlog

from bahamut.features.indicators import compute_indicators
from bahamut.agents.schemas import SignalCycleRequest

logger = structlog.get_logger()


@dataclass
class SimulatedTrade:
    trade_id: str
    asset: str
    direction: str  # LONG or SHORT
    entry_price: float
    entry_time: int  # candle index
    stop_loss: float
    take_profit: float
    size_multiplier: float = 1.0
    max_hold: int = 12
    regime: str = ""
    exit_price: Optional[float] = None
    exit_time: Optional[int] = None
    exit_reason: Optional[str] = None  # SL, TP, TIMEOUT, SIGNAL_REVERSE
    pnl: float = 0.0
    pnl_pct: float = 0.0


@dataclass
class BacktestConfig:
    asset: str = "BTCUSD"
    asset_class: str = "crypto"
    timeframe: str = "4H"
    trading_profile: str = "BALANCED"
    initial_balance: float = 100_000.0
    risk_per_trade_pct: float = 2.0
    sl_atr_mult: float = 2.0
    tp_atr_mult: float = 3.0
    max_hold_candles: int = 12  # 12 x 4H = 48h
    max_concurrent: int = 3
    slippage_bps: float = 5.0  # basis points
    spread_bps: float = 10.0
    min_candles_warmup: int = 200  # Need 200 for EMA-200
    # Ablation flags
    disable_ai_reviewer: bool = True
    disable_sentiment: bool = False
    disable_macro: bool = False
    disable_risk_veto: bool = False
    disable_trust_weighting: bool = False
    # v3 ablation flags
    disable_regime: bool = False        # Disable v3 regime detection
    disable_adaptive: bool = False      # Disable v3 adaptive SL/TP/sizing
    disable_cross_asset: bool = False   # Disable v3 cross-asset (always off in backtest anyway)


@dataclass
class BacktestResult:
    config: BacktestConfig
    trades: list
    metrics: dict
    equity_curve: list
    signals: list


class ReplayEngine:
    """Candle-by-candle backtesting engine."""

    def __init__(self, config: BacktestConfig):
        self.config = config
        self.balance = config.initial_balance
        self.peak_balance = config.initial_balance
        self.open_trades: list[SimulatedTrade] = []
        self.closed_trades: list[SimulatedTrade] = []
        self.equity_curve: list[dict] = []
        self.signals: list[dict] = []

    def run(self, candles: list[dict]) -> BacktestResult:
        """
        Run backtest on historical candle data.
        
        candles: list of dicts with keys: open, high, low, close, volume, datetime
        """
        cfg = self.config

        if len(candles) < cfg.min_candles_warmup + 10:
            raise ValueError(f"Need at least {cfg.min_candles_warmup + 10} candles, got {len(candles)}")

        logger.info("backtest_started", asset=cfg.asset, candles=len(candles),
                     warmup=cfg.min_candles_warmup)

        for i in range(cfg.min_candles_warmup, len(candles)):
            candle = candles[i]
            history = candles[:i + 1]  # All candles up to current

            # 1. Compute indicators from history
            indicators = compute_indicators(history)
            if not indicators:
                continue

            # 2. v3: Detect regime at this timestep (skipped if ablation flag set)
            regime_label = "NORMAL"
            vol_state = "NORMAL"
            struct_state = "RANGE"
            regime_risk_mult = 1.0
            if not cfg.disable_regime:
                try:
                    from bahamut.intelligence.regime import regime_detector
                    closes_arr = np.array([c["close"] for c in history])
                    highs_arr = np.array([c.get("high", c["close"]) for c in history])
                    lows_arr = np.array([c.get("low", c["close"]) for c in history])
                    if len(closes_arr) >= 60:
                        regime_result = regime_detector.detect(closes_arr, highs_arr, lows_arr, indicators)
                        regime_label = regime_result.primary_label
                        vol_state = regime_result.volatility.state
                        struct_state = regime_result.structure.state
                        regime_risk_mult = regime_result.risk_multiplier
                except Exception:
                    pass

            # 3. Check open trades for SL/TP/timeout
            self._check_exits(candle, i)

            # 4. Generate signal with regime context
            signal = self._generate_signal(indicators, history[-30:], cfg,
                                           regime_label=regime_label,
                                           vol_state=vol_state,
                                           struct_state=struct_state)

            # 5. v3: Compute adaptive SL/TP for this trade (skipped if ablation flag set)
            sl_mult = cfg.sl_atr_mult
            tp_mult = cfg.tp_atr_mult
            size_mult = 1.0
            max_hold = cfg.max_hold_candles
            if not cfg.disable_adaptive:
                try:
                    from bahamut.strategy.adaptive import adaptive_strategy
                    aparams = adaptive_strategy.compute(
                        regime={"volatility": {"state": vol_state},
                                "structure": {"state": struct_state},
                                "primary_label": regime_label,
                                "risk_multiplier": regime_risk_mult},
                        signal_confidence=signal.get("confidence", 0.5),
                        asset_class=cfg.asset_class,
                        direction=signal.get("direction", ""),
                    )
                    sl_mult = aparams.sl_multiplier
                    tp_mult = aparams.tp_multiplier
                    size_mult = aparams.size_multiplier
                    max_hold = aparams.max_hold_candles
                except Exception:
                    pass

            # 6. Execute if conditions met
            if signal["decision"] in ("SIGNAL", "STRONG_SIGNAL"):
                if len(self.open_trades) < cfg.max_concurrent:
                    existing = [t for t in self.open_trades if t.direction == signal["direction"]]
                    if not existing:
                        self._open_trade(signal, indicators, i,
                                         sl_mult=sl_mult, tp_mult=tp_mult,
                                         size_mult=size_mult, max_hold=max_hold)

            # 7. Record equity with regime
            unrealized = self._calc_unrealized(candle["close"])
            equity = self.balance + unrealized
            self.peak_balance = max(self.peak_balance, equity)
            self.equity_curve.append({
                "candle_idx": i,
                "datetime": candle.get("datetime", ""),
                "close": candle["close"],
                "equity": round(equity, 2),
                "balance": round(self.balance, 2),
                "open_trades": len(self.open_trades),
                "drawdown": round(1 - equity / self.peak_balance, 4) if self.peak_balance > 0 else 0,
                "regime": regime_label,
            })

        # Force-close remaining open trades at last candle
        last_candle = candles[-1]
        for trade in list(self.open_trades):
            self._close_trade(trade, last_candle["close"], len(candles) - 1, "END_OF_DATA")

        metrics = self._compute_metrics()

        logger.info("backtest_completed", trades=len(self.closed_trades),
                     win_rate=metrics.get("win_rate"), sharpe=metrics.get("sharpe_ratio"),
                     total_return=metrics.get("total_return_pct"))

        return BacktestResult(
            config=self.config,
            trades=[self._trade_to_dict(t) for t in self.closed_trades],
            metrics=metrics,
            equity_curve=self.equity_curve,
            signals=self.signals,
        )

    def _generate_signal(self, indicators: dict, recent_candles: list, cfg: BacktestConfig,
                         regime_label: str = "NORMAL", vol_state: str = "NORMAL",
                         struct_state: str = "RANGE") -> dict:
        """
        Signal generation using TechnicalAgent v2/v3 logic.
        Now regime-aware: adjusts neutral zone and scoring by regime.
        """
        close = indicators.get("close", 0)
        rsi = indicators.get("rsi_14", 50)
        macd_hist = indicators.get("macd_histogram", 0)
        adx = indicators.get("adx_14", 20)
        ema_20 = indicators.get("ema_20", 0)
        ema_50 = indicators.get("ema_50", 0)
        ema_200 = indicators.get("ema_200", 0)
        atr = indicators.get("atr_14", 0)
        stoch_k = indicators.get("stoch_k", 50)
        stoch_d = indicators.get("stoch_d", 50)
        bb_upper = indicators.get("bollinger_upper", close)
        bb_lower = indicators.get("bollinger_lower", close)

        score = 0

        # Market structure from candles
        if recent_candles and len(recent_candles) >= 10:
            highs = [c.get("high", c.get("close", 0)) for c in recent_candles]
            lows = [c.get("low", c.get("close", 0)) for c in recent_candles]
            swing_highs, swing_lows = [], []
            for j in range(1, len(highs) - 1):
                if highs[j] > highs[j-1] and highs[j] > highs[j+1]:
                    swing_highs.append(highs[j])
                if lows[j] < lows[j-1] and lows[j] < lows[j+1]:
                    swing_lows.append(lows[j])
            if len(swing_highs) >= 2 and len(swing_lows) >= 2:
                hh = swing_highs[-1] > swing_highs[-2]
                hl = swing_lows[-1] > swing_lows[-2]
                lh = swing_highs[-1] < swing_highs[-2]
                ll = swing_lows[-1] < swing_lows[-2]
                if hh and hl: score += 20
                elif lh and ll: score -= 20

        # EMA graduated
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

        # v3: Regime adjustments
        if regime_label == "CRISIS":
            score = int(score * 0.4) if score > 0 else int(score * 1.15)
        elif vol_state in ("EXTREME", "HIGH_VOL"):
            score = int(score * 0.7)
        elif struct_state == "CHOPPY":
            score = int(score * 0.65)
        elif struct_state == "RANGE" and adx < 20:
            score = int(score * 0.80)

        # Stochastic timing
        if stoch_k > 80 and score > 0: score -= 5
        elif stoch_k < 20 and score < 0: score += 5

        # v3: Regime-aware neutral zone
        if regime_label in ("CRISIS", "CHOPPY") or vol_state in ("EXTREME", "HIGH_VOL"):
            neutral_zone = 25
        elif struct_state in ("TRENDING_UP", "TRENDING_DOWN"):
            neutral_zone = 12
        else:
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

        # Decision thresholds (simplified from consensus)
        if confidence >= 0.65 and direction != "NO_TRADE":
            decision = "STRONG_SIGNAL"
        elif confidence >= 0.50 and direction != "NO_TRADE":
            decision = "SIGNAL"
        else:
            decision = "NO_TRADE"

        signal = {
            "direction": direction,
            "confidence": confidence,
            "decision": decision,
            "score": score,
            "atr": atr,
            "regime": regime_label,
        }
        self.signals.append(signal)
        return signal

    def _open_trade(self, signal: dict, indicators: dict, candle_idx: int,
                    sl_mult: float = None, tp_mult: float = None,
                    size_mult: float = 1.0, max_hold: int = None):
        cfg = self.config
        close = indicators["close"]
        atr = signal["atr"] or close * 0.01

        # Use adaptive params if provided, else config defaults
        _sl = sl_mult if sl_mult is not None else cfg.sl_atr_mult
        _tp = tp_mult if tp_mult is not None else cfg.tp_atr_mult
        _hold = max_hold if max_hold is not None else cfg.max_hold_candles

        # Apply slippage + spread
        slip = close * (cfg.slippage_bps / 10000)
        spread = close * (cfg.spread_bps / 10000)

        if signal["direction"] == "LONG":
            entry = close + slip + spread / 2
            sl = entry - atr * _sl
            tp = entry + atr * _tp
        else:
            entry = close - slip - spread / 2
            sl = entry + atr * _sl
            tp = entry - atr * _tp

        trade = SimulatedTrade(
            trade_id=str(uuid4())[:8],
            asset=cfg.asset,
            direction=signal["direction"],
            entry_price=round(entry, 8),
            entry_time=candle_idx,
            stop_loss=round(sl, 8),
            take_profit=round(tp, 8),
            size_multiplier=round(size_mult, 2),
            max_hold=_hold,
            regime=signal.get("regime", ""),
        )
        self.open_trades.append(trade)

    def _check_exits(self, candle: dict, candle_idx: int):
        high, low, close = candle["high"], candle["low"], candle["close"]
        cfg = self.config

        for trade in list(self.open_trades):
            # Timeout check — use per-trade max_hold from adaptive strategy
            trade_max_hold = trade.max_hold if trade.max_hold > 0 else cfg.max_hold_candles
            if candle_idx - trade.entry_time >= trade_max_hold:
                self._close_trade(trade, close, candle_idx, "TIMEOUT")
                continue

            if trade.direction == "LONG":
                if low <= trade.stop_loss:
                    self._close_trade(trade, trade.stop_loss, candle_idx, "SL")
                elif high >= trade.take_profit:
                    self._close_trade(trade, trade.take_profit, candle_idx, "TP")
            else:  # SHORT
                if high >= trade.stop_loss:
                    self._close_trade(trade, trade.stop_loss, candle_idx, "SL")
                elif low <= trade.take_profit:
                    self._close_trade(trade, trade.take_profit, candle_idx, "TP")

    def _close_trade(self, trade: SimulatedTrade, exit_price: float, candle_idx: int, reason: str):
        trade.exit_price = round(exit_price, 8)
        trade.exit_time = candle_idx
        trade.exit_reason = reason

        if trade.direction == "LONG":
            trade.pnl_pct = (exit_price - trade.entry_price) / trade.entry_price
        else:
            trade.pnl_pct = (trade.entry_price - exit_price) / trade.entry_price

        risk_amount = self.balance * (self.config.risk_per_trade_pct / 100)

        # PnL = position_size * price_change_pct
        # Position size = risk_amount / (SL distance as fraction of entry)
        sl_frac = abs(trade.entry_price - trade.stop_loss) / trade.entry_price
        if sl_frac > 0:
            position_value = risk_amount / sl_frac
            # v3: Apply size_multiplier from adaptive strategy
            position_value *= trade.size_multiplier
            trade.pnl = round(position_value * trade.pnl_pct, 2)
        else:
            trade.pnl = 0

        self.balance += trade.pnl
        self.open_trades.remove(trade)
        self.closed_trades.append(trade)

    def _calc_unrealized(self, current_price: float) -> float:
        total = 0
        for trade in self.open_trades:
            if trade.direction == "LONG":
                pnl_pct = (current_price - trade.entry_price) / trade.entry_price
            else:
                pnl_pct = (trade.entry_price - current_price) / trade.entry_price
            sl_frac = abs(trade.entry_price - trade.stop_loss) / trade.entry_price
            if sl_frac > 0:
                risk_amount = self.balance * (self.config.risk_per_trade_pct / 100)
                position_value = risk_amount / sl_frac
                total += position_value * pnl_pct
        return total

    def _compute_metrics(self) -> dict:
        trades = self.closed_trades
        if not trades:
            return {"total_trades": 0, "win_rate": 0, "sharpe_ratio": 0, "max_drawdown": 0,
                    "total_return_pct": 0, "expectancy": 0, "profit_factor": 0}

        wins = [t for t in trades if t.pnl > 0]
        losses = [t for t in trades if t.pnl <= 0]
        pnls = [t.pnl for t in trades]

        total_return = self.balance - self.config.initial_balance
        total_return_pct = total_return / self.config.initial_balance * 100

        # Drawdown from equity curve
        max_dd = 0
        if self.equity_curve:
            max_dd = max(e["drawdown"] for e in self.equity_curve)

        # Sharpe (simplified — annualized)
        if len(pnls) > 1:
            returns = np.array(pnls) / self.config.initial_balance
            # Annualize based on actual trade frequency, not daily assumption
            # Approx trades per year: trades / (data_days/252)
            n_trades = len(pnls)
            trades_per_year = max(1, n_trades)  # Conservative: don't inflate
            sharpe = float(np.mean(returns) / (np.std(returns) + 1e-10) * np.sqrt(trades_per_year))
        else:
            sharpe = 0

        # Profit factor
        gross_profit = sum(t.pnl for t in wins) if wins else 0
        gross_loss = abs(sum(t.pnl for t in losses)) if losses else 1
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0

        # Expectancy
        avg_win = np.mean([t.pnl for t in wins]) if wins else 0
        avg_loss = abs(np.mean([t.pnl for t in losses])) if losses else 0
        win_rate = len(wins) / len(trades)
        expectancy = (win_rate * avg_win) - ((1 - win_rate) * avg_loss)

        # By exit reason
        exit_reasons = {}
        for t in trades:
            r = t.exit_reason
            if r not in exit_reasons:
                exit_reasons[r] = {"count": 0, "wins": 0, "total_pnl": 0}
            exit_reasons[r]["count"] += 1
            if t.pnl > 0: exit_reasons[r]["wins"] += 1
            exit_reasons[r]["total_pnl"] += t.pnl

        # v3: By regime
        regime_stats = {}
        for t in trades:
            r = t.regime or "UNKNOWN"
            if r not in regime_stats:
                regime_stats[r] = {"count": 0, "wins": 0, "total_pnl": 0}
            regime_stats[r]["count"] += 1
            if t.pnl > 0: regime_stats[r]["wins"] += 1
            regime_stats[r]["total_pnl"] += t.pnl

        return {
            "total_trades": len(trades),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": round(win_rate, 4),
            "avg_win": round(float(avg_win), 2),
            "avg_loss": round(float(avg_loss), 2),
            "profit_factor": round(profit_factor, 3),
            "expectancy": round(expectancy, 2),
            "sharpe_ratio": round(sharpe, 3),
            "max_drawdown": round(max_dd, 4),
            "total_return": round(total_return, 2),
            "total_return_pct": round(total_return_pct, 2),
            "final_balance": round(self.balance, 2),
            "exit_reasons": exit_reasons,
            "regime_stats": regime_stats,
        }

    def _trade_to_dict(self, t: SimulatedTrade) -> dict:
        return {
            "trade_id": t.trade_id, "asset": t.asset, "direction": t.direction,
            "entry_price": t.entry_price, "exit_price": t.exit_price,
            "entry_time": t.entry_time, "exit_time": t.exit_time,
            "stop_loss": t.stop_loss, "take_profit": t.take_profit,
            "exit_reason": t.exit_reason, "pnl": t.pnl, "pnl_pct": round(t.pnl_pct, 4),
            "regime": t.regime, "size_multiplier": t.size_multiplier,
        }
