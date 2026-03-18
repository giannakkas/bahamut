#!/usr/bin/env python3
"""
Staging smoke test — validates a live Bahamut TICC deployment.

Usage:
    python staging_test.py https://your-api.railway.app admin password123

Tests all 17 endpoints + auth + error handling against a live instance.
"""

import json
import sys
import time

try:
    import httpx
except ImportError:
    print("Install httpx: pip install httpx")
    sys.exit(1)

if len(sys.argv) < 4:
    print("Usage: python staging_test.py <BASE_URL> <USERNAME> <PASSWORD>")
    print("Example: python staging_test.py http://localhost:8000 admin bahamut2026")
    sys.exit(1)

BASE = sys.argv[1].rstrip("/")
USER = sys.argv[2]
PASS = sys.argv[3]
TOKEN = ""

passed = 0
failed = 0
client = httpx.Client(timeout=10.0)


def test(name: str, ok: bool, detail: str = ""):
    global passed, failed
    if ok:
        passed += 1
        print(f"  ✅ {name}")
    else:
        failed += 1
        print(f"  ❌ {name} — {detail}")


def auth_headers():
    return {"Authorization": f"Bearer {TOKEN}"}


print("=" * 60)
print(f"STAGING SMOKE TEST — {BASE}")
print("=" * 60)

# ─── Health / Ready ───────────────────────────────────────────
print("\n[1] Health & Readiness")
r = client.get(f"{BASE}/health")
test("GET /health → 200", r.status_code == 200)
test("  status=ok", r.json().get("status") == "ok")

r = client.get(f"{BASE}/ready")
test("GET /ready → 200", r.status_code == 200)
test("  status=ready", r.json().get("status") == "ready")

# ─── Auth ─────────────────────────────────────────────────────
print("\n[2] Authentication")
r = client.post(f"{BASE}/auth/login", json={"username": USER, "password": PASS})
test("POST /auth/login → 200", r.status_code == 200)
data = r.json()
test("  has access_token", "access_token" in data)
test("  has refresh_token", "refresh_token" in data)
test("  has user", "user" in data)
TOKEN = data.get("access_token", "")
REFRESH = data.get("refresh_token", "")

r = client.post(f"{BASE}/auth/login", json={"username": USER, "password": "wrong"})
test("Bad password → 401", r.status_code == 401)
test("  no stack trace in response", "traceback" not in r.text.lower())

# Refresh token
r = client.post(f"{BASE}/auth/refresh", json={"refresh_token": REFRESH})
test("POST /auth/refresh → 200", r.status_code == 200)
test("  has new access_token", "access_token" in r.json())

r = client.post(f"{BASE}/auth/refresh", json={"refresh_token": "garbage"})
test("Bad refresh token → 401", r.status_code == 401)

# ─── 401 without token ───────────────────────────────────────
print("\n[3] Auth Guard")
r = client.get(f"{BASE}/admin/summary")
test("No token → 403", r.status_code == 403)

r = client.get(f"{BASE}/admin/summary", headers={"Authorization": "Bearer garbage"})
test("Bad token → 401", r.status_code == 401)
test("  message is safe", "traceback" not in r.text.lower())

# ─── Summary ─────────────────────────────────────────────────
print("\n[4] Dashboard Summary")
r = client.get(f"{BASE}/admin/summary", headers=auth_headers())
test("GET /admin/summary → 200", r.status_code == 200)
d = r.json()
test("  has kill_switch", "kill_switch" in d)
test("  has safe_mode", "safe_mode" in d)
test("  has readiness.components", "components" in d.get("readiness", {}))
test("  has confidence.history", isinstance(d.get("confidence", {}).get("history"), list))
test("  has risk_level", d.get("risk_level") in ("LOW", "MEDIUM", "HIGH", "CRITICAL"))
test("  has portfolio_value", isinstance(d.get("portfolio_value"), (int, float)))

# ─── Config ──────────────────────────────────────────────────
print("\n[5] Config CRUD")
r = client.get(f"{BASE}/admin/config", headers=auth_headers())
test("GET /admin/config → 200", r.status_code == 200)
cfg = r.json()
test("  37+ keys", len(cfg) >= 37)

# Read single
r = client.get(f"{BASE}/admin/config/confidence.min_trade", headers=auth_headers())
test("GET /admin/config/key → 200", r.status_code == 200)
original = r.json().get("value")

# Update
r = client.post(f"{BASE}/admin/config", headers=auth_headers(), json={"key": "confidence.min_trade", "value": 0.72})
test("POST /admin/config → 200", r.status_code == 200)

# Verify update
r = client.get(f"{BASE}/admin/config/confidence.min_trade", headers=auth_headers())
test("  value changed to 0.72", r.json().get("value") == 0.72)

# Validation
r = client.post(f"{BASE}/admin/config", headers=auth_headers(), json={"key": "confidence.min_trade", "value": 99.0})
test("Out of range → 400", r.status_code == 400)

