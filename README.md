# Bahamut.AI

A systematic multi-strategy crypto trading engine focused on trend capture, breakout confirmation, and disciplined risk management.

Bahamut runs validated trading strategies across BTC and ETH, automatically detects market regimes, routes capital to the right strategy for current conditions, and monitors everything with real-time alerts.

**Live infrastructure:**
- **Dashboard:** [admin.bahamut.ai](https://admin.bahamut.ai)
- **API:** [api.bahamut.ai](https://api.bahamut.ai)

---

## Overview

Bahamut solves a specific problem: most trend-following strategies lose money in sideways or crashing markets. Instead of trying to make one strategy work everywhere, Bahamut detects the current market regime and only trades when conditions match the strategy's edge.

The system runs two independent strategies (trend continuation and confirmed breakout) across two assets (BTC and ETH), with a regime filter that blocks trading when market conditions aren't favorable. Everything runs through a paper trading execution engine with full portfolio accounting, risk controls, and a monitoring dashboard with Telegram and email alerts.

**Current status:** Paper trading validation phase. Validated on historical data, not yet trading real capital.

---

## Key Features

- **Multi-strategy system** — v5 (trend continuation) + v9 (confirmed breakout), firing at independent times
- **Regime-aware trading** — detects TREND / RANGE / CRASH per asset, only trades in favorable conditions
- **Multi-asset support** — BTC and ETH in parallel with per-asset regime detection
- **Execution engine** — paper broker with slippage, spread, risk-based position sizing, idempotency
- **Portfolio manager** — isolated strategy sleeves, combined risk limits, kill switch at 10% drawdown
- **Real-time monitoring** — dashboard with equity, drawdown, risk, strategy metrics, trade history
- **Automated alerts** — Telegram + Email for critical events, throttled to avoid spam

---

## Strategies

### v5 — Trend Continuation

The core validated edge. Trades long when the market is in a confirmed uptrend.

- **Regime filter:** Price must be above the 200-period EMA (bull market confirmation)
- **Entry signal:** 20-period EMA crosses above the 50-period EMA (golden cross)
- **Direction:** Long only
- **Frequency:** Low — roughly 7 to 19 trades per year per asset
- **Variants:** v5_base (SL 8%, TP 16%, hold 30 bars) and v5_tuned (SL 10%, TP 25%, hold 60 bars)

This works because it only enters during confirmed bullish conditions and uses wide stops that survive normal crypto volatility. The low frequency avoids overtrading.

### v9 — Confirmed Breakout

A second, independent edge that fires at different times than v5.

- **Signal:** Price breaks the 20-bar high AND holds above it for 3 consecutive bars
- **Logic:** Breakouts that hold are statistically more likely to continue than raw breakouts
- **Parameters:** SL 10%, TP 25%, max hold 40 bars
- **Independence:** Only 2% entry overlap with v5 — genuinely different timing

v9 catches the start of new moves (structural price action) while v5 catches the middle of trends (EMA alignment). Together they provide timing diversification within the trend regime.

### v8 — Regime Filter

Classifies the market into three states using simple, deterministic rules:

| Regime | Detection | Trading Behavior |
|--------|-----------|-----------------|
| **TREND** | Price >3–5% above EMA200, positive EMA50 slope, ADX >25 | v5 + v9 active |
| **RANGE** | Price within ±5% of EMA200, flat EMAs, low ADX | No trend trading |
| **CRASH** | Price >5% below EMA200, elevated ATR | No trading (capital preservation) |

Regime detection runs independently per asset. BTC can be in TREND while ETH is in RANGE.

---

## Portfolio Structure

Strategies run in parallel with isolated capital sleeves:

| Sleeve | Allocation | Risk per Trade |
|--------|-----------|---------------|
| v5_base | 35% | 2% |
| v5_tuned | 35% | 2% |
| v9_breakout | 30% | 2% |

**Multi-asset deployment:**
- BTCUSD: Full risk (1.0× multiplier)
- ETHUSD: Reduced risk (0.75× multiplier) until validated on real data
- Combined crypto risk cap: 5% of portfolio
- Max 1 position per strategy per asset
- Max 4 total open positions

---

## Architecture

```
Market Data (Twelve Data / Cache)
       │
       ▼
┌─────────────────────┐
│  Regime Detector     │  ← per asset: TREND / RANGE / CRASH
│  (v8_detector.py)    │
└──────────┬──────────┘
           ▼
┌─────────────────────┐
│  Regime Router       │  ← activates strategies per regime
│  (router_v8.py)      │
└──────────┬──────────┘
           ▼
┌─────────────────────┐
│  Strategy Evaluation │  ← v5_base, v5_tuned, v9_breakout
│  (per asset)         │
└──────────┬──────────┘
           ▼
┌─────────────────────┐
│  Execution Engine    │  ← paper broker, slippage, risk sizing
│  (engine.py)         │
└──────────┬──────────┘
           ▼
┌─────────────────────┐
│  Portfolio Manager   │  ← sleeve accounting, risk limits, kill switch
│  (manager.py)        │
└──────────┬──────────┘
           ▼
┌──────────┴──────────┐
│  DB Persistence      │  PostgreSQL: orders, trades, snapshots
│  Dashboard API       │  FastAPI: /api/v7 + /api/monitoring
│  Alerts              │  Telegram + Email + Dashboard
└─────────────────────┘
```

**Orchestrator** (`v7_orchestrator.py`) runs as a Celery task every 2 minutes. On each cycle it fetches candles for each asset, detects the regime, routes to active strategies, evaluates signals, submits to the execution engine, updates portfolio state, persists to the database, and checks alert rules.

---

## Monitoring & Alerts

### Dashboard

The monitoring dashboard at `/v7-operations` shows:

- **Top bar:** Equity, total PnL, return %, drawdown %, open risk %, position count
- **Regime cards:** Per-asset regime status (TREND / RANGE / CRASH)
- **Strategies tab:** PnL, win rate, rolling-20 WR, profit factor, expectancy per strategy
- **Positions tab:** Open positions with entry, current price, SL, TP, unrealized PnL, risk %
- **Trades tab:** Recent closed trades with PnL, exit reason, duration
- **Alerts tab:** Recent alerts color-coded by severity

Auto-refreshes every 15 seconds.

### Alert System

Alerts fire automatically based on portfolio and execution state:

| Level | Triggers | Delivery |
|-------|----------|----------|
| **CRITICAL** | Drawdown >8%, open risk >5%, kill switch, execution errors | Telegram + Email |
| **WARNING** | Drawdown >5%, win rate <30%, approaching risk limit | Telegram |
| **INFO** | Trade opened/closed, regime change | Dashboard only |

All alerts are throttled to max once per 30 minutes per alert type to avoid spam.

**Example alerts:**

```
🚨 [CRITICAL] Bahamut Alert
Drawdown exceeded 8%
Current drawdown: 9.2%
Action: Review positions immediately.

ℹ️ [INFO] Trade closed: BTCUSD ✅
v5_base LONG BTCUSD
PnL: +$1,542.00 | Reason: TP

ℹ️ [INFO] Regime change: BTCUSD
BTCUSD: RANGE → TREND 📈
```

---

## Installation

### Prerequisites

- Python 3.11+
- Node.js 18+
- PostgreSQL
- Redis

### Backend

```bash
cd backend
pip install -r requirements.txt

# Environment variables
export DATABASE_URL="postgresql://user:pass@localhost:5432/bahamut"
export REDIS_URL="redis://localhost:6379/0"

# Optional: Telegram alerts
export TELEGRAM_BOT_TOKEN="your-bot-token"
export TELEGRAM_CHAT_ID="your-chat-id"

# Optional: Email alerts
export SMTP_HOST="smtp.gmail.com"
export SMTP_PORT="587"
export SMTP_USER="your@email.com"
export SMTP_PASS="app-password"
export ALERT_EMAIL_TO="alerts@email.com"

# Optional: Market data
export TWELVE_DATA_KEY="your-api-key"

# Run database migrations
python -m bahamut.execution.v7_migration
python -m bahamut.regime.v8_migration
```

### Frontend

```bash
cd admin-panel
npm install
```

### Running

```bash
# Backend
cd backend
uvicorn bahamut.main:app --reload

# Celery worker (execution queue)
celery -A bahamut.celery_app worker -Q critical

# Celery beat (schedules the 2-minute trading cycle)
celery -A bahamut.celery_app beat

# Frontend
cd admin-panel
npm run dev
```

The monitoring dashboard will be available at `/v7-operations` in the admin panel.

---

## API

### Monitoring Endpoints (`/api/monitoring`)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/portfolio` | Equity, PnL, drawdown, risk, regimes |
| GET | `/strategies` | Per-strategy metrics, rolling WR, PF, expectancy |
| GET | `/positions` | Open positions with risk breakdown |
| GET | `/trades` | Recent closed trades |
| GET | `/execution` | Execution quality: signals, slippage, cancellations |
| GET | `/alerts` | Recent alerts for dashboard |
| GET | `/health` | Full system health check |

### Operations Endpoints (`/api/v7`)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/portfolio/summary` | Full portfolio with sleeve breakdown |
| GET | `/portfolio/equity-curve` | Equity snapshots for charting |
| POST | `/portfolio/kill-switch` | Emergency close all positions |
| POST | `/portfolio/resume` | Resume trading after kill switch |
| POST | `/portfolio/rebalance` | Rebalance sleeve allocations |
| GET | `/execution/open-positions` | Live open positions |
| GET | `/execution/closed-trades` | Trade history |
| GET | `/execution/stats` | Win/loss/PnL summary |
| POST | `/strategies/{name}/enable` | Enable a strategy |
| POST | `/strategies/{name}/disable` | Disable a strategy |
| POST | `/orchestrator/run-cycle` | Manually trigger a trading cycle |
| GET | `/assets/summary` | Per-asset breakdown and combined risk |

---

## Validated Performance

Tested on realistic synthetic BTC + ETH data (correlated, r=0.85) over approximately 14 months:

| Strategy | BTC Trades | ETH Trades | Total | Win Rate | PnL |
|----------|-----------|-----------|-------|----------|-----|
| v5_base | 8 | 12 | 20 | 50% | +$1,372 |
| v5_tuned | 7 | 11 | 18 | 56% | +$1,617 |
| v9_breakout | 18 | 20 | 38 | 63% | +$4,876 |
| **Total** | **33** | **43** | **76** | **58%** | **+$7,865** |

Portfolio return: +7.86% on $100K starting capital. Projected annual trade count: ~76.

These results are from synthetic data designed to follow real BTC price paths (2023–2025). They have not been validated on live market data.

---

## Risk Controls

| Control | Value |
|---------|-------|
| Max total open risk | 6% of portfolio |
| Max combined crypto risk | 5% (BTC + ETH correlation-aware) |
| Max positions per strategy per asset | 1 |
| Max total open positions | 4 |
| Kill switch | Auto-triggers at 10% portfolio drawdown |
| ETH risk multiplier | 0.75× |
| Slippage model | 8 bps (BTC), 10 bps (ETH) |
| Spread model | 12 bps (BTC), 15 bps (ETH) |
| Worst-case fill | If SL and TP hit same bar, fills at SL |
| Signal idempotency | Asset-scoped signal IDs prevent duplicates |

---

## Database

| Table | Purpose |
|-------|---------|
| `strategy_sleeves` | Per-strategy capital and performance tracking |
| `v7_orders` | Order lifecycle: PENDING → OPEN → CLOSED |
| `v7_trades` | Closed trade history with PnL and regime |
| `v7_portfolio_snapshots` | Equity curve with regime metadata |
| `v8_regime_history` | Regime classification log per asset |

---

## Project Structure

```
backend/
├── bahamut/
│   ├── strategies/          # v5_base, v5_tuned, v8_range, v8_defensive
│   ├── alpha/               # v9_candidate (confirmed breakout)
│   ├── regime/              # v8_detector, v8_migration
│   ├── execution/           # engine, paper_broker, sizer, orchestrator, v7_router
│   ├── portfolio/           # manager, router_v8
│   ├── monitoring/          # alerts, dashboard_api, telegram, email
│   ├── backtesting/         # data_real, run_v5, run_v8, run_v9, run_multi_asset
│   ├── config_assets.py     # Multi-asset configuration
│   └── main.py              # FastAPI application
admin-panel/
├── app/(admin)/
│   └── v7-operations/       # Monitoring dashboard
└── components/
```

---

## Roadmap

- [ ] Connect real market data (Twelve Data API for live BTC + ETH candles)
- [ ] Live broker integration (Binance or Coinbase API)
- [ ] Validate strategies on real ETH historical data
- [ ] WebSocket push for real-time dashboard updates
- [ ] Position reconciliation on system restart
- [ ] Additional assets (SOL, major forex pairs)
- [ ] Further edge discovery (v10)

---

## Current Status

Bahamut is in **paper trading validation phase**. The system is operationally complete — strategies, execution, portfolio management, monitoring, and alerting all work end-to-end. The strategies have been validated on realistic synthetic data but have not yet been tested with real capital.

The next step is connecting live market data and running paper trades on real-time candles to accumulate 30+ trades for statistical validation before any capital deployment.

---

## Disclaimer

This software is experimental and provided as-is. It is not financial advice. Trading cryptocurrencies involves substantial risk of loss. Past performance on synthetic data does not guarantee future results. Do not trade with money you cannot afford to lose. The authors are not responsible for any financial losses incurred through the use of this software.

---

## License

Proprietary. All rights reserved.
