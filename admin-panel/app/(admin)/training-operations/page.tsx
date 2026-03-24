"use client";

import { useState, useEffect, useRef } from "react";
import { apiBase } from "@/lib/utils";

export default function TrainingOperationsPage() {
  const [data, setData] = useState<any>(null);
  const [candidates, setCandidates] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [mounted, setMounted] = useState(false);
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
    setTimeout(() => setMounted(true), 50);
    return () => clearInterval(iv);
  }, []);

  if (loading) return (
    <div className="p-8 text-center text-white/40 text-sm animate-pulse">
      <div className="inline-block w-6 h-6 border-2 border-bah-cyan/30 border-t-bah-cyan rounded-full animate-spin mb-3" />
      <p>Loading training operations...</p>
    </div>
  );

  if (!data) return (
    <div className="p-8 text-center">
      <p className="text-lg font-bold text-white mb-2">Training Operations</p>
      <p className="text-sm text-white/50">Waiting for first training cycle. The training engine runs every 10 minutes.</p>
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
  const pnlClr = (v: number) => v >= 0 ? "text-emerald-400" : "text-red-400";
  const fmtPct = (v: number) => `${(v * 100).toFixed(1)}%`;
  const fmtTime = (s: string) => { if (!s) return "—"; try { return new Date(s).toLocaleString("en-GB", { hour12: false, month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }); } catch { return s; } };
  const fadeIn = (i: number) => mounted ? { opacity: 1, transform: "translateY(0)", transition: `all 0.4s ease ${i * 0.06}s` } : { opacity: 0, transform: "translateY(12px)" };

  return (
    <div className="p-2 sm:p-4 max-w-[1440px] space-y-4 pt-12 lg:pt-4">
      {/* ═══ INLINE ANIMATIONS ═══ */}
      <style>{`
        @keyframes slideUp { from { opacity: 0; transform: translateY(16px); } to { opacity: 1; transform: translateY(0); } }
        @keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }
        @keyframes barGrow { from { width: 0; } }
        @keyframes glow { 0%, 100% { box-shadow: 0 0 4px rgba(0,200,200,0.1); } 50% { box-shadow: 0 0 12px rgba(0,200,200,0.25); } }
        .anim-slide { animation: slideUp 0.5s ease forwards; }
        .anim-fade { animation: fadeIn 0.4s ease forwards; }
        .anim-bar { animation: barGrow 0.8s ease forwards; }
        .anim-glow { animation: glow 3s ease-in-out infinite; }
        .hover-row { transition: background 0.15s ease; }
        .hover-row:hover { background: rgba(255,255,255,0.025); }
      `}</style>

      {/* ═══ HEADER ═══ */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 anim-slide" style={{ animationDelay: "0s" }}>
        <div className="flex items-center gap-3 flex-wrap">
          <h1 className="text-base sm:text-lg font-bold text-white tracking-tight">Training Operations</h1>
          <span className="px-2.5 py-0.5 text-[10px] rounded-full font-bold border bg-purple-500/20 text-purple-300 border-purple-500/40 tracking-wider">PAPER ONLY</span>
          <span className="text-[11px] text-white/50">{k.universe_size || 0} assets · ${(k.virtual_capital || 100000).toLocaleString()} virtual</span>
        </div>
        {cy.last_run && (
          <span className="text-[11px] text-white/40 font-mono">
            Last cycle: {fmtTime(cy.last_run)} · {cy.duration_ms}ms ·{" "}
            <span className={`font-semibold ${cy.status === "OK" ? "text-emerald-400" : cy.status === "DEGRADED" ? "text-amber-400" : "text-red-400"}`}>{cy.status}</span>
          </span>
        )}
      </div>

      {/* ═══ ALERTS ═══ */}
      {alerts.length > 0 && (
        <div className="space-y-1.5 anim-slide" style={{ animationDelay: "0.05s" }}>
          {alerts.map((a: any, i: number) => (
            <div key={i} className={`px-4 py-2.5 rounded-lg text-xs font-medium border ${a.level === "WARNING" ? "bg-amber-500/8 border-amber-500/25 text-amber-300" : "bg-white/[0.03] border-white/10 text-white/60"}`}>
              {a.level === "WARNING" ? "⚠️" : "ℹ️"} {a.message}
            </div>
          ))}
        </div>
      )}

      {/* ═══ TRADE CANDIDATES ═══ */}
      <div className="anim-slide" style={{ animationDelay: "0.1s" }}>
        <CandidatesPanel candidates={candidates} mounted={mounted} />
      </div>

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
          <div key={i} className="bg-bah-surface border border-white/[0.06] rounded-lg p-2.5 text-center anim-slide" style={{ animationDelay: `${0.15 + i * 0.03}s` }}>
            <div className={`text-sm font-bold ${kpi.cls || "text-white"}`}>{kpi.value}</div>
            <div className="text-[9px] text-white/35 uppercase tracking-wider font-medium">{kpi.label}</div>
          </div>
        ))}
      </div>

      {/* ═══ TABS ═══ */}
      <div className="flex border-b border-white/[0.08] overflow-x-auto">
        {(["overview", "positions", "trades", "learning", "risk"] as const).map(t => (
          <button key={t} onClick={() => setTab(t)} className={`px-4 py-2.5 text-xs font-semibold border-b-2 transition-all duration-200 whitespace-nowrap ${
            tab === t ? "border-bah-cyan text-bah-cyan" : "border-transparent text-white/35 hover:text-white/70"
          }`}>
            {t === "overview" ? "📊 Overview" : t === "positions" ? `📦 Positions (${k.open_positions || 0})` : t === "trades" ? `🔁 Trades (${k.closed_trades || 0})` : t === "learning" ? "🧬 Learning" : "⚖️ Risk & Exposure"}
          </button>
        ))}
      </div>

      {/* ═══ OVERVIEW TAB ═══ */}
      {tab === "overview" && (
        <div className="space-y-4 anim-fade">
          <Section title="Cycle Health">
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              <Stat label="Processed" value={cy.assets_processed} />
              <Stat label="Skipped" value={cy.assets_skipped} />
              <Stat label="Errors" value={cy.errors} cls={cy.errors > 0 ? "text-red-400" : ""} />
              <Stat label="Signals" value={cy.signals_generated} />
            </div>
          </Section>

          <Section title="Strategy Breakdown">
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead><tr className="border-b border-white/[0.08] text-left text-[10px] text-white/30 uppercase tracking-wider">
                  <th className="py-2.5 pr-3">Strategy</th><th className="py-2.5 pr-3">Open</th><th className="py-2.5 pr-3">Closed</th>
                  <th className="py-2.5 pr-3">WR</th><th className="py-2.5 pr-3">PF</th><th className="py-2.5 pr-3">PnL</th>
                  <th className="py-2.5 pr-3">Avg Bars</th><th className="py-2.5">Status</th>
                </tr></thead>
                <tbody>
                  {Object.entries(strats).map(([name, s]: [string, any]) => (
                    <tr key={name} className="border-b border-white/[0.04] hover-row">
                      <td className="py-2.5 pr-3 text-white font-semibold">{name}</td>
                      <td className="py-2.5 pr-3 text-white/60">{s.open_trades}</td>
                      <td className="py-2.5 pr-3 text-white/60">{s.closed_trades}</td>
                      <td className="py-2.5 pr-3 text-white/80">{fmtPct(s.win_rate)}</td>
                      <td className="py-2.5 pr-3 text-white/80">{s.profit_factor.toFixed(2)}</td>
                      <td className={`py-2.5 pr-3 font-semibold ${pnlClr(s.total_pnl)}`}>{fmtPnl(s.total_pnl)}</td>
                      <td className="py-2.5 pr-3 text-white/50">{s.avg_hold_bars?.toFixed(1)}</td>
                      <td className="py-2.5">
                        <span className={`px-2 py-0.5 rounded text-[9px] font-bold tracking-wide ${s.provisional ? "bg-amber-500/15 text-amber-300 border border-amber-500/25" : "bg-emerald-500/15 text-emerald-300 border border-emerald-500/25"}`}>
                          {s.provisional ? "WARMING" : "ACTIVE"}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Section>

          <Section title="Asset Class Breakdown">
            <div className="grid grid-cols-2 sm:grid-cols-5 gap-2.5">
              {Object.entries(classes).map(([cls, s]: [string, any], i) => (
                <div key={cls} className="bg-white/[0.02] border border-white/[0.06] rounded-lg p-3 anim-slide" style={{ animationDelay: `${i * 0.05}s` }}>
                  <div className="text-[10px] text-white/40 uppercase mb-1 tracking-wider font-semibold">{cls}</div>
                  <div className="text-xs text-white font-semibold">{s.closed_trades} closed · {s.open_trades} open</div>
                  <div className={`text-[11px] font-semibold mt-0.5 ${pnlClr(s.pnl)}`}>{fmtPnl(s.pnl)} · {fmtPct(s.win_rate)} WR</div>
                </div>
              ))}
            </div>
          </Section>

          {(rankings.best?.length > 0 || rankings.worst?.length > 0) && (
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              {rankings.best?.length > 0 && (
                <Section title="🏆 Best Assets">
                  {rankings.best.map((a: any, i: number) => (
                    <div key={i} className="flex justify-between items-center py-2 text-xs border-b border-white/[0.04] hover-row px-1 rounded">
                      <div><span className="text-white font-semibold">{a.asset}</span> <span className="text-[10px] text-white/40 ml-1">{a.class}</span></div>
                      <div className="text-emerald-400 font-semibold">{fmtPnl(a.pnl)} <span className="text-white/30 font-normal">({a.trades}t)</span></div>
                    </div>
                  ))}
                </Section>
              )}
              {rankings.worst?.length > 0 && (
                <Section title="⚠️ Worst Assets">
                  {rankings.worst.map((a: any, i: number) => (
                    <div key={i} className="flex justify-between items-center py-2 text-xs border-b border-white/[0.04] hover-row px-1 rounded">
                      <div><span className="text-white font-semibold">{a.asset}</span> <span className="text-[10px] text-white/40 ml-1">{a.class}</span></div>
                      <div className="text-red-400 font-semibold">{fmtPnl(a.pnl)} <span className="text-white/30 font-normal">({a.trades}t)</span></div>
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
        <div className="anim-fade">
        <Section title={`Open Positions (${data.positions?.length || 0})`}>
          {data.positions?.length > 0 ? (
            <div className="overflow-x-auto">
              <table className="w-full text-[11px] min-w-[800px]">
                <thead><tr className="border-b border-white/[0.08] text-left text-[10px] text-white/30 uppercase tracking-wider">
                  <th className="py-2.5 pr-2">Asset</th><th className="py-2.5 pr-2">Class</th><th className="py-2.5 pr-2">Strategy</th>
                  <th className="py-2.5 pr-2">Dir</th><th className="py-2.5 pr-2">Entry</th><th className="py-2.5 pr-2">Current</th>
                  <th className="py-2.5 pr-2">SL</th><th className="py-2.5 pr-2">TP</th>
                  <th className="py-2.5 pr-2">Unreal PnL</th><th className="py-2.5 pr-2">Bars</th>
                </tr></thead>
                <tbody>
                  {data.positions.map((p: any, i: number) => (
                    <tr key={i} className="border-b border-white/[0.04] hover-row">
                      <td className="py-2 pr-2 text-white font-semibold">{p.asset}</td>
                      <td className="py-2 pr-2 text-white/50">{p.asset_class}</td>
                      <td className="py-2 pr-2 text-white/60">{p.strategy}</td>
                      <td className="py-2 pr-2"><span className={`font-semibold ${p.direction === "LONG" ? "text-emerald-400" : "text-red-400"}`}>{p.direction}</span></td>
                      <td className="py-2 pr-2 font-mono text-white/70">{p.entry_price}</td>
                      <td className="py-2 pr-2 font-mono text-white/70">{p.current_price}</td>
                      <td className="py-2 pr-2 font-mono text-red-400/50">{p.stop_price || p.stop_loss}</td>
                      <td className="py-2 pr-2 font-mono text-emerald-400/50">{p.tp_price || p.take_profit}</td>
                      <td className={`py-2 pr-2 font-bold ${pnlClr(p.unrealized_pnl || 0)}`}>{fmtPnl(p.unrealized_pnl || 0)}</td>
                      <td className="py-2 pr-2 text-white/50">{p.bars_held || p.duration_bars || 0}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="text-center py-10 text-white/40 text-sm">No open training positions. Waiting for signals at next 4H bar boundary.</div>
          )}
        </Section>
        </div>
      )}

      {/* ═══ TRADES TAB ═══ */}
      {tab === "trades" && (
        <div className="anim-fade">
        <Section title="Closed Trades (last 50)">
          {data.closed_trades?.length > 0 ? (
            <div className="overflow-x-auto">
              <table className="w-full text-[11px] min-w-[900px]">
                <thead><tr className="border-b border-white/[0.08] text-left text-[10px] text-white/30 uppercase tracking-wider">
                  <th className="py-2.5 pr-2">Asset</th><th className="py-2.5 pr-2">Class</th><th className="py-2.5 pr-2">Strategy</th>
                  <th className="py-2.5 pr-2">Dir</th><th className="py-2.5 pr-2">Entry</th><th className="py-2.5 pr-2">Exit</th>
                  <th className="py-2.5 pr-2">PnL</th><th className="py-2.5 pr-2">Exit</th>
                  <th className="py-2.5 pr-2">Bars</th><th className="py-2.5 pr-2">Closed</th>
                </tr></thead>
                <tbody>
                  {data.closed_trades.map((t: any, i: number) => (
                    <tr key={i} className="border-b border-white/[0.04] hover-row">
                      <td className="py-2 pr-2 text-white font-semibold">{t.asset}</td>
                      <td className="py-2 pr-2 text-white/50">{t.asset_class}</td>
                      <td className="py-2 pr-2 text-white/60">{t.strategy}</td>
                      <td className="py-2 pr-2"><span className={`font-semibold ${t.direction === "LONG" ? "text-emerald-400" : "text-red-400"}`}>{t.direction}</span></td>
                      <td className="py-2 pr-2 font-mono text-white/70">{typeof t.entry_price === "number" ? t.entry_price.toFixed(2) : t.entry_price}</td>
                      <td className="py-2 pr-2 font-mono text-white/70">{typeof t.exit_price === "number" ? t.exit_price.toFixed(2) : t.exit_price}</td>
                      <td className={`py-2 pr-2 font-bold ${pnlClr(t.pnl || 0)}`}>${(t.pnl || 0).toFixed(2)}</td>
                      <td className="py-2 pr-2"><span className={`px-1.5 py-0.5 rounded text-[9px] font-bold ${
                        t.exit_reason === "TP" ? "bg-emerald-500/15 text-emerald-300" :
                        t.exit_reason === "SL" ? "bg-red-500/15 text-red-300" :
                        "bg-white/[0.06] text-white/50"
                      }`}>{t.exit_reason}</span></td>
                      <td className="py-2 pr-2 text-white/50">{t.bars_held}</td>
                      <td className="py-2 pr-2 text-white/40 text-[10px]">{fmtTime(t.exit_time)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="text-center py-10 text-white/40 text-sm">No closed training trades yet. First trades will close after SL/TP/timeout triggers.</div>
          )}
        </Section>
        </div>
      )}

      {/* ═══ LEARNING TAB ═══ */}
      {tab === "learning" && (
        <div className="space-y-4 anim-fade">
          <Section title="Learning Progress">
            <div className="flex items-center gap-4 mb-4">
              <div className="flex-1 bg-white/[0.04] rounded-full h-3.5 overflow-hidden">
                <div className="h-full rounded-full bg-gradient-to-r from-purple-500 via-bah-cyan to-emerald-400 anim-bar"
                     style={{ width: `${learn.progress_pct || 0}%` }} />
              </div>
              <span className="text-sm text-white font-bold">{learn.progress_pct || 0}%</span>
            </div>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-5">
              <Stat label="Total Samples" value={learn.total_samples} />
              <Stat label="Status" value={learn.status?.toUpperCase() || "—"} cls={learn.status === "ready" ? "text-emerald-400" : learn.status === "learning" ? "text-bah-cyan" : "text-amber-300"} />
              <Stat label="Trust Ready" value={learn.trust_ready ? "YES" : "NO"} cls={learn.trust_ready ? "text-emerald-400" : "text-white/30"} />
              <Stat label="Adaptive Ready" value={learn.adaptive_ready ? "YES" : "NO"} cls={learn.adaptive_ready ? "text-emerald-400" : "text-white/30"} />
            </div>
            <div className="space-y-2">
              {(learn.milestones || []).map((m: any, i: number) => (
                <div key={i} className="flex items-center gap-3 text-xs anim-slide" style={{ animationDelay: `${i * 0.08}s` }}>
                  <span className={`w-6 h-6 rounded-full flex items-center justify-center text-[10px] font-bold border transition-all ${
                    m.reached ? "bg-emerald-500/20 text-emerald-300 border-emerald-500/40 shadow-sm shadow-emerald-500/20" : "bg-white/[0.04] text-white/30 border-white/10"
                  }`}>{m.reached ? "✓" : i + 1}</span>
                  <span className={`font-medium ${m.reached ? "text-white" : "text-white/40"}`}>{m.label}</span>
                  <span className="text-[10px] text-white/25">({m.current || 0}/{m.required})</span>
                </div>
              ))}
            </div>
          </Section>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <Section title="Samples by Strategy">
              {Object.keys(learn.by_strategy || {}).length > 0 ? (
                Object.entries(learn.by_strategy).map(([s, cnt]: [string, any]) => (
                  <div key={s} className="flex justify-between py-1.5 text-xs border-b border-white/[0.04]">
                    <span className="text-white font-medium">{s}</span>
                    <span className="text-white/50 font-mono">{cnt}</span>
                  </div>
                ))
              ) : <div className="text-xs text-white/30">No samples yet</div>}
            </Section>
            <Section title="Samples by Asset Class">
              {Object.keys(learn.by_class || {}).length > 0 ? (
                Object.entries(learn.by_class).map(([c, cnt]: [string, any]) => (
                  <div key={c} className="flex justify-between py-1.5 text-xs border-b border-white/[0.04]">
                    <span className="text-white font-medium">{c}</span>
                    <span className="text-white/50 font-mono">{cnt}</span>
                  </div>
                ))
              ) : <div className="text-xs text-white/30">No samples yet</div>}
            </Section>
          </div>
        </div>
      )}

      {/* ═══ RISK & EXPOSURE TAB ═══ */}
      {tab === "risk" && (
        <div className="space-y-4 anim-fade">
          <Section title="Exposure">
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              <Stat label="Gross" value={`$${(expo.gross_exposure || 0).toLocaleString()}`} />
              <Stat label="Net" value={`$${(expo.net_exposure || 0).toLocaleString()}`} />
              <Stat label="Long" value={`$${(expo.long_exposure || 0).toLocaleString()}`} cls="text-emerald-400" />
              <Stat label="Short" value={`$${(expo.short_exposure || 0).toLocaleString()}`} cls="text-red-400" />
            </div>
          </Section>

          <Section title="Position Utilization">
            <div className="flex items-center gap-4 mb-3">
              <div className="flex-1 bg-white/[0.04] rounded-full h-3.5 overflow-hidden">
                <div className="h-full rounded-full bg-bah-cyan/50 anim-bar" style={{ width: `${expo.utilization_pct || 0}%` }} />
              </div>
              <span className="text-sm text-white font-bold">{expo.current_positions || 0} / {expo.max_positions || 20}</span>
            </div>
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
              <Stat label="Total Risk" value={`$${(expo.total_risk || 0).toLocaleString()}`} />
              <Stat label="Risk %" value={`${expo.risk_pct || 0}%`} />
              <Stat label="Utilization" value={`${expo.utilization_pct || 0}%`} />
            </div>
          </Section>

          {Object.keys(expo.per_class || {}).length > 0 && (
            <Section title="Exposure by Class">
              <div className="grid grid-cols-2 sm:grid-cols-5 gap-2.5">
                {Object.entries(expo.per_class).map(([cls, val]: [string, any]) => (
                  <div key={cls} className="bg-white/[0.02] border border-white/[0.06] rounded-lg p-3 text-center">
                    <div className="text-[10px] text-white/35 uppercase tracking-wider font-medium">{cls}</div>
                    <div className="text-xs text-white font-bold mt-0.5">${val.toLocaleString()}</div>
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
    <div className="bg-bah-surface border border-white/[0.06] rounded-xl p-4">
      <h3 className="text-xs font-bold text-white/80 mb-3 uppercase tracking-wider">{title}</h3>
      {children}
    </div>
  );
}

function Stat({ label, value, cls }: { label: string; value: any; cls?: string }) {
  return (
    <div className="text-center">
      <div className={`text-sm font-bold ${cls || "text-white"}`}>{value}</div>
      <div className="text-[9px] text-white/30 uppercase tracking-wider font-medium">{label}</div>
    </div>
  );
}

function CandidatesPanel({ candidates, mounted }: { candidates: any[]; mounted: boolean }) {
  const [expanded, setExpanded] = useState(true);

  if (!candidates || candidates.length === 0) {
    return (
      <div className="bg-bah-surface border border-white/[0.06] rounded-xl p-4">
        <h3 className="text-xs font-bold text-white/80 uppercase tracking-wider flex items-center gap-2">
          🔥 Trade Candidates
          <span className="text-[10px] font-normal text-white/30">— read-only intelligence</span>
        </h3>
        <p className="text-xs text-white/40 mt-2">No high-probability setups yet. Candidates appear when assets approach trigger conditions.</p>
      </div>
    );
  }

  const scoreClr = (s: number) =>
    s >= 90 ? "text-emerald-300 bg-emerald-500/20 border-emerald-500/40" :
    s >= 70 ? "text-amber-300 bg-amber-500/20 border-amber-500/40" :
    s >= 50 ? "text-white/70 bg-white/[0.06] border-white/10" :
    "text-white/40 bg-white/[0.03] border-white/[0.06]";

  const scoreBg = (s: number) =>
    s >= 90 ? "bg-emerald-400" : s >= 70 ? "bg-amber-400" : s >= 50 ? "bg-white/30" : "bg-white/15";

  return (
    <div className="bg-bah-surface border border-white/[0.06] rounded-xl overflow-hidden">
      <button onClick={() => setExpanded(!expanded)}
        className="w-full px-4 py-3 flex items-center justify-between hover:bg-white/[0.02] transition-all duration-200">
        <div className="flex items-center gap-2.5">
          <span className="text-xs font-bold text-white/80 uppercase tracking-wider">🔥 Trade Candidates</span>
          <span className="px-2 py-0.5 text-[10px] font-bold rounded bg-bah-cyan/15 text-bah-cyan border border-bah-cyan/30 anim-glow">{candidates.length}</span>
          <span className="text-[10px] text-white/35">sorted by readiness</span>
        </div>
        <span className="text-[10px] text-white/30">{expanded ? "▾" : "▸"}</span>
      </button>

      {expanded && (
        <div className="border-t border-white/[0.06]">
          <div className="overflow-x-auto">
            <table className="w-full text-[11px] min-w-[1000px]">
              <thead>
                <tr className="border-b border-white/[0.08] text-left text-[10px] text-white/25 uppercase tracking-wider">
                  <th className="px-3 py-2.5">Score</th>
                  <th className="px-3 py-2.5">Asset</th>
                  <th className="px-3 py-2.5">Class</th>
                  <th className="px-3 py-2.5">Strategy</th>
                  <th className="px-3 py-2.5">Dir</th>
                  <th className="px-3 py-2.5">Regime</th>
                  <th className="px-3 py-2.5">Distance</th>
                  <th className="px-3 py-2.5">RSI</th>
                  <th className="px-3 py-2.5">EMAs</th>
                  <th className="px-3 py-2.5">Setup</th>
                </tr>
              </thead>
              <tbody>
                {candidates.map((c: any, i: number) => (
                  <tr key={i} className="border-b border-white/[0.03] hover-row anim-slide" style={{ animationDelay: `${i * 0.04}s` }}>
                    <td className="px-3 py-2.5">
                      <div className="flex items-center gap-2">
                        <div className="w-10 h-2 bg-white/[0.04] rounded-full overflow-hidden">
                          <div className={`h-full rounded-full anim-bar ${scoreBg(c.score)}`} style={{ width: `${c.score}%`, animationDelay: `${0.3 + i * 0.05}s` }} />
                        </div>
                        <span className={`text-[11px] font-bold px-2 py-0.5 rounded border ${scoreClr(c.score)}`}>{c.score}</span>
                      </div>
                    </td>
                    <td className="px-3 py-2.5 text-white font-bold">{c.asset}</td>
                    <td className="px-3 py-2.5 text-white/50 font-medium">{c.asset_class}</td>
                    <td className="px-3 py-2.5 text-white/60">{c.strategy}</td>
                    <td className="px-3 py-2.5">
                      <span className={`font-bold ${c.direction === "LONG" ? "text-emerald-400" : "text-red-400"}`}>{c.direction}</span>
                    </td>
                    <td className="px-3 py-2.5">
                      <span className={`px-1.5 py-0.5 rounded text-[9px] font-bold tracking-wide ${
                        c.regime === "TREND" || c.regime === "BREAKOUT" ? "bg-emerald-500/15 text-emerald-300 border border-emerald-500/25" :
                        c.regime === "BEAR" ? "bg-red-500/15 text-red-300 border border-red-500/25" :
                        "bg-white/[0.05] text-white/50 border border-white/10"
                      }`}>{c.regime}</span>
                    </td>
                    <td className="px-3 py-2.5 text-[10px] text-white/60 font-mono">{c.distance_to_trigger}</td>
                    <td className="px-3 py-2.5 font-mono">
                      <span className={`font-semibold ${
                        c.indicators?.rsi < 30 ? "text-emerald-400" :
                        c.indicators?.rsi > 70 ? "text-red-400" :
                        "text-white/60"
                      }`}>{c.indicators?.rsi?.toFixed(0) || "—"}</span>
                    </td>
                    <td className="px-3 py-2.5">
                      <span className={`px-1.5 py-0.5 rounded text-[10px] font-semibold ${
                        c.indicators?.ema_alignment === "bullish_stack" ? "bg-emerald-500/15 text-emerald-300" :
                        c.indicators?.ema_alignment === "bullish" ? "bg-emerald-500/8 text-emerald-400/70" :
                        c.indicators?.ema_alignment === "bearish_stack" ? "bg-red-500/15 text-red-300" :
                        c.indicators?.ema_alignment === "bearish" ? "bg-red-500/8 text-red-400/70" :
                        "text-white/40"
                      }`}>{c.indicators?.ema_alignment?.replace("_", " ") || "—"}</span>
                    </td>
                    <td className="px-3 py-2.5">
                      <div className="space-y-0.5 max-w-[280px]">
                        {(c.reasons || []).slice(0, 3).map((r: string, j: number) => (
                          <div key={j} className="text-[10px] text-white/55 leading-snug">{r}</div>
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
