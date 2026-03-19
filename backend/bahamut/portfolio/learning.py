"""
Bahamut.AI Portfolio Learning Module

Captures portfolio state at trade entry and exit, builds a pattern database,
and derives adaptive rules that modify portfolio intelligence scoring.

DATA FLOW:
  Trade opens  → snapshot_at_entry() captures exposure/fragility/correlation
  Trade closes → snapshot_at_exit() captures same + PnL + outcome
  Daily        → analyze_patterns() processes closed trades, updates adaptive rules
  Live         → get_adaptive_adjustments() reads rules for portfolio engine

PATTERN TRACKING:
  1. Correlation clusters: which asset combos win/lose together?
  2. Fragility levels: what fragility at entry correlates with losses?
  3. Drawdown states: do trades opened during drawdowns underperform?
  4. Concentration patterns: does class/theme concentration predict outcomes?

ADAPTIVE RULES (stored in portfolio_adaptive_rules table):
  Each rule: pattern_key, adjustment_type, adjustment_value, sample_count, confidence
  Rules modify portfolio engine's size_multiplier and block thresholds.
"""
import json
import time
import structlog
from dataclasses import dataclass, field
from collections import defaultdict

logger = structlog.get_logger()


@dataclass
class PortfolioStateSnapshot:
    """Captured at trade entry and exit."""
    position_count: int = 0
    gross_exposure: float = 0.0
    net_exposure: float = 0.0
    fragility: float = 0.0
    concentration_risk: float = 0.0
    directional_risk: float = 0.0
    drawdown_proximity: float = 0.0
    dominant_class: str = ""
    dominant_class_pct: float = 0.0
    dominant_theme: str = ""
    dominant_theme_pct: float = 0.0
    total_unrealized_pnl: float = 0.0
    portfolio_in_drawdown: bool = False
    scenario_risk_level: str = ""
    worst_case_pct: float = 0.0

    def to_dict(self):
        return {k: round(v, 4) if isinstance(v, float) else v
                for k, v in self.__dict__.items()}


@dataclass
class AdaptiveRule:
    """A learned adjustment to portfolio intelligence."""
    pattern_key: str = ""        # e.g. "high_fragility", "fx_concentrated", "in_drawdown"
    adjustment_type: str = ""    # "size_mult", "block", "approval"
    adjustment_value: float = 1.0  # multiplier or threshold
    sample_count: int = 0
    win_rate: float = 0.5
    avg_pnl: float = 0.0
    confidence: float = 0.0      # 0-1, higher = more data
    active: bool = True

    def to_dict(self):
        return {
            "pattern_key": self.pattern_key,
            "adjustment_type": self.adjustment_type,
            "adjustment_value": round(self.adjustment_value, 3),
            "sample_count": self.sample_count,
            "win_rate": round(self.win_rate, 3),
            "avg_pnl": round(self.avg_pnl, 2),
            "confidence": round(self.confidence, 3),
            "active": self.active,
        }


# ══════════════════════════════════════════
# SNAPSHOT CAPTURE (called at trade open/close)
# ══════════════════════════════════════════

def capture_portfolio_state() -> PortfolioStateSnapshot:
    """Capture current portfolio state for logging with a trade event."""
    snap = PortfolioStateSnapshot()
    try:
        from bahamut.portfolio.registry import load_portfolio_snapshot
        from bahamut.portfolio.engine import _compute_exposure, _compute_fragility

        ps = load_portfolio_snapshot()
        bal = ps.balance if ps.balance > 0 else 100000.0
        exp = _compute_exposure(ps, "", "LONG", 0, bal)
        frag = _compute_fragility(ps, bal)

        snap.position_count = ps.position_count
        snap.gross_exposure = exp.gross
        snap.net_exposure = exp.net
        snap.fragility = frag.portfolio_fragility
        snap.concentration_risk = frag.concentration_risk
        snap.directional_risk = frag.directional_risk
        snap.drawdown_proximity = frag.drawdown_proximity
        snap.total_unrealized_pnl = sum(p.unrealized_pnl for p in ps.positions)

        # Dominant class
        by_class = exp.by_class
        if by_class:
            dom_cls = max(by_class, key=by_class.get)
            snap.dominant_class = dom_cls
            snap.dominant_class_pct = by_class[dom_cls]

        # Dominant theme
        by_theme = exp.by_theme
        if by_theme:
            dom_th = max(by_theme, key=by_theme.get)
            snap.dominant_theme = dom_th
            snap.dominant_theme_pct = by_theme[dom_th]

        # Drawdown state
        snap.portfolio_in_drawdown = snap.total_unrealized_pnl < -(bal * 0.02)

    except Exception as e:
        logger.debug("portfolio_snapshot_failed", error=str(e))

    return snap


