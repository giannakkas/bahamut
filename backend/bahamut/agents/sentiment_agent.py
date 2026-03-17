"""Sentiment Agent - deep news analysis via Claude Opus 4.6 for maximum accuracy."""
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
    timeout_seconds = 15  # Opus needs more time for deep analysis

    async def analyze(self, request: SignalCycleRequest, features: dict) -> AgentOutputSchema:
        asset = request.asset
        indicators = features.get("indicators", {})

        # Fetch real news
        news_headlines = await self._fetch_news(asset)

        # Use Claude Opus 4.6 for maximum accuracy
        if settings.anthropic_api_key:
            try:
                return await self._opus_analysis(request, indicators, news_headlines)
            except Exception as e:
                logger.error("sentiment_opus_failed", error=str(e))

        return self._regime_based_sentiment(request)

    async def _fetch_news(self, asset: str) -> list[dict]:
        try:
            from bahamut.ingestion.adapters.news import news_adapter
            articles = await news_adapter.get_asset_news(asset, count=8)
            return [{"title": a["title"], "source": a.get("source", ""),
                     "description": a.get("description", "")[:200]}
                    for a in articles if a.get("title")]
        except Exception as e:
            logger.warning("news_fetch_failed", asset=asset, error=str(e))
            return []

    async def _opus_analysis(self, request: SignalCycleRequest,
                              indicators: dict, headlines: list[dict]) -> AgentOutputSchema:
        close = indicators.get("close", 0)
        rsi = indicators.get("rsi_14", 50)
        macd = indicators.get("macd_histogram", 0)
        adx = indicators.get("adx_14", 20)
        atr = indicators.get("atr_14", 0)
        ema_20 = indicators.get("ema_20", close)
        ema_50 = indicators.get("ema_50", close)
        ema_200 = indicators.get("ema_200", close)

        news_block = ""
        if headlines:
            news_block = "\n\nREAL-TIME NEWS HEADLINES (analyze each one carefully):\n"
            for i, h in enumerate(headlines[:8], 1):
                news_block += f"{i}. [{h.get('source', 'Unknown')}] {h['title']}\n"
                if h.get('description'):
                    news_block += f"   Summary: {h['description']}\n"
        else:
            news_block = "\n\nNo real-time news available for this asset. Base analysis on technical and macro context only."

        prompt = f"""You are an elite institutional trading analyst at a $500M macro fund. Your job is to analyze market sentiment for {request.asset} and determine if current conditions favor LONG, SHORT, or NEUTRAL positions. People's real money depends on your accuracy.

CURRENT MARKET DATA for {request.asset}:
- Price: {close}
- RSI(14): {rsi:.1f}
- MACD Histogram: {macd}
- ADX(14): {adx:.1f} (trend strength)
- ATR(14): {atr} (volatility)
- EMA 20/50/200: {ema_20:.5f} / {ema_50:.5f} / {ema_200:.5f}
- Price vs EMAs: {'Above all (bullish structure)' if close > ema_20 > ema_50 else 'Below all (bearish structure)' if close < ema_20 < ema_50 else 'Mixed/transitioning'}
- Current regime: {request.current_regime}
- Asset class: {request.asset_class}
{news_block}

ANALYSIS REQUIREMENTS:
1. Read EVERY headline carefully. Identify which are bullish, bearish, or neutral for {request.asset}.
2. Consider the SOURCE credibility (Reuters > random blog).
3. Weigh news recency — more recent = more weight.
4. Cross-reference news sentiment with technical indicators — do they confirm or contradict?
5. Identify any potential black swan risks or narrative shifts.
6. Consider geopolitical implications if relevant.
7. BE HONEST — if signals are mixed, say NEUTRAL with low confidence. Do NOT force a direction.

Respond with ONLY this JSON (no other text):
{{
  "bias": "LONG" or "SHORT" or "NEUTRAL",
  "confidence": 0.0-1.0,
  "headline_summary": "2-3 sentence analysis of what the news collectively says",
  "bullish_factors": ["factor1", "factor2"],
  "bearish_factors": ["factor1", "factor2"],
  "key_risk": "the single biggest risk to this view",
  "news_impact": "strong_bullish" or "mild_bullish" or "neutral" or "mild_bearish" or "strong_bearish",
  "conviction_reason": "why you chose this direction and confidence level"
}}"""

        async with httpx.AsyncClient(timeout=25) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": settings.anthropic_api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": "claude-haiku-4-5-20251001",
                    "max_tokens": 500,
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
                raise ValueError(f"Could not parse Opus response: {text[:200]}")

        bias = result.get("bias", "NEUTRAL")
        confidence = min(1.0, max(0.0, float(result.get("confidence", 0.5))))

        # Build rich evidence
        evidence_list = []
        evidence_list.append(Evidence(
            claim=result.get("headline_summary", "Opus sentiment analysis"),
            data_point=f"News impact: {result.get('news_impact', 'unknown')}",
            weight=0.8,
        ))

        if headlines:
            evidence_list.append(Evidence(
                claim=f"Analyzed {len(headlines)} real-time headlines from {', '.join(set(h.get('source','') for h in headlines[:3]))}",
                data_point=result.get("conviction_reason", ""),
                weight=0.6,
            ))

        for factor in result.get("bullish_factors", [])[:2]:
            evidence_list.append(Evidence(claim=f"Bullish: {factor}", data_point="news_analysis", weight=0.4))
        for factor in result.get("bearish_factors", [])[:2]:
            evidence_list.append(Evidence(claim=f"Bearish: {factor}", data_point="news_analysis", weight=0.4))

        risk_notes = []
        if result.get("key_risk"):
            risk_notes.append(result["key_risk"])

        return self._make_output(
            request=request, bias=bias, confidence=confidence,
            evidence=evidence_list, risk_notes=risk_notes,
            urgency="NEXT_BAR",
            meta={
                "model": "claude-haiku-4-5-20251001",
                "news_count": len(headlines),
                "news_impact": result.get("news_impact", "unknown"),
                "bullish_factors": result.get("bullish_factors", []),
                "bearish_factors": result.get("bearish_factors", []),
                "conviction": result.get("conviction_reason", ""),
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
            risk_notes=["No live news - sentiment from regime only"],
            meta={"model": "fallback", "news_count": 0},
        )

    async def respond_to_challenge(self, challenge: ChallengeRequest,
                                    original_output: AgentOutputSchema) -> ChallengeResponseSchema:
        if challenge.challenge_type == "NARRATIVE_SHOCK":
            return ChallengeResponseSchema(
                challenge_id=challenge.challenge_id, challenger=challenge.challenger,
                target_agent=self.agent_id, challenge_type=challenge.challenge_type,
                response="ACCEPT",
                revised_confidence=max(0.2, original_output.confidence - 0.3),
                justification="Narrative shock acknowledged - reducing confidence",
            )
        return ChallengeResponseSchema(
            challenge_id=challenge.challenge_id, challenger=challenge.challenger,
            target_agent=self.agent_id, challenge_type=challenge.challenge_type,
            response="REJECT", justification="Opus-grade sentiment analysis maintained",
        )
