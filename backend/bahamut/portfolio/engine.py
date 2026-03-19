"""
Bahamut.AI Portfolio Intelligence Engine

Evaluates whether a proposed trade is good for the PORTFOLIO, not just good in isolation.
Sits between Risk (absolute authority) and Execution Policy (final gate).

Produces a PortfolioVerdict that can:
  - Reduce position size (soft constraint)
  - Require approval (moderate concern)
  - Block the trade (hard constraint — portfolio-level)
  - Pass through unchanged (trade improves portfolio)

5 sub-engines:
  1. Exposure Engine: gross/net exposure, per-class limits
  2. Correlation Engine: directional + asset class overlap
  3. Theme Mapper: thematic concentration risk
  4. Fragility Scorer: how fragile is the portfolio to shocks?
  5. Impact Scorer: does this trade IMPROVE or WORSEN the portfolio?
"""
import structlog
from dataclasses import dataclass, field
from bahamut.portfolio.registry import (
    PortfolioSnapshot, OpenPosition, ASSET_CLASS_MAP, THEME_MAP,
)

logger = structlog.get_logger()

# ── Limits ──
EXPOSURE_LIMITS = {
    "gross_max": 0.80,         # total position value / balance
    "net_max": 0.50,           # |long - short| / balance
    "single_class_max": 0.40,  # any one asset class / balance
    "single_theme_max": 0.30,  # any one theme / balance
    "single_asset_max": 0.15,  # single asset / balance
}


@dataclass
class ExposureMetrics:
    gross: float = 0.0         # total position value / balance
    net: float = 0.0           # (long - short) / balance
    long_pct: float = 0.0
    short_pct: float = 0.0
    by_class: dict = field(default_factory=dict)   # {class: pct}
    by_theme: dict = field(default_factory=dict)    # {theme: pct}
    by_asset: dict = field(default_factory=dict)    # {asset: pct}
    after_trade_gross: float = 0.0
    after_trade_net: float = 0.0

    def to_dict(self):
        return {
            "gross": round(self.gross, 4), "net": round(self.net, 4),
            "long_pct": round(self.long_pct, 4), "short_pct": round(self.short_pct, 4),
            "by_class": {k: round(v, 4) for k, v in self.by_class.items()},
            "by_theme": {k: round(v, 4) for k, v in self.by_theme.items()},
            "after_trade_gross": round(self.after_trade_gross, 4),
            "after_trade_net": round(self.after_trade_net, 4),
        }


@dataclass
class CorrelationMetrics:
    directional_overlap: float = 0.0    # how many positions share same direction?
    class_concentration: float = 0.0     # HHI of asset class distribution
    theme_overlap_count: int = 0         # themes shared with proposed trade
    same_class_count: int = 0            # positions in same class as proposed
    same_direction_same_class: int = 0   # worst case: same class, same direction

    def to_dict(self):
        return {
            "directional_overlap": round(self.directional_overlap, 3),
            "class_concentration": round(self.class_concentration, 3),
            "theme_overlap_count": self.theme_overlap_count,
            "same_class_count": self.same_class_count,
            "same_direction_same_class": self.same_direction_same_class,
        }


@dataclass
class FragilityMetrics:
    portfolio_fragility: float = 0.0  # 0 (robust) to 1 (fragile)
    concentration_risk: float = 0.0
    directional_risk: float = 0.0
    drawdown_proximity: float = 0.0
    avg_position_quality: float = 0.0  # avg consensus score of open positions

    def to_dict(self):
        return {k: round(v, 3) for k, v in {
            "portfolio_fragility": self.portfolio_fragility,
            "concentration_risk": self.concentration_risk,
            "directional_risk": self.directional_risk,
            "drawdown_proximity": self.drawdown_proximity,
            "avg_position_quality": self.avg_position_quality,
        }.items()}


