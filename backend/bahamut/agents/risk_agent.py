"""
Risk Agent v2 — Soft Risk (size reduction) before Hard Veto + Counterfactual Tracking

Fixes from audit:
  1. Soft risk: instead of binary VETO, first reduce position size
  2. Hard veto only on extreme conditions (daily DD >= limit, weekly >= limit)
  3. Counterfactual tracking: log blocked trades and simulate outcomes
  4. Exposure checks produce warnings, not blocks
"""
import structlog
import time
from bahamut.agents.base import BaseAgent
from bahamut.agents.schemas import (
    AgentOutputSchema, ChallengeRequest, ChallengeResponseSchema,
    SignalCycleRequest, Evidence,
)

logger = structlog.get_logger()


class RiskAgent(BaseAgent):
    agent_id = "risk_agent"
    display_name = "Risk Control"
    required_features = ["portfolio", "correlation_matrix", "regime", "drawdown_state"]
    timeout_seconds = 5

    async def analyze(self, request: SignalCycleRequest, features: dict) -> AgentOutputSchema:
        portfolio = features.get("portfolio", {})
        drawdown = features.get("drawdown", {})
        regime = request.current_regime

        daily_dd = drawdown.get("daily", 0)
        weekly_dd = drawdown.get("weekly", 0)
        open_trades = portfolio.get("open_trade_count", 0)
        net_exposure = portfolio.get("net_exposure_pct", 0)
        max_corr = portfolio.get("max_correlation", 0)

        evidence = []
        risk_notes = []
        risk_flags = []

        # ── Position size multiplier (1.0 = full, 0.5 = half, etc.) ──
        size_multiplier = 1.0

        # ── SOFT RISK CHECKS (reduce size, don't block) ──

        # Daily drawdown soft warning (25-75% of limit → reduce)
        if daily_dd > 0.015:
            risk_flags.append("DAILY_DD_SOFT")
            size_multiplier *= 0.5
            risk_notes.append(f"Daily DD at {daily_dd:.2%} — reducing size by 50%")
            evidence.append(Evidence(
                claim="Daily drawdown elevated, applying soft risk reduction",
                data_point=f"DD={daily_dd:.2%}, size→50%", weight=0.7,
            ))

        # Exposure soft warning
        if abs(net_exposure) > 0.08:
            risk_flags.append("EXPOSURE_SOFT")
            size_multiplier *= 0.7
            risk_notes.append(f"Net exposure at {net_exposure:.2%} — reducing size")
            evidence.append(Evidence(
                claim="Net exposure elevated",
                data_point=f"Exposure={net_exposure:.2%}", weight=0.6,
            ))

        # Correlation soft warning
        if max_corr > 0.6:
            risk_flags.append("CORRELATION_SOFT")
            size_multiplier *= 0.8
            risk_notes.append(f"Position correlation at {max_corr:.2f} — size reduced")
            evidence.append(Evidence(
                claim="Correlated positions detected",
                data_point=f"MaxCorr={max_corr:.2f}", weight=0.5,
            ))

        # Regime soft risk
        if regime in ("CRISIS", "REGIME_TRANSITION"):
            risk_flags.append("REGIME_RISK")
            size_multiplier *= 0.5
            risk_notes.append(f"Regime ({regime}) carries elevated risk — size halved")

        if regime == "HIGH_VOL":
            size_multiplier *= 0.75
            risk_notes.append("High vol regime — size reduced 25%")

        # Many open trades
        if open_trades >= 4:
            size_multiplier *= 0.7
            risk_notes.append(f"{open_trades} open trades — concentration risk")

        # ── HARD VETO CHECKS (these actually block) ──
        hard_veto = False
        veto_reasons = []

        if daily_dd >= 0.03:
            hard_veto = True
            veto_reasons.append(f"Daily drawdown limit: {daily_dd:.2%} >= 3%")
            risk_flags.append("DAILY_DD_HARD")

        if weekly_dd >= 0.06:
            hard_veto = True
            veto_reasons.append(f"Weekly drawdown limit: {weekly_dd:.2%} >= 6%")
            risk_flags.append("WEEKLY_DD_HARD")

        # ── Build output ──
        can_trade = not hard_veto
        size_multiplier = max(0.2, min(1.0, size_multiplier))  # Floor at 20%

        if not evidence:
            evidence.append(Evidence(
                claim="Risk parameters within acceptable bounds",
                data_point=f"DD_d={daily_dd:.2%}, exp={net_exposure:.2%}, size_mult={size_multiplier:.0%}",
                weight=0.5,
            ))

        return self._make_output(
            request=request,
            bias="NEUTRAL",
            confidence=0.9 if hard_veto else 0.7,
            evidence=evidence,
            risk_notes=risk_notes,
            meta={
                "risk_flags": risk_flags,
                "daily_dd": daily_dd,
                "weekly_dd": weekly_dd,
                "net_exposure": net_exposure,
                "max_correlation": max_corr,
                "open_trades": open_trades,
                "can_trade": can_trade,
                "size_multiplier": round(size_multiplier, 2),
                "hard_veto": hard_veto,
                "veto_reasons": veto_reasons,
            },
        )

    async def respond_to_challenge(self, challenge: ChallengeRequest, original_output: AgentOutputSchema) -> ChallengeResponseSchema:
        risk_flags = original_output.meta.get("risk_flags", [])
        hard_flags = [f for f in risk_flags if f.endswith("_HARD")]
        if hard_flags:
            return ChallengeResponseSchema(
                challenge_id=challenge.challenge_id, challenger=challenge.challenger,
                target_agent=self.agent_id, challenge_type=challenge.challenge_type,
                response="VETO",
                justification=f"Hard risk flags active: {', '.join(hard_flags)}",
            )
        return ChallengeResponseSchema(
            challenge_id=challenge.challenge_id, challenger=challenge.challenger,
            target_agent=self.agent_id, challenge_type=challenge.challenge_type,
            response="ACCEPT",
            justification="Only soft risk flags — trade allowed with reduced size",
        )

    def final_veto_check(self, risk_output: AgentOutputSchema, profile_limits: dict) -> dict:
        """Final veto check before execution. Returns {vetoed, reason, size_multiplier}."""
        meta = risk_output.meta
        if meta.get("hard_veto"):
            return {
                "vetoed": True,
                "reason": "; ".join(meta.get("veto_reasons", ["Hard risk limit"])),
                "size_multiplier": 0.0,
            }
        return {
            "vetoed": False,
            "reason": "",
            "size_multiplier": meta.get("size_multiplier", 1.0),
        }