def log_portfolio_decision(
    position_id: int,
    asset: str,
    direction: str,
    event_type: str,       # "ENTRY" or "EXIT"
    state: PortfolioStateSnapshot,
    pnl: float = 0.0,
    exit_status: str = "",
    consensus_score: float = 0.0,
    portfolio_verdict_impact: float = 0.0,
):
    """Persist a portfolio decision event."""
    try:
        from bahamut.database import sync_engine
        from sqlalchemy import text
        with sync_engine.connect() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS portfolio_decision_log (
                    id SERIAL PRIMARY KEY,
                    position_id INTEGER,
                    asset VARCHAR(20),
                    direction VARCHAR(10),
                    event_type VARCHAR(10),
                    state JSONB,
                    pnl FLOAT DEFAULT 0,
                    exit_status VARCHAR(30),
                    consensus_score FLOAT DEFAULT 0,
                    portfolio_impact FLOAT DEFAULT 0,
                    created_at TIMESTAMP DEFAULT NOW())
            """))
            conn.execute(text("""
                INSERT INTO portfolio_decision_log
                (position_id, asset, direction, event_type, state, pnl,
                 exit_status, consensus_score, portfolio_impact)
                VALUES (:pid, :a, :d, :ev, :st, :pnl, :es, :cs, :pi)
            """), {
                "pid": position_id, "a": asset, "d": direction,
                "ev": event_type, "st": json.dumps(state.to_dict()),
                "pnl": round(pnl, 2), "es": exit_status,
                "cs": round(consensus_score, 4),
                "pi": round(portfolio_verdict_impact, 4),
            })
            conn.commit()
    except Exception as e:
        logger.warning("portfolio_log_failed", error=str(e))


# ══════════════════════════════════════════
# PATTERN ANALYSIS (called daily by calibration)
# ══════════════════════════════════════════

def analyze_patterns(lookback_days: int = 30) -> list[AdaptiveRule]:
    """
    Analyze closed trades to find patterns between portfolio state and outcomes.
    Returns list of adaptive rules derived from data.
    """
    rules = []
    try:
        entries = _load_decision_log(lookback_days, "ENTRY")
        exits = _load_decision_log(lookback_days, "EXIT")

        # Build position_id → (entry_state, exit_state, pnl) mapping
        entry_map = {e["position_id"]: e for e in entries}
        paired = []
        for ex in exits:
            pid = ex["position_id"]
            if pid in entry_map:
                paired.append({
                    "entry": entry_map[pid],
                    "exit": ex,
                    "pnl": ex.get("pnl", 0),
                    "win": ex.get("pnl", 0) > 0,
                })

        if len(paired) < 5:
            logger.info("portfolio_learning_skipped", pairs=len(paired))
            return rules

        # Pattern 1: High fragility at entry → outcome
        rules.append(_analyze_bucket(
            paired, "high_fragility",
            key_fn=lambda p: _get_state(p["entry"]).get("fragility", 0) > 0.5,
        ))

        # Pattern 2: High concentration at entry → outcome
        rules.append(_analyze_bucket(
            paired, "high_concentration",
            key_fn=lambda p: _get_state(p["entry"]).get("concentration_risk", 0) > 0.4,
        ))

        # Pattern 3: Portfolio in drawdown at entry → outcome
        rules.append(_analyze_bucket(
            paired, "in_drawdown",
            key_fn=lambda p: _get_state(p["entry"]).get("portfolio_in_drawdown", False),
        ))

        # Pattern 4: High gross exposure at entry → outcome
        rules.append(_analyze_bucket(
            paired, "high_gross_exposure",
            key_fn=lambda p: _get_state(p["entry"]).get("gross_exposure", 0) > 0.5,
        ))

        # Pattern 5: Directional imbalance at entry → outcome
        rules.append(_analyze_bucket(
            paired, "directional_imbalance",
            key_fn=lambda p: _get_state(p["entry"]).get("directional_risk", 0) > 0.6,
        ))

        # Pattern 6: Theme concentration at entry → outcome
        rules.append(_analyze_bucket(
            paired, "theme_concentrated",
            key_fn=lambda p: _get_state(p["entry"]).get("dominant_theme_pct", 0) > 0.25,
        ))

        # Pattern 7: Correlation cluster (many same-class positions) → outcome
        rules.append(_analyze_bucket(
            paired, "class_crowded",
            key_fn=lambda p: _get_state(p["entry"]).get("dominant_class_pct", 0) > 0.35,
        ))

        # ── Scenario outcome learning patterns ──

        # Pattern 8: High weighted tail risk at entry → outcome
        rules.append(_analyze_bucket(
            paired, "high_weighted_tail_risk",
            key_fn=lambda p: _get_state(p["entry"]).get("worst_case_pct", 0) < -0.04,
        ))

        # Pattern 9: Scenario risk level was WARN+ at entry → outcome
        rules.append(_analyze_bucket(
            paired, "scenario_warned",
            key_fn=lambda p: _get_state(p["entry"]).get("scenario_risk_level", "") in ("WARN", "APPROVAL"),
        ))

        # Pattern 10: High fragility + high tail risk combined
        rules.append(_analyze_bucket(
            paired, "fragile_and_stressed",
            key_fn=lambda p: (
                _get_state(p["entry"]).get("fragility", 0) > 0.4
                and _get_state(p["entry"]).get("worst_case_pct", 0) < -0.03
            ),
        ))

        # Pattern 11: Theme concentration + scenario risk combined
        rules.append(_analyze_bucket(
            paired, "theme_stressed",
            key_fn=lambda p: (
                _get_state(p["entry"]).get("dominant_theme_pct", 0) > 0.20
                and _get_state(p["entry"]).get("scenario_risk_level", "") != ""
                and _get_state(p["entry"]).get("scenario_risk_level", "") != "OK"
            ),
        ))

        # Pattern 12: Portfolio in drawdown + high concentration
        rules.append(_analyze_bucket(
            paired, "drawdown_concentrated",
            key_fn=lambda p: (
                _get_state(p["entry"]).get("portfolio_in_drawdown", False)
                and _get_state(p["entry"]).get("concentration_risk", 0) > 0.35
            ),
        ))

        # Filter out rules with insufficient data
        rules = [r for r in rules if r.sample_count >= 3]

        # Persist
        _persist_rules(rules)

        logger.info("portfolio_patterns_analyzed", pairs=len(paired),
                     rules=len(rules))

    except Exception as e:
        logger.warning("pattern_analysis_failed", error=str(e))

    return rules


def _analyze_bucket(paired, pattern_key, key_fn) -> AdaptiveRule:
    """Analyze a subset of trades matching a condition."""
    matching = [p for p in paired if key_fn(p)]
    rule = AdaptiveRule(pattern_key=pattern_key)
    rule.sample_count = len(matching)

    if not matching:
        return rule

    wins = sum(1 for p in matching if p["win"])
    rule.win_rate = wins / len(matching)
    rule.avg_pnl = sum(p["pnl"] for p in matching) / len(matching)

    # Confidence: more samples = higher confidence (logistic-style)
    rule.confidence = min(1.0, len(matching) / 20)

    # Derive adjustment
    if rule.win_rate < 0.35 and rule.sample_count >= 5:
        rule.adjustment_type = "size_mult"
        rule.adjustment_value = 0.5 + rule.win_rate  # WR 0.35→0.85, WR 0.20→0.70
        rule.active = True
    elif rule.win_rate < 0.30 and rule.sample_count >= 8:
        rule.adjustment_type = "approval"
        rule.adjustment_value = 1.0  # force approval
        rule.active = True
    elif rule.win_rate > 0.65 and rule.sample_count >= 5:
        rule.adjustment_type = "size_mult"
        rule.adjustment_value = min(1.2, 0.8 + rule.win_rate * 0.5)  # WR 0.65→1.125
        rule.active = True
    else:
        rule.adjustment_type = "none"
        rule.adjustment_value = 1.0
        rule.active = False

    return rule


# ══════════════════════════════════════════
# ADAPTIVE ADJUSTMENTS (read by portfolio engine)
# ══════════════════════════════════════════

_rule_cache: dict = {"rules": [], "loaded_at": 0}
RULE_CACHE_TTL = 300  # 5 min


def get_adaptive_adjustments(state: PortfolioStateSnapshot) -> dict:
    """
    Given current portfolio state, return adjustments derived from learned patterns.
    Returns: {"size_mult": float, "force_approval": bool, "active_rules": list}
    """
    rules = _get_cached_rules()
    if not rules:
        return {"size_mult": 1.0, "force_approval": False, "active_rules": []}

    size_mult = 1.0
    force_approval = False
    active = []

    for rule in rules:
        if not rule.active or rule.confidence < 0.3:
            continue

        triggered = _check_rule_trigger(rule, state)
        if not triggered:
            continue

        if rule.adjustment_type == "size_mult":
            size_mult *= rule.adjustment_value
            active.append(rule.to_dict())
        elif rule.adjustment_type == "approval":
            force_approval = True
            active.append(rule.to_dict())

    size_mult = max(0.3, min(1.2, size_mult))

    return {
        "size_mult": round(size_mult, 3),
        "force_approval": force_approval,
        "active_rules": active,
    }


def _check_rule_trigger(rule: AdaptiveRule, state: PortfolioStateSnapshot) -> bool:
    """Check if a rule's pattern matches current state."""
    triggers = {
        "high_fragility": state.fragility > 0.5,
        "high_concentration": state.concentration_risk > 0.4,
        "in_drawdown": state.portfolio_in_drawdown,
        "high_gross_exposure": state.gross_exposure > 0.5,
        "directional_imbalance": state.directional_risk > 0.6,
        "theme_concentrated": state.dominant_theme_pct > 0.25,
        "class_crowded": state.dominant_class_pct > 0.35,
        # Scenario outcome learned patterns
        "high_weighted_tail_risk": state.worst_case_pct < -0.04,
        "scenario_warned": state.scenario_risk_level in ("WARN", "APPROVAL"),
        "fragile_and_stressed": state.fragility > 0.4 and state.worst_case_pct < -0.03,
        "theme_stressed": (state.dominant_theme_pct > 0.20
                            and state.scenario_risk_level not in ("", "OK")),
        "drawdown_concentrated": (state.portfolio_in_drawdown
                                    and state.concentration_risk > 0.35),
    }
    return triggers.get(rule.pattern_key, False)


