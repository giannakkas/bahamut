from uuid import uuid4
from bahamut.agents.base import BaseAgent
from bahamut.agents.schemas import (
    AgentOutputSchema, ChallengeRequest, ChallengeResponseSchema,
    SignalCycleRequest, Evidence,
)


class TechnicalAgent(BaseAgent):
    agent_id = "technical_agent"
    display_name = "Technical / Timing"
    required_features = ["features", "ohlcv"]

    async def analyze(
        self, request: SignalCycleRequest, features: dict
    ) -> AgentOutputSchema:
        """Analyze technical indicators for directional bias and timing."""
        f = features.get("indicators", {})

        rsi = f.get("rsi_14", 50)
        macd_hist = f.get("macd_histogram", 0)
        adx = f.get("adx_14", 20)
        ema_20 = f.get("ema_20", 0)
        ema_50 = f.get("ema_50", 0)
        ema_200 = f.get("ema_200", 0)
        close = f.get("close", 0)
        atr = f.get("atr_14", 0)
        stoch_k = f.get("stoch_k", 50)

        # ── Scoring logic ──
        score = 0  # -100 to +100 scale
        evidence = []

        # Trend alignment (EMA stack)
        if close > ema_20 > ema_50 > ema_200:
            score += 30
            evidence.append(Evidence(
                claim="Full bullish EMA alignment (20>50>200)",
                data_point=f"close={close:.5f}, ema20={ema_20:.5f}, ema50={ema_50:.5f}",
                weight=0.8,
            ))
        elif close < ema_20 < ema_50 < ema_200:
            score -= 30
            evidence.append(Evidence(
                claim="Full bearish EMA alignment (20<50<200)",
                data_point=f"close={close:.5f}, ema20={ema_20:.5f}",
                weight=0.8,
            ))
        elif close > ema_200:
            score += 10
            evidence.append(Evidence(
                claim="Price above 200 EMA (broadly bullish)",
                data_point=f"close={close:.5f}, ema200={ema_200:.5f}",
                weight=0.4,
            ))
        else:
            score -= 10

        # Momentum (RSI)
        if rsi > 60:
            score += 15
            evidence.append(Evidence(
                claim="RSI showing bullish momentum",
                data_point=f"RSI(14)={rsi:.1f}",
                weight=0.5,
            ))
        elif rsi < 40:
            score -= 15
            evidence.append(Evidence(
                claim="RSI showing bearish momentum",
                data_point=f"RSI(14)={rsi:.1f}",
                weight=0.5,
            ))

        # Overbought/oversold modifiers
        if rsi > 80:
            score -= 10  # overbought reduces bullish conviction
        elif rsi < 20:
            score += 10  # oversold reduces bearish conviction

        # MACD
        if macd_hist > 0:
            score += 15
            evidence.append(Evidence(
                claim="MACD histogram positive (bullish momentum)",
                data_point=f"MACD_hist={macd_hist:.6f}",
                weight=0.6,
            ))
        elif macd_hist < 0:
            score -= 15

        # Trend strength (ADX)
        trend_strong = adx > 25
        if trend_strong:
            score = int(score * 1.2)  # amplify signal in strong trend
            evidence.append(Evidence(
                claim="Strong trend detected (ADX > 25)",
                data_point=f"ADX(14)={adx:.1f}",
                weight=0.5,
            ))

        # Stochastic (timing)
        risk_notes = []
        if stoch_k > 80 and score > 0:
            risk_notes.append(f"Stochastic overbought ({stoch_k:.1f}), timing risk for long entry")
        elif stoch_k < 20 and score < 0:
            risk_notes.append(f"Stochastic oversold ({stoch_k:.1f}), timing risk for short entry")

        # ── Convert score to bias/confidence ──
        if score > 15:
            bias = "LONG"
            confidence = min(0.95, 0.5 + (score / 100) * 0.5)
        elif score < -15:
            bias = "SHORT"
            confidence = min(0.95, 0.5 + (abs(score) / 100) * 0.5)
        else:
            bias = "NEUTRAL"
            confidence = 0.3 + (abs(score) / 100) * 0.2

        # Invalidation
        invalidation = []
        if bias == "LONG":
            inv_price = ema_50 if ema_50 > 0 else close * 0.99
            invalidation.append(f"Price closes below 50-EMA ({inv_price:.5f})")
        elif bias == "SHORT":
            inv_price = ema_50 if ema_50 > 0 else close * 1.01
            invalidation.append(f"Price closes above 50-EMA ({inv_price:.5f})")

        return self._make_output(
            request=request,
            bias=bias,
            confidence=confidence,
            evidence=evidence,
            risk_notes=risk_notes,
            invalidation=invalidation,
            urgency="IMMEDIATE" if trend_strong and abs(score) > 40 else "NEXT_BAR",
            meta={
                "score": score, "rsi": rsi, "macd_hist": macd_hist,
                "adx": adx, "atr": atr, "trend_strong": trend_strong,
            },
        )

    async def respond_to_challenge(
        self, challenge: ChallengeRequest, original_output: AgentOutputSchema
    ) -> ChallengeResponseSchema:
        """Respond to challenges from other agents."""
        if challenge.challenge_type == "REGIME_OVERRIDE":
            # Macro agent says regime disagrees with technical read
            return ChallengeResponseSchema(
                challenge_id=challenge.challenge_id,
                challenger=challenge.challenger,
                target_agent=self.agent_id,
                challenge_type=challenge.challenge_type,
                response="PARTIAL",
                revised_confidence=max(0.3, original_output.confidence - 0.15),
                justification="Reducing confidence due to macro regime conflict, but technical setup remains valid",
            )
        elif challenge.challenge_type == "VOL_REJECT":
            return ChallengeResponseSchema(
                challenge_id=challenge.challenge_id,
                challenger=challenge.challenger,
                target_agent=self.agent_id,
                challenge_type=challenge.challenge_type,
                response="PARTIAL",
                revised_confidence=max(0.2, original_output.confidence - 0.2),
                justification="Volatility expansion acknowledged, reducing timing confidence",
            )
        else:
            return ChallengeResponseSchema(
                challenge_id=challenge.challenge_id,
                challenger=challenge.challenger,
                target_agent=self.agent_id,
                challenge_type=challenge.challenge_type,
                response="REJECT",
                justification=f"Technical indicators remain valid despite {challenge.challenge_type}",
            )
