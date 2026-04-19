"""
Bahamut.AI — Trade Candidates Scoring Tests

Run: cd backend && PYTHONPATH=. python3 -m pytest bahamut/tests/test_candidates.py -v
"""
import pytest


class TestEMACrossScoring:
    def test_bull_regime_converging_emas_high_score(self):
        """Close above EMA200 + EMAs converging = high score."""
        from bahamut.trading.candidates import score_ema_cross
        indicators = {
            "close": 100, "ema_20": 99.8, "ema_50": 100.0, "ema_200": 95,
            "rsi_14": 50, "atr_14": 2, "volume": 1000, "volume_sma_20": 800,
        }
        prev = {"ema_20": 99.5, "ema_50": 100.0}
        c = score_ema_cross("BTCUSD", "crypto", "v5_base", [], indicators, prev)
        assert c is not None
        assert c.score >= 60  # Bull + converging + RSI neutral
        assert c.regime in ("RANGE", "TREND")
        assert any("EMA200" in r for r in c.reasons)

    def test_bear_regime_capped(self):
        """Below EMA200 = capped at 35 max."""
        from bahamut.trading.candidates import score_ema_cross
        indicators = {
            "close": 90, "ema_20": 91, "ema_50": 92, "ema_200": 100,
            "rsi_14": 45, "atr_14": 2, "volume": 500, "volume_sma_20": 600,
        }
        c = score_ema_cross("ETHUSD", "crypto", "v5_base", [], indicators, None)
        assert c is not None
        assert c.score <= 35
        assert c.regime == "BEAR"

    def test_already_crossed_lower_score(self):
        """EMAs already spread = lower score than converging."""
        from bahamut.trading.candidates import score_ema_cross
        ind_spread = {
            "close": 110, "ema_20": 108, "ema_50": 102, "ema_200": 95,
            "rsi_14": 55, "atr_14": 2, "volume": 500, "volume_sma_20": 500,
        }
        ind_close = {
            "close": 101, "ema_20": 100.1, "ema_50": 100.2, "ema_200": 95,
            "rsi_14": 50, "atr_14": 2, "volume": 500, "volume_sma_20": 500,
        }
        c_spread = score_ema_cross("AAPL", "stock", "v5_base", [], ind_spread, None)
        c_close = score_ema_cross("AAPL", "stock", "v5_base", [], ind_close, None)
        assert c_close.score > c_spread.score


class TestBreakoutScoring:
    def _make_candles(self, n=35, base=100, high_at=None):
        candles = []
        for i in range(n):
            h = base + 2
            if high_at and i == high_at:
                h = base + 10  # spike
            candles.append({"open": base, "high": h, "low": base - 2, "close": base + 1, "volume": 1000})
        return candles

    def test_near_breakout_level(self):
        """Price just below 20-bar high = decent score."""
        from bahamut.trading.candidates import score_breakout
        candles = self._make_candles(35, base=100)
        # ref_high will be ~102 (base + 2)
        # Set close just below it
        candles[-1]["close"] = 101.5
        indicators = {"close": 101.5, "atr_14": 2, "ema_200": 90, "rsi_14": 55}
        c = score_breakout("XAUUSD", "commodity", candles, indicators)
        assert c is not None
        assert c.score >= 20

    def test_confirmed_breakout_high_score(self):
        """Price above 20-bar high for 3 bars = high score."""
        from bahamut.trading.candidates import score_breakout
        candles = self._make_candles(35, base=100)
        # Reference high is ~102
        ref_high = max(c["high"] for c in candles[:20])
        # Last 4 candles all above
        for i in range(-4, 0):
            candles[i]["close"] = ref_high + 5
            candles[i]["high"] = ref_high + 7
        candles[-1]["close"] = ref_high + 5
        indicators = {"close": ref_high + 5, "atr_14": 2, "ema_200": 90, "rsi_14": 60}
        c = score_breakout("SOLUSD", "crypto", candles, indicators)
        assert c is not None
        assert c.score >= 50
        assert c.regime == "BREAKOUT"

    def test_deep_below_crash(self):
        """Deep below EMA200 = capped score."""
        from bahamut.trading.candidates import score_breakout
        candles = self._make_candles(35, base=50)
        indicators = {"close": 50, "atr_14": 2, "ema_200": 100, "rsi_14": 25}
        c = score_breakout("COIN", "stock", candles, indicators)
        assert c is not None
        assert c.score <= 20


class TestCandidatesReadOnly:
    def test_does_not_import_execution_engine(self):
        """Candidates module must not import production engine."""
        import inspect
        from bahamut.trading import candidates
        source = inspect.getsource(candidates)
        assert "ExecutionEngine" not in source
        assert "submit_signal" not in source
        assert "get_execution_engine" not in source

    def test_indicator_format(self):
        from bahamut.trading.candidates import _fmt_indicators
        ind = {"close": 100, "rsi_14": 55, "ema_20": 101, "ema_50": 99,
               "ema_200": 90, "atr_14": 2.5, "volume": 1200, "volume_sma_20": 1000}
        fmt = _fmt_indicators(ind)
        assert fmt["ema_alignment"] == "bullish_stack"  # ema20 > ema50 > ema200
        assert fmt["rsi"] == 55.0
        assert fmt["volume_ratio"] == 1.2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
