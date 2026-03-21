"use client";
import { useState, useEffect, useCallback, useRef } from "react";
import { apiBase } from "@/lib/utils";

export default function DailyOperations() {
  const [portfolio, setPortfolio] = useState<any>(null);
  const [strategies, setStrategies] = useState<any>(null);
  const [positions, setPositions] = useState<any>(null);
  const [trades, setTrades] = useState<any>(null);
  
  const [alerts, setAlerts] = useState<any[]>([]);
  const [health, setHealth] = useState<any>(null);
  const [lastCycle, setLastCycle] = useState<any>(null);
  const [cycleHistory, setCycleHistory] = useState<any>(null);
  const [timing, setTiming] = useState<any>(null);
  const [stratConds, setStratConds] = useState<any>({});
  const [countdown, setCountdown] = useState(0);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState<"cycle" | "conditions" | "strategies" | "positions" | "trades" | "alerts">("cycle");
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [secondsAgo, setSecondsAgo] = useState(0);

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
  const critAlerts = alerts.filter(a => a.level === "CRITICAL").length;

  // Format helpers
  const fmtTime = (iso: string) => { if (!iso) return "—"; try { const d = new Date(iso); return d.toLocaleTimeString("en-GB", { hour12: false }); } catch { return iso; } };
  const fmtDateTime = (iso: string) => { if (!iso) return "—"; try { const d = new Date(iso); return d.toLocaleString("en-GB", { hour12: false, month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit" }); } catch { return iso; } };
  const fmtDur = (ms: number) => ms < 1000 ? `${ms}ms` : `${(ms/1000).toFixed(1)}s`;
  const fmtCountdown = (secs: number) => { const h = Math.floor(secs/3600); const m = Math.floor((secs%3600)/60); const s = secs%60; return `${h.toString().padStart(2,"0")}:${m.toString().padStart(2,"0")}:${s.toString().padStart(2,"0")}`; };
  const statusClr = (s: string) => s === "SUCCESS" ? "text-green-400" : s === "ERROR" ? "text-red-400" : s === "SKIPPED" ? "text-amber-400" : "text-bah-cyan";
  const statusBg = (s: string) => s === "SUCCESS" ? "bg-green-500/15 border-green-500/30" : s === "ERROR" ? "bg-red-500/15 border-red-500/30" : s === "SKIPPED" ? "bg-amber-500/15 border-amber-500/30" : "bg-bah-cyan/15 border-bah-cyan/30";
  const resultClr = (r: string) => r === "EXECUTED" ? "text-green-400" : r === "BLOCKED" ? "text-amber-400" : r === "NO_SIGNAL" ? "text-bah-muted" : r === "SIGNAL" ? "text-bah-cyan" : "text-bah-muted";

  return (
    <div className="p-4 max-w-[1440px] space-y-3">
      {/* ═══ HEADER ═══ */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <h1 className="text-lg font-bold text-bah-heading">Daily Operations Monitor</h1>
          <span className={`px-2 py-0.5 text-[10px] rounded-full font-semibold border ${p?.kill_switch ? "bg-red-500/20 text-red-400 border-red-500/30" : "bg-green-500/20 text-green-400 border-green-500/30"}`}>
            {p?.kill_switch ? "HALTED" : "LIVE"}
          </span>
          {health?.data_source && <span className={`px-2 py-0.5 text-[10px] rounded-full font-semibold border ${health.data_source === "LIVE" ? "bg-green-500/20 text-green-400 border-green-500/30" : "bg-amber-500/20 text-amber-400 border-amber-500/30"}`}>{health.data_source}</span>}
          {health?.engine && <span className="px-2 py-0.5 text-[10px] rounded-full text-bah-muted border border-bah-border">{health.engine}</span>}
          {critAlerts > 0 && <span className="px-2 py-0.5 text-[10px] rounded-full bg-red-500/20 text-red-400 border border-red-500/30 animate-pulse">{critAlerts} CRITICAL</span>}
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

      {/* ═══ 4H COUNTDOWN TIMER ═══ */}
      {timing && (
        <div className="bg-bah-surface border border-bah-border rounded-xl p-2.5 flex items-center gap-4 text-xs">
          <div className="flex items-center gap-2">
            <span className="text-bah-muted">Next 4H bar:</span>
            <span className="font-mono font-bold text-bah-cyan text-sm">{fmtCountdown(countdown)}</span>
          </div>
          <div className="h-4 w-px bg-bah-border" />
          <div className="flex-1 flex items-center gap-4">
            {Object.entries(timing.assets || {}).map(([asset, t]: [string, any]) => (
              <div key={asset} className="flex items-center gap-2">
                <span className="font-semibold text-bah-heading">{asset}</span>
                <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${
                  t.status === "NEW_BAR_READY" ? "bg-green-500/15 text-green-400" :
                  t.status === "STALE" ? "bg-red-500/15 text-red-400" :
                  "bg-bah-border text-bah-muted"
                }`}>{t.status === "WAITING_FOR_NEW_BAR" ? "WAITING" : t.status}</span>
                <span className="text-[10px] text-bah-muted font-mono">bar: {t.last_closed_bar?.slice(11, 16) || "?"}</span>
              </div>
            ))}
          </div>
          <span className="text-[10px] text-bah-muted font-mono">{timing.now_utc?.slice(11, 19)} UTC</span>
        </div>
      )}

      {/* ═══ CYCLE STATUS STRIP ═══ */}
      <div className="bg-bah-surface border border-bah-border rounded-xl p-3 flex items-center gap-6 text-xs font-mono">
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
      <div className="grid grid-cols-6 gap-2">
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
        <div className="grid grid-cols-2 gap-2">
          {Object.entries(p.regime).map(([asset, regime]: [string, any]) => {
            const assetData = health?.data?.[asset];
            const dataStatus = assetData?.status || "—";
            const dataDetail = assetData?.detail || "";
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

      {/* ═══ TABS ═══ */}
      <div className="flex gap-1 border-b border-bah-border">
        {(["cycle","conditions","strategies","positions","trades","alerts"] as const).map(t => (
          <button key={t} onClick={() => setTab(t)} className={`px-4 py-2 text-xs font-medium border-b-2 transition-colors ${
            tab===t?"border-bah-cyan text-bah-cyan":"border-transparent text-bah-muted hover:text-bah-heading"}`}>
            {t==="cycle"?"🔍 Cycle Inspector":t==="conditions"?"🎯 Strategy Conditions":t==="strategies"?"📊 Performance":t==="positions"?"📦 Positions":t==="trades"?"🔁 Trades":`⚠️ Alerts (${alerts.length})`}
          </button>
        ))}
      </div>

      {/* ═══ CYCLE INSPECTOR TAB ═══ */}
      {tab === "cycle" && (
        <div className="space-y-3">
          {/* Last cycle asset decisions */}
          {lc?.assets && lc.assets.length > 0 ? (
            <div className="grid grid-cols-1 gap-3">
              {lc.assets.map((a: any, i: number) => (
                <div key={i} className="bg-bah-surface border border-bah-border rounded-xl overflow-hidden">
                  <div className="px-4 py-3 border-b border-bah-border flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <span className="text-sm font-bold text-bah-heading">{a.asset}</span>
                      <span className={`text-xs font-semibold ${a.regime==="TREND"?"text-green-400":a.regime==="CRASH"?"text-red-400":"text-amber-400"}`}>
                        {a.regime} {a.regime_confidence ? `(${(a.regime_confidence*100).toFixed(0)}%)` : ""}
                      </span>
                      {a.new_bar && <span className="text-[10px] px-1.5 py-0.5 rounded bg-bah-cyan/15 text-bah-cyan border border-bah-cyan/30">NEW BAR</span>}
                      {a.bar_close > 0 && <span className="text-xs text-bah-muted font-mono">${a.bar_close.toLocaleString()}</span>}
                    </div>
                    <span className="text-[10px] text-bah-muted font-mono">{a.timestamp || ""}</span>
                  </div>

                  {a.strategies_evaluated && a.strategies_evaluated.length > 0 ? (
                    <div className="divide-y divide-bah-border/40">
                      {a.strategies_evaluated.map((s: any, j: number) => (
                        <div key={j} className="px-4 py-2.5 flex items-center gap-3">
                          <span className="text-xs font-medium text-bah-heading w-28">{s.strategy}</span>
                          <span className={`text-[10px] font-bold px-2 py-0.5 rounded border ${statusBg(s.result === "EXECUTED" ? "SUCCESS" : s.result === "BLOCKED" ? "SKIPPED" : s.result === "NO_SIGNAL" ? "" : "")}`}>
                            <span className={resultClr(s.result)}>{s.result}</span>
                          </span>
                          <span className="text-[11px] text-bah-muted flex-1">{s.reason}</span>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="px-4 py-3 text-xs text-bah-muted">{a.summary || "No strategies evaluated"}</div>
                  )}
                </div>
              ))}
            </div>
          ) : (
            <div className="bg-bah-surface border border-bah-border rounded-xl p-6 text-center text-sm text-bah-muted">
              {lc?.status === "SKIPPED" ? `Cycle skipped: ${lc.skip_reason}` : "No cycle data yet — click ▶ Run Cycle"}
            </div>
          )}

          {/* Recent cycle log */}
          {cList.length > 0 && (
            <div className="bg-bah-surface border border-bah-border rounded-xl overflow-hidden">
              <div className="px-4 py-2.5 border-b border-bah-border">
                <span className="text-xs font-semibold text-bah-heading">Recent Cycles</span>
              </div>
              <table className="w-full text-xs">
                <thead><tr className="text-left text-bah-muted border-b border-bah-border">
                  <th className="px-4 py-2">Time</th><th className="px-3 py-2">Status</th>
                  <th className="px-3 py-2 text-right">Duration</th><th className="px-3 py-2 text-right">Signals</th>
                  <th className="px-3 py-2 text-right">Orders</th><th className="px-3 py-2">Summary</th>
                </tr></thead>
                <tbody>
                  {cList.slice(0, 15).map((c: any, i: number) => (
                    <tr key={i} className="border-b border-bah-border/30">
                      <td className="px-4 py-2 font-mono text-bah-heading">{fmtTime(c.ended_at || c.started_at)}</td>
                      <td className="px-3 py-2"><span className={`font-semibold ${statusClr(c.status)}`}>{c.status}</span></td>
                      <td className="px-3 py-2 text-right font-mono">{c.duration_ms ? fmtDur(c.duration_ms) : "—"}</td>
                      <td className="px-3 py-2 text-right">{c.signals_generated || 0}</td>
                      <td className="px-3 py-2 text-right">{c.orders_created || 0}</td>
                      <td className="px-3 py-2 text-bah-muted truncate max-w-[300px]">
                        {c.skip_reason || c.error || c.assets?.map((a: any) => `${a.asset}:${a.regime || "?"}`).join(", ") || "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* ═══ STRATEGY CONDITIONS TAB ═══ */}
      {tab === "conditions" && (
        <div className="space-y-3">
          {Object.keys(stratConds).length > 0 ? (
            Object.entries(stratConds).map(([asset, data]: [string, any]) => (
              <div key={asset} className="bg-bah-surface border border-bah-border rounded-xl overflow-hidden">
                <div className="px-4 py-3 border-b border-bah-border flex items-center gap-3">
                  <span className="text-sm font-bold text-bah-heading">{asset}</span>
                  <span className={`text-xs font-semibold ${data.regime==="TREND"?"text-green-400":data.regime==="CRASH"?"text-red-400":"text-amber-400"}`}>
                    {data.regime}
                  </span>
                  {data.price > 0 && <span className="text-xs font-mono text-bah-muted">${data.price?.toLocaleString()}</span>}
                </div>
                <div className="divide-y divide-bah-border/40">
                  {(data.strategies || []).map((s: any, si: number) => (
                    <div key={si} className="px-4 py-3">
                      <div className="flex items-center gap-2 mb-2">
                        <span className="text-xs font-semibold text-bah-heading">{s.strategy}</span>
                        <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${
                          s.result==="SIGNAL"?"bg-green-500/15 text-green-400 border border-green-500/30":
                          s.result==="BLOCKED"?"bg-amber-500/15 text-amber-400 border border-amber-500/30":
                          "bg-bah-border text-bah-muted border border-bah-border"
                        }`}>{s.result}</span>
                        <span className="text-[11px] text-bah-muted">{s.reason}</span>
                      </div>
                      <div className="space-y-1.5">
                        {(s.conditions || []).map((c: any, ci: number) => (
                          <div key={ci} className="flex items-center gap-2 text-[11px]">
                            <span className={`w-4 text-center font-bold ${c.passed ? "text-green-400" : "text-red-400"}`}>
                              {c.passed ? "✓" : "✗"}
                            </span>
                            <span className="text-bah-muted w-44 shrink-0">{c.name}</span>
                            <span className="font-mono text-bah-heading">{c.actual}</span>
                            {!c.passed && <span className="text-bah-muted">→ need {c.target}</span>}
                            {c.distance && c.distance !== "N/A" && (
                              <span className={`font-mono text-[10px] ${c.passed ? "text-green-400/70" : "text-amber-400"}`}>({c.distance})</span>
                            )}
                          </div>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            ))
          ) : (
            <div className="bg-bah-surface border border-bah-border rounded-xl p-8 text-center text-sm text-bah-muted">
              No strategy condition data yet — click ▶ Run Cycle to evaluate
            </div>
          )}
        </div>
      )}

      {/* ═══ STRATEGIES TAB ═══ */}
      {tab === "strategies" && strategies && (
        <div className="bg-bah-surface border border-bah-border rounded-xl overflow-hidden">
          <table className="w-full text-xs">
            <thead><tr className="text-left text-bah-muted border-b border-bah-border">
              <th className="px-4 py-2.5">Strategy</th><th className="px-3 py-2.5 text-right">PnL</th>
              <th className="px-3 py-2.5 text-right">Trades</th><th className="px-3 py-2.5 text-right">WR</th>
              <th className="px-3 py-2.5 text-right">WR(20)</th><th className="px-3 py-2.5 text-right">PF</th>
              <th className="px-3 py-2.5 text-right">Expect.</th><th className="px-3 py-2.5 text-right">Open</th>
            </tr></thead>
            <tbody>
              {Object.entries(strategies).filter(([,v]: any) => v.trades > 0 || v.open_positions > 0).map(([n, s]: [string, any]) => (
                <tr key={n} className="border-b border-bah-border/50 hover:bg-bah-border/10">
                  <td className="px-4 py-2.5 font-medium text-bah-heading">{n}</td>
                  <td className={`px-3 py-2.5 text-right font-semibold font-mono ${s.pnl>=0?"text-green-400":"text-red-400"}`}>${s.pnl.toFixed(0)}</td>
                  <td className="px-3 py-2.5 text-right">{s.trades}</td>
                  <td className="px-3 py-2.5 text-right">{s.win_rate.toFixed(0)}%</td>
                  <td className={`px-3 py-2.5 text-right font-medium ${s.rolling_wr>=50?"text-green-400":s.rolling_wr<35?"text-red-400":"text-amber-400"}`}>{s.rolling_wr.toFixed(0)}%</td>
                  <td className={`px-3 py-2.5 text-right ${s.profit_factor>=1.5?"text-green-400":s.profit_factor<1?"text-red-400":"text-bah-heading"}`}>{s.profit_factor.toFixed(2)}</td>
                  <td className={`px-3 py-2.5 text-right font-mono ${s.expectancy>=0?"text-green-400":"text-red-400"}`}>${s.expectancy.toFixed(0)}</td>
                  <td className="px-3 py-2.5 text-right">{s.open_positions>0?<span className="text-bah-cyan font-semibold">{s.open_positions}</span>:<span className="text-bah-muted">—</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* ═══ POSITIONS TAB ═══ */}
      {tab === "positions" && (
        <div className="bg-bah-surface border border-bah-border rounded-xl overflow-hidden">
          {positions?.positions?.length > 0 ? (
            <table className="w-full text-xs">
              <thead><tr className="text-left text-bah-muted border-b border-bah-border">
                <th className="px-4 py-2.5">Asset</th><th className="px-3">Strategy</th><th className="px-3 text-right">Entry</th>
                <th className="px-3 text-right">Current</th><th className="px-3 text-right">SL</th><th className="px-3 text-right">TP</th>
                <th className="px-3 text-right">PnL</th><th className="px-3 text-right">Risk%</th><th className="px-3 text-right">Bars</th>
              </tr></thead>
              <tbody>{positions.positions.map((pos: any, i: number) => (
                <tr key={i} className="border-b border-bah-border/50">
                  <td className="px-4 py-2.5 font-medium text-bah-heading">{pos.asset}</td>
                  <td className="px-3 text-bah-muted">{pos.strategy}</td>
                  <td className="px-3 text-right font-mono">${pos.entry_price.toLocaleString()}</td>
                  <td className="px-3 text-right font-mono">${pos.current_price.toLocaleString()}</td>
                  <td className="px-3 text-right text-red-400 font-mono">${pos.stop_loss.toLocaleString()}</td>
                  <td className="px-3 text-right text-green-400 font-mono">${pos.take_profit.toLocaleString()}</td>
                  <td className={`px-3 text-right font-semibold font-mono ${pos.unrealized_pnl>=0?"text-green-400":"text-red-400"}`}>${pos.unrealized_pnl.toFixed(0)}</td>
                  <td className={`px-3 text-right ${pos.risk_pct>3?"text-red-400":"text-bah-heading"}`}>{pos.risk_pct.toFixed(1)}%</td>
                  <td className="px-3 text-right text-bah-muted">{pos.bars_held}</td>
                </tr>
              ))}</tbody>
            </table>
          ) : <div className="p-6 text-center text-bah-muted text-sm">No open positions</div>}
        </div>
      )}

      {/* ═══ TRADES TAB ═══ */}
      {tab === "trades" && (
        <div className="bg-bah-surface border border-bah-border rounded-xl overflow-hidden">
          {trades?.trades?.length > 0 ? (
            <table className="w-full text-xs">
              <thead><tr className="text-left text-bah-muted border-b border-bah-border">
                <th className="px-4 py-2.5">Asset</th><th className="px-3">Strategy</th><th className="px-3 text-right">Entry</th>
                <th className="px-3 text-right">Exit</th><th className="px-3 text-right">PnL</th><th className="px-3">Reason</th><th className="px-3 text-right">Bars</th>
              </tr></thead>
              <tbody>{trades.trades.slice(0, 30).map((t: any, i: number) => (
                <tr key={i} className="border-b border-bah-border/50">
                  <td className="px-4 py-2.5 font-medium text-bah-heading">{t.asset}</td>
                  <td className="px-3 text-bah-muted">{t.strategy}</td>
                  <td className="px-3 text-right font-mono">${t.entry_price.toLocaleString()}</td>
                  <td className="px-3 text-right font-mono">${t.exit_price.toLocaleString()}</td>
                  <td className={`px-3 text-right font-semibold font-mono ${t.pnl>=0?"text-green-400":"text-red-400"}`}>{t.pnl>=0?"+":""}${t.pnl.toFixed(0)}</td>
                  <td className="px-3 text-bah-muted">{t.exit_reason}</td>
                  <td className="px-3 text-right text-bah-muted">{t.bars_held}</td>
                </tr>
              ))}</tbody>
            </table>
          ) : <div className="p-6 text-center text-bah-muted text-sm">No trades yet</div>}
        </div>
      )}

      {/* ═══ ALERTS TAB ═══ */}
      {tab === "alerts" && (
        <div className="bg-bah-surface border border-bah-border rounded-xl overflow-hidden">
          {alerts.length > 0 ? (
            <div className="divide-y divide-bah-border/50">{alerts.slice(0, 30).map((a: any, i: number) => (
              <div key={i} className={`px-4 py-3 flex items-start gap-3 ${a.level==="CRITICAL"?"bg-red-500/5":a.level==="WARNING"?"bg-amber-500/5":""}`}>
                <span className={`mt-0.5 text-[10px] font-bold px-1.5 py-0.5 rounded ${a.level==="CRITICAL"?"bg-red-500/20 text-red-400":a.level==="WARNING"?"bg-amber-500/20 text-amber-400":"bg-bah-border text-bah-muted"}`}>{a.level}</span>
                <div className="flex-1 min-w-0"><div className="text-xs font-medium text-bah-heading">{a.title}</div><div className="text-[11px] text-bah-muted mt-0.5 whitespace-pre-line">{a.message}</div></div>
                <div className="text-[10px] text-bah-muted font-mono whitespace-nowrap">{fmtTime(a.timestamp)}</div>
              </div>
            ))}</div>
          ) : <div className="p-6 text-center text-bah-muted text-sm">No alerts</div>}
        </div>
      )}
    </div>
  );
}
