from bahamut.agents.base import BaseAgent
from bahamut.agents.schemas import (
    AgentOutputSchema, ChallengeRequest, ChallengeResponseSchema,
    SignalCycleRequest, Evidence,
)


class RiskAgent(BaseAgent):
    agent_id = "risk_agent"
    display_name = "Risk Control"
    required_features = ["portfolio", "correlation_matrix", "regime", "drawdown_state"]
    timeout_seconds = 5  # Risk agent must respond fast

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

        # Drawdown checks
        if daily_dd > 0.025:
            risk_flags.append("DAILY_DD_WARNING")
            risk_notes.append(f"Daily drawdown elevated at {daily_dd:.2%}")
            evidence.append(Evidence(
                claim="Daily drawdown approaching limit",
                data_point=f"DD={daily_dd:.2%}", weight=0.9,
            ))

        if weekly_dd > 0.05:
            risk_flags.append("WEEKLY_DD_WARNING")
            risk_notes.append(f"Weekly drawdown elevated at {weekly_dd:.2%}")

        # Exposure check
        if abs(net_exposure) > 0.10:
            risk_flags.append("HIGH_EXPOSURE")
            evidence.append(Evidence(
                claim="Net portfolio exposure is high",
                data_point=f"Net exposure={net_exposure:.2%}", weight=0.7,
            ))

        # Correlation check
        if max_corr > 0.7:
            risk_flags.append("HIGH_CORRELATION")
            evidence.append(Evidence(
                claim="High correlation between open positions",
                data_point=f"Max correlation={max_corr:.2f}", weight=0.6,
            ))

        # Regime risk
        if regime in ("CRISIS", "REGIME_TRANSITION"):
            risk_flags.append("REGIME_RISK")
            risk_notes.append(f"Current regime ({regime}) carries elevated systemic risk")

        # Risk agent always outputs NEUTRAL (it doesn't have directional opinion)
        # Its job is to flag risks and potentially VETO
        has_critical_flags = any(f in risk_flags for f in ["DAILY_DD_WARNING", "WEEKLY_DD_WARNING"])

        if not evidence:
            evidence.append(Evidence(
                claim="Risk parameters within acceptable bounds",
                data_point=f"DD_daily={daily_dd:.2%}, exposure={net_exposure:.2%}", weight=0.5,
            ))

        # Risk agent provides mild directional opinion based on technical structure
        ind = features.get("indicators", {})
        r_close = ind.get("close", 0)
        r_ema20 = ind.get("ema_20", 0)
        r_rsi = ind.get("rsi_14", 50)
        
        risk_bias = "NEUTRAL"
        if r_close and r_ema20:
            if r_close > r_ema20 and r_rsi < 70:
                risk_bias = "LONG"
            elif r_close < r_ema20 and r_rsi > 30:
                risk_bias = "SHORT"

        return self._make_output(
            request=request,
            bias=risk_bias,
            confidence=0.8 if not has_critical_flags else 0.95,
            evidence=evidence,
            risk_notes=risk_notes,
            meta={
                "risk_flags": risk_flags,
                "daily_dd": daily_dd,
                "weekly_dd": weekly_dd,
                "net_exposure": net_exposure,
                "max_correlation": max_corr,
                "open_trades": open_trades,
                "can_trade": not has_critical_flags,
            },
        )

    async def respond_to_challenge(
        self, challenge: ChallengeRequest, original_output: AgentOutputSchema
    ) -> ChallengeResponseSchema:
        # Risk agent is the challenger, not usually the target.
        # If challenged, it never backs down on risk flags.
        risk_flags = original_output.meta.get("risk_flags", [])
        if risk_flags:
            return ChallengeResponseSchema(
                challenge_id=challenge.challenge_id,
                challenger=challenge.challenger,
                target_agent=self.agent_id,
                challenge_type=challenge.challenge_type,
                response="VETO",
                justification=f"Risk flags active: {', '.join(risk_flags)}. Cannot compromise on risk.",
            )
        return ChallengeResponseSchema(
            challenge_id=challenge.challenge_id,
            challenger=challenge.challenger,
            target_agent=self.agent_id,
            challenge_type=challenge.challenge_type,
            response="ACCEPT",
            justification="No active risk flags. Risk check passes.",
        )

    def final_veto_check(self, risk_output: AgentOutputSchema, profile_limits: dict) -> dict:
        """Final veto check before execution. Returns {vetoed: bool, reason: str}."""
        flags = risk_output.meta.get("risk_flags", [])
        daily_dd = risk_output.meta.get("daily_dd", 0)
        max_daily = profile_limits.get("max_daily_drawdown", 0.03)

        if daily_dd >= max_daily:
            return {"vetoed": True, "reason": f"Daily drawdown limit reached: {daily_dd:.2%} >= {max_daily:.2%}"}

        if "WEEKLY_DD_WARNING" in flags:
            weekly_dd = risk_output.meta.get("weekly_dd", 0)
            max_weekly = profile_limits.get("max_weekly_drawdown", 0.06)
            if weekly_dd >= max_weekly:
                return {"vetoed": True, "reason": f"Weekly drawdown limit: {weekly_dd:.2%} >= {max_weekly:.2%}"}

        return {"vetoed": False, "reason": ""}
