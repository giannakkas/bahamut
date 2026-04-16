"""
Canonical execution result model — Phase 2 Item 4.

Purpose:
  Replace ad-hoc dict returns from _binance_open/_alpaca_open/etc. with a
  single typed record that captures full execution truth:
    - order lifecycle state (PENDING/SUBMITTED/ACCEPTED/FILLED/PARTIAL/REJECTED/ERROR)
    - fill state (submitted_qty vs accepted_qty vs filled_qty vs remaining_qty)
    - timestamps (submitted_at, accepted_at, filled_at)
    - execution costs (commission, slippage_abs, slippage_pct)
    - provenance (platform, raw_response, error)

Backward compatibility:
  ExecutionResult.as_dict() returns the legacy shape every existing caller
  expects: {platform, order_id, fill_price, fill_qty, status, error?}.
  New callers can access typed fields directly.

This is a pure data object — no behavior, no external calls.
"""
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum


class OrderLifecycle(str, Enum):
    """Canonical order lifecycle states.

    Distinction from FillState below: an order can be SUBMITTED (broker
    acknowledged receipt) without being FILLED (still working), or it can
    be REJECTED at submission.
    """
    PENDING = "PENDING"        # Built locally, not yet sent
    SUBMITTED = "SUBMITTED"    # Sent to broker, awaiting ack
    ACCEPTED = "ACCEPTED"      # Broker accepted, working
    FILLED = "FILLED"          # Fully filled
    PARTIAL = "PARTIAL"        # Partially filled, remainder cancelled or working
    REJECTED = "REJECTED"      # Broker rejected (insufficient margin, bad symbol, etc.)
    ERROR = "ERROR"            # Network/adapter error — state unknown
    INTERNAL = "INTERNAL"      # Simulated internally (no broker involvement)


