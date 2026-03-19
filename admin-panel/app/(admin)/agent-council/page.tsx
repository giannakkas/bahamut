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

  if (loading) return <div className="p-6 text-bah-muted">Loading agent council...</div>;

  const assets = Object.keys(cycles);

  return (
    <div className="p-6 max-w-5xl space-y-6">
      <h1 className="text-xl font-bold text-bah-heading">Agent Council</h1>
      <p className="text-xs text-bah-muted">Latest consensus cycles and agent trust scores</p>

      {/* Trust Scores */}
      {Object.keys(trustScores).length > 0 && (
        <div className="bg-bah-surface border border-bah-border rounded-xl p-5">
          <h2 className="text-sm font-semibold text-bah-heading mb-3">Agent Trust Scores</h2>
          <div className="grid grid-cols-3 gap-3">
            {Object.entries(trustScores).map(([agent, score]: [string, any]) => (
              <div key={agent} className="bg-white/[0.02] rounded-lg p-3 text-center">
                <div className="text-xs text-bah-muted mb-1">{agent.replace(/_/g, " ").replace(/\b\w/g, l => l.toUpperCase())}</div>
                <div className="text-lg font-bold text-bah-cyan">{typeof score === "number" ? (score * 100).toFixed(0) + "%" : JSON.stringify(score)}</div>
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
                  <div>
                    <span className="font-semibold text-bah-heading">{asset}</span>
                    <span className={`ml-2 text-xs ${d.direction === "LONG" ? "text-green-400" : d.direction === "SHORT" ? "text-red-400" : "text-bah-muted"}`}>
                      {d.direction || "—"}
                    </span>
                    <span className="ml-2 text-xs text-bah-muted">{d.decision || "NO_TRADE"}</span>
                  </div>
                  <div className="text-right">
                    <span className="text-lg font-mono font-bold text-purple-400">{(d.final_score || 0).toFixed(2)}</span>
                    <span className={`ml-3 text-xs px-2 py-0.5 rounded-full ${
                      d.execution_mode === "AUTO" ? "bg-green-500/20 text-green-400" :
                      d.execution_mode === "APPROVAL" ? "bg-amber-500/20 text-amber-400" :
                      "bg-gray-500/20 text-gray-400"
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