@dataclass
class PortfolioVerdict:
    allowed: bool = True
    size_multiplier: float = 1.0
    requires_approval: bool = False
    reasons: list = field(default_factory=list)
    blockers: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    improves_portfolio: bool = False
    exposure: ExposureMetrics = field(default_factory=ExposureMetrics)
    correlation: CorrelationMetrics = field(default_factory=CorrelationMetrics)
    fragility: FragilityMetrics = field(default_factory=FragilityMetrics)
    impact_score: float = 0.0  # -1 (worsens) to +1 (improves)
    scenario_risk: dict = field(default_factory=dict)  # scenario risk assessment
    marginal_risk: dict = field(default_factory=dict)
    quality_ratio: dict = field(default_factory=dict)
    kill_switch_state: dict = field(default_factory=dict)

    def to_dict(self):
        return {
            "allowed": self.allowed, "size_multiplier": round(self.size_multiplier, 3),
            "requires_approval": self.requires_approval,
            "reasons": self.reasons, "blockers": self.blockers, "warnings": self.warnings,
            "improves_portfolio": self.improves_portfolio,
            "impact_score": round(self.impact_score, 3),
            "exposure": self.exposure.to_dict(),
            "correlation": self.correlation.to_dict(),
            "fragility": self.fragility.to_dict(),
            "scenario_risk": self.scenario_risk,
            "marginal_risk": self.marginal_risk,
            "quality_ratio": self.quality_ratio,
            "kill_switch_state": self.kill_switch_state,
        }


