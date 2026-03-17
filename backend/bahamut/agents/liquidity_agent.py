from bahamut.agents.base import BaseAgent
from bahamut.agents.schemas import (
    AgentOutputSchema, ChallengeRequest, ChallengeResponseSchema,
    SignalCycleRequest, Evidence,
)


class LiquidityAgent(BaseAgent):
    agent_id = "liquidity_agent"
    display_name = "Liquidity / Whales"
    required_features = ["ohlcv", "volume_profile"]

    async def analyze(self, request: SignalCycleRequest, features: dict) -> AgentOutputSchema:
        indicators = features.get("indicators", {})
        candles = features.get("candles", [])

        close = indicators.get("close", 0)
        high = indicators.get("high", close)
        low = indicators.get("low", close)
        ema_20 = indicators.get("ema_20", close)
        ema_50 = indicators.get("ema_50", close)
        atr = indicators.get("atr_14", 0)
        volume = indicators.get("volume", 0)
        volume_sma = indicators.get("volume_sma_20", volume)

        evidence = []
        risk_notes = []
        score = 0

        # ── Whale / Volume Spike Detection ──
        from bahamut.whales.tracker import detect_volume_spikes
        whale_data = detect_volume_spikes(candles) if candles else {}
        whale_score = whale_data.get("whale_score", 0)
        whale_signal = whale_data.get("signal", "NORMAL")
        vol_ratio = whale_data.get("volume_ratio", 1.0)

        if whale_score >= 20:
            evidence.append(Evidence(
                claim=f"WHALE ALERT: {whale_signal} — volume {vol_ratio:.1f}x average",
                data_point=whale_data.get("details", ""), weight=0.95,
            ))
            # Whale activity boosts in direction of price move
            if close > ema_20:
                score += 25
            else:
                score -= 25
        elif whale_score >= 10:
            evidence.append(Evidence(
                claim=f"Elevated volume ({vol_ratio:.1f}x avg) — institutional activity likely",
                data_point=whale_data.get("details", ""), weight=0.8,
            ))
            if close > ema_20:
                score += 15
            else:
                score -= 15
        elif whale_score > 0:
            evidence.append(Evidence(
                claim=f"Volume slightly above average ({vol_ratio:.1f}x)",
                data_point=whale_data.get("details", ""), weight=0.6,
            ))
            score += 5 if close > ema_20 else -5

        # Basic volume ratio fallback (if no candles for whale tracker)
        if not candles:
            vol_ratio = volume / volume_sma if volume_sma > 0 else 1.0
            if vol_ratio > 1.5:
                evidence.append(Evidence(
                    claim="Volume spike detected - institutional participation likely",
                    data_point=f"Vol ratio={vol_ratio:.2f}x average", weight=0.7,
                ))
                score += 10 if close > ema_20 else -10
            elif vol_ratio < 0.5:
                risk_notes.append(f"Low volume ({vol_ratio:.2f}x avg) - thin liquidity")

        # ── Price Structure (support/resistance) ──
        if close > ema_20 > ema_50:
            distance = (close - ema_20) / atr if atr > 0 else 0
            if distance < 1.0:
                evidence.append(Evidence(
                    claim="Price near 20-EMA support in bullish structure",
                    data_point=f"Distance={distance:.2f} ATR from EMA20", weight=0.8,
                ))
                score += 20
            elif distance > 2.5:
                risk_notes.append("Price extended far from 20-EMA - pullback risk")
                score -= 5
        elif close < ema_20 < ema_50:
            distance = (ema_20 - close) / atr if atr > 0 else 0
            if distance < 1.0:
                evidence.append(Evidence(
                    claim="Price near 20-EMA resistance in bearish structure",
                    data_point=f"Distance={distance:.2f} ATR from EMA20", weight=0.8,
                ))
                score -= 20
            elif distance > 2.5:
                risk_notes.append("Price extended below 20-EMA - bounce risk")
                score += 5

        # ── EMA structure direction ──
        if close and ema_20 and ema_50:
            if close > ema_20 > ema_50:
                score += 8
                evidence.append(Evidence(
                    claim="Bullish price structure (above key EMAs)",
                    data_point="Close > EMA20 > EMA50", weight=0.5,
                ))
            elif close < ema_20 < ema_50:
                score -= 8
                evidence.append(Evidence(
                    claim="Bearish price structure (below key EMAs)",
                    data_point="Close < EMA20 < EMA50", weight=0.5,
                ))

        # ── Sweep detection ──
        candle_range = (high - low) / atr if atr > 0 else 1.0
        if candle_range > 2.0:
            risk_notes.append(f"Wide range candle ({candle_range:.1f}x ATR) - possible stop hunt")

        # Convert to bias
        if score > 5:
            bias = "LONG"
            confidence = min(0.85, 0.40 + score / 40)
        elif score < -5:
            bias = "SHORT"
            confidence = min(0.85, 0.40 + abs(score) / 40)
        else:
            bias = "NEUTRAL"
            confidence = 0.35

        return self._make_output(
            request=request, bias=bias, confidence=confidence,
            evidence=evidence, risk_notes=risk_notes,
            meta={
                "score": score,
                "vol_ratio": vol_ratio,
                "candle_range": candle_range,
                "whale_score": whale_score,
                "whale_signal": whale_signal,
            },
        )

    async def respond_to_challenge(self, challenge: ChallengeRequest,
                                    original_output: AgentOutputSchema) -> ChallengeResponseSchema:
        if challenge.challenge_type == "TRAP_WARNING":
            return ChallengeResponseSchema(
                challenge_id=challenge.challenge_id, challenger=challenge.challenger,
                target_agent=self.agent_id, challenge_type=challenge.challenge_type,
                response="PARTIAL",
                revised_confidence=max(0.25, original_output.confidence - 0.2),
                justification="Acknowledging trap risk - reducing confidence",
            )
        return ChallengeResponseSchema(
            challenge_id=challenge.challenge_id, challenger=challenge.challenger,
            target_agent=self.agent_id, challenge_type=challenge.challenge_type,
            response="REJECT", justification="Structure analysis based on price action remains valid",
        )
