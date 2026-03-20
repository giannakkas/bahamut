"""
Bahamut v3 — Advanced Regime Detection Engine

3-layer regime detection:
  1. Volatility Regime (ATR, realized vol, BB width) → LOW/NORMAL/HIGH/EXTREME
  2. Market Structure Regime (ADX, swing analysis) → TRENDING_UP/DOWN/RANGE/CHOPPY
  3. Hidden Markov Model (returns, volatility, momentum) → latent states

Replaces the simple rules in features/regime.py with a proper statistical engine.
"""
import numpy as np
from dataclasses import dataclass, field
from typing import Optional
import structlog

logger = structlog.get_logger()

# Try to import hmmlearn — graceful fallback if unavailable
try:
    from hmmlearn.hmm import GaussianHMM
    HMM_AVAILABLE = True
except ImportError:
    HMM_AVAILABLE = False
    logger.warning("hmmlearn_not_available", msg="HMM regime detection disabled")


@dataclass
class VolatilityRegime:
    state: str = "NORMAL"         # LOW_VOL, NORMAL, HIGH_VOL, EXTREME
    atr_percentile: float = 0.5   # Where current ATR sits in history
    realized_vol: float = 0.12
    bb_width: float = 0.02
    confidence: float = 0.5


@dataclass
class StructureRegime:
    state: str = "RANGE"          # TRENDING_UP, TRENDING_DOWN, RANGE, CHOPPY
    adx: float = 20.0
    trend_strength: float = 0.0   # -1 (strong down) to +1 (strong up)
    swing_pattern: str = ""       # HH_HL, LH_LL, MIXED
    confidence: float = 0.5


@dataclass
class HMMRegime:
    state: int = -1               # Latent state index (0, 1, 2, ...)
    state_label: str = "UNKNOWN"  # Human-readable label
    state_probs: list = field(default_factory=list)  # Probability of each state
    confidence: float = 0.0
    n_states: int = 0


@dataclass
class CompositeRegime:
    """Full 3-layer regime assessment."""
    volatility: VolatilityRegime = field(default_factory=VolatilityRegime)
    structure: StructureRegime = field(default_factory=StructureRegime)
    hmm: HMMRegime = field(default_factory=HMMRegime)

    # Derived
    primary_label: str = "NORMAL"  # Simplified label for downstream use
    confidence: float = 0.5
    risk_multiplier: float = 1.0   # Position sizing multiplier from regime

    def to_dict(self) -> dict:
        return {
            "volatility": {"state": self.volatility.state, "atr_pct": self.volatility.atr_percentile,
                           "realized_vol": self.volatility.realized_vol, "bb_width": self.volatility.bb_width},
            "structure": {"state": self.structure.state, "adx": self.structure.adx,
                          "trend_strength": self.structure.trend_strength, "swing": self.structure.swing_pattern},
            "hmm": {"state": self.hmm.state, "label": self.hmm.state_label,
                    "confidence": self.hmm.confidence, "probs": [round(p, 3) for p in self.hmm.state_probs]},
            "primary_label": self.primary_label,
            "confidence": self.confidence,
            "risk_multiplier": self.risk_multiplier,
        }