def evaluate_trade_for_portfolio(
    snapshot: PortfolioSnapshot,
    proposed_asset: str,
    proposed_direction: str,
    proposed_value: float,
    proposed_risk: float,
    consensus_score: float = 0.5,
    signal_label: str = "SIGNAL",
    atr: float = 0.0,
    entry_price: float = 0.0,
) -> PortfolioVerdict:
    """
    Main entry point. Evaluates a proposed trade against current portfolio state.
    Returns a PortfolioVerdict that can modify, approve, or block.
    """
    verdict = PortfolioVerdict()
    bal = snapshot.balance if snapshot.balance > 0 else 100000.0
    proposed_class = ASSET_CLASS_MAP.get(proposed_asset, "other")
    proposed_themes = [t for t, assets in THEME_MAP.items() if proposed_asset in assets]

    # ═══════════════════════════════════
    # 0. KILL SWITCH CHECK (before everything else)
    # ═══════════════════════════════════
    try:
        from bahamut.portfolio.kill_switch import evaluate_kill_switch
        from bahamut.portfolio.scenarios import evaluate_scenario_risk as _qs_eval
        qs = _qs_eval(snapshot.positions, proposed_asset, proposed_direction,
                       0, 1.0, bal)  # quick assessment for tail risk
        frag = _compute_fragility(snapshot, bal)
        ks_state = evaluate_kill_switch(
            weighted_tail_risk=qs.weighted_tail_risk,
            portfolio_fragility=frag.portfolio_fragility,
            concentration_risk=frag.concentration_risk,
            drawdown_proximity=frag.drawdown_proximity,
            position_count=snapshot.position_count,
        )
        verdict.kill_switch_state = ks_state.to_dict()
        if ks_state.kill_switch_active:
            verdict.blockers.append(
                f"KILL_SWITCH: {'; '.join(ks_state.triggers[:2])}")
            verdict.allowed = False
            verdict.size_multiplier = 0.0
            return verdict
        if ks_state.safe_mode_active:
            verdict.warnings.append(f"SAFE_MODE: {'; '.join(ks_state.triggers[:1])}")
            verdict.requires_approval = True
    except Exception as e:
        # SAFETY: Kill switch failure = assume unsafe, block trade
        logger.error("kill_switch_evaluation_failed", error=str(e), asset=proposed_asset)
        from bahamut.shared.degraded import mark_degraded
        mark_degraded("portfolio.kill_switch", str(e))
        verdict.blockers.append("KILL_SWITCH_UNAVAILABLE: defaulting to BLOCK for safety")
        verdict.allowed = False
        verdict.size_multiplier = 0.0
        verdict.warnings.append(f"Kill switch subsystem error: {str(e)[:100]}")
        return verdict

    # ═══════════════════════════════════
    # 1. EXPOSURE ENGINE
    # ═══════════════════════════════════
    exp = _compute_exposure(snapshot, proposed_asset, proposed_direction, proposed_value, bal)
    verdict.exposure = exp

    # Hard block: gross exposure would exceed limit
    if exp.after_trade_gross > EXPOSURE_LIMITS["gross_max"]:
        verdict.blockers.append(
            f"GROSS_EXPOSURE: {exp.after_trade_gross:.1%} > {EXPOSURE_LIMITS['gross_max']:.0%}")

    # Hard block: net directional exposure too high
    if abs(exp.after_trade_net) > EXPOSURE_LIMITS["net_max"]:
        verdict.blockers.append(
            f"NET_EXPOSURE: {abs(exp.after_trade_net):.1%} > {EXPOSURE_LIMITS['net_max']:.0%}")

    # Single class limit
    class_exp = exp.by_class.get(proposed_class, 0) + (proposed_value / bal)
    if class_exp > EXPOSURE_LIMITS["single_class_max"]:
        verdict.warnings.append(
            f"CLASS_CONCENTRATION: {proposed_class} would be {class_exp:.1%} > {EXPOSURE_LIMITS['single_class_max']:.0%}")
        verdict.size_multiplier *= 0.6

    # Single theme limit
    for theme in proposed_themes:
        theme_exp = exp.by_theme.get(theme, 0) + (proposed_value / bal)
        if theme_exp > EXPOSURE_LIMITS["single_theme_max"]:
            verdict.warnings.append(
                f"THEME_CONCENTRATION: '{theme}' would be {theme_exp:.1%} > {EXPOSURE_LIMITS['single_theme_max']:.0%}")
            verdict.size_multiplier *= 0.7
            break  # one theme warning is enough

    # ═══════════════════════════════════
    # 2. CORRELATION ENGINE
    # ═══════════════════════════════════
    corr = _compute_correlation(snapshot, proposed_asset, proposed_direction, proposed_class, proposed_themes)
    verdict.correlation = corr

    if corr.same_direction_same_class >= 2:
        verdict.warnings.append(
            f"CORRELATED_TRADES: {corr.same_direction_same_class} existing {proposed_direction} positions in {proposed_class}")
        verdict.size_multiplier *= 0.5

    if corr.class_concentration > 0.5:  # HHI > 0.5 = highly concentrated
        verdict.warnings.append(
            f"PORTFOLIO_CONCENTRATED: HHI={corr.class_concentration:.2f}")
        verdict.size_multiplier *= 0.8

    if corr.theme_overlap_count >= 3:
        verdict.warnings.append(
            f"THEME_OVERLAP: {corr.theme_overlap_count} themes shared with existing positions")
        verdict.size_multiplier *= 0.8

    # ═══════════════════════════════════
    # 3. FRAGILITY SCORING
    # ═══════════════════════════════════
    frag = _compute_fragility(snapshot, bal)
    verdict.fragility = frag

    if frag.portfolio_fragility > 0.7:
        verdict.warnings.append(
            f"HIGH_FRAGILITY: {frag.portfolio_fragility:.2f} — portfolio is vulnerable")
        verdict.requires_approval = True
        verdict.size_multiplier *= 0.5

    # ═══════════════════════════════════
    # 4. IMPACT SCORING
    # ═══════════════════════════════════
    impact = _compute_impact(snapshot, proposed_direction, proposed_class,
                              proposed_themes, consensus_score, corr, exp, bal)
    verdict.impact_score = impact
    verdict.improves_portfolio = impact > 0.1

    if impact > 0.3:
        verdict.reasons.append(f"IMPROVES_PORTFOLIO: impact={impact:.2f}")
        # Good trade for portfolio: slight size bonus
        verdict.size_multiplier = min(1.0, verdict.size_multiplier * 1.1)
    elif impact < -0.3:
        verdict.warnings.append(f"WORSENS_PORTFOLIO: impact={impact:.2f}")
        verdict.size_multiplier *= 0.7

    # ═══════════════════════════════════
    # 5. ADAPTIVE RULES (learned from history)
    # ═══════════════════════════════════
    try:
        from bahamut.portfolio.learning import capture_portfolio_state, get_adaptive_adjustments
        state = capture_portfolio_state()
        adaptive = get_adaptive_adjustments(state)
        if adaptive["size_mult"] != 1.0:
            verdict.size_multiplier *= adaptive["size_mult"]
            verdict.warnings.append(
                f"ADAPTIVE: size ×{adaptive['size_mult']:.2f} ({len(adaptive['active_rules'])} rules)")
        if adaptive["force_approval"]:
            verdict.requires_approval = True
            verdict.warnings.append("ADAPTIVE: approval required by learned pattern")
    except Exception as e:
        logger.warning("adaptive_rules_failed", error=str(e), asset=proposed_asset)
        from bahamut.shared.degraded import mark_degraded
        mark_degraded("portfolio.adaptive_rules", str(e))

    # ═══════════════════════════════════
    # 6. SCENARIO RISK (macro shock simulation)
    # ═══════════════════════════════════
    scenario_assessment = None
    try:
        from bahamut.portfolio.scenarios import evaluate_scenario_risk
        scenario_assessment = evaluate_scenario_risk(
            positions=snapshot.positions,
            proposed_asset=proposed_asset,
            proposed_direction=proposed_direction,
            proposed_value=proposed_value,
            proposed_entry_price=1.0,  # cancels out in linear PnL: value*shock_pct
            balance=bal,
        )
        if scenario_assessment.risk_level == "BLOCK":
            verdict.blockers.append(
                f"SCENARIO_RISK: tail_risk={scenario_assessment.portfolio_tail_risk:.1%} "
                f"in {scenario_assessment.worst_scenario}")
        elif scenario_assessment.risk_level == "APPROVAL":
            verdict.requires_approval = True
            verdict.warnings.append(
                f"SCENARIO_RISK: tail_risk={scenario_assessment.portfolio_tail_risk:.1%} "
                f"— approval required ({scenario_assessment.worst_scenario})")
        elif scenario_assessment.risk_level == "WARN":
            # Size reduction: scale linearly between 0.6 and 1.0
            from bahamut.portfolio.scenarios import TAIL_RISK_WARN, TAIL_RISK_APPROVAL
            tr = scenario_assessment.portfolio_tail_risk
            scale = 1.0 - 0.4 * ((tr - TAIL_RISK_WARN) / (TAIL_RISK_APPROVAL - TAIL_RISK_WARN))
            scale = max(0.6, min(1.0, scale))
            verdict.size_multiplier *= scale
            verdict.warnings.append(
                f"SCENARIO_RISK: size ×{scale:.2f} (tail_risk={tr:.1%}, worst={scenario_assessment.worst_scenario})")
    except Exception as e:
        logger.error("scenario_risk_failed", error=str(e), asset=proposed_asset)
        from bahamut.shared.degraded import mark_degraded
        mark_degraded("portfolio.scenario_risk", str(e))
        verdict.warnings.append(f"SCENARIO_RISK_UNAVAILABLE: {str(e)[:80]}")
        verdict.requires_approval = True  # conservative: require approval when scenarios can't evaluate

    if scenario_assessment:
        verdict.scenario_risk = scenario_assessment.to_dict()

    # ═══════════════════════════════════
    # 7. MARGINAL RISK CONTRIBUTION
    # ═══════════════════════════════════
    marginal_result = None
    try:
        from bahamut.portfolio.marginal_risk import compute_marginal_risk
        marginal_result = compute_marginal_risk(
            positions=snapshot.positions,
            proposed_asset=proposed_asset,
            proposed_direction=proposed_direction,
            proposed_value=proposed_value,
            balance=bal,
        )
        verdict.marginal_risk = marginal_result.to_dict()

        if marginal_result.risk_level == "BLOCK":
            verdict.blockers.append(
                f"MARGINAL_RISK: worst={marginal_result.worst_case_marginal:.0f} "
                f"in {marginal_result.worst_marginal_scenario}")
        elif marginal_result.risk_level == "APPROVAL":
            verdict.requires_approval = True
            verdict.warnings.append(
                f"MARGINAL_RISK: approval required (worst={marginal_result.worst_case_marginal:.0f})")
        elif marginal_result.risk_level == "WARN":
            verdict.size_multiplier *= 0.8
            verdict.warnings.append(
                f"MARGINAL_RISK: size ×0.80 (worst={marginal_result.worst_case_marginal:.0f})")

        if marginal_result.is_hedging:
            verdict.reasons.append(
                f"HEDGING: trade reduces tail risk by {abs(marginal_result.marginal_tail_risk):.1%}")
    except Exception as e:
        logger.error("marginal_risk_failed", error=str(e), asset=proposed_asset)
        from bahamut.shared.degraded import mark_degraded
        mark_degraded("portfolio.marginal_risk", str(e))
        verdict.warnings.append(f"MARGINAL_RISK_UNAVAILABLE: {str(e)[:80]}")

    # ═══════════════════════════════════
    # 8. QUALITY RATIO (expected return / marginal risk)
    # ═══════════════════════════════════
    try:
        from bahamut.portfolio.quality import compute_quality_ratio
        qr = compute_quality_ratio(
            consensus_score=consensus_score,
            signal_label=signal_label,
            proposed_value=proposed_value,
            atr=atr if atr > 0 else (entry_price * 0.01 if entry_price > 0 else 0),
            entry_price=entry_price if entry_price > 0 else 1.0,
            marginal_risk_result=marginal_result,
        )
        verdict.quality_ratio = qr.to_dict()

        if qr.risk_level == "BLOCK":
            verdict.blockers.append(
                f"QUALITY_RATIO: {qr.quality_ratio:.2f} — return/risk too low")
        elif qr.risk_level == "APPROVAL":
            verdict.requires_approval = True
            verdict.warnings.append(
                f"QUALITY_RATIO: {qr.quality_ratio:.2f} — approval required")
        elif qr.risk_level == "REDUCE":
            verdict.size_multiplier *= 0.7
            verdict.warnings.append(
                f"QUALITY_RATIO: {qr.quality_ratio:.2f} — size ×0.70")
    except Exception as e:
        logger.warning("quality_ratio_failed", error=str(e), asset=proposed_asset)
        from bahamut.shared.degraded import mark_degraded
        mark_degraded("portfolio.quality_ratio", str(e))

    # ═══════════════════════════════════
    # FINAL VERDICT
    # ═══════════════════════════════════
    verdict.size_multiplier = round(max(0.1, min(1.0, verdict.size_multiplier)), 3)

    if verdict.blockers:
        verdict.allowed = False
        verdict.size_multiplier = 0.0

    logger.info("portfolio_verdict", asset=proposed_asset, direction=proposed_direction,
                 allowed=verdict.allowed, size=verdict.size_multiplier,
                 impact=verdict.impact_score, fragility=frag.portfolio_fragility,
                 blockers=len(verdict.blockers), warnings=len(verdict.warnings))

    return verdict


