"""
Bahamut.AI Marginal Risk Contribution Engine

For every proposed trade, computes:
  existing_stress: portfolio PnL under each scenario WITHOUT the trade
  combined_stress: portfolio PnL under each scenario WITH the trade
  marginal_risk = combined_loss - existing_loss (per scenario + aggregate)

This answers: "How much worse does the portfolio get if we add this trade?"

A trade that hedges existing risk can have NEGATIVE marginal risk (improves portfolio).
"""
import structlog
from dataclasses import dataclass, field
from bahamut.admin.config import get_config

logger = structlog.get_logger()


@dataclass
class MarginalRiskResult:
    """Marginal risk contribution of a proposed trade."""
    marginal_by_scenario: dict = field(default_factory=dict)  # {scenario: marginal_pnl}
    worst_case_marginal: float = 0.0    # single worst marginal contribution
    worst_marginal_scenario: str = ""
    weighted_marginal: float = 0.0       # probability-weighted marginal
    existing_tail_risk: float = 0.0      # tail risk WITHOUT trade
    combined_tail_risk: float = 0.0      # tail risk WITH trade
    marginal_tail_risk: float = 0.0      # difference
    is_hedging: bool = False             # does trade reduce risk?
    risk_level: str = "OK"               # OK / WARN / APPROVAL / BLOCK

    def to_dict(self):
        return {
            "marginal_by_scenario": {k: round(v, 2) for k, v in self.marginal_by_scenario.items()},
            "worst_case_marginal": round(self.worst_case_marginal, 2),
            "worst_marginal_scenario": self.worst_marginal_scenario,
            "weighted_marginal": round(self.weighted_marginal, 2),
            "existing_tail_risk": round(self.existing_tail_risk, 4),
            "combined_tail_risk": round(self.combined_tail_risk, 4),
            "marginal_tail_risk": round(self.marginal_tail_risk, 4),
            "is_hedging": self.is_hedging,
            "risk_level": self.risk_level,
        }


def compute_marginal_risk(
    positions: list,
    proposed_asset: str,
    proposed_direction: str,
    proposed_value: float,
    balance: float,
) -> MarginalRiskResult:
    """
    Compute marginal risk by running scenarios twice:
      1. Existing portfolio only
      2. Existing portfolio + proposed trade
    Then: marginal = combined - existing (per scenario)
    """
    from bahamut.portfolio.scenarios import SCENARIO_SHOCKS, _simulate_position_pnl

    result = MarginalRiskResult()
    if balance <= 0:
        balance = 100000.0

    # Get scenario weights from central config
    scenario_weights = _get_scenario_weights()

    existing_pnls = {}
    combined_pnls = {}

    for scenario_name, shock_map in SCENARIO_SHOCKS.items():
        if scenario_name == "description":
            continue

        # Existing portfolio PnL
        existing_pnl = sum(
            _simulate_position_pnl(p.direction, p.position_value, p.current_price,
                                    shock_map.get(p.asset, 0.0))
            for p in positions
        )

        # Proposed trade PnL
        proposed_shock = shock_map.get(proposed_asset, 0.0)
        proposed_pnl = _simulate_position_pnl(
            proposed_direction, proposed_value, 1.0, proposed_shock)

        combined_pnl = existing_pnl + proposed_pnl
        marginal = combined_pnl - existing_pnl  # = proposed_pnl, but kept explicit

        existing_pnls[scenario_name] = existing_pnl
        combined_pnls[scenario_name] = combined_pnl
        result.marginal_by_scenario[scenario_name] = marginal

    # Worst case marginal
    if result.marginal_by_scenario:
        worst_scenario = min(result.marginal_by_scenario, key=result.marginal_by_scenario.get)
        result.worst_case_marginal = result.marginal_by_scenario[worst_scenario]
        result.worst_marginal_scenario = worst_scenario

    # Weighted marginal risk
    weighted_sum = 0.0
    weight_total = 0.0
    for name, marginal in result.marginal_by_scenario.items():
        w = scenario_weights.get(name, 0.1)
        weighted_sum += marginal * w
        weight_total += w
    if weight_total > 0:
        result.weighted_marginal = weighted_sum / weight_total

    # Tail risk comparison (avg of 2 worst, as % of balance)
    existing_sorted = sorted(existing_pnls.values())
    combined_sorted = sorted(combined_pnls.values())

    if len(existing_sorted) >= 2:
        result.existing_tail_risk = abs(sum(existing_sorted[:2]) / 2 / balance)
    if len(combined_sorted) >= 2:
        result.combined_tail_risk = abs(sum(combined_sorted[:2]) / 2 / balance)

    result.marginal_tail_risk = result.combined_tail_risk - result.existing_tail_risk
    result.is_hedging = result.marginal_tail_risk < -0.001  # trade reduces tail risk

    # Risk level from central config
    warn_threshold = get_config("marginal_risk.warn", 0.02)
    approval_threshold = get_config("marginal_risk.approval", 0.04)
    block_threshold = get_config("marginal_risk.block", 0.06)

    abs_marginal_pct = abs(result.worst_case_marginal) / balance
    if abs_marginal_pct >= block_threshold and not result.is_hedging:
        result.risk_level = "BLOCK"
    elif abs_marginal_pct >= approval_threshold and not result.is_hedging:
        result.risk_level = "APPROVAL"
    elif abs_marginal_pct >= warn_threshold and not result.is_hedging:
        result.risk_level = "WARN"
    else:
        result.risk_level = "OK"

    logger.info("marginal_risk_computed",
                 proposed=proposed_asset, weighted=round(result.weighted_marginal, 2),
                 worst=round(result.worst_case_marginal, 2),
                 hedging=result.is_hedging, level=result.risk_level)

    return result


def _get_scenario_weights() -> dict:
    """Load scenario weights from central config."""
    return {
        "risk_off": get_config("scenario.weight.risk_off", 0.30),
        "risk_on": get_config("scenario.weight.risk_on", 0.10),
        "volatility_spike": get_config("scenario.weight.volatility_spike", 0.25),
        "usd_shock": get_config("scenario.weight.usd_shock", 0.15),
        "crypto_shock": get_config("scenario.weight.crypto_shock", 0.20),
    }
