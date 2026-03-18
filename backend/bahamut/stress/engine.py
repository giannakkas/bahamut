"""
Bahamut.AI Stress Testing Engine

Two modes:
  1. REPLAY: Load decision_traces from DB, replay through current consensus
     + execution pipeline with modified parameters. Measures how many trades
     would have changed (opened/blocked/sized differently).

  2. SCENARIO: Run predefined synthetic stress scenarios that simulate
     extreme conditions (trust collapse, regime shock, losing streak, etc.)
     through the real pipeline.

All runs are read-only. No positions opened. No trust scores modified.
Results persisted to stress_test_runs table.
"""
import json
import time
import structlog
from dataclasses import dataclass, field
from uuid import uuid4
from copy import deepcopy

logger = structlog.get_logger()


@dataclass
class StressResult:
    scenario_name: str = ""
    mode: str = ""  # "replay" or "scenario"
    total_signals: int = 0
    would_open: int = 0
    would_block: int = 0
    original_opens: int = 0
    original_blocks: int = 0
    changed_decisions: int = 0
    avg_size_multiplier: float = 0.0
    max_drawdown_simulated: float = 0.0
    win_rate_simulated: float = 0.0
    blockers_fired: dict = field(default_factory=dict)  # {blocker: count}
    warnings_fired: dict = field(default_factory=dict)
    details: list = field(default_factory=list)
    elapsed_ms: int = 0
    notes: list = field(default_factory=list)

    def to_dict(self):
        return {
            "scenario_name": self.scenario_name, "mode": self.mode,
            "total_signals": self.total_signals,
            "would_open": self.would_open, "would_block": self.would_block,
            "original_opens": self.original_opens, "original_blocks": self.original_blocks,
            "changed_decisions": self.changed_decisions,
            "avg_size_multiplier": round(self.avg_size_multiplier, 3),
            "max_drawdown_simulated": round(self.max_drawdown_simulated, 4),
            "win_rate_simulated": round(self.win_rate_simulated, 3),
            "blockers_fired": self.blockers_fired,
            "warnings_fired": self.warnings_fired,
            "notes": self.notes,
            "elapsed_ms": self.elapsed_ms,
        }


