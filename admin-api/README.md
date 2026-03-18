# Bahamut TICC — FastAPI Backend

API backend for the Trading Intelligence Control Center admin panel.

## Structure

```
bahamut-api/
├── main.py                  # FastAPI app, CORS, router registration
├── config.py                # pydantic-settings env config
├── auth.py                  # JWT create/verify, bcrypt, get_current_user dependency
├── requirements.txt
├── .env.example
├── models/
│   ├── auth.py              # LoginRequest, LoginResponse
│   ├── config.py            # ConfigMeta, ConfigUpdatePayload, ConfigOverride
│   ├── portfolio.py         # SystemSummary, MarginalRiskData, Alert, etc.
│   └── audit.py             # AuditLogEntry
├── routers/
│   ├── auth_router.py       # POST /auth/login
│   ├── admin_router.py      # /admin/* (config, overrides, audit, learning, alerts, AI)
│   └── portfolio_router.py  # /portfolio/* (marginal-risk, kill-switch)
├── services/
│   └── store.py             # In-memory data store (replace with DB later)
└── test_all.py              # 104-assertion integration test
```

## Setup

```bash
cp .env.example .env         # Edit JWT_SECRET for production
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

## Endpoints (17 total)

| # | Method | Path | Auth | Description |
|---|--------|------|------|-------------|
| 1 | POST | `/auth/login` | No | Returns JWT token |
| 2 | GET | `/admin/summary` | Yes | System overview |
| 3 | GET | `/admin/config` | Yes | All config keys |
| 4 | GET | `/admin/config/{key}` | Yes | Single config key |
| 5 | POST | `/admin/config` | Yes | Update config value |
| 6 | POST | `/admin/config/reset/{key}` | Yes | Reset to default |
| 7 | GET | `/admin/config/overrides` | Yes | Active overrides |
| 8 | POST | `/admin/config/overrides` | Yes | Create override |
| 9 | DELETE | `/admin/config/overrides/{key}` | Yes | Remove override |
| 10 | GET | `/admin/audit-log` | Yes | Config change history |
| 11 | GET | `/portfolio/marginal-risk` | Yes | Risk data + scenarios |
| 12 | GET | `/portfolio/kill-switch` | Yes | Kill switch state |
| 13 | POST | `/portfolio/kill-switch` | Yes | Toggle kill switch |
| 14 | GET | `/admin/learning/patterns` | Yes | AI learned patterns |
| 15 | GET | `/admin/alerts` | Yes | System alerts |
| 16 | POST | `/admin/alerts/{id}/dismiss` | Yes | Dismiss alert |
| 17 | GET | `/admin/ai/optimize` | Yes | AI suggestions |

## Test

```bash
python test_all.py
# Expected: 104 passed, 0 failed
```

## Connect to Frontend

In `bahamut-ticc/.env.local`:
```
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_MOCK_MODE=false
```

Default login: `admin` / `bahamut2026` (configurable via `.env`)
