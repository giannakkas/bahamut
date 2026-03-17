// ── Auth ──
export interface User {
  id: string;
  email: string;
  full_name: string;
  role: 'trader' | 'admin' | 'viewer';
  workspace_id: string;
}

// ── Regime ──
export interface Regime {
  regime: string;
  confidence: number;
  previous_regime?: string;
  transition_reason?: string;
  timestamp: string;
}

// ── Agent ──
export interface AgentContribution {
  agent_id: string;
  bias: string;
  confidence: number;
  trust_score: number;
  base_weight: number;
  regime_relevance: number;
  effective_contribution: number;
}

export interface Evidence {
  claim: string;
  data_point: string;
  weight: number;
}

export interface AgentOutput {
  agent_id: string;
  directional_bias: 'LONG' | 'SHORT' | 'NEUTRAL' | 'NO_TRADE';
  confidence: number;
  evidence: Evidence[];
  risk_notes: string[];
  invalidation_conditions: string[];
  meta: Record<string, any>;
}

// ── Consensus ──
export interface TradePlan {
  entry_price?: number;
  entry_type: string;
  stop_loss: number;
  take_profit: number;
  position_size_pct: number;
  risk_reward_ratio: number;
  max_hold_duration: string;
  invalidation_price: number;
}

export interface ConsensusDecision {
  consensus_id: string;
  cycle_id: string;
  asset: string;
  direction: 'LONG' | 'SHORT' | 'NO_TRADE';
  final_score: number;
  decision: string;
  agreement_pct: number;
  agent_contributions: AgentContribution[];
  dissenting_agents: { agent_id: string; bias: string; confidence: number }[];
  challenges: any[];
  regime: string;
  risk_flags: string[];
  blocked: boolean;
  block_reason?: string;
  trade_plan?: TradePlan;
  explanation: string;
  execution_mode: 'AUTO' | 'APPROVAL' | 'WATCH';
  trading_profile: string;
}

// ── Risk ──
export interface DrawdownState {
  daily: number;
  weekly: number;
  total: number;
  dailyLimit: number;
  weeklyLimit: number;
  totalLimit: number;
}

export interface CircuitBreaker {
  name: string;
  active: boolean;
  reason?: string;
}

// ── Trade ──
export interface Trade {
  id: string;
  asset: string;
  direction: string;
  pnl_pct?: number;
  status: string;
  execution_mode: string;
  opened_at?: string;
  closed_at?: string;
  close_reason?: string;
}

// ── Trust ──
export interface TrustScore {
  agent_id: string;
  dimension: string;
  score: number;
  samples: number;
}

// ── Agent metadata for display ──
export const AGENT_META: Record<string, { name: string; icon: string; color: string }> = {
  macro_agent: { name: 'Macro', icon: 'M', color: '#6C63FF' },
  flow_agent: { name: 'Flow', icon: 'F', color: '#06B6D4' },
  volatility_agent: { name: 'Volatility', icon: 'V', color: '#F59E0B' },
  options_agent: { name: 'Options', icon: 'O', color: '#E94560' },
  liquidity_agent: { name: 'Liquidity / Whales', icon: 'L', color: '#10B981' },
  sentiment_agent: { name: 'Sentiment', icon: 'S', color: '#F43F5E' },
  technical_agent: { name: 'Technical', icon: 'T', color: '#8B5CF6' },
  risk_agent: { name: 'Risk', icon: 'R', color: '#EF4444' },
  learning_agent: { name: 'Learning', icon: 'Le', color: '#14B8A6' },
};
