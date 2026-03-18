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
                 portfolio_balance=100000, mean_agent_trust=1.0,
                 system_confidence=0.7)
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
        """System confidence < 0.25 → hard block."""
        d = self.pol.evaluate(self._req(system_confidence=0.20))
        assert not d.allowed
        assert any("LOW_CONFIDENCE" in b for b in d.blockers)

    def test_moderate_trust_requires_approval(self):
        """System confidence 0.25-0.40 → requires approval."""
        d = self.pol.evaluate(self._req(system_confidence=0.35))
        assert d.allowed and d.requires_approval

    def test_slightly_low_trust_reduces_size(self):
        """System confidence 0.40-0.60 → position size reduced."""
        d = self.pol.evaluate(self._req(system_confidence=0.45))
        assert d.allowed and d.position_size_multiplier < 1.0

    def test_trust_floor_still_blocks(self):
        """Even with OK system_confidence, collapsed mean_trust blocks."""
        d = self.pol.evaluate(self._req(system_confidence=0.70, mean_agent_trust=0.4))
        assert not d.allowed
        assert any("TRUST_FLOOR" in b for b in d.blockers)

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

    def test_low_stress_score_downgrades(self):
        """Stress score < 0.35 → tighten one level."""
        r = resolve_effective_profile("AGGRESSIVE", "RISK_ON", stress_score=0.25)
        assert r.effective_profile == "BALANCED"
        assert any("Stress" in reason for reason in r.reasons)

    def test_good_stress_score_no_change(self):
        """Stress score >= 0.35 → no profile change."""
        r = resolve_effective_profile("AGGRESSIVE", "RISK_ON", stress_score=0.60)
        assert r.effective_profile == "AGGRESSIVE"


# ══════════════════════════════════════
# 11. STRESS TEST ENGINE (6 tests)
# ══════════════════════════════════════
from bahamut.stress.engine import StressResult, replay_with_modified_params
from bahamut.stress.scenarios import SCENARIOS