def _compute_exposure(snapshot, asset, direction, value, bal):
    exp = ExposureMetrics()
    dirs = snapshot.by_direction()
    long_val = sum(p.position_value for p in dirs.get("LONG", []))
    short_val = sum(p.position_value for p in dirs.get("SHORT", []))
    exp.gross = (long_val + short_val) / bal
    exp.net = (long_val - short_val) / bal
    exp.long_pct = long_val / bal
    exp.short_pct = short_val / bal

    # Per-class exposure
    for cls, positions in snapshot.by_asset_class().items():
        exp.by_class[cls] = sum(p.position_value for p in positions) / bal

    # Per-theme exposure
    for theme, positions in snapshot.by_theme().items():
        exp.by_theme[theme] = sum(p.position_value for p in positions) / bal

    # Per-asset exposure
    for p in snapshot.positions:
        exp.by_asset[p.asset] = exp.by_asset.get(p.asset, 0) + p.position_value / bal

    # After-trade projections
    new_long = long_val + (value if direction == "LONG" else 0)
    new_short = short_val + (value if direction == "SHORT" else 0)
    exp.after_trade_gross = (new_long + new_short) / bal
    exp.after_trade_net = (new_long - new_short) / bal

    return exp


def _compute_correlation(snapshot, asset, direction, asset_class, themes):
    corr = CorrelationMetrics()
    if not snapshot.positions:
        return corr

    # Directional overlap: what fraction go the same way?
    same_dir = sum(1 for p in snapshot.positions if p.direction == direction)
    corr.directional_overlap = same_dir / len(snapshot.positions)

    # Class concentration: Herfindahl-Hirschman Index
    classes = snapshot.by_asset_class()
    total = len(snapshot.positions) or 1
    shares = [(len(positions) / total) ** 2 for positions in classes.values()]
    corr.class_concentration = sum(shares)

    # Same class count
    corr.same_class_count = len(classes.get(asset_class, []))
    corr.same_direction_same_class = sum(
        1 for p in classes.get(asset_class, []) if p.direction == direction)

    # Theme overlap
    existing_themes = set()
    for p in snapshot.positions:
        existing_themes.update(p.themes)
    corr.theme_overlap_count = len(existing_themes & set(themes))

    return corr


