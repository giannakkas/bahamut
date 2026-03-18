"""
Bahamut.AI Scenario-Based Portfolio Risk Engine

Simulates portfolio PnL under 5 predefined macro scenarios using linear
price shock maps. No external dependencies — pure arithmetic on positions.

For each proposed trade:
  1. Take snapshot of open positions + proposed trade
  2. Apply each scenario's shock map (% price move per asset)
  3. Compute simulated PnL for every position under every scenario
  4. Derive: worst_case_loss, portfolio_tail_risk, scenario_var

Integration:
  Portfolio engine calls evaluate_scenario_risk() between adaptive rules
  and final verdict. Result can reduce size, require approval, or block.

Shock maps are directional:
  - A LONG position loses when price drops
  - A SHORT position gains when price drops
  - shock_map[asset] = expected % move (negative = price drop)
"""
import structlog
from dataclasses import dataclass, field

logger = structlog.get_logger()

# ══════════════════════════════════════
# SHOCK MAPS: % price move per scenario
# ══════════════════════════════════════
# Positive = price goes UP, Negative = price goes DOWN
# Based on historical crisis magnitudes (simplified)

SCENARIO_SHOCKS = {
    "risk_off": {
        "description": "Flight to safety — equities and crypto sell off, "
                       "safe havens rally, USD strengthens",
        # FX: USD strengthens → pairs where USD is quote fall
        "EURUSD": -0.015, "GBPUSD": -0.020, "AUDUSD": -0.025,
        "NZDUSD": -0.025, "USDCAD": 0.015, "USDCHF": -0.010,
        "USDJPY": -0.020,  # JPY safe haven → USDJPY falls
        "EURGBP": 0.005, "EURJPY": -0.025, "GBPJPY": -0.030,
        # Crypto: sell-off
        "BTCUSD": -0.08, "ETHUSD": -0.10, "SOLUSD": -0.12,
        "BNBUSD": -0.10, "XRPUSD": -0.10, "ADAUSD": -0.12,
        "DOGEUSD": -0.15, "AVAXUSD": -0.12, "DOTUSD": -0.12,
        "LINKUSD": -0.10, "MATICUSD": -0.12,
        # Commodities: gold rallies, oil drops
        "XAUUSD": 0.03, "XAGUSD": 0.02,
        "WTIUSD": -0.06, "BCOUSD": -0.05,
        # Stocks: broad sell-off
        "AAPL": -0.04, "MSFT": -0.04, "GOOGL": -0.05,
        "AMZN": -0.05, "NVDA": -0.07, "META": -0.06,
        "TSLA": -0.08, "JPM": -0.05, "V": -0.03,
        "AMD": -0.07, "NFLX": -0.05, "CRM": -0.05,
    },

    "risk_on": {
        "description": "Risk appetite surge — equities and crypto rally, "
                       "safe havens weaken, USD weakens",
        "EURUSD": 0.012, "GBPUSD": 0.015, "AUDUSD": 0.020,
        "NZDUSD": 0.020, "USDCAD": -0.012, "USDCHF": 0.008,
        "USDJPY": 0.015, "EURGBP": -0.003, "EURJPY": 0.020,
        "GBPJPY": 0.025,
        "BTCUSD": 0.06, "ETHUSD": 0.08, "SOLUSD": 0.10,
        "BNBUSD": 0.08, "XRPUSD": 0.08, "ADAUSD": 0.10,
        "DOGEUSD": 0.12, "AVAXUSD": 0.10, "DOTUSD": 0.10,
        "LINKUSD": 0.08, "MATICUSD": 0.10,
        "XAUUSD": -0.02, "XAGUSD": -0.015,
        "WTIUSD": 0.04, "BCOUSD": 0.035,
        "AAPL": 0.03, "MSFT": 0.03, "GOOGL": 0.04,
        "AMZN": 0.04, "NVDA": 0.06, "META": 0.05,
        "TSLA": 0.07, "JPM": 0.04, "V": 0.025,
        "AMD": 0.06, "NFLX": 0.04, "CRM": 0.04,
    },

    "volatility_spike": {
        "description": "VIX spike — broad sell-off with amplified moves, "
                       "high-beta assets hit hardest",
        "EURUSD": -0.010, "GBPUSD": -0.015, "AUDUSD": -0.020,
        "NZDUSD": -0.020, "USDCAD": 0.010, "USDCHF": -0.005,
        "USDJPY": -0.015, "EURGBP": 0.005, "EURJPY": -0.020,
        "GBPJPY": -0.025,
        "BTCUSD": -0.12, "ETHUSD": -0.15, "SOLUSD": -0.18,
        "BNBUSD": -0.14, "XRPUSD": -0.14, "ADAUSD": -0.18,
        "DOGEUSD": -0.20, "AVAXUSD": -0.18, "DOTUSD": -0.18,
        "LINKUSD": -0.14, "MATICUSD": -0.18,
        "XAUUSD": 0.025, "XAGUSD": 0.015,
        "WTIUSD": -0.08, "BCOUSD": -0.07,
        "AAPL": -0.06, "MSFT": -0.05, "GOOGL": -0.07,
        "AMZN": -0.07, "NVDA": -0.10, "META": -0.08,
        "TSLA": -0.12, "JPM": -0.06, "V": -0.04,
        "AMD": -0.10, "NFLX": -0.07, "CRM": -0.07,
    },

    "usd_shock": {
        "description": "Sudden USD weakness — all USD-quoted pairs rally, "
                       "commodities rise, US stocks mixed",
        "EURUSD": 0.025, "GBPUSD": 0.030, "AUDUSD": 0.030,
        "NZDUSD": 0.030, "USDCAD": -0.025, "USDCHF": 0.020,
        "USDJPY": -0.025, "EURGBP": -0.005, "EURJPY": 0.005,
        "GBPJPY": 0.010,
        "BTCUSD": 0.05, "ETHUSD": 0.06, "SOLUSD": 0.07,
        "BNBUSD": 0.05, "XRPUSD": 0.05, "ADAUSD": 0.06,
        "DOGEUSD": 0.07, "AVAXUSD": 0.06, "DOTUSD": 0.06,
        "LINKUSD": 0.05, "MATICUSD": 0.06,
        "XAUUSD": 0.04, "XAGUSD": 0.05,
        "WTIUSD": 0.05, "BCOUSD": 0.04,
        "AAPL": -0.01, "MSFT": -0.01, "GOOGL": -0.015,
        "AMZN": -0.01, "NVDA": -0.015, "META": -0.02,
        "TSLA": -0.02, "JPM": -0.02, "V": -0.01,
        "AMD": -0.015, "NFLX": -0.01, "CRM": -0.015,
    },

    "crypto_shock": {
        "description": "Crypto-specific crash — cascading liquidations, "
                       "DeFi contagion, traditional assets mostly unaffected",
        "EURUSD": 0.0, "GBPUSD": 0.0, "AUDUSD": -0.003,
        "NZDUSD": -0.003, "USDCAD": 0.0, "USDCHF": 0.0,
        "USDJPY": -0.005, "EURGBP": 0.0, "EURJPY": -0.005,
        "GBPJPY": -0.005,
        "BTCUSD": -0.20, "ETHUSD": -0.25, "SOLUSD": -0.30,
        "BNBUSD": -0.25, "XRPUSD": -0.22, "ADAUSD": -0.28,
        "DOGEUSD": -0.35, "AVAXUSD": -0.30, "DOTUSD": -0.30,
        "LINKUSD": -0.25, "MATICUSD": -0.30,
        "XAUUSD": 0.005, "XAGUSD": 0.003,
        "WTIUSD": -0.01, "BCOUSD": -0.008,
        "AAPL": -0.005, "MSFT": -0.003, "GOOGL": -0.005,
        "AMZN": -0.005, "NVDA": -0.01, "META": -0.008,
        "TSLA": -0.015, "JPM": -0.003, "V": -0.002,
        "AMD": -0.01, "NFLX": -0.003, "CRM": -0.005,
    },
}