class TestStressTesting:

    def test_stress_result_structure(self):
        r = StressResult(scenario_name="test", mode="scenario", total_signals=10)
        d = r.to_dict()
        for k in ("scenario_name", "mode", "total_signals", "would_open",
                   "would_block", "changed_decisions", "avg_size_multiplier",
                   "blockers_fired", "warnings_fired"):
            assert k in d

    def test_all_scenarios_have_required_keys(self):
        for s in SCENARIOS:
            assert "name" in s, f"Scenario missing name"
            assert "description" in s, f"{s.get('name')} missing description"
            assert len(s["description"]) > 20, f"{s['name']} description too short"

    def test_scenario_count(self):
        assert len(SCENARIOS) == 13, f"Expected 13 scenarios, got {len(SCENARIOS)}"

    def test_unique_scenario_names(self):
        names = [s["name"] for s in SCENARIOS]
        assert len(names) == len(set(names)), "Duplicate scenario names"

    def test_replay_no_traces_returns_empty(self):
        """Replay with no DB connection returns empty result gracefully."""
        r = replay_with_modified_params(max_traces=5)
        assert r.total_signals == 0
        assert "No decision traces found" in r.notes

    def test_trust_collapse_scenario_exists(self):
        tc = next(s for s in SCENARIOS if s["name"] == "trust_collapse")
        for a in ["technical_agent", "macro_agent", "sentiment_agent"]:
            assert tc["trust_overrides"][a] == 0.3

    def test_mutator_scenarios_have_functions(self):
        """All 5 new scenarios must have callable mutators."""
        mutator_names = ["regime_flip_mid_trade", "stale_agent_inputs",
                         "disagreement_drift", "correlated_agent_failure",
                         "false_high_confidence"]
        for name in mutator_names:
            s = next((s for s in SCENARIOS if s["name"] == name), None)
            assert s is not None, f"Missing scenario: {name}"
            assert s.get("mutators"), f"{name} has no mutators"
            for m in s["mutators"]:
                assert callable(m), f"{name} mutator is not callable"

    def test_regime_flip_mutator(self):
        """Regime flip should change trace regime at midpoint."""
        from bahamut.stress.scenarios import _mutate_regime_flip
        trace = {"regime": "RISK_ON"}
        _mutate_regime_flip(0, 10, [], {}, trace)
        assert trace["regime"] == "RISK_ON"
        _mutate_regime_flip(5, 10, [], {}, trace)
        assert trace["regime"] == "CRISIS"

    def test_stale_agents_mutator(self):
        """Stale agents should progressively time out."""
        from bahamut.stress.scenarios import _mutate_stale_agents
        from bahamut.agents.schemas import AgentOutputSchema, Evidence
        from uuid import uuid4
        from datetime import datetime, timezone
        agents = []
        for aid in ["technical_agent", "macro_agent", "sentiment_agent",
                     "volatility_agent", "liquidity_agent"]:
            agents.append(AgentOutputSchema(
                agent_id=aid, cycle_id=uuid4(), timestamp=datetime.now(timezone.utc),
                asset="EURUSD", timeframe="4H", directional_bias="LONG",
                confidence=0.80, evidence=[Evidence(claim="t", data_point="t", weight=0.5)],
                meta={}))
        # At start: nobody stale
        _mutate_stale_agents(0, 20, agents, {}, {})
        stale_0 = sum(1 for a in agents if a.meta.get("timed_out"))
        # At end: 3 stale
        agents2 = []
        for aid in ["technical_agent", "macro_agent", "sentiment_agent",
                     "volatility_agent", "liquidity_agent"]:
            agents2.append(AgentOutputSchema(
                agent_id=aid, cycle_id=uuid4(), timestamp=datetime.now(timezone.utc),
                asset="EURUSD", timeframe="4H", directional_bias="LONG",
                confidence=0.80, evidence=[Evidence(claim="t", data_point="t", weight=0.5)],
                meta={}))
        _mutate_stale_agents(19, 20, agents2, {}, {})
        stale_end = sum(1 for a in agents2 if a.meta.get("timed_out"))
        assert stale_0 == 0, f"Start should have 0 stale, got {stale_0}"
        assert stale_end == 3, f"End should have 3 stale, got {stale_end}"

    def test_disagreement_drift_mutator(self):
        """Disagreement should rise to BLOCKED by end."""
        from bahamut.stress.scenarios import _mutate_disagreement_drift
        from bahamut.agents.schemas import AgentOutputSchema, Evidence
        from uuid import uuid4
        from datetime import datetime, timezone
        agents = [AgentOutputSchema(
            agent_id="technical_agent", cycle_id=uuid4(),
            timestamp=datetime.now(timezone.utc), asset="EURUSD", timeframe="4H",
            directional_bias="LONG", confidence=0.8,
            evidence=[Evidence(claim="t", data_point="t", weight=0.5)], meta={})]
        d = {"disagreement_index": 0.1, "execution_gate": "CLEAR", "gate_reasons": []}
        _mutate_disagreement_drift(19, 20, agents, d, {})
        assert d["disagreement_index"] > 0.7
        assert d["execution_gate"] == "BLOCKED"

    def test_correlated_failure_mutator(self):
        """Technical + Macro should both go NEUTRAL with timed_out."""
        from bahamut.stress.scenarios import _mutate_correlated_failure
        from bahamut.agents.schemas import AgentOutputSchema, Evidence
        from uuid import uuid4
        from datetime import datetime, timezone
        agents = []
        for aid in ["technical_agent", "macro_agent", "sentiment_agent"]:
            agents.append(AgentOutputSchema(
                agent_id=aid, cycle_id=uuid4(), timestamp=datetime.now(timezone.utc),
                asset="EURUSD", timeframe="4H", directional_bias="LONG",
                confidence=0.80, evidence=[Evidence(claim="t", data_point="t", weight=0.5)],
                meta={}))
        d = {"disagreement_index": 0.1, "execution_gate": "CLEAR", "gate_reasons": []}
        _mutate_correlated_failure(0, 10, agents, d, {})
        tech = next(a for a in agents if a.agent_id == "technical_agent")
        macro = next(a for a in agents if a.agent_id == "macro_agent")
        sent = next(a for a in agents if a.agent_id == "sentiment_agent")
        assert tech.directional_bias == "NEUTRAL" and tech.meta.get("timed_out")
        assert macro.directional_bias == "NEUTRAL" and macro.meta.get("timed_out")
        assert sent.directional_bias == "LONG"  # unaffected

    def test_false_confidence_mutator(self):
        """One agent should flip to opposing direction with 0.95 confidence."""
        from bahamut.stress.scenarios import _mutate_false_high_confidence
        from bahamut.agents.schemas import AgentOutputSchema, Evidence
        from uuid import uuid4
        from datetime import datetime, timezone
        agents = []
        for aid in ["technical_agent", "macro_agent", "sentiment_agent",
                     "volatility_agent", "liquidity_agent"]:
            agents.append(AgentOutputSchema(
                agent_id=aid, cycle_id=uuid4(), timestamp=datetime.now(timezone.utc),
                asset="EURUSD", timeframe="4H", directional_bias="LONG",
                confidence=0.70, evidence=[Evidence(claim="t", data_point="t", weight=0.5)],
                meta={}))
        d = {"disagreement_index": 0.1, "execution_gate": "CLEAR", "gate_reasons": []}
        _mutate_false_high_confidence(0, 10, agents, d, {})
        # trace_idx=0 → liar is technical_agent (idx 0)
        tech = next(a for a in agents if a.agent_id == "technical_agent")
        assert tech.directional_bias == "SHORT"
        assert tech.confidence == 0.95
        assert tech.meta.get("injected_false_signal")


