"use client";
import { useState, useEffect, useCallback, useRef } from "react";
import { apiBase } from "@/lib/utils";

export default function DailyOperations() {
  const [portfolio, setPortfolio] = useState<any>(null);
  const [strategies, setStrategies] = useState<any>(null);
  const [positions, setPositions] = useState<any>(null);
  const [trades, setTrades] = useState<any>(null);
  
  const [alerts, setAlerts] = useState<any[]>([]);
  const [hiddenAlerts, setHiddenAlerts] = useState<number[]>([]);
  const [health, setHealth] = useState<any>(null);
  const [lastCycle, setLastCycle] = useState<any>(null);
  const [cycleHistory, setCycleHistory] = useState<any>(null);
  const [timing, setTiming] = useState<any>(null);
  const [stratConds, setStratConds] = useState<any>({});
  const [performance, setPerformance] = useState<any>(null);
  const [countdown, setCountdown] = useState(0);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState<"cycle" | "conditions" | "strategies" | "positions" | "trades" | "alerts" | "training">("cycle");
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [secondsAgo, setSecondsAgo] = useState(0);
  const [isMobile, setIsMobile] = useState(false);

  // Detect mobile
  useEffect(() => {
    const check = () => setIsMobile(window.innerWidth < 1024);
    check();
    window.addEventListener("resize", check);
    return () => window.removeEventListener("resize", check);
  }, []);

  const token = typeof window !== "undefined" ? sessionStorage.getItem("bah_token") : null;
  const api = useCallback(async (path: string) => {
    try {
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 8000);
      const r = await fetch(`${apiBase()}/monitoring${path}`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        signal: controller.signal,
      });
      clearTimeout(timeout);
      if (r.ok) return r.json();
    } catch {} return null;
  }, [token]);
  const v7 = useCallback(async (path: string, opts?: any) => {
    try {
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 30000);
      const r = await fetch(`${apiBase()}/v7${path}`, {
        headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
        signal: controller.signal, ...opts,
      });
      clearTimeout(timeout);
      if (r.ok) return r.json();
    } catch {} return null;
  }, [token]);

  const load = useCallback(async () => {
    const d = await api("/dashboard");
    if (d) {
      setPortfolio(d.portfolio);
      setStrategies(d.strategies);
      setPositions(d.positions);
      setTrades(d.trades);
      setAlerts(d.alerts || []);
      setHealth(d.health);
      setLastCycle(d.last_cycle);
      setCycleHistory({ cycles: d.cycle_history, stats: d.cycle_stats });
      if (d.timing) { setTiming(d.timing); setCountdown(d.timing.seconds_until_next_close || 0); }
      if (d.strategy_conditions) setStratConds(d.strategy_conditions);
      if (d.performance) setPerformance(d.performance);
    }
    setLoading(false);
    setLastUpdated(new Date());
  }, [api]);

  // Live auto-refresh every 5 seconds
  useEffect(() => { load(); const i = setInterval(load, 5_000); return () => clearInterval(i); }, [load]);

  // Tick countdown + seconds-ago every second
  useEffect(() => {
    const i = setInterval(() => {
      if (lastUpdated) setSecondsAgo(Math.round((Date.now() - lastUpdated.getTime()) / 1000));
      setCountdown(c => Math.max(0, c - 1));
    }, 1000);
    return () => clearInterval(i);
  }, [lastUpdated]);

  // ── Run Cycle with progress bar ──
  const [cycleRunning, setCycleRunning] = useState(false);
  const [testTradeResult, setTestTradeResult] = useState<any>(null);
  const [testTradeLoading, setTestTradeLoading] = useState(false);
  const [cycleProgress, setCycleProgress] = useState(0);
  const [cycleError, setCycleError] = useState("");
  const progressRef = useRef<NodeJS.Timeout | null>(null);

  const runCycle = async () => {
    setCycleRunning(true); setCycleError(""); setCycleProgress(5);

    // Animate progress bar
    let prog = 5;
    progressRef.current = setInterval(() => {
      prog += Math.random() * 12 + 3;
      if (prog > 90) prog = 90;
      setCycleProgress(prog);
    }, 200);

    try {
      const res = await v7("/orchestrator/run-cycle", { method: "POST" });
      if (res?.status === "error") setCycleError(res.error || "Unknown error");
    } catch (e: any) { setCycleError(e.message || "Network error"); }

    // Complete progress bar
    if (progressRef.current) clearInterval(progressRef.current);
    setCycleProgress(100);
    setTimeout(() => { setCycleRunning(false); setCycleProgress(0); }, 600);

    // Rapid reload
    await load();
    setTimeout(load, 1000);
  };

  const killSwitch = async () => { if (confirm("Kill switch?")) { await v7("/portfolio/kill-switch", { method: "POST" }); load(); } };
  const resume = async () => { await v7("/portfolio/resume", { method: "POST" }); load(); };

  if (loading) return <div className="p-8 text-bah-muted">Loading...</div>;

  const p = portfolio;
  const dd = p?.drawdown_pct || 0;
  const risk = p?.open_risk_pct || 0;
  const pnl = p?.pnl_total || 0;
  const lc = lastCycle;
  const cStats = cycleHistory?.stats || {};
  const cList = cycleHistory?.cycles || [];
  const critAlerts = alerts.filter(a => a.level === "CRITICAL" && a.status !== "RESOLVED").length;

  // Format helpers
  const fmtTime = (iso: string) => { if (!iso) return "—"; try { const d = new Date(iso); return d.toLocaleTimeString("en-GB", { hour12: false }); } catch { return iso; } };
  const fmtDateTime = (iso: string) => { if (!iso) return "—"; try { const d = new Date(iso); return d.toLocaleString("en-GB", { hour12: false, month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit" }); } catch { return iso; } };
  const fmtDur = (ms: number) => ms < 1000 ? `${ms}ms` : `${(ms/1000).toFixed(1)}s`;
  const fmtCountdown = (secs: number) => { const h = Math.floor(secs/3600); const m = Math.floor((secs%3600)/60); const s = secs%60; return `${h.toString().padStart(2,"0")}:${m.toString().padStart(2,"0")}:${s.toString().padStart(2,"0")}`; };
  const statusClr = (s: string) => s === "SUCCESS" ? "text-green-400" : s === "ERROR" ? "text-red-400" : s === "SKIPPED" ? "text-amber-400" : "text-bah-cyan";
  const statusBg = (s: string) => s === "SUCCESS" ? "bg-green-500/15 border-green-500/30" : s === "ERROR" ? "bg-red-500/15 border-red-500/30" : s === "SKIPPED" ? "bg-amber-500/15 border-amber-500/30" : "bg-bah-cyan/15 border-bah-cyan/30";
  const resultClr = (r: string) => r === "EXECUTED" ? "text-green-400" : r === "BLOCKED" ? "text-amber-400" : r === "NO_SIGNAL" ? "text-bah-muted" : r === "SIGNAL" ? "text-bah-cyan" : "text-bah-muted";

  return (
    <div className="p-2 sm:p-4 max-w-[1440px] space-y-3 pt-12 lg:pt-4">
      {/* ═══ HEADER ═══ */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
        <div className="flex items-center gap-2 flex-wrap">
          <h1 className="text-base sm:text-lg font-bold text-bah-heading">Daily Operations Monitor</h1>
          {p?.kill_switch ? (
            <span className="px-2 py-0.5 text-[10px] rounded-full font-semibold border bg-red-500/20 text-red-400 border-red-500/30">HALTED</span>
          ) : (
            <span className="px-2 py-0.5 text-[10px] rounded-full font-semibold border bg-green-500/20 text-green-400 border-green-500/30">
              LIVE{health?.data_source === "LIVE" ? "" : ` · ${health?.data_source || "?"}`}
            </span>
          )}
          {health?.engine && <span className="px-2 py-0.5 text-[10px] rounded-full text-bah-muted border border-bah-border">{health.engine}</span>}
          {critAlerts > 0 && <button onClick={() => setTab("alerts")} className="px-2 py-0.5 text-[10px] rounded-full bg-red-500/20 text-red-400 border border-red-500/30 animate-pulse cursor-pointer hover:bg-red-500/30 transition-colors">{critAlerts} CRITICAL</button>}
        </div>
        <div className="flex gap-2 items-center">
          <span className="text-[10px] text-bah-muted font-mono flex items-center gap-1.5">
            <span className={`inline-block w-1.5 h-1.5 rounded-full ${secondsAgo < 10 ? "bg-green-400 animate-pulse" : secondsAgo < 30 ? "bg-amber-400" : "bg-red-400"}`} />
            {secondsAgo}s ago
          </span>
          <button onClick={runCycle} disabled={cycleRunning} className={`px-3 py-1.5 border rounded-lg text-xs font-semibold transition-all ${
            cycleRunning ? "bg-bah-cyan/30 border-bah-cyan/50 text-bah-cyan" : "bg-bah-cyan/20 border-bah-cyan/40 text-bah-cyan hover:bg-bah-cyan/30"
          }`}>{cycleRunning ? "⟳ Running..." : "▶ Run Cycle"}</button>
          <button onClick={() => load()} className="px-3 py-1.5 border border-bah-border rounded-lg text-xs text-bah-muted hover:text-bah-heading">↻</button>
          {p?.kill_switch
            ? <button onClick={resume} className="px-3 py-1.5 bg-green-500/20 border border-green-500/40 rounded-lg text-xs text-green-400">Resume</button>
            : <button onClick={killSwitch} className="px-3 py-1.5 bg-red-500/10 border border-red-500/30 rounded-lg text-xs text-red-400">Kill Switch</button>}
        </div>
      </div>

      {/* ═══ PROGRESS BAR ═══ */}
      {(cycleRunning || cycleProgress > 0) && (
        <div className="h-1 bg-bah-border rounded-full overflow-hidden">
          <div className="h-full bg-gradient-to-r from-bah-cyan to-green-400 rounded-full transition-all duration-200 ease-out"
            style={{ width: `${cycleProgress}%` }} />
        </div>
      )}

      {/* Cycle error display */}
      {cycleError && (
        <div className="bg-red-500/10 border border-red-500/30 rounded-lg px-4 py-2 text-xs text-red-400 flex items-center justify-between">
          <span>Cycle error: {cycleError}</span>
          <button onClick={() => setCycleError("")} className="text-red-400 hover:text-red-300 ml-4">✕</button>
        </div>
      )}

      {/* ═══ DATA HEALTH + OPERATOR TRUST ═══ */}
      {health && (
        <div className="bg-bah-surface border border-bah-border rounded-xl p-2.5 flex flex-wrap items-center gap-3 text-[11px]">
          <div className="flex items-center gap-1.5">
            <span className={`w-2 h-2 rounded-full ${
              (health as any)?.data_source === "LIVE" ? "bg-green-400" : "bg-amber-400"
            }`} />
            <span className="text-bah-muted">Data:</span>
            <span className="text-bah-heading font-semibold">{(health as any)?.data_source || "?"}</span>
          </div>
          {(portfolio as any)?.regime && Object.entries((portfolio as any).regime).map(([asset, regime]: [string, any]) => (
            <div key={asset} className="flex items-center gap-1">
              <span className="text-bah-muted">{asset}:</span>
              <span className={`font-semibold ${String(regime)==="TREND"?"text-green-400":String(regime)==="CRASH"?"text-red-400":"text-amber-400"}`}>{String(regime)}</span>
            </div>
          ))}
          {lastCycle?.ended_at && (
            <div className="flex items-center gap-1">
              <span className="text-bah-muted">Last cycle:</span>
              <span className="text-bah-heading font-mono">{fmtTime(lastCycle.ended_at)}</span>
            </div>
          )}
        </div>
      )}

      {/* ═══ 4H COUNTDOWN TIMER ═══ */}
      {timing && (
        <div className="bg-bah-surface border border-bah-border rounded-xl p-2.5 flex flex-wrap items-center gap-2 sm:gap-4 text-xs">
          <div className="flex items-center gap-2">
            <span className="text-bah-muted">Next 4H bar:</span>
            <span className="font-mono font-bold text-bah-cyan text-sm">{fmtCountdown(countdown)}</span>
          </div>
          <div className="hidden sm:block h-4 w-px bg-bah-border" />
          <div className="flex flex-wrap items-center gap-2 sm:gap-4">
            {Object.entries(timing.assets || {}).map(([asset, t]: [string, any]) => (
              <div key={asset} className="flex items-center gap-2">
                <span className="font-semibold text-bah-heading">{asset}</span>
                <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${
                  (t.data_health || t.status) === "HEALTHY" ? "bg-green-500/15 text-green-400" :
                  (t.data_health || t.status) === "DEGRADED" ? "bg-amber-500/15 text-amber-400" :
                  (t.data_health || t.status) === "STALE" || t.status === "STALE" ? "bg-red-500/15 text-red-400" :
                  t.status === "NEW_BAR_READY" ? "bg-green-500/15 text-green-400" :
                  "bg-bah-border text-bah-muted"
                }`}>{t.data_health === "HEALTHY" ? (t.status === "NEW_BAR_READY" ? "NEW BAR" : "WAITING") : (t.data_health || t.status)}</span>
                <span className="text-[10px] text-bah-muted font-mono">bar: {t.last_processed_bar?.slice(11, 16) || t.last_closed_bar?.slice(11, 16) || "?"}</span>
              </div>
            ))}
          </div>
          <span className="text-[10px] text-bah-muted font-mono ml-auto">{timing.now_utc?.slice(11, 19)} UTC</span>
        </div>
      )}

      {/* ═══ CYCLE STATUS STRIP ═══ */}
      <div className="bg-bah-surface border border-bah-border rounded-xl p-3 flex flex-wrap items-center gap-3 sm:gap-6 text-xs font-mono">
        <div>
          <span className="text-bah-muted">Last cycle:</span>{" "}
          <span className="text-bah-heading">{fmtDateTime(lc?.ended_at)}</span>
        </div>
        <div>
          <span className="text-bah-muted">Duration:</span>{" "}
          <span className="text-bah-heading">{lc?.duration_ms ? fmtDur(lc.duration_ms) : "—"}</span>
        </div>
        <div>
          <span className="text-bah-muted">Status:</span>{" "}
          <span className={`font-semibold ${statusClr(lc?.status)}`}>{lc?.status || "IDLE"}</span>
        </div>
        <div>
          <span className="text-bah-muted">Signals:</span>{" "}
          <span className={lc?.signals_generated > 0 ? "text-bah-cyan font-semibold" : "text-bah-heading"}>{lc?.signals_generated ?? 0}</span>
        </div>
        <div>
          <span className="text-bah-muted">Orders:</span>{" "}
          <span className={lc?.orders_created > 0 ? "text-green-400 font-semibold" : "text-bah-heading"}>{lc?.orders_created ?? 0}</span>
        </div>
        <div className="ml-auto text-bah-muted">
          Success: {cStats.success || 0} / Skip: {cStats.skipped || 0} / Err: {cStats.errors || 0}
        </div>
      </div>

      {/* ═══ KEY METRICS ═══ */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2">
        {[
          { l: "Equity", v: `$${(p?.equity||100000).toLocaleString(undefined,{maximumFractionDigits:0})}`, c: "text-bah-heading" },
          { l: "P&L", v: `${pnl>=0?"+":""}$${Math.abs(pnl).toFixed(0)}`, c: pnl>=0?"text-green-400":"text-red-400" },
          { l: "Return", v: `${(p?.return_pct||0)>=0?"+":""}${(p?.return_pct||0).toFixed(2)}%`, c: (p?.return_pct||0)>=0?"text-green-400":"text-red-400" },
          { l: "Drawdown", v: `${dd.toFixed(1)}%`, c: dd>8?"text-red-400":dd>5?"text-amber-400":"text-green-400" },
          { l: "Open Risk", v: `${risk.toFixed(1)}%`, c: risk>5?"text-red-400":risk>4?"text-amber-400":"text-bah-heading" },
          { l: "Positions", v: `${p?.open_positions||0} / ${p?.total_trades||0}`, c: "text-bah-cyan" },
        ].map(m => (
          <div key={m.l} className="bg-bah-surface border border-bah-border rounded-xl p-2.5 text-center">
            <div className={`text-lg font-bold font-mono ${m.c}`}>{m.v}</div>
            <div className="text-[9px] text-bah-muted uppercase mt-0.5">{m.l}</div>
          </div>
        ))}
      </div>

      {/* ═══ REGIME CARDS (with data status) ═══ */}
      {p?.regime && Object.keys(p.regime).length > 0 && (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
          {Object.entries(p.regime).map(([asset, regime]: [string, any]) => {
            const assetData = health?.data?.[asset];
            const dataStatus = typeof assetData?.status === "string" ? assetData.status : String(assetData?.status || "—");
            const dataDetail = typeof assetData?.detail === "string" ? assetData.detail : (assetData?.detail ? JSON.stringify(assetData.detail) : "");
            return (
              <div key={asset} className={`rounded-xl border p-3 ${
                regime==="TREND"?"bg-green-500/5 border-green-500/20":regime==="CRASH"?"bg-red-500/5 border-red-500/20":"bg-amber-500/5 border-amber-500/20"}`}>
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-bold text-bah-heading">{asset}</span>
                    <span className={`text-xs font-semibold ${regime==="TREND"?"text-green-400":regime==="CRASH"?"text-red-400":"text-amber-400"}`}>
                      {regime==="TREND"?"📈":regime==="CRASH"?"🔻":"↔️"} {regime as string}
                    </span>
                  </div>
                  <span className={`text-[10px] font-mono px-1.5 py-0.5 rounded ${
                    dataStatus==="OK"?"text-green-400 bg-green-500/10":dataStatus==="STALE"?"text-amber-400 bg-amber-500/10":"text-bah-muted bg-bah-border/50"
                  }`}>{dataStatus === "OK" ? "LIVE" : dataStatus === "SYNTHETIC" ? "SYNTHETIC" : dataStatus}</span>
                </div>
                {dataDetail && (
                  <div className="text-[10px] text-bah-muted mt-1 font-mono truncate">{dataDetail}</div>
                )}
              </div>
            );
          })}
        </div>
      )}


      {/* ═══ TABS (desktop only) ═══ */}
      <div className="hidden lg:flex gap-1 border-b border-bah-border">
        {(["cycle","conditions","strategies","positions","trades","alerts","training"] as const).map(t => (
          <button key={t} onClick={() => setTab(t)} className={`px-4 py-2 text-xs font-medium border-b-2 transition-colors whitespace-nowrap ${
            tab===t?"border-bah-cyan text-bah-cyan":"border-transparent text-bah-muted hover:text-bah-heading"}`}>
            {t==="cycle"?"🔍 Cycle Inspector":t==="conditions"?"🎯 Strategy Conditions":t==="strategies"?"📊 Performance":t==="positions"?"📦 Positions":t==="trades"?"🔁 Trades":t==="training"?"🧪 Training":`⚠️ Alerts (${alerts.length - hiddenAlerts.length})`}
          </button>
        ))}
      </div>

      {/* ═══ CYCLE INSPECTOR ═══ */}
      {(tab === "cycle" || isMobile) && (
        <div className="space-y-3">
          {isMobile && <div className="text-[10px] font-semibold text-bah-muted uppercase tracking-widest pt-1">🔍 Cycle Inspector</div>}
          {lc?.assets && lc.assets.length > 0 ? (
            <div className="grid grid-cols-1 gap-3">
              {lc.assets.map((a: any, i: number) => (
                <div key={i} className="bg-bah-surface border border-bah-border rounded-xl overflow-hidden">
                  <div className="px-3 py-2.5 border-b border-bah-border">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="text-sm font-bold text-bah-heading">{a.asset}</span>
                      <span className={`text-xs font-semibold ${a.regime==="TREND"?"text-green-400":a.regime==="CRASH"?"text-red-400":"text-amber-400"}`}>
                        {a.regime} {a.regime_confidence ? `(${(a.regime_confidence*100).toFixed(0)}%)` : ""}
                      </span>
                      {a.new_bar && <span className="text-[10px] px-1.5 py-0.5 rounded bg-bah-cyan/15 text-bah-cyan border border-bah-cyan/30">NEW BAR</span>}
                      {a.bar_close > 0 && <span className="text-xs text-bah-muted font-mono">${a.bar_close.toLocaleString()}</span>}
                    </div>
                    <span className="text-[10px] text-bah-muted font-mono">{a.timestamp || ""}</span>
                  </div>
                  {a.strategies_evaluated?.length > 0 ? (
                    <div className="divide-y divide-bah-border/40">
                      {a.strategies_evaluated.map((s: any, j: number) => (
                        <div key={j} className="px-3 py-2.5">
                          <div className="flex items-center gap-2 flex-wrap">
                            <span className="text-xs font-medium text-bah-heading">{s.strategy}</span>
                            <span className={`text-[10px] font-bold px-2 py-0.5 rounded border ${statusBg(s.result === "EXECUTED" ? "SUCCESS" : s.result === "BLOCKED" ? "SKIPPED" : "")}`}>
                              <span className={resultClr(s.result)}>{s.result}</span>
                            </span>
                          </div>
                          <div className="text-[11px] text-bah-muted mt-1">{s.reason}</div>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="px-3 py-3 text-xs text-bah-muted">{a.summary || "No strategies evaluated"}</div>
                  )}
                </div>
              ))}
            </div>
          ) : (
            <div className="bg-bah-surface border border-bah-border rounded-xl p-6 text-center text-sm text-bah-muted">
              {lc?.status === "SKIPPED" ? `Cycle skipped: ${lc.skip_reason}` : "No cycle data yet — click ▶ Run Cycle"}
            </div>
          )}
          {/* Recent cycles — desktop only */}
          {!isMobile && cList.length > 0 && (
            <div className="bg-bah-surface border border-bah-border rounded-xl overflow-hidden">
              <div className="px-4 py-2.5 border-b border-bah-border"><span className="text-xs font-semibold text-bah-heading">Recent Cycles</span></div>
              <table className="w-full text-xs">
                <thead><tr className="text-left text-bah-muted border-b border-bah-border">
                  <th className="px-4 py-2">Time</th><th className="px-3 py-2">Status</th><th className="px-3 py-2 text-right">Duration</th>
                  <th className="px-3 py-2 text-right">Signals</th><th className="px-3 py-2 text-right">Orders</th><th className="px-3 py-2">Summary</th>
                </tr></thead>
                <tbody>{cList.slice(0, 15).map((c: any, i: number) => (
                  <tr key={i} className="border-b border-bah-border/30">
                    <td className="px-4 py-2 font-mono text-bah-heading">{fmtTime(c.ended_at || c.started_at)}</td>
                    <td className="px-3 py-2"><span className={`font-semibold ${statusClr(c.status)}`}>{c.status}</span></td>
                    <td className="px-3 py-2 text-right font-mono">{c.duration_ms ? fmtDur(c.duration_ms) : "—"}</td>
                    <td className="px-3 py-2 text-right">{c.signals_generated || 0}</td>
                    <td className="px-3 py-2 text-right">{c.orders_created || 0}</td>
                    <td className="px-3 py-2 text-bah-muted truncate max-w-[300px]">{c.skip_reason || c.error || c.assets?.map((a: any) => `${a.asset}:${a.regime || "?"}`).join(", ") || "—"}</td>
                  </tr>
                ))}</tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* ═══ STRATEGY CONDITIONS ═══ */}
      {(tab === "conditions" || isMobile) && (
        <div className="space-y-3">
          {isMobile && <div className="text-[10px] font-semibold text-bah-muted uppercase tracking-widest pt-2">🎯 Strategy Conditions</div>}
          {Object.keys(stratConds).length > 0 ? (
            Object.entries(stratConds).map(([asset, data]: [string, any]) => (
              <div key={asset} className="bg-bah-surface border border-bah-border rounded-xl overflow-hidden">
                <div className="px-3 py-2.5 border-b border-bah-border flex items-center gap-2 flex-wrap">
                  <span className="text-sm font-bold text-bah-heading">{asset}</span>
                  <span className={`text-xs font-semibold ${data.regime==="TREND"?"text-green-400":data.regime==="CRASH"?"text-red-400":"text-amber-400"}`}>{data.regime}</span>
                  {data.price > 0 && <span className="text-xs font-mono text-bah-muted">${data.price?.toLocaleString()}</span>}
                </div>
                <div className="divide-y divide-bah-border/40">
                  {(data.strategies || []).map((s: any, si: number) => (
                    <div key={si} className="px-3 py-3">
                      <div className="flex items-center gap-2 mb-1 flex-wrap">
                        <span className="text-xs font-semibold text-bah-heading">{s.strategy}</span>
                        <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${
                          s.result==="SIGNAL"?"bg-green-500/15 text-green-400 border border-green-500/30":
                          s.result==="BLOCKED"?"bg-amber-500/15 text-amber-400 border border-amber-500/30":
                          "bg-bah-border text-bah-muted border border-bah-border"}`}>{s.result}</span>
                      </div>
                      <div className="text-[11px] text-bah-muted mb-2">{s.reason}</div>
                      <div className="space-y-1">
                        {(s.conditions || []).map((c: any, ci: number) => (
                          <div key={ci} className="text-[11px]">
                            <span className={`font-bold ${c.passed?"text-green-400":"text-red-400"}`}>{c.passed?"✓":"✗"}</span>
                            {" "}<span className="text-bah-muted">{c.name}:</span>
                            {" "}<span className="font-mono text-bah-heading">{c.actual}</span>
                            {!c.passed && <span className="text-bah-muted"> → {c.target}</span>}
                            {c.distance && c.distance !== "N/A" && <span className={`font-mono text-[10px] ${c.passed?"text-green-400/70":"text-amber-400"}`}> ({c.distance})</span>}
                          </div>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            ))
          ) : <div className="bg-bah-surface border border-bah-border rounded-xl p-6 text-center text-sm text-bah-muted">No strategy data yet — click ▶ Run Cycle</div>}
        </div>
      )}

      {/* ═══ PERFORMANCE ═══ */}
      {(tab === "strategies" || isMobile) && (
        <div className="space-y-3">
          {isMobile && <div className="text-[10px] font-semibold text-bah-muted uppercase tracking-widest pt-2 pb-2">📊 Performance</div>}

          {/* Portfolio summary */}
          {performance?.portfolio && performance.has_data ? (
            <div className="bg-bah-surface border border-bah-border rounded-xl p-3 sm:p-4">
              <div className="text-xs font-semibold text-bah-heading mb-2">Portfolio Summary</div>
              <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-6 gap-3 text-[11px]">
                <div><span className="text-bah-muted">Closed Trades</span><div className="text-bah-heading font-bold text-sm">{performance.portfolio.total_trades}</div></div>
                <div><span className="text-bah-muted">Total PnL</span><div className={`font-bold text-sm font-mono ${performance.portfolio.pnl>=0?"text-green-400":"text-red-400"}`}>${performance.portfolio.pnl?.toFixed(0)}</div></div>
                <div><span className="text-bah-muted">Win Rate</span><div className="text-bah-heading font-bold text-sm">{performance.portfolio.win_rate?.toFixed(1)}%</div></div>
                <div><span className="text-bah-muted">Profit Factor</span><div className={`font-bold text-sm ${performance.portfolio.profit_factor>=1.5?"text-green-400":performance.portfolio.profit_factor<1?"text-red-400":"text-bah-heading"}`}>{performance.portfolio.profit_factor?.toFixed(2)}</div></div>
                <div><span className="text-bah-muted">Expectancy</span><div className={`font-mono font-bold text-sm ${performance.portfolio.expectancy>=0?"text-green-400":"text-red-400"}`}>${performance.portfolio.expectancy?.toFixed(0)}</div></div>
                <div><span className="text-bah-muted">Max Drawdown</span><div className="text-red-400 font-bold text-sm font-mono">${performance.portfolio.max_drawdown?.toFixed(0)}</div></div>
              </div>
            </div>
          ) : null}

          {/* Strategy table */}
          {performance?.strategies && Object.keys(performance.strategies).length > 0 ? (
            <div className="bg-bah-surface border border-bah-border rounded-xl overflow-hidden">
              <div className="px-3 sm:px-4 py-2.5 border-b border-bah-border"><span className="text-xs font-semibold text-bah-heading">Strategy Breakdown</span></div>
              <div className="hidden lg:block">
                <table className="w-full text-xs">
                  <thead><tr className="text-left text-bah-muted border-b border-bah-border">
                    <th className="px-4 py-2.5">Strategy</th><th className="px-3 py-2.5 text-right">PnL</th><th className="px-3 py-2.5 text-right">Trades</th>
                    <th className="px-3 py-2.5 text-right">WR</th><th className="px-3 py-2.5 text-right">PF</th><th className="px-3 py-2.5 text-right">Expect.</th><th className="px-3 py-2.5 text-right">Open</th>
                  </tr></thead>
                  <tbody>{Object.entries(performance.strategies).map(([n, s]: [string, any]) => (
                    <tr key={n} className="border-b border-bah-border/50">
                      <td className="px-4 py-2.5 font-medium text-bah-heading">{n}</td>
                      <td className={`px-3 py-2.5 text-right font-semibold font-mono ${(s.pnl||0)>=0?"text-green-400":"text-red-400"}`}>${(s.pnl||0).toFixed(0)}</td>
                      <td className="px-3 py-2.5 text-right">{s.total_trades || 0}</td>
                      <td className="px-3 py-2.5 text-right">{(s.win_rate||0).toFixed(0)}%</td>
                      <td className={`px-3 py-2.5 text-right ${(s.profit_factor||0)>=1.5?"text-green-400":(s.profit_factor||0)<1?"text-red-400":"text-bah-heading"}`}>{(s.profit_factor||0).toFixed(2)}</td>
                      <td className={`px-3 py-2.5 text-right font-mono ${(s.expectancy||0)>=0?"text-green-400":"text-red-400"}`}>${(s.expectancy||0).toFixed(0)}</td>
                      <td className="px-3 py-2.5 text-right">{(s.open_positions||0)>0?<span className="text-bah-cyan font-semibold">{s.open_positions}</span>:"—"}</td>
                    </tr>
                  ))}</tbody>
                </table>
              </div>
              <div className="lg:hidden space-y-2 p-2">
                {Object.entries(performance.strategies).map(([n, s]: [string, any]) => (
                  <div key={n} className="bg-bah-border/20 rounded-lg p-3">
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-xs font-semibold text-bah-heading">{n}</span>
                      <span className={`text-sm font-bold font-mono ${(s.pnl||0)>=0?"text-green-400":"text-red-400"}`}>${(s.pnl||0).toFixed(0)}</span>
                    </div>
                    <div className="grid grid-cols-4 gap-2 text-[10px]">
                      <div><span className="text-bah-muted">Trades</span><div className="font-semibold">{s.total_trades||0}</div></div>
                      <div><span className="text-bah-muted">WR</span><div className="font-semibold">{(s.win_rate||0).toFixed(0)}%</div></div>
                      <div><span className="text-bah-muted">PF</span><div className="font-semibold">{(s.profit_factor||0).toFixed(2)}</div></div>
                      <div><span className="text-bah-muted">Open</span><div className="font-semibold">{(s.open_positions||0)>0?s.open_positions:"—"}</div></div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ) : null}

          {/* Asset breakdown */}
          {performance?.assets && Object.keys(performance.assets).length > 0 ? (
            <div className="bg-bah-surface border border-bah-border rounded-xl overflow-hidden">
              <div className="px-3 sm:px-4 py-2.5 border-b border-bah-border"><span className="text-xs font-semibold text-bah-heading">Asset Breakdown</span></div>
              <table className="w-full text-xs">
                <thead><tr className="text-left text-bah-muted border-b border-bah-border">
                  <th className="px-4 py-2">Asset</th><th className="px-3 py-2 text-right">PnL</th><th className="px-3 py-2 text-right">Trades</th><th className="px-3 py-2 text-right">WR</th><th className="px-3 py-2 text-right">Open</th>
                </tr></thead>
                <tbody>{Object.entries(performance.assets).map(([n, a]: [string, any]) => (
                  <tr key={n} className="border-b border-bah-border/50">
                    <td className="px-4 py-2 font-medium text-bah-heading">{n}</td>
                    <td className={`px-3 py-2 text-right font-mono font-semibold ${(a.pnl||0)>=0?"text-green-400":"text-red-400"}`}>${(a.pnl||0).toFixed(0)}</td>
                    <td className="px-3 py-2 text-right">{a.total_trades||0}</td>
                    <td className="px-3 py-2 text-right">{(a.win_rate||0).toFixed(0)}%</td>
                    <td className="px-3 py-2 text-right">{(a.open_positions||0)>0?<span className="text-bah-cyan font-semibold">{a.open_positions}</span>:"—"}</td>
                  </tr>
                ))}</tbody>
              </table>
            </div>
          ) : null}

          {/* Empty state */}
          {!performance?.has_data && (
            <div className="bg-bah-surface border border-bah-border rounded-xl p-6 text-center">
              <div className="text-sm text-bah-muted">No closed trades yet</div>
              <div className="text-[11px] text-bah-muted mt-1">Engine is evaluating market conditions. Trades will appear when strategy conditions are met.</div>
              <div className="text-[11px] text-bah-muted mt-2">Use <span className="text-bah-cyan">▶ Test Trade</span> below to verify the full lifecycle.</div>
            </div>
          )}

          {/* Test Trade buttons */}
          <div className="bg-bah-surface border border-bah-border rounded-xl p-3 sm:p-4">
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs font-semibold text-bah-heading">🧪 Test Trade Mode</span>
              <span className="text-[10px] text-amber-400 bg-amber-500/10 border border-amber-500/20 px-2 py-0.5 rounded">PAPER ONLY</span>
            </div>
            <div className="text-[11px] text-bah-muted mb-3">Run a controlled test trade to verify the signal → order → position → close lifecycle.</div>
            <div className="flex gap-2 flex-wrap">
              <button disabled={testTradeLoading} onClick={async () => {
                setTestTradeResult(null);
                setTestTradeLoading(true);
                try {
                  const r = await fetch(`${apiBase()}/monitoring/test-trade/open`, {
                    method: "POST", headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
                  });
                  if (!r.ok) {
                    setTestTradeResult({ type: "error", error: `HTTP ${r.status}: ${await r.text().catch(() => "")}` });
                  } else {
                    const data = await r.json();
                    setTestTradeResult({ type: "open", ...data });
                    load();
                  }
                } catch (e: any) { setTestTradeResult({ type: "error", error: e.message }); }
                setTestTradeLoading(false);
              }} className="px-3 py-1.5 text-[11px] bg-green-500/15 text-green-400 border border-green-500/30 rounded-lg hover:bg-green-500/25 transition-colors disabled:opacity-50">
                {testTradeLoading ? "⟳ Opening..." : "▶ Open Test Trade (BTCUSD LONG)"}
              </button>
              <button disabled={testTradeLoading} onClick={async () => {
                setTestTradeResult(null);
                setTestTradeLoading(true);
                try {
                  const r = await fetch(`${apiBase()}/monitoring/test-trade/close`, {
                    method: "POST", headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
                  });
                  if (!r.ok) {
                    setTestTradeResult({ type: "error", error: `HTTP ${r.status}: ${await r.text().catch(() => "")}` });
                  } else {
                    const data = await r.json();
                    setTestTradeResult({ type: "close", ...data });
                    load();
                  }
                } catch (e: any) { setTestTradeResult({ type: "error", error: e.message }); }
                setTestTradeLoading(false);
              }} className="px-3 py-1.5 text-[11px] bg-red-500/15 text-red-400 border border-red-500/30 rounded-lg hover:bg-red-500/25 transition-colors disabled:opacity-50">
                {testTradeLoading ? "⟳ Closing..." : "■ Close Test Trade"}
              </button>
              <button disabled={testTradeLoading} onClick={async () => {
                setTestTradeLoading(true);
                try {
                  const r = await fetch(`${apiBase()}/monitoring/test-trade/status`, {
                    headers: token ? { Authorization: `Bearer ${token}` } : {},
                  });
                  if (!r.ok) {
                    setTestTradeResult({ type: "error", error: `HTTP ${r.status}: ${await r.text().catch(() => "")}` });
                  } else {
                    const data = await r.json();
                    setTestTradeResult({ type: "status", ...data });
                  }
                } catch (e: any) { setTestTradeResult({ type: "error", error: e.message }); }
                setTestTradeLoading(false);
              }} className="px-3 py-1.5 text-[11px] bg-bah-border/50 text-bah-muted border border-bah-border rounded-lg hover:bg-bah-border/80 transition-colors disabled:opacity-50">
                ℹ Test Status
              </button>
            </div>

            {/* Test Trade Result Card */}
            {testTradeResult && (
              <div className={`mt-3 rounded-lg border p-3 text-xs ${
                testTradeResult.status === "OPENED" ? "bg-green-500/5 border-green-500/20" :
                testTradeResult.status === "CLOSED" ? "bg-bah-cyan/5 border-bah-cyan/20" :
                testTradeResult.status === "REJECTED" || testTradeResult.status === "FAILED" || testTradeResult.type === "error" ? "bg-red-500/5 border-red-500/20" :
                "bg-bah-border/30 border-bah-border"
              }`}>
                <div className="flex items-center justify-between mb-2">
                  <span className="font-semibold text-bah-heading">
                    {testTradeResult.status === "OPENED" ? "✅ Test Trade Opened" :
                     testTradeResult.status === "CLOSED" ? "🔒 Test Trade Closed" :
                     testTradeResult.status === "REJECTED" ? "⚠️ Trade Rejected" :
                     testTradeResult.status === "NOT_FOUND" ? "ℹ️ No Test Position" :
                     testTradeResult.type === "status" ? "📊 Test Trade Status" :
                     testTradeResult.type === "error" ? "❌ Error" :
                     "ℹ️ Result"}
                  </span>
                  <button onClick={() => setTestTradeResult(null)} className="text-bah-muted hover:text-bah-heading">✕</button>
                </div>

                {/* OPENED */}
                {testTradeResult.status === "OPENED" && testTradeResult.position && (
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-[11px]">
                    <div><span className="text-bah-muted">Asset</span><div className="font-semibold text-bah-heading">{testTradeResult.position.asset}</div></div>
                    <div><span className="text-bah-muted">Direction</span><div className="font-semibold text-green-400">{testTradeResult.position.direction}</div></div>
                    <div><span className="text-bah-muted">Entry</span><div className="font-mono font-semibold text-bah-heading">${testTradeResult.position.entry_price?.toLocaleString()}</div></div>
                    <div><span className="text-bah-muted">Size</span><div className="font-mono text-bah-heading">{testTradeResult.position.size?.toFixed(6)}</div></div>
                    <div><span className="text-red-400">Stop Loss</span><div className="font-mono text-red-400">${testTradeResult.position.stop_loss?.toLocaleString()}</div></div>
                    <div><span className="text-green-400">Take Profit</span><div className="font-mono text-green-400">${testTradeResult.position.take_profit?.toLocaleString()}</div></div>
                    <div><span className="text-bah-muted">Strategy</span><div className="text-bah-heading">{testTradeResult.position.strategy}</div></div>
                    <div><span className="text-bah-muted">Order ID</span><div className="font-mono text-bah-muted text-[10px]">{testTradeResult.order_id}</div></div>
                  </div>
                )}

                {/* CLOSED */}
                {testTradeResult.status === "CLOSED" && testTradeResult.trade && (
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-[11px]">
                    <div><span className="text-bah-muted">Asset</span><div className="font-semibold text-bah-heading">{testTradeResult.trade.asset}</div></div>
                    <div><span className="text-bah-muted">PnL</span><div className={`font-bold font-mono text-sm ${testTradeResult.trade.pnl >= 0 ? "text-green-400" : "text-red-400"}`}>${testTradeResult.trade.pnl?.toFixed(2)}</div></div>
                    <div><span className="text-bah-muted">PnL %</span><div className={`font-semibold ${testTradeResult.trade.pnl_pct >= 0 ? "text-green-400" : "text-red-400"}`}>{testTradeResult.trade.pnl_pct?.toFixed(2)}%</div></div>
                    <div><span className="text-bah-muted">Exit Reason</span><div className="text-bah-heading">{testTradeResult.trade.exit_reason}</div></div>
                    <div><span className="text-bah-muted">Entry</span><div className="font-mono text-bah-heading">${testTradeResult.trade.entry_price?.toLocaleString()}</div></div>
                    <div><span className="text-bah-muted">Exit</span><div className="font-mono text-bah-heading">${testTradeResult.trade.exit_price?.toLocaleString()}</div></div>
                    <div><span className="text-bah-muted">Bars Held</span><div className="text-bah-heading">{testTradeResult.trade.bars_held}</div></div>
                    <div><span className="text-bah-muted">Direction</span><div className="text-bah-heading">{testTradeResult.trade.direction}</div></div>
                  </div>
                )}

                {/* STATUS */}
                {testTradeResult.type === "status" && (
                  <div className="text-[11px]">
                    <div className="flex gap-4 mb-2">
                      <span className="text-bah-muted">Open positions: <span className="text-bah-heading font-semibold">{testTradeResult.open_test_positions || 0}</span></span>
                      <span className="text-bah-muted">Closed trades: <span className="text-bah-heading font-semibold">{testTradeResult.closed_test_trades || 0}</span></span>
                    </div>
                    {testTradeResult.positions?.length > 0 && (
                      <div className="space-y-1">{testTradeResult.positions.map((p: any, i: number) => (
                        <div key={i} className="flex items-center gap-3 text-[10px] bg-bah-border/20 rounded px-2 py-1">
                          <span className="font-semibold text-bah-heading">{p.asset}</span>
                          <span className="font-mono">${p.entry_price?.toLocaleString()}</span>
                          <span className={p.unrealized_pnl >= 0 ? "text-green-400" : "text-red-400"}>${p.unrealized_pnl?.toFixed(2)}</span>
                        </div>
                      ))}</div>
                    )}
                  </div>
                )}

                {/* REJECTED/FAILED/ERROR */}
                {(testTradeResult.status === "REJECTED" || testTradeResult.status === "FAILED" || testTradeResult.type === "error") && (
                  <div className="text-[11px] text-red-400">{testTradeResult.reason || testTradeResult.error || "Unknown error"}</div>
                )}

                {/* NOT_FOUND */}
                {testTradeResult.status === "NOT_FOUND" && (
                  <div className="text-[11px] text-bah-muted">{testTradeResult.reason || "No open test position to close."}</div>
                )}
              </div>
            )}
          </div>
        </div>
      )}

      {/* ═══ POSITIONS ═══ */}
      {(tab === "positions" || isMobile) && (
        <div>
          {isMobile && <div className="text-[10px] font-semibold text-bah-muted uppercase tracking-widest pt-2 pb-2">📦 Positions</div>}
          {positions?.positions?.length > 0 ? (
            <>
              <div className="hidden lg:block bg-bah-surface border border-bah-border rounded-xl overflow-hidden">
                <table className="w-full text-xs">
                  <thead><tr className="text-left text-bah-muted border-b border-bah-border">
                    <th className="px-4 py-2.5">Asset</th><th className="px-3">Strategy</th><th className="px-3 text-right">Entry</th>
                    <th className="px-3 text-right">SL</th><th className="px-3 text-right">TP</th><th className="px-3 text-right">PnL</th><th className="px-3 text-right">Bars</th>
                  </tr></thead>
                  <tbody>{positions.positions.map((pos: any, i: number) => (
                    <tr key={i} className="border-b border-bah-border/50">
                      <td className="px-4 py-2.5 font-medium text-bah-heading">{pos.asset}</td>
                      <td className="px-3 text-bah-muted">{pos.strategy}</td>
                      <td className="px-3 text-right font-mono">${pos.entry_price.toLocaleString()}</td>
                      <td className="px-3 text-right text-red-400 font-mono">${pos.stop_loss.toLocaleString()}</td>
                      <td className="px-3 text-right text-green-400 font-mono">${pos.take_profit.toLocaleString()}</td>
                      <td className={`px-3 text-right font-semibold font-mono ${pos.unrealized_pnl>=0?"text-green-400":"text-red-400"}`}>${pos.unrealized_pnl.toFixed(0)}</td>
                      <td className="px-3 text-right text-bah-muted">{pos.bars_held}</td>
                    </tr>
                  ))}</tbody>
                </table>
              </div>
              <div className="lg:hidden space-y-2">
                {positions.positions.map((pos: any, i: number) => (
                  <div key={i} className="bg-bah-surface border border-bah-border rounded-xl p-3">
                    <div className="flex items-center justify-between mb-2">
                      <div><span className="text-sm font-bold text-bah-heading">{pos.asset}</span> <span className="text-[10px] text-bah-muted">{pos.strategy}</span></div>
                      <span className={`text-sm font-bold font-mono ${pos.unrealized_pnl>=0?"text-green-400":"text-red-400"}`}>${pos.unrealized_pnl.toFixed(0)}</span>
                    </div>
                    <div className="grid grid-cols-3 gap-2 text-[10px]">
                      <div><span className="text-bah-muted">Entry</span><div className="font-mono text-bah-heading">${pos.entry_price.toLocaleString()}</div></div>
                      <div><span className="text-red-400">SL</span><div className="font-mono text-red-400">${pos.stop_loss.toLocaleString()}</div></div>
                      <div><span className="text-green-400">TP</span><div className="font-mono text-green-400">${pos.take_profit.toLocaleString()}</div></div>
                    </div>
                  </div>
                ))}
              </div>
            </>
          ) : <div className="bg-bah-surface border border-bah-border rounded-xl p-4 text-center text-bah-muted text-xs">No open positions</div>}
        </div>
      )}

      {/* ═══ TRADES ═══ */}
      {(tab === "trades" || isMobile) && (
        <div>
          {isMobile && <div className="text-[10px] font-semibold text-bah-muted uppercase tracking-widest pt-2 pb-2">🔁 Trades</div>}
          {trades?.trades?.length > 0 ? (
            <>
              <div className="hidden lg:block bg-bah-surface border border-bah-border rounded-xl overflow-hidden">
                <table className="w-full text-xs">
                  <thead><tr className="text-left text-bah-muted border-b border-bah-border">
                    <th className="px-4 py-2.5">Asset</th><th className="px-3">Strategy</th><th className="px-3 text-right">Entry</th>
                    <th className="px-3 text-right">Exit</th><th className="px-3 text-right">PnL</th><th className="px-3">Reason</th>
                  </tr></thead>
                  <tbody>{trades.trades.slice(0, 30).map((t: any, i: number) => (
                    <tr key={i} className="border-b border-bah-border/50">
                      <td className="px-4 py-2.5 font-medium text-bah-heading">{t.asset}</td>
                      <td className="px-3 text-bah-muted">{t.strategy}</td>
                      <td className="px-3 text-right font-mono">${t.entry_price.toLocaleString()}</td>
                      <td className="px-3 text-right font-mono">${t.exit_price.toLocaleString()}</td>
                      <td className={`px-3 text-right font-semibold font-mono ${t.pnl>=0?"text-green-400":"text-red-400"}`}>{t.pnl>=0?"+":""}${t.pnl.toFixed(0)}</td>
                      <td className="px-3 text-bah-muted">{t.exit_reason}</td>
                    </tr>
                  ))}</tbody>
                </table>
              </div>
              <div className="lg:hidden space-y-2">
                {trades.trades.slice(0, 20).map((t: any, i: number) => (
                  <div key={i} className="bg-bah-surface border border-bah-border rounded-xl p-3 flex items-center justify-between">
                    <div>
                      <span className="text-xs font-bold text-bah-heading">{t.asset}</span>
                      <span className="text-[10px] text-bah-muted ml-1">{t.strategy}</span>
                      <div className="text-[10px] text-bah-muted font-mono mt-0.5">${t.entry_price.toLocaleString()} → ${t.exit_price.toLocaleString()} · {t.exit_reason}</div>
                    </div>
                    <span className={`text-sm font-bold font-mono ${t.pnl>=0?"text-green-400":"text-red-400"}`}>{t.pnl>=0?"+":""}${t.pnl.toFixed(0)}</span>
                  </div>
                ))}
              </div>
            </>
          ) : <div className="bg-bah-surface border border-bah-border rounded-xl p-4 text-center text-bah-muted text-xs">No trades yet</div>}
        </div>
      )}

      {/* ═══ ALERTS ═══ */}
      {(tab === "alerts" || isMobile) && (
        <div>
          {isMobile && <div className="text-[10px] font-semibold text-bah-muted uppercase tracking-widest pt-2 pb-2">⚠️ Alerts ({alerts.length - hiddenAlerts.length})</div>}
          <div className="bg-bah-surface border border-bah-border rounded-xl overflow-hidden">
            {alerts.length > hiddenAlerts.length ? (
              <>
                <div className="px-3 py-2 border-b border-bah-border flex items-center justify-between">
                  <span className="text-[10px] text-bah-muted">{alerts.length - hiddenAlerts.length} alert{alerts.length - hiddenAlerts.length !== 1 ? "s" : ""}</span>
                  <button onClick={() => setHiddenAlerts(alerts.map((_, idx) => idx))} className="text-[10px] text-bah-muted hover:text-bah-heading transition-colors px-2 py-1 rounded hover:bg-white/[0.03]">Archive All</button>
                </div>
                <div className="divide-y divide-bah-border/50">{alerts.slice(0, 30).map((a: any, i: number) => {
                if (hiddenAlerts.includes(i)) return null;
                const t = String(a.title || "").toLowerCase();
                let advice = "";
                let fix = "";
                let icon = "ℹ️";
                let advCls = "bg-bah-cyan/5 border-bah-cyan/20";
                if (t.includes("stale data")) { advice = "Safe to ignore. System using cached prices."; fix = "Set TWELVE_DATA_KEY in Railway to get live prices."; icon = "💤"; advCls = "bg-bah-border/30 border-bah-border"; }
                else if (t.includes("drawdown exceeded")) { advice = "Review positions immediately."; fix = "Consider closing losers or activating kill switch."; icon = "⚡"; advCls = "bg-red-500/5 border-red-500/20"; }
                else if (t.includes("drawdown elevated")) { advice = "Monitor closely. Not critical yet."; fix = "Check open positions."; icon = "👁"; advCls = "bg-amber-500/5 border-amber-500/20"; }
                else if (t.includes("risk exceeded")) { advice = "Total risk exceeds 5%."; fix = "Reduce positions."; icon = "⚡"; advCls = "bg-red-500/5 border-red-500/20"; }
                else if (t.includes("kill switch")) { advice = "Trading halted."; fix = "Resume via Dashboard when ready."; icon = "⚡"; advCls = "bg-red-500/5 border-red-500/20"; }
                else if (t.includes("trade opened")) { advice = "System managing SL/TP automatically."; icon = "ℹ️"; }
                else if (t.includes("trade closed")) { advice = "Review P&L. No action needed."; icon = "ℹ️"; }
                else if (t.includes("regime")) { advice = "Strategies adapt automatically."; icon = "ℹ️"; }
                else if (t.includes("data error")) { advice = "Data feed error. Will retry."; fix = "Check Twelve Data API."; icon = "👁"; advCls = "bg-amber-500/5 border-amber-500/20"; }
                else if (a.level === "CRITICAL") { advice = "Requires immediate attention."; icon = "⚡"; advCls = "bg-red-500/5 border-red-500/20"; }
                else if (a.level === "WARNING") { advice = "Monitor this situation."; icon = "👁"; advCls = "bg-amber-500/5 border-amber-500/20"; }
                else { advice = "Informational — no action needed."; }
                return (
                <div key={i} className={`px-3 py-3 ${a.level==="CRITICAL"?"bg-red-500/5":a.level==="WARNING"?"bg-amber-500/5":""}`}>
                  <div className="flex items-start gap-2">
                    <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded shrink-0 ${a.level==="CRITICAL"?"bg-red-500/20 text-red-400":a.level==="WARNING"?"bg-amber-500/20 text-amber-400":"bg-bah-border text-bah-muted"}`}>{String(a.level)}</span>
                    <div className="flex-1 min-w-0">
                      <div className="text-xs font-medium text-bah-heading">{String(a.title)}</div>
                      <div className="text-[11px] text-bah-muted mt-0.5 break-words">{String(a.message)}</div>
                      <div className={`mt-2 text-[11px] px-2.5 py-2 rounded-lg border ${advCls}`}>
                        <div className="text-bah-heading font-medium">{icon} {advice}</div>
                        {fix && <div className="text-bah-muted mt-1">{"→ "}{fix}</div>}
                      </div>
                    </div>
                    <div className="flex flex-col gap-1 shrink-0">
                      {a.level === "CRITICAL" && a.key && (
                        <button onClick={async () => {
                          try {
                            await fetch(`${apiBase()}/monitoring/alerts/acknowledge?key=${encodeURIComponent(a.key)}`, {
                              method: "POST", headers: { "Authorization": `Bearer ${localStorage.getItem("token")}` },
                            });
                            setAlerts(prev => prev.filter(al => al.key !== a.key));
                          } catch {}
                        }} className="text-[10px] font-medium text-red-400 hover:text-red-300 px-2 py-1 rounded border border-red-500/30 hover:bg-red-500/15 transition-colors" title="Acknowledge this alert">
                          ACK
                        </button>
                      )}
                      <button onClick={() => setHiddenAlerts(h => [...h, i])} className="text-[10px] text-bah-muted hover:text-bah-heading shrink-0 px-1.5 py-0.5 rounded hover:bg-white/[0.05]" title="Hide">✕</button>
                    </div>
                  </div>
                  <div className="text-[10px] text-bah-muted font-mono mt-1 text-right">{fmtTime(a.timestamp)}</div>
                </div>
                );
              })}</div>
              </>
            ) : (
              <div className="p-4 text-center text-bah-muted text-xs">
                {hiddenAlerts.length > 0 ? (
                  <><span>All alerts archived</span>{" "}<button onClick={() => setHiddenAlerts([])} className="text-bah-cyan hover:underline">Show all</button></>
                ) : "No alerts"}
              </div>
            )}
          </div>
        </div>
      )}

      {/* ═══ TRAINING UNIVERSE ═══ */}
      {(tab === "training" || isMobile) && (
        <div className="bg-bah-surface border border-bah-border rounded-xl overflow-hidden">
          {isMobile && <div className="text-[10px] font-semibold text-bah-muted uppercase tracking-widest pt-2 pb-2 px-3">🧪 Training Universe</div>}
          <TrainingPanel token={token} apiBase={apiBase} />
        </div>
      )}
    </div>
  );
}

function TrainingPanel({ token, apiBase }: { token: string | null; apiBase: () => string }) {
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const load = async () => {
      try {
        const r = await fetch(`${apiBase()}/monitoring/training`, {
          headers: token ? { Authorization: `Bearer ${token}` } : {},
        });
        if (r.ok) setData(await r.json());
      } catch {}
      setLoading(false);
    };
    load();
    const iv = setInterval(load, 30000);
    return () => clearInterval(iv);
  }, []);

  if (loading) return <div className="p-6 text-center text-bah-muted text-sm">Loading training data...</div>;
  if (!data) return <div className="p-6 text-center text-bah-muted text-sm">Training module not active yet. Deploy and wait for the first 10-min cycle.</div>;

  const d = data;
  return (
    <div className="p-4 space-y-4">
      {/* Header stats */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="px-2 py-0.5 text-[10px] font-bold rounded bg-purple-500/15 text-purple-400 border border-purple-500/30">PAPER ONLY</span>
          <span className="text-xs text-bah-muted">{d.universe_size || 0} assets in training universe</span>
        </div>
        <div className="flex items-center gap-2">
          {d.last_cycle && <span className="text-[10px] text-bah-muted font-mono">Last cycle: {new Date(d.last_cycle).toLocaleTimeString("en-GB",{hour12:false})}</span>}
          <a href="/training-operations" className="px-2.5 py-1 text-[10px] font-semibold text-bah-cyan border border-bah-cyan/30 rounded hover:bg-bah-cyan/10 transition-colors">Full Dashboard →</a>
        </div>
      </div>

      {/* KPI cards */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <div className="bg-bah-bg border border-bah-border rounded-lg p-3 text-center">
          <div className="text-lg font-bold text-bah-heading">{d.open_positions || 0}</div>
          <div className="text-[10px] text-bah-muted uppercase">Open Positions</div>
        </div>
        <div className="bg-bah-bg border border-bah-border rounded-lg p-3 text-center">
          <div className="text-lg font-bold text-bah-heading">{d.total_closed_trades || 0}</div>
          <div className="text-[10px] text-bah-muted uppercase">Closed Trades</div>
        </div>
        <div className="bg-bah-bg border border-bah-border rounded-lg p-3 text-center">
          <div className={`text-lg font-bold ${(d.total_pnl||0) >= 0 ? "text-green-400" : "text-red-400"}`}>
            ${(d.total_pnl||0).toLocaleString(undefined,{minimumFractionDigits:0})}
          </div>
          <div className="text-[10px] text-bah-muted uppercase">Total PnL (Paper)</div>
        </div>
        <div className="bg-bah-bg border border-bah-border rounded-lg p-3 text-center">
          <div className="text-lg font-bold text-bah-heading">{((d.win_rate||0)*100).toFixed(1)}%</div>
          <div className="text-[10px] text-bah-muted uppercase">Win Rate</div>
        </div>
      </div>

      {/* Asset class breakdown */}
      {d.class_stats && Object.keys(d.class_stats).length > 0 && (
        <div>
          <h3 className="text-xs font-semibold text-bah-heading mb-2">By Asset Class</h3>
          <div className="grid grid-cols-2 sm:grid-cols-5 gap-2">
            {Object.entries(d.class_stats).map(([cls, s]: [string, any]) => (
              <div key={cls} className="bg-bah-bg border border-bah-border rounded-lg p-2.5">
                <div className="text-[10px] text-bah-muted uppercase mb-1">{cls}</div>
                <div className="text-xs text-bah-heading font-semibold">{s.trades} trades</div>
                <div className={`text-[10px] ${s.total_pnl >= 0 ? "text-green-400" : "text-red-400"}`}>
                  ${s.total_pnl?.toFixed(0)} · {((s.win_rate||0)*100).toFixed(0)}% WR
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Strategy breakdown */}
      {d.strategy_stats && Object.keys(d.strategy_stats).length > 0 && (
        <div>
          <h3 className="text-xs font-semibold text-bah-heading mb-2">By Strategy</h3>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead><tr className="border-b border-bah-border text-left text-[10px] text-bah-muted uppercase">
                <th className="py-2 pr-3">Strategy</th><th className="py-2 pr-3">Trades</th><th className="py-2 pr-3">Win Rate</th><th className="py-2 pr-3">PnL</th>
              </tr></thead>
              <tbody>
                {Object.entries(d.strategy_stats).map(([name, s]: [string, any]) => (
                  <tr key={name} className="border-b border-bah-border/30">
                    <td className="py-2 pr-3 text-bah-heading font-medium">{name}</td>
                    <td className="py-2 pr-3 text-bah-muted">{s.trades}</td>
                    <td className="py-2 pr-3">{((s.win_rate||0)*100).toFixed(1)}%</td>
                    <td className={`py-2 pr-3 ${s.total_pnl >= 0 ? "text-green-400" : "text-red-400"}`}>${s.total_pnl?.toFixed(0)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Recent trades */}
      {d.recent_trades && d.recent_trades.length > 0 && (
        <div>
          <h3 className="text-xs font-semibold text-bah-heading mb-2">Recent Closed Trades</h3>
          <div className="overflow-x-auto">
            <table className="w-full text-[11px]">
              <thead><tr className="border-b border-bah-border text-left text-[10px] text-bah-muted uppercase">
                <th className="py-1.5 pr-2">Asset</th><th className="py-1.5 pr-2">Strategy</th><th className="py-1.5 pr-2">Dir</th>
                <th className="py-1.5 pr-2">PnL</th><th className="py-1.5 pr-2">Exit</th><th className="py-1.5 pr-2">Bars</th>
              </tr></thead>
              <tbody>
                {d.recent_trades.slice(0, 10).map((t: any, i: number) => (
                  <tr key={i} className="border-b border-bah-border/20">
                    <td className="py-1.5 pr-2 text-bah-heading">{t.asset}</td>
                    <td className="py-1.5 pr-2 text-bah-muted">{t.strategy}</td>
                    <td className="py-1.5 pr-2">{t.direction}</td>
                    <td className={`py-1.5 pr-2 font-medium ${t.pnl >= 0 ? "text-green-400" : "text-red-400"}`}>${t.pnl?.toFixed(2)}</td>
                    <td className="py-1.5 pr-2 text-bah-muted">{t.exit_reason}</td>
                    <td className="py-1.5 pr-2 text-bah-muted">{t.bars_held}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {d.total_closed_trades === 0 && (
        <div className="text-center py-8 text-bah-muted text-sm">
          <p>No training trades yet.</p>
          <p className="text-xs mt-1">The training cycle runs every 10 minutes across {d.universe_size || 50} assets. Trades will appear after the first 4H bar boundary.</p>
        </div>
      )}
    </div>
  );
}
