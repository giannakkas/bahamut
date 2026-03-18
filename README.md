# Bahamut.AI — Adaptive Portfolio Intelligence and Trading Control Platform

Bahamut is a multi-agent portfolio intelligence system that analyzes financial markets, produces consensus trading signals, manages portfolio risk in real time, and learns from its own outcomes to improve over time.

It runs 6 independent AI agents across 45+ assets (FX, crypto, equities, commodities), forces them to debate and challenge each other, computes weighted consensus, evaluates every proposed trade against the full portfolio context, and decides whether to execute, reduce, or block — with structured explanations for every decision.

**Live system:** [frontend-production-947b.up.railway.app](https://frontend-production-947b.up.railway.app)
**API:** [bahamut-production.up.railway.app](https://bahamut-production.up.railway.app)

---

## Overview

Most trading systems evaluate signals in isolation. A strong buy signal on BTCUSD might look good on its own, but if the portfolio is already 40% crypto, adding more concentrates risk instead of diversifying it.

Bahamut solves this by treating signal generation and portfolio management as a single integrated system. Every proposed trade passes through a 10-step portfolio evaluation pipeline before it can execute. The system tracks how its decisions perform, identifies patterns in portfolio states that correlate with losses, and automatically adjusts its behavior.

The platform is designed as a paper trading and analysis system. It generates and evaluates signals but does not connect to live brokers. Execution is simulated through a paper trading engine with full PnL tracking, learning attribution, and performance analytics.

---

## Key Capabilities

### Multi-Agent Analysis

Six specialized agents independently analyze each asset:

- **Technical Agent** — price action, indicators, chart patterns
- **Macro Agent** — economic data, interest rates, macro regime
- **Volatility Agent** — VIX, implied vol, volatility regime
- **Sentiment Agent** — news sentiment, market positioning
- **Liquidity Agent** — volume, spread, market depth
- **Risk Agent** — absolute authority veto, portfolio-level flags

Agents run concurrently with 15-second timeouts. Each produces a directional bias (LONG/SHORT/NEUTRAL) with a confidence score and supporting evidence. Agents then challenge each other's conclusions before consensus is computed.

### Consensus Engine

Agent outputs are weighted by four factors multiplied together:

`effective_weight = base_weight * trust_score * regime_factor * timeframe_factor`

Trust scores evolve with every trade outcome — agents that are consistently right gain influence, agents that are wrong lose it. The system detects when all trust scores are low and applies aggregate dampening to prevent the normalization from cancelling out individual unreliability.

A disagreement engine computes a 5-component disagreement index. High disagreement can force approval-only mode or block execution entirely.

### Portfolio Intelligence

Every proposed trade passes through a 10-step evaluation pipeline:

1. **Kill switch check** — block all trades if portfolio stress is extreme
2. **Exposure engine** — gross/net/per-class/per-theme exposure limits
3. **Correlation engine** — directional overlap, HHI concentration, same-class detection
4. **Fragility scoring** — concentration risk, directional risk, drawdown proximity
5. **Impact scoring** — does this trade improve or worsen portfolio diversification
6. **Adaptive rules** — learned patterns from historical portfolio states
7. **Scenario risk** — weighted simulation across 5 macro scenarios
8. **Marginal risk** — how much risk does this specific trade ADD to the portfolio
9. **Quality ratio** — expected return vs marginal risk
10. **Final verdict** — combine all constraints, produce size/approval/block decision

### Scenario Risk Engine

Five predefined macro scenarios simulate portfolio PnL under stress:

- **Risk-off** — flight to safety, equity and crypto selloff
- **Risk-on** — broad risk appetite, safe havens weaken
- **Volatility spike** — amplified moves, high-beta hit hardest
- **USD shock** — sudden dollar weakness
- **Crypto shock** — cascading liquidations, DeFi contagion

Each scenario applies per-asset shock percentages (30+ assets mapped) to all open positions plus the proposed trade. Scenarios are probability-weighted (configurable), producing weighted tail risk, weighted expected stress, and top contributor analysis.

### Self-Learning System

The system learns at three levels:

**Agent trust evolution** — per-agent, per-regime, per-asset-class trust scores updated after every trade closes. Asymmetric: wrong costs more than right rewards. High-confidence wrong answers receive extra penalties.

**Portfolio pattern learning** — captures portfolio state (exposure, fragility, concentration, drawdown) at trade entry and exit. Daily analysis identifies patterns such as "trades opened when fragility > 0.5 have a 27% win rate" and generates adaptive rules that modify future sizing.

**Scenario outcome learning** — tracks whether scenario risk warnings at entry correlated with actual trade outcomes. Identifies combined patterns such as "high theme concentration + scenario stress leads to accelerated losses."

### Execution Policy

Nine hard blockers and four soft constraints evaluated on every trade:

Hard blockers: risk veto, daily drawdown, weekly drawdown, max positions, duplicate asset, score floor, disagreement blocked, crisis + conservative, hard risk flags.

Soft constraints: crisis size reduction, disagreement approval-only, correlation size reduction, exposure size reduction. System confidence (composite of trust stability, disagreement trend, recent performance, calibration health) gates execution at three levels.

### Dynamic Capital Allocation

When the portfolio is full (max positions reached) and a strong signal arrives, the system evaluates whether to reallocate:

- Every open position is scored on a 0-1 quality scale (signal quality, PnL trajectory, risk/reward, time decay, momentum)
- The proposed trade is scored on the same scale
- If the proposed trade materially outscores the weakest position (minimum 0.20 margin), the weakest is closed and capital is reallocated
- Throttled to 3 reallocations per hour to prevent churn

### Kill Switch and Safe Mode

Portfolio-level emergency protections:

- **Hard kill switch** — blocks all new trades when weighted tail risk exceeds threshold, fragility exceeds threshold, or combined stress exceeds threshold
- **Safe mode** — tightens limits (2 max trades, 1% max position) when fragility is elevated but not critical
- **Deleveraging** — recommends closing weakest positions when portfolio stress is extreme

### Decision Explainability

Every trade decision produces a structured explanation with 7 factors: trust, disagreement, regime, risk, system confidence, calibration, and agreement. Each factor includes a status (high/low/blocked), numeric value, impact classification (positive/negative/blocking), and human-readable detail text. A narrative string summarizes the reasoning.

### Admin Configuration

52 tunable system constants consolidated into a central configuration service:

- Scenario weights and tail risk thresholds
- Marginal risk and quality ratio thresholds
- Exposure limits (gross, net, class, theme, asset)
- Kill switch and safe mode triggers
- Allocator rules (quality thresholds, reallocation margins)
- Profile limits (drawdown, position count, score floors)
- Readiness check thresholds

All config is persisted to database with type validation, default values, and a versioned audit log.

---

## Architecture

### Infrastructure

| Service | Technology | Purpose |
|---------|-----------|---------|
| API | FastAPI (Python 3.12) | REST API, 103 endpoints across 16 modules |
| Worker | Celery | Processes signal cycles, scans, paper trades, learning |
| Beat | Celery Beat | Schedules periodic tasks (ingestion, cycles, calibration) |
| Frontend | Next.js 14 (TypeScript) | Dashboard with 14 pages |
| Database | PostgreSQL | 22 tables, full persistence |
| Cache | Redis | Celery broker, result cache, real-time state |

### Backend Modules

The backend is organized into 20 modules:

| Module | Purpose |
|--------|---------|
| `agents` | 6 AI agents, orchestrator, persistence, challenge system |
| `consensus` | Weighted consensus engine, disagreement, trust store, weights, explainer, system confidence |
| `execution` | Execution policy (9 blockers + soft constraints), kill switch endpoint |
| `portfolio` | Registry, exposure/correlation/fragility engines, scenario risk, marginal risk, quality ratio, capital allocator, kill switch, adaptive learning |
| `learning` | Calibration (daily/weekly/emergency), meta-evaluation, threshold tuning, profile adapter |
| `stress` | Replay-based stress testing (13 scenarios including 5 with per-trace mutators), assessment bridge |
| `readiness` | 13-point trading readiness checklist |
| `admin` | Central config service (52 keys), audit log, admin API |
| `paper_trading` | Simulated execution engine, position management, learning attribution |
| `ingestion` | Market data adapters (Twelve Data, Finnhub), news, OHLCV |
| `scanner` | 45+ asset scanner with scoring |
| `features` | Technical indicators, regime detection |
| `risk` | Risk dashboard, drawdown tracking |

### Frontend Pages

| Page | Content |
|------|---------|
| Command | System overview, active signals, risk status, news feed |
| Agent Council | Signal cycles, agent outputs, challenge log, decision reasoning |
| Learning Lab | 16 panels: trust, fitness, leaderboard, readiness, stress, portfolio exposure, fragility, scenarios, rankings, adaptive rules, reallocation log |
| Paper Trading | Positions, PnL tracking, trade history |
| Risk Control | Drawdown limits, exposure, circuit breakers |
| Top Picks | Scanner results, ranked opportunities |
| Execution | Kill switch, policy config, execution status |

### Data Flow

```
Market Data (Twelve Data, Finnhub)
    |
    v
Feature Computation (indicators, regime detection)
    |
    v
6 AI Agents (parallel analysis, 15s timeout)
    |
    v
Challenge System (agents debate each other)
    |
    v
Consensus Engine (weighted scoring, disagreement, trust dampening)
    |
    v
Risk Agent Veto (absolute authority, first check)
    |
    v
Portfolio Intelligence (10-step pipeline)
    |
    v
Execution Policy (9 blockers + soft constraints)
    |
    v
Paper Trading Engine (simulated execution, SL/TP/timeout management)
    |
    v
Learning Pipeline (trust updates, portfolio state capture, pattern analysis)
    |
    v
Calibration (daily/weekly thresholds, adaptive rules, meta-evaluation)
```

---

## System Design Principles

**Safety-first execution.** Risk agent has absolute veto authority. Kill switch blocks all trades before any other evaluation runs. Nine independent hard blockers must all pass. The system defaults to caution.

**Explainability.** Every decision carries structured reasoning — which factors contributed, what blocked it, why the size was reduced. No black-box outputs.

**Closed learning loop.** Trade outcomes feed back into trust scores, portfolio patterns generate adaptive rules, scenario risk warnings are validated against actual results. The system evolves from its own performance data.

**Modularity.** Each module has clear boundaries and can be tested independently. The portfolio intelligence pipeline is a sequence of independent steps, each with its own verdict contribution.

**Central configuration.** No scattered hardcoded constants. All 52 tunable parameters live in a single config service with defaults, type validation, persistence, and audit logging.

**Graceful degradation.** If any module fails (agent timeout, DB unreachable, external API down), the system continues with reduced confidence rather than crashing. API calls have 10-second timeouts. All frontend loading uses `Promise.allSettled` with `finally` blocks.

---

## API Overview

103 endpoints across 16 route groups:

| Category | Endpoints | Examples |
|----------|-----------|---------|
| Auth | 4 | Login, register, token refresh, user info |
| Agents | 11 | Trigger cycles, latest signals, trust scores, health |
| Consensus | 5 | Thresholds, weights, disagreement config |
| Learning | 13 | Meta-evaluation, trust summary, leaderboard, thresholds, fitness, system confidence |
| Portfolio | 16 | Snapshot, exposure, fragility, rankings, scenario sim, marginal risk, kill switch, adaptive rules |
| Paper Trading | 9 | Positions, open/close, portfolio stats, history |
| Stress | 7 | Run scenarios, replay, assessment, history |
| Admin | 8 | Config get/set/reset, audit log, system summary |
| Execution | 4 | Kill switch, policy config, status |
| Scanner | 8 | Full scan, top picks, scan history |
| Market | 7 | Candles, prices, features |
| Readiness | 2 | Health check, 13-point checklist |

All endpoints require JWT authentication (access + refresh tokens).

---

## Getting Started

### Prerequisites

- Python 3.12+
- Node.js 20+
- PostgreSQL 15+ (or use Docker)
- Redis 7+

### Backend

```bash
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Set environment variables (see below)
cp .env.example .env

# Run API
uvicorn bahamut.main:app --host 0.0.0.0 --port 8000

# Run worker (separate terminal)
celery -A bahamut.celery_app worker --loglevel=info

# Run scheduler (separate terminal)
celery -A bahamut.celery_app beat --loglevel=info
```

### Frontend

```bash
cd frontend
npm install

# Set environment variables
echo "NEXT_PUBLIC_API_URL=http://localhost:8000" > .env.local

npm run dev
```

### Run Tests

```bash
cd backend
python -m pytest tests/test_intelligence.py -v
```

190 tests across 25 subsystems covering consensus, execution policy, disagreement, trust scoring, regime detection, learning attribution, meta-learning, threshold tuning, adaptive profiles, stress testing, readiness, system confidence, stress assessment, decision explainability, portfolio intelligence, dynamic allocation, portfolio learning, scenario risk, admin config, weighted scenarios, marginal risk, quality ratio, kill switch, and scenario outcome learning.

---

## Environment Variables

### Backend

| Variable | Required | Description |
|----------|----------|-------------|
| `DATABASE_URL` | Yes | PostgreSQL connection string |
| `REDIS_URL` | Yes | Redis connection string |
| `JWT_SECRET` | Yes | JWT signing secret (change in production) |
| `JWT_REFRESH_SECRET` | Yes | Refresh token secret |
| `TWELVE_DATA_KEY` | Yes | Twelve Data API key (market data) |
| `FINNHUB_KEY` | Yes | Finnhub API key (news, earnings) |
| `GEMINI_API_KEY` | No | Google Gemini API key (AI agent reasoning) |
| `ANTHROPIC_API_KEY` | No | Anthropic API key (alternative AI provider) |
| `NEWSAPI_KEY` | No | NewsAPI key (sentiment) |
| `OANDA_API_KEY` | No | OANDA API key (FX data) |
| `FRED_API_KEY` | No | FRED API key (economic data) |

### Frontend

| Variable | Required | Description |
|----------|----------|-------------|
| `NEXT_PUBLIC_API_URL` | Yes | Backend API base URL |
| `NEXT_PUBLIC_WS_URL` | No | WebSocket URL for real-time updates |

---

## Deployment

### Railway (Recommended)

The system is designed for Railway deployment with 6 services:

1. **API** — FastAPI application
2. **Worker** — Celery worker for async processing
3. **Beat** — Celery Beat scheduler
4. **Frontend** — Next.js application
5. **PostgreSQL** — Managed database
6. **Redis** — Managed cache/broker

Each service has its own Dockerfile or Railway configuration. Environment variables are shared across services through Railway's variable reference system.

### Docker Compose (Local Development)

```bash
docker-compose up -d
```

This starts PostgreSQL, Redis, and the API service. Frontend runs separately with `npm run dev`.

---

## Current Status

The core system is functional and deployed:

- Multi-agent analysis running on 15-minute cycles across 45+ assets
- Full paper trading engine with simulated execution, SL/TP management, and PnL tracking
- Self-learning pipeline processing every closed trade for trust score updates
- Portfolio intelligence evaluating every proposed trade through 10-step pipeline
- Stress testing with 13 scenarios (8 static + 5 dynamic mutators)
- 190 tests passing across 25 subsystems
- Admin configuration with 52 tunable parameters

Areas still evolving:

- Learning system needs more trade history to generate statistically significant adaptive rules (minimum sample counts enforced)
- Scenario shock maps use simplified linear PnL approximation (no convexity, no cross-asset correlation matrices)
- Market data dependent on external API reliability (Twelve Data, Finnhub)
- Paper trading only — no live broker integration

---

## Roadmap

- Multi-user workspace support with role-based access control
- Live broker integration (starting with FX via OANDA)
- Advanced learning engine with regime-conditioned adaptive rules
- Full admin control panel UI for configuration management
- Real-time WebSocket push for signal updates and position changes
- Historical backtesting engine using stored decision traces
- Mobile-responsive dashboard

---

## Repository Structure

```
bahamut/
├── backend/
│   ├── bahamut/
│   │   ├── admin/          # Central config, audit log
│   │   ├── agents/         # 6 AI agents, orchestrator, challenge system
│   │   ├── auth/           # JWT authentication
│   │   ├── consensus/      # Weighted consensus, disagreement, trust, explainer
│   │   ├── execution/      # Execution policy, kill switch
│   │   ├── features/       # Indicators, regime detection
│   │   ├── ingestion/      # Market data adapters
│   │   ├── learning/       # Calibration, meta-learning, thresholds, profile adapter
│   │   ├── paper_trading/  # Simulated execution, learning attribution
│   │   ├── portfolio/      # Intelligence engine, scenarios, marginal risk, quality, allocator
│   │   ├── readiness/      # Trading readiness checklist
│   │   ├── risk/           # Risk dashboard
│   │   ├── scanner/        # 45+ asset scanner
│   │   ├── stress/         # Stress testing, scenarios, assessment
│   │   └── ...
│   └── tests/
├── frontend/
│   └── src/app/            # 14 Next.js pages
├── docker-compose.yml
├── Dockerfile
└── railway.toml
```

---

## License

This is a proprietary project. All rights reserved.