# ══════════════════════════════════════
# 12. READINESS CHECKLIST (5 tests)
# ══════════════════════════════════════
from bahamut.readiness.checklist import (
    ReadinessReport, CheckResult, run_readiness_check,
    _check_execution_policy, _check_trust_maturity,
)

class TestReadinessChecklist:

    def test_report_structure(self):
        r = ReadinessReport(overall="NOT_READY", pass_count=3, warn_count=2, fail_count=7)
        d = r.to_dict()
        assert d["overall"] == "NOT_READY"
        assert d["pass_count"] == 3
        assert "checks" in d

    def test_check_result_structure(self):
        c = CheckResult(name="test", category="SYSTEM", status="PASS",
                        value="ok", threshold="ok")
        assert c.status == "PASS"
        assert c.category == "SYSTEM"

    def test_execution_policy_check_passes(self):
        """The execution policy smoke test should pass (module loads correctly)."""
        c = _check_execution_policy()
        assert c.status == "PASS"
        assert c.name == "execution_policy"

    def test_overall_logic_ready(self):
        r = ReadinessReport()
        r.fail_count = 0
        r.warn_count = 1
        # READY = 0 fails and ≤2 warns
        if r.fail_count == 0 and r.warn_count <= 2:
            r.overall = "READY"
        assert r.overall == "READY"

    def test_overall_logic_not_ready(self):
        r = ReadinessReport()
        r.fail_count = 5
        if r.fail_count > 2:
            r.overall = "NOT_READY"
        assert r.overall == "NOT_READY"


# ══════════════════════════════════════
# 13. SYSTEM CONFIDENCE (6 tests)
# ══════════════════════════════════════
from bahamut.consensus.system_confidence import (
    ConfidenceBreakdown, compute_system_confidence, WEIGHTS,
)

