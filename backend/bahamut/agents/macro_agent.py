from bahamut.agents.base import BaseAgent
from bahamut.agents.schemas import (
    AgentOutputSchema, ChallengeRequest, ChallengeResponseSchema,
    SignalCycleRequest, Evidence,
)


class MacroAgent(BaseAgent):
    agent_id = "macro_agent"
    display_name = "Macro / Rates"
    required_features = ["macro_data", "volatility_data", "regime"]

    async def analyze(self, request: SignalCycleRequest, features: dict) -> AgentOutputSchema:
        macro = features.get("macro", {})
        vol = features.get("volatility", {})

        vix = vol.get("vix", 20)
        dxy = macro.get("dxy", 100)
        us10y = macro.get("us10y", 4.0)
        us2y = macro.get("us2y", 4.5)
        spread = us10y - us2y
        regime = request.current_regime

        score = 0
        evidence = []

        # Yield curve analysis
        if spread < -0.2:
            evidence.append(Evidence(
                claim="Yield curve inverted (recession signal)",
                data_point=f"10Y-2Y spread={spread:.2f}%", weight=0.9,
            ))
            score -= 20  # risk-off for equities
        elif spread > 0.5:
            evidence.append(Evidence(
                claim="Yield curve steep (growth signal)",
                data_point=f"10Y-2Y spread={spread:.2f}%", weight=0.7,
            ))
            score += 15

        # DXY impact on FX
        asset_class = request.asset_class
        if asset_class == "fx":
            if dxy > 105:
                score -= 20
                evidence.append(Evidence(
                    claim="Strong USD (DXY elevated) - bearish for non-USD pairs",
                    data_point=f"DXY={dxy:.2f}", weight=0.8,
                ))
            elif dxy < 100:
                score += 20
                evidence.append(Evidence(
                    claim="Weak USD (DXY depressed) - bullish for non-USD pairs",
                    data_point=f"DXY={dxy:.2f}", weight=0.8,
                ))

        # VIX regime interpretation
        risk_notes = []
        if vix > 30:
            score -= 15
            risk_notes.append(f"Elevated VIX ({vix:.1f}) - risk-off environment")
        elif vix < 15:
            score += 10

        # Regime alignment
        if regime in ("RISK_ON", "TREND_CONTINUATION"):
            score += 10
        elif regime in ("RISK_OFF", "CRISIS"):
            score -= 10

        # Convert to bias
        if score > 10:
            bias = "LONG"
            confidence = min(0.90, 0.5 + (score / 80) * 0.4)
        elif score < -10:
            bias = "SHORT"
            confidence = min(0.90, 0.5 + (abs(score) / 80) * 0.4)
        else:
            bias = "NEUTRAL"
            confidence = 0.35

        return self._make_output(
            request=request, bias=bias, confidence=confidence,
            evidence=evidence, risk_notes=risk_notes,
            urgency="PATIENT",
            meta={"score": score, "vix": vix, "dxy": dxy, "spread": spread},
        )

    async def respond_to_challenge(
        self, challenge: ChallengeRequest, original_output: AgentOutputSchema
    ) -> ChallengeResponseSchema:
        return ChallengeResponseSchema(
            challenge_id=challenge.challenge_id,
            challenger=challenge.challenger,
            target_agent=self.agent_id,
            challenge_type=challenge.challenge_type,
            response="REJECT",
            justification="Macro fundamentals are slow-moving and take precedence over shorter-term signals",
        )
