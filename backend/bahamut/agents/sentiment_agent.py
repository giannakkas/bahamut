"""Sentiment Agent - analyzes real news headlines via Claude LLM."""
from bahamut.agents.base import BaseAgent
from bahamut.agents.schemas import (
    AgentOutputSchema, ChallengeRequest, ChallengeResponseSchema,
    SignalCycleRequest, Evidence,
)
from bahamut.config import get_settings
import structlog
import httpx
import json

logger = structlog.get_logger()
settings = get_settings()


class SentimentAgent(BaseAgent):
    agent_id = "sentiment_agent"
    display_name = "Sentiment / Narrative"
    timeout_seconds = 15

    async def analyze(self, request: SignalCycleRequest, features: dict) -> AgentOutputSchema:
        asset = request.asset
        indicators = features.get("indicators", {})

        # Step 1: Try to fetch real news for this asset
        news_headlines = await self._fetch_news(asset)

        # Step 2: Use Claude to analyze the news + price data
        if settings.anthropic_api_key:
            try:
                return await self._llm_analysis(request, indicators, news_headlines)
            except Exception as e:
                logger.error("sentiment_llm_failed", error=str(e))

        # Fallback: regime-based
        return self._regime_based_sentiment(request)

    async def _fetch_news(self, asset: str) -> list[str]:
        """Fetch real news headlines for the asset."""
        try:
            from bahamut.ingestion.adapters.news import news_adapter
            articles = await news_adapter.get_asset_news(asset, count=5)
            return [a["title"] for a in articles if a.get("title")]
        except Exception as e:
            logger.warning("news_fetch_failed", asset=asset, error=str(e))
            return []

    async def _llm_analysis(self, request: SignalCycleRequest,
                             indicators: dict, headlines: list[str]) -> AgentOutputSchema:
        close = indicators.get("close", 0)
        rsi = indicators.get("rsi_14", 50)

        news_section = ""
        if headlines:
            news_section = f"\n\nRecent news headlines for {request.asset}:\n" + "\n".join(f"- {h}" for h in headlines[:5])
            news_section += "\n\nAnalyze these headlines for bullish/bearish sentiment."
        else:
            news_section = f"\n\nNo recent news available. Analyze based on market conditions and regime."

        prompt = f"""You are a financial sentiment analyst for {request.asset}.

Current data:
- Price: {close}
- RSI: {rsi}
- Regime: {request.current_regime}
- Asset class: {request.asset_class}{news_section}

Provide your analysis as JSON:
{{"bias": "LONG" or "SHORT" or "NEUTRAL", "confidence": 0.0-1.0, "headline": "one sentence summary", "risk_note": "key risk", "news_impact": "positive" or "negative" or "neutral"}}

Respond ONLY with JSON."""

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
                    "max_tokens": 250,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
            resp.raise_for_status()
            data = resp.json()

        text = data["content"][0]["text"].strip()
        try:
            result = json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                result = json.loads(text[start:end])
            else:
                raise ValueError(f"Could not parse: {text[:100]}")

        bias = result.get("bias", "NEUTRAL")
        confidence = min(1.0, max(0.0, float(result.get("confidence", 0.5))))

        evidence_list = [Evidence(
            claim=result.get("headline", "LLM sentiment analysis"),
            data_point=f"News impact: {result.get('news_impact', 'unknown')}", weight=0.7,
        )]

        if headlines:
            evidence_list.append(Evidence(
                claim=f"Based on {len(headlines)} real news headlines",
                data_point=headlines[0][:80] if headlines else "", weight=0.5,
            ))

        return self._make_output(
            request=request, bias=bias, confidence=confidence,
            evidence=evidence_list,
            risk_notes=[result.get("risk_note", "")] if result.get("risk_note") else [],
            urgency="NEXT_BAR",
            meta={
                "source": "claude_llm" + ("_with_news" if headlines else "_no_news"),
                "news_count": len(headlines),
                "news_impact": result.get("news_impact", "unknown"),
            },
        )

    def _regime_based_sentiment(self, request: SignalCycleRequest) -> AgentOutputSchema:
        regime = request.current_regime
        regime_sentiment = {
            "RISK_ON": ("LONG", 0.55, "Risk-on regime suggests positive sentiment"),
            "RISK_OFF": ("SHORT", 0.55, "Risk-off regime suggests negative sentiment"),
            "HIGH_VOL": ("NEUTRAL", 0.40, "High volatility creates mixed sentiment"),
            "LOW_VOL": ("NEUTRAL", 0.45, "Low volatility with no strong narrative"),
            "CRISIS": ("SHORT", 0.65, "Crisis regime - strong negative sentiment"),
            "TREND_CONTINUATION": ("LONG", 0.50, "Trend continuation - mildly positive"),
        }
        bias, conf, claim = regime_sentiment.get(regime, ("NEUTRAL", 0.40, "No clear sentiment"))
        return self._make_output(
            request=request, bias=bias, confidence=conf,
            evidence=[Evidence(claim=claim, data_point=f"Regime={regime}", weight=0.5)],
            risk_notes=["No live news data - sentiment from regime only"],
            meta={"source": "regime_fallback", "news_count": 0},
        )

    async def respond_to_challenge(self, challenge: ChallengeRequest,
                                    original_output: AgentOutputSchema) -> ChallengeResponseSchema:
        if challenge.challenge_type == "NARRATIVE_SHOCK":
            return ChallengeResponseSchema(
                challenge_id=challenge.challenge_id, challenger=challenge.challenger,
                target_agent=self.agent_id, challenge_type=challenge.challenge_type,
                response="ACCEPT",
                revised_confidence=max(0.2, original_output.confidence - 0.3),
                justification="Narrative shock acknowledged",
            )
        return ChallengeResponseSchema(
            challenge_id=challenge.challenge_id, challenger=challenge.challenger,
            target_agent=self.agent_id, challenge_type=challenge.challenge_type,
            response="REJECT", justification="Sentiment assessment maintained",
        )