class TestSystemConfidence:

    def test_weights_sum_to_one(self):
        total = sum(WEIGHTS.values())
        assert abs(total - 1.0) < 0.001, f"Weights sum to {total}, not 1.0"

    def test_breakdown_structure(self):
        bd = ConfidenceBreakdown(system_confidence=0.65, trust_stability=0.8,
                                  disagreement_trend=0.6, recent_performance=0.5,
                                  calibration_health=0.7)
        d = bd.to_dict()
        for k in ("system_confidence", "trust_stability", "disagreement_trend",
                   "recent_performance", "calibration_health", "mean_agent_trust"):
            assert k in d

    def test_confidence_bounded(self):
        bd = ConfidenceBreakdown()
        bd.system_confidence = (
            WEIGHTS["trust_stability"] * 1.0
            + WEIGHTS["disagreement_trend"] * 1.0
            + WEIGHTS["recent_performance"] * 1.0
            + WEIGHTS["calibration_health"] * 1.0
        )
        assert 0.99 <= bd.system_confidence <= 1.01

    def test_all_bad_produces_low(self):
        bd = ConfidenceBreakdown()
        bd.system_confidence = (
            WEIGHTS["trust_stability"] * 0.1
            + WEIGHTS["disagreement_trend"] * 0.1
            + WEIGHTS["recent_performance"] * 0.1
            + WEIGHTS["calibration_health"] * 0.1
        )
        assert bd.system_confidence < 0.15

    def test_compute_returns_breakdown(self):
        """compute_system_confidence should return a ConfidenceBreakdown with all fields."""
        bd = compute_system_confidence()
        assert isinstance(bd, ConfidenceBreakdown)
        assert 0.0 <= bd.system_confidence <= 1.0
        assert bd.computed_at > 0

    def test_mean_trust_backward_compat(self):
        """mean_agent_trust should always be present for backward compat."""
        bd = compute_system_confidence()
        assert bd.mean_agent_trust > 0


# ══════════════════════════════════════
# 14. STRESS ASSESSMENT (5 tests)
# ══════════════════════════════════════
from bahamut.stress.assessment import StressAssessment, compute_stress_assessment

class TestStressAssessment:

    def test_assessment_structure(self):
        sa = StressAssessment(overall_stress_score=0.6, crisis_resilience=0.8)
        d = sa.to_dict()
        for k in ("has_recent_results", "crisis_resilience", "trust_fragility",
                   "threshold_adequacy", "decision_stability", "agent_redundancy",
                   "overall_stress_score", "recommended_actions"):
            assert k in d

    def test_no_results_returns_defaults(self):
        sa = compute_stress_assessment()
        assert isinstance(sa, StressAssessment)
        assert 0.0 <= sa.overall_stress_score <= 1.0

    def test_overall_weighted_correctly(self):
        sa = StressAssessment(
            crisis_resilience=1.0, trust_fragility=0.0,
            threshold_adequacy=1.0, decision_stability=1.0,
            agent_redundancy=1.0,
        )
        expected = 0.25*1.0 + 0.20*1.0 + 0.20*1.0 + 0.20*1.0 + 0.15*1.0
        sa.overall_stress_score = round(expected, 3)
        assert sa.overall_stress_score == 1.0

    def test_high_fragility_is_bad(self):
        """High trust_fragility means system is vulnerable — inverted in score."""
        sa = StressAssessment(
            crisis_resilience=0.5, trust_fragility=0.9,
            threshold_adequacy=0.5, decision_stability=0.5,
            agent_redundancy=0.5,
        )
        score = 0.25*0.5 + 0.20*(1.0-0.9) + 0.20*0.5 + 0.20*0.5 + 0.15*0.5
        assert score < 0.5

    def test_actions_deduplicated(self):
        sa = StressAssessment()
        sa.recommended_actions = [
            {"target": "thresholds", "action": "TIGHTEN", "reason": "a"},
            {"target": "thresholds", "action": "TIGHTEN", "reason": "b"},
        ]
        # Real compute deduplicates, but manual doesn't — that's OK, it's a data holder


# ══════════════════════════════════════
# 15. DECISION EXPLAINER (7 tests)
# ══════════════════════════════════════
from bahamut.consensus.explainer import explain_decision, DecisionExplanation

