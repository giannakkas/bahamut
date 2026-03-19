# Bahamut.AI — Production Alert Rules

All alerts are derived from `GET /api/v1/system/health`.

---

## CRITICAL Alerts (Page immediately)

### 1. Database Unavailable

- **Condition**: `checks.db.status != "ok"`
- **Severity**: CRITICAL
- **Impact**: All reads/writes fail, system non-functional
- **Action**: Check Railway Postgres service, verify connection string, check disk space
- **Recovery**: Restart Postgres service; if data corruption, restore from backup

### 2. Auth Revocation Degraded

- **Condition**: `checks.auth.status == "degraded"`
- **Severity**: CRITICAL
- **Impact**: Token revocation checks failing — revoked tokens may pass through OR all authenticated requests blocked (fail-closed)
- **Action**: Verify Redis connectivity, then DB connectivity. Check `auth.revocation` in degraded subsystems
- **Recovery**: Restart Redis; if persistent, check DB revoked_tokens table

### 3. Schema Version Mismatch

- **Condition**: `checks.schema.status == "mismatch"`
- **Severity**: CRITICAL
- **Impact**: DB has newer schema than deployed code — possible data corruption
- **Action**: Deploy correct code version immediately. Do NOT rollback DB
- **Recovery**: Deploy matching code version; verify with `schema_version` table

### 4. Kill Switch Degraded

- **Condition**: `portfolio.kill_switch` in `checks.degraded.critical`
- **Severity**: CRITICAL
- **Impact**: Portfolio kill switch evaluation failing — trades may be blocked as safety fallback
- **Action**: Check scenario risk engine, DB connectivity for kill_switch_events table
- **Recovery**: Fix underlying DB/computation error; degraded flag auto-clears after 5 min

### 5. Redis Unavailable

- **Condition**: `checks.redis.status != "ok"`
- **Severity**: CRITICAL
- **Impact**: WebSocket pub/sub fails, token revocation degrades, Celery tasks queue in memory
- **Action**: Check Railway Redis service, verify REDIS_URL env var
- **Recovery**: Restart Redis service; cached data will rebuild automatically

---

## WARNING Alerts (Investigate within 1 hour)

### 6. High API Latency

- **Condition**: `checks.db.latency_ms > 500` OR `checks.redis.latency_ms > 100`
- **Severity**: WARNING
- **Impact**: User experience degraded, API timeouts possible
- **Action**: Check Railway resource usage, DB connection pool, slow queries
- **Recovery**: Usually transient; if persistent, check for table bloat, missing indexes

### 7. Degraded Subsystems (Non-Critical)

- **Condition**: `checks.degraded.severity == "warning"` AND `checks.degraded.count > 0`
- **Severity**: WARNING
- **Impact**: Some subsystems returning fallback values
- **Action**: Check specific subsystem in `checks.degraded.subsystems`
- **Recovery**: Degraded flags auto-expire after 5 minutes if underlying issue resolves

### 8. Celery Queue Backlog

- **Condition**: `checks.celery_queue.backlog > 50`
- **Severity**: WARNING
- **Impact**: Signal cycles, price updates, and learning tasks delayed
- **Action**: Check Worker service is running, check for stuck tasks
- **Recovery**: Restart Worker service; tasks will process from Redis queue

### 9. Scenario Risk Degraded

- **Condition**: `portfolio.scenario_risk` in `checks.degraded.subsystems`
- **Severity**: WARNING
- **Impact**: Trades require manual approval (fail-safe activated)
- **Action**: Check stress engine, verify position data integrity
- **Recovery**: Auto-clears when next successful evaluation completes

---

## Monitoring Endpoints

| Endpoint | Purpose | Poll Interval |
|----------|---------|---------------|
| `GET /api/v1/system/health` | Full system health | Every 60s |
| `GET /metrics` | Request counts, latency percentiles | Every 60s |
| `GET /health` | Simple alive check | Every 30s |

---

## Recommended Monitoring Setup

For Railway deployment, use one of:

1. **Better Uptime / UptimeRobot** — poll `/health` every 30s, `/api/v1/system/health` every 60s
2. **Railway built-in healthchecks** — configure per service
3. **Custom cron** — run `backend/scripts/smoke_test.py` every 5 minutes
