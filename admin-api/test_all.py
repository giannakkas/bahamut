"""
Integration test — verifies ALL 17 endpoints match frontend contract.
Run: python test_all.py
"""
import json
import os
import sys

# Use in-memory SQLite for tests
os.environ["DATABASE_URL"] = "sqlite:///./test_bahamut.db"

from fastapi.testclient import TestClient
from main import app
from services.database import init_db

# Init DB before tests (lifespan doesn't auto-fire in TestClient)
init_db()

client = TestClient(app)
passed = 0
failed = 0


def test(name: str, ok: bool, detail: str = ""):
    global passed, failed
    if ok:
        passed += 1
        print(f"  ✅ {name}")
    else:
        failed += 1
        print(f"  ❌ {name} — {detail}")


def keys_present(data: dict, keys: list[str]) -> bool:
    return all(k in data for k in keys)


print("=" * 60)
print("BAHAMUT TICC — FULL ENDPOINT TEST")
print("=" * 60)

# ─── 1. Health ────────────────────────────────────────────────────
print("\n[health]")
r = client.get("/health")
test("GET /health → 200", r.status_code == 200)
test("  has status=ok", r.json().get("status") == "ok")

# ─── 2. Login ─────────────────────────────────────────────────────
print("\n[auth]")
r = client.post("/auth/login", json={"username": "admin", "password": "bahamut2026"})
test("POST /auth/login → 200", r.status_code == 200)
data = r.json()
test("  has access_token", "access_token" in data)
test("  has refresh_token", "refresh_token" in data)
test("  has user", data.get("user") == "admin")
TOKEN = data.get("access_token", "")
REFRESH = data.get("refresh_token", "")

r = client.post("/auth/login", json={"username": "admin", "password": "wrong"})
test("POST /auth/login bad creds → 401", r.status_code == 401)

# ─── 2b. Refresh ──────────────────────────────────────────────────
print("\n[auth/refresh]")
r = client.post("/auth/refresh", json={"refresh_token": REFRESH})
test("POST /auth/refresh → 200", r.status_code == 200)
test("  has new access_token", "access_token" in r.json())

r = client.post("/auth/refresh", json={"refresh_token": "garbage"})
test("POST /auth/refresh bad token → 401", r.status_code == 401)

# Try using access token as refresh (should fail due to type check)
r = client.post("/auth/refresh", json={"refresh_token": TOKEN})
test("POST /auth/refresh with access token → 401", r.status_code == 401)

AUTH = {"Authorization": f"Bearer {TOKEN}"}

# ─── 3. Protected route without token ────────────────────────────
print("\n[auth guard]")
r = client.get("/admin/summary")
test("GET /admin/summary no token → 403", r.status_code == 403)

r = client.get("/admin/summary", headers={"Authorization": "Bearer garbage"})
test("GET /admin/summary bad token → 401", r.status_code == 401)

# ─── 4. Summary ──────────────────────────────────────────────────
print("\n[admin/summary]")
r = client.get("/admin/summary", headers=AUTH)
test("GET /admin/summary → 200", r.status_code == 200)
d = r.json()
test("  kill_switch.active exists", "active" in d.get("kill_switch", {}))
test("  kill_switch.reason exists", "reason" in d.get("kill_switch", {}))
test("  kill_switch.last_triggered exists", "last_triggered" in d.get("kill_switch", {}))
test("  safe_mode.active exists", "active" in d.get("safe_mode", {}))
test("  readiness.score exists", "score" in d.get("readiness", {}))
test("  readiness.components.data exists", "data" in d.get("readiness", {}).get("components", {}))
test("  confidence.score exists", "score" in d.get("confidence", {}))
test("  confidence.trend exists", d.get("confidence", {}).get("trend") in ("rising", "stable", "falling"))
test("  confidence.history is list", isinstance(d.get("confidence", {}).get("history"), list))
test("  risk_level valid", d.get("risk_level") in ("LOW", "MEDIUM", "HIGH", "CRITICAL"))
test("  has portfolio_value", isinstance(d.get("portfolio_value"), (int, float)))
test("  has daily_pnl", isinstance(d.get("daily_pnl"), (int, float)))
test("  has open_positions", isinstance(d.get("open_positions"), int))
test("  has agents_active", isinstance(d.get("agents_active"), int))
test("  has last_cycle", isinstance(d.get("last_cycle"), str))

# ─── 5. Config ───────────────────────────────────────────────────
print("\n[admin/config]")
r = client.get("/admin/config", headers=AUTH)
test("GET /admin/config → 200", r.status_code == 200)
cfg = r.json()
test("  is dict with 37+ keys", isinstance(cfg, dict) and len(cfg) >= 37)
sample_key = "confidence.min_trade"
sample = cfg.get(sample_key, {})
test(f"  {sample_key} has value", "value" in sample)
test(f"  {sample_key} has type", sample.get("type") in ("float", "int", "bool", "string"))
test(f"  {sample_key} has category", "category" in sample)
test(f"  {sample_key} has description", "description" in sample)
test(f"  {sample_key} has default", "default" in sample)