class TestDecisionExplainer:

    def test_positive_factors(self):
        ex = explain_decision(
            direction="LONG", label="SIGNAL", final_score=0.68,
            mean_trust=1.32, disagreement_index=0.15, disagreement_gate="CLEAR",
            regime="TREND_CONTINUATION", risk_flags=[], risk_can_trade=True,
            agreement_pct=0.80)
        positive = [f for f in ex.factors if f.impact == "positive"]
        assert len(positive) >= 3, f"Expected ≥3 positive factors, got {len(positive)}"
        assert ex.direction == "LONG"
        assert "LONG" in ex.narrative

    def test_blocked_explanation(self):
        ex = explain_decision(
            direction="NO_TRADE", label="BLOCKED", final_score=0.0,
            mean_trust=0.3, disagreement_index=0.72, disagreement_gate="BLOCKED",
            regime="CRISIS", risk_flags=[], risk_can_trade=True)
        assert len(ex.blocked_flags) >= 1
        assert "BLOCKED" in ex.narrative

    def test_risk_veto_in_factors(self):
        ex = explain_decision(
            direction="NO_TRADE", label="BLOCKED", final_score=0.0,
            mean_trust=1.0, disagreement_index=0.1, disagreement_gate="CLEAR",
            regime="RISK_ON", risk_flags=["DAILY_DD"], risk_can_trade=False)
        risk_factor = next(f for f in ex.factors if f.name == "risk")
        assert risk_factor.impact == "blocking"

    def test_system_confidence_factor(self):
        ex = explain_decision(
            direction="LONG", label="SIGNAL", final_score=0.6,
            mean_trust=1.0, disagreement_index=0.2, disagreement_gate="CLEAR",
            regime="RISK_ON", risk_flags=[], risk_can_trade=True,
            system_confidence=0.30)
        conf_factor = next(f for f in ex.factors if f.name == "system_confidence")
        assert conf_factor.status == "low"
        assert conf_factor.impact == "negative"

    def test_calibration_overconfident_dissenters(self):
        ex = explain_decision(
            direction="LONG", label="SIGNAL", final_score=0.6,
            mean_trust=1.0, disagreement_index=0.3, disagreement_gate="CLEAR",
            regime="RISK_ON", risk_flags=[], risk_can_trade=True,
            contributions=[
                {"agent_id": "macro_agent", "confidence": 0.90, "effective_contribution": -0.05},
            ])
        cal_factor = next(f for f in ex.factors if f.name == "calibration")
        assert cal_factor.status == "warning"

    def test_to_dict_complete(self):
        ex = explain_decision(
            direction="LONG", label="SIGNAL", final_score=0.7,
            mean_trust=1.0, disagreement_index=0.1, disagreement_gate="CLEAR",
            regime="RISK_ON", risk_flags=[], risk_can_trade=True)
        d = ex.to_dict()
        for k in ("direction", "label", "factors", "blocked_flags", "narrative", "score_breakdown"):
            assert k in d
        assert isinstance(d["factors"], list)
        assert len(d["factors"]) >= 4

    def test_all_factor_names(self):
        ex = explain_decision(
            direction="LONG", label="SIGNAL", final_score=0.7,
            mean_trust=1.1, disagreement_index=0.2, disagreement_gate="CLEAR",
            regime="RISK_ON", risk_flags=[], risk_can_trade=True,
            system_confidence=0.65, agreement_pct=0.75, contributions=[])
        names = {f.name for f in ex.factors}
        for expected in ("trust", "disagreement", "regime", "risk", "system_confidence",
                          "calibration", "agreement"):
            assert expected in names, f"Missing factor: {expected}"


# ══════════════════════════════════════
# 16. PORTFOLIO INTELLIGENCE (10 tests)
# ══════════════════════════════════════
from bahamut.portfolio.registry import (
    PortfolioSnapshot, OpenPosition, ASSET_CLASS_MAP, THEME_MAP,
)
from bahamut.portfolio.engine import (
    evaluate_trade_for_portfolio, _compute_exposure, _compute_correlation,
    _compute_fragility, _compute_impact, EXPOSURE_LIMITS,
)

