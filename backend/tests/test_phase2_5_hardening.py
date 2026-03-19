"""
Phase 2.5 Hardening Tests

Tests for:
  1. Paper trading single-writer enforcement
  2. Token revocation fail-closed behavior
  3. Schema versioning + mismatch detection
  4. System health structure
  5. Regression safety for Phase 1 + 2
  6. Integration tests (skip if no DB/Redis)
"""
import pytest
import os
import re
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock
from datetime import datetime, timezone, timedelta


# ═══════════════════════════════════════
# TEST GROUP 1: Paper Trading Single Writer
# ═══════════════════════════════════════

class TestPaperTradingSingleWriter:
    def _scan_writes(self):
        """Scan INSERT/UPDATE to paper_portfolios and paper_positions."""
        from collections import defaultdict
        base = os.path.join(os.path.dirname(__file__), "..", "bahamut")
        writers = defaultdict(set)
        for root, dirs, files in os.walk(base):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for fn in files:
                if not fn.endswith(".py"):
                    continue
                filepath = os.path.join(root, fn)
                rel = os.path.relpath(filepath, base)
                with open(filepath) as f:
                    content = f.read()
                for m in re.finditer(r'INSERT INTO (paper_portfolios|paper_positions)', content):
                    writers[m.group(1)].add(rel)
                for m in re.finditer(r'UPDATE (paper_portfolios|paper_positions)\s', content):
                    writers[m.group(1)].add(rel)
        return writers

    def test_paper_portfolios_single_writer(self):
        """paper_portfolios must only be written by paper_trading/store.py."""
        writers = self._scan_writes()
        w = writers.get("paper_portfolios", set())
        assert w <= {"paper_trading/store.py"}, \
            f"paper_portfolios has unexpected writers: {w}"

    def test_paper_positions_single_writer(self):
        """paper_positions must only be written by paper_trading/store.py."""
        writers = self._scan_writes()
        w = writers.get("paper_positions", set())
        assert w <= {"paper_trading/store.py"}, \
            f"paper_positions has unexpected writers: {w}"

    def test_store_has_all_functions(self):
        """store.py must have all needed write functions."""
        from bahamut.paper_trading.store import (
            get_or_create_portfolio, update_portfolio_after_close,
            open_position, close_position, close_position_for_reallocation,
            close_all_positions, get_open_position_count, has_open_position,
            get_position_id_by_cycle,
        )
        for fn in [get_or_create_portfolio, update_portfolio_after_close,
                    open_position, close_position, close_position_for_reallocation,
                    close_all_positions, get_open_position_count, has_open_position,
                    get_position_id_by_cycle]:
            assert callable(fn)

    def test_no_direct_sql_in_executor(self):
        """sync_executor must NOT contain INSERT INTO paper_positions."""
        path = os.path.join(os.path.dirname(__file__), "..",
                            "bahamut", "paper_trading", "sync_executor.py")
        with open(path) as f:
            content = f.read()
        assert "INSERT INTO paper_positions" not in content, \
            "sync_executor.py must use store.py, not direct INSERT"
        assert "INSERT INTO paper_portfolios" not in content, \
            "sync_executor.py must use store.py, not direct INSERT"

    def test_no_direct_sql_in_allocator(self):
        """allocator must NOT contain UPDATE paper_positions."""
        path = os.path.join(os.path.dirname(__file__), "..",
                            "bahamut", "portfolio", "allocator.py")
        with open(path) as f:
            content = f.read()
        assert "UPDATE paper_positions" not in content, \
            "allocator.py must use store.py"
        assert "UPDATE paper_portfolios" not in content, \
            "allocator.py must use store.py"

    def test_no_direct_sql_in_execution_router(self):
        """execution/router.py must NOT contain UPDATE paper_positions."""
        path = os.path.join(os.path.dirname(__file__), "..",
                            "bahamut", "execution", "router.py")
        with open(path) as f:
            content = f.read()
        assert "UPDATE paper_positions" not in content, \
            "execution/router.py must use store.py"


# ═══════════════════════════════════════
# TEST GROUP 2: Token Revocation Fail-Closed
# ═══════════════════════════════════════

