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

function UtilBar({ label, value, max }: { label: string; value: number; max: number }) {
  const pct = Math.min(100, (value / Math.max(1, max)) * 100);
  const color = pct >= 90 ? "bg-red-500" : pct >= 70 ? "bg-yellow-500" : "bg-green-500";
  return (
    <div className="flex items-center gap-2 text-[11px]">
      <span className="w-24 text-bah-muted text-right truncate">{label}</span>
      <div className="flex-1 h-2.5 bg-bah-surface rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="w-14 text-right text-bah-heading font-bold">{value}/{max}</span>
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

  useEffect(() => { load(); const iv = setInterval(load, 60000); return () => clearInterval(iv); }, [load]);
  if (loading) return <div className="p-8 text-bah-muted">Loading risk metrics...</div>;
  if (!data || data.error) return <div className="p-8 text-red-400">Error: {data?.error || "No data"}</div>;
  const d = data;
  const re = d.risk_engine || {};
  const exp = d.exposure || {};
  const corr = d.correlation || {};
  const ctrl = d.controls || {};
  const hasEngine = !!re.status;

  const modeColor = re.mode === "BLOCKED" ? "text-red-400 bg-red-500/10 border-red-500/30"
    : re.mode === "REDUCED" ? "text-yellow-400 bg-yellow-500/10 border-yellow-500/30"
    : "text-green-400 bg-green-500/10 border-green-500/30";
  const modeIcon = re.mode === "BLOCKED" ? "🛑" : re.mode === "REDUCED" ? "⚠️" : "✅";

  return (
    <div className="space-y-4 p-4 max-w-[1400px] mx-auto">
      <h1 className="text-xl font-black text-bah-heading">Risk Dashboard</h1>

      {/* ═══ RISK ENGINE STATUS ═══ */}
      {hasEngine && (
        <div className={`border rounded-xl p-4 ${modeColor}`}>
          <div className="flex items-center justify-between flex-wrap gap-2">
            <div className="flex items-center gap-3">
              <span className="text-2xl">{modeIcon}</span>
              <div>
                <div className="text-lg font-black">{re.mode || "UNKNOWN"}</div>
                <div className="text-[10px] opacity-70">Risk Engine · New trades: {re.block_new_trades ? "BLOCKED" : "ALLOWED"} · Size: {((re.size_multiplier || 1) * 100).toFixed(0)}%</div>
              </div>
            </div>
            <div className="text-right">
              <div className="text-sm font-bold">{ctrl.triggered_rules?.length || 0} rules triggered</div>
              <div className="text-[10px] opacity-70">{ctrl.warnings?.length || 0} warnings</div>
            </div>
          </div>
          {(ctrl.triggered_rules?.length > 0 || ctrl.warnings?.length > 0) && (
            <div className="mt-3 pt-3 border-t border-current/20 space-y-1">
              {(ctrl.triggered_rules || []).map((r: string, i: number) => (
                <div key={i} className="text-[11px] font-bold">🛑 {r.replace(/_/g, " ").toUpperCase()}</div>
              ))}
              {(ctrl.warnings || []).map((w: string, i: number) => (
                <div key={`w${i}`} className="text-[11px]">⚠️ {w}</div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* ═══ KPIs ═══ */}
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

      {/* ═══ DAILY BRAKE + PORTFOLIO PROTECTION ═══ */}
      {hasEngine && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <Section title="Daily Risk Brake">
            <div className="space-y-3">
              <div className="flex justify-between items-end">
                <div>
                  <div className={`text-2xl font-black ${pnlC(re.current_daily_pnl)}`}>{fmS(re.current_daily_pnl)}</div>
                  <div className="text-[10px] text-bah-muted">Today realized + unrealized</div>
                </div>
                <div className="text-right">
                  <div className="text-sm font-bold text-bah-heading">{(re.current_daily_drawdown_pct || 0).toFixed(1)}%</div>
                  <div className="text-[10px] text-bah-muted">of {re.daily_loss_limit_pct}% limit</div>
                </div>
              </div>
              <div className="h-3 bg-bah-surface rounded-full overflow-hidden">
                {(() => {
                  const pct = Math.min(100, ((re.current_daily_drawdown_pct || 0) / Math.max(0.01, re.daily_loss_limit_pct)) * 100);
                  const c = pct >= 90 ? "bg-red-500" : pct >= 50 ? "bg-yellow-500" : "bg-green-500";
                  return <div className={`h-full rounded-full ${c}`} style={{ width: `${Math.max(2, pct)}%` }} />;
                })()}
              </div>
              <div className="text-[10px] text-bah-muted">
                Limit: {fm(re.daily_loss_limit_cash)} / {re.daily_loss_limit_pct}%
              </div>
            </div>
          </Section>

          <Section title="Portfolio Protection">
            <div className="space-y-3">
              <div className="flex justify-between items-end">
                <div>
                  <div className={`text-2xl font-black ${d.current_drawdown > 0 ? "text-orange-400" : "text-green-400"}`}>{fm(d.current_drawdown)}</div>
                  <div className="text-[10px] text-bah-muted">Current drawdown ({d.current_drawdown_pct.toFixed(2)}%)</div>
                </div>
                <div className="text-right">
                  <div className="text-sm font-bold text-red-400">{fm(d.max_drawdown)}</div>
                  <div className="text-[10px] text-bah-muted">Max historical ({d.max_drawdown_pct.toFixed(1)}%)</div>
                </div>
              </div>
              <div className="h-3 bg-bah-surface rounded-full overflow-hidden">
                {(() => {
                  const pct = Math.min(100, ((re.current_portfolio_drawdown_pct || 0) / Math.max(0.01, re.max_portfolio_drawdown_pct || 8)) * 100);
                  const c = pct >= 90 ? "bg-red-500" : pct >= 60 ? "bg-yellow-500" : "bg-green-500";
                  return <div className={`h-full rounded-full ${c}`} style={{ width: `${Math.max(2, pct)}%` }} />;
                })()}
              </div>
              <div className="text-[10px] text-bah-muted">
                Guard: {re.max_portfolio_drawdown_pct || 8}% max · Equity: {fm(re.current_equity || d.current_equity)} / Peak: {fm(re.peak_equity || d.current_equity)}
              </div>
            </div>
          </Section>
        </div>
      )}

      {/* ═══ EXPOSURE MONITOR ═══ */}
      {hasEngine && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <Section title="Exposure by Class">
            <div className="space-y-2">
              <div className="flex justify-between text-[10px] text-bah-muted mb-1">
                <span>Notional: {fm(exp.total_notional || 0)}</span>
                <span>Risk: {fm(exp.total_risk_weighted || 0)}</span>
                <span>Open: {exp.open_positions || 0}</span>
              </div>
              {Object.entries(exp.by_class || {}).map(([cls, e]: [string, any]) => (
                <UtilBar key={cls} label={cls.toUpperCase()} value={e.positions} max={e.cap_positions} />
              ))}
              {Object.keys(exp.by_class || {}).length === 0 && (
                <div className="text-[11px] text-bah-muted">No open positions</div>
              )}
            </div>
          </Section>

          <Section title="Exposure by Strategy">
            <div className="space-y-2 mt-5">
              {Object.entries(exp.by_strategy || {}).map(([s, e]: [string, any]) => (
                <UtilBar key={s} label={s.replace(/_/g, " ")} value={e.positions} max={e.cap_positions} />
              ))}
              {Object.keys(exp.by_strategy || {}).length === 0 && (
                <div className="text-[11px] text-bah-muted">No open positions</div>
              )}
            </div>
          </Section>
        </div>
      )}

      {/* ═══ ADAPTIVE NEWS RISK ═══ */}
      {d.adaptive_news?.summary && (
        <Section title="News Event Risk">
          <div className="space-y-3">
            <div className="flex gap-3 flex-wrap">
              {Object.entries(d.adaptive_news.summary?.mode_counts || {}).map(([mode, count]: [string, any]) => {
                const c = mode === "FROZEN" ? "border-red-500/30 bg-red-500/10 text-red-400"
                  : mode === "RESTRICTED" ? "border-yellow-500/30 bg-yellow-500/10 text-yellow-400"
                  : mode === "CAUTION" ? "border-orange-400/30 bg-orange-400/10 text-orange-400"
                  : "border-green-500/30 bg-green-500/10 text-green-400";
                return (
                  <div key={mode} className={`border rounded-lg px-3 py-2 text-center ${c}`}>
                    <div className="text-lg font-black">{count as number}</div>
                    <div className="text-[9px] uppercase font-bold">{mode}</div>
                  </div>
                );
              })}
              {d.adaptive_news.summary?.starvation_guard_active && (
                <div className="border border-red-500/40 bg-red-500/10 rounded-lg px-3 py-2 text-center">
                  <div className="text-lg font-black text-red-400">⚠️</div>
                  <div className="text-[9px] text-red-400 uppercase font-bold">Starvation Guard</div>
                </div>
              )}
            </div>
            {Object.entries(d.adaptive_news.assets || {}).filter(([, a]: [string, any]) => a.mode !== "NORMAL").length > 0 && (
              <div className="space-y-1 mt-2">
                <div className="text-[10px] text-bah-muted uppercase font-bold">Non-Normal Assets</div>
                {Object.entries(d.adaptive_news.assets || {}).filter(([, a]: [string, any]) => a.mode !== "NORMAL").map(([asset, a]: [string, any]) => {
                  const mc = a.mode === "FROZEN" ? "text-red-400" : a.mode === "RESTRICTED" ? "text-yellow-400" : "text-orange-400";
                  return (
                    <div key={asset} className="flex items-center justify-between text-xs py-0.5 border-b border-bah-border/20">
                      <div className="flex items-center gap-2">
                        <span className="font-bold text-bah-heading">{asset}</span>
                        <span className={`text-[10px] font-bold ${mc}`}>{a.mode}</span>
                      </div>
                      <div className="flex gap-3 text-[10px] text-bah-muted">
                        <span>bias: {a.bias}</span>
                        <span>size: {((a.size_multiplier || 1) * 100).toFixed(0)}%</span>
                        <span>{a.age_seconds ? `${Math.round(a.age_seconds / 60)}m ago` : ""}</span>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </Section>
      )}

      {/* ═══ CORRELATION + RECOMMENDATIONS ═══ */}
      {hasEngine && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <Section title="Correlation / Cluster Risk">
            {corr.top_clusters?.length > 0 ? (
              <div className="space-y-2">
                {corr.top_clusters.map((c: any, i: number) => (
                  <div key={i} className={`text-xs p-2 rounded-lg border ${c.status === "BLOCKED" ? "border-red-500/30 bg-red-500/5" : "border-yellow-500/30 bg-yellow-500/5"}`}>
                    <div className="flex justify-between">
                      <span className="font-bold text-bah-heading">{c.label}</span>
                      <span className={c.status === "BLOCKED" ? "text-red-400 font-bold" : "text-yellow-400 font-bold"}>{c.count}/{c.max}</span>
                    </div>
                    <div className="text-[10px] text-bah-muted mt-0.5">{c.assets.join(", ")}</div>
                  </div>
                ))}
                <div className="text-[10px] text-bah-muted">Method: {corr.method} · {corr.blocked_candidates_count || 0} blocked</div>
              </div>
            ) : (
              <div className="text-[11px] text-green-400">No cluster concentration warnings</div>
            )}
          </Section>

          <Section title="Risk Recommendations">
            <div className="space-y-1.5">
              {(ctrl.recommendations || []).map((r: string, i: number) => (
                <div key={i} className="text-xs text-bah-heading py-1 border-b border-bah-border/20 flex items-start gap-2">
                  <span className="text-bah-cyan mt-px">›</span>
                  <span>{r}</span>
                </div>
              ))}
              {(!ctrl.recommendations || ctrl.recommendations.length === 0) && (
                <div className="text-[11px] text-bah-muted">No recommendations</div>
              )}
            </div>
          </Section>
        </div>
      )}

      {/* ═══ EXISTING: Streaks ═══ */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
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

        <Section title="R-Multiple Analysis">
          <div className="grid grid-cols-4 gap-6 text-center">
            <div><div className={`text-xl font-black ${pnlC(d.avg_r_multiple)}`}>{d.avg_r_multiple.toFixed(3)}</div><div className="text-[9px] text-bah-muted">Avg R (all)</div></div>
            <div><div className="text-xl font-black text-green-400">+{d.avg_win_r.toFixed(3)}</div><div className="text-[9px] text-bah-muted">Avg Win R</div></div>
            <div><div className="text-xl font-black text-red-400">{d.avg_loss_r.toFixed(3)}</div><div className="text-[9px] text-bah-muted">Avg Loss R</div></div>
            <div><div className="text-xl font-black text-bah-heading">{d.avg_bars_held}</div><div className="text-[9px] text-bah-muted">Avg Bars ({(d.avg_bars_held * 4).toFixed(0)}h)</div></div>
          </div>
        </Section>
      </div>

      {/* ═══ Daily PnL ═══ */}
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

      {/* ═══ By Strategy ═══ */}
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

      {/* ═══ By Class ═══ */}
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
