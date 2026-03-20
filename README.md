# Bahamut.AI — Adaptive AI Trading Intelligence Platform

Bahamut is a multi-agent AI trading intelligence system that scans 219 financial assets, runs 6 specialized AI agents to produce consensus trading signals, manages portfolio risk through a 10-step evaluation pipeline, and continuously learns from its own trade outcomes.

The system combines **Gemini 2.5 Flash** and **Claude** as dual AI providers with pure mathematical analysis, a challenge/debate system where agents argue against each other, and a self-learning feedback loop that evolves trust scores based on real performance.

**Live:**
- **Frontend:** [bahamut.ai](https://bahamut.ai)
- **Admin Panel:** [admin.bahamut.ai](https://admin.bahamut.ai)
- **API:** [api.bahamut.ai](https://api.bahamut.ai)

---

## System Stats

| Metric | Value |
|--------|-------|
| Backend Python files | 122 |
| Backend LOC | ~19,700 |
| Frontend + Admin TSX/TS LOC | ~6,300 |
| API endpoints | 128 |
| Database tables | 27 |
| Config parameters | 54 |
| Test cases | 290 (282 passing) |
| Scanner assets | 219 |
| Agent signal assets | 76 |
| AI providers | 2 (Gemini + Claude) |
| Frontend pages | 13 |
| Admin pages | 18 |
| Railway services | 8 |

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Market Data Layer                           │
│  Twelve Data (219 assets) · Finnhub (news) · Forex Factory (cal)  │
└────────────────────────────┬────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│                   Asset Scanner (every 15 min)                     │
│  219 assets: 27 FX · 7 Commodities · 40 Crypto · 145 Stocks      │
│  RSI · EMA · MACD · ADX · Bollinger · Whale detection · Volume    │
│  → Top 20 auto-trigger deep AI analysis                           │
└────────────────────────────┬────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│               6 AI Agents (parallel, 20s timeout)                  │
│                                                                     │
│  🤖 Macro Agent ──────── Gemini AI reads news + macro data         │
│  🤖 Sentiment Agent ──── Gemini + Claude dual-model (parallel)     │
│  📊 Technical Agent ──── RSI, EMA, MACD, ADX, chart patterns       │
│  📊 Volatility Agent ─── ATR, Bollinger, VIX regime                │
│  📊 Liquidity Agent ──── Volume, whale detection, order flow       │
│  🛡️ Risk Agent ─────────  Absolute veto authority, portfolio flags  │
│                                                                     │
│  Agents challenge each other → debate → consensus                  │
└────────────────────────────┬────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    Consensus Engine                                 │
│  Trust-weighted scoring · Disagreement analysis · Floor logic      │
│                                                                     │
│  🤖 AI Consensus Reviewer (Gemini + Claude parallel)               │
│     - Reviews borderline decisions (score 0.40-0.80)               │
│     - Circuit breaker per provider (3 fails → 2 min cooldown)      │
│     - 6s hard timeout ceiling · ±0.15 max score adjustment         │
└────────────────────────────┬────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│              Portfolio Intelligence (10-step pipeline)              │
│                                                                     │
│  1. Kill switch check       6. Adaptive rules                      │
│  2. Exposure engine          7. Scenario risk (5 macro scenarios)   │
│  3. Correlation engine       8. Marginal risk                      │
│  4. Fragility scoring        9. Quality ratio                      │
│  5. Impact scoring          10. Final verdict (size/approve/block)  │
└────────────────────────────┬────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│                   Execution Policy                                  │
│  9 hard blockers · 4 soft constraints · Auto-approve toggle        │
│  Dynamic reallocation (close weak → open strong)                   │
└────────────────────────────┬────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│                Paper Trading Engine                                 │
│  Simulated execution · SL/TP/timeout monitoring (every 2 min)      │
│  Position tracking · PnL attribution · Max 10 concurrent positions │
└────────────────────────────┬────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│                   Learning Pipeline                                 │
│  Agent trust updates · Portfolio pattern analysis · Scenario        │
│  outcome learning · Daily/weekly/monthly calibration                │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Asset Universe

### Scanner (219 assets — every 15 min)

| Class | Count | Examples |
|-------|-------|---------|
| FX | 27 | EUR/USD, GBP/JPY, AUD/NZD, CHF/JPY, EUR/CAD... |
| Commodities | 7 | Gold, Silver, WTI Crude, Natural Gas, Platinum, Copper, Palladium |
| Crypto | 40 | BTC, ETH, SOL, BNB, XRP, ADA, DOGE, LINK, TON, SUI, PEPE, RENDER, INJ... |
| Stocks | 145 | Mega Cap, Finance, Healthcare, Consumer, Semis, Cloud, Cybersecurity, EV, Oil, Defense, Airlines, REITs... |

### Agent Signals (76 assets — deep 6-agent analysis)

| Class | Count |
|-------|-------|
| FX | 10 |
| Commodities | 4 |
| Crypto | 15 |
| Stocks | 47 |

---

## AI Intelligence Layer

### Multi-Model Architecture

| Component | Provider | Role |
|-----------|----------|------|
| Macro Agent | Gemini → Claude fallback → math | Reads news, VIX, DXY, yield curve, regime |
| Sentiment Agent | Gemini + Claude **in parallel** | Dual opinion merge: agree/partial/disagree |
| Consensus Reviewer | Gemini + Claude **in parallel** | Reviews borderline decisions ±0.15 |

### AI Consensus Reviewer (`consensus/ai_reviewer.py`)

Async-first architecture with dual interface:

```python
# Async (for async callers)
result = await ai_consensus_review(asset, direction, score, agent_summaries)

# Sync wrapper (for Celery workers)
result = ai_consensus_review_sync(asset, direction, score, agent_summaries)
```

Features:
- Parallel Gemini + Claude via `asyncio.gather()`
- Per-provider circuit breaker (3 failures/5min → 2min cooldown → auto-recovery)
- 5s timeout per provider, 6s hard ceiling
- Latency logging per provider
- Only reviews borderline scores (0.40-0.80)
- Score adjustment clamped to ±0.15
- `GET /trust/ai-reviewer-status` monitoring endpoint

---

## 6 AI Agents

| Agent | Type | Analysis |
|-------|------|----------|
| **Technical** | 📊 Math | RSI, EMA (20/50/200), MACD, ADX, Bollinger Bands |
| **Macro** | 🤖 AI | VIX, DXY, yield curve, regime + news via Gemini/Claude |
| **Volatility** | 📊 Math | ATR, Bollinger width, VIX regime |
| **Sentiment** | 🤖 AI | News + positioning via dual Gemini+Claude |
| **Liquidity** | 📊 Math | Volume, whale detection, unusual activity |
| **Risk** | 🛡️ Math | Portfolio-level veto, absolute authority |

---

## Portfolio Intelligence (10-Step Pipeline)

1. **Kill switch** — blocks all trades if tail risk > 25% or fragility > 80%
2. **Exposure engine** — gross/net/per-class/per-theme limits
3. **Correlation engine** — directional overlap, HHI concentration
4. **Fragility scoring** — concentration, directional risk, drawdown proximity
5. **Impact scoring** — does this trade improve or worsen diversification
6. **Adaptive rules** — learned patterns from historical portfolio states
7. **Scenario risk** — 5 macro scenarios with per-asset shock maps
8. **Marginal risk** — how much risk does this trade ADD
9. **Quality ratio** — expected return vs marginal risk
10. **Final verdict** — size/approve/block with structured explanation

---

## Execution & Safety

### Kill Switch
- Tail risk threshold: 25% (configurable)
- Manual override: 1 hour TTL, logged
- Recovery: 15min cooldown → 30min gradual re-entry

### Execution Modes
- **AUTO** — executes immediately
- **APPROVAL** — requires manual approval
- **WATCH** — logged, not traded

### Position Limits

| Profile | Max Positions | Min Score | Max Daily DD |
|---------|---------------|-----------|--------------|
| Conservative | 5 | 0.65 | 2% |
| Balanced | 10 | 0.55 | 3% |
| Aggressive | 15 | 0.45 | 5% |

---

## Role-Based Access

| Role | Access |
|------|--------|
| **super_admin** | Full access, config editing, role management |
| **admin** | Dashboard, risk, alerts, users, paper trading, agents |
| **trader** | Execution, risk control, journal, paper trading |
| **user** | Command, top picks, macro arena, event radar |

---

## Infrastructure

### Railway Services (8)

| Service | Technology | Purpose |
|---------|-----------|---------|
| API | FastAPI Python 3.12 | 128 endpoints |
| Frontend | Next.js 14 | bahamut.ai (13 pages) |
| Admin Panel | Next.js 14 | admin.bahamut.ai (18 pages) |
| Worker | Celery | Signal cycles, scans, trades |
| Beat | Celery Beat | Scheduled tasks |
| Postgres | PostgreSQL 15 | 27 tables |
| Redis | Redis 7 | Broker + cache |

### Scheduled Tasks

| Task | Frequency |
|------|-----------|
| Signal cycles (FX/Crypto) | 15 min |
| Stock cycles | 30 min (market hours) |
| Market scanner | 15 min |
| Position checker | 2 min |
| OHLCV ingestion | 2 min |
| News monitoring | 2 min |
| Regime detection | 5 min |
| Daily calibration | 00:15 UTC |
| Weekly calibration | Sunday 20:00 UTC |

---

## Frontend Pages (bahamut.ai — 13 pages)

Command · Top Picks · Macro Arena · Event Radar · Execution · Risk Control · Trade Journal · Paper Trading · Intel Reports · Agent Council · Learning Lab · Settings · Login

## Admin Pages (admin.bahamut.ai — 18 pages)

Dashboard · Top Picks · Risk & Kill Switch · Alerts (Active/Archived) · Audit Log · Learning · AI Optimizer · Users · Paper Trading · Agent Council · Learning Lab · Execution Monitor · Trade Journal · Configuration · Overrides · Trust & Intelligence · Adaptive Risk · Agent Ranking

---

## Market Data

### Twelve Data (Grow plan — $29/mo)
- 219 symbols, unlimited credits, 55 req/min
- Global rate limiter at 50/min with auto-throttle
- In-memory cache: 15min candles, 5min prices
- 429 retry with progressive backoff

---

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `DATABASE_URL` | Yes | PostgreSQL connection |
| `REDIS_URL` | Yes | Redis connection |
| `JWT_SECRET` | Yes | JWT signing secret |
| `TWELVE_DATA_KEY` | Yes | Twelve Data API key |
| `FINNHUB_KEY` | Yes | Finnhub API key |
| `GEMINI_API_KEY` | Yes | Google Gemini API key |
| `ANTHROPIC_API_KEY` | Recommended | Anthropic API key |

---

## Getting Started

```bash
# Backend
cd backend && pip install -r requirements.txt
uvicorn bahamut.main:app --host 0.0.0.0 --port 8000
celery -A bahamut.celery_app worker --loglevel=info
celery -A bahamut.celery_app beat --loglevel=info

# Frontend
cd frontend && npm install && npm run dev

# Admin
cd admin-panel && npm install && npm run dev

# Tests
cd backend && PYTHONPATH=. python -m pytest tests/ -v
# 282 passed, 8 skipped
```

---

## Repository Structure

```
bahamut/
├── backend/bahamut/
│   ├── admin/           # Config (54 keys), audit, alerts
│   ├── agents/          # 6 AI agents, orchestrator, challenges
│   │   ├── macro_agent.py      # 🤖 Gemini AI
│   │   ├── sentiment_agent.py  # 🤖 Gemini + Claude dual
│   │   ├── technical_agent.py  # 📊 Math
│   │   ├── volatility_agent.py # 📊 Math
│   │   ├── liquidity_agent.py  # 📊 Math
│   │   └── risk_agent.py       # 🛡️ Veto authority
│   ├── consensus/       # Engine + AI reviewer
│   │   ├── engine.py
│   │   └── ai_reviewer.py      # Async-first, circuit breaker
│   ├── execution/       # Policy, kill switch
│   ├── ingestion/       # Twelve Data (rate limiter), Finnhub
│   ├── intelligence/    # Trust API, adaptive risk
│   ├── learning/        # Calibration, meta-learning
│   ├── paper_trading/   # Engine, SL/TP, positions
│   ├── portfolio/       # 10-step intelligence pipeline
│   └── scanner/         # 219-asset scanner
├── frontend/            # bahamut.ai (13 pages)
├── admin-panel/         # admin.bahamut.ai (18 pages)
└── tests/               # 290 test cases
```

---

## Development Phases

- **Phase 1** ✅ Infrastructure hardening, exception handling, fail-closed
- **Phase 2** ✅ Production safety, single-writer, CORS, health
- **Phase 3** ✅ Productization, warmup, roles, config guardrails
- **Phase 4** ✅ Intelligence layer, explainability, adaptive risk
- **Phase 5** ✅ AI upgrade: dual-model sentiment, AI macro, AI reviewer
- **Phase 6** ✅ Asset expansion: 219 scanner, 76 agents, rate limiting

---

## License

Proprietary. All rights reserved.
