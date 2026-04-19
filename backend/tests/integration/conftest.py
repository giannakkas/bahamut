"""Shared fixtures for integration tests."""
import pytest
import json
import os

# Force test environment
os.environ["ENVIRONMENT"] = "test"
os.environ["REDIS_URL"] = "redis://localhost:6379/15"  # Use DB 15 for tests


@pytest.fixture
def mock_redis(monkeypatch):
    """In-memory Redis mock using dict."""
    store = {}

    class FakeRedis:
        def __init__(self, *a, **kw):
            pass

        def get(self, key):
            return store.get(key)

        def set(self, key, value, **kw):
            store[key] = value
            return True

        def setex(self, key, ttl, value):
            store[key] = value
            return True

        def incr(self, key):
            store[key] = int(store.get(key, 0)) + 1
            return store[key]

        def incrbyfloat(self, key, amount):
            store[key] = float(store.get(key, 0)) + amount
            return store[key]

        def expire(self, key, ttl):
            return True

        def delete(self, *keys):
            for k in keys:
                store.pop(k, None)

        def exists(self, key):
            return key in store

        def lpush(self, key, *values):
            if key not in store:
                store[key] = []
            for v in values:
                store[key].insert(0, v)

        def ltrim(self, key, start, end):
            if key in store and isinstance(store[key], list):
                store[key] = store[key][start:end + 1]

        def lrange(self, key, start, end):
            if key not in store:
                return []
            return store[key][start:end + 1 if end >= 0 else None]

        def hset(self, key, field, value):
            if key not in store:
                store[key] = {}
            store[key][field] = value

        def hget(self, key, field):
            return store.get(key, {}).get(field)

        def hgetall(self, key):
            return store.get(key, {})

        def pipeline(self):
            return FakePipeline(self)

        def scan_iter(self, match="*"):
            import fnmatch
            return [k for k in store if fnmatch.fnmatch(k, match)]

        @classmethod
        def from_url(cls, *a, **kw):
            return cls()

    class FakePipeline:
        def __init__(self, redis):
            self._redis = redis
            self._commands = []

        def incrbyfloat(self, key, amount):
            self._commands.append(("incrbyfloat", key, amount))
            return self

        def get(self, key):
            self._commands.append(("get", key))
            return self

        def execute(self):
            results = []
            for cmd in self._commands:
                if cmd[0] == "incrbyfloat":
                    results.append(self._redis.incrbyfloat(cmd[1], cmd[2]))
                elif cmd[0] == "get":
                    results.append(self._redis.get(cmd[1]))
            self._commands = []
            return results

    monkeypatch.setattr("redis.from_url", FakeRedis.from_url)
    return store


class MockResponse:
    """Reusable mock HTTP response."""
    def __init__(self, status_code=200, data=None):
        self.status_code = status_code
        self._data = data or {}

    def json(self):
        return self._data


@pytest.fixture
def mock_binance_fill(monkeypatch):
    """Mock Binance that returns FILLED immediately."""
    def _post(*args, **kwargs):
        return MockResponse(200, {
            "orderId": 12345,
            "status": "FILLED",
            "avgPrice": "100.50",
            "executedQty": "1.0",
            "clientOrderId": "bah_test_123",
        })
    monkeypatch.setattr("httpx.post", _post)


@pytest.fixture
def mock_binance_pending(monkeypatch):
    """Mock Binance that returns NEW (not yet filled)."""
    call_count = {"n": 0}

    def _post(*args, **kwargs):
        return MockResponse(200, {
            "orderId": 12345,
            "status": "NEW",
            "avgPrice": "0",
            "executedQty": "0",
            "clientOrderId": "bah_test_123",
        })

    def _get(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] >= 3:
            return MockResponse(200, {
                "orderId": 12345,
                "status": "FILLED",
                "avgPrice": "100.75",
                "executedQty": "1.0",
            })
        return MockResponse(200, {
            "orderId": 12345,
            "status": "NEW",
            "avgPrice": "0",
            "executedQty": "0",
        })

    monkeypatch.setattr("httpx.post", _post)
    monkeypatch.setattr("httpx.get", _get)
    return call_count


@pytest.fixture
def mock_binance_rejected(monkeypatch):
    """Mock Binance that returns error."""
    def _post(*args, **kwargs):
        return MockResponse(400, {"code": -2010, "msg": "Insufficient margin"})
    monkeypatch.setattr("httpx.post", _post)
