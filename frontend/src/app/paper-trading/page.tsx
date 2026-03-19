"use client";

import { useState, useEffect, useCallback } from "react";
import { useAuthStore } from "@/stores/auth";
import AppShell from "@/components/layout/AppShell";

const API = process.env.NEXT_PUBLIC_API_URL || "https://bahamut-production.up.railway.app";

interface Position {
  id: number;
  asset: string;
  direction: string;
  entry_price: number;
  current_price: number;
  exit_price: number | null;
  quantity: number;
  position_value: number;
  risk_amount: number;
  unrealized_pnl: number;
  unrealized_pnl_pct: number;
  realized_pnl: number | null;
  realized_pnl_pct: number | null;
  stop_loss: number;
  take_profit: number;
  signal_score: number;
  signal_label: string;
  status: string;
  opened_at: string;
  closed_at: string | null;
  agent_votes: Record<string, { direction: string; confidence: number }>;
}

interface Portfolio {
  balance: number;
  initial_balance: number;
  total_pnl: number;
  total_pnl_pct: number;
  total_trades: number;
  winning_trades: number;
  losing_trades: number;
  win_rate: number;
  best_trade: number;
  worst_trade: number;
  max_drawdown: number;
  peak_balance: number;
  open_positions: Position[];
}

interface AgentLeaderboard {
  agent: string;
  accuracy: number;
  total_signals: number;
  correct: number;
  wrong: number;
  best_streak: number;
  worst_streak: number;
}

interface LearningEvent {
  id: number;
  agent: string;
  asset: string;
  agent_direction: string;
  actual_outcome: string;
  confidence: number;
  was_correct: boolean | null;
  trust_delta: number;
  pnl: number;
  created_at: string;
}

const AGENT_COLORS: Record<string, string> = {
  technical: "#3b82f6",
  macro: "#8b5cf6",
  sentiment: "#f59e0b",
  volatility: "#ef4444",
  liquidity: "#06b6d4",
  risk: "#10b981",
};

function StatCard({ label, value, sub, color }: {
  label: string; value: string; sub?: string; color?: string;
}) {
  return (
    <div className="bg-[#1a1f2e] border border-gray-800 rounded-xl p-4">
      <div className="text-xs text-gray-400 uppercase tracking-wider mb-1">{label}</div>
      <div className={`text-2xl font-bold ${color || "text-white"}`}>{value}</div>
      {sub && <div className="text-xs text-gray-500 mt-1">{sub}</div>}
    </div>
  );
}

function PnlBadge({ value, pct }: { value: number; pct?: number }) {
  const isPos = value >= 0;
  return (
    <span className={`font-mono text-sm ${isPos ? "text-emerald-400" : "text-red-400"}`}>
      {isPos ? "+" : ""}${value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
      {pct !== undefined && (
        <span className="text-xs ml-1">({isPos ? "+" : ""}{pct.toFixed(1)}%)</span>
      )}
    </span>
  );
}

function DirectionBadge({ direction }: { direction: string }) {
  const isLong = direction === "LONG";
  return (
    <span className={`px-2 py-0.5 rounded text-xs font-bold ${
      isLong ? "bg-emerald-500/20 text-emerald-400" : "bg-red-500/20 text-red-400"
    }`}>
      {isLong ? "▲" : "▼"} {direction}
    </span>
  );
}

function StatusBadge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    OPEN: "bg-blue-500/20 text-blue-400",
    CLOSED_TP: "bg-emerald-500/20 text-emerald-400",
    CLOSED_SL: "bg-red-500/20 text-red-400",
    CLOSED_TIMEOUT: "bg-yellow-500/20 text-yellow-400",
    CLOSED_SIGNAL: "bg-purple-500/20 text-purple-400",
  };
  return (
    <span className={`px-2 py-0.5 rounded text-xs font-medium ${colors[status] || "bg-gray-500/20 text-gray-400"}`}>
      {status.replace("CLOSED_", "")}
    </span>
  );
}

