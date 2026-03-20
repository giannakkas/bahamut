"""
Data Router — Multi-source data layer with validation

Features:
  1. Primary: Twelve Data
  2. Secondary fallback: OANDA
  3. Data validation: stale candle detection, missing data, spike filtering
  4. Source health tracking
"""
import time
import structlog
import numpy as np
from dataclasses import dataclass, field

logger = structlog.get_logger()


@dataclass
class SourceHealth:
    name: str
    consecutive_failures: int = 0
    last_success: float = 0.0
    last_failure: float = 0.0
    total_requests: int = 0
    total_failures: int = 0

    @property
    def is_healthy(self) -> bool:
        return self.consecutive_failures < 3

    def record_success(self):
        self.consecutive_failures = 0
        self.last_success = time.time()
        self.total_requests += 1

    def record_failure(self):
        self.consecutive_failures += 1
        self.last_failure = time.time()
        self.total_requests += 1
        self.total_failures += 1


@dataclass
class DataValidation:
    is_valid: bool = True
    warnings: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    stale: bool = False
    has_gaps: bool = False
    has_spikes: bool = False


class DataRouter:
    def __init__(self):
        self._sources = {
            "twelvedata": SourceHealth(name="twelvedata"),
            "oanda": SourceHealth(name="oanda"),
        }

    def validate_candles(self, candles: list[dict], expected_interval_minutes: int = 240) -> DataValidation:
        """Validate candle data quality."""
        v = DataValidation()

        if not candles:
            v.is_valid = False
            v.errors.append("No candle data")
            return v

        if len(candles) < 20:
            v.is_valid = False
            v.errors.append(f"Too few candles: {len(candles)} (need 20+)")
            return v

        # Stale data check
        last_candle = candles[-1]
        if "datetime" in last_candle:
            try:
                from datetime import datetime, timezone
                dt_str = last_candle["datetime"]
                # Parse common formats
                for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"]:
                    try:
                        last_dt = datetime.strptime(dt_str, fmt).replace(tzinfo=timezone.utc)
                        age_hours = (datetime.now(timezone.utc) - last_dt).total_seconds() / 3600
                        if age_hours > expected_interval_minutes / 60 * 3:
                            v.stale = True
                            v.warnings.append(f"Stale data: last candle {age_hours:.1f}h old")
                        break
                    except ValueError:
                        continue
            except Exception:
                pass

        # Missing data / gaps
        closes = [c["close"] for c in candles if c.get("close")]
        if any(c == 0 for c in closes):
            v.has_gaps = True
            v.warnings.append("Zero-value closes detected")

        # Spike detection (>5 ATR move in single candle)
        if len(closes) > 14:
            returns = np.diff(np.array(closes)) / np.array(closes[:-1])
            mean_return = np.mean(np.abs(returns[-14:]))
            if mean_return > 0:
                last_return = abs(returns[-1]) if len(returns) > 0 else 0
                if last_return > mean_return * 5:
                    v.has_spikes = True
                    v.warnings.append(f"Price spike detected: {last_return:.4%} vs avg {mean_return:.4%}")

        # OHLC sanity
        for i, c in enumerate(candles[-5:]):
            h, l, o, cl = c.get("high", 0), c.get("low", 0), c.get("open", 0), c.get("close", 0)
            if h < l and h > 0:
                v.errors.append(f"Invalid OHLC: high < low at index {len(candles)-5+i}")
                v.is_valid = False
            if h > 0 and (o > h * 1.001 or cl > h * 1.001):
                v.warnings.append(f"O/C outside H/L range at index {len(candles)-5+i}")

        return v

    def validate_indicators(self, indicators: dict) -> DataValidation:
        """Validate computed indicators for sanity."""
        v = DataValidation()

        rsi = indicators.get("rsi_14")
        if rsi is not None and (rsi < 0 or rsi > 100):
            v.errors.append(f"RSI out of range: {rsi}")
            v.is_valid = False

        adx = indicators.get("adx_14")
        if adx is not None and (adx < 0 or adx > 100):
            v.errors.append(f"ADX out of range: {adx}")
            v.is_valid = False

        atr = indicators.get("atr_14", 0)
        close = indicators.get("close", 0)
        if close > 0 and atr > 0:
            atr_pct = atr / close
            if atr_pct > 0.20:  # >20% of price — suspicious
                v.warnings.append(f"ATR suspiciously high: {atr_pct:.1%} of price")

        return v

    def get_source_status(self) -> dict:
        return {name: {"healthy": s.is_healthy, "failures": s.consecutive_failures,
                        "total": s.total_requests, "fail_rate": s.total_failures / max(1, s.total_requests)}
                for name, s in self._sources.items()}

    def record_source_result(self, source: str, success: bool):
        if source in self._sources:
            if success:
                self._sources[source].record_success()
            else:
                self._sources[source].record_failure()

    def get_preferred_source_order(self) -> list[str]:
        """Return sources ordered by health. Healthy sources first."""
        healthy = [s for s in self._sources.values() if s.is_healthy]
        unhealthy = [s for s in self._sources.values() if not s.is_healthy]
        # Sort healthy by recent success time (most recent first)
        healthy.sort(key=lambda s: s.last_success, reverse=True)
        return [s.name for s in healthy + unhealthy]


# Singleton
data_router = DataRouter()