def replay_with_modified_params(
    trust_overrides: dict = None,
    profile_override: str = None,
    threshold_overrides: dict = None,
    regime_override: str = None,
    max_traces: int = 50,
    mutators: list = None,
) -> StressResult:
    """
    Replay recent decision traces through the current pipeline with modified params.
    Read-only: no trades opened, no trust modified.

    mutators: list of callables with signature:
        fn(trace_idx, total_traces, agent_outputs, disagree_dict, trace) -> None
    Each mutator modifies agent_outputs list and/or disagree_dict in place.
    """
    start = time.time()
    result = StressResult(scenario_name="replay", mode="replay")

    traces = _load_recent_traces(max_traces)
    if not traces:
        result.notes.append("No decision traces found")
        return result

    from bahamut.consensus.engine import ConsensusEngine, PROFILE_THRESHOLDS
    from bahamut.consensus.disagreement import DisagreementEngine
    from bahamut.consensus.weights import weight_resolver
    from bahamut.execution.policy import ExecutionPolicy, ExecutionRequest
    from bahamut.agents.schemas import AgentOutputSchema, Evidence, DisagreementMetrics

    engine = ConsensusEngine()
    policy = ExecutionPolicy()
    size_mults = []

    # Temporarily apply threshold overrides
    original_thresholds = deepcopy(PROFILE_THRESHOLDS)
    if threshold_overrides:
        for profile, overrides in threshold_overrides.items():
            if profile in PROFILE_THRESHOLDS:
                PROFILE_THRESHOLDS[profile].update(overrides)

    mutators = mutators or []

    try:
        for trace_idx, trace in enumerate(traces):
            result.total_signals += 1
            consensus = trace.get("consensus_output", {})
            agent_data = trace.get("agent_outputs", [])
            stored_disagree = trace.get("disagreement_metrics", {})
            stored_trust = trace.get("trust_scores_at_decision", {})
            outcome = trace.get("outcome", {})
            asset = trace.get("asset", "EURUSD")
            regime = regime_override or trace.get("regime", "RISK_ON")
            profile = profile_override or trace.get("trading_profile", "BALANCED")

            # Apply trust overrides
            trust_scores = stored_trust.copy() if stored_trust else {}
            if trust_overrides:
                trust_scores.update(trust_overrides)

            # Was originally opened?
            original_opened = consensus.get("execution_mode") in ("AUTO", "APPROVAL") and \
                              consensus.get("decision") in ("STRONG_SIGNAL", "SIGNAL")
            if original_opened:
                result.original_opens += 1
            else:
                result.original_blocks += 1

            # Re-resolve weights with (possibly modified) trust
            resolved = weight_resolver.resolve_weights(
                "fx", regime, "4H", trust_scores)

            # Build mutable disagreement dict
            disagree_dict = {
                "disagreement_index": stored_disagree.get("disagreement_index", 0),
                "execution_gate": stored_disagree.get("execution_gate", "CLEAR"),
                "gate_reasons": list(stored_disagree.get("gate_reasons", [])),
            }

            # Reconstruct minimal agent outputs for consensus
            mock_agents = []
            for ao in agent_data:
                try:
                    mock_agents.append(AgentOutputSchema(
                        agent_id=ao.get("agent_id", "unknown"),
                        cycle_id=uuid4(),
                        timestamp=ao.get("timestamp", "2025-01-01T00:00:00+00:00"),
                        asset=asset, timeframe="4H",
                        directional_bias=ao.get("directional_bias", "NEUTRAL"),
                        confidence=ao.get("confidence", 0.5),
                        evidence=[Evidence(claim="replay", data_point="replay", weight=0.5)],
                        meta=dict(ao.get("meta", {})),
                    ))
                except Exception:
                    continue

            if not mock_agents:
                continue

            # ── Apply mutators ──
            total_traces = len(traces)
            for mutator in mutators:
                try:
                    mutator(trace_idx, total_traces, mock_agents, disagree_dict, trace)
                except Exception as e:
                    logger.debug("mutator_failed", error=str(e))

            # Build disagreement metrics after mutation
            dm = DisagreementMetrics(
                disagreement_index=disagree_dict["disagreement_index"],
                execution_gate=disagree_dict["execution_gate"],
                gate_reasons=disagree_dict["gate_reasons"],
            )

            # Re-read regime (mutators can change trace["regime"])
            regime = regime_override or trace.get("regime", regime)

            # Re-resolve weights if mutators changed trust or regime
            resolved = weight_resolver.resolve_weights(
                "fx", regime, "4H", trust_scores)

            # Run consensus
            try:
                decision = engine.calculate(
                    mock_agents, "fx", regime, profile,
                    trust_scores=trust_scores, resolved_weights=resolved,
                    disagreement_metrics=dm)
            except Exception:
                continue

            # Run execution policy
            mean_trust = sum(trust_scores.get(a, 1.0) for a in
                             ["technical_agent", "macro_agent", "sentiment_agent",
                              "volatility_agent", "liquidity_agent"]) / 5
            exec_req = ExecutionRequest(
                asset=asset, direction=decision.direction,
                consensus_score=decision.final_score, signal_label=decision.decision,
                execution_mode_from_consensus=decision.execution_mode,
                disagreement_gate=dm.execution_gate, disagreement_index=dm.disagreement_index,
                risk_can_trade=True, risk_flags=[], trading_profile=profile,
                open_position_count=1, has_position_in_asset=False,
                portfolio_balance=100000, mean_agent_trust=mean_trust, regime=regime,
            )
            exec_dec = policy.evaluate(exec_req)

            now_opens = exec_dec.allowed and decision.decision in ("STRONG_SIGNAL", "SIGNAL")
            if now_opens:
                result.would_open += 1
                size_mults.append(exec_dec.position_size_multiplier)
            else:
                result.would_block += 1

            if now_opens != original_opened:
                result.changed_decisions += 1

            for b in exec_dec.blockers:
                key = b.split(":")[0] if ":" in b else b
                result.blockers_fired[key] = result.blockers_fired.get(key, 0) + 1
            for w in exec_dec.warnings:
                key = w.split(":")[0] if ":" in w else w
                result.warnings_fired[key] = result.warnings_fired.get(key, 0) + 1

            # Simulated P&L from outcome
            if outcome and outcome.get("pnl") is not None:
                pnl = outcome["pnl"]
                if now_opens:
                    result.details.append({
                        "asset": asset, "pnl": pnl,
                        "score": decision.final_score,
                        "size_mult": exec_dec.position_size_multiplier,
                    })

        # Compute simulated metrics
        if size_mults:
            result.avg_size_multiplier = sum(size_mults) / len(size_mults)
        if result.details:
            wins = sum(1 for d in result.details if d["pnl"] > 0)
            result.win_rate_simulated = wins / len(result.details) if result.details else 0
            # Max drawdown simulation
            running_pnl = 0
            peak = 0
            max_dd = 0
            for d in result.details:
                running_pnl += d["pnl"] * d["size_mult"]
                peak = max(peak, running_pnl)
                dd = (peak - running_pnl) / max(1, peak) if peak > 0 else 0
                max_dd = max(max_dd, dd)
            result.max_drawdown_simulated = max_dd

    finally:
        # Restore original thresholds
        for profile, orig in original_thresholds.items():
            PROFILE_THRESHOLDS[profile] = orig

    result.elapsed_ms = int((time.time() - start) * 1000)
    _persist_result(result)
    return result


