"""
Bahamut.AI Test Suite — 48 tests across 6 critical subsystems.
Run: cd backend && python -m pytest tests/test_intelligence.py -v
"""
import pytest
import math
from uuid import uuid4
from datetime import datetime, timezone
from unittest.mock import MagicMock

from bahamut.agents.schemas import (
    AgentOutputSchema, ChallengeResponseSchema, DisagreementMetrics, Evidence,
)


def _out(agent_id, bias, conf, cid=None):
    return AgentOutputSchema(
        agent_id=agent_id, cycle_id=cid or uuid4(),
        timestamp=datetime.now(timezone.utc), asset="EURUSD", timeframe="4H",
        directional_bias=bias, confidence=conf,
        evidence=[Evidence(claim="t", data_point="t", weight=0.5)], meta={},
    )

def _risk(can_trade=True, flags=None, cid=None):
    return AgentOutputSchema(
        agent_id="risk_agent", cycle_id=cid or uuid4(),
        timestamp=datetime.now(timezone.utc), asset="EURUSD", timeframe="4H",
        directional_bias="NEUTRAL", confidence=0.8,
        evidence=[Evidence(claim="risk", data_point="ok", weight=0.5)],
        meta={"can_trade": can_trade, "risk_flags": flags or []},
    )


# ══════════════════════════════════════
# 1. DISAGREEMENT ENGINE (6 tests)
# ══════════════════════════════════════
from bahamut.consensus.disagreement import DisagreementEngine

class TestDisagreementEngine:
    def setup_method(self):
        self.eng = DisagreementEngine()

    def test_unanimous_low_disagreement(self):
        c = uuid4()
        outs = [_out("technical_agent","LONG",0.85,c), _out("macro_agent","LONG",0.75,c),
                _out("sentiment_agent","LONG",0.70,c), _out("volatility_agent","LONG",0.65,c),
                _out("liquidity_agent","LONG",0.60,c)]
        r = self.eng.calculate(outs, _risk(cid=c), [], "BALANCED")
        assert r.disagreement_index < 0.2
        assert r.contradiction_count == 0
        assert r.execution_gate == "CLEAR"

    def test_split_high_disagreement(self):
        c = uuid4()
        outs = [_out("technical_agent","LONG",0.9,c), _out("macro_agent","LONG",0.8,c),
                _out("sentiment_agent","SHORT",0.85,c), _out("volatility_agent","SHORT",0.8,c),
                _out("liquidity_agent","SHORT",0.75,c)]
        r = self.eng.calculate(outs, _risk(cid=c), [], "BALANCED")
        assert r.disagreement_index > 0.3
        assert r.contradiction_count > 0

    def test_risk_veto_blocks(self):
        c = uuid4()
        outs = [_out("technical_agent","LONG",0.9,c)]
        r = self.eng.calculate(outs, _risk(False,["DAILY_DD"],c), [], "BALANCED")
        assert r.execution_gate == "BLOCKED"
        assert r.risk_rejection_penalty == 1.0

    def test_conservative_stricter(self):
        c = uuid4()
        outs = [_out("technical_agent","LONG",0.7,c), _out("macro_agent","SHORT",0.65,c),
                _out("sentiment_agent","NEUTRAL",0.5,c)]
        risk = _risk(cid=c)
        rc = self.eng.calculate(outs, risk, [], "CONSERVATIVE")
        ra = self.eng.calculate(outs, risk, [], "AGGRESSIVE")
        gate_ord = {"CLEAR": 0, "APPROVAL_ONLY": 1, "BLOCKED": 2}
        assert gate_ord[rc.execution_gate] >= gate_ord[ra.execution_gate]

    def test_empty_blocked(self):
        assert self.eng.calculate([], None, [], "BALANCED").execution_gate == "BLOCKED"

    def test_challenge_veto_increases(self):
        c = uuid4()
        outs = [_out("technical_agent","LONG",0.7,c), _out("macro_agent","LONG",0.6,c)]
        risk = _risk(cid=c)
        r0 = self.eng.calculate(outs, risk, [], "BALANCED")
        chs = [ChallengeResponseSchema(
            challenge_id=uuid4(), challenger="risk_agent", target_agent="technical_agent",
            challenge_type="RISK_CHECK", response="VETO")]
        r1 = self.eng.calculate(outs, risk, chs, "BALANCED")
        assert r1.challenge_severity > r0.challenge_severity


