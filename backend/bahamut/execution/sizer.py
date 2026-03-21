"""
Position Sizer — size trades by risk, not notional.

position_size = risk_amount / abs(entry - stop)
risk_amount = sleeve_equity * risk_per_trade_pct
"""


def size_position(
    equity: float,
    entry_price: float,
    stop_price: float,
    risk_pct: float = 0.02,
    max_position_pct: float = 0.25,  # Max 25% of equity in one position
) -> dict:
    """
    Calculate position size based on risk.

    Returns dict with size (units), risk_amount ($), position_value ($).
    """
    if entry_price <= 0 or stop_price <= 0 or equity <= 0:
        return {"size": 0, "risk_amount": 0, "position_value": 0}

    risk_amount = equity * risk_pct
    sl_distance = abs(entry_price - stop_price)

    if sl_distance <= 0:
        return {"size": 0, "risk_amount": 0, "position_value": 0}

    # Size in asset units
    size = risk_amount / sl_distance

    # Cap at max position value
    position_value = size * entry_price
    max_value = equity * max_position_pct
    if position_value > max_value:
        size = max_value / entry_price
        position_value = max_value
        risk_amount = size * sl_distance  # Adjusted risk

    return {
        "size": round(size, 8),
        "risk_amount": round(risk_amount, 2),
        "position_value": round(position_value, 2),
    }