def _compute_fragility(snapshot, bal):
    frag = FragilityMetrics()
    if not snapshot.positions:
        return frag

    # Concentration risk (HHI of position values)
    total_val = snapshot.total_position_value or 1
    value_shares = [(p.position_value / total_val) ** 2 for p in snapshot.positions]
    frag.concentration_risk = min(1.0, sum(value_shares))

    # Directional risk: how one-sided is the portfolio?
    dirs = snapshot.by_direction()
    long_val = sum(p.position_value for p in dirs.get("LONG", []))
    short_val = sum(p.position_value for p in dirs.get("SHORT", []))
    if long_val + short_val > 0:
        frag.directional_risk = abs(long_val - short_val) / (long_val + short_val)

    # Drawdown proximity (how much of the balance is at risk?)
    total_risk = snapshot.total_risk
    frag.drawdown_proximity = min(1.0, total_risk / bal) if bal > 0 else 0

    # Average position quality
    scores = [p.consensus_score for p in snapshot.positions if p.consensus_score > 0]
    frag.avg_position_quality = sum(scores) / len(scores) if scores else 0.5

    # Composite fragility
    frag.portfolio_fragility = round(
        0.30 * frag.concentration_risk
        + 0.25 * frag.directional_risk
        + 0.25 * frag.drawdown_proximity
        + 0.20 * (1.0 - frag.avg_position_quality),  # low quality = more fragile
        3,
    )
    return frag


