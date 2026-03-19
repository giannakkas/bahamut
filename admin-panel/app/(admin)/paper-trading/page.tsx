"use client";
import { useState, useEffect } from "react";
import { apiBase } from "@/lib/utils";

export default function PaperTradingPage() {
  const [portfolio, setPortfolio] = useState<any>(null);
  const [closedPositions, setClosedPositions] = useState<any[]>([]);
  const [leaderboard, setLeaderboard] = useState<any[]>([]);
  const [learningLog, setLearningLog] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState<"positions" | "leaderboard" | "learning">("positions");
  const token = typeof window !== "undefined" ? sessionStorage.getItem("bah_token") : null;
  const headers = { Authorization: `Bearer ${token}` };

  const load = async () => {
    try {
      const [pf, pos, lb, ll] = await Promise.all([
        fetch(`${apiBase()}/paper-trading/portfolio`, { headers }).then(r => r.json()).catch(() => null),
        fetch(`${apiBase()}/paper-trading/positions?limit=50`, { headers }).then(r => r.json()).catch(() => ({ positions: [] })),
        fetch(`${apiBase()}/paper-trading/leaderboard`, { headers }).then(r => r.json()).catch(() => []),
        fetch(`${apiBase()}/paper-trading/learning-log?limit=30`, { headers }).then(r => r.json()).catch(() => []),
      ]);
      setPortfolio(pf);
      setClosedPositions(pos?.positions?.filter((p: any) => p.status !== "OPEN") || []);
      setLeaderboard(Array.isArray(lb) ? lb : lb?.leaderboard || []);
      setLearningLog(Array.isArray(ll) ? ll : ll?.events || []);
    } catch (e) { console.error(e); }
    setLoading(false);
  };

  useEffect(() => { load(); }, []);

  if (loading) return <div className="p-6 text-bah-muted">Loading paper trading...</div>;

  const p = portfolio;
  const openPositions = p?.open_positions || [];
  const totalUnrealized = openPositions.reduce((s: number, pos: any) => s + (pos.unrealized_pnl || 0), 0);
  const totalAtRisk = openPositions.reduce((s: number, pos: any) => s + (pos.risk_amount || 0), 0);

  return (
    <div className="p-6 max-w-6xl space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-bah-heading flex items-center gap-3">
            Self-Learning Engine
            <span className="px-2 py-0.5 bg-green-500/20 text-green-400 text-[10px] rounded-full font-semibold border border-green-500/30">
              PAPER TRADING
            </span>
          </h1>
          <p className="text-xs text-bah-muted mt-1">Autonomous demo trading • AI agents learn from every trade outcome</p>
        </div>
        <button onClick={() => { setLoading(true); load(); }}
          className="px-3 py-1.5 border border-bah-border rounded-lg text-xs text-bah-muted hover:text-bah-heading transition-colors">
          ↻ Refresh
        </button>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-7 gap-3">
        {[
          { label: "Balance", value: `$${(p?.balance || 100000).toLocaleString()}`, color: "text-bah-heading" },
          { label: "Unrealized P&L", value: `${totalUnrealized >= 0 ? "+" : ""}$${totalUnrealized.toFixed(0)}`, color: totalUnrealized >= 0 ? "text-green-400" : "text-red-400" },
          { label: "Total P&L", value: `${(p?.total_pnl || 0) >= 0 ? "+" : ""}$${(p?.total_pnl || 0).toFixed(0)}`, color: (p?.total_pnl || 0) >= 0 ? "text-green-400" : "text-red-400" },
          { label: "Win Rate", value: `${((p?.win_rate || 0) * 100).toFixed(1)}%`, color: "text-bah-heading" },
          { label: "Total Trades", value: p?.total_trades || 0, color: "text-bah-heading" },
          { label: "Max Drawdown", value: `${((p?.max_drawdown || 0) * 100).toFixed(2)}%`, color: "text-amber-400" },
          { label: "Open Positions", value: openPositions.length, color: "text-bah-cyan" },
        ].map(m => (
          <div key={m.label} className="bg-bah-surface border border-bah-border rounded-xl p-3 text-center">
            <div className={`text-lg font-bold ${m.color}`}>{m.value}</div>
            <div className="text-[9px] text-bah-muted uppercase mt-0.5">{m.label}</div>
          </div>
        ))}
      </div>

      {/* Open Positions */}
      {openPositions.length > 0 && (
        <div className="bg-bah-surface border border-bah-border rounded-xl overflow-hidden">
          <div className="px-4 py-3 border-b border-bah-border flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-green-400 animate-pulse" />
            <h2 className="text-sm font-semibold text-bah-heading">Open Positions</h2>
          </div>
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-bah-border text-[10px] text-bah-muted uppercase">
                <th className="px-3 py-2 text-left">Asset</th>
                <th className="px-3 py-2 text-left">Direction</th>
                <th className="px-3 py-2 text-right">Invested</th>
                <th className="px-3 py-2 text-right">Risk</th>
                <th className="px-3 py-2 text-right">Entry</th>
                <th className="px-3 py-2 text-right">Current</th>
                <th className="px-3 py-2 text-right">SL</th>
                <th className="px-3 py-2 text-right">TP</th>
                <th className="px-3 py-2 text-right">P&L</th>
                <th className="px-3 py-2 text-right">Score</th>
              </tr>
            </thead>
            <tbody>
              {openPositions.map((pos: any, i: number) => (
                <tr key={i} className="border-b border-bah-border/30 hover:bg-white/[0.02]">
                  <td className="px-3 py-2 font-semibold text-bah-heading">{pos.asset}</td>
                  <td className="px-3 py-2">
                    <span className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${
                      pos.direction === "LONG" ? "bg-green-500/20 text-green-400" : "bg-red-500/20 text-red-400"
                    }`}>
                      {pos.direction === "LONG" ? "▲" : "▼"} {pos.direction}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-right font-mono text-bah-subtle">${(pos.position_value || 0).toLocaleString()}</td>
                  <td className="px-3 py-2 text-right font-mono text-red-400">${(pos.risk_amount || 0).toLocaleString()}</td>
                  <td className="px-3 py-2 text-right font-mono text-bah-subtle">{pos.entry_price}</td>
                  <td className="px-3 py-2 text-right font-mono text-bah-heading">{pos.current_price || pos.entry_price}</td>
                  <td className="px-3 py-2 text-right font-mono text-red-400">{pos.stop_loss || "—"}</td>
                  <td className="px-3 py-2 text-right font-mono text-green-400">{pos.take_profit || "—"}</td>
                  <td className={`px-3 py-2 text-right font-mono font-semibold ${(pos.unrealized_pnl || 0) >= 0 ? "text-green-400" : "text-red-400"}`}>
                    {(pos.unrealized_pnl || 0) >= 0 ? "+" : ""}${(pos.unrealized_pnl || 0).toFixed(2)}
                    <span className="text-bah-muted ml-1">({(pos.unrealized_pnl_pct || 0) >= 0 ? "+" : ""}{((pos.unrealized_pnl_pct || 0) * 100).toFixed(1)}%)</span>
                  </td>
                  <td className="px-3 py-2 text-right font-mono text-purple-400">{(pos.score || 0).toFixed(2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Tabs */}
      <div className="flex gap-2 border-b border-bah-border pb-1">
        {[
          { key: "positions", label: "📊 Trade History", icon: "" },
          { key: "leaderboard", label: "🏆 Agent Leaderboard", icon: "" },
          { key: "learning", label: "🧬 Learning Log", icon: "" },
        ].map(t => (
          <button key={t.key} onClick={() => setTab(t.key as any)}
            className={`px-3 py-1.5 rounded-t-md text-xs font-semibold transition-colors ${
              tab === t.key ? "bg-bah-surface text-bah-cyan border border-bah-border border-b-0" : "text-bah-muted hover:text-bah-heading"
            }`}>{t.label}</button>
        ))}
      </div>

      {/* Tab Content */}
      {tab === "positions" && (
        <div className="bg-bah-surface border border-bah-border rounded-xl overflow-hidden">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-bah-border text-[10px] text-bah-muted uppercase">
                <th className="px-3 py-2 text-left">Asset</th>
                <th className="px-3 py-2 text-left">Direction</th>
                <th className="px-3 py-2 text-right">Entry</th>
                <th className="px-3 py-2 text-right">Exit</th>
                <th className="px-3 py-2 text-right">P&L</th>
                <th className="px-3 py-2 text-left">Status</th>
              </tr>
            </thead>
            <tbody>
              {closedPositions.map((t: any, i: number) => (
                <tr key={i} className="border-b border-bah-border/30 hover:bg-white/[0.02]">
                  <td className="px-3 py-2 font-medium text-bah-heading">{t.asset}</td>
                  <td className="px-3 py-2"><span className={t.direction === "LONG" ? "text-green-400" : "text-red-400"}>{t.direction}</span></td>
                  <td className="px-3 py-2 text-right font-mono">{t.entry_price}</td>
                  <td className="px-3 py-2 text-right font-mono">{t.exit_price || "—"}</td>
                  <td className={`px-3 py-2 text-right font-mono font-semibold ${(t.realized_pnl || 0) >= 0 ? "text-green-400" : "text-red-400"}`}>
                    ${(t.realized_pnl || 0).toFixed(2)}
                  </td>
                  <td className="px-3 py-2 text-bah-muted">{t.status}</td>
                </tr>
              ))}
              {closedPositions.length === 0 && (
                <tr><td colSpan={6} className="text-center py-6 text-bah-muted">No closed trades yet</td></tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {tab === "leaderboard" && (
        <div className="bg-bah-surface border border-bah-border rounded-xl overflow-hidden">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-bah-border text-[10px] text-bah-muted uppercase">
                <th className="px-3 py-2 text-left">Agent</th>
                <th className="px-3 py-2 text-right">Trades</th>
                <th className="px-3 py-2 text-right">Win Rate</th>
                <th className="px-3 py-2 text-right">Avg Return</th>
                <th className="px-3 py-2 text-right">Score</th>
              </tr>
            </thead>
            <tbody>
              {leaderboard.map((a: any, i: number) => (
                <tr key={i} className="border-b border-bah-border/30">
                  <td className="px-3 py-2 text-bah-heading font-medium">{a.agent_name || a.agent_id || a.name}</td>
                  <td className="px-3 py-2 text-right font-mono">{a.total_signals || a.trades || 0}</td>
                  <td className="px-3 py-2 text-right font-mono">{((a.accuracy || a.win_rate || 0) * 100).toFixed(1)}%</td>
                  <td className="px-3 py-2 text-right font-mono">{((a.avg_return || 0) * 100).toFixed(2)}%</td>
                  <td className="px-3 py-2 text-right font-mono text-purple-400">{(a.composite_score || a.score || 0).toFixed(2)}</td>
                </tr>
              ))}
              {leaderboard.length === 0 && (
                <tr><td colSpan={5} className="text-center py-6 text-bah-muted">Agent data will appear after signal cycles complete</td></tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {tab === "learning" && (
        <div className="bg-bah-surface border border-bah-border rounded-xl overflow-hidden">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-bah-border text-[10px] text-bah-muted uppercase">
                <th className="px-3 py-2 text-left">Agent</th>
                <th className="px-3 py-2 text-left">Asset</th>
                <th className="px-3 py-2 text-left">Correct</th>
                <th className="px-3 py-2 text-right">Trust Δ</th>
                <th className="px-3 py-2 text-right">P&L %</th>
                <th className="px-3 py-2 text-left">Time</th>
              </tr>
            </thead>
            <tbody>
              {learningLog.map((l: any, i: number) => (
                <tr key={i} className="border-b border-bah-border/30">
                  <td className="px-3 py-2 text-bah-heading">{l.agent_name || "—"}</td>
                  <td className="px-3 py-2 text-bah-subtle">{l.asset || "—"}</td>
                  <td className="px-3 py-2">
                    <span className={l.was_correct ? "text-green-400" : "text-red-400"}>{l.was_correct ? "✓" : "✗"}</span>
                  </td>
                  <td className={`px-3 py-2 text-right font-mono ${(l.trust_delta || 0) >= 0 ? "text-green-400" : "text-red-400"}`}>
                    {(l.trust_delta || 0) >= 0 ? "+" : ""}{((l.trust_delta || 0) * 100).toFixed(1)}%
                  </td>
                  <td className={`px-3 py-2 text-right font-mono ${(l.position_pnl_pct || 0) >= 0 ? "text-green-400" : "text-red-400"}`}>
                    {((l.position_pnl_pct || 0) * 100).toFixed(2)}%
                  </td>
                  <td className="px-3 py-2 text-bah-muted">{l.created_at ? new Date(l.created_at).toLocaleString() : "—"}</td>
                </tr>
              ))}
              {learningLog.length === 0 && (
                <tr><td colSpan={6} className="text-center py-6 text-bah-muted">Learning events will appear after trades close</td></tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
