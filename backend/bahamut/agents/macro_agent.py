"""Macro Agent - AI-powered macro/geopolitical analysis via Gemini + Claude fallback."""
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


class MacroAgent(BaseAgent):
    agent_id = "macro_agent"
    display_name = "Macro / Rates"
    required_features = ["macro_data", "volatility_data", "regime"]
    timeout_seconds = 20

    async def analyze(self, request: SignalCycleRequest, features: dict) -> AgentOutputSchema:
        macro = features.get("macro", {})
        vol = features.get("volatility", {})
        indicators = features.get("indicators", {})

        vix = vol.get("vix", 20)
        dxy = macro.get("dxy", 100)
        us10y = macro.get("us10y", 4.0)
        us2y = macro.get("us2y", 4.5)
        spread = us10y - us2y
        regime = request.current_regime
        close = indicators.get("close", 0)
        ema_200 = indicators.get("ema_200", 0)

        context = {
            "asset": request.asset, "asset_class": request.asset_class, "regime": regime,
            "vix": round(vix, 1), "dxy": round(dxy, 2),
            "us10y": round(us10y, 2), "us2y": round(us2y, 2), "yield_spread": round(spread, 2),
            "price": round(close, 5) if close else 0,
            "above_200ema": close > ema_200 if close and ema_200 else None,
        }

        # Inject deterministic news impact
        news_impact = self._get_news_impact(request.asset, request.asset_class)
        if news_impact.get("impact_score", 0) > 0.1:
            context["news_impact_score"] = news_impact.get("impact_score", 0)
            context["news_directional_bias"] = news_impact.get("directional_bias", "NEUTRAL")
            context["news_shock_level"] = news_impact.get("shock_level", "NONE")
            context["news_freeze"] = news_impact.get("freeze_trading", False)

        news = await self._fetch_macro_news(request.asset)

        # Try AI analysis (Gemini -> Claude -> math fallback)
        ai_result = None
        gemini_key = settings.gemini_api_key or os.environ.get('GEMINI_API_KEY', '')
        if gemini_key:
            try:
                ai_result = await self._gemini_macro(context, news, gemini_key)
            except Exception as e:
                logger.error("macro_gemini_failed", error=str(e))

        if not ai_result and settings.anthropic_api_key:
            try:
                ai_result = await self._claude_macro(context, news)
            except Exception as e:
                logger.error("macro_claude_failed", error=str(e))

        if ai_result:
            return self._build_ai_output(request, ai_result, context)
        return self._math_fallback(request, features, context)

    async def _fetch_macro_news(self, asset: str) -> list[str]:
        try:
            from bahamut.ingestion.adapters.news import news_adapter
            articles = await news_adapter.get_asset_news(asset, count=10)
            return [a.get("title", "") for a in articles if a.get("title")]
        except Exception:
            return []

    def _get_news_impact(self, asset: str, asset_class: str) -> dict:
        """Get deterministic news impact assessment for macro context."""
        try:
            from bahamut.intelligence.news_impact import compute_news_impact_sync
            nia = compute_news_impact_sync(asset, asset_class)
            return nia.to_dict()
        except Exception:
            return {}

    async def _gemini_macro(self, context: dict, news: list, api_key: str) -> dict:
        prompt = self._build_prompt(context, news)
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(
                f"{GEMINI_URL}?key={api_key}",
                json={"contents": [{"parts": [{"text": prompt}]}],
                      "generationConfig": {"temperature": 0.2, "maxOutputTokens": 500}},
            )
            resp.raise_for_status()
            data = resp.json()
        text = data["candidates"][0]["content"]["parts"][0]["text"]
        return self._parse_json(text)

    async def _claude_macro(self, context: dict, news: list) -> dict:
        prompt = self._build_prompt(context, news)
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={"x-api-key": settings.anthropic_api_key,
                         "anthropic-version": "2023-06-01", "content-type": "application/json"},
                json={"model": "claude-sonnet-4-20250514", "max_tokens": 500,
                      "messages": [{"role": "user", "content": prompt}]},
            )
            resp.raise_for_status()
            data = resp.json()
        return self._parse_json(data["content"][0]["text"])

    def _build_prompt(self, ctx: dict, news: list) -> str:
        news_txt = "\n".join(f"- {h}" for h in news[:8]) if news else "No recent news."
        return f"""You are a macro-economic analyst for an AI trading system. Analyze the macro environment for {ctx['asset']} ({ctx['asset_class']}).

MACRO DATA:
- VIX: {ctx['vix']} | DXY: {ctx['dxy']} | US 10Y: {ctx['us10y']}% | US 2Y: {ctx['us2y']}%
- Yield spread (10Y-2Y): {ctx['yield_spread']}% | Regime: {ctx['regime']}
- Price vs 200 EMA: {"ABOVE" if ctx['above_200ema'] else "BELOW" if ctx['above_200ema'] is not None else "N/A"}

RECENT NEWS:
{news_txt}

Respond ONLY with JSON (no markdown):
{{"direction":"LONG/SHORT/NEUTRAL","confidence":0.0-1.0,"reasoning":"1-2 sentence thesis","key_factors":["f1","f2","f3"],"risk_notes":["r1"],"urgency":"URGENT/PATIENT"}}"""

    def _parse_json(self, text: str) -> dict:
        text = text.strip()
        if "```" in text:
            text = text.split("```")[1].lstrip("json\n")
        start, end = text.find("{"), text.rfind("}") + 1
        if start >= 0 and end > start:
            return json.loads(text[start:end])
        raise ValueError("No JSON found")

    def _build_ai_output(self, request, ai: dict, ctx: dict) -> AgentOutputSchema:
        direction = ai.get("direction", "NEUTRAL")
        confidence = min(0.90, max(0.30, float(ai.get("confidence", 0.5))))
        evidence = [Evidence(claim=ai.get("reasoning", "AI macro analysis"),
                             data_point=f"VIX={ctx['vix']}, DXY={ctx['dxy']}", weight=0.9)]
        for f in ai.get("key_factors", [])[:3]:
            evidence.append(Evidence(claim=f, data_point="AI analysis", weight=0.7))

        return self._make_output(
            request=request, bias=direction, confidence=confidence,
            evidence=evidence, risk_notes=ai.get("risk_notes", []),
            urgency=ai.get("urgency", "PATIENT"),
            meta={"ai_model": "gemini_or_claude", "vix": ctx["vix"], "dxy": ctx["dxy"], "spread": ctx["yield_spread"]},
        )

    def _math_fallback(self, request, features, ctx) -> AgentOutputSchema:
        score, evidence, risk_notes = 0, [], []
        spread, vix, dxy = ctx["yield_spread"], ctx["vix"], ctx["dxy"]

        if spread < -0.2:
            evidence.append(Evidence(claim="Yield curve inverted", data_point=f"spread={spread:.2f}%", weight=0.9))
            score -= 20
        elif spread > 0.5:
            evidence.append(Evidence(claim="Yield curve steep", data_point=f"spread={spread:.2f}%", weight=0.7))
            score += 15
        if request.asset_class == "fx":
            if dxy > 105: score -= 20
            elif dxy < 100: score += 20
        if vix > 30: score -= 15; risk_notes.append(f"VIX elevated ({vix:.1f})")
        elif vix < 15: score += 10
        if ctx.get("above_200ema"): score += 8
        elif ctx.get("above_200ema") is False: score -= 8

        if score > 5: bias, conf = "LONG", min(0.85, 0.40 + score / 60 * 0.45)
        elif score < -5: bias, conf = "SHORT", min(0.85, 0.40 + abs(score) / 60 * 0.45)
        else: bias, conf = "NEUTRAL", 0.35

        return self._make_output(request=request, bias=bias, confidence=conf,
                                  evidence=evidence, risk_notes=risk_notes, urgency="PATIENT",
                                  meta={"ai_model": "math_fallback", "vix": vix, "dxy": dxy})

    async def respond_to_challenge(self, challenge: ChallengeRequest, original_output: AgentOutputSchema) -> ChallengeResponseSchema:
        return ChallengeResponseSchema(
            challenge_id=challenge.challenge_id, challenger=challenge.challenger,
            target_agent=self.agent_id, challenge_type=challenge.challenge_type,
            response="REJECT", justification="Macro fundamentals take precedence over shorter-term signals",
        )
