"""Integration tests for safe_execute framework."""
import pytest
import os

os.environ.setdefault("ENVIRONMENT", "test")


class TestSafeExecute:
    """Tests for the safe_execute error handling wrapper."""

    def test_success_returns_value(self):
        from bahamut.shared.safe import safe_execute
        result = safe_execute(lambda: 42, category="test_success")
        assert result == 42

    def test_failure_returns_default(self):
        from bahamut.shared.safe import safe_execute
        result = safe_execute(
            lambda: 1 / 0, category="test_div_zero", default="fallback"
        )
        assert result == "fallback"

    def test_failure_returns_none_by_default(self):
        from bahamut.shared.safe import safe_execute
        result = safe_execute(lambda: 1 / 0, category="test_none")
        assert result is None

    def test_critical_reraises(self):
        from bahamut.shared.safe import safe_execute
        with pytest.raises(ZeroDivisionError):
            safe_execute(lambda: 1 / 0, category="test_critical", critical=True)

    def test_counts_failures(self, mock_redis):
        from bahamut.shared.safe import safe_execute
        safe_execute(lambda: 1 / 0, category="test_counter")
        safe_execute(lambda: 1 / 0, category="test_counter")
        # Counter should be 2
        key = "bahamut:counters:safe_test_counter_failures"
        assert mock_redis.get(key, 0) >= 2

    def test_args_passed_through(self):
        from bahamut.shared.safe import safe_execute
        result = safe_execute(lambda x, y: x + y, 3, 4, category="test_args")
        assert result == 7


class TestSafeCallDecorator:
    """Tests for the @safe_call decorator."""

    def test_decorator_wraps_function(self):
        from bahamut.shared.safe import safe_call

        @safe_call(category="test_decorator", default=-1)
        def divide(a, b):
            return a / b

        assert divide(10, 2) == 5.0
        assert divide(10, 0) == -1

    def test_decorator_critical_reraises(self):
        from bahamut.shared.safe import safe_call

        @safe_call(category="test_dec_critical", critical=True)
        def fail():
            raise ValueError("boom")

        with pytest.raises(ValueError, match="boom"):
            fail()
