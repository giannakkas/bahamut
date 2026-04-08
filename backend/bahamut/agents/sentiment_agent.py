"""
Sentiment Agent v2 — Cost-optimized AI usage

Fixes from audit:
  1. Default: Gemini ONLY (free tier)
  2. Claude only on: disagreement, high-impact news, or Gemini failure
  3. Removed always-parallel dual-model execution
  4. Cleaner fallback chain: Gemini → Claude → regime-based
"""
from bahamut.agents.base import BaseAgent
from bahamut.agents.schemas import (
    AgentOutputSchema, ChallengeRequest, ChallengeResponseSchema,
    SignalCycleRequest, Evidence,
)
from bahamut.config import get_settings
import structlog
import httpx
import json
import os

logger = structlog.get_logger()
settings = get_settings()

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"


class SentimentAgent(BaseAgent):
    agent_id = "sentiment_agent"
    display_name = "Sentiment / Narrative"
    timeout_seconds = 15

    async def analyze(self, request: SignalCycleRequest, features: dict) -> AgentOutputSchema:
        indicators = features.get("indicators", {})
        news_headlines = await self._fetch_news(request.asset)

        # ── Deterministic news impact (always runs, no AI needed) ──
        news_impact_data = {}
        try:
            from bahamut.intelligence.news_impact import (
                compute_news_impact, dedupe_headlines, cache_news_data,
            )
            deduped = dedupe_headlines(news_headlines)
            # Cache for sync access by training selector
            cache_news_data(request.asset, deduped)
            nia = compute_news_impact(request.asset, request.asset_class, deduped)
            news_impact_data = nia.to_dict()
        except Exception as e:
            logger.debug("sentiment_news_impact_failed", error=str(e)[:80])

        gemini_key = settings.gemini_api_key or os.environ.get('GEMINI_API_KEY', '')
        has_claude = bool(settings.anthropic_api_key)

        # ── PRIMARY: Gemini only (free) ──
        gemini_out = None
        if gemini_key:
            try:
                gemini_out = await self._gemini_analysis(request, indicators, news_headlines, gemini_key)
            except Exception as e:
                logger.error("gemini_failed", error=str(e))

        if gemini_out:
            # Only escalate to Claude if: low confidence OR high-impact news detected
            det_impact = news_impact_data.get("impact_score", 0)
            needs_second_opinion = (
                gemini_out.confidence < 0.45 or
                det_impact >= 0.5 or  # Deterministic: significant news event
                gemini_out.meta.get("news_impact") in ("strong_bullish", "strong_bearish") or
                len(news_headlines) > 5  # Lots of news = important event
            )

            # Inject deterministic news data into output meta
            gemini_out.meta["news_impact_deterministic"] = news_impact_data

            if needs_second_opinion and has_claude:
                try:
                    claude_out = await self._claude_analysis(request, indicators, news_headlines)
                    if claude_out:
                        return self._merge_opinions(gemini_out, claude_out, request)
                except Exception as e:
                    logger.warning("claude_second_opinion_failed", error=str(e))

            return gemini_out

        # ── FALLBACK: Claude only if Gemini totally failed ──
        if has_claude:
            try:
                return await self._claude_analysis(request, indicators, news_headlines)
            except Exception as e:
                logger.error("claude_fallback_failed", error=str(e))

        return self._regime_based_sentiment(request)

    def _merge_opinions(self, gemini: AgentOutputSchema, claude: AgentOutputSchema, request) -> AgentOutputSchema:
        g_bias, c_bias = gemini.directional_bias, claude.directional_bias
        g_conf, c_conf = gemini.confidence, claude.confidence

        if g_bias == c_bias:
            merged_bias = g_bias
            merged_conf = min(0.95, max(g_conf, c_conf) * 1.10)
            agreement = "AGREE"
        elif g_bias == "NEUTRAL" or c_bias == "NEUTRAL":
            merged_bias = g_bias if g_bias != "NEUTRAL" else c_bias
            merged_conf = max(g_conf, c_conf) * 0.85
            agreement = "PARTIAL"
        else:
            merged_bias = "NEUTRAL"
            merged_conf = 0.30
            agreement = "DISAGREE"

        logger.info("sentiment_merge", asset=request.asset,
                     gemini=f"{g_bias}/{g_conf:.2f}", claude=f"{c_bias}/{c_conf:.2f}",
                     merged=f"{merged_bias}/{merged_conf:.2f}", agreement=agreement)

        all_evidence = list(gemini.evidence) + [
            e for e in claude.evidence if e.claim not in [x.claim for x in gemini.evidence]
        ]
        all_risks = list(set(gemini.risk_notes + claude.risk_notes))

        return self._make_output(
            request=request, bias=merged_bias, confidence=round(merged_conf, 3),
            evidence=all_evidence[:6], risk_notes=all_risks[:4],
            urgency=gemini.urgency,
            meta={"ai_model": f"dual({agreement})", "gemini_conf": g_conf, "claude_conf": c_conf},
        )

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
            news_block = "\n\nREAL-TIME NEWS:\n"
            for i, h in enumerate(headlines[:8], 1):
                news_block += f"{i}. [{h.get('source', '?')}] {h['title']}\n"
        else:
            news_block = "\n\nNo news available. Analyze based on technicals and regime only."

        return f"""You are an institutional trading analyst. Analyze sentiment for {request.asset}.

MARKET DATA:
- Price: {close} | RSI: {rsi:.1f} | MACD Hist: {macd} | ADX: {adx:.1f}
- EMA 20/50/200: {ema_20}/{ema_50}/{ema_200}
- Regime: {request.current_regime}
{news_block}

RULES:
1. Read every headline. Identify bullish vs bearish.
2. Weigh source credibility.
3. If mixed signals, say NEUTRAL with LOW confidence.

Respond ONLY with JSON:
{{"bias":"LONG"/"SHORT"/"NEUTRAL","confidence":0.0-1.0,"headline_summary":"2-3 sentences","bullish_factors":["f1"],"bearish_factors":["f1"],"key_risk":"biggest risk","news_impact":"strong_bullish"/"mild_bullish"/"neutral"/"mild_bearish"/"strong_bearish","conviction_reason":"why"}}"""

    async def _gemini_analysis(self, request, indicators, headlines, api_key):
        prompt = self._build_prompt(request, indicators, headlines)
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{GEMINI_URL}?key={api_key}",
                json={"contents": [{"parts": [{"text": prompt}]}],
                      "generationConfig": {"temperature": 0.3, "maxOutputTokens": 500,
                                            "responseMimeType": "application/json"}},
            )
            resp.raise_for_status()
            data = resp.json()
        text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
        result = json.loads(text)
        return self._build_output(request, result, headlines, "gemini-2.5-flash")

    async def _claude_analysis(self, request, indicators, headlines):
        prompt = self._build_prompt(request, indicators, headlines)
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={"x-api-key": settings.anthropic_api_key,
                         "anthropic-version": "2023-06-01", "content-type": "application/json"},
                json={"model": "claude-haiku-4-5-20251001", "max_tokens": 500,
                      "messages": [{"role": "user", "content": prompt}]},
            )
            resp.raise_for_status()
            data = resp.json()
        text = data["content"][0]["text"].strip()
        start, end = text.find("{"), text.rfind("}") + 1
        result = json.loads(text[start:end]) if start >= 0 else json.loads(text)
        return self._build_output(request, result, headlines, "claude-haiku-4.5")

    def _build_output(self, request, result, headlines, model_name):
        bias = result.get("bias", "NEUTRAL")
        confidence = min(1.0, max(0.0, float(result.get("confidence", 0.5))))
        evidence_list = [
            Evidence(claim=result.get("headline_summary", "AI sentiment analysis"),
                     data_point=f"Impact: {result.get('news_impact', 'unknown')}", weight=0.8),
        ]
        if headlines:
            sources = ', '.join(set(h.get('source', '') for h in headlines[:3] if h.get('source')))
            evidence_list.append(Evidence(
                claim=f"Analyzed {len(headlines)} headlines from {sources}",
                data_point=result.get("conviction_reason", ""), weight=0.6,
            ))
        for f in result.get("bullish_factors", [])[:2]:
            evidence_list.append(Evidence(claim=f"Bullish: {f}", data_point="news", weight=0.4))
        for f in result.get("bearish_factors", [])[:2]:
            evidence_list.append(Evidence(claim=f"Bearish: {f}", data_point="news", weight=0.4))

        return self._make_output(
            request=request, bias=bias, confidence=confidence,
            evidence=evidence_list,
            risk_notes=[result["key_risk"]] if result.get("key_risk") else [],
            urgency="NEXT_BAR",
            meta={"model": model_name, "news_count": len(headlines),
                  "news_impact": result.get("news_impact", "unknown"),
                  "bullish_factors": result.get("bullish_factors", []),
                  "bearish_factors": result.get("bearish_factors", [])},
        )

    def _regime_based_sentiment(self, request):
        regime_map = {
            "RISK_ON": ("LONG", 0.50, "Risk-on regime suggests mild positive sentiment"),
            "RISK_OFF": ("SHORT", 0.50, "Risk-off regime suggests negative sentiment"),
            "HIGH_VOL": ("NEUTRAL", 0.35, "High volatility — mixed sentiment"),
            "LOW_VOL": ("NEUTRAL", 0.40, "Low volatility — no strong narrative"),
            "CRISIS": ("SHORT", 0.60, "Crisis regime — strong negative sentiment"),
            "TREND_CONTINUATION": ("LONG", 0.45, "Trend continuation — mildly positive"),
        }
        bias, conf, claim = regime_map.get(request.current_regime, ("NEUTRAL", 0.35, "No clear sentiment"))
        return self._make_output(
            request=request, bias=bias, confidence=conf,
            evidence=[Evidence(claim=claim, data_point=f"Regime={request.current_regime}", weight=0.5)],
            risk_notes=["No AI analysis — regime fallback"],
            meta={"model": "regime_fallback", "news_count": 0},
        )

    async def respond_to_challenge(self, challenge, original_output):
        if challenge.challenge_type == "NARRATIVE_SHOCK":
            return ChallengeResponseSchema(
                challenge_id=challenge.challenge_id, challenger=challenge.challenger,
                target_agent=self.agent_id, challenge_type=challenge.challenge_type,
                response="ACCEPT", revised_confidence=max(0.2, original_output.confidence - 0.3),
                justification="Narrative shock acknowledged",
            )
        return ChallengeResponseSchema(
            challenge_id=challenge.challenge_id, challenger=challenge.challenger,
            target_agent=self.agent_id, challenge_type=challenge.challenge_type,
            response="REJECT", justification="Sentiment analysis maintained",
        )