def _get_cached_rules() -> list[AdaptiveRule]:
    now = time.time()
    if _rule_cache["rules"] and (now - _rule_cache["loaded_at"]) < RULE_CACHE_TTL:
        return _rule_cache["rules"]
    rules = _load_rules()
    _rule_cache["rules"] = rules
    _rule_cache["loaded_at"] = now
    return rules


def get_all_rules() -> list[dict]:
    """Get all adaptive rules for API/UI."""
    rules = _get_cached_rules()
    return [r.to_dict() for r in rules]


def get_decision_log(limit: int = 20) -> list[dict]:
    """Get recent portfolio decision log entries."""
    try:
        from bahamut.database import sync_engine
        from sqlalchemy import text
        with sync_engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT position_id, asset, direction, event_type, state,
                       pnl, exit_status, consensus_score, portfolio_impact, created_at
                FROM portfolio_decision_log ORDER BY created_at DESC LIMIT :l
            """), {"l": limit}).mappings().all()
            return [dict(r) for r in rows]
    except Exception as e:

        logger.warning("portfolio_learning_silent_error", error=str(e))
        return []


# ══════════════════════════════════════════
# DB HELPERS
# ══════════════════════════════════════════

def _load_decision_log(days: int, event_type: str) -> list[dict]:
    try:
        from bahamut.database import sync_engine
        from sqlalchemy import text
        with sync_engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT position_id, asset, direction, state, pnl, exit_status,
                       consensus_score, portfolio_impact
                FROM portfolio_decision_log
                WHERE event_type = :ev AND created_at > NOW() - INTERVAL ':d days'
                ORDER BY created_at
            """.replace(":d days", f"{int(days)} days")), {"ev": event_type}).mappings().all()
            return [dict(r) for r in rows]
    except Exception as e:

        logger.warning("portfolio_learning_silent_error", error=str(e))
        return []


