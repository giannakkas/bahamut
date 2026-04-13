"use client";
import React, { useState, useEffect, useCallback } from "react";
import { apiBase } from "@/lib/utils";

const pnlC = (n: number) => n > 0.01 ? "text-green-400" : n < -0.01 ? "text-red-400" : "text-bah-muted";
const trustC = (t: number) => t >= 0.6 ? "text-green-400" : t >= 0.5 ? "text-yellow-400" : "text-red-400";
const matC = (m: string) => m === "mature" ? "text-green-400" : m === "developing" ? "text-yellow-400" : "text-bah-muted";

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="bg-bah-card border border-bah-border rounded-xl p-4">
      <h3 className="text-[11px] font-bold text-bah-muted uppercase tracking-wider mb-3">{title}</h3>
      {children}
    </div>
  );
}

function TrustBar({ value, label }: { value: number; label: string }) {
  const pct = Math.min(100, Math.max(0, value * 100));
  const color = value >= 0.6 ? "bg-green-500" : value >= 0.5 ? "bg-yellow-500" : "bg-red-500";
  return (
    <div className="flex items-center gap-2">
      <span className="text-[10px] text-bah-muted w-12 text-right">{label}</span>
      <div className="flex-1 h-3 bg-bah-surface rounded-full overflow-hidden">
        <div className={`h-full ${color} rounded-full`} style={{ width: `${pct}%` }} />
      </div>
      <span className={`text-[11px] font-bold w-10 ${trustC(value)}`}>{value.toFixed(3)}</span>
    </div>
  );
}