# ─── 6. Config single key ────────────────────────────────────────
print("\n[admin/config/{key}]")
r = client.get(f"/admin/config/{sample_key}", headers=AUTH)
test(f"GET /admin/config/{sample_key} → 200", r.status_code == 200)
r = client.get("/admin/config/nonexistent.key", headers=AUTH)
test("GET /admin/config/nonexistent → 404", r.status_code == 404)

# ─── 7. Config update ────────────────────────────────────────────
print("\n[admin/config POST]")
r = client.post("/admin/config", headers=AUTH, json={"key": sample_key, "value": 0.72})
test("POST /admin/config → 200", r.status_code == 200)
# Verify it changed
r2 = client.get(f"/admin/config/{sample_key}", headers=AUTH)
test("  value updated to 0.72", r2.json().get("value") == 0.72)

# Invalid range
r = client.post("/admin/config", headers=AUTH, json={"key": sample_key, "value": 5.0})
test("POST /admin/config out of range → 400", r.status_code == 400)

# Invalid key
r = client.post("/admin/config", headers=AUTH, json={"key": "fake.key", "value": 1})
test("POST /admin/config bad key → 400", r.status_code == 400)

# ─── 8. Config reset ─────────────────────────────────────────────
print("\n[admin/config/reset]")
r = client.post(f"/admin/config/reset/{sample_key}", headers=AUTH)
test(f"POST /admin/config/reset/{sample_key} → 200", r.status_code == 200)
r2 = client.get(f"/admin/config/{sample_key}", headers=AUTH)
test("  value reset to default 0.6", r2.json().get("value") == 0.6)

# ─── 9. Overrides ────────────────────────────────────────────────
print("\n[admin/config/overrides]")
r = client.get("/admin/config/overrides", headers=AUTH)
test("GET /admin/config/overrides → 200", r.status_code == 200)
test("  is list", isinstance(r.json(), list))

# Create
r = client.post("/admin/config/overrides", headers=AUTH, json={
    "key": "exposure.max_single", "value": 0.1, "ttl": 3600, "reason": "Volatility spike"
})
test("POST /admin/config/overrides → 201", r.status_code == 201)

# Verify it's there
r2 = client.get("/admin/config/overrides", headers=AUTH)
ov = r2.json()
test("  override created", len(ov) >= 1 and ov[0].get("key") == "exposure.max_single")
test("  has ttl", "ttl" in ov[0])
test("  has created", "created" in ov[0])
test("  has expires", "expires" in ov[0])
test("  has reason", "reason" in ov[0])

# Delete
r = client.delete("/admin/config/overrides/exposure.max_single", headers=AUTH)
test("DELETE /admin/config/overrides/key → 200", r.status_code == 200)
r2 = client.get("/admin/config/overrides", headers=AUTH)
test("  override removed", len(r2.json()) == 0)

# ─── 10. Audit Log ───────────────────────────────────────────────
print("\n[admin/audit-log]")
r = client.get("/admin/audit-log", headers=AUTH)
test("GET /admin/audit-log → 200", r.status_code == 200)
al = r.json()
test("  is list", isinstance(al, list))
test("  has entries", len(al) >= 1)
entry = al[0]
test("  entry has id", isinstance(entry.get("id"), int))
test("  entry has timestamp", isinstance(entry.get("timestamp"), str))
test("  entry has key", isinstance(entry.get("key"), str))
test("  entry has old_value", "old_value" in entry)
test("  entry has new_value", "new_value" in entry)
test("  entry has source", entry.get("source") in ("user", "system"))
test("  entry has user", isinstance(entry.get("user"), str))

# ─── 11. Marginal Risk ───────────────────────────────────────────
print("\n[portfolio/marginal-risk]")
r = client.get("/portfolio/marginal-risk", headers=AUTH)
test("GET /portfolio/marginal-risk → 200", r.status_code == 200)
mr = r.json()
test("  has total_risk", isinstance(mr.get("total_risk"), (int, float)))
test("  has expected_return", isinstance(mr.get("expected_return"), (int, float)))
test("  has quality_ratio", isinstance(mr.get("quality_ratio"), (int, float)))
test("  has contributors list", isinstance(mr.get("contributors"), list))
c = mr["contributors"][0]
test("  contributor has asset", isinstance(c.get("asset"), str))
test("  contributor has contribution_pct", isinstance(c.get("contribution_pct"), (int, float)))
test("  has scenarios list", isinstance(mr.get("scenarios"), list))
s = mr["scenarios"][0]
test("  scenario has name", isinstance(s.get("name"), str))
test("  scenario has probability", isinstance(s.get("probability"), (int, float)))
test("  scenario has impact", isinstance(s.get("impact"), (int, float)))
test("  scenario has color", isinstance(s.get("color"), str))