class FillStatus(str, Enum):
    """Fill state — orthogonal to lifecycle."""
    UNFILLED = "UNFILLED"
    PARTIAL = "PARTIAL"
    FILLED = "FILLED"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ExecutionResult:
    """Canonical result of an open or close execution attempt.

    Every adapter (_binance_open, _alpaca_open, paper_broker, internal) must
    return one of these. Fields not applicable to a given platform are left
    at their defaults — but they exist in the shape, so downstream code can
    rely on key presence.
    """
    # ── Identity ──
    platform: str = "internal"              # "binance_futures" | "alpaca" | "internal" | "paper"
    order_id: str = ""                      # Broker-assigned ID (primary lookup key)
    client_order_id: str = ""               # Our ID we submitted (optional; for idempotency)

    # ── Intent (what we asked for) ──
    asset: str = ""
    direction: str = ""                     # "LONG" | "SHORT"
    submitted_qty: float = 0.0
    submitted_at: str = ""

    # ── Broker state ──
    lifecycle: str = OrderLifecycle.PENDING.value
    accepted_qty: float = 0.0
    accepted_at: str = ""

    # ── Fill state ──
    fill_status: str = FillStatus.UNFILLED.value
    filled_qty: float = 0.0
    remaining_qty: float = 0.0
    avg_fill_price: float = 0.0
    filled_at: str = ""

    # ── Costs ──
    commission: float = 0.0                 # Absolute fee charged (quote currency)
    commission_asset: str = ""              # Currency fee is denominated in
    slippage_abs: float = 0.0               # |avg_fill - reference_price|
    slippage_pct: float = 0.0               # slippage_abs / reference_price * 100
    reference_price: float = 0.0            # Pre-submission reference (for slippage calc)

    # ── Legacy / compatibility ──
    status: str = "unknown"                 # Legacy key — maps to lifecycle for existing callers
    error: str = ""
    raw: dict = field(default_factory=dict) # Raw broker response for debugging

    # ── Post-init provenance ──
    def __post_init__(self):
        if not self.submitted_at:
            self.submitted_at = _now_iso()
        # Keep legacy 'status' coherent with lifecycle for backward compat
        if self.status == "unknown":
            self.status = self._legacy_status()

    def _legacy_status(self) -> str:
        """Map canonical lifecycle to the legacy status strings callers read."""
        mapping = {
            OrderLifecycle.FILLED.value: "filled",
            OrderLifecycle.PARTIAL.value: "partial",
            OrderLifecycle.ACCEPTED.value: "submitted",
            OrderLifecycle.SUBMITTED.value: "submitted",
            OrderLifecycle.REJECTED.value: "error",
            OrderLifecycle.ERROR.value: "error",
            OrderLifecycle.INTERNAL.value: "internal",
            OrderLifecycle.PENDING.value: "pending",
        }
        return mapping.get(self.lifecycle, "unknown")

    def is_success(self) -> bool:
        """True if the order reached the broker and at least partially filled."""
        return self.lifecycle in (OrderLifecycle.FILLED.value,
                                  OrderLifecycle.PARTIAL.value,
                                  OrderLifecycle.ACCEPTED.value)

    def is_broker_backed(self) -> bool:
        """True if a real broker (not internal sim) handled this."""
        return self.platform in ("binance_futures", "binance", "alpaca", "paper")

    def as_dict(self) -> dict:
        """Legacy contract — existing callers read these keys:
            platform, order_id, fill_price, fill_qty, status, error
        All canonical fields are ALSO included so new callers can access them.
        """
        d = asdict(self)
        # Legacy key aliases
        d["fill_price"] = self.avg_fill_price
        d["fill_qty"] = self.filled_qty
        return d

    # ── Constructors for common outcomes ──
    @classmethod
    def from_binance_futures(cls, asset: str, direction: str,
                             submitted_qty: float, raw: dict,
                             reference_price: float = 0.0) -> "ExecutionResult":
        """Build a canonical result from Binance Futures place_market_order output."""
        if "error" in raw:
            return cls(
                platform="binance_futures", asset=asset, direction=direction,
                submitted_qty=submitted_qty,
                lifecycle=OrderLifecycle.ERROR.value,
                fill_status=FillStatus.UNFILLED.value,
                error=str(raw.get("error", ""))[:300],
                reference_price=reference_price,
                raw=raw if isinstance(raw, dict) else {},
            )

        order_id = str(raw.get("order_id", raw.get("orderId", "")))
        fill_price = float(raw.get("fill_price", raw.get("avgPrice", 0)) or 0)
        fill_qty = float(raw.get("fill_qty", raw.get("executedQty", 0)) or 0)
        binance_status = str(raw.get("status", "")).upper()

        # Map Binance status to canonical lifecycle
        if binance_status == "FILLED" and fill_qty > 0:
            lifecycle = OrderLifecycle.FILLED.value
            fill_state = FillStatus.FILLED.value
        elif binance_status == "PARTIALLY_FILLED":
            lifecycle = OrderLifecycle.PARTIAL.value
            fill_state = FillStatus.PARTIAL.value
        elif binance_status in ("NEW", "ACCEPTED"):
            lifecycle = OrderLifecycle.ACCEPTED.value
            fill_state = FillStatus.UNFILLED.value
        elif binance_status in ("REJECTED", "CANCELED", "EXPIRED"):
            lifecycle = OrderLifecycle.REJECTED.value
            fill_state = FillStatus.UNFILLED.value
        elif fill_qty > 0:
            # Unknown status but we have fills — treat as filled
            lifecycle = OrderLifecycle.FILLED.value
            fill_state = FillStatus.FILLED.value
        else:
            lifecycle = OrderLifecycle.ERROR.value
            fill_state = FillStatus.UNFILLED.value

        slippage_abs = abs(fill_price - reference_price) if (fill_price > 0 and reference_price > 0) else 0.0
        slippage_pct = (slippage_abs / reference_price * 100) if reference_price > 0 else 0.0

        now = _now_iso()
        return cls(
            platform="binance_futures",
            order_id=order_id,
            asset=asset, direction=direction,
            submitted_qty=submitted_qty,
            accepted_qty=submitted_qty if lifecycle != OrderLifecycle.REJECTED.value else 0.0,
            accepted_at=now if lifecycle != OrderLifecycle.ERROR.value else "",
            lifecycle=lifecycle, fill_status=fill_state,
            filled_qty=fill_qty,
            remaining_qty=max(0.0, submitted_qty - fill_qty),
            avg_fill_price=fill_price,
            filled_at=now if fill_state in (FillStatus.FILLED.value, FillStatus.PARTIAL.value) else "",
            reference_price=reference_price,
            slippage_abs=round(slippage_abs, 8),
            slippage_pct=round(slippage_pct, 4),
            raw=raw if isinstance(raw, dict) else {},
        )

    @classmethod
    def from_alpaca(cls, asset: str, direction: str,
                    submitted_qty: float, raw: dict,
                    reference_price: float = 0.0) -> "ExecutionResult":
        """Build a canonical result from Alpaca order output."""
        if "error" in raw:
            return cls(
                platform="alpaca", asset=asset, direction=direction,
                submitted_qty=submitted_qty,
                lifecycle=OrderLifecycle.ERROR.value,
                fill_status=FillStatus.UNFILLED.value,
                error=str(raw.get("error", ""))[:300],
                reference_price=reference_price,
                raw=raw if isinstance(raw, dict) else {},
            )

        order_id = str(raw.get("order_id", raw.get("id", "")))
        fill_price = float(raw.get("fill_price", raw.get("filled_avg_price") or 0) or 0)
        fill_qty = float(raw.get("fill_qty", raw.get("filled_qty") or 0) or 0)
        alpaca_status = str(raw.get("status", "")).lower()

        if alpaca_status == "filled" and fill_qty > 0:
            lifecycle = OrderLifecycle.FILLED.value
            fill_state = FillStatus.FILLED.value
        elif alpaca_status == "partially_filled":
            lifecycle = OrderLifecycle.PARTIAL.value
            fill_state = FillStatus.PARTIAL.value
        elif alpaca_status in ("new", "accepted", "pending_new"):
            lifecycle = OrderLifecycle.ACCEPTED.value
            fill_state = FillStatus.UNFILLED.value
        elif alpaca_status in ("rejected", "canceled", "expired", "done_for_day"):
            lifecycle = OrderLifecycle.REJECTED.value
            fill_state = FillStatus.UNFILLED.value
        elif alpaca_status == "submitted":
            lifecycle = OrderLifecycle.SUBMITTED.value
            fill_state = FillStatus.UNFILLED.value
        elif fill_qty > 0:
            lifecycle = OrderLifecycle.FILLED.value
            fill_state = FillStatus.FILLED.value
        else:
            lifecycle = OrderLifecycle.ERROR.value
            fill_state = FillStatus.UNFILLED.value

        slippage_abs = abs(fill_price - reference_price) if (fill_price > 0 and reference_price > 0) else 0.0
        slippage_pct = (slippage_abs / reference_price * 100) if reference_price > 0 else 0.0

        now = _now_iso()
        return cls(
            platform="alpaca",
            order_id=order_id,
            asset=asset, direction=direction,
            submitted_qty=submitted_qty,
            accepted_qty=submitted_qty if lifecycle != OrderLifecycle.REJECTED.value else 0.0,
            accepted_at=now if lifecycle != OrderLifecycle.ERROR.value else "",
            lifecycle=lifecycle, fill_status=fill_state,
            filled_qty=fill_qty,
            remaining_qty=max(0.0, submitted_qty - fill_qty),
            avg_fill_price=fill_price,
            filled_at=now if fill_state in (FillStatus.FILLED.value, FillStatus.PARTIAL.value) else "",
            reference_price=reference_price,
            slippage_abs=round(slippage_abs, 8),
            slippage_pct=round(slippage_pct, 4),
            raw=raw if isinstance(raw, dict) else {},
        )

    @classmethod
    def internal_sim(cls, asset: str, direction: str, qty: float,
                     reference_price: float = 0.0) -> "ExecutionResult":
        """Internal simulation — no broker, no real fills. Explicitly labeled."""
        return cls(
            platform="internal",
            asset=asset, direction=direction,
            submitted_qty=qty,
            lifecycle=OrderLifecycle.INTERNAL.value,
            fill_status=FillStatus.UNFILLED.value,
            reference_price=reference_price,
        )

    @classmethod
    def error(cls, platform: str, asset: str, direction: str,
              qty: float, message: str) -> "ExecutionResult":
        """Build a canonical error result."""
        return cls(
            platform=platform, asset=asset, direction=direction,
            submitted_qty=qty,
            lifecycle=OrderLifecycle.ERROR.value,
            fill_status=FillStatus.UNFILLED.value,
            error=str(message)[:300],
        )
