"use client";

import { useState, useEffect } from "react";
import { apiBase } from "@/lib/utils";

export default function TrustPage() {
  const [learning, setLearning] = useState<any>(null);
  const [killSwitch, setKillSwitch] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const token = typeof window !== "undefined" ? sessionStorage.getItem("bah_token") : null;

  useEffect(() => {
    const load = async () => {
      try {
        const headers = { Authorization: `Bearer ${token}` };
        const [lp, ks] = await Promise.all([
          fetch(`${apiBase()}/trust/learning-progress`, { headers }).then(r => r.json()),
          fetch(`${apiBase()}/trust/kill-switch-status`, { headers }).then(r => r.json()),
        ]);
        setLearning(lp);
        setKillSwitch(ks);
      } catch (e) { console.error(e); }
      setLoading(false);
    };
    load();
  }, []);

  if (loading) return <div className="p-3 sm:p-6 text-bah-muted">Loading trust data...</div>;

  return (
    <div className="p-3 sm:p-6 max-w-4xl space-y-6">
      <h1 className="text-xl font-bold text-bah-heading">Trust & Intelligence</h1>
      <p className="text-xs text-bah-muted">Super admin view — system intelligence overview</p>

      {/* Learning Progress */}
      <div className="bg-bah-surface border border-bah-border rounded-xl p-5">
        <h2 className="text-sm font-semibold text-bah-heading mb-3">Learning Progress</h2>
        {learning && (
          <div className="space-y-3">
            <div className="flex items-center gap-4">
              <span className={`px-3 py-1 rounded-full text-xs font-semibold ${
                learning.status === "ready" ? "bg-green-500/20 text-green-400" :
                learning.status === "learning" ? "bg-cyan-500/20 text-cyan-400" :
                "bg-amber-500/20 text-amber-400"
              }`}>{learning.status?.toUpperCase()}</span>
              <span className="text-sm text-bah-muted">Progress: {learning.progress}%</span>
            </div>
            <div className="h-2 bg-white/[0.04] rounded-full overflow-hidden">
              <div className="h-full bg-bah-cyan rounded-full transition-all" style={{ width: `${learning.progress}%` }} />
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3 text-center">
              <div className="bg-white/[0.02] rounded-lg p-3">
                <div className="text-lg font-bold text-bah-heading">{learning.samples_collected}</div>
                <div className="text-[10px] text-bah-muted">Samples</div>
              </div>
              <div className="bg-white/[0.02] rounded-lg p-3">
                <div className="text-lg font-bold text-bah-heading">{learning.patterns_detected}</div>
                <div className="text-[10px] text-bah-muted">Patterns</div>
              </div>
              <div className="bg-white/[0.02] rounded-lg p-3">
                <div className="text-lg font-bold text-bah-heading">{learning.closed_trades}</div>
                <div className="text-[10px] text-bah-muted">Closed Trades</div>
              </div>
            </div>
            <div className="text-xs text-bah-muted">Next milestone: {learning.next_milestone}</div>
          </div>
        )}
      </div>

      {/* Kill Switch Recovery */}
      <div className="bg-bah-surface border border-bah-border rounded-xl p-5">
        <h2 className="text-sm font-semibold text-bah-heading mb-3">Kill Switch Recovery Status</h2>
        {killSwitch && (
          <div className="space-y-2">
            <div className="flex items-center gap-3">
              <span className={`px-3 py-1 rounded-full text-xs font-semibold ${
                killSwitch.status === "normal" || killSwitch.status === "recovered" ? "bg-green-500/20 text-green-400" :
                killSwitch.status === "active" ? "bg-red-500/20 text-red-400" :
                "bg-amber-500/20 text-amber-400"
              }`}>{killSwitch.status?.toUpperCase()}</span>
              <span className="text-xs text-bah-muted">Size multiplier: ×{killSwitch.size_multiplier}</span>
            </div>
            <div className="text-sm text-bah-subtle">{killSwitch.message}</div>
            {killSwitch.cooldown_remaining_seconds > 0 && (
              <div className="text-xs text-amber-400">Cooldown: {killSwitch.cooldown_remaining_seconds}s remaining</div>
            )}
            <div className="text-xs text-bah-muted">Triggers today: {killSwitch.trigger_count_today}</div>
          </div>
        )}
      </div>
    </div>
  );
}