class RegimeDetector:
    """Advanced 3-layer regime detection."""

    def __init__(self):
        self._hmm_model: Optional[object] = None
        self._hmm_fitted = False
        self._hmm_state_labels: dict[int, str] = {}

    def detect(
        self,
        closes: np.ndarray,
        highs: np.ndarray,
        lows: np.ndarray,
        indicators: dict,
    ) -> CompositeRegime:
        """
        Full regime detection from price data and indicators.

        closes/highs/lows: numpy arrays of recent price history (200+ preferred)
        indicators: dict from compute_indicators()
        """
        regime = CompositeRegime()

        # Layer 1: Volatility
        regime.volatility = self._detect_volatility(closes, highs, lows, indicators)

        # Layer 2: Market Structure
        regime.structure = self._detect_structure(closes, highs, lows, indicators)

        # Layer 3: HMM
        regime.hmm = self._detect_hmm(closes)

        # Composite label + risk multiplier
        regime.primary_label = self._compute_primary_label(regime)
        regime.confidence = self._compute_composite_confidence(regime)
        regime.risk_multiplier = self._compute_risk_multiplier(regime)

        return regime

    # ═══════════════════════════════════════════════════════════
    # LAYER 1: VOLATILITY REGIME
    # ═══════════════════════════════════════════════════════════

    def _detect_volatility(
        self, closes: np.ndarray, highs: np.ndarray, lows: np.ndarray, ind: dict
    ) -> VolatilityRegime:
        atr = ind.get("atr_14", 0)
        close = ind.get("close", 0)
        bb_upper = ind.get("bollinger_upper", close)
        bb_lower = ind.get("bollinger_lower", close)
        realized_vol = ind.get("realized_vol_20", 0.12)

        if close <= 0:
            return VolatilityRegime()

        bb_width = (bb_upper - bb_lower) / close
        atr_pct = atr / close if close > 0 else 0

        # ATR percentile relative to history
        atr_percentile = 0.5
        if len(closes) >= 50 and len(highs) >= 50:
            # Compute historical ATR values
            historical_atrs = []
            for i in range(15, min(len(closes), 200)):
                h_slice = highs[i-14:i]
                l_slice = lows[i-14:i]
                c_prev = closes[i-15:i-1]
                if len(h_slice) != len(c_prev) or len(h_slice) == 0:
                    continue
                tr_slice = np.maximum(
                    h_slice - l_slice,
                    np.maximum(
                        np.abs(h_slice - c_prev),
                        np.abs(l_slice - c_prev)
                    )
                )
                if len(tr_slice) > 0:
                    historical_atrs.append(float(np.mean(tr_slice)))

            if historical_atrs:
                atr_percentile = float(np.mean(np.array(historical_atrs) < atr))

        # Classification
        if atr_percentile > 0.90 or realized_vol > 0.30 or bb_width > 0.06:
            state = "EXTREME"
            confidence = 0.85
        elif atr_percentile > 0.70 or realized_vol > 0.18 or bb_width > 0.035:
            state = "HIGH_VOL"
            confidence = 0.75
        elif atr_percentile < 0.25 and realized_vol < 0.08 and bb_width < 0.012:
            state = "LOW_VOL"
            confidence = 0.70
        else:
            state = "NORMAL"
            confidence = 0.65

        return VolatilityRegime(
            state=state, atr_percentile=round(atr_percentile, 3),
            realized_vol=round(realized_vol, 4), bb_width=round(bb_width, 5),
            confidence=round(confidence, 3),
        )

    # ═══════════════════════════════════════════════════════════
    # LAYER 2: MARKET STRUCTURE REGIME
    # ═══════════════════════════════════════════════════════════

    def _detect_structure(
        self, closes: np.ndarray, highs: np.ndarray, lows: np.ndarray, ind: dict
    ) -> StructureRegime:
        adx = ind.get("adx_14", 20)
        ema_20 = ind.get("ema_20", 0)
        ema_50 = ind.get("ema_50", 0)
        ema_200 = ind.get("ema_200", 0)
        close_price = ind.get("close", 0)

        # Swing analysis
        swing_pattern = "MIXED"
        if len(highs) >= 10 and len(lows) >= 10:
            sh, sl = [], []
            for i in range(1, min(len(highs) - 1, 25)):
                if highs[-(i+1)] > highs[-(i+2)] and highs[-(i+1)] > highs[-i]:
                    sh.append(float(highs[-(i+1)]))
                if lows[-(i+1)] < lows[-(i+2)] and lows[-(i+1)] < lows[-i]:
                    sl.append(float(lows[-(i+1)]))

            if len(sh) >= 2 and len(sl) >= 2:
                hh = sh[0] > sh[1]
                hl = sl[0] > sl[1]
                lh = sh[0] < sh[1]
                ll = sl[0] < sl[1]

                if hh and hl:
                    swing_pattern = "HH_HL"
                elif lh and ll:
                    swing_pattern = "LH_LL"
                elif lh and hl:
                    swing_pattern = "CONTRACTING"
                elif hh and ll:
                    swing_pattern = "EXPANDING"

        # Trend strength: -1 to +1
        trend_strength = 0.0
        if close_price > 0 and ema_20 > 0 and ema_50 > 0:
            if close_price > ema_20 > ema_50:
                trend_strength = min(1.0, adx / 40)
            elif close_price < ema_20 < ema_50:
                trend_strength = -min(1.0, adx / 40)
            else:
                trend_strength = (adx / 100 - 0.2) * (1 if close_price > ema_50 else -1)

        # Classification
        if adx > 30 and swing_pattern in ("HH_HL",) and trend_strength > 0.3:
            state = "TRENDING_UP"
            confidence = min(0.90, 0.5 + adx / 80)
        elif adx > 30 and swing_pattern in ("LH_LL",) and trend_strength < -0.3:
            state = "TRENDING_DOWN"
            confidence = min(0.90, 0.5 + adx / 80)
        elif adx < 20:
            if swing_pattern in ("CONTRACTING", "EXPANDING", "MIXED"):
                state = "CHOPPY"
                confidence = 0.60
            else:
                state = "RANGE"
                confidence = 0.55
        else:
            # ADX 20-30: weak trend
            if trend_strength > 0.2:
                state = "TRENDING_UP"
                confidence = 0.55
            elif trend_strength < -0.2:
                state = "TRENDING_DOWN"
                confidence = 0.55
            else:
                state = "RANGE"
                confidence = 0.50

        return StructureRegime(
            state=state, adx=round(adx, 2),
            trend_strength=round(trend_strength, 4),
            swing_pattern=swing_pattern, confidence=round(confidence, 3),
        )

    # ═══════════════════════════════════════════════════════════
    # LAYER 3: HIDDEN MARKOV MODEL
    # ═══════════════════════════════════════════════════════════

    def _detect_hmm(self, closes: np.ndarray, n_states: int = 4) -> HMMRegime:
        if not HMM_AVAILABLE or len(closes) < 60:
            return HMMRegime(state=-1, state_label="UNAVAILABLE", confidence=0)

        try:
            # Feature matrix: [returns, volatility, momentum]
            returns = np.diff(np.log(closes + 1e-10))
            n = len(returns)

            # Rolling volatility (10-period)
            vol = np.array([
                np.std(returns[max(0, i-10):i+1]) if i >= 10 else np.std(returns[:i+1])
                for i in range(n)
            ])

            # Momentum (10-period return)
            momentum = np.array([
                returns[max(0, i-10):i+1].sum() for i in range(n)
            ])

            # Stack features
            X = np.column_stack([returns, vol, momentum])

            # Remove NaN/inf
            mask = np.all(np.isfinite(X), axis=1)
            X = X[mask]

            if len(X) < 40:
                return HMMRegime(state=-1, state_label="INSUFFICIENT_DATA", confidence=0)

            # Fit or retrain model (retrain every 100 new observations)
            should_retrain = (
                not self._hmm_fitted
                or self._hmm_model is None
                or len(X) % 100 < 2  # Retrain roughly every 100 candles
            )
            if should_retrain:
                model = GaussianHMM(
                    n_components=n_states,
                    covariance_type="full",
                    n_iter=100,
                    random_state=42,
                    tol=0.01,
                )
                model.fit(X)
                self._hmm_model = model
                self._hmm_fitted = True

                # Label states by their mean return and volatility
                self._label_hmm_states(model, n_states)

            # Predict current state
            states = self._hmm_model.predict(X)
            current_state = int(states[-1])

            # State probabilities for last observation
            try:
                log_probs = self._hmm_model.predict_proba(X[-1:])
                state_probs = log_probs[0].tolist()
            except Exception:
                state_probs = [1.0 / n_states] * n_states

            confidence = max(state_probs) if state_probs else 0.0
            label = self._hmm_state_labels.get(current_state, f"STATE_{current_state}")

            return HMMRegime(
                state=current_state,
                state_label=label,
                state_probs=state_probs,
                confidence=round(confidence, 3),
                n_states=n_states,
            )

        except Exception as e:
            logger.warning("hmm_detection_failed", error=str(e)[:100])
            return HMMRegime(state=-1, state_label="ERROR", confidence=0)

    def _label_hmm_states(self, model, n_states: int):
        """Assign human-readable labels to HMM states based on mean features."""
        means = model.means_  # Shape: (n_states, n_features)
        # Features: [return, volatility, momentum]

        state_info = []
        for i in range(n_states):
            mean_ret = means[i][0]
            mean_vol = means[i][1]
            mean_mom = means[i][2]
            state_info.append((i, mean_ret, mean_vol, mean_mom))

        # Sort by volatility to assign labels
        by_vol = sorted(state_info, key=lambda x: x[2])

        labels = {}
        for rank, (idx, ret, vol, mom) in enumerate(by_vol):
            if rank == 0:
                labels[idx] = "CALM_MARKET"
            elif rank == n_states - 1:
                if ret < 0:
                    labels[idx] = "CRISIS_SELLOFF"
                else:
                    labels[idx] = "VOLATILE_RALLY"
            elif ret > 0 and mom > 0:
                labels[idx] = "BULL_TREND"
            elif ret < 0 and mom < 0:
                labels[idx] = "BEAR_TREND"
            else:
                labels[idx] = "TRANSITION"

        self._hmm_state_labels = labels

    def retrain_hmm(self, closes: np.ndarray, n_states: int = 4):
        """Force HMM retrain (e.g. daily or weekly)."""
        self._hmm_fitted = False
        self._hmm_model = None
        return self._detect_hmm(closes, n_states)

    # ═══════════════════════════════════════════════════════════
    # COMPOSITE LOGIC
    # ═══════════════════════════════════════════════════════════

    def _compute_primary_label(self, r: CompositeRegime) -> str:
        """Map 3-layer regime to a single actionable label."""
        vol = r.volatility.state
        struct = r.structure.state
        hmm = r.hmm.state_label

        if vol == "EXTREME" or hmm == "CRISIS_SELLOFF":
            return "CRISIS"
        if vol == "HIGH_VOL":
            if struct in ("TRENDING_UP", "TRENDING_DOWN"):
                return "VOLATILE_TREND"
            return "HIGH_VOL"
        if struct == "TRENDING_UP":
            return "TREND_UP"
        if struct == "TRENDING_DOWN":
            return "TREND_DOWN"
        if vol == "LOW_VOL":
            if struct == "RANGE":
                return "LOW_VOL_RANGE"
            return "LOW_VOL"
        if struct == "CHOPPY":
            return "CHOPPY"
        return "NORMAL"

    def _compute_composite_confidence(self, r: CompositeRegime) -> float:
        """Weighted average of layer confidences."""
        weights = {"vol": 0.25, "struct": 0.35, "hmm": 0.40}
        conf = (
            r.volatility.confidence * weights["vol"] +
            r.structure.confidence * weights["struct"] +
            r.hmm.confidence * weights["hmm"]
        )
        # If HMM unavailable, redistribute weights
        if r.hmm.confidence == 0:
            conf = (
                r.volatility.confidence * 0.40 +
                r.structure.confidence * 0.60
            )
        return round(min(0.95, conf), 3)

    def _compute_risk_multiplier(self, r: CompositeRegime) -> float:
        """
        Position sizing multiplier based on regime.
        1.0 = normal, <1 = reduce, >1 = can be slightly more aggressive.
        """
        label = r.primary_label
        multipliers = {
            "CRISIS": 0.3,
            "HIGH_VOL": 0.6,
            "VOLATILE_TREND": 0.7,
            "CHOPPY": 0.6,
            "TREND_UP": 1.0,
            "TREND_DOWN": 0.9,
            "LOW_VOL": 1.0,
            "LOW_VOL_RANGE": 0.85,
            "NORMAL": 1.0,
        }
        return multipliers.get(label, 0.8)


# Singleton
regime_detector = RegimeDetector()
