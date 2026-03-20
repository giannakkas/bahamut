"use client";
import { useState, useEffect } from "react";
import { apiBase } from "@/lib/utils";

export default function ExecutionPage() {
  const [cycles, setCycles] = useState<any>({});
  const [loading, setLoading] = useState(true);
  const [approving, setApproving] = useState<string | null>(null);
  const [approvingAll, setApprovingAll] = useState(false);
  const [autoApprove, setAutoApprove] = useState(false);
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

  useEffect(() => { load(); }, []);

  const allCycles = Object.entries(cycles);
  const pending = allCycles.filter(([, c]: [string, any]) => c?.decision?.execution_mode === "APPROVAL");
  const autoTrades = allCycles.filter(([, c]: [string, any]) => c?.decision?.execution_mode === "AUTO");
  const watching = allCycles.filter(([, c]: [string, any]) => c?.decision?.execution_mode === "WATCH" || !c?.decision?.execution_mode);

  const handleApprove = async (asset: string) => {
    setApproving(asset);
    try {
      await fetch(`${apiBase()}/execution/approve/${asset}`, { method: "POST", headers });
      await load();
    } catch (e) { console.error(e); }
    setApproving(null);
  };

  const handleApproveAll = async () => {
    setApprovingAll(true);
    try {
      await fetch(`${apiBase()}/execution/approve-all`, { method: "POST", headers });
      await load();
    } catch (e) { console.error(e); }
    setApprovingAll(false);
  };

  if (loading) return <div className="p-6 text-bah-muted">Loading execution engine...</div>;

  return (
    <div className="p-6 max-w-5xl space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-bah-heading">Execution Engine</h1>
          <p className="text-xs text-bah-muted mt-1">
            {pending.length} pending approval · {autoTrades.length} auto-eligible · {watching.length} watch
          </p>
        </div>
        <div className="flex gap-2 items-center">
          {/* Auto-Approve Toggle */}
          <button
            onClick={async () => {
              const newVal = !autoApprove;
              try {
                await fetch(`${apiBase()}/admin/auto-approve`, {
                  method: "POST", headers,
                  body: JSON.stringify({ enabled: newVal }),
                });
                setAutoApprove(newVal);
              } catch (e) { console.error(e); }
            }}
            className={`px-4 py-2 rounded-lg text-xs font-semibold border transition-colors ${
              autoApprove
                ? "bg-green-500/20 text-green-400 border-green-500/40"
                : "bg-white/[0.02] text-bah-muted border-bah-border hover:text-bah-heading"
            }`}
          >
            {autoApprove ? "⚡ Auto-Approve ON" : "Auto-Approve OFF"}
          </button>
          {pending.length > 0 && (
            <button onClick={handleApproveAll} disabled={approvingAll}
              className="px-4 py-2 bg-green-500/20 text-green-400 border border-green-500/30 rounded-lg text-xs font-semibold hover:bg-green-500/30 disabled:opacity-50 transition-colors">
              {approvingAll ? "Approving..." : `Approve All (${pending.length})`}
            </button>
          )}
          <button onClick={() => { setLoading(true); load(); }}
            className="px-3 py-2 border border-bah-border rounded-lg text-xs text-bah-muted hover:text-bah-heading transition-colors">
            ↻ Refresh
          </button>
        </div>
      </div>

      {/* Pending Approval */}
      {pending.length > 0 && (
        <div>
          <div className="flex items-center gap-2 mb-3">
            <span className="w-2 h-2 rounded-full bg-amber-400 animate-pulse" />
            <h2 className="text-sm font-semibold text-amber-400">Pending Approval ({pending.length})</h2>
          </div>
          <div className="space-y-2">
            {pending.map(([asset, cycle]: [string, any]) => {
              const d = cycle?.decision || {};
              return (
                <div key={asset} className="bg-bah-surface border border-amber-500/20 rounded-xl p-4">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <span className={`text-lg ${d.direction === "LONG" ? "text-green-400" : "text-red-400"}`}>
                        {d.direction === "LONG" ? "▲" : "▼"}
                      </span>
                      <div>
                        <span className="font-bold text-bah-heading text-lg">{asset}</span>
                        <span className={`ml-2 font-semibold ${d.direction === "LONG" ? "text-green-400" : "text-red-400"}`}>
                          {d.direction}
                        </span>
                      </div>
                      <span className="text-xs text-bah-muted">{d.decision} · BALANCED · APPROVAL</span>
                    </div>
                    <div className="flex items-center gap-4">
                      <div className="text-right">
                        <div className="text-2xl font-mono font-bold text-purple-400">{(d.final_score || 0).toFixed(0)}</div>
                        <div className="text-[10px] text-bah-muted">Agreement {((d.agreement_pct || 0) * 100).toFixed(0)}%</div>
                      </div>
                      <button onClick={() => handleApprove(asset)} disabled={approving === asset}
                        className="px-4 py-2 bg-green-500 text-black rounded-lg text-xs font-bold hover:bg-green-400 disabled:opacity-50 transition-colors">
                        {approving === asset ? "..." : "Approve"}
                      </button>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Auto Trades */}
      {autoTrades.length > 0 && (
        <div>
          <div className="flex items-center gap-2 mb-3">
            <span className="w-2 h-2 rounded-full bg-green-400" />
            <h2 className="text-sm font-semibold text-green-400">Auto-Eligible ({autoTrades.length})</h2>
          </div>
          <div className="bg-bah-surface border border-bah-border rounded-xl overflow-hidden">
            {autoTrades.map(([asset, cycle]: [string, any]) => {
              const d = cycle?.decision || {};
              return (
                <div key={asset} className="flex items-center justify-between px-4 py-3 border-b border-bah-border/30 last:border-0">
                  <div className="flex items-center gap-3">
                    <span className={d.direction === "LONG" ? "text-green-400" : "text-red-400"}>
                      {d.direction === "LONG" ? "▲" : "▼"}
                    </span>
                    <span className="font-semibold text-bah-heading">{asset}</span>
                    <span className="text-xs text-bah-muted">{d.direction}</span>
                  </div>
                  <div className="flex items-center gap-3">
                    <span className="font-mono text-purple-400 font-bold">{(d.final_score || 0).toFixed(2)}</span>
                    <span className="text-xs px-2 py-0.5 rounded-full bg-green-500/20 text-green-400 border border-green-500/30">AUTO</span>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Watching */}
      {watching.length > 0 && (
        <div>
          <div className="flex items-center gap-2 mb-3">
            <span className="w-2 h-2 rounded-full bg-gray-400" />
            <h2 className="text-sm font-semibold text-bah-muted">Watching ({watching.length})</h2>
          </div>
          <div className="bg-bah-surface border border-bah-border rounded-xl overflow-hidden">
            {watching.map(([asset, cycle]: [string, any]) => {
              const d = cycle?.decision || {};
              return (
                <div key={asset} className="flex items-center justify-between px-4 py-2 border-b border-bah-border/30 last:border-0">
                  <div className="flex items-center gap-3">
                    <span className="text-bah-muted">─</span>
                    <span className="text-sm text-bah-subtle">{asset}</span>
                    <span className="text-xs text-bah-muted">{d.direction || "—"}</span>
                  </div>
                  <span className="font-mono text-xs text-bah-muted">{(d.final_score || 0).toFixed(2)}</span>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {allCycles.length === 0 && (
        <div className="text-sm text-bah-muted text-center py-12">No signal cycles yet. Cycles run every 15 minutes.</div>
      )}
    </div>
  );
}
