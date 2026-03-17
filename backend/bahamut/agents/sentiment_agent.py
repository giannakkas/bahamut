"""Sentiment Agent - deep news analysis via Google Gemini 2.5 Flash (FREE)."""
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

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"


class SentimentAgent(BaseAgent):
    agent_id = "sentiment_agent"
    display_name = "Sentiment / Narrative"
    timeout_seconds = 15

    async def analyze(self, request: SignalCycleRequest, features: dict) -> AgentOutputSchema:
        asset = request.asset
        indicators = features.get("indicators", {})
        news_headlines = await self._fetch_news(asset)

        # Try Gemini first (FREE), fallback to Claude
        if settings.gemini_api_key:
            try:
                return await self._gemini_analysis(request, indicators, news_headlines)
            except Exception as e:
                logger.error("gemini_failed", error=str(e))

        if settings.anthropic_api_key:
            try:
                return await self._claude_fallback(request, indicators, news_headlines)
            except Exception as e:
                logger.error("claude_fallback_failed", error=str(e))

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

    def _build_prompt(self, request, indicators, headlines):
        close = indicators.get("close", 0)
        rsi = indicators.get("rsi_14", 50)
        macd = indicators.get("macd_histogram", 0)
        adx = indicators.get("adx_14", 20)
        ema_20 = indicators.get("ema_20", close)
        ema_50 = indicators.get("ema_50", close)
        ema_200 = indicators.get("ema_200", close)

        news_block = ""
        if headlines:
            news_block = "\n\nREAL-TIME NEWS HEADLINES:\n"
            for i, h in enumerate(headlines[:8], 1):
                news_block += f"{i}. [{h.get('source', 'Unknown')}] {h['title']}\n"
                if h.get('description'):
                    news_block += f"   {h['description']}\n"
        else:
            news_block = "\n\nNo news available. Analyze based on technicals and regime only."

        return f"""You are an elite institutional trading analyst. Analyze sentiment for {request.asset}. Real money depends on accuracy.

MARKET DATA for {request.asset}:
- Price: {close}
- RSI(14): {rsi:.1f}
- MACD Histogram: {macd}
- ADX(14): {adx:.1f}
- EMA 20/50/200: {ema_20} / {ema_50} / {ema_200}
- Structure: {'Bullish (price above all EMAs)' if close > ema_20 > ema_50 else 'Bearish (price below all EMAs)' if close < ema_20 < ema_50 else 'Mixed'}
- Regime: {request.current_regime}
{news_block}

RULES:
1. Read EVERY headline. Identify bullish vs bearish for {request.asset}.
2. Weigh source credibility (Reuters/CNBC > blogs).
3. Cross-reference news with technical data.
4. If mixed signals, say NEUTRAL with LOW confidence. Never force a direction.

Respond ONLY with this JSON:
{{"bias": "LONG" or "SHORT" or "NEUTRAL", "confidence": 0.0-1.0, "headline_summary": "2-3 sentence analysis", "bullish_factors": ["factor1"], "bearish_factors": ["factor1"], "key_risk": "biggest risk", "news_impact": "strong_bullish" or "mild_bullish" or "neutral" or "mild_bearish" or "strong_bearish", "conviction_reason": "why this direction"}}"""

    async def _gemini_analysis(self, request, indicators, headlines):
        prompt = self._build_prompt(request, indicators, headlines)

        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(
                f"{GEMINI_URL}?key={settings.gemini_api_key}",
                json={
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {
                        "temperature": 0.3,
                        "maxOutputTokens": 500,
                        "responseMimeType": "application/json",
                    },
                },
            )
            resp.raise_for_status()
            data = resp.json()

        text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
        result = json.loads(text)

        return self._build_output(request, result, headlines, "gemini-2.5-flash")

    async def _claude_fallback(self, request, indicators, headlines):
        prompt = self._build_prompt(request, indicators, headlines)

        async with httpx.AsyncClient(timeout=15) as client:
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
        start = text.find("{")
        end = text.rfind("}") + 1
        result = json.loads(text[start:end]) if start >= 0 else json.loads(text)

        return self._build_output(request, result, headlines, "claude-haiku-4.5-fallback")

    def _build_output(self, request, result, headlines, model_name):
        bias = result.get("bias", "NEUTRAL")
        confidence = min(1.0, max(0.0, float(result.get("confidence", 0.5))))

        evidence_list = [
            Evidence(
                claim=result.get("headline_summary", "AI sentiment analysis"),
                data_point=f"News impact: {result.get('news_impact', 'unknown')}",
                weight=0.8,
            ),
        ]

        if headlines:
            sources = ', '.join(set(h.get('source', '') for h in headlines[:3] if h.get('source')))
            evidence_list.append(Evidence(
                claim=f"Analyzed {len(headlines)} real-time headlines from {sources}",
                data_point=result.get("conviction_reason", ""),
                weight=0.6,
            ))

        for f in result.get("bullish_factors", [])[:2]:
            evidence_list.append(Evidence(claim=f"Bullish: {f}", data_point="news", weight=0.4))
        for f in result.get("bearish_factors", [])[:2]:
            evidence_list.append(Evidence(claim=f"Bearish: {f}", data_point="news", weight=0.4))

        risk_notes = [result["key_risk"]] if result.get("key_risk") else []

        return self._make_output(
            request=request, bias=bias, confidence=confidence,
            evidence=evidence_list, risk_notes=risk_notes,
            urgency="NEXT_BAR",
            meta={
                "model": model_name,
                "news_count": len(headlines),
                "news_impact": result.get("news_impact", "unknown"),
                "bullish_factors": result.get("bullish_factors", []),
                "bearish_factors": result.get("bearish_factors", []),
                "conviction": result.get("conviction_reason", ""),
            },
        )

    def _regime_based_sentiment(self, request):
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
            risk_notes=["No AI analysis available - regime fallback only"],
            meta={"model": "regime_fallback", "news_count": 0},
        )

    async def respond_to_challenge(self, challenge, original_output):
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
            response="REJECT", justification="AI sentiment analysis maintained",
        )
