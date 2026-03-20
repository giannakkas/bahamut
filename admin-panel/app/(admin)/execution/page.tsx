"use client";
import { useState, useEffect } from "react";
import { apiBase } from "@/lib/utils";

const AGENT_META: Record<string, { name: string; icon: string; color: string }> = {
  technical_agent: { name: "Technical", icon: "📊", color: "#3b82f6" },
  macro_agent: { name: "Macro", icon: "🌍", color: "#10b981" },
  volatility_agent: { name: "Volatility", icon: "🌊", color: "#f59e0b" },
  sentiment_agent: { name: "Sentiment", icon: "🎭", color: "#ef4444" },
  liquidity_agent: { name: "Liquidity / Whales", icon: "🐋", color: "#06b6d4" },
  risk_agent: { name: "Risk", icon: "🛡️", color: "#ef4444" },
};

function ScoreRing({ score }: { score: number }) {
  const color = score > 0.7 ? "#10b981" : score > 0.5 ? "#f59e0b" : "#ef4444";
  return (
    <div className="relative w-16 h-16">
      <svg viewBox="0 0 100 100" className="w-full h-full -rotate-90">
        <circle cx="50" cy="50" r="40" stroke="#2A2A4A" strokeWidth="6" fill="none" />
        <circle cx="50" cy="50" r="40" strokeWidth="6" fill="none"
          stroke={color} strokeDasharray={`${score * 251} 251`} strokeLinecap="round" />
      </svg>
      <div className="absolute inset-0 flex items-center justify-center">
        <span className="font-mono text-lg font-bold" style={{ color }}>{(score * 100).toFixed(0)}</span>
      </div>
    </div>
  );
}

