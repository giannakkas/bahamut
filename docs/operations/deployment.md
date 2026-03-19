# Bahamut.AI — Deployment & Rollback Guide

## Architecture

```
Railway Services (6):
  ├── API          (FastAPI, bahamut-production.up.railway.app)
  ├── Worker       (Celery worker)
  ├── Beat         (Celery beat scheduler)
  ├── Frontend     (Next.js, frontend-production-947b.up.railway.app)
  ├── Admin Panel  (Next.js, admin-panel-production-*.up.railway.app)
  ├── Postgres     (managed)
  └── Redis        (managed)
```

## Pre-Deploy Checklist

1. **Run all tests locally**: `PYTHONPATH=. pytest tests/ -v`
2. **Verify no critical degraded subsystems**: `GET /api/v1/system/health`
3. **Confirm schema version**: code `SCHEMA_VERSION` matches or exceeds DB version
4. **Review git diff**: no accidental credential exposure, no debug code

## Deployment Order

### Standard Deploy (all services)

```
1. Backend API       ← schema init runs here at startup
2. Worker            ← picks up new task code
3. Beat              ← picks up new schedule
4. Frontend          ← safe to deploy last (stateless)
5. Admin Panel       ← safe to deploy last (stateless)
```

### Backend-Only Deploy

```
1. Push to main
2. Railway auto-deploys API service
3. Worker + Beat auto-restart (same codebase)
4. Verify: GET /api/v1/system/health → status: "healthy"
5. Verify: GET /api/v1/system/health → schema.status: "ok"
```

### Frontend-Only Deploy

```
1. Push frontend changes to main
2. Railway auto-deploys frontend + admin-panel
3. Verify: pages load, login works
```

## Post-Deploy Verification

```bash
# 1. Health check
curl https://bahamut-production.up.railway.app/api/v1/system/health

# 2. Auth flow
curl -X POST https://bahamut-production.up.railway.app/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"...","password":"..."}'

# 3. Run smoke test
python backend/scripts/smoke_test.py --base-url https://bahamut-production.up.railway.app
```

## Rollback Plan

### Scenario 1: Bad Backend Deploy

```bash
# Option A: Revert commit and push
git revert HEAD
git push origin main

# Option B: Force deploy previous commit
git push origin HEAD~1:main --force
```

### Scenario 2: Schema Version Mismatch

If `GET /system/health` shows `schema.status: "mismatch"`:

```
1. DO NOT rollback — DB schema is already upgraded
2. Fix forward: deploy the correct code version
3. If impossible: manually update schema_version table:
   UPDATE schema_version SET version = <correct_version>;
```

### Scenario 3: Partial Deploy Failure

If API deploys but Worker/Beat fail:

```
1. Check Railway dashboard for build errors
2. Worker/Beat share the same Docker image — rebuild should fix both
3. If stuck: manually restart via Railway CLI or dashboard
4. Celery tasks will queue in Redis and process when worker recovers
```

## Safety Rules

- **NEVER** deploy when `/system/health` shows `status: "critical"`
- **NEVER** deploy schema changes without testing `init_schema()` locally first
- **ALWAYS** verify health endpoint after every deploy
- **ALWAYS** keep at least 3 recent commits available for rollback
- Database and Redis are managed by Railway — do NOT restart them manually