def run_scenario(scenario_config: dict) -> StressResult:
    """
    Run a predefined stress scenario. Config must contain:
      name, trust_overrides, profile, regime, threshold_overrides, mutators
    """
    return replay_with_modified_params(
        trust_overrides=scenario_config.get("trust_overrides"),
        profile_override=scenario_config.get("profile"),
        threshold_overrides=scenario_config.get("threshold_overrides"),
        regime_override=scenario_config.get("regime"),
        max_traces=scenario_config.get("max_traces", 50),
        mutators=scenario_config.get("mutators"),
    )


def run_all_scenarios() -> list[StressResult]:
    """Run all predefined stress scenarios."""
    from bahamut.stress.scenarios import SCENARIOS
    results = []
    for s in SCENARIOS:
        r = run_scenario(s)
        r.scenario_name = s["name"]
        results.append(r)
        logger.info("stress_scenario_complete", name=s["name"],
                     changed=r.changed_decisions, total=r.total_signals)
    return results


def get_recent_results(limit: int = 10) -> list[dict]:
    try:
        from bahamut.database import sync_engine
        from sqlalchemy import text
        with sync_engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT scenario_name, mode, total_signals, would_open, would_block,
                       changed_decisions, avg_size_mult, blockers, warnings,
                       elapsed_ms, created_at
                FROM stress_test_runs ORDER BY created_at DESC LIMIT :l
            """), {"l": limit}).mappings().all()
            return [dict(r) for r in rows]
    except Exception:
        return []


def _load_recent_traces(limit: int) -> list[dict]:
    try:
        from bahamut.database import sync_engine
        from sqlalchemy import text
        with sync_engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT cycle_id, asset, regime, trading_profile, agent_outputs,
                       consensus_output, disagreement_metrics, trust_scores_at_decision,
                       outcome
                FROM decision_traces
                ORDER BY created_at DESC LIMIT :l
            """), {"l": limit}).mappings().all()
            return [dict(r) for r in rows]
    except Exception as e:
        logger.debug("trace_load_failed", error=str(e))
        return []


def _persist_result(result: StressResult):
    try:
        from bahamut.database import sync_engine
        from sqlalchemy import text
        with sync_engine.connect() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS stress_test_runs (
                    id SERIAL PRIMARY KEY, scenario_name VARCHAR(100),
                    mode VARCHAR(20), total_signals INTEGER,
                    would_open INTEGER, would_block INTEGER,
                    changed_decisions INTEGER, avg_size_mult FLOAT,
                    blockers JSONB, warnings JSONB,
                    elapsed_ms INTEGER, notes TEXT,
                    created_at TIMESTAMP DEFAULT NOW())
            """))
            conn.execute(text("""
                INSERT INTO stress_test_runs
                (scenario_name, mode, total_signals, would_open, would_block,
                 changed_decisions, avg_size_mult, blockers, warnings, elapsed_ms, notes)
                VALUES (:n, :m, :t, :o, :b, :c, :s, :bl, :w, :e, :no)
            """), {
                "n": result.scenario_name, "m": result.mode,
                "t": result.total_signals, "o": result.would_open,
                "b": result.would_block, "c": result.changed_decisions,
                "s": result.avg_size_multiplier,
                "bl": json.dumps(result.blockers_fired),
                "w": json.dumps(result.warnings_fired),
                "e": result.elapsed_ms,
                "no": "\n".join(result.notes),
            })
            conn.commit()
    except Exception as e:
        logger.warning("stress_persist_failed", error=str(e))