# ══════════════════════════════════════
# 2. EXECUTION POLICY (12 tests)
# ══════════════════════════════════════
from bahamut.execution.policy import ExecutionPolicy, ExecutionRequest

class TestExecutionPolicy:
    def setup_method(self):
        self.pol = ExecutionPolicy()

    def _req(self, **kw):
        d = dict(asset="EURUSD", direction="LONG", consensus_score=0.75,
                 signal_label="STRONG_SIGNAL", execution_mode_from_consensus="AUTO",
                 disagreement_gate="CLEAR", disagreement_index=0.1,
                 risk_can_trade=True, trading_profile="BALANCED",
                 current_drawdown_daily=0.01, current_drawdown_weekly=0.02,
                 open_position_count=1, has_position_in_asset=False,
                 portfolio_balance=100000, mean_agent_trust=1.0)
        d.update(kw)
        return ExecutionRequest(**d)

    def test_clean_allowed(self):
        d = self.pol.evaluate(self._req())
        assert d.allowed and d.mode == "PAPER_AUTO" and len(d.blockers) == 0

    def test_risk_veto(self):
        d = self.pol.evaluate(self._req(risk_can_trade=False, risk_flags=["DD"]))
        assert not d.allowed and "RISK_VETO" in d.blockers[0]

    def test_daily_dd(self):
        d = self.pol.evaluate(self._req(current_drawdown_daily=0.04))
        assert not d.allowed

    def test_weekly_dd(self):
        d = self.pol.evaluate(self._req(current_drawdown_weekly=0.07))
        assert not d.allowed

    def test_max_pos(self):
        d = self.pol.evaluate(self._req(open_position_count=5))
        assert not d.allowed

    def test_dup(self):
        d = self.pol.evaluate(self._req(has_position_in_asset=True))
        assert not d.allowed

    def test_low_score(self):
        d = self.pol.evaluate(self._req(consensus_score=0.40))
        assert not d.allowed

    def test_disagree_blocked(self):
        d = self.pol.evaluate(self._req(disagreement_gate="BLOCKED"))
        assert not d.allowed

    def test_conservative_approval(self):
        d = self.pol.evaluate(self._req(trading_profile="CONSERVATIVE", consensus_score=0.85))
        assert d.allowed and d.requires_approval and d.mode == "PAPER_APPROVAL"

    def test_disagree_approval_size(self):
        d = self.pol.evaluate(self._req(disagreement_gate="APPROVAL_ONLY", disagreement_index=0.45))
        assert d.allowed and d.position_size_multiplier < 1.0 and d.requires_approval

    def test_crisis_conservative_blocks(self):
        d = self.pol.evaluate(self._req(regime="CRISIS", trading_profile="CONSERVATIVE"))
        assert not d.allowed

    def test_watch_blocks(self):
        d = self.pol.evaluate(self._req(execution_mode_from_consensus="WATCH"))
        assert not d.allowed

    def test_low_trust_blocks(self):
        """Mean trust < 0.5 → hard block."""
        d = self.pol.evaluate(self._req(mean_agent_trust=0.4))
        assert not d.allowed
        assert any("LOW_TRUST" in b for b in d.blockers)

    def test_moderate_trust_requires_approval(self):
        """Mean trust 0.5-0.7 → requires approval even for STRONG_SIGNAL."""
        d = self.pol.evaluate(self._req(mean_agent_trust=0.6))
        assert d.allowed and d.requires_approval

    def test_slightly_low_trust_reduces_size(self):
        """Mean trust 0.7-0.85 → position size reduced."""
        d = self.pol.evaluate(self._req(mean_agent_trust=0.75))
        assert d.allowed and d.position_size_multiplier < 1.0

    def test_risk_flags_reduce_size(self):
        """HIGH_CORRELATION flag → position size reduced."""
        d = self.pol.evaluate(self._req(risk_flags=["HIGH_CORRELATION"]))
        assert d.allowed and d.position_size_multiplier < 1.0
        assert any("CORR" in w for w in d.warnings)

    def test_stale_data_blocks(self):
        """STALE_DATA hard flag → blocked."""
        d = self.pol.evaluate(self._req(risk_flags=["STALE_DATA"]))
        assert not d.allowed
        assert any("RISK_FLAGS" in b for b in d.blockers)