# Reset
r = client.post(f"{BASE}/admin/config/reset/confidence.min_trade", headers=auth_headers())
test("POST /admin/config/reset → 200", r.status_code == 200)

r = client.get(f"{BASE}/admin/config/confidence.min_trade", headers=auth_headers())
test("  value reset to default", r.json().get("value") == 0.6)

# ─── Overrides ───────────────────────────────────────────────
print("\n[6] Overrides")
r = client.get(f"{BASE}/admin/config/overrides", headers=auth_headers())
test("GET /admin/config/overrides → 200", r.status_code == 200)

r = client.post(f"{BASE}/admin/config/overrides", headers=auth_headers(), json={
    "key": "exposure.max_single", "value": 0.1, "ttl": 3600, "reason": "staging test"
})
test("POST create override → 201", r.status_code == 201)

r = client.get(f"{BASE}/admin/config/overrides", headers=auth_headers())
test("  override visible", len(r.json()) >= 1)

r = client.delete(f"{BASE}/admin/config/overrides/exposure.max_single", headers=auth_headers())
test("DELETE override → 200", r.status_code == 200)

# ─── Audit Log ───────────────────────────────────────────────
print("\n[7] Audit Log")
r = client.get(f"{BASE}/admin/audit-log", headers=auth_headers())
test("GET /admin/audit-log → 200", r.status_code == 200)
al = r.json()
test("  is list with entries", isinstance(al, list) and len(al) >= 1)
test("  latest entry has config change", al[0].get("key") is not None)

# ─── Risk / Kill Switch ─────────────────────────────────────
print("\n[8] Risk & Kill Switch")
r = client.get(f"{BASE}/portfolio/marginal-risk", headers=auth_headers())
test("GET /portfolio/marginal-risk → 200", r.status_code == 200)
mr = r.json()
test("  has contributors", len(mr.get("contributors", [])) >= 1)
test("  has scenarios", len(mr.get("scenarios", [])) >= 1)

r = client.get(f"{BASE}/portfolio/kill-switch", headers=auth_headers())
test("GET /portfolio/kill-switch → 200", r.status_code == 200)

r = client.post(f"{BASE}/portfolio/kill-switch", headers=auth_headers(), json={"active": True})
test("POST kill-switch ON → 200", r.status_code == 200)

r = client.get(f"{BASE}/portfolio/kill-switch", headers=auth_headers())
test("  kill switch active", r.json().get("active") is True)

r = client.post(f"{BASE}/portfolio/kill-switch", headers=auth_headers(), json={"active": False})
test("POST kill-switch OFF → 200", r.status_code == 200)

# ─── Learning ────────────────────────────────────────────────
print("\n[9] Learning Patterns")
r = client.get(f"{BASE}/admin/learning/patterns", headers=auth_headers())
test("GET /admin/learning/patterns → 200", r.status_code == 200)
test("  has patterns", len(r.json()) >= 1)

# ─── Alerts ──────────────────────────────────────────────────
print("\n[10] Alerts")
r = client.get(f"{BASE}/admin/alerts", headers=auth_headers())
test("GET /admin/alerts → 200", r.status_code == 200)
alerts = r.json()
test("  has alerts", len(alerts) >= 1)

undismissed = [a for a in alerts if not a["dismissed"]]
if undismissed:
    aid = undismissed[0]["id"]
    r = client.post(f"{BASE}/admin/alerts/{aid}/dismiss", headers=auth_headers())
    test(f"POST /admin/alerts/{aid}/dismiss → 200", r.status_code == 200)

r = client.post(f"{BASE}/admin/alerts/999999/dismiss", headers=auth_headers())
test("Dismiss nonexistent → 404", r.status_code == 404)

# ─── AI Optimize ─────────────────────────────────────────────
print("\n[11] AI Optimization")
# Reset a config to generate suggestions
client.post(f"{BASE}/admin/config", headers=auth_headers(), json={"key": "confidence.min_trade", "value": 0.65})
r = client.get(f"{BASE}/admin/ai/optimize", headers=auth_headers())
test("GET /admin/ai/optimize → 200", r.status_code == 200)
test("  has suggestions", len(r.json()) >= 1)

# ─── Error responses ─────────────────────────────────────────
print("\n[12] Error Response Safety")
r = client.get(f"{BASE}/admin/config/nonexistent.key.here", headers=auth_headers())
test("404 body is safe JSON", "detail" in r.json())
test("  no stack trace", "traceback" not in r.text.lower() and "File " not in r.text)

# ─── Summary ─────────────────────────────────────────────────
print("\n" + "=" * 60)
total = passed + failed
print(f"RESULTS: {passed}/{total} passed, {failed} failed")
if failed == 0:
    print("✅ STAGING VALIDATION PASSED — ready for production")
else:
    print("❌ STAGING VALIDATION FAILED — fix issues before go-live")
print("=" * 60)

client.close()
sys.exit(1 if failed else 0)
