from bahamut.agents.base import BaseAgent
from bahamut.agents.schemas import (
    AgentOutputSchema, ChallengeRequest, ChallengeResponseSchema,
    SignalCycleRequest, Evidence,
)
from bahamut.config import get_settings
import structlog
import httpx

logger = structlog.get_logger()
settings = get_settings()


class SentimentAgent(BaseAgent):
    agent_id = "sentiment_agent"
    display_name = "Sentiment / Narrative"
    required_features = ["news", "sentiment"]
    timeout_seconds = 15  # LLM calls can be slower

    async def analyze(self, request: SignalCycleRequest, features: dict) -> AgentOutputSchema:
        """Use Claude to analyze market sentiment for the asset."""
        asset = request.asset
        regime = request.current_regime

        # If Anthropic API key available, use LLM for sentiment analysis
        if settings.anthropic_api_key:
            try:
                return await self._llm_analysis(request, features)
            except Exception as e:
                logger.error("sentiment_llm_failed", error=str(e))

        # Fallback: rule-based sentiment from regime
        return self._regime_based_sentiment(request)

    async def _llm_analysis(self, request: SignalCycleRequest, features: dict) -> AgentOutputSchema:
        """Call Claude API for sentiment analysis."""
        indicators = features.get("indicators", {})
        close = indicators.get("close", 0)
        rsi = indicators.get("rsi_14", 50)

        prompt = f"""You are a financial sentiment analyst. Analyze the current market sentiment for {request.asset}.

Current data:
- Price: {close}
- RSI: {rsi}
- Regime: {request.current_regime}
- Asset class: {request.asset_class}

Provide your analysis as JSON with these exact fields:
{{"bias": "LONG" or "SHORT" or "NEUTRAL", "confidence": 0.0-1.0, "headline": "one sentence summary", "risk_note": "key risk"}}

Respond ONLY with the JSON, no other text."""

        async with httpx.AsyncClient(timeout=12) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": settings.anthropic_api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": "claude-sonnet-4-20250514",
                    "max_tokens": 200,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
            resp.raise_for_status()
            data = resp.json()

        text = data["content"][0]["text"].strip()

        # Parse JSON response
        import json
        try:
            result = json.loads(text)
        except json.JSONDecodeError:
            # Try to extract JSON from response
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                result = json.loads(text[start:end])
            else:
                raise ValueError(f"Could not parse LLM response: {text[:100]}")

        bias = result.get("bias", "NEUTRAL")
        confidence = min(1.0, max(0.0, float(result.get("confidence", 0.5))))

        return self._make_output(
            request=request, bias=bias, confidence=confidence,
            evidence=[Evidence(
                claim=result.get("headline", "LLM sentiment analysis"),
                data_point=f"Claude analysis for {request.asset}", weight=0.7,
            )],
            risk_notes=[result.get("risk_note", "")] if result.get("risk_note") else [],
            urgency="NEXT_BAR",
            meta={"source": "claude_llm", "raw_response": result},
        )

    def _regime_based_sentiment(self, request: SignalCycleRequest) -> AgentOutputSchema:
        """Fallback: derive sentiment from regime."""
        regime = request.current_regime
        regime_sentiment = {
            "RISK_ON": ("LONG", 0.55, "Risk-on regime suggests positive sentiment"),
            "RISK_OFF": ("SHORT", 0.55, "Risk-off regime suggests negative sentiment"),
            "HIGH_VOL": ("NEUTRAL", 0.40, "High volatility creates mixed sentiment"),
            "LOW_VOL": ("NEUTRAL", 0.45, "Low volatility with no strong narrative"),
            "CRISIS": ("SHORT", 0.65, "Crisis regime - strong negative sentiment"),
            "TREND_CONTINUATION": ("LONG", 0.50, "Trend continuation - mildly positive"),
        }

        bias, conf, claim = regime_sentiment.get(regime, ("NEUTRAL", 0.40, "No clear sentiment signal"))

        return self._make_output(
            request=request, bias=bias, confidence=conf,
            evidence=[Evidence(claim=claim, data_point=f"Regime={regime}", weight=0.5)],
            risk_notes=["Sentiment derived from regime only - no live news data"],
            meta={"source": "regime_fallback"},
        )

    async def respond_to_challenge(self, challenge: ChallengeRequest,
                                    original_output: AgentOutputSchema) -> ChallengeResponseSchema:
        if challenge.challenge_type == "NARRATIVE_SHOCK":
            return ChallengeResponseSchema(
                challenge_id=challenge.challenge_id, challenger=challenge.challenger,
                target_agent=self.agent_id, challenge_type=challenge.challenge_type,
                response="ACCEPT",
                revised_confidence=max(0.2, original_output.confidence - 0.3),
                justification="Narrative shock acknowledged - reducing confidence significantly",
            )
        return ChallengeResponseSchema(
            challenge_id=challenge.challenge_id, challenger=challenge.challenger,
            target_agent=self.agent_id, challenge_type=challenge.challenge_type,
            response="REJECT", justification="Sentiment assessment maintained",
        )
