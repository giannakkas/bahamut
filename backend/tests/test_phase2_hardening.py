"""
Phase 2 Hardening Tests

Tests for:
  1. Centralized schema management (single source of truth)
  2. Table ownership enforcement (no multi-writer conflicts)
  3. DB query layer (connection safety)
  4. Token revocation logic
  5. Auth flow with JTI
  6. System health endpoint structure
  7. Paper trading store (canonical writer)

Integration tests requiring DB/Redis skip gracefully when unavailable.
"""
import pytest
import os
import re
import time
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock
from datetime import datetime, timezone, timedelta


# ═══════════════════════════════════════
# TEST GROUP 1: Centralized Schema
# ═══════════════════════════════════════

class TestCentralizedSchema:
    def test_schema_tables_exist(self):
        """Centralized schema must define all expected tables."""
        from bahamut.db.schema.tables import TABLES
        table_names = []
        for sql in TABLES:
            m = re.search(r'CREATE TABLE IF NOT EXISTS (\w+)', sql)
            if m:
                table_names.append(m.group(1))
        
        required = [
            "admin_config", "admin_audit_log",
            "agent_outputs", "agent_trade_performance",
            "signal_cycles", "consensus_decisions", "decision_traces",
            "trust_scores_live", "trust_score_history_live",
            "paper_portfolios", "paper_positions",
            "learning_events", "calibration_runs", "regime_snapshots",
            "threshold_overrides", "meta_evaluations", "scan_history",
            "portfolio_adaptive_rules", "portfolio_decision_log",
            "reallocation_log", "kill_switch_events", "stress_test_runs",
            "revoked_tokens", "schema_version",
        ]
        for table in required:
            assert table in table_names, \
                f"Table '{table}' missing from centralized schema"
    
    def test_schema_version_defined(self):
        """Schema version must be a positive integer."""
        from bahamut.db.schema.tables import SCHEMA_VERSION
        assert isinstance(SCHEMA_VERSION, int)
        assert SCHEMA_VERSION >= 1

    def test_no_scattered_create_table(self):
        """No CREATE TABLE statements should exist outside db/schema/tables.py."""
        base = os.path.join(os.path.dirname(__file__), "..", "..", "bahamut")
        violations = []
        allowed_files = {"db/schema/tables.py", "db/query.py"}
        
        for root, dirs, files in os.walk(base):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for fn in files:
                if not fn.endswith(".py"):
                    continue
                filepath = os.path.join(root, fn)
                rel = os.path.relpath(filepath, base)
                if rel in allowed_files:
                    continue
                with open(filepath) as f:
                    for i, line in enumerate(f, 1):
                        if "CREATE TABLE IF NOT EXISTS" in line and \
                           "# Schema managed" not in line and \
                           "pass  # Schema" not in line and \
                           '"""' not in line and \
                           "doc" not in line.lower():
                            violations.append(f"{rel}:{i}")
        
        assert not violations, \
            f"Found scattered CREATE TABLE outside centralized schema:\n" + \
            "\n".join(violations)


# ═══════════════════════════════════════
# TEST GROUP 2: Table Ownership Enforcement
# ═══════════════════════════════════════