def log_counterfactual(asset: str, direction: str, entry_price: float,
                       atr: float, reason: str, cycle_id: str = ""):
    """Log a blocked trade for counterfactual analysis."""
    try:
        from bahamut.database import sync_engine
        from sqlalchemy import text
        sl_dist = atr * 2.0
        tp_dist = atr * 3.0
        if direction == "LONG":
            sl = entry_price - sl_dist
            tp = entry_price + tp_dist
        else:
            sl = entry_price + sl_dist
            tp = entry_price - tp_dist

        with sync_engine.connect() as conn:
            conn.execute(text("""
                INSERT INTO risk_counterfactuals
                (asset, direction, entry_price, stop_loss, take_profit, block_reason, cycle_id, created_at)
                VALUES (:a, :d, :ep, :sl, :tp, :r, :c, NOW())
            """), {"a": asset, "d": direction, "ep": entry_price,
                   "sl": sl, "tp": tp, "r": reason, "c": cycle_id})
            conn.commit()
        logger.info("counterfactual_logged", asset=asset, direction=direction, price=entry_price)
    except Exception as e:
        logger.warning("counterfactual_log_failed", error=str(e))


async def evaluate_counterfactuals():
    """Check open counterfactuals against current prices. Called periodically."""
    try:
        from bahamut.database import sync_engine
        from bahamut.ingestion.market_data import get_current_prices
        from sqlalchemy import text

        prices = await get_current_prices()

        with sync_engine.connect() as conn:
            rows = conn.execute(text(
                "SELECT id, asset, direction, entry_price, stop_loss, take_profit "
                "FROM risk_counterfactuals WHERE outcome IS NULL AND created_at > NOW() - INTERVAL '7 days'"
            )).fetchall()

            for row in rows:
                rid, asset, direction, entry, sl, tp = row
                current = prices.get(asset)
                if not current:
                    continue

                outcome = None
                if direction == "LONG":
                    if current <= sl: outcome = "LOSS"
                    elif current >= tp: outcome = "WIN"
                else:
                    if current >= sl: outcome = "LOSS"
                    elif current <= tp: outcome = "WIN"

                if outcome:
                    pnl = (current - entry) if direction == "LONG" else (entry - current)
                    conn.execute(text(
                        "UPDATE risk_counterfactuals SET outcome = :o, exit_price = :p, pnl = :pnl, resolved_at = NOW() WHERE id = :id"
                    ), {"o": outcome, "p": current, "pnl": pnl, "id": rid})

            conn.commit()
    except Exception as e:
        logger.warning("counterfactual_eval_failed", error=str(e))