# ─── 12. Kill Switch ─────────────────────────────────────────────
print("\n[portfolio/kill-switch]")
r = client.get("/portfolio/kill-switch", headers=AUTH)
test("GET /portfolio/kill-switch → 200", r.status_code == 200)
ks = r.json()
test("  has active (bool)", isinstance(ks.get("active"), bool))
test("  has reason (str|null)", ks.get("reason") is None or isinstance(ks["reason"], str))

# Toggle on
r = client.post("/portfolio/kill-switch", headers=AUTH, json={"active": True})
test("POST /portfolio/kill-switch active=true → 200", r.status_code == 200)
r2 = client.get("/portfolio/kill-switch", headers=AUTH)
test("  kill switch now active", r2.json().get("active") is True)

# Toggle off
r = client.post("/portfolio/kill-switch", headers=AUTH, json={"active": False})
test("POST /portfolio/kill-switch active=false → 200", r.status_code == 200)
r2 = client.get("/portfolio/kill-switch", headers=AUTH)
test("  kill switch now inactive", r2.json().get("active") is False)

# ─── 13. Learning Patterns ───────────────────────────────────────
print("\n[admin/learning/patterns]")
r = client.get("/admin/learning/patterns", headers=AUTH)
test("GET /admin/learning/patterns → 200", r.status_code == 200)
lp = r.json()
test("  is list", isinstance(lp, list))
test("  has entries", len(lp) >= 1)
p = lp[0]
test("  pattern has pattern", isinstance(p.get("pattern"), str))
test("  pattern has frequency", isinstance(p.get("frequency"), int))
test("  pattern has confidence", isinstance(p.get("confidence"), (int, float)))
test("  pattern has win_rate", isinstance(p.get("win_rate"), (int, float)))
test("  pattern has last_seen", isinstance(p.get("last_seen"), str))

# ─── 14. Alerts ──────────────────────────────────────────────────
print("\n[admin/alerts]")
r = client.get("/admin/alerts", headers=AUTH)
test("GET /admin/alerts → 200", r.status_code == 200)
alerts = r.json()
test("  is list", isinstance(alerts, list))
test("  has entries", len(alerts) >= 1)
a = alerts[0]
test("  alert has id", isinstance(a.get("id"), int))
test("  alert has type", a.get("type") in ("info", "warning", "error", "critical"))
test("  alert has message", isinstance(a.get("message"), str))
test("  alert has timestamp", isinstance(a.get("timestamp"), str))
test("  alert has dismissed", isinstance(a.get("dismissed"), bool))

# ─── 15. Dismiss Alert ───────────────────────────────────────────
print("\n[admin/alerts/dismiss]")
undismissed = [x for x in alerts if not x["dismissed"]]
if undismissed:
    aid = undismissed[0]["id"]
    r = client.post(f"/admin/alerts/{aid}/dismiss", headers=AUTH)
    test(f"POST /admin/alerts/{aid}/dismiss → 200", r.status_code == 200)
    r2 = client.get("/admin/alerts", headers=AUTH)
    dismissed_now = [x for x in r2.json() if x["id"] == aid][0]
    test("  alert now dismissed", dismissed_now.get("dismissed") is True)

r = client.post("/admin/alerts/9999/dismiss", headers=AUTH)
test("POST /admin/alerts/9999/dismiss → 404", r.status_code == 404)

# ─── 16. AI Optimize ─────────────────────────────────────────────
print("\n[admin/ai/optimize]")
# First reset config so suggestions are generated
client.post("/admin/config", headers=AUTH, json={"key": "confidence.min_trade", "value": 0.65})
r = client.get("/admin/ai/optimize", headers=AUTH)
test("GET /admin/ai/optimize → 200", r.status_code == 200)
ai = r.json()
test("  is list", isinstance(ai, list))
test("  has suggestions", len(ai) >= 1)
sg = ai[0]
test("  suggestion has key", isinstance(sg.get("key"), str))
test("  suggestion has current", isinstance(sg.get("current"), (int, float)))
test("  suggestion has suggested", isinstance(sg.get("suggested"), (int, float)))
test("  suggestion has reason", isinstance(sg.get("reason"), str))

# ─── Summary ─────────────────────────────────────────────────────
print("\n" + "=" * 60)
print(f"RESULTS: {passed} passed, {failed} failed, {passed + failed} total")
print("=" * 60)

sys.exit(1 if failed else 0)
