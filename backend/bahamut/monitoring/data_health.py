"""
Bahamut Data Health Module

Provides clean, operator-facing data health status:
  - LIVE_DATA_OK: All assets receiving fresh data
  - DELAYED: Data is slightly behind (< 15 min)
  - STALE: Data is old (> 15 min)
  - FALLBACK: Using synthetic/cached data

Shows per-asset last update times and whether the latest cycle
used live or fallback data.
"""
import os
import json
import structlog
from datetime import datetime, timezone

logger = structlog.get_logger()


def get_data_health() -> dict:
    """
    Get comprehensive data health status for the operator.

    Returns:
        {
            "status": "OK" | "DELAYED" | "STALE" | "FALLBACK",
            "source": "LIVE" | "SYNTHETIC",
            "assets": {
                "BTCUSD": { "last_update": "...", "age_seconds": N, "status": "OK" },
                "ETHUSD": { "last_update": "...", "age_seconds": N, "status": "OK" },
            },
            "last_cycle_source": "LIVE" | "CACHE" | "FALLBACK",
        }
    """
    result = {
        "status": "FALLBACK",
        "source": "SYNTHETIC",
        "assets": {},
        "last_cycle_source": "FALLBACK",
    }

    try:
        from bahamut.data.live_data import get_data_source, get_data_status, get_last_bar_timestamp

        # Overall source
        source = get_data_source()
        result["source"] = source

        # Per-asset status
        now = datetime.now(timezone.utc)
        data_status = get_data_status()
        worst_status = "OK"

        for asset in ["BTCUSD", "ETHUSD"]:
            asset_info = data_status.get(asset, {})
            last_bar = get_last_bar_timestamp(asset)

            age_seconds = None
            if last_bar:
                try:
                    bar_time = datetime.fromisoformat(last_bar.replace("Z", "+00:00"))
                    age_seconds = int((now - bar_time).total_seconds())
                except Exception:
                    pass

            # Determine status
            raw_status = asset_info.get("status", "UNKNOWN") if isinstance(asset_info, dict) else str(asset_info)
            if raw_status == "OK" and age_seconds is not None and age_seconds < 900:  # < 15 min
                asset_status = "OK"
            elif age_seconds is not None and age_seconds < 21600:  # < 6 hours (1.5 bars)
                asset_status = "DELAYED" if age_seconds > 900 else "OK"
            elif raw_status in ("STALE", "ERROR"):
                asset_status = "STALE"
            else:
                asset_status = "FALLBACK" if source == "SYNTHETIC" else "DELAYED"

            # Track worst
            status_order = {"OK": 0, "DELAYED": 1, "STALE": 2, "FALLBACK": 3}
            if status_order.get(asset_status, 3) > status_order.get(worst_status, 0):
                worst_status = asset_status

            result["assets"][asset] = {
                "last_update": last_bar or "never",
                "age_seconds": age_seconds,
                "status": asset_status,
                "detail": str(asset_info.get("detail", "")) if isinstance(asset_info, dict) else "",
            }

        result["status"] = worst_status
        result["last_cycle_source"] = "LIVE" if source == "LIVE" else "CACHE" if worst_status != "FALLBACK" else "FALLBACK"

    except Exception as e:
        logger.error("data_health_error", error=str(e))

    return result