def _compute_impact(snapshot, direction, asset_class, themes, score, corr, exp, bal):
    """
    Does this trade IMPROVE the portfolio? Score from -1 to +1.
    Positive: adds diversification, hedges existing risk, high quality.
    Negative: increases concentration, adds correlated risk.
    """
    impact = 0.0

    # Diversification: different direction from majority → hedging benefit
    if snapshot.positions:
        majority_dir = max(["LONG", "SHORT"],
                            key=lambda d: sum(1 for p in snapshot.positions if p.direction == d))
        if direction != majority_dir:
            impact += 0.3  # hedging
        else:
            impact -= 0.1  # adding to crowded side

    # New asset class: diversification bonus
    existing_classes = set(p.asset_class for p in snapshot.positions)
    if asset_class not in existing_classes:
        impact += 0.25  # new class = diversification
    elif corr.same_direction_same_class >= 2:
        impact -= 0.25  # piling into same class same direction

    # Theme diversity
    existing_themes = set()
    for p in snapshot.positions:
        existing_themes.update(p.themes)
    new_themes = set(themes) - existing_themes
    if new_themes:
        impact += 0.15  # introduces new themes
    if corr.theme_overlap_count >= 3:
        impact -= 0.2  # heavy theme overlap

    # Signal quality
    if score >= 0.7:
        impact += 0.15  # high quality signal
    elif score < 0.5:
        impact -= 0.15  # weak signal

    # Exposure balance: does this reduce net exposure?
    if abs(exp.after_trade_net) < abs(exp.net):
        impact += 0.15  # trade reduces directional imbalance

    return round(max(-1.0, min(1.0, impact)), 3)