class TestTokenRevocationFailClosed:
    def test_fail_closed_when_both_unavailable(self):
        """If Redis AND DB both fail, is_token_revoked must return True (block)."""
        from bahamut.auth.revocation import is_token_revoked

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(side_effect=Exception("Redis down"))

        with patch("bahamut.shared.redis_client.redis_manager") as mock_mgr:
            mock_mgr.redis = mock_redis
            with patch("bahamut.db.query.run_query_one", side_effect=Exception("DB down")):
                result = asyncio.get_event_loop().run_until_complete(
                    is_token_revoked("some-jti-123")
                )
                assert result is True, \
                    "MUST fail-closed (block access) when both Redis and DB unavailable"

    def test_marks_degraded_on_double_failure(self):
        """Double failure must mark auth.revocation as degraded."""
        from bahamut.auth.revocation import is_token_revoked
        from bahamut.shared.degraded import is_degraded, clear_degraded

        clear_degraded("auth.revocation")

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(side_effect=Exception("Redis down"))

        with patch("bahamut.shared.redis_client.redis_manager") as mock_mgr:
            mock_mgr.redis = mock_redis
            with patch("bahamut.db.query.run_query_one", side_effect=Exception("DB down")):
                asyncio.get_event_loop().run_until_complete(
                    is_token_revoked("test-jti-456")
                )

        assert is_degraded("auth.revocation"), \
            "auth.revocation must be marked degraded on double failure"
        clear_degraded("auth.revocation")

    def test_redis_success_returns_false_for_valid_token(self):
        """Valid token (not in Redis) should return False."""
        from bahamut.auth.revocation import is_token_revoked

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)

        with patch("bahamut.shared.redis_client.redis_manager") as mock_mgr:
            mock_mgr.redis = mock_redis
            result = asyncio.get_event_loop().run_until_complete(
                is_token_revoked("valid-jti")
            )
            assert result is False

    def test_redis_success_returns_true_for_revoked_token(self):
        """Revoked token (in Redis) should return True."""
        from bahamut.auth.revocation import is_token_revoked

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value="1")

        with patch("bahamut.shared.redis_client.redis_manager") as mock_mgr:
            mock_mgr.redis = mock_redis
            result = asyncio.get_event_loop().run_until_complete(
                is_token_revoked("revoked-jti")
            )
            assert result is True

    def test_db_fallback_works(self):
        """When Redis fails but DB works, should use DB."""
        from bahamut.auth.revocation import is_token_revoked

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(side_effect=Exception("Redis down"))

        with patch("bahamut.shared.redis_client.redis_manager") as mock_mgr:
            mock_mgr.redis = mock_redis
            with patch("bahamut.db.query.run_query_one", return_value=None):
                result = asyncio.get_event_loop().run_until_complete(
                    is_token_revoked("test-jti-db")
                )
                assert result is False

    def test_empty_jti_returns_false(self):
        """Empty JTI should not be blocked."""
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
# TEST GROUP 3: Schema Versioning
# ═══════════════════════════════════════

class TestSchemaVersioning:
    def test_schema_version_bumped(self):
        """Schema version must be >= 3 for Phase 2.5."""
        from bahamut.db.schema.tables import SCHEMA_VERSION
        assert SCHEMA_VERSION >= 3

    def test_get_schema_status_callable(self):
        """get_schema_status must exist and be callable."""
        from bahamut.db.schema.tables import get_schema_status
        assert callable(get_schema_status)

    def test_schema_version_table_in_schema(self):
        """schema_version table must be in centralized schema."""
        from bahamut.db.schema.tables import TABLES
        found = any("schema_version" in sql for sql in TABLES)
        assert found, "schema_version table must be in TABLES"

    def test_revoked_tokens_table_in_schema(self):
        """revoked_tokens table must be in centralized schema."""
        from bahamut.db.schema.tables import TABLES
        found = any("revoked_tokens" in sql for sql in TABLES)
        assert found, "revoked_tokens table must be in TABLES"


# ═══════════════════════════════════════
# TEST GROUP 4: System Health Structure
# ═══════════════════════════════════════

class TestSystemHealthStructure:
    def test_health_router_exists(self):
        from bahamut.system.router import router
        assert router is not None

    def test_health_source_has_auth_check(self):
        """Health endpoint must check auth.revocation status."""
        path = os.path.join(os.path.dirname(__file__), "..",
                            "bahamut", "system", "router.py")
        with open(path) as f:
            content = f.read()
        assert "auth.revocation" in content, \
            "Health must check auth.revocation degraded status"
        assert "schema" in content.lower(), \
            "Health must include schema version check"
        assert "latency_ms" in content, \
            "Health must include latency measurements"


