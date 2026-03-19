# Bahamut.AI — Backup & Restore Guide

## PostgreSQL Backup

### Daily Backup (pg_dump)

```bash
# From a machine with access to the Railway Postgres instance:
export PGURL="postgresql://user:pass@host:port/dbname"

# Full dump (compressed)
pg_dump "$PGURL" --format=custom --file="bahamut_$(date +%Y%m%d_%H%M%S).dump"

# Schema only (for reference)
pg_dump "$PGURL" --schema-only --file="bahamut_schema_$(date +%Y%m%d).sql"
```

### Automated Daily Backup (cron)

```bash
# Add to crontab on a server with DB access:
0 3 * * * pg_dump "$PGURL" --format=custom --file="/backups/bahamut_$(date +\%Y\%m\%d).dump" 2>> /var/log/bahamut_backup.log
```

### Retention Policy

| Period | Retention |
|--------|-----------|
| Daily | Keep 7 days |
| Weekly | Keep 4 weeks (Sunday backup) |
| Monthly | Keep 6 months (1st of month) |

### Critical Tables (Priority Backup)

These tables contain irreplaceable data:

- `paper_portfolios` — portfolio state and balance
- `paper_positions` — all trade history
- `decision_traces` — AI decision audit trail
- `learning_events` — trust score training data
- `trust_scores_live` — agent trust calibration
- `calibration_runs` — threshold calibration history

---

## Restore Procedure

### Full Restore

```bash
# 1. Stop all services (Railway: pause API, Worker, Beat)

# 2. Restore from dump
pg_restore --clean --if-exists --dbname="$PGURL" bahamut_YYYYMMDD.dump

# 3. Verify schema version
psql "$PGURL" -c "SELECT MAX(version) FROM schema_version;"

# 4. Restart services (Railway: resume API first, then Worker, Beat)

# 5. Verify health
curl https://bahamut-production.up.railway.app/api/v1/system/health
```

### Single Table Restore

```bash
# Extract single table from dump
pg_restore --data-only --table=paper_positions bahamut_YYYYMMDD.dump | psql "$PGURL"
```

### Validation After Restore

```bash
# Check row counts match expectations
psql "$PGURL" -c "
  SELECT 'paper_portfolios' as tbl, count(*) FROM paper_portfolios
  UNION ALL SELECT 'paper_positions', count(*) FROM paper_positions
  UNION ALL SELECT 'decision_traces', count(*) FROM decision_traces
  UNION ALL SELECT 'trust_scores_live', count(*) FROM trust_scores_live
  UNION ALL SELECT 'schema_version', max(version)::text FROM schema_version;
"
```

---

## Redis Strategy

### What's in Redis

| Data | Ephemeral? | Lost on Restart? |
|------|-----------|-----------------|
| Token revocation blacklist | Semi — has DB fallback | Yes, but DB fallback kicks in |
| WebSocket pub/sub channels | Yes | Yes, clients reconnect |
| Daily brief cache | Yes | Regenerated on next cycle |
| Celery task queue | Yes | Pending tasks lost |
| Celery results | Yes | Acceptable loss |

### Redis Backup

Redis data is **ephemeral by design** in Bahamut. All critical state lives in PostgreSQL.

If Redis restarts:
- Token revocation falls back to DB `revoked_tokens` table
- WebSocket clients reconnect automatically
- Celery tasks re-enqueue on next beat cycle
- Cached data regenerates within one signal cycle (15 min)

**No Redis backup needed** — PostgreSQL is the source of truth.

---

## Disaster Recovery Timeline

| Scenario | RTO | RPO |
|----------|-----|-----|
| Redis restart | ~30 seconds | 0 (no data loss) |
| DB failover (Railway managed) | ~2 minutes | 0 |
| Full DB restore from backup | ~15 minutes | Up to 24 hours |
| Full infrastructure rebuild | ~1 hour | Up to 24 hours |
