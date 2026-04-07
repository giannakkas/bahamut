"use client";
import React, { useState, useEffect, useCallback } from "react";
import { apiBase } from "@/lib/utils";

const fm = (n: number) => `$${Math.abs(n).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const fmS = (n: number) => `${n >= 0 ? "+" : "-"}${fm(n)}`;
const pnlC = (n: number) => n > 0.01 ? "text-green-400" : n < -0.01 ? "text-red-400" : "text-bah-muted";

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="bg-bah-card border border-bah-border rounded-xl p-4">
      <h3 className="text-[11px] font-bold text-bah-muted uppercase tracking-wider mb-3">{title}</h3>
      {children}
    </div>
  );
}

export default function RiskPage() {
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    try {
      const t = localStorage.getItem("bahamut_admin_token");
      const h: Record<string, string> = t ? { Authorization: `Bearer ${t}` } : {};
      const r = await fetch(`${apiBase()}/training/risk-metrics`, { headers: h });
      if (r.ok) setData(await r.json());
    } catch {}
    setLoading(false);
  }, []);

  useEffect(() => { load(); }, [load]);
  if (loading) return <div className="p-8 text-bah-muted">Loading risk metrics...</div>;
  if (!data || data.error) return <div className="p-8 text-red-400">Error: {data?.error || "No data"}</div>;
  const d = data;

  return (
    <div className="space-y-4 p-4 max-w-[1400px] mx-auto">
      <h1 className="text-xl font-black text-bah-heading">Risk Dashboard</h1>

      {/* KPIs */}
      <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-8 gap-2">
        {[
          { l: "Total PnL", v: fmS(d.total_pnl), c: pnlC(d.total_pnl) },
          { l: "Return", v: `${d.return_pct >= 0 ? "+" : ""}${d.return_pct}%`, c: pnlC(d.return_pct) },
          { l: "Max Drawdown", v: fm(d.max_drawdown), c: "text-red-400" },
          { l: "DD %", v: `${d.max_drawdown_pct.toFixed(1)}%`, c: "text-red-400" },
          { l: "Profit Factor", v: d.profit_factor.toFixed(2), c: d.profit_factor >= 1.5 ? "text-green-400" : d.profit_factor >= 1 ? "text-yellow-400" : "text-red-400" },
          { l: "Avg R", v: d.avg_r_multiple.toFixed(3), c: pnlC(d.avg_r_multiple) },
          { l: "Trades", v: String(d.total_trades), c: "text-bah-heading" },
          { l: "Equity", v: fm(d.current_equity), c: "text-bah-cyan" },
        ].map((card, i) => (
          <div key={i} className="bg-bah-card border border-bah-border rounded-lg p-3 text-center">
            <div className={`text-lg font-black ${card.c}`}>{card.v}</div>
            <div className="text-[9px] text-bah-muted uppercase">{card.l}</div>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Drawdown */}
        <Section title="Drawdown">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <div className="text-3xl font-black text-red-400">{fm(d.max_drawdown)}</div>
              <div className="text-[11px] text-bah-muted">Max Drawdown ({d.max_drawdown_pct.toFixed(2)}%)</div>
            </div>
            <div>
              <div className={`text-3xl font-black ${d.current_drawdown > 0 ? "text-orange-400" : "text-green-400"}`}>{fm(d.current_drawdown)}</div>
              <div className="text-[11px] text-bah-muted">Current Drawdown ({d.current_drawdown_pct.toFixed(2)}%)</div>
            </div>
          </div>
        </Section>

        {/* Streaks */}
        <Section title="Streaks & Extremes">
          <div className="grid grid-cols-3 gap-4">
            <div className="text-center"><div className="text-2xl font-black text-green-400">{d.best_streak}</div><div className="text-[9px] text-bah-muted">Best Win Streak</div></div>
            <div className="text-center"><div className="text-2xl font-black text-red-400">{d.worst_streak}</div><div className="text-[9px] text-bah-muted">Worst Loss Streak</div></div>
            <div className="text-center"><div className={`text-2xl font-black ${d.current_streak_type === "win" ? "text-green-400" : d.current_streak_type === "loss" ? "text-red-400" : "text-bah-muted"}`}>{d.current_streak}</div><div className="text-[9px] text-bah-muted">Current ({d.current_streak_type || "flat"})</div></div>
          </div>
          <div className="grid grid-cols-2 gap-4 mt-3 pt-3 border-t border-bah-border">
            <div><div className="text-lg font-bold text-green-400">{fmS(d.biggest_win?.pnl || 0)}</div><div className="text-[10px] text-bah-muted">Best — {d.biggest_win?.asset} ({d.biggest_win?.strategy})</div></div>
            <div><div className="text-lg font-bold text-red-400">{fmS(d.biggest_loss?.pnl || 0)}</div><div className="text-[10px] text-bah-muted">Worst — {d.biggest_loss?.asset} ({d.biggest_loss?.strategy})</div></div>
          </div>
        </Section>
      </div>

      {/* R-Multiples */}
      <Section title="R-Multiple Analysis">
        <div className="grid grid-cols-4 gap-6 text-center">
          <div><div className={`text-xl font-black ${pnlC(d.avg_r_multiple)}`}>{d.avg_r_multiple.toFixed(3)}</div><div className="text-[9px] text-bah-muted">Avg R (all)</div></div>
          <div><div className="text-xl font-black text-green-400">+{d.avg_win_r.toFixed(3)}</div><div className="text-[9px] text-bah-muted">Avg Win R</div></div>
          <div><div className="text-xl font-black text-red-400">{d.avg_loss_r.toFixed(3)}</div><div className="text-[9px] text-bah-muted">Avg Loss R</div></div>
          <div><div className="text-xl font-black text-bah-heading">{d.avg_bars_held}</div><div className="text-[9px] text-bah-muted">Avg Bars ({(d.avg_bars_held * 4).toFixed(0)}h)</div></div>
        </div>
      </Section>

      {/* Daily PnL */}
      {d.daily_pnl?.length > 0 && (
        <Section title="Daily P&L (Last 14 Days)">
          <div className="flex items-end gap-1 h-36">
            {d.daily_pnl.map((day: any, i: number) => {
              const maxAbs = Math.max(...d.daily_pnl.map((x: any) => Math.abs(x.pnl)), 1);
              const h = Math.max(6, Math.abs(day.pnl) / maxAbs * 100);
              return (
                <div key={i} className="flex-1 flex flex-col items-center justify-end h-full">
                  <div className="text-[8px] text-bah-muted mb-0.5">{fmS(day.pnl)}</div>
                  <div className={`w-full rounded-sm ${day.pnl >= 0 ? "bg-green-500/60" : "bg-red-500/60"}`} style={{ height: `${h}%` }} />
                  <div className="text-[8px] text-bah-muted mt-0.5">{day.date.slice(5)}</div>
                </div>
              );
            })}
          </div>
        </Section>
      )}

      {/* By Strategy */}
      <Section title="Risk by Strategy">
        <table className="w-full text-xs">
          <thead><tr className="text-bah-muted text-[10px] uppercase">
            <th className="text-left py-1">Strategy</th><th className="text-right">Trades</th><th className="text-right">W/L</th>
            <th className="text-right">PnL</th><th className="text-right">Max Loss</th><th className="text-right">Σ R</th>
          </tr></thead>
          <tbody>
            {Object.entries(d.by_strategy || {}).map(([name, s]: [string, any]) => (
              <tr key={name} className="border-t border-bah-border/30">
                <td className="py-1.5 font-bold text-bah-heading">{name}</td>
                <td className="text-right">{s.trades}</td><td className="text-right">{s.wins}/{s.losses}</td>
                <td className={`text-right font-bold ${pnlC(s.pnl)}`}>{fmS(s.pnl)}</td>
                <td className="text-right text-red-400">{fm(s.max_loss)}</td>
                <td className={`text-right ${pnlC(s.r_sum)}`}>{s.r_sum > 0 ? "+" : ""}{s.r_sum}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Section>

      {/* By Class */}
      <Section title="Risk by Asset Class">
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-2">
          {Object.entries(d.by_class || {}).map(([cls, s]: [string, any]) => (
            <div key={cls} className={`border rounded-lg p-3 text-center ${s.pnl >= 0 ? "bg-green-500/5 border-green-500/20" : "bg-red-500/5 border-red-500/20"}`}>
              <div className="text-xs font-bold text-bah-heading uppercase">{cls}</div>
              <div className={`text-lg font-black mt-1 ${pnlC(s.pnl)}`}>{fmS(s.pnl)}</div>
              <div className="text-[9px] text-bah-muted">{s.trades}T · {s.wins}W/{s.losses}L</div>
            </div>
          ))}
        </div>
      </Section>
    </div>
  );
}
