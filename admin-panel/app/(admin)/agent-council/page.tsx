"use client";
import { useState, useEffect } from "react";
import { apiBase } from "@/lib/utils";

export default function AgentCouncilPage() {
  const [cycles, setCycles] = useState<any>({});
  const [trustScores, setTrustScores] = useState<any>({});
  const [loading, setLoading] = useState(true);
  const token = typeof window !== "undefined" ? sessionStorage.getItem("bah_token") : null;
  const headers = { Authorization: `Bearer ${token}` };

  useEffect(() => {
    Promise.all([
      fetch(`${apiBase()}/agents/latest-cycles`, { headers }).then(r => r.json()).catch(() => ({})),
      fetch(`${apiBase()}/agents/trust-scores`, { headers }).then(r => r.json()).catch(() => ({})),
    ]).then(([c, ts]) => { setCycles(c); setTrustScores(ts); setLoading(false); });
  }, []);

  if (loading) return <div className="p-3 sm:p-6 text-bah-muted">Loading agent council...</div>;

  // Parse trust scores — extract global score from nested object
  const agents = Object.entries(trustScores).map(([name, data]: [string, any]) => {
    let globalScore = 0;
    let provisional = true;
    if (typeof data === "number") {
      globalScore = data;
      provisional = false;
    } else if (data && typeof data === "object") {
      // Structure: { global: { score, samples, provisional, ... }, regime:..., asset:..., tf:... }
      const g = data.global || data;
      globalScore = g.score ?? g.trust_score ?? 0;
      provisional = g.provisional ?? true;
    }
    return { name, globalScore, provisional };
  });

  const assets = Object.keys(cycles);

  return (
    <div className="p-3 sm:p-6 max-w-5xl space-y-6">
      <h1 className="text-xl font-bold text-bah-heading">Agent Council</h1>
      <p className="text-xs text-bah-muted">Latest consensus cycles and agent trust scores</p>

      {/* Trust Scores */}
      {agents.length > 0 && (
        <div className="bg-bah-surface border border-bah-border rounded-xl p-5">
          <h2 className="text-sm font-semibold text-bah-heading mb-3">Agent Trust Scores</h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
            {agents.map((a) => (
              <div key={a.name} className="bg-white/[0.02] rounded-lg p-4 text-center border border-bah-border/30">
                <div className="text-xs text-bah-muted mb-2">
                  {a.name.replace(/_/g, " ").replace(/\b\w/g, l => l.toUpperCase())}
                </div>
                <div className={`text-2xl font-bold ${a.globalScore >= 0.8 ? "text-green-400" : a.globalScore >= 0.5 ? "text-bah-cyan" : "text-amber-400"}`}>
                  {(a.globalScore * 100).toFixed(0)}%
                </div>
                {a.provisional && (
                  <div className="text-[10px] text-amber-400 mt-1">PROVISIONAL</div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Latest Cycles */}
      <div className="bg-bah-surface border border-bah-border rounded-xl overflow-hidden">
        <div className="px-4 py-3 border-b border-bah-border">
          <h2 className="text-sm font-semibold text-bah-heading">Latest Signal Cycles ({assets.length} assets)</h2>
        </div>
        {assets.length > 0 ? (
          <div className="divide-y divide-bah-border/30">
            {assets.map(asset => {
              const cycle = cycles[asset];
              const d = cycle?.decision || {};
              return (
                <div key={asset} className="px-4 py-3 flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <span className={`text-sm ${
                      d.direction === "LONG" ? "text-green-400" :
                      d.direction === "SHORT" ? "text-red-400" : "text-bah-muted"
                    }`}>
                      {d.direction === "LONG" ? "▲" : d.direction === "SHORT" ? "▼" : "─"}
                    </span>
                    <div>
                      <span className="font-semibold text-bah-heading">{asset}</span>
                      <span className="ml-2 text-xs text-bah-muted">{d.direction || "—"}</span>
                      <span className="ml-2 text-xs text-bah-muted">{d.decision || "NO_TRADE"}</span>
                    </div>
                  </div>
                  <div className="flex items-center gap-4">
                    <span className="text-lg font-mono font-bold text-purple-400">{(d.final_score || 0).toFixed(2)}</span>
                    <span className={`text-xs px-2 py-0.5 rounded-full font-semibold ${
                      d.execution_mode === "AUTO" ? "bg-green-500/20 text-green-400 border border-green-500/30" :
                      d.execution_mode === "APPROVAL" ? "bg-amber-500/20 text-amber-400 border border-amber-500/30" :
                      "bg-gray-500/20 text-gray-400 border border-gray-500/30"
                    }`}>{d.execution_mode || "WATCH"}</span>
                  </div>
                </div>
              );
            })}
          </div>
        ) : (
          <div className="text-sm text-bah-muted text-center py-8">No signal cycles yet. Cycles run every 15 minutes.</div>
        )}
      </div>
    </div>
  );
}