export default function TrustPage() {
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState<"overview" | "patterns" | "assets" | "regimes">("overview");

  const load = useCallback(async () => {
    try {
      const t = localStorage.getItem("bahamut_admin_token");
      const h: Record<string, string> = t ? { Authorization: `Bearer ${t}` } : {};
      const r = await fetch(`${apiBase()}/training/trust-dashboard`, { headers: h });
      if (r.ok) setData(await r.json());
    } catch {}
    setLoading(false);
  }, []);

  useEffect(() => { load(); }, [load]);
  if (loading) return <div className="p-8 text-bah-muted">Loading trust data...</div>;
  if (!data || data.error) return <div className="p-8 text-red-400">Error: {data?.error || "No data"}</div>;

  const strategies = data.strategies || {};
  const patterns = data.patterns || {};
  const STRAT_NAMES: Record<string, string> = { "v5_base": "V5 · EMA Trend", "v9_breakout": "V9 · Breakout", "v10_mean_reversion": "V10 · Mean Reversion" };

  return (
    <div className="space-y-4 p-4 max-w-[1400px] mx-auto">
      <h1 className="text-xl font-black text-bah-heading">Trust Dashboard</h1>
      <p className="text-xs text-bah-muted -mt-2">Monitor trust scores, pattern performance, and learning progress to optimize the system.</p>

      {/* Strategy Trust Overview */}
      <Section title="Strategy Trust Scores">
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
          {Object.entries(strategies).map(([name, s]: [string, any]) => (
            <div key={name} className={`border rounded-lg p-3 ${s.trust >= 0.6 ? "border-green-500/30 bg-green-500/5" : s.trust >= 0.5 ? "border-yellow-500/30 bg-yellow-500/5" : "border-red-500/30 bg-red-500/5"}`}>
              <div className="text-xs font-bold text-bah-heading">{STRAT_NAMES[name] || name}</div>
              <div className={`text-3xl font-black mt-1 ${trustC(s.trust)}`}>{s.trust.toFixed(3)}</div>
              <div className="w-full h-2 bg-bah-surface rounded-full mt-2 overflow-hidden">
                <div className={`h-full rounded-full ${s.trust >= 0.6 ? "bg-green-500" : s.trust >= 0.5 ? "bg-yellow-500" : "bg-red-500"}`}
                     style={{ width: `${s.trust * 100}%` }} />
              </div>
              <div className="grid grid-cols-3 gap-1 mt-2 text-[9px]">
                <div><span className="text-bah-muted">Samples:</span> <span className="text-bah-heading font-bold">{s.samples}</span></div>
                <div><span className="text-bah-muted">WR:</span> <span className="text-bah-heading font-bold">{(s.wr * 100).toFixed(0)}%</span></div>
                <div><span className="text-bah-muted">Mat:</span> <span className={`font-bold ${matC(s.maturity)}`}>{s.maturity}</span></div>
              </div>
            </div>
          ))}
        </div>
      </Section>

      {/* Tabs */}
      <div className="flex gap-2">
        {(["overview", "patterns", "assets", "regimes"] as const).map(t => (
          <button key={t} onClick={() => setTab(t)}
            className={`px-3 py-1.5 rounded-lg text-xs font-bold ${tab === t ? "bg-bah-cyan text-black" : "bg-bah-surface text-bah-muted hover:text-bah-heading"}`}>
            {t === "overview" ? "Best & Worst" : t === "patterns" ? "All Patterns" : t === "assets" ? "By Asset" : "By Regime"}
          </button>
        ))}
      </div>

      {tab === "overview" && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {/* Best Patterns */}
          <Section title="🏆 Best Patterns (by expectancy)">
            <div className="space-y-1.5">
              {(patterns.best || []).map((p: any, i: number) => (
                <div key={i} className="flex items-center justify-between text-xs py-1 border-b border-bah-border/20">
                  <div>
                    <span className="font-bold text-bah-heading">{p.key}</span>
                    <span className={`ml-2 text-[9px] font-bold ${matC(p.maturity)}`}>{p.maturity}</span>
                  </div>
                  <div className="flex gap-3">
                    <span className="text-bah-muted">{p.trades}T</span>
                    <span className={`font-bold ${pnlC(p.expectancy)}`}>{p.expectancy > 0 ? "+" : ""}{p.expectancy.toFixed(3)}R</span>
                    <span className={trustC(p.trust)}>{p.trust.toFixed(3)}</span>
                  </div>
                </div>
              ))}
            </div>
          </Section>

          {/* Worst Patterns */}
          <Section title="⚠️ Worst Patterns (watch these)">
            <div className="space-y-1.5">
              {(patterns.worst || []).map((p: any, i: number) => (
                <div key={i} className="flex items-center justify-between text-xs py-1 border-b border-bah-border/20">
                  <div>
                    <span className="font-bold text-bah-heading">{p.key}</span>
                    <span className={`ml-2 text-[9px] font-bold ${matC(p.maturity)}`}>{p.maturity}</span>
                  </div>
                  <div className="flex gap-3">
                    <span className="text-bah-muted">{p.trades}T</span>
                    <span className={`font-bold ${pnlC(p.expectancy)}`}>{p.expectancy > 0 ? "+" : ""}{p.expectancy.toFixed(3)}R</span>
                    <span className={trustC(p.trust)}>{p.trust.toFixed(3)}</span>
                  </div>
                </div>
              ))}
            </div>
          </Section>

          {/* Most Traded */}
          <Section title="📊 Most Traded Patterns">
            <div className="space-y-1.5">
              {(patterns.most_traded || []).map((p: any, i: number) => (
                <div key={i} className="flex items-center justify-between text-xs py-1 border-b border-bah-border/20">
                  <span className="font-bold text-bah-heading">{p.key}</span>
                  <div className="flex gap-3">
                    <span className="text-bah-heading font-bold">{p.trades}T</span>
                    <span className={`${pnlC(p.expectancy)}`}>{p.expectancy.toFixed(3)}R</span>
                    <span className={trustC(p.trust)}>{p.trust.toFixed(3)}</span>
                  </div>
                </div>
              ))}
            </div>
          </Section>

          {/* Exit Stats */}
          <Section title="🚪 Exit Reason Analysis">
            <div className="space-y-2">
              {Object.entries(data.exit_stats || {}).map(([reason, s]: [string, any]) => (
                <div key={reason} className="flex items-center justify-between text-xs py-1 border-b border-bah-border/20">
                  <span className={`font-bold ${reason === "TP" ? "text-green-400" : reason === "SL" ? "text-red-400" : "text-yellow-400"}`}>{reason}</span>
                  <div className="flex gap-3">
                    <span className="text-bah-muted">{s.count} trades</span>
                    <span className={pnlC(s.avg_pnl)}>avg {s.avg_pnl > 0 ? "+" : ""}{s.avg_pnl.toFixed(2)}</span>
                    <span className={pnlC(s.avg_r)}>avg {s.avg_r.toFixed(3)}R</span>
                  </div>
                </div>
              ))}
            </div>
          </Section>
        </div>
      )}

      {tab === "patterns" && (
        <Section title="All Pattern Trust Scores">
          <div className="space-y-1">
            {(patterns.most_traded || []).concat(patterns.best || [], patterns.worst || [])
              .filter((p: any, i: number, arr: any[]) => arr.findIndex((x: any) => x.key === p.key) === i)
              .sort((a: any, b: any) => b.trust - a.trust)
              .map((p: any, i: number) => (
                <TrustBar key={i} value={p.trust} label={p.key.split(":").slice(1).join(":")} />
              ))}
          </div>
        </Section>
      )}

      {tab === "assets" && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <Section title="💰 Best Assets">
            <table className="w-full text-xs">
              <thead><tr className="text-bah-muted text-[10px]">
                <th className="text-left">Asset</th><th className="text-left">Class</th><th className="text-right">Trades</th>
                <th className="text-right">WR</th><th className="text-right">PnL</th><th className="text-right">Avg R</th>
              </tr></thead>
              <tbody>
                {(data.best_assets || []).map((a: any, i: number) => (
                  <tr key={i} className="border-t border-bah-border/20">
                    <td className="py-1 font-bold text-bah-heading">{a.asset}</td>
                    <td className="text-bah-muted">{a.class}</td>
                    <td className="text-right">{a.trades}</td>
                    <td className="text-right">{(a.wr * 100).toFixed(0)}%</td>
                    <td className={`text-right font-bold ${pnlC(a.pnl)}`}>+${a.pnl.toFixed(0)}</td>
                    <td className={`text-right ${pnlC(a.avg_r)}`}>{a.avg_r.toFixed(3)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Section>

          <Section title="📉 Worst Assets">
            <table className="w-full text-xs">
              <thead><tr className="text-bah-muted text-[10px]">
                <th className="text-left">Asset</th><th className="text-left">Class</th><th className="text-right">Trades</th>
                <th className="text-right">WR</th><th className="text-right">PnL</th><th className="text-right">Avg R</th>
              </tr></thead>
              <tbody>
                {(data.worst_assets || []).map((a: any, i: number) => (
                  <tr key={i} className="border-t border-bah-border/20">
                    <td className="py-1 font-bold text-bah-heading">{a.asset}</td>
                    <td className="text-bah-muted">{a.class}</td>
                    <td className="text-right">{a.trades}</td>
                    <td className="text-right">{(a.wr * 100).toFixed(0)}%</td>
                    <td className={`text-right font-bold text-red-400`}>${a.pnl.toFixed(0)}</td>
                    <td className={`text-right ${pnlC(a.avg_r)}`}>{a.avg_r.toFixed(3)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Section>
        </div>
      )}

      {tab === "regimes" && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <Section title="Regime Performance">
            <div className="space-y-3">
              {Object.entries(data.regime_stats || {}).map(([regime, s]: [string, any]) => (
                <div key={regime} className={`border rounded-lg p-3 ${s.pnl >= 0 ? "border-green-500/20 bg-green-500/5" : "border-red-500/20 bg-red-500/5"}`}>
                  <div className="flex justify-between items-center">
                    <span className="text-sm font-black text-bah-heading">{regime}</span>
                    <span className={`text-lg font-black ${pnlC(s.pnl)}`}>{s.pnl >= 0 ? "+" : ""}${s.pnl.toFixed(0)}</span>
                  </div>
                  <div className="flex gap-4 mt-1 text-[10px] text-bah-muted">
                    <span>{s.trades} trades</span>
                    <span>WR: {(s.wr * 100).toFixed(0)}%</span>
                    <span>{s.wins}W / {s.losses}L</span>
                    <span>Avg R: {s.avg_r.toFixed(3)}</span>
                  </div>
                </div>
              ))}
            </div>
          </Section>

          <Section title="Direction Performance">
            <div className="space-y-3">
              {Object.entries(data.direction_stats || {}).map(([dir, s]: [string, any]) => (
                <div key={dir} className={`border rounded-lg p-3 ${s.pnl >= 0 ? "border-green-500/20 bg-green-500/5" : "border-red-500/20 bg-red-500/5"}`}>
                  <div className="flex justify-between items-center">
                    <span className={`text-sm font-black ${dir === "LONG" ? "text-green-400" : "text-red-400"}`}>{dir}</span>
                    <span className={`text-lg font-black ${pnlC(s.pnl)}`}>{s.pnl >= 0 ? "+" : ""}${s.pnl.toFixed(0)}</span>
                  </div>
                  <div className="text-[10px] text-bah-muted mt-1">{s.trades} trades · {s.wins} wins</div>
                </div>
              ))}
            </div>
          </Section>
        </div>
      )}
    </div>
  );
}