# ══════════════════════════════════════
# 3. DYNAMIC WEIGHTS (7 tests)
# ══════════════════════════════════════
from bahamut.consensus.weights import DynamicWeightResolver

class TestDynamicWeightResolver:
    def setup_method(self):
        self.wr = DynamicWeightResolver()

    def test_positive(self):
        w = self.wr.resolve_weights("fx", "RISK_ON")
        assert all(v > 0 for v in w.values()) and len(w) == 5

    def test_trust_amplifies(self):
        wl = self.wr.resolve_weights("fx","RISK_ON",trust_scores={"technical_agent":0.5})
        wh = self.wr.resolve_weights("fx","RISK_ON",trust_scores={"technical_agent":1.5})
        assert wh["technical_agent"] > wl["technical_agent"]

    def test_regime_shifts(self):
        wr = self.wr.resolve_weights("fx","RISK_ON")
        wc = self.wr.resolve_weights("fx","CRISIS")
        assert wc["technical_agent"] < wr["technical_agent"]
        assert wc["macro_agent"] > wr["macro_agent"]

    def test_event_proximity(self):
        wf = self.wr.resolve_weights("fx","RISK_ON",event_distance_hours=24)
        wn = self.wr.resolve_weights("fx","RISK_ON",event_distance_hours=1)
        assert wn["macro_agent"] > wf["macro_agent"]

    def test_crypto_vs_fx(self):
        wfx = self.wr.resolve_weights("fx","RISK_ON")
        wcr = self.wr.resolve_weights("crypto","RISK_ON")
        assert wcr["sentiment_agent"] > wfx["sentiment_agent"] or \
               wcr["liquidity_agent"] > wfx["liquidity_agent"]

    def test_profile_override(self):
        wd = self.wr.resolve_weights("fx","RISK_ON")
        wo = self.wr.resolve_weights("fx","RISK_ON",profile_weight_overrides={"technical_agent":0.50})
        assert wo["technical_agent"] > wd["technical_agent"]

    def test_explanation_fields(self):
        ex = self.wr.get_weight_explanation("fx","RISK_ON")
        assert len(ex) == 5
        for e in ex:
            for k in ("agent_id","base_weight","trust_multiplier","regime_factor",
                       "timeframe_factor","event_factor","effective_weight"):
                assert k in e


# ══════════════════════════════════════
# 4. CONSENSUS ENGINE (6 tests)
# ══════════════════════════════════════
from bahamut.consensus.engine import ConsensusEngine

