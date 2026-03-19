# Bahamut.AI — Incident Runbook

## 1. Database Down

### Detect
- `GET /api/v1/system/health` → `checks.db.status: "error"`
- API returns 500 errors on authenticated endpoints
- Logs: `query_failed`, `transaction_failed`

### Fix
1. Check Railway dashboard → Postgres service status
2. If Postgres is down: restart via Railway dashboard
3. If connection refused: verify `DATABASE_URL` env var
4. If disk full: Railway auto-scales, but check volume usage
5. If data corruption: restore from latest backup (see `backup.md`)

### Verify Recovery
```bash
curl https://bahamut-production.up.railway.app/api/v1/system/health | jq '.checks.db'
# Expected: {"status": "ok", "latency_ms": <number>}
```

---

## 2. Redis Down

### Detect
- `GET /api/v1/system/health` → `checks.redis.status: "error"` or `"disconnected"`
- WebSocket connections drop
- Token revocation falls back to DB (slower auth)
- Logs: `redis_revoke_check_failed`, `health_check_redis_failed`

### Fix
1. Check Railway dashboard → Redis service status
2. Restart Redis service if needed
3. Verify `REDIS_URL` env var

### Verify Recovery
```bash
curl https://bahamut-production.up.railway.app/api/v1/system/health | jq '.checks.redis'
# Expected: {"status": "ok", "latency_ms": <number>}
```

### Note
Redis loss is **non-catastrophic**. All critical data is in PostgreSQL. System degrades gracefully.

---

## 3. Celery Stuck

### Detect
- `GET /api/v1/system/health` → `checks.celery_queue.backlog > 50`
- No new signal cycles appearing in dashboard
- No price updates on open positions
- Logs: Worker service showing no task completions

### Fix
1. Check Railway → Worker service logs for errors
2. Check Railway → Beat service is running (triggers scheduled tasks)
3. Restart Worker service
4. If Redis is down: fix Redis first (Celery depends on it)
5. If stuck on specific task: check logs for the task error, fix code, redeploy

### Verify Recovery
```bash
# Check queue drains
curl https://bahamut-production.up.railway.app/api/v1/system/health | jq '.checks.celery_queue'
# Expected: {"backlog": 0} or small number

# Check signal cycles are running
curl -H "Authorization: Bearer $TOKEN" \
  https://bahamut-production.up.railway.app/api/v1/agents/status
```

---

## 4. Degraded Subsystem Persists

### Detect
- `GET /api/v1/system/health` → `checks.degraded.count > 0` for more than 10 minutes
- Degraded flags normally auto-expire after 5 minutes

### Fix
1. Identify which subsystem: check `checks.degraded.subsystems`
2. Common causes:
   - `portfolio.kill_switch` → DB issue with kill_switch_events table
   - `portfolio.scenario_risk` → stress engine computation error
   - `portfolio.marginal_risk` → marginal risk module error
   - `auth.revocation` → both Redis AND DB unavailable (CRITICAL)
   - `schema.version` → code/DB version mismatch
3. Fix the root cause (usually DB or computation error)
4. Degraded flag auto-clears on next successful operation

### Manual Clear (emergency only)
```python
# Via Python shell on the API service:
from bahamut.shared.degraded import clear_degraded
clear_degraded("portfolio.kill_switch")  # or whatever subsystem
```

---

## 5. Auth Failures

### Detect
- Users unable to login
- 401 errors on all authenticated endpoints
- `checks.auth.status: "degraded"`

### Fix

**If login itself fails:**
1. Check DB connectivity (users table)
2. Verify `JWT_SECRET` and `JWT_REFRESH_SECRET` env vars haven't changed
3. Check logs for `login_failed` errors

**If token validation fails:**
1. If `auth.revocation` degraded: fix Redis/DB (see sections 1 & 2)
2. If JWT decode fails: `JWT_SECRET` may have changed between deploys
3. If all users suddenly logged out: secret rotation occurred — expected

**If refresh fails:**
1. Check `JWT_REFRESH_SECRET` env var
2. Check `/api/v1/auth/refresh` endpoint logs
3. Users need to re-login if refresh tokens are invalid

### Verify Recovery
```bash
# Test login
curl -X POST https://bahamut-production.up.railway.app/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"test@example.com","password":"..."}'
# Should return access_token + refresh_token
```

---

## 6. Schema Mismatch

### Detect
- `GET /api/v1/system/health` → `checks.schema.status: "mismatch"`
- Logs: `schema_version_mismatch` at CRITICAL level
- `schema.version` appears in degraded subsystems

### Fix
1. **DO NOT** rollback the database
2. Check what version the DB has:
   ```sql
   SELECT MAX(version) FROM schema_version;
   ```
3. Check what version the code expects:
   ```python
   from bahamut.db.schema.tables import SCHEMA_VERSION
   print(SCHEMA_VERSION)
   ```
4. Deploy the code version that matches the DB version
5. If DB is ahead of all code versions: someone ran migrations manually — investigate

### Prevention
- Always deploy code before running schema changes
- Never manually modify `schema_version` table in production
- `init_schema()` handles upgrades automatically at startup

---

## General Escalation Path

```
1. Check /api/v1/system/health
2. Identify failing component
3. Check Railway dashboard for service status
4. Check service logs for errors
5. Apply fix from relevant runbook section
6. Verify recovery via health endpoint
7. Run smoke test: python backend/scripts/smoke_test.py
```