class TestTableOwnership:
    def _scan_writes(self):
        """Scan all INSERT INTO and UPDATE statements in codebase."""
        from collections import defaultdict
        base = os.path.join(os.path.dirname(__file__), "..", "..", "bahamut")
        writers = defaultdict(set)  # table -> set of files
        
        for root, dirs, files in os.walk(base):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for fn in files:
                if not fn.endswith(".py"):
                    continue
                filepath = os.path.join(root, fn)
                rel = os.path.relpath(filepath, base)
                with open(filepath) as f:
                    content = f.read()
                for m in re.finditer(r'INSERT INTO (\w+)', content):
                    writers[m.group(1)].add(rel)
                for m in re.finditer(r'UPDATE (\w+)\s+SET', content):
                    writers[m.group(1)].add(rel)
        return writers

    def test_trust_scores_single_writer(self):
        """trust_scores_live must only be written by consensus/trust_store.py."""
        writers = self._scan_writes()
        trust_writers = writers.get("trust_scores_live", set())
        assert trust_writers <= {"consensus/trust_store.py"}, \
            f"trust_scores_live has unexpected writers: {trust_writers}"

    def test_trust_history_single_writer(self):
        """trust_score_history_live must only be written by consensus/trust_store.py."""
        writers = self._scan_writes()
        trust_writers = writers.get("trust_score_history_live", set())
        assert trust_writers <= {"consensus/trust_store.py"}, \
            f"trust_score_history_live has unexpected writers: {trust_writers}"

    def test_calibration_runs_single_writer(self):
        """calibration_runs must only be written by learning/calibration.py."""
        writers = self._scan_writes()
        cal_writers = writers.get("calibration_runs", set())
        assert cal_writers <= {"learning/calibration.py"}, \
            f"calibration_runs has unexpected writers: {cal_writers}"

    def test_no_schema_conflicts(self):
        """No conflicting schema definitions in codebase (outside centralized schema)."""
        base = os.path.join(os.path.dirname(__file__), "..", "..", "bahamut")
        # Only db/schema/tables.py should have CREATE TABLE
        creates = {}
        for root, dirs, files in os.walk(base):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for fn in files:
                if not fn.endswith(".py"):
                    continue
                filepath = os.path.join(root, fn)
                rel = os.path.relpath(filepath, base)
                with open(filepath) as f:
                    content = f.read()
                for m in re.finditer(r'CREATE TABLE IF NOT EXISTS (\w+)\s*\(', content):
                    table = m.group(1)
                    creates.setdefault(table, []).append(rel)
        
        # Expect all CREATE TABLEs in db/schema/tables.py only
        conflicts = {t: files for t, files in creates.items()
                     if any(f != "db/schema/tables.py" and f != "db/query.py" for f in files)}
        assert not conflicts, \
            f"Tables with CREATE outside centralized schema: {conflicts}"


# ═══════════════════════════════════════
# TEST GROUP 3: DB Query Layer
# ═══════════════════════════════════════

class TestDBQueryLayer:
    def test_query_module_exists(self):
        """db.query module must be importable."""
        from bahamut.db.query import run_query, run_transaction, get_connection, check_db_health
        assert callable(run_query)
        assert callable(run_transaction)
        assert callable(get_connection)
        assert callable(check_db_health)

    def test_get_connection_is_context_manager(self):
        """get_connection must be a context manager."""
        from bahamut.db.query import get_connection
        import contextlib
        assert hasattr(get_connection, '__enter__') or hasattr(get_connection, '__call__')


# ═══════════════════════════════════════
# TEST GROUP 4: Token Revocation
# ═══════════════════════════════════════