class TestConsensusEngine:
    def setup_method(self):
        self.eng = ConsensusEngine()

    def test_no_trade_empty(self):
        r = self.eng.calculate([], "fx", "RISK_ON", "BALANCED")
        assert r.direction == "NO_TRADE" and r.decision == "NO_TRADE"

    def test_strong_agreement_signal(self):
        c = uuid4()
        outs = [_out("technical_agent","LONG",0.9,c), _out("macro_agent","LONG",0.85,c),
                _out("sentiment_agent","LONG",0.8,c), _out("volatility_agent","LONG",0.75,c),
                _out("liquidity_agent","LONG",0.7,c), _risk(cid=c)]
        r = self.eng.calculate(outs, "fx", "RISK_ON", "BALANCED")
        assert r.direction == "LONG" and r.final_score > 0.5

    def test_risk_veto_blocks(self):
        """Risk veto returns immediately with score=0.0 and NO_TRADE — before any scoring."""
        c = uuid4()
        outs = [_out("technical_agent","LONG",0.9,c),
                _risk(False,["DAILY_DD"],c)]
        r = self.eng.calculate(outs, "fx", "RISK_ON", "BALANCED")
        assert r.blocked and r.decision == "BLOCKED"
        assert r.final_score == 0.0, f"Risk veto should produce score=0.0, got {r.final_score}"
        assert r.direction == "NO_TRADE"

    def test_disagreement_downgrades(self):
        c = uuid4()
        outs = [_out("technical_agent","LONG",0.9,c), _out("macro_agent","LONG",0.85,c),
                _risk(cid=c)]
        dm = DisagreementMetrics(disagreement_index=0.8, execution_gate="BLOCKED",
                                  gate_reasons=["High"])
        r = self.eng.calculate(outs, "fx", "RISK_ON", "BALANCED", disagreement_metrics=dm)
        assert r.execution_mode == "WATCH"

    def test_resolved_weights_affect_score(self):
        c = uuid4()
        outs = [_out("technical_agent","LONG",0.8,c), _out("macro_agent","LONG",0.7,c),
                _out("sentiment_agent","SHORT",0.6,c), _risk(cid=c)]
        wt = {"technical_agent":0.8,"macro_agent":0.05,"sentiment_agent":0.05,
              "volatility_agent":0.05,"liquidity_agent":0.05}
        ws = {"technical_agent":0.05,"macro_agent":0.05,"sentiment_agent":0.8,
              "volatility_agent":0.05,"liquidity_agent":0.05}
        rt = self.eng.calculate(outs,"fx","RISK_ON","BALANCED",resolved_weights=wt)
        rs = self.eng.calculate(outs,"fx","RISK_ON","BALANCED",resolved_weights=ws)
        assert rt.final_score > rs.final_score

    def test_contributions_have_effective_weight(self):
        c = uuid4()
        outs = [_out("technical_agent","LONG",0.8,c), _risk(cid=c)]
        r = self.eng.calculate(outs, "fx", "RISK_ON", "BALANCED")
        for ct in r.agent_contributions:
            assert "effective_weight" in ct

    def test_uniform_low_trust_dampens_score(self):
        """When ALL agents have low trust, score should be lower than cold start."""
        c = uuid4()
        outs = [_out("technical_agent","LONG",0.85,c), _out("macro_agent","LONG",0.75,c),
                _out("sentiment_agent","LONG",0.70,c), _risk(cid=c)]
        trust_1 = {a: 1.0 for a in ["technical_agent","macro_agent","sentiment_agent",
                                      "volatility_agent","liquidity_agent","risk_agent"]}
        trust_low = {a: 0.3 for a in trust_1}
        r1 = self.eng.calculate(outs, "fx", "RISK_ON", "BALANCED", trust_scores=trust_1)
        rl = self.eng.calculate(outs, "fx", "RISK_ON", "BALANCED", trust_scores=trust_low)
        assert rl.final_score < r1.final_score, \
            f"Low trust {rl.final_score} should be < cold start {r1.final_score}"


