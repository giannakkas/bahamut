"use client";

import { useState, useEffect } from "react";
import { apiBase } from "@/lib/utils";

export default function AdaptiveRiskPage() {
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const token = typeof window !== "undefined" ? sessionStorage.getItem("bah_token") : null;

  useEffect(() => {
    fetch(`${apiBase()}/trust/risk-adaptation`, {
      headers: { Authorization: `Bearer ${token}` },
    }).then(r => r.json()).then(setData).catch(console.error).finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="p-3 sm:p-6 text-bah-muted">Loading adaptive risk...</div>;

  const conditions = data?.conditions || {};
  const adjustments = data?.adjustments || {};

  return (
    <div className="p-3 sm:p-6 max-w-4xl space-y-6">
      <h1 className="text-xl font-bold text-bah-heading">Adaptive Risk Engine</h1>
      <p className="text-xs text-bah-muted">Super admin view — dynamic threshold adjustments</p>

      {/* Current Conditions */}
      <div className="bg-bah-surface border border-bah-border rounded-xl p-5">
        <h2 className="text-sm font-semibold text-bah-heading mb-3">Market Conditions</h2>
        <div className="grid grid-cols-4 gap-3">
          {[
            { label: "Volatility", value: conditions.volatility_level || "—", color: conditions.volatility_level === "high" ? "text-red-400" : "text-green-400" },
            { label: "Drawdown", value: conditions.drawdown_trend || "—", color: conditions.drawdown_trend === "worsening" ? "text-red-400" : "text-green-400" },
            { label: "Streak", value: conditions.streak || 0, color: (conditions.streak || 0) < 0 ? "text-red-400" : "text-green-400" },
            { label: "Win Rate", value: `${((conditions.recent_win_rate || 0) * 100).toFixed(0)}%`, color: "text-bah-cyan" },
          ].map(item => (
            <div key={item.label} className="bg-white/[0.02] rounded-lg p-3 text-center">
              <div className={`text-lg font-bold ${item.color}`}>{item.value}</div>
              <div className="text-[10px] text-bah-muted uppercase">{item.label}</div>
            </div>
          ))}
        </div>
      </div>

      {/* Threshold Adjustments */}
      <div className="bg-bah-surface border border-bah-border rounded-xl p-5">
        <h2 className="text-sm font-semibold text-bah-heading mb-3">Active Adjustments</h2>
        <div className="space-y-3">
          {Object.entries(adjustments).map(([key, adj]: [string, any]) => (
            <div key={key} className="flex items-center justify-between py-2 border-b border-bah-border/30 last:border-0">
              <div>
                <div className="text-sm text-bah-heading font-medium">{key.replace(/_/g, " ").replace(/\b\w/g, l => l.toUpperCase())}</div>
                <div className="text-[10px] text-bah-muted">{adj.reason}</div>
              </div>
              <div className="text-right">
                <div className="text-sm font-mono">
                  <span className="text-bah-muted">{adj.base}</span>
                  {adj.delta !== 0 && (
                    <span className={adj.delta > 0 ? "text-green-400" : "text-red-400"}>
                      {" "}{adj.delta > 0 ? "+" : ""}{adj.delta}
                    </span>
                  )}
                  <span className="text-bah-cyan font-bold ml-2">→ {adj.adjusted}</span>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
