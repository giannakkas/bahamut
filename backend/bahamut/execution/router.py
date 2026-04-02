"""
Bahamut.AI — Execution Router

Routes trade execution to the correct platform:
  - Crypto → Binance Testnet (spot)
  - Stocks/ETFs → Alpaca Paper Trading
  - Forex/Commodity/Index → Internal only (no broker yet)
"""
import structlog

logger = structlog.get_logger()


def execute_open(asset: str, asset_class: str, direction: str,
                 size: float, risk_amount: float, **kwargs) -> dict:
    """Execute a position open on the appropriate platform."""
    platform = _get_platform(asset, asset_class)

    if platform == "binance":
        return _binance_open(asset, direction, size)
    elif platform == "alpaca":
        return _alpaca_open(asset, direction, size, risk_amount)
    else:
        return {"platform": "internal", "order_id": "", "fill_price": 0,
                "fill_qty": size, "status": "internal"}


def execute_close(asset: str, asset_class: str, direction: str,
                  size: float, entry_price: float, **kwargs) -> dict:
    """Execute a position close on the appropriate platform."""
    platform = _get_platform(asset, asset_class)

    if platform == "binance":
        return _binance_close(asset, direction, size)
    elif platform == "alpaca":
        return _alpaca_close(asset, direction, size)
    else:
        return {"platform": "internal", "order_id": "", "fill_price": 0,
                "fill_qty": size, "status": "internal"}


def get_execution_status() -> dict:
    """Get status of both execution platforms."""
    status = {"binance": "not_configured", "alpaca": "not_configured"}
    try:
        from bahamut.execution.binance_adapter import get_account
        from bahamut.execution.binance_adapter import _configured as b_cfg
        if b_cfg():
            acc = get_account()
            status["binance"] = "connected" if acc else "error"
    except Exception as e:
        status["binance"] = f"error: {str(e)[:50]}"
    try:
        from bahamut.execution.alpaca_adapter import get_account
        from bahamut.execution.alpaca_adapter import _configured as a_cfg
        if a_cfg():
            acc = get_account()
            if acc:
                status["alpaca"] = "connected"
                status["alpaca_cash"] = acc.get("cash", 0)
                status["alpaca_equity"] = acc.get("equity", 0)
            else:
                status["alpaca"] = "error"
    except Exception as e:
        status["alpaca"] = f"error: {str(e)[:50]}"
    return status


def _get_platform(asset: str, asset_class: str) -> str:
    if asset_class == "crypto":
        from bahamut.execution.binance_adapter import _configured
        return "binance" if _configured() else "internal"
    elif asset_class in ("stock",):
        from bahamut.execution.alpaca_adapter import _configured
        return "alpaca" if _configured() else "internal"
    else:
        return "internal"


def _binance_open(asset: str, direction: str, size: float) -> dict:
    from bahamut.execution.binance_adapter import place_market_buy, place_market_sell
    try:
        result = place_market_buy(asset, size) if direction == "LONG" else place_market_sell(asset, size)
        if result and "error" not in result:
            return {"platform": "binance", "order_id": result.get("order_id", ""),
                    "fill_price": result.get("fill_price", 0),
                    "fill_qty": result.get("fill_qty", size), "status": "filled"}
        error = result.get("error", "Unknown") if result else "No response"
        logger.error("binance_open_failed", asset=asset, error=error)
        return {"platform": "binance", "status": "error", "error": str(error)[:200],
                "order_id": "", "fill_price": 0, "fill_qty": 0}
    except Exception as e:
        return {"platform": "binance", "status": "error", "error": str(e)[:200],
                "order_id": "", "fill_price": 0, "fill_qty": 0}


def _binance_close(asset: str, direction: str, size: float) -> dict:
    from bahamut.execution.binance_adapter import place_market_buy, place_market_sell
    try:
        result = place_market_sell(asset, size) if direction == "LONG" else place_market_buy(asset, size)
        if result and "error" not in result:
            return {"platform": "binance", "order_id": result.get("order_id", ""),
                    "fill_price": result.get("fill_price", 0),
                    "fill_qty": result.get("fill_qty", size), "status": "filled"}
        error = result.get("error", "Unknown") if result else "No response"
        return {"platform": "binance", "status": "error", "error": str(error)[:200],
                "order_id": "", "fill_price": 0, "fill_qty": 0}
    except Exception as e:
        return {"platform": "binance", "status": "error", "error": str(e)[:200],
                "order_id": "", "fill_price": 0, "fill_qty": 0}


def _alpaca_open(asset: str, direction: str, size: float, risk_amount: float) -> dict:
    from bahamut.execution.alpaca_adapter import place_market_buy, place_market_sell, is_market_open
    if not is_market_open():
        logger.info("alpaca_market_closed", asset=asset, msg="Will fill at next open")
    try:
        result = place_market_buy(asset, quantity=size) if direction == "LONG" else place_market_sell(asset, quantity=size)
        if result and "error" not in result:
            return {"platform": "alpaca", "order_id": result.get("order_id", ""),
                    "fill_price": result.get("fill_price", 0),
                    "fill_qty": result.get("fill_qty", size), "status": result.get("status", "submitted")}
        error = result.get("error", "Unknown") if result else "No response"
        return {"platform": "alpaca", "status": "error", "error": str(error)[:200],
                "order_id": "", "fill_price": 0, "fill_qty": 0}
    except Exception as e:
        return {"platform": "alpaca", "status": "error", "error": str(e)[:200],
                "order_id": "", "fill_price": 0, "fill_qty": 0}


def _alpaca_close(asset: str, direction: str, size: float) -> dict:
    from bahamut.execution.alpaca_adapter import place_market_buy, place_market_sell
    try:
        result = place_market_sell(asset, size) if direction == "LONG" else place_market_buy(asset, quantity=size)
        if result and "error" not in result:
            return {"platform": "alpaca", "order_id": result.get("order_id", ""),
                    "fill_price": result.get("fill_price", 0),
                    "fill_qty": result.get("fill_qty", size), "status": result.get("status", "submitted")}
        error = result.get("error", "Unknown") if result else "No response"
        return {"platform": "alpaca", "status": "error", "error": str(error)[:200],
                "order_id": "", "fill_price": 0, "fill_qty": 0}
    except Exception as e:
        return {"platform": "alpaca", "status": "error", "error": str(e)[:200],
                "order_id": "", "fill_price": 0, "fill_qty": 0}


# ═══════════════════════════════════════════
# FastAPI Router (for /api/v1/execution endpoints)
# ═══════════════════════════════════════════
from fastapi import APIRouter
router = APIRouter()


@router.get("/status")
async def execution_status():
    """Get status of connected execution platforms (Binance/Alpaca)."""
    return get_execution_status()


@router.get("/platforms")
async def execution_platforms():
    """Show which platform each asset class routes to."""
    return {
        "crypto": "binance_testnet",
        "stock": "alpaca_paper",
        "forex": "internal",
        "commodity": "internal",
        "index": "internal",
    }