# Thresholds
TAIL_RISK_WARN = 0.05    # 5% of balance → size reduction
TAIL_RISK_APPROVAL = 0.08  # 8% → require approval
TAIL_RISK_BLOCK = 0.12    # 12% → block trade


@dataclass
class ScenarioResult:
    """PnL simulation result for a single scenario."""
    name: str = ""
    description: str = ""
    portfolio_pnl: float = 0.0          # simulated total portfolio PnL
    portfolio_pnl_pct: float = 0.0      # as % of balance
    proposed_trade_pnl: float = 0.0     # PnL of just the proposed trade
    position_impacts: list = field(default_factory=list)  # [{asset, pnl, shock_pct}]

    def to_dict(self):
        return {
            "name": self.name,
            "portfolio_pnl": round(self.portfolio_pnl, 2),
            "portfolio_pnl_pct": round(self.portfolio_pnl_pct, 4),
            "proposed_trade_pnl": round(self.proposed_trade_pnl, 2),
            "positions_impacted": len(self.position_impacts),
        }


@dataclass
class ScenarioRiskAssessment:
    """Aggregate result across all scenarios."""
    worst_case_loss: float = 0.0        # worst portfolio PnL across scenarios
    worst_case_pct: float = 0.0         # as % of balance
    worst_scenario: str = ""            # which scenario is worst
    portfolio_tail_risk: float = 0.0    # avg of 2 worst scenarios as % of balance
    scenario_var: float = 0.0           # variance of PnL across scenarios
    all_scenarios: list = field(default_factory=list)
    proposed_worst_contribution: float = 0.0  # how much does proposed trade add to worst case
    risk_level: str = "OK"              # OK, WARN, APPROVAL, BLOCK

    def to_dict(self):
        return {
            "worst_case_loss": round(self.worst_case_loss, 2),
            "worst_case_pct": round(self.worst_case_pct, 4),
            "worst_scenario": self.worst_scenario,
            "portfolio_tail_risk": round(self.portfolio_tail_risk, 4),
            "scenario_var": round(self.scenario_var, 4),
            "proposed_worst_contribution": round(self.proposed_worst_contribution, 2),
            "risk_level": self.risk_level,
            "scenarios": [s.to_dict() for s in self.all_scenarios],
        }


