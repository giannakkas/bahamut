"use client";

import { useState, useEffect } from "react";
import { apiBase } from "@/lib/utils";

export default function AgentRankingPage() {
  const [agents, setAgents] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const token = typeof window !== "undefined" ? sessionStorage.getItem("bah_token") : null;

  useEffect(() => {
    fetch(`${apiBase()}/trust/agent-leaderboard`, {
      headers: { Authorization: `Bearer ${token}` },
    }).then(r => r.json()).then(d => setAgents(Array.isArray(d) ? d : [])).catch(console.error).finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="p-3 sm:p-6 text-bah-muted">Loading agent rankings...</div>;

  const tierColors: Record<string, string> = {
    A: "bg-green-500/20 text-green-400 border-green-500/30",
    B: "bg-cyan-500/20 text-cyan-400 border-cyan-500/30",
    C: "bg-amber-500/20 text-amber-400 border-amber-500/30",
    D: "bg-red-500/20 text-red-400 border-red-500/30",
  };

  return (
    <div className="p-3 sm:p-6 max-w-4xl space-y-6">
      <h1 className="text-xl font-bold text-bah-heading">Agent Leaderboard</h1>
      <p className="text-xs text-bah-muted">Super admin view — AI agent performance ranking</p>

      <div className="bg-bah-surface border border-bah-border rounded-xl overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-bah-border text-left text-xs text-bah-muted uppercase tracking-wider">
              <th className="px-4 py-3">#</th>
              <th className="px-4 py-3">Agent</th>
              <th className="px-4 py-3">Tier</th>
              <th className="px-4 py-3">Score</th>
              <th className="px-4 py-3">Win Rate</th>
              <th className="px-4 py-3">Consistency</th>
              <th className="px-4 py-3">Trades</th>
            </tr>
          </thead>
          <tbody>
            {agents.map((a) => (
              <tr key={a.agent_id} className="border-b border-bah-border/30 hover:bg-white/[0.02]">
                <td className="px-4 py-3 text-bah-muted font-mono">{a.rank}</td>
                <td className="px-4 py-3">
                  <div className="font-medium text-bah-heading">{a.name}</div>
                </td>
                <td className="px-4 py-3">
                  <span className={`px-2 py-0.5 rounded-full text-[11px] font-bold border ${tierColors[a.tier] || tierColors.D}`}>
                    {a.tier}
                  </span>
                </td>
                <td className="px-4 py-3">
                  <div className="flex items-center gap-2">
                    <div className="w-16 h-1.5 bg-white/[0.04] rounded-full overflow-hidden">
                      <div className="h-full bg-bah-cyan rounded-full" style={{ width: `${a.composite_score * 100}%` }} />
                    </div>
                    <span className="font-mono text-bah-cyan">{(a.composite_score * 100).toFixed(0)}%</span>
                  </div>
                </td>
                <td className="px-4 py-3 font-mono text-sm">
                  <span className={a.win_rate >= 0.6 ? "text-green-400" : a.win_rate >= 0.45 ? "text-amber-400" : "text-red-400"}>
                    {(a.win_rate * 100).toFixed(1)}%
                  </span>
                </td>
                <td className="px-4 py-3 font-mono text-sm">{(a.consistency * 100).toFixed(0)}%</td>
                <td className="px-4 py-3 text-bah-muted">{a.total_trades}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {agents.length === 0 && (
          <div className="text-sm text-bah-muted text-center py-8">No agent data yet — agents will appear after signal cycles run</div>
        )}
      </div>
    </div>
  );
}