function TradeCard({ asset, cycle, onApprove, approving }: {
  asset: string; cycle: any; onApprove: () => void; approving: boolean;
}) {
  const d = cycle?.decision || {};
  const agents = cycle?.agent_outputs || [];
  const challenges = cycle?.challenges || [];
  const [expanded, setExpanded] = useState(true);

  const dirColor = d.direction === "LONG" ? "#10b981" : d.direction === "SHORT" ? "#ef4444" : "#4a5568";
  const dirArrow = d.direction === "LONG" ? "▲" : d.direction === "SHORT" ? "▼" : "─";

  return (
    <div className="bg-[#0F0F1E] border border-[#2A2A4A] rounded-lg overflow-hidden">
      {/* Header */}
      <div className={`p-4 flex items-center justify-between cursor-pointer`}
        style={{ borderLeft: `4px solid ${dirColor}` }}
        onClick={() => setExpanded(!expanded)}>
        <div className="flex items-center gap-4">
          <div className="text-3xl font-bold" style={{ color: dirColor }}>{dirArrow}</div>
          <div>
            <div className="text-lg font-bold text-[#E8E8F0]">
              {asset} <span style={{ color: dirColor }}>{d.direction}</span>
            </div>
            <div className="text-xs text-[#555570]">
              {d.decision} · {d.trading_profile || "BALANCED"} · {d.execution_mode}
            </div>
          </div>
        </div>
        <div className="flex items-center gap-6">
          <ScoreRing score={d.final_score || 0} />
          <div className="text-right">
            <div className="text-sm text-[#8888AA]">Agreement</div>
            <div className="font-mono text-lg font-semibold text-[#E8E8F0]">
              {((d.agreement_pct || 0) * 100).toFixed(0)}%
            </div>
          </div>
          <span className="text-[#555570]">{expanded ? "▾" : "▸"}</span>
        </div>
      </div>

      {expanded && (
        <div className="border-t border-[#2A2A4A]">
          {/* Agent Council */}
          <div className="p-4">
            <div className="text-xs text-[#555570] mb-2 font-semibold uppercase tracking-wider">Agent Council</div>
            <div className="flex gap-2 flex-wrap">
              {agents.map((a: any) => {
                const meta = AGENT_META[a.agent_id] || { name: a.agent_id, icon: "?", color: "#888" };
                const arrow = a.directional_bias === "LONG" ? "▲" : a.directional_bias === "SHORT" ? "▼" : "─";
                const ac = a.directional_bias === "LONG" ? "#10b981" : a.directional_bias === "SHORT" ? "#ef4444" : "#555570";
                return (
                  <div key={a.agent_id} className="flex items-center gap-1.5 bg-[#161628] rounded-md px-2.5 py-1.5 border border-[#2A2A4A]">
                    <div className="w-5 h-5 rounded-full flex items-center justify-center text-[8px] font-bold text-white"
                      style={{ backgroundColor: meta.color }}>{meta.icon}</div>
                    <span className="text-xs text-[#8888AA]">{meta.name}</span>
                    <span className="text-xs font-semibold" style={{ color: ac }}>
                      {arrow}{((a.confidence || 0) * 100).toFixed(0)}%
                    </span>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Challenges */}
          {challenges.length > 0 && (
            <div className="px-4 pb-3">
              <div className="text-xs text-[#555570] mb-2 font-semibold uppercase tracking-wider">
                Challenges ({challenges.length})
              </div>
              {challenges.map((ch: any, i: number) => (
                <div key={i} className="flex items-center gap-2 text-xs py-1">
                  <span className="text-[#f59e0b] font-mono">[{i + 1}]</span>
                  <span className="text-[#8888AA]">{ch.challenger} → {ch.target_agent}</span>
                  <span className="text-[#555570]">({ch.challenge_type})</span>
                  <span className={`ml-auto font-semibold ${
                    ch.response === "VETO" ? "text-[#ef4444]" : ch.response === "PARTIAL" ? "text-[#f59e0b]" : "text-[#555570]"
                  }`}>{ch.response}</span>
                </div>
              ))}
            </div>
          )}

          {/* Risk flags */}
          {d.risk_flags?.length > 0 && (
            <div className="px-4 pb-3">
              <div className="text-xs text-[#f59e0b]">Risk flags: {Array.isArray(d.risk_flags) ? d.risk_flags.join(", ") : String(d.risk_flags)}</div>
            </div>
          )}

          {/* Price + timing */}
          <div className="px-4 pb-3 flex items-center gap-4 text-xs text-[#555570]">
            {cycle.market_price && <span>Price: <span className="font-mono text-[#E8E8F0]">{cycle.market_price}</span></span>}
            {cycle.elapsed_ms && <span>Elapsed: <span className="font-mono">{cycle.elapsed_ms}ms</span></span>}
            <span className="flex items-center gap-1">
              <span className="relative flex h-1.5 w-1.5">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-[#10b981] opacity-75" style={{ animationDuration: "3s" }} />
                <span className="relative inline-flex rounded-full h-1.5 w-1.5 bg-[#10b981]" />
              </span>
              Live Data
            </span>
          </div>

          {/* Actions */}
          {d.execution_mode === "APPROVAL" || d.execution_mode === "AUTO" && (
            <div className="p-4 border-t border-[#2A2A4A] bg-[#161628]/50 flex items-center gap-3">
              <button onClick={(e) => { e.stopPropagation(); onApprove(); }} disabled={approving}
                className="bg-[#10b981] hover:bg-[#10b981]/90 text-white font-semibold px-6 py-2 rounded-md text-sm transition-colors disabled:opacity-50">
                {approving ? "Approving..." : "Approve Trade"}
              </button>
              <button className="bg-[#E94560] hover:bg-[#E94560]/90 text-white font-semibold px-6 py-2 rounded-md text-sm transition-colors">
                Reject
              </button>
              <button className="bg-[#1C1C35] hover:bg-[#161628] text-[#8888AA] font-semibold px-6 py-2 rounded-md text-sm border border-[#2A2A4A] transition-colors">
                Snooze 30m
              </button>
              <a href="/agent-council" className="ml-auto text-xs text-[#6C63FF] hover:underline">
                View in Agent Council →
              </a>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default function ExecutionPage() {
  const [cycles, setCycles] = useState<any>({});
  const [loading, setLoading] = useState(true);
  const [approving, setApproving] = useState<string | null>(null);
  const [approvingAll, setApprovingAll] = useState(false);
  const [autoApprove, setAutoApprove] = useState(false);
  const [actions, setActions] = useState<Record<string, string>>({});
  const token = typeof window !== "undefined" ? sessionStorage.getItem("bah_token") : null;
  const headers = { Authorization: `Bearer ${token}`, "Content-Type": "application/json" };

  const load = async () => {
    try {
      const [cyclesRes, aaRes] = await Promise.all([
        fetch(`${apiBase()}/agents/latest-cycles`, { headers }),
        fetch(`${apiBase()}/admin/auto-approve`, { headers }),
      ]);
      setCycles(await cyclesRes.json());
      const aa = await aaRes.json();
      setAutoApprove(aa?.auto_approve || false);
    } catch (e) { console.error(e); }
    setLoading(false);
  };

  useEffect(() => { load(); const i = setInterval(load, 30000); return () => clearInterval(i); }, []);

  const allCycles = Object.entries(cycles);
  const pending = allCycles.filter(([a, c]: [string, any]) => c?.decision?.execution_mode === "APPROVAL" && !actions[a]);
  const autoTrades = allCycles.filter(([a, c]: [string, any]) => c?.decision?.execution_mode === "AUTO" && !actions[a]);
  const watching = allCycles.filter(([a, c]: [string, any]) => (c?.decision?.execution_mode === "WATCH" || !c?.decision?.execution_mode) && !actions[a]);

  const handleApprove = async (asset: string) => {
    setApproving(asset);
    try {
      await fetch(`${apiBase()}/execution/approve/${asset}`, { method: "POST", headers });
      setActions(prev => ({ ...prev, [asset]: "APPROVED" }));
    } catch (e) { console.error(e); }
    setApproving(null);
  };

  const handleApproveAll = async () => {
    setApprovingAll(true);
    try {
      await fetch(`${apiBase()}/execution/approve-all`, { method: "POST", headers });
      pending.forEach(([a]) => setActions(prev => ({ ...prev, [a]: "APPROVED" })));
      await load();
    } catch (e) { console.error(e); }
    setApprovingAll(false);
  };

  const toggleAutoApprove = async () => {
    const newVal = !autoApprove;
    try {
      await fetch(`${apiBase()}/admin/auto-approve`, {
        method: "POST", headers, body: JSON.stringify({ enabled: newVal }),
      });
      setAutoApprove(newVal);
    } catch (e) { console.error(e); }
  };

  if (loading) return <div className="p-6 text-[#555570]">Loading execution engine...</div>;

  return (
    <div className="p-6 max-w-5xl space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-[#E8E8F0]">Execution Engine</h1>
          <p className="text-sm text-[#8888AA] mt-1">
            {pending.length} pending approval · {autoTrades.length} auto-eligible · {watching.length} watch
          </p>
        </div>
        <div className="flex items-center gap-3">
          <button onClick={toggleAutoApprove}
            className={`px-4 py-2 rounded-lg text-xs font-semibold border transition-colors ${
              autoApprove
                ? "bg-[#10b981]/20 text-[#10b981] border-[#10b981]/30"
                : "bg-[#161628] text-[#8888AA] border-[#2A2A4A] hover:text-[#E8E8F0]"
            }`}>
            {autoApprove ? "⚡ Auto-Approve ON" : "Auto-Approve OFF"}
          </button>
          {pending.length > 0 && (
            <button onClick={handleApproveAll} disabled={approvingAll}
              className="px-4 py-2 bg-[#10b981]/20 text-[#10b981] border border-[#10b981]/30 rounded-lg text-xs font-semibold hover:bg-[#10b981]/30 disabled:opacity-50 transition-colors">
              {approvingAll ? "Approving..." : `Approve All (${pending.length})`}
            </button>
          )}
          <a href="/risk" className="text-sm text-[#E94560] hover:underline">Risk Control →</a>
        </div>
      </div>

      {/* Pending Approval */}
      {pending.length > 0 && (
        <div className="space-y-4">
          <div className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-[#f59e0b] animate-pulse" />
            <h2 className="text-sm font-semibold text-[#f59e0b]">Pending Approval ({pending.length})</h2>
          </div>
          {pending.map(([asset, cycle]: [string, any]) => (
            <TradeCard key={asset} asset={asset} cycle={cycle}
              onApprove={() => handleApprove(asset)} approving={approving === asset} />
          ))}
        </div>
      )}

      {/* Auto Trades */}
      {autoTrades.length > 0 && (
        <div className="space-y-4">
          <div className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-[#10b981]" />
            <h2 className="text-sm font-semibold text-[#10b981]">Auto-Eligible ({autoTrades.length})</h2>
          </div>
          {autoTrades.map(([asset, cycle]: [string, any]) => (
            <TradeCard key={asset} asset={asset} cycle={cycle}
              onApprove={() => handleApprove(asset)} approving={approving === asset} />
          ))}
        </div>
      )}

      {/* Watch Only */}
      {watching.length > 0 && (
        <div>
          <div className="flex items-center gap-2 mb-3">
            <h2 className="text-sm text-[#555570]">Watch Only ({watching.length})</h2>
          </div>
          <div className="bg-[#0F0F1E] border border-[#2A2A4A] rounded-lg overflow-hidden">
            {watching.map(([asset, cycle]: [string, any]) => {
              const d = cycle?.decision || {};
              const dirColor = d.direction === "LONG" ? "#10b981" : d.direction === "SHORT" ? "#ef4444" : "#555570";
              const dirArrow = d.direction === "LONG" ? "▲" : d.direction === "SHORT" ? "▼" : "─";
              return (
                <div key={asset} className="flex items-center justify-between px-4 py-3 border-b border-[#2A2A4A]/50 last:border-0">
                  <div className="flex items-center gap-3">
                    <span style={{ color: dirColor }}>{dirArrow}</span>
                    <span className="text-sm text-[#E8E8F0] font-medium">{asset}</span>
                    <span className="text-xs text-[#555570]">{d.direction} · {d.decision || "NO_TRADE"}</span>
                  </div>
                  <div className="flex items-center gap-3">
                    <span className="font-mono text-sm text-[#6C63FF]">{(d.final_score || 0).toFixed(2)}</span>
                    <span className="text-xs px-2 py-0.5 rounded-full bg-[#161628] text-[#555570] border border-[#2A2A4A]">WATCH</span>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {allCycles.length === 0 && (
        <div className="text-sm text-[#555570] text-center py-12">
          No signal cycles yet. Cycles run every 15 minutes.
        </div>
      )}
    </div>
  );
}
