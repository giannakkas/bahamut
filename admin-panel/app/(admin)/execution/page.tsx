"use client";
import { useState, useEffect } from "react";
import { apiBase } from "@/lib/utils";

export default function ExecutionPage() {
  const [executions, setExecutions] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const token = typeof window !== "undefined" ? sessionStorage.getItem("bah_token") : null;

  useEffect(() => {
    fetch(`${apiBase()}/execution/history`, { headers: { Authorization: `Bearer ${token}` } })
      .then(r => r.json()).then(d => setExecutions(Array.isArray(d) ? d : []))
      .catch(() => setExecutions([])).finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="p-6 text-bah-muted">Loading executions...</div>;

  return (
    <div className="p-6 max-w-5xl space-y-6">
      <h1 className="text-xl font-bold text-bah-heading">Execution Monitor</h1>
      <p className="text-xs text-bah-muted">Trade execution history and pending approvals</p>

      <div className="bg-bah-surface border border-bah-border rounded-xl overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-bah-border text-xs text-bah-muted uppercase">
              <th className="px-4 py-2 text-left">Asset</th>
              <th className="px-4 py-2 text-left">Direction</th>
              <th className="px-4 py-2 text-left">Mode</th>
              <th className="px-4 py-2 text-right">Score</th>
              <th className="px-4 py-2 text-left">Status</th>
              <th className="px-4 py-2 text-left">Time</th>
            </tr>
          </thead>
          <tbody>
            {executions.map((e: any, i: number) => (
              <tr key={i} className="border-b border-bah-border/30 hover:bg-white/[0.02]">
                <td className="px-4 py-2 font-medium text-bah-heading">{e.asset}</td>
                <td className="px-4 py-2"><span className={e.direction === "LONG" ? "text-green-400" : "text-red-400"}>{e.direction}</span></td>
                <td className="px-4 py-2 text-xs text-bah-muted">{e.execution_mode}</td>
                <td className="px-4 py-2 text-right font-mono text-purple-400">{(e.score || 0).toFixed(2)}</td>
                <td className="px-4 py-2 text-xs">{e.status}</td>
                <td className="px-4 py-2 text-xs text-bah-muted">{e.created_at || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {executions.length === 0 && <div className="text-sm text-bah-muted text-center py-8">No execution history yet</div>}
      </div>
    </div>
  );
}
