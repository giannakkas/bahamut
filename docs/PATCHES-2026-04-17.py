# Bahamut.AI — Concrete Code Patches
# Apply these in order of priority

# ═══════════════════════════════════════════════════════════════
# PATCH 1: Add Commission/Fee Model to Paper Broker (CRITICAL)
# File: backend/bahamut/execution/paper_broker.py
# ═══════════════════════════════════════════════════════════════

# In BrokerConfig, add:
#   commission_rate: float = 0.0004  # Binance taker: 0.04% per side (0.08% round-trip)
#
# In _close(), change PnL calculation to:

"""
--- a/backend/bahamut/execution/paper_broker.py
+++ b/backend/bahamut/execution/paper_broker.py
@@ dataclass
 class BrokerConfig:
     slippage_bps: float = 8.0
     spread_bps: float = 12.0
+    commission_rate: float = 0.0004  # 0.04% per side (Binance taker)
     mode: str = "paper"

@@ _close
     def _close(self, pos, exit_price, reason):
         reason_str = reason.value if hasattr(reason, 'value') else str(reason)
+        # Commission: charged on both entry and exit notional
+        entry_notional = pos.entry_price * pos.size
+        exit_notional = exit_price * pos.size
+        commission = (entry_notional + exit_notional) * self.config.commission_rate
+
         if pos.direction == "LONG":
-            pnl = (exit_price - pos.entry_price) * pos.size
+            pnl = (exit_price - pos.entry_price) * pos.size - commission
             pnl_pct = (exit_price - pos.entry_price) / pos.entry_price
         else:
-            pnl = (pos.entry_price - exit_price) * pos.size
+            pnl = (pos.entry_price - exit_price) * pos.size - commission
             pnl_pct = (pos.entry_price - exit_price) / pos.entry_price
+        # Adjust pnl_pct to include commission impact
+        pnl_pct = pnl / (pos.entry_price * pos.size) if pos.size > 0 else 0
"""


# ═══════════════════════════════════════════════════════════════
# PATCH 2: Fix Kill Switch to Use Per-Asset Prices (CRITICAL)
# File: backend/bahamut/execution/engine.py
# ═══════════════════════════════════════════════════════════════

"""
--- a/backend/bahamut/execution/engine.py
+++ b/backend/bahamut/execution/engine.py
@@ activate_kill_switch
-    def activate_kill_switch(self, price: float):
-        \"\"\"Close all positions and block new trades.\"\"\"
+    def activate_kill_switch(self, price: float = 0.0):
+        \"\"\"Close all positions and block new trades.
+        
+        If price=0 (default), fetches current price per asset.
+        If price>0, uses that price for all (legacy/fallback).
+        \"\"\"
         with self._lock:
             self._kill_switch = True
             closed_count = 0
             for pos in list(self.open_positions):
-                trade = self.broker.force_close(pos, price, "KILL_SWITCH")
+                close_price = price
+                if close_price <= 0:
+                    close_price = self._get_asset_price(pos.asset)
+                if close_price <= 0:
+                    close_price = pos.current_price  # last known price
+                trade = self.broker.force_close(pos, close_price, "KILL_SWITCH")
                 self.closed_trades.append(trade)
                 self.open_positions.remove(pos)
                 closed_count += 1

+    @staticmethod
+    def _get_asset_price(asset: str) -> float:
+        \"\"\"Fetch current price for an asset (best effort).\"\"\"
+        try:
+            from bahamut.data.binance_data import is_crypto, get_price
+            if is_crypto(asset):
+                return get_price(asset)
+        except Exception:
+            pass
+        try:
+            from bahamut.data.live_data import fetch_candles
+            candles = fetch_candles(asset, count=5)
+            if candles:
+                return candles[-1]["close"]
+        except Exception:
+            pass
+        return 0.0
"""


# ═══════════════════════════════════════════════════════════════
# PATCH 3: Fix ADX to True Wilder-Smoothed Average (HIGH)
# File: backend/bahamut/features/indicators.py
# ═══════════════════════════════════════════════════════════════