def evaluate_scenario_risk(
    positions: list,
    proposed_asset: str,
    proposed_direction: str,
    proposed_value: float,
    proposed_entry_price: float,
    balance: float,
) -> ScenarioRiskAssessment:
    """
    Run all scenarios against current portfolio + proposed trade.
    Returns tail risk assessment.

    positions: list of OpenPosition from registry
    """
    assessment = ScenarioRiskAssessment()
    if balance <= 0:
        balance = 100000.0

    scenario_pnls = []

    for scenario_name, shock_map in SCENARIO_SHOCKS.items():
        result = ScenarioResult(
            name=scenario_name,
            description=SCENARIO_SHOCKS[scenario_name].get("description", ""),
        )

        total_pnl = 0.0

        # Simulate existing positions
        for pos in positions:
            shock_pct = shock_map.get(pos.asset, 0.0)
            pnl = _simulate_position_pnl(
                pos.direction, pos.position_value, pos.current_price, shock_pct)
            total_pnl += pnl
            result.position_impacts.append({
                "asset": pos.asset, "direction": pos.direction,
                "pnl": round(pnl, 2), "shock_pct": shock_pct,
            })

        # Simulate proposed trade
        proposed_shock = shock_map.get(proposed_asset, 0.0)
        proposed_pnl = _simulate_position_pnl(
            proposed_direction, proposed_value, proposed_entry_price, proposed_shock)
        total_pnl += proposed_pnl
        result.proposed_trade_pnl = proposed_pnl
        result.portfolio_pnl = total_pnl
        result.portfolio_pnl_pct = total_pnl / balance

        assessment.all_scenarios.append(result)
        scenario_pnls.append((scenario_name, total_pnl, proposed_pnl))

    # Derive aggregate metrics
    if scenario_pnls:
        # Sort by PnL ascending (worst first)
        scenario_pnls.sort(key=lambda x: x[1])

        worst = scenario_pnls[0]
        assessment.worst_case_loss = worst[1]
        assessment.worst_case_pct = worst[1] / balance
        assessment.worst_scenario = worst[0]
        assessment.proposed_worst_contribution = worst[2]

        # Tail risk: average of 2 worst scenarios
        tail_pnls = [s[1] for s in scenario_pnls[:2]]
        assessment.portfolio_tail_risk = abs(sum(tail_pnls) / len(tail_pnls) / balance)

        # Variance
        mean_pnl = sum(s[1] for s in scenario_pnls) / len(scenario_pnls)
        assessment.scenario_var = sum((s[1] - mean_pnl) ** 2
                                       for s in scenario_pnls) / len(scenario_pnls)

    # Risk level
    tr = assessment.portfolio_tail_risk
    if tr >= TAIL_RISK_BLOCK:
        assessment.risk_level = "BLOCK"
    elif tr >= TAIL_RISK_APPROVAL:
        assessment.risk_level = "APPROVAL"
    elif tr >= TAIL_RISK_WARN:
        assessment.risk_level = "WARN"
    else:
        assessment.risk_level = "OK"

    logger.info("scenario_risk_assessed",
                 worst=assessment.worst_scenario,
                 tail_risk=round(tr, 4),
                 risk_level=assessment.risk_level,
                 proposed=proposed_asset)

    return assessment


