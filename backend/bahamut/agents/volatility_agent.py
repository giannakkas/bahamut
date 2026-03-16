from bahamut.agents.base import BaseAgent
from bahamut.agents.schemas import (
    AgentOutputSchema, ChallengeRequest, ChallengeResponseSchema,
    SignalCycleRequest, Evidence,
)


class VolatilityAgent(BaseAgent):
    agent_id = "volatility_agent"
    display_name = "Volatility / Regime"
    required_features = ["volatility_data", "ohlcv"]

    async def analyze(self, request: SignalCycleRequest, features: dict) -> AgentOutputSchema:
        indicators = features.get("indicators", {})

        realized_vol = indicators.get("realized_vol_20", 0.12)
        atr = indicators.get("atr_14", 0)
        close = indicators.get("close", 0)
        bb_upper = indicators.get("bollinger_upper", close)
        bb_lower = indicators.get("bollinger_lower", close)

        evidence = []
        risk_notes = []
        score = 0

        # Bollinger Band width as vol proxy
        bb_width = (bb_upper - bb_lower) / close if close > 0 else 0

        if bb_width > 0.03:
            evidence.append(Evidence(
                claim="Bollinger Band expansion - high volatility environment",
                data_point=f"BB width={bb_width:.4f}", weight=0.7,
            ))
            risk_notes.append("Elevated volatility - wider stops recommended")
            score -= 10  # caution in high vol
        elif bb_width < 0.01:
            evidence.append(Evidence(
                claim="Bollinger Band compression - potential breakout setup",
                data_point=f"BB width={bb_width:.4f}", weight=0.8,
            ))
            score += 5  # compression often precedes moves

        # Realized vol assessment
        if realized_vol > 0.20:
            risk_notes.append(f"High realized volatility ({realized_vol:.1%}) - reduce position sizes")
            evidence.append(Evidence(
                claim="Realized volatility elevated above 20%",
                data_point=f"RealVol20={realized_vol:.1%}", weight=0.6,
            ))
            score -= 15
        elif realized_vol < 0.08:
            evidence.append(Evidence(
                claim="Low realized volatility - stable conditions",
                data_point=f"RealVol20={realized_vol:.1%}", weight=0.5,
            ))
            score += 10

        # ATR relative to price
        atr_pct = atr / close if close > 0 else 0
        if atr_pct > 0.01:
            risk_notes.append(f"Wide ATR ({atr_pct:.3%} of price) - volatile conditions")

        # Vol agent is mostly NEUTRAL - it assesses conditions, not direction
        bias = "NEUTRAL"
        confidence = 0.5 + abs(score) / 100

        if score < -15:
            risk_notes.append("VOLATILITY AGENT RECOMMENDS CAUTION: reduce exposure or wait")
        elif score > 10:
            evidence.append(Evidence(
                claim="Volatility conditions favor taking positions",
                data_point=f"Score={score}", weight=0.4,
            ))

        return self._make_output(
            request=request, bias=bias, confidence=confidence,
            evidence=evidence, risk_notes=risk_notes, urgency="PATIENT",
            meta={"bb_width": bb_width, "realized_vol": realized_vol,
                  "atr_pct": atr_pct, "vol_score": score},
        )

    async def respond_to_challenge(self, challenge: ChallengeRequest,
                                    original_output: AgentOutputSchema) -> ChallengeResponseSchema:
        return ChallengeResponseSchema(
            challenge_id=challenge.challenge_id, challenger=challenge.challenger,
            target_agent=self.agent_id, challenge_type=challenge.challenge_type,
            response="REJECT",
            justification="Volatility assessment is data-driven and does not change based on directional challenges",
        )