"""
Replace the entire _adx() function with:
"""

def _adx_fixed(highs, lows, closes, period=14):
    """Average Directional Index — TRUE Wilder-smoothed ADX.
    
    Computes +DM/-DM → smooth → +DI/-DI → DX → smooth DX → ADX.
    Previous implementation returned a single unsmoothed DX value.
    """
    import numpy as np
    
    n = len(closes)
    if n < period * 2 + 1:
        return 20.0  # default weak trend

    # Step 1: +DM and -DM
    plus_dm = np.zeros(n)
    minus_dm = np.zeros(n)
    for i in range(1, n):
        up = highs[i] - highs[i - 1]
        down = lows[i - 1] - lows[i]
        plus_dm[i] = up if (up > down and up > 0) else 0
        minus_dm[i] = down if (down > up and down > 0) else 0

    # Step 2: True Range
    tr = np.maximum(
        highs[1:] - lows[1:],
        np.maximum(
            np.abs(highs[1:] - closes[:-1]),
            np.abs(lows[1:] - closes[:-1])
        )
    )

    # Step 3: Wilder-smooth TR, +DM, -DM (first value = sum of first `period`)
    atr_s = float(np.sum(tr[:period]))
    pdm_s = float(np.sum(plus_dm[1:period + 1]))
    mdm_s = float(np.sum(minus_dm[1:period + 1]))

    # Build DX series for smoothing
    dx_values = []

    for i in range(period, len(tr)):
        # Wilder smoothing: prev - (prev/period) + current
        atr_s = atr_s - (atr_s / period) + tr[i]
        pdm_s = pdm_s - (pdm_s / period) + plus_dm[i + 1]
        mdm_s = mdm_s - (mdm_s / period) + minus_dm[i + 1]

        if atr_s == 0:
            dx_values.append(0.0)
            continue

        plus_di = 100 * pdm_s / atr_s
        minus_di = 100 * mdm_s / atr_s
        di_sum = plus_di + minus_di

        if di_sum == 0:
            dx_values.append(0.0)
        else:
            dx_values.append(100 * abs(plus_di - minus_di) / di_sum)

    if len(dx_values) < period:
        return round(dx_values[-1], 4) if dx_values else 20.0

    # Step 4: Wilder-smooth the DX series to get ADX
    adx = float(np.mean(dx_values[:period]))  # First ADX = mean of first `period` DX values
    for i in range(period, len(dx_values)):
        adx = (adx * (period - 1) + dx_values[i]) / period

    return round(adx, 4)


# ═══════════════════════════════════════════════════════════════
# PATCH 4: Increase Crypto Candle Count (HIGH — 1 line)
# File: backend/bahamut/training/orchestrator.py
# ═══════════════════════════════════════════════════════════════

"""
--- a/backend/bahamut/training/orchestrator.py
+++ b/backend/bahamut/training/orchestrator.py
-CRYPTO_CANDLE_COUNT = 200  # 200 × 15m = ~50 hours of data
+CRYPTO_CANDLE_COUNT = 300  # 300 × 15m = ~75 hours of data (ensures EMA-200 is fully seeded)
"""


# ═══════════════════════════════════════════════════════════════
# PATCH 5: Fix Realized Volatility Annualization (MEDIUM)
# File: backend/bahamut/features/indicators.py
# ═══════════════════════════════════════════════════════════════

"""
Change compute_indicators() to accept interval parameter and fix annualization:

Add parameter: def compute_indicators(candles: list[dict], interval: str = "4h") -> dict:

Then replace the realized volatility block:
"""

# Annualization factors: periods per year
_ANNUAL_FACTORS = {
    "1m":  365 * 24 * 60,       # 525,600
    "5m":  365 * 24 * 12,       # 105,120
    "15m": 365 * 24 * 4,        #  35,040
    "30m": 365 * 24 * 2,        #  17,520
    "1h":  365 * 24,            #   8,760
    "4h":  365 * 6,             #   2,190
    "1d":  252,                 #     252 (equity convention)
}

