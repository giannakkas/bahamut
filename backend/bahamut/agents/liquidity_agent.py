from bahamut.agents.base import BaseAgent
from bahamut.agents.schemas import (
    AgentOutputSchema, ChallengeRequest, ChallengeResponseSchema,
    SignalCycleRequest, Evidence,
)


class LiquidityAgent(BaseAgent):
    agent_id = "liquidity_agent"
    display_name = "Liquidity / Structure"
    required_features = ["ohlcv", "volume_profile"]

    async def analyze(self, request: SignalCycleRequest, features: dict) -> AgentOutputSchema:
        indicators = features.get("indicators", {})

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

        # Volume analysis
        vol_ratio = volume / volume_sma if volume_sma > 0 else 1.0
        if vol_ratio > 1.5:
            evidence.append(Evidence(
                claim="Volume spike detected - institutional participation likely",
                data_point=f"Vol ratio={vol_ratio:.2f}x average", weight=0.7,
            ))
            score += 10 if close > ema_20 else -10
        elif vol_ratio < 0.5:
            risk_notes.append(f"Low volume ({vol_ratio:.2f}x avg) - thin liquidity, breakout risk")
            evidence.append(Evidence(
                claim="Below-average volume - thin liquidity conditions",
                data_point=f"Vol ratio={vol_ratio:.2f}x", weight=0.5,
            ))

        # Price structure relative to EMAs (support/resistance)
        ema_spread = abs(ema_20 - ema_50) / close if close > 0 else 0
        if close > ema_20 > ema_50:
            # Price above both EMAs - bullish structure
            distance_from_ema20 = (close - ema_20) / atr if atr > 0 else 0
            if distance_from_ema20 < 1.0:
                evidence.append(Evidence(
                    claim="Price near 20-EMA support in bullish structure",
                    data_point=f"Distance={distance_from_ema20:.2f} ATR from EMA20", weight=0.8,
                ))
                score += 20
            elif distance_from_ema20 > 2.5:
                risk_notes.append("Price extended far from 20-EMA - pullback risk")
                score -= 5
        elif close < ema_20 < ema_50:
            distance_from_ema20 = (ema_20 - close) / atr if atr > 0 else 0
            if distance_from_ema20 < 1.0:
                evidence.append(Evidence(
                    claim="Price near 20-EMA resistance in bearish structure",
                    data_point=f"Distance={distance_from_ema20:.2f} ATR from EMA20", weight=0.8,
                ))
                score -= 20
            elif distance_from_ema20 > 2.5:
                risk_notes.append("Price extended far below 20-EMA - bounce risk")
                score += 5

        # Recent range analysis (potential sweep zones)
        candle_range = (high - low) / atr if atr > 0 else 1.0
        if candle_range > 2.0:
            risk_notes.append(f"Wide range candle ({candle_range:.1f}x ATR) - possible sweep/stop hunt")
            evidence.append(Evidence(
                claim="Wide range candle may indicate stop sweeping activity",
                data_point=f"Range={candle_range:.1f}x ATR", weight=0.6,
            ))

        # Convert to bias
        # EMA structure adds to liquidity view
        if close and ema_20 and ema_50:
            if close > ema_20 > ema_50:
                score += 8
                evidence.append(Evidence(
                    claim="Price structure bullish (above key EMAs)",
                    data_point=f"Close > EMA20 > EMA50", weight=0.5,
                ))
            elif close < ema_20 < ema_50:
                score -= 8
                evidence.append(Evidence(
                    claim="Price structure bearish (below key EMAs)",
                    data_point=f"Close < EMA20 < EMA50", weight=0.5,
                ))

        # Looser thresholds
        if score > 5:
            bias = "LONG"
            confidence = min(0.80, 0.40 + score / 50)
        elif score < -5:
            bias = "SHORT"
            confidence = min(0.80, 0.40 + abs(score) / 50)
        else:
            bias = "NEUTRAL"
            confidence = 0.35

        return self._make_output(
            request=request, bias=bias, confidence=confidence,
            evidence=evidence, risk_notes=risk_notes,
            meta={"score": score, "vol_ratio": vol_ratio, "candle_range": candle_range},
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
