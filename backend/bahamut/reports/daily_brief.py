"""
AI-Generated Daily Market Brief using Gemini 2.5 Flash.
Pulls real market data, news, and cycle results to generate
a comprehensive morning brief for traders.
"""
import json
import httpx
import structlog
from datetime import datetime, timezone
from bahamut.config import get_settings
from bahamut.ingestion.adapters.news import news_adapter, econ_calendar

logger = structlog.get_logger()
settings = get_settings()


async def generate_daily_brief() -> dict:
    """Generate a comprehensive AI market brief."""

    # Gather all data
    news = await news_adapter.get_headlines("general", 10)
    events = await econ_calendar.get_upcoming_events(3)

    # Get latest cycle results from Redis
    cycle_summaries = []
    try:
        import redis
        r = redis.from_url(settings.redis_url)
        for asset in ["EURUSD", "GBPUSD", "USDJPY", "XAUUSD", "BTCUSD", "ETHUSD", "AAPL", "TSLA", "NVDA", "META"]:
            cached = r.get(f"bahamut:latest_cycle:{asset}")
            if cached:
                cycle = json.loads(cached)
                d = cycle.get("decision", {})
                if d:
                    cycle_summaries.append(f"{asset}: {d.get('direction','?')} (score={d.get('final_score',0):.2f}, {d.get('decision','?')})")
        r.close()
    except Exception:
        pass

    # Build context for Gemini
    news_text = "\n".join([f"- [{a.get('source','')}] {a.get('title','')}" for a in news[:8]])
    events_text = "\n".join([f"- {e.get('event','')} ({e.get('currency','')}) Impact: {e.get('impact','')} | Forecast: {e.get('estimate','')} | Previous: {e.get('prev','')}" for e in events[:10] if (e.get('impact','') or '').lower() == 'high'])
    signals_text = "\n".join(cycle_summaries) if cycle_summaries else "No signal cycles available yet."

    now = datetime.now(timezone.utc)

    prompt = f"""You are the Chief Market Strategist at Bahamut.AI, an institutional AI trading platform. Write today's morning market brief for professional traders.

DATE: {now.strftime('%A, %B %d, %Y')} (UTC)

LATEST REAL-TIME NEWS:
{news_text or "No news available."}

HIGH IMPACT ECONOMIC EVENTS (next 3 days):
{events_text or "No high impact events scheduled."}

AI AGENT SIGNAL CYCLE RESULTS:
{signals_text}

Write a professional morning brief covering:
1. MARKET OVERVIEW (2-3 sentences on overall market conditions)
2. KEY MOVERS (which assets/events are driving markets today)
3. SIGNAL SUMMARY (interpret the AI agent results - what are they saying collectively?)
4. RISK EVENTS (upcoming events traders should watch)
5. TRADING OUTLOOK (1-2 sentences on the day ahead)

Keep it concise and actionable. No fluff. Traders are busy.

Respond ONLY with this JSON:
{{"overview": "...", "key_movers": "...", "signal_summary": "...", "risk_events": "...", "outlook": "...", "regime_assessment": "RISK_ON or RISK_OFF or MIXED"}}"""

    # Try Gemini
    gemini_key = settings.gemini_api_key or __import__('os').environ.get('GEMINI_API_KEY', '')
    if gemini_key:
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                resp = await client.post(
                    f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={gemini_key}",
                    json={
                        "contents": [{"parts": [{"text": prompt}]}],
                        "generationConfig": {
                            "temperature": 0.4,
                            "maxOutputTokens": 800,
                            "responseMimeType": "application/json",
                        },
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                text = data["candidates"][0]["content"]["parts"][0]["text"]
                result = json.loads(text)
                logger.info("daily_brief_generated", model="gemini")
                return {
                    "date": now.strftime("%Y-%m-%d"),
                    "generated_at": now.isoformat(),
                    "model": "gemini-2.5-flash",
                    "regime": result.get("regime_assessment", "MIXED"),
                    **result,
                    "signals_analyzed": len(cycle_summaries),
                    "news_analyzed": len(news),
                    "events_upcoming": len([e for e in events if (e.get('impact','') or '').lower() == 'high']),
                }
        except Exception as e:
            logger.error("gemini_brief_failed", error=str(e))

    # Fallback: structured brief without AI
    return {
        "date": now.strftime("%Y-%m-%d"),
        "generated_at": now.isoformat(),
        "model": "template",
        "regime": "MIXED",
        "overview": f"Market brief for {now.strftime('%B %d, %Y')}. {len(news)} news articles analyzed, {len(cycle_summaries)} signal cycles completed.",
        "key_movers": ", ".join([a.get("title", "")[:50] for a in news[:3]]) if news else "No major movers identified.",
        "signal_summary": "; ".join(cycle_summaries[:5]) if cycle_summaries else "No signals generated yet. Cycles run every 15 minutes.",
        "risk_events": f"{len([e for e in events if (e.get('impact','') or '').lower() == 'high'])} high-impact events in next 3 days.",
        "outlook": "Monitor scheduled events and breaking news for trading opportunities.",
        "signals_analyzed": len(cycle_summaries),
        "news_analyzed": len(news),
        "events_upcoming": len(events),
    }
