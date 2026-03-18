"""
Bahamut.AI Trust Score Store — write-through cache (memory + PostgreSQL).
Reads from memory (fast), writes to both memory + DB on every update.
"""
import structlog

logger = structlog.get_logger()

AGENT_IDS = ["macro_agent", "volatility_agent", "liquidity_agent", "sentiment_agent", "technical_agent"]
ALL_AGENT_IDS = AGENT_IDS + ["risk_agent"]
INITIAL_DIMENSIONS = [
    "global", "regime:risk_on", "regime:risk_off", "regime:high_vol",
    "regime:low_vol", "regime:crisis", "regime:trend_continuation",
    "asset:fx", "asset:indices", "asset:commodities", "asset:crypto", "asset:bonds",
    "tf:1H", "tf:4H", "tf:1D",
]
TRUST_MIN, TRUST_MAX, TRUST_BASELINE = 0.1, 2.0, 1.0
MIN_SAMPLES = 10


class TrustScoreStore:
    def __init__(self):
        self._scores: dict[str, dict[str, float]] = {}
        self._samples: dict[str, dict[str, int]] = {}
        self._last_updated: dict[str, dict[str, float]] = {}  # epoch timestamps
        self._loaded = False
        self._init_defaults()

    def _init_defaults(self):
        for aid in ALL_AGENT_IDS:
            self._scores.setdefault(aid, {})
            self._samples.setdefault(aid, {})
            for dim in INITIAL_DIMENSIONS:
                self._scores[aid].setdefault(dim, TRUST_BASELINE)
                self._samples[aid].setdefault(dim, 0)

    def load_from_db(self):
        try:
            from bahamut.database import sync_engine
            from sqlalchemy import text
            with sync_engine.connect() as conn:
                conn.execute(text("""CREATE TABLE IF NOT EXISTS trust_scores_live (
                    id SERIAL PRIMARY KEY, agent_id VARCHAR(50) NOT NULL,
                    dimension VARCHAR(100) NOT NULL, score FLOAT DEFAULT 1.0,
                    sample_count INTEGER DEFAULT 0, updated_at TIMESTAMP DEFAULT NOW(),
                    UNIQUE(agent_id, dimension))"""))
                conn.commit()
                for row in conn.execute(text("SELECT agent_id, dimension, score, sample_count FROM trust_scores_live")).fetchall():
                    aid, dim, sc, n = row
                    self._scores.setdefault(aid, {})[dim] = float(sc)
                    self._samples.setdefault(aid, {})[dim] = int(n)
            self._loaded = True
            self._init_defaults()
            logger.info("trust_loaded_from_db")
        except Exception as e:
            logger.warning("trust_db_load_failed", error=str(e))
            self._init_defaults()

    def _persist(self, aid, dim, score, n):
        try:
            from bahamut.database import sync_engine
            from sqlalchemy import text
            with sync_engine.connect() as conn:
                conn.execute(text("""INSERT INTO trust_scores_live (agent_id, dimension, score, sample_count, updated_at)
                    VALUES (:a, :d, :s, :n, NOW()) ON CONFLICT (agent_id, dimension)
                    DO UPDATE SET score = :s, sample_count = :n, updated_at = NOW()"""),
                    {"a": aid, "d": dim, "s": round(score, 4), "n": n})
                conn.commit()
        except Exception as e:
            logger.warning("trust_persist_failed", agent=aid, error=str(e))

    def _persist_history(self, aid, dim, old, new, reason, trade_id=None, alpha=None):
        try:
            from bahamut.database import sync_engine
            from sqlalchemy import text
            with sync_engine.connect() as conn:
                conn.execute(text("""CREATE TABLE IF NOT EXISTS trust_score_history_live (
                    id SERIAL PRIMARY KEY, agent_id VARCHAR(50), dimension VARCHAR(100),
                    old_score FLOAT, new_score FLOAT, change_reason VARCHAR(50),
                    trade_id VARCHAR(100), alpha_used FLOAT, created_at TIMESTAMP DEFAULT NOW())"""))
                conn.execute(text("""INSERT INTO trust_score_history_live
                    (agent_id, dimension, old_score, new_score, change_reason, trade_id, alpha_used)
                    VALUES (:a, :d, :o, :n, :r, :t, :al)"""),
                    {"a": aid, "d": dim, "o": round(old, 4), "n": round(new, 4),
                     "r": reason, "t": trade_id, "al": alpha})
                conn.commit()
        except Exception as e:
            logger.warning("trust_history_failed", error=str(e))

    def get(self, agent_id, dimension):
        if not self._loaded: self.load_from_db()
        return self._scores.get(agent_id, {}).get(dimension, TRUST_BASELINE), \
               self._samples.get(agent_id, {}).get(dimension, 0)

    def set(self, agent_id, dimension, score, increment_sample=True):
        import time
        score = max(TRUST_MIN, min(TRUST_MAX, score))
        self._scores.setdefault(agent_id, {})[dimension] = round(score, 4)
        if increment_sample:
            self._samples.setdefault(agent_id, {})[dimension] = \
                self._samples.get(agent_id, {}).get(dimension, 0) + 1
        self._last_updated.setdefault(agent_id, {})[dimension] = time.time()
        n = self._samples.get(agent_id, {}).get(dimension, 0)
        self._persist(agent_id, dimension, score, n)

    def resolve(self, agent_id, regime, asset_class, timeframe):
        gt, gn = self.get(agent_id, "global")
        rt, rn = self.get(agent_id, f"regime:{regime.lower()}")
        at, an = self.get(agent_id, f"asset:{asset_class}")
        tt, tn = self.get(agent_id, f"tf:{timeframe}")
        w = {"global": 0.20, "regime": 0.35, "asset": 0.25, "tf": 0.20}
        s = {"global": gt, "regime": rt if rn >= MIN_SAMPLES else gt,
             "asset": at if an >= MIN_SAMPLES else gt, "tf": tt if tn >= MIN_SAMPLES else gt}
        return max(TRUST_MIN, min(TRUST_MAX, round(sum(w[k]*s[k] for k in w), 4)))

    def get_scores_for_context(self, regime, asset_class, timeframe):
        return {aid: self.resolve(aid, regime, asset_class, timeframe) for aid in ALL_AGENT_IDS}

    def update_after_trade(self, agent_id, outcome_correct, confidence,
                           regime, asset_class, timeframe, trade_id=None):
        outcome = 1.0 if outcome_correct else 0.0

        # Base alpha from confidence + correctness (asymmetric)
        if outcome_correct and confidence >= 0.7: base_alpha, reason = 0.05, "correct_high"
        elif outcome_correct: base_alpha, reason = 0.03, "correct_low"
        elif not outcome_correct and confidence >= 0.7: base_alpha, reason = 0.10, "wrong_high"
        elif not outcome_correct and confidence < 0.5: base_alpha, reason = 0.04, "wrong_low"
        else: base_alpha, reason = 0.05, "wrong_med"

        for dim in ["global", f"regime:{regime.lower()}", f"asset:{asset_class}", f"tf:{timeframe}"]:
            cur, n_samples = self.get(agent_id, dim)
            old = cur

            # Sample-size weighted alpha: high learning rate for cold start,
            # tapering as samples grow. Minimum 30% of base_alpha even at 200+ samples.
            # n=0 → 1.0x, n=5 → 0.67x, n=20 → 0.43x, n=50 → 0.35x, n=200 → 0.31x
            sample_factor = max(0.3, 1.0 / (1.0 + n_samples * 0.1))
            alpha = base_alpha * sample_factor

            norm = (cur - TRUST_MIN) / (TRUST_MAX - TRUST_MIN)
            new_norm = norm + alpha * (outcome - norm)
            new = round(TRUST_MIN + new_norm * (TRUST_MAX - TRUST_MIN), 4)
            new = max(TRUST_MIN, min(TRUST_MAX, new))
            self.set(agent_id, dim, new)
            self._persist_history(agent_id, dim, old, new, reason, trade_id, alpha)

        logger.info("trust_updated", agent=agent_id,
                     outcome="correct" if outcome_correct else "wrong",
                     base_alpha=base_alpha)

    def apply_daily_decay(self, stale_threshold_days=14, decay_rate=0.005):
        """Decay scores toward baseline ONLY for dimensions not updated recently."""
        import time
        now = time.time()
        stale_cutoff = now - (stale_threshold_days * 86400)
        decayed = 0
        skipped = 0

        for aid in ALL_AGENT_IDS:
            for dim in list(self._scores.get(aid, {}).keys()):
                s = self._scores[aid][dim]
                if s == TRUST_BASELINE:
                    continue

                last = self._last_updated.get(aid, {}).get(dim, 0)
                if last > stale_cutoff:
                    skipped += 1
                    continue  # Recently updated — don't decay

                new = s + (TRUST_BASELINE - s) * decay_rate
                self._scores[aid][dim] = round(max(TRUST_MIN, min(TRUST_MAX, new)), 4)
                n = self._samples.get(aid, {}).get(dim, 0)
                self._persist(aid, dim, self._scores[aid][dim], n)
                decayed += 1

        logger.info("trust_decay_applied", decayed=decayed, skipped=skipped,
                     stale_days=stale_threshold_days)

    def get_all_scores(self):
        if not self._loaded: self.load_from_db()
        return {aid: {dim: {"score": self._scores.get(aid, {}).get(dim, TRUST_BASELINE),
                            "samples": self._samples.get(aid, {}).get(dim, 0),
                            "provisional": self._samples.get(aid, {}).get(dim, 0) < MIN_SAMPLES}
                      for dim in self._scores.get(aid, {})} for aid in ALL_AGENT_IDS}

    def get_trust_summary(self):
        if not self._loaded: self.load_from_db()
        out = []
        for aid in ALL_AGENT_IDS:
            gs, gn = self.get(aid, "global")
            out.append({"agent_id": aid, "global_trust": round(gs, 3),
                        "global_samples": gn, "provisional": gn < MIN_SAMPLES})
        return out


trust_store = TrustScoreStore()
