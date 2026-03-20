"""
Technical Agent v2 — Market Structure + Regime-Aware Scoring

Fixes from audit:
  1. Removed EMA-only bias (was SHORT-biased due to scoring structure)
  2. Added HH/HL/LH/LL market structure detection
  3. Added volatility compression → breakout detection
  4. Added momentum exhaustion (RSI divergence proxy)
  5. Added regime-aware threshold adjustment
  6. Softer neutral zone, graduated EMA scoring
"""
from bahamut.agents.base import BaseAgent
from bahamut.agents.schemas import (
    AgentOutputSchema, ChallengeRequest, ChallengeResponseSchema,
    SignalCycleRequest, Evidence,
)


class TechnicalAgent(BaseAgent):
    agent_id = "technical_agent"
    display_name = "Technical / Timing"
    required_features = ["features", "ohlcv"]

    async def analyze(self, request: SignalCycleRequest, features: dict) -> AgentOutputSchema:
        f = features.get("indicators", {})
        candles = features.get("candles", [])

        rsi = f.get("rsi_14", 50)
        macd_hist = f.get("macd_histogram", 0)
        macd_line = f.get("macd_line", 0)
        macd_signal = f.get("macd_signal", 0)
        adx = f.get("adx_14", 20)
        ema_20 = f.get("ema_20", 0)
        ema_50 = f.get("ema_50", 0)
        ema_200 = f.get("ema_200", 0)
        close = f.get("close", 0)
        atr = f.get("atr_14", 0)
        stoch_k = f.get("stoch_k", 50)
        stoch_d = f.get("stoch_d", 50)
        bb_upper = f.get("bollinger_upper", close)
        bb_lower = f.get("bollinger_lower", close)
        realized_vol = f.get("realized_vol_20", 0.12)
        regime = request.current_regime

        score = 0
        evidence = []
        risk_notes = []

        # ── 1. MARKET STRUCTURE (HH/HL vs LH/LL) ──
        structure = self._detect_market_structure(candles)
        if structure["label"] not in ("UNKNOWN",):
            score += structure["score"]
            if structure["score"] != 0:
                evidence.append(Evidence(
                    claim=f"Market structure: {structure['label']}",
                    data_point=structure["detail"], weight=0.85,
                ))

        # ── 2. EMA TREND — graduated scoring (was +30/-30 binary) ──
        ema_score = 0
        if close > 0 and ema_20 > 0 and ema_50 > 0 and ema_200 > 0:
            if close > ema_20 > ema_50 > ema_200:
                ema_score = 20
                evidence.append(Evidence(
                    claim="Full bullish EMA alignment",
                    data_point=f"P={close:.5f}>E20={ema_20:.5f}>E50={ema_50:.5f}",
                    weight=0.6,
                ))
            elif close < ema_20 < ema_50 < ema_200:
                ema_score = -20
                evidence.append(Evidence(
                    claim="Full bearish EMA alignment",
                    data_point=f"P={close:.5f}<E20={ema_20:.5f}<E50={ema_50:.5f}",
                    weight=0.6,
                ))
            else:
                # Graduated partial alignment
                if close > ema_200: ema_score += 5
                else: ema_score -= 5
                if close > ema_50: ema_score += 5
                else: ema_score -= 5
                if close > ema_20: ema_score += 5
                else: ema_score -= 5
        score += ema_score

        # ── 3. RSI MOMENTUM + EXHAUSTION ──
        if rsi > 65:
            score += 10
            evidence.append(Evidence(claim="RSI bullish momentum", data_point=f"RSI={rsi:.1f}", weight=0.5))
        elif rsi < 35:
            score -= 10
            evidence.append(Evidence(claim="RSI bearish momentum", data_point=f"RSI={rsi:.1f}", weight=0.5))

        # Momentum exhaustion: extreme RSI reduces conviction
        if score > 15 and rsi > 75 and stoch_k > 85:
            score -= 10
            risk_notes.append(f"Bullish momentum exhaustion (RSI={rsi:.1f}, Stoch={stoch_k:.1f})")
        elif score < -15 and rsi < 25 and stoch_k < 15:
            score += 10
            risk_notes.append(f"Bearish momentum exhaustion (RSI={rsi:.1f}, Stoch={stoch_k:.1f})")

        # ── 4. MACD ──
        if macd_hist > 0:
            score += 10
        elif macd_hist < 0:
            score -= 10
        # Fresh crossover detection
        if macd_line and macd_signal:
            if macd_line > macd_signal and macd_hist > 0 and abs(macd_hist) < abs(macd_line) * 0.3:
                score += 5
                evidence.append(Evidence(claim="Fresh MACD bullish cross", data_point=f"Hist={macd_hist:.6f}", weight=0.6))
            elif macd_line < macd_signal and macd_hist < 0 and abs(macd_hist) < abs(macd_line) * 0.3:
                score -= 5
                evidence.append(Evidence(claim="Fresh MACD bearish cross", data_point=f"Hist={macd_hist:.6f}", weight=0.6))

        # ── 5. VOLATILITY COMPRESSION ──
        compressed = False
        bb_width = 0
        if close > 0:
            bb_width = (bb_upper - bb_lower) / close
            atr_pct = atr / close
            compressed = bb_width < 0.015 and atr_pct < 0.008 and realized_vol < 0.12
            if compressed:
                evidence.append(Evidence(
                    claim=f"Volatility compression (BB width {bb_width:.3%})",
                    data_point="Breakout setup", weight=0.7,
                ))
                risk_notes.append("Volatility compressed — breakout imminent")

        # ── 6. STOCHASTIC TIMING ──
        if stoch_k > 80 and score > 0:
            score -= 5
            risk_notes.append(f"Stochastic overbought ({stoch_k:.1f})")
        elif stoch_k < 20 and score < 0:
            score += 5
            risk_notes.append(f"Stochastic oversold ({stoch_k:.1f})")
        if stoch_k > stoch_d and stoch_k < 30:
            score += 5
        elif stoch_k < stoch_d and stoch_k > 70:
            score -= 5

        # ── 7. ADX TREND STRENGTH ──
        trend_strong = adx > 25
        if trend_strong:
            score = int(score * 1.10)
            evidence.append(Evidence(claim=f"Strong trend (ADX={adx:.1f})", data_point="Amplified", weight=0.5))
        elif adx < 15:
            score = int(score * 0.85)
            risk_notes.append(f"Weak trend ADX={adx:.1f}")

        # ── 8. REGIME ADJUSTMENTS ──
        if regime == "CRISIS":
            score = int(score * 0.5) if score > 0 else int(score * 1.1)
        elif regime == "HIGH_VOL":
            score = int(score * 0.7)
        elif regime == "LOW_VOL" and adx < 20 and not compressed:
            score = int(score * 0.85)
        elif regime == "RISK_OFF" and score > 0:
            score = int(score * 0.75)

        # ── FINAL OUTPUT ──
        neutral_zone = 20 if regime in ("HIGH_VOL", "CRISIS") else 15
        if score > neutral_zone:
            bias = "LONG"
            confidence = min(0.90, 0.45 + (score / 120) * 0.45)
        elif score < -neutral_zone:
            bias = "SHORT"
            confidence = min(0.90, 0.45 + (abs(score) / 120) * 0.45)
        else:
            bias = "NEUTRAL"
            confidence = 0.25 + (abs(score) / 100) * 0.2

        if compressed and bias != "NEUTRAL":
            confidence = min(0.92, confidence * 1.08)

        invalidation = []
        if bias == "LONG":
            invalidation.append(f"Price closes below 50-EMA ({ema_50 or close * 0.985:.5f})")
        elif bias == "SHORT":
            invalidation.append(f"Price closes above 50-EMA ({ema_50 or close * 1.015:.5f})")

        return self._make_output(
            request=request, bias=bias, confidence=confidence,
            evidence=evidence, risk_notes=risk_notes, invalidation=invalidation,
            urgency="IMMEDIATE" if trend_strong and abs(score) > 50 else "NEXT_BAR",
            meta={"score": score, "rsi": rsi, "macd_hist": macd_hist, "adx": adx,
                  "atr": atr, "trend_strong": trend_strong, "structure": structure["label"],
                  "compression": compressed, "ema_score": ema_score},
        )

    def _detect_market_structure(self, candles: list) -> dict:
        if not candles or len(candles) < 10:
            return {"label": "UNKNOWN", "score": 0, "detail": "Insufficient candles"}
        highs = [c.get("high", c.get("close", 0)) for c in candles]
        lows = [c.get("low", c.get("close", 0)) for c in candles]
        swing_highs, swing_lows = [], []
        for i in range(1, len(highs) - 1):
            if highs[i] > highs[i-1] and highs[i] > highs[i+1]:
                swing_highs.append(highs[i])
            if lows[i] < lows[i-1] and lows[i] < lows[i+1]:
                swing_lows.append(lows[i])
        if len(swing_highs) < 2 or len(swing_lows) < 2:
            return {"label": "UNKNOWN", "score": 0, "detail": "Too few swings"}
        sh1, sh2 = swing_highs[-2], swing_highs[-1]
        sl1, sl2 = swing_lows[-2], swing_lows[-1]
        hh, hl = sh2 > sh1, sl2 > sl1
        lh, ll = sh2 < sh1, sl2 < sl1
        if hh and hl:
            return {"label": "BULLISH_STRUCTURE", "score": 20, "detail": f"HH+HL"}
        elif lh and ll:
            return {"label": "BEARISH_STRUCTURE", "score": -20, "detail": f"LH+LL"}
        elif lh and hl:
            return {"label": "CONTRACTING", "score": 0, "detail": "LH+HL squeeze"}
        return {"label": "MIXED", "score": 0, "detail": "No clear pattern"}

    async def respond_to_challenge(self, challenge: ChallengeRequest, original_output: AgentOutputSchema) -> ChallengeResponseSchema:
        if challenge.challenge_type == "REGIME_OVERRIDE":
            return ChallengeResponseSchema(
                challenge_id=challenge.challenge_id, challenger=challenge.challenger,
                target_agent=self.agent_id, challenge_type=challenge.challenge_type,
                response="PARTIAL", revised_confidence=max(0.3, original_output.confidence - 0.15),
                justification="Reducing confidence due to macro regime conflict",
            )
        elif challenge.challenge_type == "VOL_REJECT":
            return ChallengeResponseSchema(
                challenge_id=challenge.challenge_id, challenger=challenge.challenger,
                target_agent=self.agent_id, challenge_type=challenge.challenge_type,
                response="PARTIAL", revised_confidence=max(0.2, original_output.confidence - 0.2),
                justification="Volatility expansion acknowledged",
            )
        return ChallengeResponseSchema(
            challenge_id=challenge.challenge_id, challenger=challenge.challenger,
            target_agent=self.agent_id, challenge_type=challenge.challenge_type,
            response="REJECT", justification=f"Technical setup remains valid despite {challenge.challenge_type}",
        )