def _get_state(entry: dict) -> dict:
    """Extract state dict from a decision log row."""
    st = entry.get("state", {})
    if isinstance(st, str):
        try:
            return json.loads(st)
        except Exception as e:

            logger.warning("portfolio_learning_silent_error", error=str(e))
            return {}
    return st or {}


def _persist_rules(rules: list[AdaptiveRule]):
    try:
        from bahamut.database import sync_engine
        from sqlalchemy import text
        with sync_engine.connect() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS portfolio_adaptive_rules (
                    id SERIAL PRIMARY KEY,
                    pattern_key VARCHAR(50) UNIQUE NOT NULL,
                    adjustment_type VARCHAR(20),
                    adjustment_value FLOAT DEFAULT 1.0,
                    sample_count INTEGER DEFAULT 0,
                    win_rate FLOAT DEFAULT 0.5,
                    avg_pnl FLOAT DEFAULT 0,
                    confidence FLOAT DEFAULT 0,
                    active BOOLEAN DEFAULT TRUE,
                    updated_at TIMESTAMP DEFAULT NOW())
            """))
            for r in rules:
                conn.execute(text("""
                    INSERT INTO portfolio_adaptive_rules
                    (pattern_key, adjustment_type, adjustment_value, sample_count,
                     win_rate, avg_pnl, confidence, active, updated_at)
                    VALUES (:pk, :at, :av, :sc, :wr, :ap, :co, :ac, NOW())
                    ON CONFLICT (pattern_key) DO UPDATE SET
                        adjustment_type = :at, adjustment_value = :av,
                        sample_count = :sc, win_rate = :wr, avg_pnl = :ap,
                        confidence = :co, active = :ac, updated_at = NOW()
                """), {
                    "pk": r.pattern_key, "at": r.adjustment_type,
                    "av": r.adjustment_value, "sc": r.sample_count,
                    "wr": r.win_rate, "ap": r.avg_pnl,
                    "co": r.confidence, "ac": r.active,
                })
            conn.commit()
    except Exception as e:
        logger.warning("persist_rules_failed", error=str(e))


def _load_rules() -> list[AdaptiveRule]:
    try:
        from bahamut.database import sync_engine
        from sqlalchemy import text
        with sync_engine.connect() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS portfolio_adaptive_rules (
                    id SERIAL PRIMARY KEY,
                    pattern_key VARCHAR(50) UNIQUE NOT NULL,
                    adjustment_type VARCHAR(20),
                    adjustment_value FLOAT DEFAULT 1.0,
                    sample_count INTEGER DEFAULT 0,
                    win_rate FLOAT DEFAULT 0.5,
                    avg_pnl FLOAT DEFAULT 0,
                    confidence FLOAT DEFAULT 0,
                    active BOOLEAN DEFAULT TRUE,
                    updated_at TIMESTAMP DEFAULT NOW())
            """))
            rows = conn.execute(text(
                "SELECT * FROM portfolio_adaptive_rules WHERE active = TRUE ORDER BY confidence DESC"
            )).mappings().all()
            return [AdaptiveRule(
                pattern_key=r["pattern_key"],
                adjustment_type=r["adjustment_type"],
                adjustment_value=float(r["adjustment_value"]),
                sample_count=int(r["sample_count"]),
                win_rate=float(r["win_rate"]),
                avg_pnl=float(r["avg_pnl"]),
                confidence=float(r["confidence"]),
                active=bool(r["active"]),
            ) for r in rows]
    except Exception as e:

        logger.warning("portfolio_learning_silent_error", error=str(e))
        return []