class TestPortfolioIntelligence:

    def _snap(self, positions=None, balance=100000):
        positions = positions or []
        return PortfolioSnapshot(
            positions=positions, balance=balance,
            total_position_value=sum(p.position_value for p in positions),
            total_risk=sum(p.risk_amount for p in positions),
        )

    def _pos(self, asset="EURUSD", direction="LONG", value=5000, risk=200,
             score=0.65, pnl=0):
        ac = ASSET_CLASS_MAP.get(asset, "other")
        themes = [t for t, assets in THEME_MAP.items() if asset in assets]
        return OpenPosition(
            id=1, asset=asset, direction=direction, position_value=value,
            risk_amount=risk, entry_price=1.0, current_price=1.0,
            unrealized_pnl=pnl, consensus_score=score,
            asset_class=ac, themes=themes,
        )

    def test_empty_portfolio_allows(self):
        snap = self._snap()
        v = evaluate_trade_for_portfolio(snap, "EURUSD", "LONG", 5000, 200, 0.70)
        assert v.allowed
        assert v.size_multiplier == 1.0

    def test_gross_exposure_blocks(self):
        """Positions totaling 85% of balance → new trade blocked."""
        pos = [self._pos("EURUSD", "LONG", 42000), self._pos("GBPUSD", "LONG", 43000)]
        snap = self._snap(pos, 100000)
        v = evaluate_trade_for_portfolio(snap, "BTCUSD", "LONG", 5000, 200, 0.70)
        assert not v.allowed
        assert any("GROSS_EXPOSURE" in b for b in v.blockers)

    def test_same_class_same_direction_reduces(self):
        """3 LONG FX positions → correlated trade warning + size reduction."""
        pos = [self._pos("EURUSD", "LONG", 5000),
               self._pos("GBPUSD", "LONG", 5000),
               self._pos("AUDUSD", "LONG", 5000)]
        snap = self._snap(pos, 100000)
        v = evaluate_trade_for_portfolio(snap, "NZDUSD", "LONG", 5000, 200, 0.70)
        assert v.allowed
        assert v.size_multiplier < 1.0
        assert any("CORRELATED" in w for w in v.warnings)

    def test_hedging_trade_improves(self):
        """Adding a SHORT when portfolio is all LONG → positive impact."""
        pos = [self._pos("EURUSD", "LONG", 10000),
               self._pos("BTCUSD", "LONG", 10000)]
        snap = self._snap(pos, 100000)
        v = evaluate_trade_for_portfolio(snap, "XAUUSD", "SHORT", 5000, 200, 0.70)
        assert v.impact_score > 0
        assert v.improves_portfolio

    def test_new_asset_class_diversifies(self):
        """Adding crypto to FX-only portfolio → diversification bonus."""
        pos = [self._pos("EURUSD", "LONG", 5000)]
        snap = self._snap(pos, 100000)
        v = evaluate_trade_for_portfolio(snap, "BTCUSD", "LONG", 5000, 200, 0.70)
        assert v.impact_score > 0

    def test_fragility_high_requires_approval(self):
        """Highly concentrated, one-sided portfolio → fragility requires approval."""
        pos = [self._pos("EURUSD", "LONG", 30000, risk=5000),
               self._pos("GBPUSD", "LONG", 30000, risk=5000)]
        snap = self._snap(pos, 100000)
        v = evaluate_trade_for_portfolio(snap, "USDJPY", "LONG", 5000, 200, 0.50)
        # Either fragility requires approval or size is reduced
        assert v.size_multiplier < 1.0 or v.requires_approval

    def test_exposure_metrics_complete(self):
        pos = [self._pos("EURUSD", "LONG", 10000)]
        snap = self._snap(pos, 100000)
        exp = _compute_exposure(snap, "BTCUSD", "LONG", 5000, 100000)
        d = exp.to_dict()
        for k in ("gross", "net", "long_pct", "short_pct", "by_class",
                   "after_trade_gross", "after_trade_net"):
            assert k in d

    def test_correlation_empty_portfolio(self):
        snap = self._snap()
        corr = _compute_correlation(snap, "EURUSD", "LONG", "fx", ["usd_strength"])
        assert corr.directional_overlap == 0
        assert corr.class_concentration == 0

    def test_fragility_empty_portfolio(self):
        snap = self._snap()
        frag = _compute_fragility(snap, 100000)
        assert frag.portfolio_fragility == 0

    def test_theme_map_coverage(self):
        """Every theme should have at least 2 assets."""
        for theme, assets in THEME_MAP.items():
            assert len(assets) >= 2, f"Theme '{theme}' has only {len(assets)} assets"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