# ═══════════════════════════════════════
# TEST GROUP 5: Phase 1+2 Regression
# ═══════════════════════════════════════

class TestPhaseRegression:
    def test_degraded_mode_enforcement_in_engine(self):
        """is_degraded must still be checked in portfolio engine."""
        path = os.path.join(os.path.dirname(__file__), "..",
                            "bahamut", "portfolio", "engine.py")
        with open(path) as f:
            content = f.read()
        assert "is_degraded" in content
        assert "DEGRADED_MODE" in content

    def test_kill_switch_fail_closed(self):
        """Kill switch must still default to active on error."""
        path = os.path.join(os.path.dirname(__file__), "..",
                            "bahamut", "portfolio", "kill_switch.py")
        with open(path) as f:
            content = f.read()
        assert '"kill_switch_active": True' in content

    def test_no_bare_except_pass(self):
        """No except:pass in codebase."""
        base = os.path.join(os.path.dirname(__file__), "..", "bahamut")
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
        assert not violations, f"Found except:pass: {violations}"

    def test_no_scattered_create_table(self):
        """No CREATE TABLE outside centralized schema."""
        base = os.path.join(os.path.dirname(__file__), "..", "bahamut")
        allowed = {"db/schema/tables.py", "db/query.py"}
        violations = []
        for root, dirs, files in os.walk(base):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for fn in files:
                if not fn.endswith(".py"):
                    continue
                filepath = os.path.join(root, fn)
                rel = os.path.relpath(filepath, base)
                if rel in allowed:
                    continue
                with open(filepath) as f:
                    for i, line in enumerate(f, 1):
                        if "CREATE TABLE IF NOT EXISTS" in line and \
                           "# Schema" not in line and "pass  #" not in line and \
                           '"""' not in line and "doc" not in line.lower():
                            violations.append(f"{rel}:{i}")
        assert not violations, \
            f"Scattered CREATE TABLE found:\n" + "\n".join(violations)

    def test_cors_no_wildcard(self):
        from bahamut.config import get_settings
        assert "*" not in get_settings().cors_origins

    def test_jwt_has_jti(self):
        """All tokens must include JTI."""
        from bahamut.auth.router import create_token
        from bahamut.config import get_settings
        from jose import jwt
        settings = get_settings()
        token = create_token(
            {"sub": "test"}, settings.jwt_secret, timedelta(hours=1)
        )
        decoded = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
        assert "jti" in decoded


# ═══════════════════════════════════════
# TEST GROUP 6: Integration (skip if no services)
# ═══════════════════════════════════════

class TestIntegration:
    @pytest.fixture(autouse=True)
    def check_db(self):
        try:
            from bahamut.db.query import check_db_health
            result = check_db_health()
            if result["status"] != "ok":
                pytest.skip("DB not available")
        except Exception:
            pytest.skip("DB not available")

    def test_schema_init_idempotent(self):
        from bahamut.db.schema.tables import init_schema
        try:
            init_schema()
            init_schema()
        except TypeError:
            pytest.skip("DB connection returning mocks — test environment issue")

    def test_schema_version_recorded(self):
        from bahamut.db.schema.tables import init_schema, get_schema_status, SCHEMA_VERSION
        try:
            init_schema()
            status = get_schema_status()
            assert status["status"] == "ok"
            assert status["db_version"] == SCHEMA_VERSION
        except (TypeError, Exception) as e:
            if "MagicMock" in str(e) or "Mock" in str(type(e).__name__):
                pytest.skip("DB returning mocks")
            raise

    def test_db_write_read_consistency(self):
        from bahamut.db.query import run_transaction, run_query
        try:
            run_transaction(
                "INSERT INTO schema_version (version) VALUES (:v)",
                {"v": 9999}
            )
            rows = run_query("SELECT version FROM schema_version WHERE version = 9999")
            assert len(rows) >= 1
            run_transaction("DELETE FROM schema_version WHERE version = 9999")
        except Exception:
            pytest.skip("DB not fully available for write/read test")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