export default function PaperTradingPage() {
  const { token } = useAuthStore();
  const [portfolio, setPortfolio] = useState<Portfolio | null>(null);
  const [closedPositions, setClosedPositions] = useState<Position[]>([]);
  const [leaderboard, setLeaderboard] = useState<AgentLeaderboard[]>([]);
  const [learningLog, setLearningLog] = useState<LearningEvent[]>([]);
  const [tab, setTab] = useState<"positions" | "leaderboard" | "learning">("positions");
  const [loading, setLoading] = useState(true);

  const headers = { Authorization: `Bearer ${token}`, "Content-Type": "application/json" };

  const fetchData = useCallback(async () => {
    try {
      const [pRes, posRes, lbRes, llRes] = await Promise.allSettled([
        fetch(`${API}/api/v1/paper-trading/portfolio`, { headers }),
        fetch(`${API}/api/v1/paper-trading/positions?limit=50`, { headers }),
        fetch(`${API}/api/v1/paper-trading/leaderboard`, { headers }),
        fetch(`${API}/api/v1/paper-trading/learning-log?limit=30`, { headers }),
      ]);

      if (pRes.status === "fulfilled" && pRes.value.ok)
        setPortfolio(await pRes.value.json());
      if (posRes.status === "fulfilled" && posRes.value.ok) {
        const data = await posRes.value.json();
        setClosedPositions(data.positions?.filter((p: Position) => p.status !== "OPEN") || []);
      }
      if (lbRes.status === "fulfilled" && lbRes.value.ok) {
        const data = await lbRes.value.json();
        setLeaderboard(data.agents || []);
      }
      if (llRes.status === "fulfilled" && llRes.value.ok) {
        const data = await llRes.value.json();
        setLearningLog(data.events || []);
      }
    } catch (err) {
      console.error("Failed to fetch paper trading data:", err);
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 30_000); // Refresh every 30s
    return () => clearInterval(interval);
  }, [fetchData]);

  if (loading) {
    return (
      <AppShell>
        <div className="flex items-center justify-center h-96">
          <div className="text-gray-400 animate-pulse text-lg">Loading Paper Trading Engine...</div>
        </div>
      </AppShell>
    );
  }

  const p = portfolio;
  const totalUnrealized = p?.open_positions?.reduce((sum: number, pos: any) => sum + (pos.unrealized_pnl || 0), 0) || 0;
  const totalAtRisk = p?.open_positions?.reduce((sum: number, pos: any) => sum + (pos.risk_amount || 0), 0) || 0;
  const availableBalance = (p?.balance || 100_000) - totalAtRisk;

  return (
    <AppShell>
    <div className="min-h-screen p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white flex items-center gap-3">
            <span className="text-3xl">🧠</span> Self-Learning Engine
            <span className="text-xs bg-emerald-500/20 text-emerald-400 px-2 py-1 rounded-full font-medium">
              PAPER TRADING
            </span>
          </h1>
          <p className="text-sm text-gray-400 mt-1">
            Autonomous demo trading • AI agents learn from every trade outcome
          </p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={fetchData}
            className="px-3 py-1.5 bg-gray-800 text-gray-300 rounded-lg hover:bg-gray-700 text-sm"
          >
            ↻ Refresh
          </button>
        </div>
      </div>

      {/* Portfolio Stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-3">
        <StatCard
          label="Balance"
          value={`$${(p?.balance || 100_000).toLocaleString()}`}
          sub={`$${Math.round(totalAtRisk).toLocaleString()} at risk · $${Math.round(availableBalance).toLocaleString()} available`}
        />
        <StatCard
          label="Unrealized P&L"
          value={`${totalUnrealized >= 0 ? "+" : ""}$${totalUnrealized.toLocaleString(undefined, {minimumFractionDigits: 0, maximumFractionDigits: 0})}`}
          sub={`${(p?.open_positions?.length || 0)} open positions`}
          color={totalUnrealized >= 0 ? "text-emerald-400" : "text-red-400"}
        />
        <StatCard
          label="Total P&L"
          value={`${(p?.total_pnl || 0) >= 0 ? "+" : ""}$${(p?.total_pnl || 0).toLocaleString()}`}
          sub={`${(p?.total_pnl_pct || 0) >= 0 ? "+" : ""}${(p?.total_pnl_pct || 0).toFixed(2)}% realized`}
          color={(p?.total_pnl || 0) >= 0 ? "text-emerald-400" : "text-red-400"}
        />
        <StatCard
          label="Win Rate"
          value={`${(p?.win_rate || 0).toFixed(1)}%`}
          sub={`${p?.winning_trades || 0}W / ${p?.losing_trades || 0}L`}
          color={(p?.win_rate || 0) >= 50 ? "text-emerald-400" : "text-red-400"}
        />
        <StatCard
          label="Total Trades"
          value={`${p?.total_trades || 0}`}
          sub="Completed"
        />
        <StatCard
          label="Max Drawdown"
          value={`${(p?.max_drawdown || 0).toFixed(2)}%`}
          sub={`Peak: $${(p?.peak_balance || 100_000).toLocaleString()}`}
          color="text-yellow-400"
        />
        <StatCard
          label="Open Positions"
          value={`${p?.open_positions?.length || 0}`}
          sub={`/ ${p?.max_open_positions || 10} max`}
        />
      </div>

      {/* Open Positions */}
      {p?.open_positions && p.open_positions.length > 0 && (
        <div className="bg-[#1a1f2e] border border-gray-800 rounded-xl p-4">
          <h2 className="text-lg font-semibold text-white mb-3 flex items-center gap-2">
            <span className="w-2 h-2 bg-blue-400 rounded-full animate-pulse" />
            Open Positions
          </h2>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-gray-400 text-xs uppercase border-b border-gray-700">
                  <th className="text-left py-2 px-3">Asset</th>
                  <th className="text-left py-2 px-3">Direction</th>
                  <th className="text-right py-2 px-3">Invested</th>
                  <th className="text-right py-2 px-3">Risk</th>
                  <th className="text-right py-2 px-3">Entry</th>
                  <th className="text-right py-2 px-3">Current</th>
                  <th className="text-right py-2 px-3">SL</th>
                  <th className="text-right py-2 px-3">TP</th>
                  <th className="text-right py-2 px-3">P&L</th>
                  <th className="text-right py-2 px-3">Score</th>
                </tr>
              </thead>
              <tbody>
                {p.open_positions.map((pos) => (
                  <tr key={pos.id} className="border-b border-gray-800/50 hover:bg-gray-800/30">
                    <td className="py-2 px-3 font-medium text-white">{pos.asset}</td>
                    <td className="py-2 px-3"><DirectionBadge direction={pos.direction} /></td>
                    <td className="py-2 px-3 text-right font-mono text-gray-300">${pos.position_value ? Math.round(pos.position_value).toLocaleString() : '—'}</td>
                    <td className="py-2 px-3 text-right font-mono text-yellow-400/70">${pos.risk_amount ? Math.round(pos.risk_amount).toLocaleString() : '—'}</td>
                    <td className="py-2 px-3 text-right font-mono text-gray-300">{pos.entry_price}</td>
                    <td className="py-2 px-3 text-right font-mono text-gray-300">{pos.current_price}</td>
                    <td className="py-2 px-3 text-right font-mono text-red-400/70">{pos.stop_loss}</td>
                    <td className="py-2 px-3 text-right font-mono text-emerald-400/70">{pos.take_profit}</td>
                    <td className="py-2 px-3 text-right">
                      <PnlBadge value={pos.unrealized_pnl} pct={pos.unrealized_pnl_pct} />
                    </td>
                    <td className="py-2 px-3 text-right font-mono text-yellow-400">{pos.signal_score?.toFixed(2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Tabs */}
      <div className="flex gap-1 bg-[#1a1f2e] border border-gray-800 rounded-xl p-1 w-fit">
        {(["positions", "leaderboard", "learning"] as const).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
              tab === t ? "bg-blue-500/20 text-blue-400" : "text-gray-400 hover:text-white"
            }`}
          >
            {t === "positions" ? "📊 Trade History" : t === "leaderboard" ? "🏆 Agent Leaderboard" : "🧬 Learning Log"}
          </button>
        ))}
      </div>

      {/* Trade History */}
      {tab === "positions" && (
        <div className="bg-[#1a1f2e] border border-gray-800 rounded-xl p-4">
          {closedPositions.length === 0 ? (
            <div className="text-center py-12 text-gray-400">
              <div className="text-4xl mb-3">📭</div>
              <div>No closed trades yet. The engine will start trading automatically when signals fire.</div>
              <div className="text-xs mt-2 text-gray-500">
                Trades open on SIGNAL (≥0.58) or STRONG_SIGNAL (≥0.72) consensus scores
              </div>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-gray-400 text-xs uppercase border-b border-gray-700">
                    <th className="text-left py-2 px-3">Asset</th>
                    <th className="text-left py-2 px-3">Dir</th>
                    <th className="text-right py-2 px-3">Entry</th>
                    <th className="text-right py-2 px-3">Exit</th>
                    <th className="text-right py-2 px-3">P&L</th>
                    <th className="text-center py-2 px-3">Status</th>
                    <th className="text-right py-2 px-3">Score</th>
                    <th className="text-right py-2 px-3">Closed</th>
                  </tr>
                </thead>
                <tbody>
                  {closedPositions.map((pos) => (
                    <tr key={pos.id} className="border-b border-gray-800/50 hover:bg-gray-800/30">
                      <td className="py-2 px-3 font-medium text-white">{pos.asset}</td>
                      <td className="py-2 px-3"><DirectionBadge direction={pos.direction} /></td>
                      <td className="py-2 px-3 text-right font-mono text-gray-300">{pos.entry_price}</td>
                      <td className="py-2 px-3 text-right font-mono text-gray-300">{pos.exit_price}</td>
                      <td className="py-2 px-3 text-right">
                        <PnlBadge value={pos.realized_pnl || 0} pct={pos.realized_pnl_pct || 0} />
                      </td>
                      <td className="py-2 px-3 text-center"><StatusBadge status={pos.status} /></td>
                      <td className="py-2 px-3 text-right font-mono text-yellow-400">{pos.signal_score?.toFixed(2)}</td>
                      <td className="py-2 px-3 text-right text-gray-400 text-xs">
                        {pos.closed_at ? new Date(pos.closed_at).toLocaleDateString() : "-"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* Agent Leaderboard */}
      {tab === "leaderboard" && (
        <div className="bg-[#1a1f2e] border border-gray-800 rounded-xl p-4">
          {leaderboard.length === 0 ? (
            <div className="text-center py-12 text-gray-400">
              <div className="text-4xl mb-3">🏆</div>
              <div>Leaderboard populates after trades close and the learning loop processes them.</div>
            </div>
          ) : (
            <div className="space-y-3">
              {leaderboard.map((agent, i) => (
                <div
                  key={agent.agent}
                  className="flex items-center gap-4 p-3 bg-gray-800/30 rounded-lg border border-gray-700/50"
                >
                  <div className="text-2xl font-bold text-gray-500 w-8 text-center">
                    {i === 0 ? "🥇" : i === 1 ? "🥈" : i === 2 ? "🥉" : `#${i + 1}`}
                  </div>
                  <div
                    className="w-1 h-10 rounded-full"
                    style={{ backgroundColor: AGENT_COLORS[agent.agent] || "#666" }}
                  />
                  <div className="flex-1">
                    <div className="text-white font-medium capitalize">{agent.agent} Agent</div>
                    <div className="text-xs text-gray-400">
                      {agent.correct}W / {agent.wrong}L · {agent.total_signals} signals
                    </div>
                  </div>
                  <div className="text-right">
                    <div className={`text-xl font-bold ${
                      agent.accuracy >= 0.6 ? "text-emerald-400" :
                      agent.accuracy >= 0.45 ? "text-yellow-400" : "text-red-400"
                    }`}>
                      {(agent.accuracy * 100).toFixed(1)}%
                    </div>
                    <div className="text-xs text-gray-500">accuracy</div>
                  </div>
                  <div className="text-right w-20">
                    <div className="text-sm text-emerald-400">🔥 {agent.best_streak}</div>
                    <div className="text-sm text-red-400">💀 {Math.abs(agent.worst_streak)}</div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Learning Log */}
      {tab === "learning" && (
        <div className="bg-[#1a1f2e] border border-gray-800 rounded-xl p-4">
          {learningLog.length === 0 ? (
            <div className="text-center py-12 text-gray-400">
              <div className="text-4xl mb-3">🧬</div>
              <div>Learning events appear here as trades close and trust scores adjust.</div>
              <div className="text-xs mt-2 text-gray-500">
                Each event shows which agent was right/wrong and how trust was adjusted
              </div>
            </div>
          ) : (
            <div className="space-y-2">
              {learningLog.map((event) => (
                <div
                  key={event.id}
                  className={`flex items-center gap-3 p-3 rounded-lg border ${
                    event.was_correct
                      ? "border-emerald-500/20 bg-emerald-500/5"
                      : event.was_correct === false
                      ? "border-red-500/20 bg-red-500/5"
                      : "border-gray-700/50 bg-gray-800/30"
                  }`}
                >
                  <div className="text-lg">
                    {event.was_correct ? "✅" : event.was_correct === false ? "❌" : "➖"}
                  </div>
                  <div
                    className="w-1 h-8 rounded-full"
                    style={{ backgroundColor: AGENT_COLORS[event.agent] || "#666" }}
                  />
                  <div className="flex-1">
                    <div className="text-sm text-white">
                      <span className="capitalize font-medium">{event.agent}</span>
                      {" said "}
                      <span className={event.agent_direction === "LONG" ? "text-emerald-400" : "text-red-400"}>
                        {event.agent_direction}
                      </span>
                      {" on "}
                      <span className="text-gray-300">{event.asset}</span>
                      {" · "}
                      <span className="text-gray-400">{(event.confidence * 100).toFixed(0)}% conf</span>
                    </div>
                    <div className="text-xs text-gray-500">
                      Trade P&L: <PnlBadge value={event.pnl} />
                    </div>
                  </div>
                  <div className={`text-sm font-mono ${
                    event.trust_delta > 0 ? "text-emerald-400" : "text-red-400"
                  }`}>
                    {event.trust_delta > 0 ? "+" : ""}{event.trust_delta.toFixed(4)}
                    <div className="text-xs text-gray-500">trust Δ</div>
                  </div>
                  <div className="text-xs text-gray-500">
                    {new Date(event.created_at).toLocaleString()}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Info Footer */}
      <div className="bg-[#1a1f2e]/50 border border-gray-800/50 rounded-xl p-4 text-xs text-gray-500">
        <strong className="text-gray-400">How Self-Learning Works:</strong> Every signal cycle → if consensus ≥ 0.58, a paper trade opens automatically
        → ATR-based stop loss (2x) and take profit (3x) → positions checked every 60s → on close, each agent&apos;s vote is graded
        → correct agents get trust +0.015, wrong agents get trust -0.025 → trust scores feed back into consensus weights
        → the system gets smarter with every trade.
      </div>
    </div>
    </AppShell>
  );
}
