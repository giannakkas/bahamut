"use client";

import { useState, useEffect } from "react";
import { apiBase } from "@/lib/utils";

export default function TrainingOperationsPage() {
  const [data, setData] = useState<any>(null);
  const [candidates, setCandidates] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState<"overview" | "positions" | "trades" | "learning" | "risk">("overview");
  const token = typeof window !== "undefined" ? sessionStorage.getItem("bah_token") : null;

  const load = async () => {
    try {
      const r = await fetch(`${apiBase()}/training/operations`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (r.ok) setData(await r.json());
    } catch {}
    try {
      const r = await fetch(`${apiBase()}/training/candidates`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (r.ok) setCandidates(await r.json());
    } catch {}
    setLoading(false);
  };

  useEffect(() => {
    load();
    const iv = setInterval(load, 30000);
    return () => clearInterval(iv);
  }, []);

  if (loading) return <div className="p-8 text-center text-bah-muted text-sm">Loading training operations...</div>;
  if (!data) return (
    <div className="p-8 text-center text-bah-muted">
      <p className="text-lg font-bold text-bah-heading mb-2">Training Operations</p>
      <p className="text-sm">Waiting for first training cycle. The training engine runs every 10 minutes.</p>
    </div>
  );

  const k = data.kpi || {};
  const cy = data.cycle_health || {};
  const strats = data.strategy_breakdown || {};
  const classes = data.class_breakdown || {};
  const rankings = data.asset_rankings || {};
  const learn = data.learning || {};
  const expo = data.exposure || {};
  const alerts = data.alerts || [];

  const fmtPnl = (v: number) => v >= 0 ? `+$${v.toLocaleString(undefined, { minimumFractionDigits: 0 })}` : `-$${Math.abs(v).toLocaleString(undefined, { minimumFractionDigits: 0 })}`;
  const pnlClr = (v: number) => v >= 0 ? "text-green-400" : "text-red-400";
  const fmtPct = (v: number) => `${(v * 100).toFixed(1)}%`;
  const fmtTime = (s: string) => { if (!s) return "—"; try { return new Date(s).toLocaleString("en-GB", { hour12: false, month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }); } catch { return s; } };

  return (
    <div className="p-2 sm:p-4 max-w-[1440px] space-y-4 pt-12 lg:pt-4">
      {/* ═══ HEADER ═══ */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
        <div className="flex items-center gap-2 flex-wrap">
          <h1 className="text-base sm:text-lg font-bold text-bah-heading">Training Operations</h1>
          <span className="px-2 py-0.5 text-[10px] rounded-full font-semibold border bg-purple-500/20 text-purple-400 border-purple-500/30">PAPER ONLY</span>
          <span className="text-[10px] text-bah-muted">{k.universe_size || 0} assets · ${(k.virtual_capital || 100000).toLocaleString()} virtual</span>
        </div>
        {cy.last_run && (
          <span className="text-[10px] text-bah-muted font-mono">
            Last cycle: {fmtTime(cy.last_run)} · {cy.duration_ms}ms ·{" "}
            <span className={cy.status === "OK" ? "text-green-400" : cy.status === "DEGRADED" ? "text-amber-400" : "text-red-400"}>{cy.status}</span>
          </span>
        )}
      </div>

      {/* ═══ ALERTS ═══ */}
      {alerts.length > 0 && (
        <div className="space-y-1">
          {alerts.map((a: any, i: number) => (
            <div key={i} className={`px-3 py-2 rounded-lg text-xs border ${a.level === "WARNING" ? "bg-amber-500/5 border-amber-500/20 text-amber-400" : "bg-bah-border/20 border-bah-border text-bah-muted"}`}>
              {a.level === "WARNING" ? "⚠️" : "ℹ️"} {a.message}
            </div>
          ))}
        </div>
      )}

      {/* ═══ TRADE CANDIDATES ═══ */}
      <CandidatesPanel candidates={candidates} />

      {/* ═══ KPI ROW ═══ */}
      <div className="grid grid-cols-3 sm:grid-cols-5 lg:grid-cols-10 gap-2">
        {[
          { label: "Universe", value: k.universe_size || 0 },
          { label: "Scanned", value: k.assets_scanned || 0 },
          { label: "Open", value: k.open_positions || 0 },
          { label: "Closed", value: k.closed_trades || 0 },
          { label: "Net PnL", value: fmtPnl(k.net_pnl || 0), cls: pnlClr(k.net_pnl || 0) },
          { label: "Win Rate", value: fmtPct(k.win_rate || 0) },
          { label: "Avg Bars", value: (k.avg_duration_bars || 0).toFixed(1) },
          { label: "Samples", value: k.learning_samples || 0 },
          { label: "Util %", value: `${expo.utilization_pct || 0}%` },
          { label: "Risk %", value: `${expo.risk_pct || 0}%` },
        ].map((kpi, i) => (
          <div key={i} className="bg-bah-surface border border-bah-border rounded-lg p-2 text-center">
            <div className={`text-sm font-bold ${kpi.cls || "text-bah-heading"}`}>{kpi.value}</div>
            <div className="text-[9px] text-bah-muted uppercase tracking-wide">{kpi.label}</div>
          </div>
        ))}
      </div>

      {/* ═══ TABS ═══ */}
      <div className="flex border-b border-bah-border overflow-x-auto">
        {(["overview", "positions", "trades", "learning", "risk"] as const).map(t => (
          <button key={t} onClick={() => setTab(t)} className={`px-4 py-2 text-xs font-medium border-b-2 transition-colors whitespace-nowrap ${
            tab === t ? "border-bah-cyan text-bah-cyan" : "border-transparent text-bah-muted hover:text-bah-heading"
          }`}>
            {t === "overview" ? "📊 Overview" : t === "positions" ? `📦 Positions (${k.open_positions || 0})` : t === "trades" ? `🔁 Trades (${k.closed_trades || 0})` : t === "learning" ? "🧬 Learning" : "⚖️ Risk & Exposure"}
          </button>
        ))}
      </div>

      {/* ═══ OVERVIEW TAB ═══ */}
      {tab === "overview" && (
        <div className="space-y-4">
          {/* Cycle Health */}
          <Section title="Cycle Health">
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs">
              <Stat label="Processed" value={cy.assets_processed} />
              <Stat label="Skipped" value={cy.assets_skipped} />
              <Stat label="Errors" value={cy.errors} cls={cy.errors > 0 ? "text-red-400" : ""} />
              <Stat label="Signals" value={cy.signals_generated} />
            </div>
          </Section>

          {/* Strategy Breakdown */}
          <Section title="Strategy Breakdown">
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead><tr className="border-b border-bah-border text-left text-[10px] text-bah-muted uppercase">
                  <th className="py-2 pr-3">Strategy</th><th className="py-2 pr-3">Open</th><th className="py-2 pr-3">Closed</th>
                  <th className="py-2 pr-3">WR</th><th className="py-2 pr-3">PF</th><th className="py-2 pr-3">PnL</th>
                  <th className="py-2 pr-3">Avg Bars</th><th className="py-2">Status</th>
                </tr></thead>
                <tbody>
                  {Object.entries(strats).map(([name, s]: [string, any]) => (
                    <tr key={name} className="border-b border-bah-border/30">
                      <td className="py-2 pr-3 text-bah-heading font-medium">{name}</td>
                      <td className="py-2 pr-3 text-bah-muted">{s.open_trades}</td>
                      <td className="py-2 pr-3 text-bah-muted">{s.closed_trades}</td>
                      <td className="py-2 pr-3">{fmtPct(s.win_rate)}</td>
                      <td className="py-2 pr-3">{s.profit_factor.toFixed(2)}</td>
                      <td className={`py-2 pr-3 font-medium ${pnlClr(s.total_pnl)}`}>{fmtPnl(s.total_pnl)}</td>
                      <td className="py-2 pr-3 text-bah-muted">{s.avg_hold_bars?.toFixed(1)}</td>
                      <td className="py-2">
                        <span className={`px-1.5 py-0.5 rounded text-[9px] font-bold ${s.provisional ? "bg-amber-500/15 text-amber-400" : "bg-green-500/15 text-green-400"}`}>
                          {s.provisional ? "WARMING" : "ACTIVE"}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Section>

          {/* Asset Class Breakdown */}
          <Section title="Asset Class Breakdown">
            <div className="grid grid-cols-2 sm:grid-cols-5 gap-2">
              {Object.entries(classes).map(([cls, s]: [string, any]) => (
                <div key={cls} className="bg-bah-bg border border-bah-border rounded-lg p-3">
                  <div className="text-[10px] text-bah-muted uppercase mb-1 tracking-wide">{cls}</div>
                  <div className="text-xs text-bah-heading font-semibold">{s.closed_trades} closed · {s.open_trades} open</div>
                  <div className={`text-[11px] font-medium ${pnlClr(s.pnl)}`}>{fmtPnl(s.pnl)} · {fmtPct(s.win_rate)} WR</div>
                </div>
              ))}
            </div>
          </Section>

          {/* Rankings */}
          {(rankings.best?.length > 0 || rankings.worst?.length > 0) && (
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              {rankings.best?.length > 0 && (
                <Section title="🏆 Best Assets">
                  {rankings.best.map((a: any, i: number) => (
                    <div key={i} className="flex justify-between items-center py-1.5 text-xs border-b border-bah-border/20">
                      <div><span className="text-bah-heading font-medium">{a.asset}</span> <span className="text-[10px] text-bah-muted">{a.class}</span></div>
                      <div className="text-green-400 font-medium">{fmtPnl(a.pnl)} <span className="text-bah-muted">({a.trades}t)</span></div>
                    </div>
                  ))}
                </Section>
              )}
              {rankings.worst?.length > 0 && (
                <Section title="⚠️ Worst Assets">
                  {rankings.worst.map((a: any, i: number) => (
                    <div key={i} className="flex justify-between items-center py-1.5 text-xs border-b border-bah-border/20">
                      <div><span className="text-bah-heading font-medium">{a.asset}</span> <span className="text-[10px] text-bah-muted">{a.class}</span></div>
                      <div className="text-red-400 font-medium">{fmtPnl(a.pnl)} <span className="text-bah-muted">({a.trades}t)</span></div>
                    </div>
                  ))}
                </Section>
              )}
            </div>
          )}
        </div>
      )}

      {/* ═══ POSITIONS TAB ═══ */}
      {tab === "positions" && (
        <Section title={`Open Positions (${data.positions?.length || 0})`}>
          {data.positions?.length > 0 ? (
            <div className="overflow-x-auto">
              <table className="w-full text-[11px] min-w-[800px]">
                <thead><tr className="border-b border-bah-border text-left text-[10px] text-bah-muted uppercase">
                  <th className="py-2 pr-2">Asset</th><th className="py-2 pr-2">Class</th><th className="py-2 pr-2">Strategy</th>
                  <th className="py-2 pr-2">Dir</th><th className="py-2 pr-2">Entry</th><th className="py-2 pr-2">Current</th>
                  <th className="py-2 pr-2">SL</th><th className="py-2 pr-2">TP</th>
                  <th className="py-2 pr-2">Unreal PnL</th><th className="py-2 pr-2">Bars</th>
                </tr></thead>
                <tbody>
                  {data.positions.map((p: any, i: number) => (
                    <tr key={i} className="border-b border-bah-border/20">
                      <td className="py-1.5 pr-2 text-bah-heading font-medium">{p.asset}</td>
                      <td className="py-1.5 pr-2 text-bah-muted">{p.asset_class}</td>
                      <td className="py-1.5 pr-2 text-bah-muted">{p.strategy}</td>
                      <td className="py-1.5 pr-2"><span className={p.direction === "LONG" ? "text-green-400" : "text-red-400"}>{p.direction}</span></td>
                      <td className="py-1.5 pr-2 font-mono">{p.entry_price}</td>
                      <td className="py-1.5 pr-2 font-mono">{p.current_price}</td>
                      <td className="py-1.5 pr-2 font-mono text-red-400/60">{p.stop_price || p.stop_loss}</td>
                      <td className="py-1.5 pr-2 font-mono text-green-400/60">{p.tp_price || p.take_profit}</td>
                      <td className={`py-1.5 pr-2 font-medium ${pnlClr(p.unrealized_pnl || 0)}`}>{fmtPnl(p.unrealized_pnl || 0)}</td>
                      <td className="py-1.5 pr-2 text-bah-muted">{p.bars_held || p.duration_bars || 0}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="text-center py-8 text-bah-muted text-sm">No open training positions. Waiting for signals at next 4H bar boundary.</div>
          )}
        </Section>
      )}

      {/* ═══ TRADES TAB ═══ */}
      {tab === "trades" && (
        <Section title={`Closed Trades (last 50)`}>
          {data.closed_trades?.length > 0 ? (
            <div className="overflow-x-auto">
              <table className="w-full text-[11px] min-w-[900px]">
                <thead><tr className="border-b border-bah-border text-left text-[10px] text-bah-muted uppercase">
                  <th className="py-2 pr-2">Asset</th><th className="py-2 pr-2">Class</th><th className="py-2 pr-2">Strategy</th>
                  <th className="py-2 pr-2">Dir</th><th className="py-2 pr-2">Entry</th><th className="py-2 pr-2">Exit</th>
                  <th className="py-2 pr-2">PnL</th><th className="py-2 pr-2">Exit</th>
                  <th className="py-2 pr-2">Bars</th><th className="py-2 pr-2">Closed</th>
                </tr></thead>
                <tbody>
                  {data.closed_trades.map((t: any, i: number) => (
                    <tr key={i} className="border-b border-bah-border/20">
                      <td className="py-1.5 pr-2 text-bah-heading font-medium">{t.asset}</td>
                      <td className="py-1.5 pr-2 text-bah-muted">{t.asset_class}</td>
                      <td className="py-1.5 pr-2 text-bah-muted">{t.strategy}</td>
                      <td className="py-1.5 pr-2"><span className={t.direction === "LONG" ? "text-green-400" : "text-red-400"}>{t.direction}</span></td>
                      <td className="py-1.5 pr-2 font-mono">{typeof t.entry_price === 'number' ? t.entry_price.toFixed(2) : t.entry_price}</td>
                      <td className="py-1.5 pr-2 font-mono">{typeof t.exit_price === 'number' ? t.exit_price.toFixed(2) : t.exit_price}</td>
                      <td className={`py-1.5 pr-2 font-medium ${pnlClr(t.pnl || 0)}`}>${(t.pnl || 0).toFixed(2)}</td>
                      <td className="py-1.5 pr-2"><span className={`px-1 py-0.5 rounded text-[9px] font-bold ${
                        t.exit_reason === "TP" ? "bg-green-500/15 text-green-400" :
                        t.exit_reason === "SL" ? "bg-red-500/15 text-red-400" :
                        "bg-bah-border text-bah-muted"
                      }`}>{t.exit_reason}</span></td>
                      <td className="py-1.5 pr-2 text-bah-muted">{t.bars_held}</td>
                      <td className="py-1.5 pr-2 text-bah-muted text-[10px]">{fmtTime(t.exit_time)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="text-center py-8 text-bah-muted text-sm">No closed training trades yet. First trades will close after SL/TP/timeout triggers.</div>
          )}
        </Section>
      )}

      {/* ═══ LEARNING TAB ═══ */}
      {tab === "learning" && (
        <div className="space-y-4">
          {/* Progress */}
          <Section title="Learning Progress">
            <div className="flex items-center gap-4 mb-3">
              <div className="flex-1 bg-bah-bg rounded-full h-3 overflow-hidden">
                <div className="h-full rounded-full bg-gradient-to-r from-purple-500 to-bah-cyan transition-all duration-500"
                     style={{ width: `${learn.progress_pct || 0}%` }} />
              </div>
              <span className="text-xs text-bah-heading font-semibold">{learn.progress_pct || 0}%</span>
            </div>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-4">
              <Stat label="Total Samples" value={learn.total_samples} />
              <Stat label="Status" value={learn.status?.toUpperCase() || "—"} cls={learn.status === "ready" ? "text-green-400" : learn.status === "learning" ? "text-bah-cyan" : "text-amber-400"} />
              <Stat label="Trust Ready" value={learn.trust_ready ? "YES" : "NO"} cls={learn.trust_ready ? "text-green-400" : "text-bah-muted"} />
              <Stat label="Adaptive Ready" value={learn.adaptive_ready ? "YES" : "NO"} cls={learn.adaptive_ready ? "text-green-400" : "text-bah-muted"} />
            </div>
            {/* Milestones */}
            <div className="space-y-1.5">
              {(learn.milestones || []).map((m: any, i: number) => (
                <div key={i} className="flex items-center gap-2 text-xs">
                  <span className={`w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-bold border ${
                    m.reached ? "bg-green-500/20 text-green-400 border-green-500/30" : "bg-bah-border/50 text-bah-muted border-bah-border"
                  }`}>{m.reached ? "✓" : i + 1}</span>
                  <span className={m.reached ? "text-bah-heading" : "text-bah-muted"}>{m.label}</span>
                  <span className="text-[10px] text-bah-muted">({m.current || 0}/{m.required})</span>
                </div>
              ))}
            </div>
          </Section>

          {/* Samples by strategy/class */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <Section title="Samples by Strategy">
              {Object.keys(learn.by_strategy || {}).length > 0 ? (
                Object.entries(learn.by_strategy).map(([s, cnt]: [string, any]) => (
                  <div key={s} className="flex justify-between py-1 text-xs border-b border-bah-border/20">
                    <span className="text-bah-heading">{s}</span>
                    <span className="text-bah-muted font-mono">{cnt}</span>
                  </div>
                ))
              ) : <div className="text-xs text-bah-muted">No samples yet</div>}
            </Section>
            <Section title="Samples by Asset Class">
              {Object.keys(learn.by_class || {}).length > 0 ? (
                Object.entries(learn.by_class).map(([c, cnt]: [string, any]) => (
                  <div key={c} className="flex justify-between py-1 text-xs border-b border-bah-border/20">
                    <span className="text-bah-heading">{c}</span>
                    <span className="text-bah-muted font-mono">{cnt}</span>
                  </div>
                ))
              ) : <div className="text-xs text-bah-muted">No samples yet</div>}
            </Section>
          </div>
        </div>
      )}

      {/* ═══ RISK & EXPOSURE TAB ═══ */}
      {tab === "risk" && (
        <div className="space-y-4">
          <Section title="Exposure">
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              <Stat label="Gross" value={`$${(expo.gross_exposure || 0).toLocaleString()}`} />
              <Stat label="Net" value={`$${(expo.net_exposure || 0).toLocaleString()}`} />
              <Stat label="Long" value={`$${(expo.long_exposure || 0).toLocaleString()}`} cls="text-green-400" />
              <Stat label="Short" value={`$${(expo.short_exposure || 0).toLocaleString()}`} cls="text-red-400" />
            </div>
          </Section>

          <Section title="Position Utilization">
            <div className="flex items-center gap-4 mb-2">
              <div className="flex-1 bg-bah-bg rounded-full h-3 overflow-hidden">
                <div className="h-full rounded-full bg-bah-cyan/60 transition-all"
                     style={{ width: `${expo.utilization_pct || 0}%` }} />
              </div>
              <span className="text-xs text-bah-heading font-semibold">{expo.current_positions || 0} / {expo.max_positions || 20}</span>
            </div>
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
              <Stat label="Total Risk" value={`$${(expo.total_risk || 0).toLocaleString()}`} />
              <Stat label="Risk %" value={`${expo.risk_pct || 0}%`} />
              <Stat label="Utilization" value={`${expo.utilization_pct || 0}%`} />
            </div>
          </Section>

          {Object.keys(expo.per_class || {}).length > 0 && (
            <Section title="Exposure by Class">
              <div className="grid grid-cols-2 sm:grid-cols-5 gap-2">
                {Object.entries(expo.per_class).map(([cls, val]: [string, any]) => (
                  <div key={cls} className="bg-bah-bg border border-bah-border rounded-lg p-2.5 text-center">
                    <div className="text-[10px] text-bah-muted uppercase">{cls}</div>
                    <div className="text-xs text-bah-heading font-semibold">${val.toLocaleString()}</div>
                  </div>
                ))}
              </div>
            </Section>
          )}
        </div>
      )}
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="bg-bah-surface border border-bah-border rounded-xl p-4">
      <h3 className="text-xs font-semibold text-bah-heading mb-3 uppercase tracking-wide">{title}</h3>
      {children}
    </div>
  );
}

function Stat({ label, value, cls }: { label: string; value: any; cls?: string }) {
  return (
    <div className="text-center">
      <div className={`text-sm font-bold ${cls || "text-bah-heading"}`}>{value}</div>
      <div className="text-[9px] text-bah-muted uppercase">{label}</div>
    </div>
  );
}

function CandidatesPanel({ candidates }: { candidates: any[] }) {
  const [expanded, setExpanded] = useState(true);
  if (!candidates || candidates.length === 0) {
    return (
      <div className="bg-bah-surface border border-bah-border rounded-xl p-4">
        <h3 className="text-xs font-semibold text-bah-heading uppercase tracking-wide flex items-center gap-2">
          🔥 Trade Candidates
          <span className="text-[10px] font-normal text-bah-muted">— read-only intelligence</span>
        </h3>
        <p className="text-xs text-bah-muted mt-2">No high-probability setups yet. Candidates appear when assets approach trigger conditions.</p>
      </div>
    );
  }

  const scoreClr = (s: number) => s >= 90 ? "text-green-400 bg-green-500/15 border-green-500/30" : s >= 70 ? "text-amber-400 bg-amber-500/15 border-amber-500/30" : "text-bah-muted bg-bah-border/50 border-bah-border";
  const scoreBg = (s: number) => s >= 90 ? "bg-green-500" : s >= 70 ? "bg-amber-500" : "bg-bah-border";

  return (
    <div className="bg-bah-surface border border-bah-border rounded-xl overflow-hidden">
      <button onClick={() => setExpanded(!expanded)}
        className="w-full px-4 py-3 flex items-center justify-between hover:bg-white/[0.02] transition-colors">
        <div className="flex items-center gap-2">
          <span className="text-xs font-semibold text-bah-heading uppercase tracking-wide">🔥 Trade Candidates</span>
          <span className="px-1.5 py-0.5 text-[10px] font-bold rounded bg-bah-cyan/15 text-bah-cyan border border-bah-cyan/30">{candidates.length}</span>
          <span className="text-[10px] text-bah-muted">sorted by readiness score</span>
        </div>
        <span className="text-[10px] text-bah-muted">{expanded ? "▾" : "▸"}</span>
      </button>

      {expanded && (
        <div className="border-t border-bah-border">
          <div className="overflow-x-auto">
            <table className="w-full text-[11px] min-w-[900px]">
              <thead>
                <tr className="border-b border-bah-border text-left text-[10px] text-bah-muted uppercase tracking-wider">
                  <th className="px-3 py-2">Score</th>
                  <th className="px-3 py-2">Asset</th>
                  <th className="px-3 py-2">Class</th>
                  <th className="px-3 py-2">Strategy</th>
                  <th className="px-3 py-2">Dir</th>
                  <th className="px-3 py-2">Regime</th>
                  <th className="px-3 py-2">Distance</th>
                  <th className="px-3 py-2">RSI</th>
                  <th className="px-3 py-2">EMAs</th>
                  <th className="px-3 py-2">Setup</th>
                </tr>
              </thead>
              <tbody>
                {candidates.map((c: any, i: number) => (
                  <tr key={i} className="border-b border-bah-border/20 hover:bg-white/[0.015]">
                    <td className="px-3 py-2">
                      <div className="flex items-center gap-1.5">
                        <div className="w-8 h-1.5 bg-bah-bg rounded-full overflow-hidden">
                          <div className={`h-full rounded-full ${scoreBg(c.score)}`} style={{ width: `${c.score}%` }} />
                        </div>
                        <span className={`text-[11px] font-bold px-1.5 py-0.5 rounded border ${scoreClr(c.score)}`}>{c.score}</span>
                      </div>
                    </td>
                    <td className="px-3 py-2 text-bah-heading font-semibold">{c.asset}</td>
                    <td className="px-3 py-2 text-bah-muted">{c.asset_class}</td>
                    <td className="px-3 py-2 text-bah-muted">{c.strategy}</td>
                    <td className="px-3 py-2">
                      <span className={c.direction === "LONG" ? "text-green-400" : "text-red-400"}>{c.direction}</span>
                    </td>
                    <td className="px-3 py-2">
                      <span className={`px-1 py-0.5 rounded text-[9px] font-bold ${
                        c.regime === "TREND" || c.regime === "BREAKOUT" ? "bg-green-500/10 text-green-400" :
                        c.regime === "BEAR" ? "bg-red-500/10 text-red-400" :
                        "bg-bah-border/50 text-bah-muted"
                      }`}>{c.regime}</span>
                    </td>
                    <td className="px-3 py-2 text-[10px] text-bah-muted font-mono">{c.distance_to_trigger}</td>
                    <td className="px-3 py-2 text-[10px] font-mono">
                      <span className={
                        c.indicators?.rsi < 30 ? "text-green-400" :
                        c.indicators?.rsi > 70 ? "text-red-400" :
                        "text-bah-muted"
                      }>{c.indicators?.rsi?.toFixed(0) || "—"}</span>
                    </td>
                    <td className="px-3 py-2 text-[10px]">
                      <span className={`px-1 py-0.5 rounded ${
                        c.indicators?.ema_alignment === "bullish_stack" ? "bg-green-500/10 text-green-400" :
                        c.indicators?.ema_alignment === "bullish" ? "bg-green-500/5 text-green-400/70" :
                        c.indicators?.ema_alignment === "bearish_stack" ? "bg-red-500/10 text-red-400" :
                        c.indicators?.ema_alignment === "bearish" ? "bg-red-500/5 text-red-400/70" :
                        "text-bah-muted"
                      }`}>{c.indicators?.ema_alignment?.replace("_", " ") || "—"}</span>
                    </td>
                    <td className="px-3 py-2">
                      <div className="space-y-0.5">
                        {(c.reasons || []).slice(0, 3).map((r: string, j: number) => (
                          <div key={j} className="text-[10px] text-bah-muted leading-tight">{r}</div>
                        ))}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
