"""
Bahamut.AI Stress Scenarios — predefined conditions to test system resilience.

Each scenario modifies trust, regime, profile, or thresholds and replays
historical traces through the current pipeline.

Scenarios test:
  1. Would the system have stopped trading during a crisis?
  2. How much would position sizes shrink with low trust?
  3. Would tighter thresholds have prevented losing trades?
  4. Would the system survive a total trust collapse?
  5. What happens when one dominant agent fails?
"""

SCENARIOS = [
    {
        "name": "crisis_regime_shock",
        "description": "All traces replayed as if CRISIS regime was active. "
                       "Tests: crisis size reduction, CONSERVATIVE auto-downgrade, "
                       "regime-disallowed blocking.",
        "regime": "CRISIS",
        "trust_overrides": None,
        "profile": None,  # use stored profile (will be auto-downgraded by engine)
        "threshold_overrides": None,
        "max_traces": 50,
    },
    {
        "name": "trust_collapse",
        "description": "All agent trust scores set to 0.3 (near minimum). "
                       "Tests: trust dampening in consensus, LOW_TRUST execution block, "
                       "how many trades would have been prevented.",
        "regime": None,
        "trust_overrides": {
            "technical_agent": 0.3, "macro_agent": 0.3,
            "sentiment_agent": 0.3, "volatility_agent": 0.3,
            "liquidity_agent": 0.3,
        },
        "profile": None,
        "threshold_overrides": None,
        "max_traces": 50,
    },
    {
        "name": "conservative_mode",
        "description": "All traces replayed under CONSERVATIVE profile. "
                       "Tests: higher score thresholds, no auto-trade, "
                       "lower max positions, tighter drawdown limits.",
        "regime": None,
        "trust_overrides": None,
        "profile": "CONSERVATIVE",
        "threshold_overrides": None,
        "max_traces": 50,
    },
    {
        "name": "aggressive_mode",
        "description": "All traces replayed under AGGRESSIVE profile. "
                       "Tests: would more trades have opened? What would P&L look like?",
        "regime": None,
        "trust_overrides": None,
        "profile": "AGGRESSIVE",
        "threshold_overrides": None,
        "max_traces": 50,
    },
    {
        "name": "tight_thresholds",
        "description": "Signal thresholds raised by +0.10 across all profiles. "
                       "Tests: how many marginal signals would have been filtered out.",
        "regime": None,
        "trust_overrides": None,
        "profile": None,
        "threshold_overrides": {
            "BALANCED": {"strong_signal": 0.82, "signal": 0.68, "weak_signal": 0.55},
            "AGGRESSIVE": {"strong_signal": 0.72, "signal": 0.58, "weak_signal": 0.45},
            "CONSERVATIVE": {"strong_signal": 0.92, "signal": 0.80, "weak_signal": 0.65},
        },
        "max_traces": 50,
    },
    {
        "name": "technical_agent_failure",
        "description": "Technical agent trust set to 0.1 (effectively removed). "
                       "Tests: system behavior when the highest-weighted agent is unreliable.",
        "regime": None,
        "trust_overrides": {"technical_agent": 0.1},
        "profile": None,
        "threshold_overrides": None,
        "max_traces": 50,
    },
    {
        "name": "high_vol_regime",
        "description": "All traces replayed as HIGH_VOL. Volatility agent boosted, "
                       "technical agent dampened. Tests regime-aware weight shifting.",
        "regime": "HIGH_VOL",
        "trust_overrides": None,
        "profile": None,
        "threshold_overrides": None,
        "max_traces": 50,
    },
    {
        "name": "golden_conditions",
        "description": "All trust at 1.5, AGGRESSIVE profile, RISK_ON regime. "
                       "Tests: maximum possible throughput. How many trades pass? "
                       "What would max exposure look like?",
        "regime": "RISK_ON",
        "trust_overrides": {
            "technical_agent": 1.5, "macro_agent": 1.5,
            "sentiment_agent": 1.5, "volatility_agent": 1.5,
            "liquidity_agent": 1.5,
        },
        "profile": "AGGRESSIVE",
        "threshold_overrides": None,
        "max_traces": 50,
    },
]