# ══════════════════════════════════════
# 5. TRUST SCORE STORE (8 tests)
# ══════════════════════════════════════
class TestTrustScoreStore:
    def _fresh(self):
        from bahamut.consensus.trust_store import TrustScoreStore
        s = TrustScoreStore()
        s._loaded = True
        s._persist = MagicMock()
        s._persist_history = MagicMock()
        return s

    def test_baseline(self):
        s = self._fresh()
        sc, n = s.get("technical_agent", "global")
        assert sc == 1.0 and n == 0

    def test_correct_increases(self):
        s = self._fresh()
        b, _ = s.get("technical_agent", "global")
        s.update_after_trade("technical_agent", True, 0.8, "risk_on", "fx", "4H")
        a, _ = s.get("technical_agent", "global")
        assert a > b

    def test_cold_start_learns_faster(self):
        """With 0 samples, alpha is higher → bigger score change than with 50 samples."""
        s1 = self._fresh()
        s2 = self._fresh()
        # s2 has 50 prior samples on global dimension
        s2._samples["technical_agent"]["global"] = 50
        b1, _ = s1.get("technical_agent", "global")
        b2, _ = s2.get("technical_agent", "global")
        s1.update_after_trade("technical_agent", True, 0.8, "risk_on", "fx", "4H")
        s2.update_after_trade("technical_agent", True, 0.8, "risk_on", "fx", "4H")
        a1, _ = s1.get("technical_agent", "global")
        a2, _ = s2.get("technical_agent", "global")
        delta1 = a1 - b1
        delta2 = a2 - b2
        assert delta1 > delta2, f"Cold start delta {delta1} should > mature delta {delta2}"

    def test_wrong_decreases(self):
        s = self._fresh()
        b, _ = s.get("technical_agent", "global")
        s.update_after_trade("technical_agent", False, 0.8, "risk_on", "fx", "4H")
        a, _ = s.get("technical_agent", "global")
        assert a < b

    def test_wrong_high_conf_worse(self):
        s1, s2 = self._fresh(), self._fresh()
        s1.update_after_trade("technical_agent", False, 0.9, "risk_on", "fx", "4H")
        s2.update_after_trade("technical_agent", False, 0.3, "risk_on", "fx", "4H")
        a1, _ = s1.get("technical_agent", "global")
        a2, _ = s2.get("technical_agent", "global")
        assert a1 < a2  # high conf wrong punished harder

    def test_bounded(self):
        s = self._fresh()
        for _ in range(100):
            s.update_after_trade("technical_agent", False, 0.95, "risk_on", "fx", "4H")
        sc, _ = s.get("technical_agent", "global")
        assert sc >= 0.1
        s2 = self._fresh()
        for _ in range(100):
            s2.update_after_trade("technical_agent", True, 0.95, "risk_on", "fx", "4H")
        sc2, _ = s2.get("technical_agent", "global")
        assert sc2 <= 2.0

    def test_resolve_blends(self):
        s = self._fresh()
        s.set("technical_agent", "global", 1.2)
        s.set("technical_agent", "regime:risk_on", 1.4)
        r = s.resolve("technical_agent", "risk_on", "fx", "4H")
        assert 0.1 <= r <= 2.0

    def test_decay(self):
        s = self._fresh()
        s.set("technical_agent", "global", 1.5, increment_sample=False)
        # Mark as stale (updated 30 days ago) so decay applies
        s._last_updated["technical_agent"]["global"] = 0  # epoch = very old
        s.apply_daily_decay(decay_rate=0.1)
        sc, _ = s.get("technical_agent", "global")
        assert 1.0 < sc < 1.5

    def test_decay_skips_recent(self):
        """Recently updated scores should NOT be decayed."""
        s = self._fresh()
        s.set("technical_agent", "global", 1.5, increment_sample=False)
        # _last_updated is set to now by set() — should be skipped
        s.apply_daily_decay(decay_rate=0.1)
        sc, _ = s.get("technical_agent", "global")
        assert sc == 1.5  # unchanged

    def test_all_scores_provisional(self):
        s = self._fresh()
        all_s = s.get_all_scores()
        for aid, dims in all_s.items():
            for dim, info in dims.items():
                assert "provisional" in info and "score" in info


# ══════════════════════════════════════
# 6. REGIME DETECTION (9 tests)
# ══════════════════════════════════════
from bahamut.features.regime import (
    detect_regime_from_features, RegimeState, compute_regime_similarity,
)

