"use client";
import React, { useState, useEffect, useCallback } from "react";
import { apiBase } from "@/lib/utils";

// ═══════════════════════════════════════════
// HELPERS
// ═══════════════════════════════════════════
const fm = (n: number) => `$${Math.abs(n).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const fmS = (n: number) => `${n >= 0 ? "+" : "-"}${fm(n)}`;
const pnlC = (n: number) => n > 0.01 ? "text-green-400" : n < -0.01 ? "text-red-400" : "text-bah-muted";
const modeC = (m: string) =>
  m === "FROZEN" ? "text-red-400 bg-red-500/10 border-red-500/30"
  : m === "RESTRICTED" ? "text-orange-400 bg-orange-500/10 border-orange-500/30"
  : m === "CAUTION" ? "text-yellow-400 bg-yellow-500/10 border-yellow-500/30"
  : m === "BLOCKED" ? "text-red-400 bg-red-500/10 border-red-500/30"
  : m === "REDUCED" ? "text-yellow-400 bg-yellow-500/10 border-yellow-500/30"
  : "text-green-400 bg-green-500/10 border-green-500/30";

// ═══════════════════════════════════════════
// PANEL COMPONENT
// ═══════════════════════════════════════════
function P({ title, children, accent = "bah-cyan" }: { title: string; children: React.ReactNode; accent?: string }) {
  return (
    <div className="bg-bah-card border border-bah-border rounded-xl overflow-hidden">
      <div className={`px-4 py-2 border-b border-bah-border flex items-center gap-2`}>
        <div className={`w-1 h-3 rounded-sm bg-${accent}`} />
        <h3 className="text-[10px] font-bold text-bah-muted uppercase tracking-[0.12em] font-mono">{title}</h3>
      </div>
      <div className="p-3">{children}</div>
    </div>
  );
}

function Stat({ label, value, color }: { label: string; value: string | number; color?: string }) {
  return (
    <div className="text-center">
      <div className={`text-lg font-black font-mono ${color || "text-bah-heading"}`}>{value}</div>
      <div className="text-[8px] font-bold text-bah-muted uppercase tracking-wider mt-0.5">{label}</div>
    </div>
  );
}

function Badge({ label, color }: { label: string; color: string }) {
  return (
    <span className={`inline-flex px-1.5 py-0.5 rounded text-[8px] font-bold font-mono uppercase tracking-wider border ${color}`}>
      {label}
    </span>
  );
}

function StatusDot({ ok }: { ok: boolean }) {
  return <div className={`w-2 h-2 rounded-full ${ok ? "bg-green-400 shadow-[0_0_6px_rgba(16,185,129,0.5)]" : "bg-red-400 shadow-[0_0_6px_rgba(239,68,68,0.5)]"}`} />;
}

// ═══════════════════════════════════════════
// MAIN PAGE
// ═══════════════════════════════════════════
export default function DiagramDashboard() {
  const [d, setD] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [lastFetch, setLastFetch] = useState<Date | null>(null);

  const fetchData = useCallback(async () => {
    try {
      const t = localStorage.getItem("bahamut_admin_token");
      const h: Record<string, string> = t ? { Authorization: `Bearer ${t}` } : {};
      const r = await fetch(`${apiBase()}/training/diagram-dashboard`, { headers: h });
      if (r.ok) {
        const data = await r.json();
        setD(data);
        setError("");
        setLastFetch(new Date());
      } else {
        setError(`HTTP ${r.status}`);
      }
    } catch (e: any) {
      setError(e.message || "Fetch error");
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    fetchData();
    const iv = setInterval(fetchData, 15000);
    return () => clearInterval(iv);
  }, [fetchData]);

  if (loading && !d) {
    return (
      <div className="flex items-center justify-center h-64 text-bah-muted font-mono text-sm">
        <div className="animate-pulse">Loading Diagram Dashboard...</div>
      </div>
    );
  }

  const re = d?.risk_engine || {};
  const an = d?.adaptive_news || {};
  const anAssets = an?.assets || {};
  const anSummary = an?.summary || {};
  const exec = d?.execution || {};
  const strats = d?.strategies || {};
  const trust = d?.trust || {};
  const counters = d?.counters || {};
  const health = d?.health || {};
  const lastCycle = d?.last_cycle || {};
  const sentiment = d?.sentiment || {};
  const exposure = d?.exposure || {};

  const fgVal = sentiment?.fear_greed?.value;

  return (
    <div className="space-y-4">
      {/* HEADER */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-black text-bah-heading font-mono tracking-tight">DIAGRAM DASHBOARD</h1>
          <p className="text-[10px] text-bah-muted font-mono tracking-wider uppercase">
            Live System State · Architecture · Risk · Execution
          </p>
        </div>
        <div className="flex items-center gap-3">
          {error && <Badge label={`ERR: ${error}`} color="text-red-400 bg-red-500/10 border-red-500/30" />}
          {lastFetch && (
            <span className="text-[9px] text-bah-muted font-mono">
              Updated {lastFetch.toLocaleTimeString()}
            </span>
          )}
          <button onClick={fetchData} className="px-2 py-1 text-[9px] font-bold font-mono rounded border border-bah-cyan/40 bg-bah-cyan/10 text-bah-cyan hover:bg-bah-cyan/20 transition-all">
            REFRESH
          </button>
        </div>
      </div>

      {/* ═══ ROW 1: SYSTEM OVERVIEW ═══ */}
      <div className="grid grid-cols-5 gap-3">
        <P title="Portfolio">
          <Stat label="Equity" value={re.current_equity ? fm(re.current_equity) : "—"} color="text-green-400" />
        </P>
        <P title="Open Positions">
          <Stat label="Positions" value={d?.open_count ?? "—"} />
        </P>
        <P title="Total Trades">
          <Stat label="Trades" value={Object.values(strats).reduce((a: number, s: any) => a + (s.trades || 0), 0) || "—"} />
        </P>
        <P title="Fear & Greed">
          <Stat label="Crypto F&G" value={fgVal ?? "—"} color={fgVal <= 25 ? "text-red-400" : fgVal <= 50 ? "text-yellow-400" : "text-green-400"} />
        </P>
        <P title="Risk Mode">
          <div className="text-center">
            <Badge label={re.mode || "NORMAL"} color={modeC(re.mode || "NORMAL")} />
          </div>
        </P>
      </div>

      {/* ═══ ROW 2: STRATEGIES + ADAPTIVE NEWS + RISK ENGINE ═══ */}
      <div className="grid grid-cols-3 gap-3">

        {/* STRATEGIES */}
        <P title="Strategy Status" accent="green-400">
          <div className="space-y-2">
            {[
              { key: "v5_base", label: "V5 EMA Trend", regimes: "TREND" },
              { key: "v9_breakout", label: "V9 Breakout", regimes: "TREND · RANGE · BKOUT" },
              { key: "v10_mean_reversion", label: "V10 Mean Rev", regimes: "RANGE · CRASH" },
            ].map(s => {
              const sd = strats[s.key] || {};
              const td = (trust as any)?.[s.key] || {};
              return (
                <div key={s.key} className="bg-bah-surface rounded-lg p-2.5 border border-bah-border/50">
                  <div className="flex items-center justify-between mb-1.5">
                    <span className="text-[10px] font-bold text-bah-heading font-mono">{s.label}</span>
                    <Badge label={sd.win_rate >= 55 ? "HEALTHY" : sd.win_rate >= 45 ? "WEAK" : "POOR"} color={
                      sd.win_rate >= 55 ? modeC("NORMAL") : sd.win_rate >= 45 ? modeC("CAUTION") : modeC("BLOCKED")
                    } />
                  </div>
                  <div className="grid grid-cols-3 gap-1 text-[9px] font-mono">
                    <div>
                      <span className="text-bah-muted">WR </span>
                      <span className={sd.win_rate >= 55 ? "text-green-400" : "text-yellow-400"}>{sd.win_rate || 0}%</span>
                    </div>
                    <div>
                      <span className="text-bah-muted">PnL </span>
                      <span className={pnlC(sd.pnl || 0)}>{fmS(sd.pnl || 0)}</span>
                    </div>
                    <div>
                      <span className="text-bah-muted">Trades </span>
                      <span className="text-bah-heading">{sd.trades || 0}</span>
                    </div>
                  </div>
                  <div className="mt-1 flex gap-1">
                    {s.regimes.split(" · ").map(r => (
                      <span key={r} className="px-1 py-0.5 rounded bg-bah-cyan/10 text-bah-cyan text-[7px] font-bold font-mono">{r}</span>
                    ))}
                  </div>
                </div>
              );
            })}
          </div>
        </P>

        {/* ADAPTIVE NEWS */}
        <P title="Adaptive News Risk" accent="yellow-400">
          <div className="space-y-3">
            {/* Mode counts */}
            <div className="flex gap-2">
              {["NORMAL", "CAUTION", "RESTRICTED", "FROZEN"].map(m => (
                <div key={m} className={`flex-1 text-center rounded-lg py-1.5 border ${modeC(m)}`}>
                  <div className="text-sm font-black font-mono">{anSummary.mode_counts?.[m] ?? 0}</div>
                  <div className="text-[7px] font-bold uppercase tracking-wider">{m}</div>
                </div>
              ))}
            </div>
            {anSummary.starvation_guard_active && (
              <div className="bg-red-500/10 border border-red-500/30 rounded-lg px-3 py-1.5 text-[9px] text-red-400 font-bold font-mono text-center">
                ⚠ STARVATION GUARD ACTIVE
              </div>
            )}
            {/* Non-normal assets table */}
            {Object.entries(anAssets).filter(([, a]: [string, any]) => a.mode !== "NORMAL").length > 0 && (
              <div className="space-y-0.5">
                <div className="text-[8px] text-bah-muted font-bold uppercase tracking-wider mb-1">Affected Assets</div>
                {Object.entries(anAssets).filter(([, a]: [string, any]) => a.mode !== "NORMAL").slice(0, 8).map(([asset, a]: [string, any]) => (
                  <div key={asset} className="flex items-center justify-between text-[9px] font-mono py-0.5 border-b border-bah-border/20">
                    <div className="flex items-center gap-1.5">
                      <span className="text-bah-heading font-bold">{asset}</span>
                      <Badge label={a.mode} color={modeC(a.mode)} />
                    </div>
                    <div className="flex gap-2 text-bah-muted">
                      <span>bias:{a.bias}</span>
                      <span>{((a.size_multiplier || 1) * 100).toFixed(0)}%</span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </P>

        {/* RISK ENGINE */}
        <P title="Risk Engine" accent="orange-400">
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-[9px] text-bah-muted font-mono">Mode</span>
              <Badge label={re.mode || "NORMAL"} color={modeC(re.mode || "NORMAL")} />
            </div>
            <div className="flex items-center justify-between">
              <span className="text-[9px] text-bah-muted font-mono">Block New Trades</span>
              <span className={`text-[9px] font-bold font-mono ${re.block_new_trades ? "text-red-400" : "text-green-400"}`}>
                {re.block_new_trades ? "YES" : "NO"}
              </span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-[9px] text-bah-muted font-mono">Size Multiplier</span>
              <span className="text-[10px] font-bold font-mono text-bah-heading">{re.size_multiplier ?? 1.0}×</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-[9px] text-bah-muted font-mono">Daily PnL</span>
              <span className={`text-[10px] font-bold font-mono ${pnlC(re.current_daily_pnl || 0)}`}>
                {fmS(re.current_daily_pnl || 0)}
              </span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-[9px] text-bah-muted font-mono">Portfolio DD</span>
              <span className="text-[10px] font-bold font-mono text-bah-heading">
                {(re.current_portfolio_drawdown_pct || 0).toFixed(1)}%
              </span>
            </div>
            {/* Class utilization */}
            {exposure?.by_class && Object.keys(exposure.by_class).length > 0 && (
              <div className="border-t border-bah-border/50 pt-2 mt-1">
                <div className="text-[8px] text-bah-muted font-bold uppercase tracking-wider mb-1">Class Exposure</div>
                {Object.entries(exposure.by_class).map(([cls, e]: [string, any]) => (
                  <div key={cls} className="flex items-center justify-between text-[9px] font-mono py-0.5">
                    <span className="text-bah-muted uppercase">{cls}</span>
                    <span className="text-bah-heading">{e.positions || 0}/{e.cap_positions || "?"}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </P>
      </div>

      {/* ═══ ROW 3: TRADE FLOW + EXECUTION + COUNTERS ═══ */}
      <div className="grid grid-cols-3 gap-3">

        {/* TRADE FLOW */}
        <P title="Last Cycle Decisions">
          <div className="space-y-2">
            <div className="grid grid-cols-3 gap-2">
              <div className="text-center py-1.5 rounded-lg bg-green-500/10 border border-green-500/20">
                <div className="text-sm font-black font-mono text-green-400">{lastCycle.executed ?? 0}</div>
                <div className="text-[7px] font-bold text-green-400/60 uppercase">Executed</div>
              </div>
              <div className="text-center py-1.5 rounded-lg bg-yellow-500/10 border border-yellow-500/20">
                <div className="text-sm font-black font-mono text-yellow-400">{lastCycle.watchlist ?? 0}</div>
                <div className="text-[7px] font-bold text-yellow-400/60 uppercase">Watchlist</div>
              </div>
              <div className="text-center py-1.5 rounded-lg bg-red-500/10 border border-red-500/20">
                <div className="text-sm font-black font-mono text-red-400">{lastCycle.rejected ?? 0}</div>
                <div className="text-[7px] font-bold text-red-400/60 uppercase">Rejected</div>
              </div>
            </div>
            {d?.last_scan_time && (
              <div className="text-[9px] text-bah-muted font-mono">
                Last scan: {new Date(d.last_scan_time).toLocaleTimeString()}
              </div>
            )}
            {d?.cycle_count > 0 && (
              <div className="text-[9px] text-bah-muted font-mono">
                Total cycles: {d.cycle_count}
              </div>
            )}
            {lastCycle.executed === 0 && lastCycle.total > 0 && (
              <div className="bg-yellow-500/10 border border-yellow-500/30 rounded px-2 py-1 text-[9px] text-yellow-400 font-mono font-bold">
                ⚠ No trades executed this cycle
              </div>
            )}
          </div>
        </P>

        {/* EXECUTION */}
        <P title="Execution Status">
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-[9px] text-bah-muted font-mono">Binance Futures</span>
              <div className="flex items-center gap-1.5">
                <StatusDot ok={exec.binance_futures === "connected"} />
                <span className="text-[9px] font-mono text-bah-heading">{exec.binance_futures || "—"}</span>
              </div>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-[9px] text-bah-muted font-mono">Alpaca Paper</span>
              <div className="flex items-center gap-1.5">
                <StatusDot ok={exec.alpaca === "connected"} />
                <span className="text-[9px] font-mono text-bah-heading">{exec.alpaca || "—"}</span>
              </div>
            </div>
            {exec.binance_futures_balance && (
              <div className="flex items-center justify-between">
                <span className="text-[9px] text-bah-muted font-mono">Binance Balance</span>
                <span className="text-[9px] font-mono text-bah-heading">${parseFloat(exec.binance_futures_balance).toFixed(2)}</span>
              </div>
            )}
            {exec.alpaca_equity && (
              <div className="flex items-center justify-between">
                <span className="text-[9px] text-bah-muted font-mono">Alpaca Equity</span>
                <span className="text-[9px] font-mono text-bah-heading">${parseFloat(exec.alpaca_equity).toFixed(2)}</span>
              </div>
            )}
            {/* Open positions */}
            {(d?.open_positions?.length || 0) > 0 && (
              <div className="border-t border-bah-border/50 pt-2 mt-1">
                <div className="text-[8px] text-bah-muted font-bold uppercase tracking-wider mb-1">Open Positions</div>
                {d.open_positions.slice(0, 5).map((p: any, i: number) => (
                  <div key={i} className="flex items-center justify-between text-[9px] font-mono py-0.5">
                    <span className="text-bah-heading">{p.asset}</span>
                    <span className={p.direction === "LONG" ? "text-green-400" : "text-red-400"}>{p.direction}</span>
                    <span className="text-bah-muted">{p.strategy}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </P>

        {/* CONTAINMENT COUNTERS */}
        <P title="Containment Counters">
          <div className="space-y-1">
            {[
              { key: "engine_suppress_blocks", label: "Engine Suppress" },
              { key: "sentiment_gate_blocks", label: "Sentiment Gate" },
              { key: "risk_engine_blocks", label: "Risk Engine" },
              { key: "news_size_reductions", label: "News Size Reduce" },
              { key: "mature_neg_expectancy_blocks", label: "Neg Expectancy" },
            ].map(c => (
              <div key={c.key} className="flex items-center justify-between text-[9px] font-mono py-0.5">
                <span className="text-bah-muted">{c.label}</span>
                <span className={`font-bold ${(counters[c.key] || 0) > 0 ? "text-yellow-400" : "text-bah-heading"}`}>
                  {counters[c.key] || 0}
                </span>
              </div>
            ))}
          </div>
        </P>
      </div>

      {/* ═══ ROW 4: LEARNING + HEALTH ═══ */}
      <div className="grid grid-cols-2 gap-3">

        {/* LEARNING / TRUST */}
        <P title="Learning & Trust">
          <div className="space-y-2">
            <div className="grid grid-cols-3 gap-2">
              {[
                { key: "v5_base", label: "V5" },
                { key: "v9_breakout", label: "V9" },
                { key: "v10_mean_reversion", label: "V10" },
              ].map(s => {
                const t = (trust as any)?.[s.key] || {};
                return (
                  <div key={s.key} className="text-center bg-bah-surface rounded-lg py-2 border border-bah-border/50">
                    <div className="text-[7px] text-bah-muted font-bold uppercase tracking-wider">{s.label}</div>
                    <div className="text-sm font-black font-mono text-bah-heading">{(t.trust || 0.5).toFixed(3)}</div>
                    <div className="text-[7px] text-bah-muted font-mono">{t.maturity || "—"}</div>
                  </div>
                );
              })}
            </div>
            <div className="border-t border-bah-border/50 pt-2 space-y-1">
              <div className="flex items-center gap-1.5 text-[9px] font-mono">
                <StatusDot ok={true} />
                <span className="text-bah-muted">Production / Research isolation</span>
                <Badge label="ACTIVE" color={modeC("NORMAL")} />
              </div>
              <div className="flex items-center gap-1.5 text-[9px] font-mono">
                <StatusDot ok={true} />
                <span className="text-bah-muted">Legacy mode</span>
                <Badge label="DISABLED" color="text-bah-muted bg-bah-surface border-bah-border" />
              </div>
            </div>
          </div>
        </P>

        {/* SYSTEM HEALTH */}
        <P title="System Health">
          <div className="grid grid-cols-2 gap-2">
            {[
              { label: "Redis", ok: health.redis },
              { label: "Binance", ok: exec.binance_futures === "connected" },
              { label: "Alpaca", ok: exec.alpaca === "connected" },
              { label: "Legacy Off", ok: health.legacy_disabled },
              { label: "Adaptive News", ok: an.adaptive_news_enabled !== false },
              { label: "Risk Engine", ok: re.status === "active" },
            ].map((h, i) => (
              <div key={i} className="flex items-center gap-2 bg-bah-surface rounded-lg px-3 py-2 border border-bah-border/50">
                <StatusDot ok={h.ok} />
                <span className="text-[9px] font-mono text-bah-heading">{h.label}</span>
              </div>
            ))}
          </div>
          {d?.ts && (
            <div className="mt-2 text-[8px] text-bah-muted font-mono text-center">
              Server time: {new Date(d.ts).toLocaleString()}
            </div>
          )}
        </P>
      </div>
    </div>
  );
}