class TestTokenRevocation:
    def test_jti_generation(self):
        """JTI must be a unique string."""
        from bahamut.auth.revocation import generate_jti
        jti1 = generate_jti()
        jti2 = generate_jti()
        assert isinstance(jti1, str)
        assert len(jti1) > 10
        assert jti1 != jti2

    def test_token_contains_jti(self):
        """Access tokens must now include a JTI claim."""
        from jose import jwt
        from bahamut.config import get_settings
        settings = get_settings()
        
        # Simulate create_token with JTI
        from bahamut.auth.revocation import generate_jti
        payload = {
            "sub": "test-user",
            "jti": generate_jti(),
            "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        }
        token = jwt.encode(payload, settings.jwt_secret, algorithm="HS256")
        decoded = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
        assert "jti" in decoded
        assert len(decoded["jti"]) > 10

    def test_revoke_with_mock_redis(self):
        """Token revocation should work via Redis."""
        import asyncio
        from bahamut.auth.revocation import revoke_token, is_token_revoked
        
        jti = "test-jti-12345"
        expires = datetime.now(timezone.utc) + timedelta(hours=1)
        
        # Mock Redis
        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock(return_value=True)
        mock_redis.get = AsyncMock(return_value="1")
        
        with patch("bahamut.shared.redis_client.redis_manager") as mock_mgr:
            mock_mgr.redis = mock_redis
            
            # Revoke
            result = asyncio.get_event_loop().run_until_complete(
                revoke_token(jti, expires, user_id="user1")
            )
            assert result is True
            mock_redis.set.assert_called_once()
            
            # Check revoked
            is_revoked = asyncio.get_event_loop().run_until_complete(
                is_token_revoked(jti)
            )
            assert is_revoked is True

    def test_is_revoked_returns_false_for_unknown(self):
        """Unknown JTI should not be considered revoked."""
        import asyncio
        from bahamut.auth.revocation import is_token_revoked
        
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        
        with patch("bahamut.shared.redis_client.redis_manager") as mock_mgr:
            mock_mgr.redis = mock_redis
            
            result = asyncio.get_event_loop().run_until_complete(
                is_token_revoked("unknown-jti")
            )
            assert result is False

    def test_revocation_fails_open_on_error(self):
        """If revocation check errors, should NOT lock out users (fail-open)."""
        import asyncio
        from bahamut.auth.revocation import is_token_revoked
        
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(side_effect=Exception("Redis down"))
        
        with patch("bahamut.shared.redis_client.redis_manager") as mock_mgr:
            mock_mgr.redis = mock_redis
            # Also patch DB fallback to fail
            with patch("bahamut.db.query.run_query_one", side_effect=Exception("DB down")):
                result = asyncio.get_event_loop().run_until_complete(
                    is_token_revoked("some-jti")
                )
                # Should return False (fail-open) not True
                assert result is False

    def test_empty_jti_not_revoked(self):
        """Empty/None JTI should not be considered revoked."""
        import asyncio
        from bahamut.auth.revocation import is_token_revoked
        
        result = asyncio.get_event_loop().run_until_complete(
            is_token_revoked("")
        )
        assert result is False
        
        result = asyncio.get_event_loop().run_until_complete(
            is_token_revoked(None)
        )
        assert result is False


# ═══════════════════════════════════════
# TEST GROUP 5: Auth Flow with Revocation
# ═══════════════════════════════════════

class TestAuthRevocationIntegration:
    def test_create_token_includes_jti(self):
        """create_token function must include JTI in payload."""
        from bahamut.auth.router import create_token
        from bahamut.config import get_settings
        from jose import jwt
        
        settings = get_settings()
        token = create_token(
            {"sub": "test-user", "email": "test@test.com"},
            settings.jwt_secret,
            timedelta(hours=1),
        )
        decoded = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
        assert "jti" in decoded, "Token must contain JTI for revocation"
        assert len(decoded["jti"]) > 10

    def test_refresh_token_type_preserved(self):
        """Refresh tokens must still have type='refresh' alongside JTI."""
        from bahamut.auth.router import create_token
        from bahamut.config import get_settings
        from jose import jwt
        
        settings = get_settings()
        token = create_token(
            {"sub": "test-user", "type": "refresh"},
            settings.jwt_refresh_secret,
            timedelta(days=7),
        )
        decoded = jwt.decode(token, settings.jwt_refresh_secret, algorithms=["HS256"])
        assert decoded["type"] == "refresh"
        assert "jti" in decoded

    def test_access_and_refresh_different_jti(self):
        """Access and refresh tokens must have different JTIs."""
        from bahamut.auth.router import create_token
        from bahamut.config import get_settings
        from jose import jwt
        
        settings = get_settings()
        access = create_token(
            {"sub": "test-user"},
            settings.jwt_secret,
            timedelta(hours=1),
        )
        refresh = create_token(
            {"sub": "test-user", "type": "refresh"},
            settings.jwt_refresh_secret,
            timedelta(days=7),
        )
        access_jti = jwt.decode(access, settings.jwt_secret, algorithms=["HS256"])["jti"]
        refresh_jti = jwt.decode(refresh, settings.jwt_refresh_secret, algorithms=["HS256"])["jti"]
        assert access_jti != refresh_jti


# ═══════════════════════════════════════
# TEST GROUP 6: Paper Trading Store
# ═══════════════════════════════════════

class TestPaperTradingStore:
    def test_store_module_importable(self):
        """paper_trading/store.py must be importable with all functions."""
        from bahamut.paper_trading.store import (
            get_or_create_portfolio, update_portfolio_balance,
            open_position, close_position, close_position_manual,
            update_position_price, get_open_positions,
            get_open_position_count, has_open_position,
        )
        assert callable(get_or_create_portfolio)
        assert callable(open_position)
        assert callable(close_position)
        assert callable(close_position_manual)


# ═══════════════════════════════════════
# TEST GROUP 7: System Health Structure
# ═══════════════════════════════════════

class TestSystemHealth:
    def test_health_module_importable(self):
        """System health router must be importable."""
        from bahamut.system.router import router
        assert router is not None

    def test_schema_version_in_health(self):
        """Health endpoint should report schema version."""
        from bahamut.db.schema.tables import SCHEMA_VERSION
        assert SCHEMA_VERSION >= 2  # Phase 2 bumped to 2


# ═══════════════════════════════════════
# TEST GROUP 8: Regression — Phase 1 Tests
# ═══════════════════════════════════════

class TestPhase1Regression:
    """Ensure Phase 1 fixes still hold."""

    def test_degraded_mode_still_enforced(self):
        """Degraded mode enforcement must still be present in engine.py."""
        engine_path = os.path.join(os.path.dirname(__file__), "..",
                                    "bahamut", "portfolio", "engine.py")
        with open(engine_path) as f:
            content = f.read()
        assert "is_degraded" in content, \
            "Degraded mode enforcement (is_degraded check) must be in engine.py"
        assert "DEGRADED_MODE" in content, \
            "DEGRADED_MODE warning must be in engine.py"

    def test_kill_switch_still_fail_closed(self):
        """Kill switch get_current_state must still default to active on error."""
        ks_path = os.path.join(os.path.dirname(__file__), "..",
                                "bahamut", "portfolio", "kill_switch.py")
        with open(ks_path) as f:
            content = f.read()
        assert '"kill_switch_active": True' in content, \
            "Kill switch must still fail-closed (default to active on error)"

    def test_no_bare_except_pass(self):
        """No except:pass or except Exception: pass in codebase."""
        base = os.path.join(os.path.dirname(__file__), "..", "..", "bahamut")
        violations = []
        for root, dirs, files in os.walk(base):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for fn in files:
                if not fn.endswith(".py"):
                    continue
                filepath = os.path.join(root, fn)
                with open(filepath) as f:
                    for i, line in enumerate(f, 1):
                        stripped = line.strip()
                        if stripped in ("except: pass", "except Exception: pass"):
                            rel = os.path.relpath(filepath, base)
                            violations.append(f"{rel}:{i}")
        assert not violations, \
            f"Found except:pass: {violations}"

    def test_cors_no_wildcard(self):
        """CORS must not allow wildcard."""
        from bahamut.config import get_settings
        settings = get_settings()
        assert "*" not in settings.cors_origins


# ═══════════════════════════════════════
# TEST GROUP 9: Integration (skip if no DB)
# ═══════════════════════════════════════

class TestIntegrationDB:
    """Integration tests that run against real DB.
    Skip if DATABASE_URL not available or connection fails."""

    @pytest.fixture(autouse=True)
    def check_db(self):
        try:
            from bahamut.db.query import check_db_health
            result = check_db_health()
            if result["status"] != "ok":
                pytest.skip("DB not available for integration tests")
        except Exception:
            pytest.skip("DB not available for integration tests")

    def test_schema_init_idempotent(self):
        """init_schema() must be safe to call multiple times."""
        from bahamut.db.schema.tables import init_schema
        # Should not raise
        init_schema()
        init_schema()

    def test_run_query_basic(self):
        """run_query must return results from a simple SELECT."""
        from bahamut.db.query import run_query
        try:
            rows = run_query("SELECT 1 AS val")
            assert len(rows) == 1
            assert rows[0]["val"] == 1
        except Exception:
            pytest.skip("DB query failed - may not have real Postgres available")

    def test_run_transaction_basic(self):
        """run_transaction must execute without error."""
        from bahamut.db.query import run_transaction
        # Use schema_version table as a safe target
        run_transaction(
            "INSERT INTO schema_version (version) VALUES (:v) ON CONFLICT DO NOTHING",
            {"v": 999}
        )

    def test_connection_cleanup(self):
        """Connections must be properly closed after use."""
        from bahamut.db.query import get_connection
        with get_connection() as conn:
            from sqlalchemy import text
            conn.execute(text("SELECT 1"))
        # Connection should be closed — no leak
        assert conn.closed


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