def _simulate_position_pnl(
    direction: str,
    position_value: float,
    current_price: float,
    shock_pct: float,
) -> float:
    """
    Linear PnL approximation: price moves by shock_pct.
    LONG: profit when price goes up, loss when down.
    SHORT: profit when price goes down, loss when up.
    """
    if current_price <= 0 or position_value <= 0:
        return 0.0

    # Quantity implied by position value and current price
    implied_qty = position_value / current_price
    price_change = current_price * shock_pct

    if direction == "LONG":
        return implied_qty * price_change
    else:  # SHORT
        return implied_qty * (-price_change)


def get_scenario_list() -> list[dict]:
    """List available scenarios for API/UI."""
    return [
        {"name": name, "description": shocks.get("description", ""),
         "assets_affected": len([k for k in shocks if k != "description"])}
        for name, shocks in SCENARIO_SHOCKS.items()
    ]


def simulate_portfolio_standalone(scenario_name: str = None) -> list[dict]:
    """
    Simulate current portfolio under scenarios (without a proposed trade).
    Used for UI dashboard.
    """
    from bahamut.portfolio.registry import load_portfolio_snapshot

    snap = load_portfolio_snapshot()
    bal = snap.balance if snap.balance > 0 else 100000.0
    results = []

    scenarios = {scenario_name: SCENARIO_SHOCKS[scenario_name]} \
        if scenario_name and scenario_name in SCENARIO_SHOCKS \
        else SCENARIO_SHOCKS

    for name, shock_map in scenarios.items():
        total_pnl = 0.0
        impacts = []
        for pos in snap.positions:
            shock = shock_map.get(pos.asset, 0.0)
            pnl = _simulate_position_pnl(pos.direction, pos.position_value,
                                          pos.current_price, shock)
            total_pnl += pnl
            if abs(pnl) > 0.01:
                impacts.append({"asset": pos.asset, "direction": pos.direction,
                                "pnl": round(pnl, 2), "shock": shock})
        results.append({
            "scenario": name,
            "portfolio_pnl": round(total_pnl, 2),
            "portfolio_pnl_pct": round(total_pnl / bal, 4),
            "impacts": impacts,
        })

    return results
