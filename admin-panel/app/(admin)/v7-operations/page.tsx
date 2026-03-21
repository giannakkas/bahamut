"use client";
import { useState, useEffect, useCallback } from "react";
import { apiBase } from "@/lib/utils";

export default function MonitoringDashboard() {
  const [portfolio, setPortfolio] = useState<any>(null);
  const [strategies, setStrategies] = useState<any>(null);
  const [positions, setPositions] = useState<any>(null);
  const [trades, setTrades] = useState<any>(null);
  const [execution, setExecution] = useState<any>(null);
  const [alerts, setAlerts] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState<"overview" | "positions" | "trades" | "alerts">("overview");

  const token = typeof window !== "undefined" ? sessionStorage.getItem("bah_token") : null;
  const monApi = useCallback(async (path: string) => {
    try {
      const r = await fetch(`${apiBase}/api/monitoring${path}`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (r.ok) return r.json();
    } catch {}
    return null;
  }, [token]);

  const v7Api = useCallback(async (path: string, opts?: any) => {
    try {
      const r = await fetch(`${apiBase}/api/v7${path}`, {
        headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
        ...opts,
      });
      if (r.ok) return r.json();
    } catch {}
    return null;
  }, [token]);

  const [health, setHealth] = useState<any>(null);

  const load = useCallback(async () => {
    const [p, s, pos, t, e, a, h] = await Promise.all([
      monApi("/portfolio"), monApi("/strategies"), monApi("/positions"),
      monApi("/trades"), monApi("/execution"), monApi("/alerts"),
      monApi("/health"),
    ]);
    if (p) setPortfolio(p);
    if (s) setStrategies(s);
    if (pos) setPositions(pos);
    if (t) setTrades(t);
    if (e) setExecution(e);
    if (a?.alerts) setAlerts(a.alerts);
    if (h) setHealth(h);
    setLoading(false);
  }, [monApi]);

  useEffect(() => { load(); const i = setInterval(load, 15_000); return () => clearInterval(i); }, [load]);

  const handleKillSwitch = async () => {
    if (!confirm("Activate kill switch? This closes ALL positions.")) return;
    await v7Api("/portfolio/kill-switch", { method: "POST" }); load();
  };
  const handleResume = async () => { await v7Api("/portfolio/resume", { method: "POST" }); load(); };
  const handleRunCycle = async () => { await v7Api("/orchestrator/run-cycle", { method: "POST" }); setTimeout(load, 1500); };

  if (loading) return <div className="p-8 text-bah-muted">Loading...</div>;

  const p = portfolio;
  const dd = p?.drawdown_pct || 0;
  const risk = p?.open_risk_pct || 0;
  const pnl = p?.pnl_total || 0;
  const ddColor = dd > 8 ? "text-red-400" : dd > 5 ? "text-amber-400" : "text-green-400";
  const riskColor = risk > 5 ? "text-red-400" : risk > 4 ? "text-amber-400" : "text-bah-heading";
  const critAlerts = alerts.filter(a => a.level === "CRITICAL").length;
  const warnAlerts = alerts.filter(a => a.level === "WARNING").length;

  return (
    <div className="p-4 max-w-[1400px] space-y-4">
      {/* TOP BAR */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <h1 className="text-lg font-bold text-bah-heading">Daily Operations Monitor</h1>
          <span className={`px-2 py-0.5 text-[10px] rounded-full font-semibold border ${
            p?.kill_switch ? "bg-red-500/20 text-red-400 border-red-500/30" : "bg-green-500/20 text-green-400 border-green-500/30"
          }`}>{p?.kill_switch ? "HALTED" : "LIVE"}</span>
          {health?.data_source && (
            <span className={`px-2 py-0.5 text-[10px] rounded-full font-semibold border ${
              health.data_source === "LIVE" ? "bg-green-500/20 text-green-400 border-green-500/30" : "bg-amber-500/20 text-amber-400 border-amber-500/30"
            }`}>{health.data_source === "LIVE" ? "LIVE DATA" : "SYNTHETIC"}</span>
          )}
          {health?.engine && (
            <span className="px-2 py-0.5 text-[10px] rounded-full text-bah-muted border border-bah-border">{health.engine}</span>
          )}
          {critAlerts > 0 && <span className="px-2 py-0.5 text-[10px] rounded-full bg-red-500/20 text-red-400 border border-red-500/30 animate-pulse">{critAlerts} CRITICAL</span>}
          {warnAlerts > 0 && <span className="px-2 py-0.5 text-[10px] rounded-full bg-amber-500/20 text-amber-400 border border-amber-500/30">{warnAlerts} WARN</span>}
        </div>
        <div className="flex gap-2">
          <button onClick={handleRunCycle} className="px-3 py-1.5 bg-bah-cyan/20 border border-bah-cyan/40 rounded-lg text-xs text-bah-cyan hover:bg-bah-cyan/30">▶ Cycle</button>
          <button onClick={() => { setLoading(true); load(); }} className="px-3 py-1.5 border border-bah-border rounded-lg text-xs text-bah-muted hover:text-bah-heading">↻</button>
          {p?.kill_switch
            ? <button onClick={handleResume} className="px-3 py-1.5 bg-green-500/20 border border-green-500/40 rounded-lg text-xs text-green-400">Resume</button>
            : <button onClick={handleKillSwitch} className="px-3 py-1.5 bg-red-500/10 border border-red-500/30 rounded-lg text-xs text-red-400">Kill Switch</button>
          }
        </div>
      </div>

      {/* KEY METRICS */}
      <div className="grid grid-cols-6 gap-2">
        {[
          { l: "Equity", v: `$${(p?.equity || 100000).toLocaleString(undefined, {maximumFractionDigits:0})}`, c: "text-bah-heading" },
          { l: "Total P&L", v: `${pnl >= 0 ? "+" : ""}$${Math.abs(pnl).toFixed(0)}`, c: pnl >= 0 ? "text-green-400" : "text-red-400" },
          { l: "Return", v: `${(p?.return_pct||0) >= 0 ? "+" : ""}${(p?.return_pct||0).toFixed(2)}%`, c: (p?.return_pct||0) >= 0 ? "text-green-400" : "text-red-400" },
          { l: "Drawdown", v: `${dd.toFixed(1)}%`, c: ddColor },
          { l: "Open Risk", v: `${risk.toFixed(1)}%`, c: riskColor },
          { l: "Positions", v: `${p?.open_positions||0} / ${p?.total_trades||0}`, c: "text-bah-cyan" },
        ].map((m) => (
          <div key={m.l} className="bg-bah-surface border border-bah-border rounded-xl p-3 text-center">
            <div className={`text-lg font-bold ${m.c}`}>{m.v}</div>
            <div className="text-[9px] text-bah-muted uppercase mt-0.5">{m.l}</div>
          </div>
        ))}
      </div>

      {/* REGIME CARDS */}
      {p?.regime && Object.keys(p.regime).length > 0 && (
        <div className="grid grid-cols-2 gap-2">
          {Object.entries(p.regime).map(([asset, regime]: [string, any]) => (
            <div key={asset} className={`rounded-xl border p-3 flex items-center justify-between ${
              regime === "TREND" ? "bg-green-500/5 border-green-500/20" :
              regime === "CRASH" ? "bg-red-500/5 border-red-500/20" : "bg-amber-500/5 border-amber-500/20"
            }`}>
              <div className="flex items-center gap-2">
                <span className="text-sm font-bold text-bah-heading">{asset}</span>
                <span className={`text-xs font-semibold ${
                  regime === "TREND" ? "text-green-400" : regime === "CRASH" ? "text-red-400" : "text-amber-400"
                }`}>{regime === "TREND" ? "📈" : regime === "CRASH" ? "🔻" : "↔️"} {regime as string}</span>
              </div>
              <span className="text-[10px] text-bah-muted">{regime === "TREND" ? "v5+v9 active" : regime === "CRASH" ? "No trading" : "Range mode"}</span>
            </div>
          ))}
        </div>
      )}

      {/* TABS */}
      <div className="flex gap-1 border-b border-bah-border">
        {(["overview","positions","trades","alerts"] as const).map((t) => (
          <button key={t} onClick={() => setTab(t)} className={`px-4 py-2 text-xs font-medium border-b-2 transition-colors ${
            tab === t ? "border-bah-cyan text-bah-cyan" : "border-transparent text-bah-muted hover:text-bah-heading"
          }`}>{t === "overview" ? "📊 Strategies" : t === "positions" ? "📦 Positions" : t === "trades" ? "🔁 Trades" : `⚠️ Alerts (${alerts.length})`}</button>
        ))}
      </div>

      {/* STRATEGIES TAB */}
      {tab === "overview" && strategies && (
        <div className="bg-bah-surface border border-bah-border rounded-xl overflow-hidden">
          <table className="w-full text-xs">
            <thead><tr className="text-left text-bah-muted border-b border-bah-border">
              <th className="px-4 py-2.5">Strategy</th>
              <th className="px-3 py-2.5 text-right">PnL</th>
              <th className="px-3 py-2.5 text-right">Trades</th>
              <th className="px-3 py-2.5 text-right">WR</th>
              <th className="px-3 py-2.5 text-right">WR(20)</th>
              <th className="px-3 py-2.5 text-right">PF</th>
              <th className="px-3 py-2.5 text-right">Expect.</th>
              <th className="px-3 py-2.5 text-right">Equity</th>
              <th className="px-3 py-2.5 text-right">Open</th>
            </tr></thead>
            <tbody>
              {Object.entries(strategies).filter(([,v]: any) => v.trades > 0 || v.open_positions > 0).map(([n, s]: [string, any]) => (
                <tr key={n} className="border-b border-bah-border/50 hover:bg-bah-border/10">
                  <td className="px-4 py-2.5 font-medium text-bah-heading">{n}</td>
                  <td className={`px-3 py-2.5 text-right font-semibold ${s.pnl >= 0 ? "text-green-400" : "text-red-400"}`}>${s.pnl.toFixed(0)}</td>
                  <td className="px-3 py-2.5 text-right text-bah-heading">{s.trades}</td>
                  <td className="px-3 py-2.5 text-right">{s.win_rate.toFixed(0)}%</td>
                  <td className={`px-3 py-2.5 text-right font-medium ${s.rolling_wr >= 50 ? "text-green-400" : s.rolling_wr < 35 ? "text-red-400" : "text-amber-400"}`}>{s.rolling_wr.toFixed(0)}%</td>
                  <td className={`px-3 py-2.5 text-right ${s.profit_factor >= 1.5 ? "text-green-400" : s.profit_factor < 1 ? "text-red-400" : "text-bah-heading"}`}>{s.profit_factor.toFixed(2)}</td>
                  <td className={`px-3 py-2.5 text-right ${s.expectancy >= 0 ? "text-green-400" : "text-red-400"}`}>${s.expectancy.toFixed(0)}</td>
                  <td className="px-3 py-2.5 text-right text-bah-muted">${s.equity.toLocaleString(undefined, {maximumFractionDigits:0})}</td>
                  <td className="px-3 py-2.5 text-right">{s.open_positions > 0 ? <span className="text-bah-cyan font-semibold">{s.open_positions}</span> : <span className="text-bah-muted">—</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {execution && (
            <div className="px-4 py-2 border-t border-bah-border/50 flex gap-6 text-[10px] text-bah-muted">
              <span>Signals: {execution.total_signals_processed}</span>
              <span>Orders: {execution.total_orders}</span>
              <span>Cancelled: {execution.cancelled_orders}</span>
              <span>Avg Slippage: {execution.avg_slippage_bps}bps</span>
            </div>
          )}
        </div>
      )}

      {/* POSITIONS TAB */}
      {tab === "positions" && (
        <div className="bg-bah-surface border border-bah-border rounded-xl overflow-hidden">
          {positions?.positions?.length > 0 ? (
            <table className="w-full text-xs">
              <thead><tr className="text-left text-bah-muted border-b border-bah-border">
                <th className="px-4 py-2.5">Asset</th><th className="px-3 py-2.5">Strategy</th>
                <th className="px-3 py-2.5 text-right">Entry</th><th className="px-3 py-2.5 text-right">Current</th>
                <th className="px-3 py-2.5 text-right">SL</th><th className="px-3 py-2.5 text-right">TP</th>
                <th className="px-3 py-2.5 text-right">PnL</th><th className="px-3 py-2.5 text-right">Risk%</th>
                <th className="px-3 py-2.5 text-right">Bars</th>
              </tr></thead>
              <tbody>{positions.positions.map((pos: any, i: number) => (
                <tr key={i} className="border-b border-bah-border/50">
                  <td className="px-4 py-2.5 font-medium text-bah-heading">{pos.asset}</td>
                  <td className="px-3 py-2.5 text-bah-muted">{pos.strategy}</td>
                  <td className="px-3 py-2.5 text-right">${pos.entry_price.toLocaleString()}</td>
                  <td className="px-3 py-2.5 text-right">${pos.current_price.toLocaleString()}</td>
                  <td className="px-3 py-2.5 text-right text-red-400">${pos.stop_loss.toLocaleString()}</td>
                  <td className="px-3 py-2.5 text-right text-green-400">${pos.take_profit.toLocaleString()}</td>
                  <td className={`px-3 py-2.5 text-right font-semibold ${pos.unrealized_pnl >= 0 ? "text-green-400" : "text-red-400"}`}>${pos.unrealized_pnl.toFixed(0)}</td>
                  <td className={`px-3 py-2.5 text-right ${pos.risk_pct > 3 ? "text-red-400" : "text-bah-heading"}`}>{pos.risk_pct.toFixed(1)}%</td>
                  <td className="px-3 py-2.5 text-right text-bah-muted">{pos.bars_held}</td>
                </tr>
              ))}</tbody>
            </table>
          ) : <div className="p-8 text-center text-bah-muted text-sm">No open positions</div>}
        </div>
      )}

      {/* TRADES TAB */}
      {tab === "trades" && (
        <div className="bg-bah-surface border border-bah-border rounded-xl overflow-hidden">
          {trades?.trades?.length > 0 ? (
            <table className="w-full text-xs">
              <thead><tr className="text-left text-bah-muted border-b border-bah-border">
                <th className="px-4 py-2.5">Asset</th><th className="px-3 py-2.5">Strategy</th>
                <th className="px-3 py-2.5 text-right">Entry</th><th className="px-3 py-2.5 text-right">Exit</th>
                <th className="px-3 py-2.5 text-right">PnL</th><th className="px-3 py-2.5">Reason</th>
                <th className="px-3 py-2.5 text-right">Bars</th>
              </tr></thead>
              <tbody>{trades.trades.slice(0, 30).map((t: any, i: number) => (
                <tr key={i} className="border-b border-bah-border/50">
                  <td className="px-4 py-2.5 font-medium text-bah-heading">{t.asset}</td>
                  <td className="px-3 py-2.5 text-bah-muted">{t.strategy}</td>
                  <td className="px-3 py-2.5 text-right">${t.entry_price.toLocaleString()}</td>
                  <td className="px-3 py-2.5 text-right">${t.exit_price.toLocaleString()}</td>
                  <td className={`px-3 py-2.5 text-right font-semibold ${t.pnl >= 0 ? "text-green-400" : "text-red-400"}`}>{t.pnl >= 0 ? "+" : ""}${t.pnl.toFixed(0)}</td>
                  <td className="px-3 py-2.5 text-bah-muted">{t.exit_reason}</td>
                  <td className="px-3 py-2.5 text-right text-bah-muted">{t.bars_held}</td>
                </tr>
              ))}</tbody>
            </table>
          ) : <div className="p-8 text-center text-bah-muted text-sm">No trades yet</div>}
        </div>
      )}

      {/* ALERTS TAB */}
      {tab === "alerts" && (
        <div className="bg-bah-surface border border-bah-border rounded-xl overflow-hidden">
          {alerts.length > 0 ? (
            <div className="divide-y divide-bah-border/50">
              {alerts.slice(0, 40).map((a: any, i: number) => (
                <div key={i} className={`px-4 py-3 flex items-start gap-3 ${
                  a.level === "CRITICAL" ? "bg-red-500/5" : a.level === "WARNING" ? "bg-amber-500/5" : ""
                }`}>
                  <span className={`mt-0.5 text-[10px] font-bold px-1.5 py-0.5 rounded ${
                    a.level === "CRITICAL" ? "bg-red-500/20 text-red-400" :
                    a.level === "WARNING" ? "bg-amber-500/20 text-amber-400" : "bg-bah-border text-bah-muted"
                  }`}>{a.level}</span>
                  <div className="flex-1 min-w-0">
                    <div className="text-xs font-medium text-bah-heading">{a.title}</div>
                    <div className="text-[11px] text-bah-muted mt-0.5 whitespace-pre-line">{a.message}</div>
                  </div>
                  <div className="text-[10px] text-bah-muted whitespace-nowrap">
                    {a.timestamp ? new Date(a.timestamp).toLocaleTimeString() : ""}
                  </div>
                </div>
              ))}
            </div>
          ) : <div className="p-8 text-center text-bah-muted text-sm">No alerts</div>}
        </div>
      )}
    </div>
  );
}