# In compute_indicators, replace:
#   result["realized_vol_20"] = float(np.std(returns) * np.sqrt(252))
# With:
#   ann_factor = _ANNUAL_FACTORS.get(interval, 252)
#   result["realized_vol_20"] = float(np.std(returns) * np.sqrt(ann_factor))


# ═══════════════════════════════════════════════════════════════
# PATCH 6: Fix Bollinger Bands to Sample Std (LOW)
# File: backend/bahamut/features/indicators.py
# ═══════════════════════════════════════════════════════════════

"""
--- a/backend/bahamut/features/indicators.py
+++ b/backend/bahamut/features/indicators.py
@@ _bollinger
-    std = float(np.std(closes[-period:]))
+    std = float(np.std(closes[-period:], ddof=1))
"""


# ═══════════════════════════════════════════════════════════════
# PATCH 7: Add EMA-200 Degradation Warning (LOW — quick win)
# File: backend/bahamut/features/indicators.py
# ═══════════════════════════════════════════════════════════════

"""
--- a/backend/bahamut/features/indicators.py
+++ b/backend/bahamut/features/indicators.py
@@ EMAs
     if len(closes) >= 200:
         result["ema_200"] = _ema(closes, 200)
+        result["_ema200_degraded"] = False
     else:
         result["ema_200"] = _ema(closes, len(closes) - 1) if len(closes) > 1 else closes[-1]
+        result["_ema200_degraded"] = True
+        logger.warning("ema200_degraded", candles=len(closes),
+                       effective_period=len(closes)-1,
+                       msg="EMA-200 using shorter period — values are unreliable")
"""


# ═══════════════════════════════════════════════════════════════
# PATCH 8: Add v5_tuned Missing Filters (MEDIUM — quick win)
# File: backend/bahamut/strategies/v5_tuned.py
# ═══════════════════════════════════════════════════════════════

"""
v5_tuned copies v5_base's signal logic but is missing:
- ATR minimum volatility filter
- ADX trend strength filter  
- EMA gap filter
- Suppress check

Add these before the golden cross check, matching v5_base's implementation.
"""


# ═══════════════════════════════════════════════════════════════
# PATCH 9: Persist bars_held in Training Engine (HIGH)
# File: backend/bahamut/training/engine.py
# ═══════════════════════════════════════════════════════════════

"""
In the position update function (update_positions_for_asset), bars_held is
incremented in Redis. On DB load, bars_held should be computed from:
  bars_held = (now - entry_time) / interval_seconds

Or better: persist bars_held to the training_positions table and load it
on startup reconciliation.

Add column:
  ALTER TABLE training_positions ADD COLUMN IF NOT EXISTS bars_held INT DEFAULT 0;

Update on every bar update cycle, and load during _load_positions_from_db().
"""


# ═══════════════════════════════════════════════════════════════
# PATCH 10: Gap Detection for Candle Data (MEDIUM)
# File: backend/bahamut/data/binance_data.py
# ═══════════════════════════════════════════════════════════════

def validate_candle_continuity(candles: list, interval: str = "15m") -> tuple:
    """Check that candles are contiguous (no gaps).
    
    Returns (is_valid, gap_count, gap_details).
    """
    if not candles or len(candles) < 2:
        return True, 0, []

    expected_ms = {
        "1m": 60000, "5m": 300000, "15m": 900000, "30m": 1800000,
        "1h": 3600000, "4h": 14400000, "1d": 86400000,
    }.get(interval, 900000)

    gaps = []
    for i in range(1, len(candles)):
        ot_curr = candles[i].get("open_time", 0)
        ot_prev = candles[i-1].get("open_time", 0)
        if ot_curr and ot_prev:
            diff = ot_curr - ot_prev
            if diff != expected_ms:
                gaps.append({
                    "index": i,
                    "expected_ms": expected_ms,
                    "actual_ms": diff,
                    "missing_bars": (diff // expected_ms) - 1,
                })

    return len(gaps) == 0, len(gaps), gaps