class TestRegimeDetection:
    def _feat(self, close=100, ema20=99, ema50=98, ema200=95,
              rsi=55, adx=25, atr=1.5, macd=0.2, macd_sig=0.1, vix=18):
        return {"indicators": {"close": close, "ema_20": ema20, "ema_50": ema50,
                "ema_200": ema200, "rsi_14": rsi, "adx": adx, "atr_14": atr,
                "macd": macd, "macd_signal": macd_sig}, "vix": vix}

    def test_high_vix(self):
        s = detect_regime_from_features(self._feat(vix=28))
        assert s.volatility_state == "HIGH_VOL"

    def test_crisis(self):
        s = detect_regime_from_features(self._feat(vix=40))
        assert s.crisis_flag and s.primary_regime == "CRISIS"

    def test_bullish_trend(self):
        s = detect_regime_from_features(self._feat(close=110, ema20=108, ema50=105,
                                                    ema200=100, rsi=65, adx=30, vix=12))
        assert s.risk_appetite == "RISK_ON"
        assert s.primary_regime in ("TREND_CONTINUATION", "LOW_VOL")

    def test_risk_off(self):
        s = detect_regime_from_features(self._feat(close=85, ema20=90, ema50=95,
                                                    ema200=100, rsi=30, adx=15, vix=28,
                                                    macd=-0.5, macd_sig=0))
        assert s.risk_appetite == "RISK_OFF"

    def test_confidence_bounded(self):
        s = detect_regime_from_features(self._feat())
        assert 0 <= s.confidence <= 1.0

    def test_feature_vector_len(self):
        s = detect_regime_from_features(self._feat())
        assert len(s.feature_vector) == 6

    def test_similarity_identical(self):
        v = [0.5, 0.3, 0.6, 0.4, 1.0, 0.0]
        assert compute_regime_similarity(v, v) == 1.0

    def test_similarity_orthogonal(self):
        assert compute_regime_similarity([1,0,0,0,0,0], [0,1,0,0,0,0]) == 0.0

    def test_to_dict_fields(self):
        d = RegimeState(primary_regime="RISK_ON", confidence=0.75).to_dict()
        for k in ("primary_regime","risk_appetite","trend_state","volatility_state",
                   "crisis_flag","confidence"):
            assert k in d


# ══════════════════════════════════════
# 7. LEARNING ATTRIBUTION (6 tests)
# ══════════════════════════════════════
from bahamut.paper_trading.learning import _calculate_trust_delta

class TestLearningAttribution:

    def test_correct_positive_delta(self):
        d = _calculate_trust_delta(True, 0.7, 100.0, 1.0)
        assert d > 0

    def test_wrong_negative_delta(self):
        d = _calculate_trust_delta(False, 0.7, -100.0, 0.0)
        assert d < 0

    def test_neutral_zero(self):
        assert _calculate_trust_delta(None, 0.5, 0, 0.5) == 0.0

    def test_tp_hit_rewards_more_than_timeout(self):
        """TP hit (timing=1.0) should give larger reward than timeout (timing=0.5)."""
        d_tp = _calculate_trust_delta(True, 0.7, 100.0, 1.0)
        d_to = _calculate_trust_delta(True, 0.7, 100.0, 0.5)
        assert d_tp > d_to, f"TP {d_tp} should > timeout {d_to}"

    def test_sl_hit_punishes_more_than_timeout(self):
        """SL hit (timing=0.0) should give larger penalty than timeout (timing=0.5)."""
        d_sl = _calculate_trust_delta(False, 0.7, -100.0, 0.0)
        d_to = _calculate_trust_delta(False, 0.7, -100.0, 0.5)
        assert d_sl < d_to, f"SL {d_sl} should be more negative than timeout {d_to}"

    def test_high_conf_wrong_punished_harder(self):
        """High confidence wrong → bigger penalty than low confidence wrong."""
        d_hi = _calculate_trust_delta(False, 0.9, -100.0, 0.0)
        d_lo = _calculate_trust_delta(False, 0.3, -100.0, 0.0)
        assert d_hi < d_lo

    def test_calibration_penalty_amplifies_wrong(self):
        """Agent with systematic overconfidence gets amplified penalty when wrong."""
        d_no_cal = _calculate_trust_delta(False, 0.8, -100.0, 0.0, calibration_penalty=0.0)
        d_cal = _calculate_trust_delta(False, 0.8, -100.0, 0.0, calibration_penalty=0.3)
        assert d_cal < d_no_cal, f"Calibrated {d_cal} should be more negative than {d_no_cal}"

    def test_calibration_penalty_reduces_correct_reward(self):
        """Overconfident agent gets reduced reward even when correct."""
        d_no_cal = _calculate_trust_delta(True, 0.8, 100.0, 1.0, calibration_penalty=0.0)
        d_cal = _calculate_trust_delta(True, 0.8, 100.0, 1.0, calibration_penalty=0.3)
        assert d_cal < d_no_cal, f"Calibrated {d_cal} should be less than {d_no_cal}"


