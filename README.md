# BAHAMUT.AI

**Institutional-Grade AI Trading Intelligence Platform**

Multi-agent AI system where 11 specialized agents analyze markets, debate internally, reach weighted consensus, and continuously self-calibrate from trade outcomes.

---

## Architecture

```
DATA → AGENT ANALYSIS → AGENT DEBATE → CONSENSUS → SIGNAL → EXECUTION → OUTCOME → LEARNING → RECALIBRATION
```

**Agents:** Macro, Flow, Volatility, Options/Gamma, Liquidity/Structure, Sentiment/Narrative, Technical/Timing, Risk (veto power), Execution, Learning, Supervisor/Consensus

**Profiles:** Conservative | Balanced | Aggressive — each deeply modifies thresholds, risk limits, agent weights, and execution behavior

**Modes:** Auto-Trade (11 safety gates) | Approval Required (full trade cards)

---

## Quick Start

```bash
# 1. Clone and configure
cp .env.example .env
# Edit .env with your API keys

# 2. Start everything
make up

# 3. Verify
make health

# 4. Access
# Frontend: http://localhost:3000
# API:      http://localhost:8000
# API Docs: http://localhost:8000/docs
```

## Key Commands

```bash
make up              # Start all services
make down            # Stop all services
make logs            # Follow all logs
make logs-api        # Follow API logs only
make logs-worker     # Follow Celery worker logs
make cycle           # Manually trigger signal cycle for all assets
make cycle-single    # Trigger cycle for EURUSD only
make db-shell        # PostgreSQL shell
make redis-shell     # Redis CLI
make migrate         # Run database migrations
make reset           # Full reset (wipes database)
make health          # Check API health
```

## Project Structure

```
bahamut/
├── backend/
│   ├── bahamut/
│   │   ├── main.py              # FastAPI app
│   │   ├── celery_app.py        # Celery + beat schedule
│   │   ├── config.py            # Pydantic Settings
│   │   ├── database.py          # SQLAlchemy async engine
│   │   ├── models.py            # All 20+ database tables
│   │   ├── auth/                # JWT auth, registration, RBAC
│   │   ├── agents/              # Agent framework + implementations
│   │   │   ├── base.py          # BaseAgent ABC
│   │   │   ├── orchestrator.py  # 7-round consensus cycle
│   │   │   ├── technical_agent.py
│   │   │   ├── macro_agent.py
│   │   │   ├── risk_agent.py
│   │   │   └── schemas.py       # Pydantic models for all agent I/O
│   │   ├── consensus/
│   │   │   ├── engine.py        # Weighted consensus algorithm
│   │   │   └── trust_store.py   # Multi-dimensional trust scores
│   │   ├── execution/           # Auto-trade pipeline + kill switch
│   │   ├── learning/            # Trust updates, calibration, regime memory
│   │   ├── risk/                # Drawdown, correlation, circuit breakers
│   │   ├── reports/             # AI-generated briefs
│   │   ├── ws/                  # WebSocket gateway + Redis pub/sub
│   │   └── ingestion/           # Data source adapters
│   ├── alembic/                 # Database migrations
│   └── tests/
├── frontend/
│   ├── src/
│   │   ├── app/                 # Next.js pages (10 modules)
│   │   ├── components/          # React components (70+)
│   │   ├── stores/              # Zustand state management
│   │   ├── lib/                 # API client, types, WebSocket
│   │   └── styles/              # Design system CSS
│   └── tailwind.config.ts       # Institutional dark theme
├── docker-compose.yml
├── Makefile
└── .env.example
```

## Tech Stack

| Layer | Technology |
|-------|-----------|
| API | FastAPI + Uvicorn |
| Database | PostgreSQL 16 + TimescaleDB |
| Cache | Redis 7 |
| Task Queue | Celery + Redis |
| Frontend | Next.js 14 + React + TypeScript |
| Styling | Tailwind CSS (dark institutional theme) |
| Charts | Lightweight Charts + Recharts |
| State | Zustand |
| AI/LLM | Anthropic Claude API |
| Deployment | Docker Compose → Railway |

## API Endpoints

| Group | Key Routes |
|-------|-----------|
| Auth | `POST /auth/register`, `POST /auth/login`, `GET /auth/me` |
| Agents | `POST /agents/trigger`, `GET /agents/trust-scores` |
| Consensus | `GET /consensus/thresholds`, `GET /consensus/weights/:class` |
| Execution | `POST /execution/kill-switch`, `GET /execution/status` |
| Risk | `GET /risk/dashboard` |
| Learning | `GET /learning/trust-scores`, `POST /learning/emergency-recalibrate` |
| Reports | `GET /reports/daily-brief` |
| WebSocket | `ws://localhost:8000/ws?token=JWT` |

## MVP Status

**Working now:**
- Full database schema (20+ tables with relationships)
- JWT authentication with registration and login
- 3 agent implementations (Macro, Technical, Risk with veto)
- 7-round consensus cycle (independent → conflict → challenge → consensus)
- Weighted consensus algorithm with trust scores and regime relevance
- Multi-dimensional trust score store with asymmetric learning rates
- Celery beat scheduling (15-min signal cycles + daily/weekly/monthly calibration)
- WebSocket gateway with Redis pub/sub
- Risk dashboard API with drawdown and circuit breaker state
- Kill switch endpoint
- Dark institutional frontend with dashboard, sidebar nav, and 10 page stubs
- Docker Compose (PostgreSQL + TimescaleDB + Redis + API + Worker + Beat + Frontend)

**Next to build:**
- Real market data ingestion (OANDA / Twelve Data adapters)
- Feature engineering service (indicator computation from live data)
- Remaining 8 agents (Flow, Volatility, Options, Liquidity, Sentiment, Execution, Learning, full Supervisor)
- Trade card approval UI
- Trade execution + broker integration
- Full learning loop (post-trade attribution → trust updates → threshold recalibration)
- Agent Council interactive frontend page
- Regime memory engine with cosine similarity

---

*Built for serious traders and funds. Not a toy. Not a dashboard.*
