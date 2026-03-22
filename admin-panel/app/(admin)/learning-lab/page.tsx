"use client";
import { useState, useEffect } from "react";
import { apiBase } from "@/lib/utils";

export default function LearningLabPage() {
  const [calibration, setCalibration] = useState<any[]>([]);
  const [progress, setProgress] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const token = typeof window !== "undefined" ? sessionStorage.getItem("bah_token") : null;
  const headers = { Authorization: `Bearer ${token}` };

  useEffect(() => {
    Promise.all([
      fetch(`${apiBase()}/trust/learning-progress`, { headers }).then(r => r.json()).catch(() => null),
      fetch(`${apiBase()}/agents/calibration`, { headers }).then(r => r.json()).catch(() => []),
    ]).then(([p, c]) => { setProgress(p); setCalibration(Array.isArray(c) ? c : []); setLoading(false); });
  }, []);

  if (loading) return <div className="p-3 sm:p-6 text-bah-muted">Loading learning lab...</div>;

  return (
    <div className="p-3 sm:p-6 max-w-5xl space-y-6">
      <h1 className="text-xl font-bold text-bah-heading">Learning Lab</h1>
      <p className="text-xs text-bah-muted">System calibration, learning progress, and training data</p>

      {progress && (
        <div className="bg-bah-surface border border-bah-border rounded-xl p-5">
          <h2 className="text-sm font-semibold text-bah-heading mb-3">Learning Status</h2>
          <div className="flex items-center gap-4 mb-3">
            <span className={`px-3 py-1 rounded-full text-xs font-semibold ${
              progress.status === "ready" ? "bg-green-500/20 text-green-400" :
              progress.status === "learning" ? "bg-cyan-500/20 text-cyan-400" :
              "bg-amber-500/20 text-amber-400"}`}>{progress.status?.toUpperCase()}</span>
            <span className="text-sm text-bah-muted">{progress.progress}% complete</span>
          </div>
          <div className="h-2 bg-white/[0.04] rounded-full overflow-hidden mb-4">
            <div className="h-full bg-bah-cyan rounded-full transition-all" style={{ width: `${progress.progress}%` }} />
          </div>
          {progress.milestones && (
            <div className="space-y-2">
              {progress.milestones.map((ms: any, i: number) => (
                <div key={i} className="flex items-center gap-2 text-xs">
                  <span className={ms.reached ? "text-green-400" : "text-bah-muted"}>{ms.reached ? "✓" : "○"}</span>
                  <span className={ms.reached ? "text-bah-heading" : "text-bah-muted"}>{ms.label}</span>
                  <span className="text-bah-muted">({ms.required} samples)</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      <div className="bg-bah-surface border border-bah-border rounded-xl p-5">
        <h2 className="text-sm font-semibold text-bah-heading mb-3">Calibration Runs</h2>
        {calibration.length > 0 ? (
          <div className="space-y-2">
            {calibration.slice(0, 10).map((c: any, i: number) => (
              <div key={i} className="flex justify-between items-center py-2 border-b border-bah-border/30 last:border-0 text-xs">
                <span className="text-bah-heading">{c.agent || c.agent_name || "System"}</span>
                <span className="text-bah-muted">{c.accuracy ? `${(c.accuracy * 100).toFixed(1)}% accuracy` : "—"}</span>
                <span className="text-bah-muted">{c.created_at || c.timestamp || "—"}</span>
              </div>
            ))}
          </div>
        ) : (
          <div className="text-sm text-bah-muted text-center py-6">No calibration data yet — calibration runs after enough trades close</div>
        )}
      </div>
    </div>
  );
}
