#!/usr/bin/env python3
"""
Bahamut.AI — Production Smoke Test

Validates core system functionality against a live deployment.

Usage:
    python smoke_test.py --base-url https://bahamut-production.up.railway.app
    python smoke_test.py --base-url http://localhost:8000 --email test@test.com --password test123

Exit code: 0 if all checks pass, 1 if any fail.
"""
import argparse
import json
import sys
import time
import requests

# ANSI colors
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
RESET = "\033[0m"
BOLD = "\033[1m"


class SmokeTest:
    def __init__(self, base_url: str, email: str = None, password: str = None):
        self.base = base_url.rstrip("/")
        self.api = f"{self.base}/api/v1"
        self.email = email
        self.password = password
        self.access_token = None
        self.refresh_token = None
        self.results = []

    def _check(self, name: str, fn) -> bool:
        start = time.monotonic()
        try:
            result = fn()
            elapsed = round((time.monotonic() - start) * 1000)
            if result:
                self.results.append(("PASS", name, elapsed))
                print(f"  {GREEN}✓ PASS{RESET}  {name} ({elapsed}ms)")
                return True
            else:
                self.results.append(("FAIL", name, elapsed))
                print(f"  {RED}✗ FAIL{RESET}  {name} ({elapsed}ms)")
                return False
        except Exception as e:
            elapsed = round((time.monotonic() - start) * 1000)
            self.results.append(("FAIL", name, elapsed))
            print(f"  {RED}✗ FAIL{RESET}  {name} ({elapsed}ms) — {str(e)[:100]}")
            return False

    def run(self):
        print(f"\n{BOLD}Bahamut.AI Smoke Test{RESET}")
        print(f"Target: {self.base}\n")

        # 1. Basic connectivity
        self._check("Health endpoint (GET /health)", self._test_health)
        self._check("System health (GET /api/v1/system/health)", self._test_system_health)
        self._check("Metrics endpoint (GET /metrics)", self._test_metrics)

        # 2. Auth flow (if credentials provided)
        if self.email and self.password:
            self._check("Login (POST /api/v1/auth/login)", self._test_login)
            if self.access_token:
                self._check("Protected endpoint (GET /api/v1/auth/me)", self._test_protected)
                self._check("Refresh token (POST /api/v1/auth/refresh)", self._test_refresh)
                self._check("Logout (POST /api/v1/auth/logout)", self._test_logout)
        else:
            print(f"  {YELLOW}⊘ SKIP{RESET}  Auth tests (no credentials provided)")

        # 3. System checks
        self._check("System health — DB status", self._test_db_status)
        self._check("System health — Redis status", self._test_redis_status)
        self._check("System health — Schema status", self._test_schema_status)
        self._check("System health — No critical degraded", self._test_no_critical_degraded)

        # Summary
        passed = sum(1 for r in self.results if r[0] == "PASS")
        failed = sum(1 for r in self.results if r[0] == "FAIL")
        total = len(self.results)

        print(f"\n{BOLD}Results: {passed}/{total} passed", end="")
        if failed > 0:
            print(f", {RED}{failed} FAILED{RESET}")
        else:
            print(f" {GREEN}— ALL PASS{RESET}")

        return failed == 0

    # ─── Test implementations ───

    def _test_health(self):
        r = requests.get(f"{self.base}/health", timeout=5)
        return r.status_code == 200 and r.json().get("status") == "healthy"

    def _test_system_health(self):
        r = requests.get(f"{self.api}/system/health", timeout=10)
        data = r.json()
        return r.status_code == 200 and data.get("status") in ("healthy", "degraded")

    def _test_metrics(self):
        r = requests.get(f"{self.base}/metrics", timeout=5)
        return r.status_code == 200

    def _test_login(self):
        r = requests.post(f"{self.api}/auth/login", json={
            "email": self.email, "password": self.password
        }, timeout=10)
        if r.status_code == 200:
            data = r.json()
            self.access_token = data.get("access_token")
            self.refresh_token = data.get("refresh_token")
            return bool(self.access_token and self.refresh_token)
        return False

    def _test_protected(self):
        r = requests.get(f"{self.api}/auth/me", headers={
            "Authorization": f"Bearer {self.access_token}"
        }, timeout=5)
        return r.status_code == 200 and "email" in r.json()

    def _test_refresh(self):
        r = requests.post(f"{self.api}/auth/refresh", json={
            "refresh_token": self.refresh_token
        }, timeout=5)
        if r.status_code == 200:
            new_token = r.json().get("access_token")
            if new_token:
                self.access_token = new_token
                return True
        return False

    def _test_logout(self):
        r = requests.post(f"{self.api}/auth/logout", headers={
            "Authorization": f"Bearer {self.access_token}"
        }, timeout=5)
        return r.status_code == 200

    def _test_db_status(self):
        r = requests.get(f"{self.api}/system/health", timeout=10)
        return r.json().get("checks", {}).get("db", {}).get("status") == "ok"

    def _test_redis_status(self):
        r = requests.get(f"{self.api}/system/health", timeout=10)
        return r.json().get("checks", {}).get("redis", {}).get("status") == "ok"

    def _test_schema_status(self):
        r = requests.get(f"{self.api}/system/health", timeout=10)
        return r.json().get("checks", {}).get("schema", {}).get("status") in ("ok", "upgrading")

    def _test_no_critical_degraded(self):
        r = requests.get(f"{self.api}/system/health", timeout=10)
        degraded = r.json().get("checks", {}).get("degraded", {})
        return degraded.get("severity") != "critical"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Bahamut.AI Production Smoke Test")
    parser.add_argument("--base-url", required=True, help="Base URL of the API")
    parser.add_argument("--email", help="Test user email for auth tests")
    parser.add_argument("--password", help="Test user password for auth tests")
    args = parser.parse_args()

    test = SmokeTest(args.base_url, args.email, args.password)
    success = test.run()
    sys.exit(0 if success else 1)
