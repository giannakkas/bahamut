"""
Bahamut Meta-Labeling Model — ML win-probability with an honesty gate.

Trains a classifier on CLOSED trades that carry an entry_features JSON vector
(captured at open since migration 005) to estimate P(win) for future signals.
Strategies stay the signal generators; this model only grades setups.

THE HONESTY GATE: a validation run on the 854 pre-fix historical trades gave
holdout AUC ~0.52 (coin flip) — those trades lacked rich features and 79% were
aging-bug timeouts (noise labels). So this model NEVER influences trading
unless BOTH hold:
  1. trained on >= MIN_SAMPLES feature-rich trades, AND
  2. time-ordered holdout AUC >= AUC_GATE.
Until then it reports its own inadequacy via status(). Even after passing the
gate, acting on predictions requires admin config meta_model.enabled=true
(default false) — shadow logging only.

Model persistence: Redis (pickle+base64, small model). Retrain via
POST /training/meta-model/retrain (seconds).
"""
import base64
import json
import os
import pickle
import structlog
from datetime import datetime, timezone

logger = structlog.get_logger()

MIN_SAMPLES = 200
AUC_GATE = 0.55
HOLDOUT_FRAC = 0.25
REDIS_MODEL_KEY = "bahamut:meta_model:blob"
REDIS_STATUS_KEY = "bahamut:meta_model:status"

NUMERIC_FEATURES = [
    "readiness", "confidence", "sl_pct", "tp_pct", "rr", "vix",
    "rsi_14", "rsi", "adx", "atr_14", "realized_vol_20",
]
CATEGORICAL_FEATURES = ["regime", "exec_type", "tier", "macro_state"]


def _get_redis():
    import redis
    try:
        return redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
    except Exception:
        return None


def _vectorize(rows: list[dict], categories: dict | None = None):
    """rows: [{features…, direction, asset_class}] → (X, categories)."""
    import numpy as np
    if categories is None:
        categories = {}
        for c in CATEGORICAL_FEATURES + ["direction", "asset_class", "strategy"]:
            categories[c] = sorted({str(r.get(c, "") or "") for r in rows})
    X = []
    for r in rows:
        vec = [float(r.get(k) or 0.0) for k in NUMERIC_FEATURES]
        for c, vals in categories.items():
            v = str(r.get(c, "") or "")
            vec.extend([1.0 if v == val else 0.0 for val in vals])
        X.append(vec)
    return np.array(X, dtype=float), categories


def _load_training_rows() -> list[dict]:
    """Closed trades with non-empty entry_features, oldest first."""
    from bahamut.db.query import run_query
    rows = run_query("""
        SELECT strategy, asset_class, direction, pnl, entry_time, entry_features
        FROM training_trades
        WHERE entry_features IS NOT NULL AND entry_features != ''
        ORDER BY entry_time ASC
    """)
    out = []
    for r in rows or []:
        try:
            feat = json.loads(r["entry_features"])
        except Exception:
            continue
        feat.update({
            "strategy": r["strategy"], "asset_class": r["asset_class"],
            "direction": r["direction"],
            "label": 1 if float(r["pnl"] or 0) > 0.01 else 0,
        })
        out.append(feat)
    return out


def train_from_db() -> dict:
    """Train + walk-forward validate. Persists the model ONLY if the gate passes."""
    status = {
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "samples": 0, "gate_passed": False, "active": False,
        "min_samples": MIN_SAMPLES, "auc_gate": AUC_GATE,
        "holdout_auc": None, "note": "",
    }
    try:
        rows = _load_training_rows()
        status["samples"] = len(rows)
        if len(rows) < MIN_SAMPLES:
            status["note"] = (f"Insufficient feature-rich trades ({len(rows)}/{MIN_SAMPLES}). "
                              "Collecting — every new closed trade adds one.")
            _save_status(status)
            return status

        import numpy as np
        from sklearn.ensemble import GradientBoostingClassifier
        from sklearn.metrics import roc_auc_score

        split = int(len(rows) * (1 - HOLDOUT_FRAC))
        X, cats = _vectorize(rows)
        y = np.array([r["label"] for r in rows])
        if len(set(y[:split])) < 2 or len(set(y[split:])) < 2:
            status["note"] = "Degenerate labels (all wins or all losses in a split)."
            _save_status(status)
            return status

        model = GradientBoostingClassifier(
            n_estimators=150, max_depth=3, learning_rate=0.05,
            subsample=0.8, random_state=42,
        ).fit(X[:split], y[:split])
        auc = float(roc_auc_score(y[split:], model.predict_proba(X[split:])[:, 1]))
        status["holdout_auc"] = round(auc, 4)

        if auc < AUC_GATE:
            status["note"] = (f"Gate FAILED: holdout AUC {auc:.3f} < {AUC_GATE}. "
                              "Model NOT activated — predictions would be noise.")
            _save_status(status)
            return status

        # Gate passed: refit on all data, persist
        model_full = GradientBoostingClassifier(
            n_estimators=150, max_depth=3, learning_rate=0.05,
            subsample=0.8, random_state=42,
        ).fit(X, y)
        blob = base64.b64encode(pickle.dumps({"model": model_full, "categories": cats})).decode()
        r = _get_redis()
        if r:
            r.set(REDIS_MODEL_KEY, blob)
        status["gate_passed"] = True
        status["active"] = True
        status["note"] = f"Gate passed (AUC {auc:.3f}). Shadow predictions active."
        _save_status(status)
        logger.info("meta_model_trained", samples=len(rows), auc=auc)
        return status
    except Exception as e:
        status["note"] = f"Training error: {str(e)[:200]}"
        _save_status(status)
        logger.warning("meta_model_train_failed", error=str(e)[:200])
        return status


def _save_status(status: dict):
    r = _get_redis()
    if r:
        try:
            r.set(REDIS_STATUS_KEY, json.dumps(status))
        except Exception:
            pass


def get_status() -> dict:
    r = _get_redis()
    if r:
        try:
            raw = r.get(REDIS_STATUS_KEY)
            if raw:
                return json.loads(raw)
        except Exception:
            pass
    return {"samples": 0, "gate_passed": False, "active": False,
            "note": "Never trained. POST /training/meta-model/retrain once "
                    f"{MIN_SAMPLES}+ feature-rich trades have closed."}


def predict_pwin(features: dict) -> float | None:
    """P(win) for an entry-time feature dict, or None if no active model."""
    try:
        r = _get_redis()
        if not r:
            return None
        raw = r.get(REDIS_MODEL_KEY)
        if not raw:
            return None
        obj = pickle.loads(base64.b64decode(raw))
        X, _ = _vectorize([features], obj["categories"])
        return float(obj["model"].predict_proba(X)[0, 1])
    except Exception:
        return None


def shadow_log(asset: str, strategy: str, pwin: float | None):
    """Record a shadow prediction so live accuracy can be audited later."""
    if pwin is None:
        return
    r = _get_redis()
    if not r:
        return
    try:
        r.lpush("bahamut:meta_model:shadow", json.dumps({
            "ts": datetime.now(timezone.utc).isoformat(),
            "asset": asset, "strategy": strategy, "pwin": round(pwin, 4),
        }))
        r.ltrim("bahamut:meta_model:shadow", 0, 999)
    except Exception:
        pass