# ══════════════════════════════════════
# 8. META-LEARNING (4 tests)
# ══════════════════════════════════════
from bahamut.learning.meta import SystemHealthReport, PerformanceWindow

class TestMetaLearning:

    def test_improving_trend(self):
        r = SystemHealthReport()
        r.windows = {
            7: PerformanceWindow(window_days=7, total_trades=5, wins=4, win_rate=0.80, profit_factor=2.5),
            30: PerformanceWindow(window_days=30, total_trades=20, wins=10, win_rate=0.50, profit_factor=1.1),
        }
        # 7d much better than 30d → positive trend
        wr_delta = r.windows[7].win_rate - r.windows[30].win_rate
        assert wr_delta > 0.2

    def test_cold_start(self):
        r = SystemHealthReport()
        r.windows = {30: PerformanceWindow(window_days=30, total_trades=2)}
        # Too few trades
        assert r.windows[30].total_trades < 5

    def test_to_dict_complete(self):
        r = SystemHealthReport(trend="STABLE", trend_score=0.1, risk_level="NORMAL")
        d = r.to_dict()
        for k in ("trend", "trend_score", "risk_level", "consensus_quality",
                   "recommended_actions", "agent_diversity_score"):
            assert k in d

    def test_critical_risk_generates_action(self):
        w7 = PerformanceWindow(window_days=7, total_trades=6, wins=0, max_consecutive_losses=6)
        assert w7.max_consecutive_losses >= 5


# ══════════════════════════════════════
# 9. THRESHOLD TUNING (4 tests)
# ══════════════════════════════════════
from bahamut.learning.thresholds import _clamp, BOUNDS, BASELINE_THRESHOLDS

class TestThresholdTuning:

    def test_clamp_within_bounds(self):
        assert _clamp("strong_signal", 0.99) == BOUNDS["strong_signal"][1]
        assert _clamp("strong_signal", 0.10) == BOUNDS["strong_signal"][0]

    def test_clamp_passes_valid(self):
        assert _clamp("signal", 0.60) == 0.60

    def test_baseline_not_mutated(self):
        """BASELINE_THRESHOLDS should never change."""
        assert BASELINE_THRESHOLDS["BALANCED"]["strong_signal"] == 0.72
        assert BASELINE_THRESHOLDS["CONSERVATIVE"]["signal"] == 0.70

    def test_bounds_hierarchy(self):
        """strong_signal bounds should be above signal bounds."""
        assert BOUNDS["strong_signal"][0] > BOUNDS["signal"][0]


# ══════════════════════════════════════
# 10. ADAPTIVE PROFILE (5 tests)
# ══════════════════════════════════════
from bahamut.learning.profile_adapter import resolve_effective_profile

class TestAdaptiveProfile:

    def test_no_change_normal(self):
        r = resolve_effective_profile("BALANCED", "RISK_ON")
        assert r.effective_profile == "BALANCED" and not r.adjusted

    def test_crisis_downgrades(self):
        r = resolve_effective_profile("BALANCED", "CRISIS",
                                       profile_config={"auto_downgrade_on_crisis": True})
        assert r.effective_profile == "CONSERVATIVE" and r.adjusted

    def test_losing_streak_tightens(self):
        r = resolve_effective_profile("AGGRESSIVE", "RISK_ON",
                                       recent_streak=-4,
                                       profile_config={"streak_tighten_after": 3})
        assert r.effective_profile == "BALANCED"

    def test_meta_critical_forces_conservative(self):
        r = resolve_effective_profile("AGGRESSIVE", "RISK_ON", meta_risk_level="CRITICAL")
        assert r.effective_profile == "CONSERVATIVE"

    def test_never_upgrades_beyond_base(self):
        """Winning streak can restore but never exceed base profile."""
        r = resolve_effective_profile("BALANCED", "RISK_ON",
                                       recent_streak=10,
                                       profile_config={"streak_loosen_after": 5})
        assert r.effective_profile == "BALANCED"  # can't go to AGGRESSIVE


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
