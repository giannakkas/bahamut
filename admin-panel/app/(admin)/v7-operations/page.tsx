"use client";
import { useState, useEffect, useCallback } from "react";
import { apiBase } from "@/lib/utils";

// ─── Types ───
interface Sleeve {
  allocation_pct: number;
  equity: number;
  realized_pnl: number;
  unrealized_pnl: number;
  drawdown_pct: number;
  trades: number;
  wins: number;
  win_rate: number;
  enabled: boolean;
  open_positions: number;
}

interface Summary {
  total_equity: number;
  initial_capital: number;
  total_return_pct: number;
  total_realized_pnl: number;
  total_unrealized_pnl: number;
  total_open_risk: number;
  drawdown_pct: number;
  peak_equity: number;
  open_positions: number;
  total_trades: number;
  kill_switch: boolean;
  sleeves: Record<string, Sleeve>;
}

interface Position {
  order_id: string;
  strategy: string;
  asset: string;
  direction: string;
  entry_price: number;
  current_price: number;
  stop_price: number;
  tp_price: number;
  size: number;
  unrealized_pnl: number;
  unrealized_pnl_pct: number;
  bars_held: number;
  max_hold_bars: number;
  entry_time: string;
}

interface Trade {
  trade_id: string;
  strategy: string;
  asset: string;
  direction: string;
  entry_price: number;
  exit_price: number;
  pnl: number;
  pnl_pct: number;
  exit_reason: string;
  bars_held: number;
  entry_time: string;
  exit_time: string;
}

// ─── Component ───
export default function V7OperationsPage() {
  const [summary, setSummary] = useState<Summary | null>(null);
  const [positions, setPositions] = useState<Position[]>([]);
  const [trades, setTrades] = useState<Trade[]>([]);
  const [assetData, setAssetData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [tab, setTab] = useState<"overview" | "positions" | "trades">("overview");

  const token = typeof window !== "undefined" ? sessionStorage.getItem("bah_token") : null;
  const headers: Record<string, string> = token ? { Authorization: `Bearer ${token}` } : {};

  const api = useCallback(
    async (path: string, opts?: RequestInit) => {
      try {
        const res = await fetch(`${apiBase().replace("/api/v1", "/api/v7")}${path}`, {
          ...opts,
          headers: { "Content-Type": "application/json", ...headers, ...(opts?.headers || {}) },
        });
        if (!res.ok) throw new Error(`${res.status}`);
        return res.json();
      } catch (e: any) {
        console.error(`v7 API ${path}:`, e);
        return null;
      }
    },
    [token]
  );

  const load = useCallback(async () => {
    const [s, p, t, a] = await Promise.all([
      api("/portfolio/summary"),
      api("/execution/open-positions"),
      api("/execution/closed-trades"),
      api("/assets/summary"),
    ]);
    if (s) setSummary(s);
    if (p) setPositions(Array.isArray(p) ? p : []);
    if (t) setTrades(Array.isArray(t) ? t : []);
    if (a) setAssetData(a);
    setLoading(false);
  }, [api]);

  useEffect(() => {
    load();
    const interval = setInterval(load, 30_000); // Refresh every 30s
    return () => clearInterval(interval);
  }, [load]);

  const handleKillSwitch = async () => {
    if (!confirm("Activate kill switch? This will close ALL open positions.")) return;
    await api("/portfolio/kill-switch", { method: "POST" });
    load();
  };

  const handleResume = async () => {
    await api("/portfolio/resume", { method: "POST" });
    load();
  };

  const handleToggleStrategy = async (name: string, enable: boolean) => {
    await api(`/strategies/${name}/${enable ? "enable" : "disable"}`, { method: "POST" });
    load();
  };

  const handleRebalance = async () => {
    await api("/portfolio/rebalance", { method: "POST", body: "{}" });
    load();
  };

  const handleRunCycle = async () => {
    await api("/orchestrator/run-cycle", { method: "POST" });
    setTimeout(load, 1000); // Refresh after cycle completes
  };

  if (loading) return <div className="p-6 text-bah-muted">Loading v7 operations...</div>;

  const s = summary;
  const totalPnl = (s?.total_realized_pnl || 0) + (s?.total_unrealized_pnl || 0);

  return (
    <div className="p-6 max-w-7xl space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-bah-heading flex items-center gap-3">
            v8 Trading Operations
            <span
              className={`px-2 py-0.5 text-[10px] rounded-full font-semibold border ${
                s?.kill_switch
                  ? "bg-red-500/20 text-red-400 border-red-500/30"
                  : "bg-green-500/20 text-green-400 border-green-500/30"
              }`}
            >
              {s?.kill_switch ? "KILL SWITCH ACTIVE" : "LIVE"}
            </span>
          </h1>
          <p className="text-xs text-bah-muted mt-1">
            Multi-regime portfolio • {s?.portfolio_mode || "initializing"}
          </p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={handleRunCycle}
            className="px-3 py-1.5 bg-bah-cyan/20 border border-bah-cyan/40 rounded-lg text-xs text-bah-cyan hover:bg-bah-cyan/30"
          >
            ▶ Run Cycle
          </button>
          <button
            onClick={() => { setLoading(true); load(); }}
            className="px-3 py-1.5 border border-bah-border rounded-lg text-xs text-bah-muted hover:text-bah-heading transition-colors"
          >
            ↻ Refresh
          </button>
          {s?.kill_switch ? (
            <button
              onClick={handleResume}
              className="px-3 py-1.5 bg-green-500/20 border border-green-500/40 rounded-lg text-xs text-green-400 hover:bg-green-500/30"
            >
              Resume Trading
            </button>
          ) : (
            <button
              onClick={handleKillSwitch}
              className="px-3 py-1.5 bg-red-500/20 border border-red-500/40 rounded-lg text-xs text-red-400 hover:bg-red-500/30"
            >
              Kill Switch
            </button>
          )}
        </div>
      </div>

      {/* Portfolio Stats */}
      <div className="grid grid-cols-6 gap-3">
        {[
          { label: "Total Equity", value: `$${(s?.total_equity || 100000).toLocaleString()}`, color: "text-bah-heading" },
          { label: "Total P&L", value: `${totalPnl >= 0 ? "+" : ""}$${totalPnl.toFixed(0)}`, color: totalPnl >= 0 ? "text-green-400" : "text-red-400" },
          { label: "Return", value: `${(s?.total_return_pct || 0) >= 0 ? "+" : ""}${(s?.total_return_pct || 0).toFixed(2)}%`, color: (s?.total_return_pct || 0) >= 0 ? "text-green-400" : "text-red-400" },
          { label: "Drawdown", value: `${(s?.drawdown_pct || 0).toFixed(2)}%`, color: (s?.drawdown_pct || 0) > 5 ? "text-red-400" : "text-amber-400" },
          { label: "Open Risk", value: `$${(s?.total_open_risk || 0).toLocaleString()}`, color: "text-amber-400" },
          { label: "Open / Total", value: `${s?.open_positions || 0} / ${s?.total_trades || 0}`, color: "text-bah-cyan" },
        ].map((m) => (
          <div key={m.label} className="bg-bah-surface border border-bah-border rounded-xl p-3 text-center">
            <div className={`text-lg font-bold ${m.color}`}>{m.value}</div>
            <div className="text-[9px] text-bah-muted uppercase mt-0.5">{m.label}</div>
          </div>
        ))}
      </div>

      {/* v8 Regime Banner */}
      {s?.regime && (
        <div className={`rounded-xl border p-4 flex items-center justify-between ${
          s.regime === "TREND" ? "bg-green-500/10 border-green-500/30" :
          s.regime === "CRASH" ? "bg-red-500/10 border-red-500/30" :
          "bg-amber-500/10 border-amber-500/30"
        }`}>
          <div className="flex items-center gap-3">
            <span className={`text-2xl font-bold ${
              s.regime === "TREND" ? "text-green-400" :
              s.regime === "CRASH" ? "text-red-400" : "text-amber-400"
            }`}>
              {s.regime === "TREND" ? "📈" : s.regime === "CRASH" ? "🔻" : "↔️"} {s.regime}
            </span>
            <div className="text-xs text-bah-muted">
              <div>Mode: <span className="text-bah-heading font-semibold">{s.portfolio_mode || "—"}</span></div>
              {s.asset_regimes && Object.keys(s.asset_regimes).length > 0 ? (
                <div className="flex gap-3 mt-0.5">
                  {Object.entries(s.asset_regimes).map(([a, r]: [string, any]) => (
                    <span key={a} className={r === "TREND" ? "text-green-400" : r === "CRASH" ? "text-red-400" : "text-amber-400"}>
                      {a}: {r as string}
                    </span>
                  ))}
                </div>
              ) : (
                <div>Active: {s.sleeves ? Object.entries(s.sleeves).filter(([,v]: any) => v.enabled).map(([k]) => k).join(", ") || "none" : "—"}</div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Asset Breakdown */}
      {assetData?.assets && (
        <div className="grid grid-cols-2 gap-3">
          {Object.entries(assetData.assets).map(([asset, data]: [string, any]) => (
            <div key={asset} className="bg-bah-surface border border-bah-border rounded-xl p-4">
              <div className="flex items-center justify-between mb-3">
                <h3 className="text-sm font-bold text-bah-heading">{asset}</h3>
                <div className="flex gap-2">
                  <span className={`text-[10px] px-2 py-0.5 rounded-full font-semibold border ${
                    data.regime === "TREND" ? "bg-green-500/20 text-green-400 border-green-500/30" :
                    data.regime === "CRASH" ? "bg-red-500/20 text-red-400 border-red-500/30" :
                    "bg-amber-500/20 text-amber-400 border-amber-500/30"
                  }`}>
                    {data.regime || "—"}
                  </span>
                  <span className="text-[10px] px-2 py-0.5 rounded-full bg-bah-cyan/20 text-bah-cyan border border-bah-cyan/30">
                    {data.open_positions} open
                  </span>
                </div>
              </div>
              <div className="grid grid-cols-3 gap-3 text-xs">
                <div>
                  <div className="text-bah-muted">Realized</div>
                  <div className={data.realized_pnl >= 0 ? "text-green-400 font-semibold" : "text-red-400 font-semibold"}>
                    ${data.realized_pnl.toFixed(0)}
                  </div>
                </div>
                <div>
                  <div className="text-bah-muted">Unrealized</div>
                  <div className={data.unrealized_pnl >= 0 ? "text-green-400 font-semibold" : "text-red-400 font-semibold"}>
                    ${data.unrealized_pnl.toFixed(0)}
                  </div>
                </div>
                <div>
                  <div className="text-bah-muted">Trades</div>
                  <div className="text-bah-heading font-semibold">{data.closed_trades}</div>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Crypto Risk Bar */}
      {assetData && (
        <div className="bg-bah-surface border border-bah-border rounded-xl p-3 flex items-center justify-between text-xs">
          <span className="text-bah-muted">Combined Crypto Risk:</span>
          <div className="flex items-center gap-4">
            <span className={`font-semibold ${assetData.crypto_risk_pct > 4 ? "text-red-400" : "text-bah-heading"}`}>
              {assetData.crypto_risk_pct}% of portfolio
            </span>
            <span className="text-bah-muted">
              (${assetData.total_crypto_risk.toLocaleString()} / ${assetData.max_crypto_risk.toLocaleString()} max)
            </span>
          </div>
        </div>
      )}

      {/* Strategy Sleeves */}
      <div className="bg-bah-surface border border-bah-border rounded-xl overflow-hidden">
        <div className="px-4 py-3 border-b border-bah-border flex items-center justify-between">
          <h2 className="text-sm font-semibold text-bah-heading">Strategy Sleeves</h2>
          <button
            onClick={handleRebalance}
            className="px-2 py-1 text-[10px] border border-bah-border rounded text-bah-muted hover:text-bah-heading"
          >
            Rebalance
          </button>
        </div>
        <div className="divide-y divide-bah-border">
          {s?.sleeves && Object.entries(s.sleeves).map(([name, sleeve]) => (
            <div key={name} className="px-4 py-3 flex items-center gap-6">
              <div className="flex items-center gap-2 w-32">
                <span className={`w-2 h-2 rounded-full ${sleeve.enabled ? "bg-green-400" : "bg-gray-600"}`} />
                <span className="text-sm font-mono text-bah-heading">{name}</span>
              </div>
              <div className="flex-1 grid grid-cols-7 gap-4 text-xs">
                <div>
                  <div className="text-bah-muted">Allocation</div>
                  <div className="text-bah-heading font-semibold">{sleeve.allocation_pct}%</div>
                </div>
                <div>
                  <div className="text-bah-muted">Equity</div>
                  <div className="text-bah-heading font-semibold">${sleeve.equity.toLocaleString()}</div>
                </div>
                <div>
                  <div className="text-bah-muted">P&L</div>
                  <div className={(sleeve.realized_pnl + sleeve.unrealized_pnl) >= 0 ? "text-green-400 font-semibold" : "text-red-400 font-semibold"}>
                    ${(sleeve.realized_pnl + sleeve.unrealized_pnl).toFixed(0)}
                  </div>
                </div>
                <div>
                  <div className="text-bah-muted">Drawdown</div>
                  <div className={sleeve.drawdown_pct > 5 ? "text-red-400" : "text-bah-heading"}>{sleeve.drawdown_pct}%</div>
                </div>
                <div>
                  <div className="text-bah-muted">Win Rate</div>
                  <div className="text-bah-heading">{sleeve.win_rate}%</div>
                </div>
                <div>
                  <div className="text-bah-muted">Trades</div>
                  <div className="text-bah-heading">{sleeve.trades}</div>
                </div>
                <div className="flex items-center">
                  <button
                    onClick={() => handleToggleStrategy(name, !sleeve.enabled)}
                    className={`px-2 py-0.5 text-[10px] rounded border ${
                      sleeve.enabled
                        ? "border-green-500/40 text-green-400 hover:bg-green-500/10"
                        : "border-red-500/40 text-red-400 hover:bg-red-500/10"
                    }`}
                  >
                    {sleeve.enabled ? "Enabled" : "Disabled"}
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 border-b border-bah-border">
        {(["overview", "positions", "trades"] as const).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`px-4 py-2 text-xs font-medium border-b-2 transition-colors ${
              tab === t
                ? "border-bah-cyan text-bah-cyan"
                : "border-transparent text-bah-muted hover:text-bah-heading"
            }`}
          >
            {t === "overview" ? "Overview" : t === "positions" ? `Open Positions (${positions.length})` : `Trade History (${trades.length})`}
          </button>
        ))}
      </div>

      {/* Tab Content */}
      {tab === "overview" && (
        <div className="grid grid-cols-2 gap-4">
          <div className="bg-bah-surface border border-bah-border rounded-xl p-4">
            <h3 className="text-sm font-semibold text-bah-heading mb-3">Regime Routing</h3>
            <div className="text-xs space-y-2">
              <div className="flex justify-between"><span className="text-bah-muted">TREND regime</span><span className="text-green-400">→ v5_base + v5_tuned</span></div>
              <div className="flex justify-between"><span className="text-bah-muted">RANGE regime</span><span className="text-amber-400">→ v8_range (mean reversion)</span></div>
              <div className="flex justify-between"><span className="text-bah-muted">CRASH regime</span><span className="text-red-400">→ v8_defensive (no trade)</span></div>
              <div className="pt-2 border-t border-bah-border/50 mt-2">
                <div className="text-bah-muted">v5 signal: EMA20×50 cross, price &gt; EMA200, long only</div>
                <div className="text-bah-muted">v8_range: BB mean reversion, long near lower / short near upper</div>
              </div>
            </div>
          </div>
          <div className="bg-bah-surface border border-bah-border rounded-xl p-4">
            <h3 className="text-sm font-semibold text-bah-heading mb-3">Risk Limits</h3>
            <div className="text-xs space-y-2">
              <div className="flex justify-between"><span className="text-bah-muted">Max total open risk</span><span className="text-bah-heading">6%</span></div>
              <div className="flex justify-between"><span className="text-bah-muted">Max positions per sleeve</span><span className="text-bah-heading">1</span></div>
              <div className="flex justify-between"><span className="text-bah-muted">v5 risk per trade</span><span className="text-bah-heading">2%</span></div>
              <div className="flex justify-between"><span className="text-bah-muted">v8_range risk per trade</span><span className="text-bah-heading">1.5%</span></div>
              <div className="flex justify-between"><span className="text-bah-muted">Kill switch threshold</span><span className="text-bah-heading">10% drawdown</span></div>
              <div className="flex justify-between"><span className="text-bah-muted">Execution mode</span><span className="text-amber-400 font-semibold">PAPER</span></div>
            </div>
          </div>
        </div>
      )}

      {tab === "positions" && (
        <div className="bg-bah-surface border border-bah-border rounded-xl overflow-hidden">
          {positions.length === 0 ? (
            <div className="p-8 text-center text-bah-muted text-sm">No open positions</div>
          ) : (
            <table className="w-full text-xs">
              <thead className="bg-bah-bg/50">
                <tr className="text-bah-muted text-left">
                  <th className="px-3 py-2">Strategy</th>
                  <th className="px-3 py-2">Asset</th>
                  <th className="px-3 py-2">Dir</th>
                  <th className="px-3 py-2 text-right">Entry</th>
                  <th className="px-3 py-2 text-right">Current</th>
                  <th className="px-3 py-2 text-right">SL</th>
                  <th className="px-3 py-2 text-right">TP</th>
                  <th className="px-3 py-2 text-right">P&L</th>
                  <th className="px-3 py-2 text-right">P&L %</th>
                  <th className="px-3 py-2 text-right">Bars</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-bah-border/50">
                {positions.map((p) => (
                  <tr key={p.order_id} className="hover:bg-white/[0.02]">
                    <td className="px-3 py-2 font-mono">{p.strategy}</td>
                    <td className="px-3 py-2">{p.asset}</td>
                    <td className="px-3 py-2"><span className="px-1.5 py-0.5 bg-green-500/20 text-green-400 rounded text-[10px]">{p.direction}</span></td>
                    <td className="px-3 py-2 text-right font-mono">${p.entry_price.toLocaleString()}</td>
                    <td className="px-3 py-2 text-right font-mono">${p.current_price.toLocaleString()}</td>
                    <td className="px-3 py-2 text-right font-mono text-red-400/70">${p.stop_price.toLocaleString()}</td>
                    <td className="px-3 py-2 text-right font-mono text-green-400/70">${p.tp_price.toLocaleString()}</td>
                    <td className={`px-3 py-2 text-right font-semibold ${p.unrealized_pnl >= 0 ? "text-green-400" : "text-red-400"}`}>
                      ${p.unrealized_pnl.toFixed(0)}
                    </td>
                    <td className={`px-3 py-2 text-right ${p.unrealized_pnl_pct >= 0 ? "text-green-400" : "text-red-400"}`}>
                      {p.unrealized_pnl_pct >= 0 ? "+" : ""}{p.unrealized_pnl_pct.toFixed(2)}%
                    </td>
                    <td className="px-3 py-2 text-right">{p.bars_held}/{p.max_hold_bars}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {tab === "trades" && (
        <div className="bg-bah-surface border border-bah-border rounded-xl overflow-hidden">
          {trades.length === 0 ? (
            <div className="p-8 text-center text-bah-muted text-sm">No closed trades yet</div>
          ) : (
            <table className="w-full text-xs">
              <thead className="bg-bah-bg/50">
                <tr className="text-bah-muted text-left">
                  <th className="px-3 py-2">Strategy</th>
                  <th className="px-3 py-2">Asset</th>
                  <th className="px-3 py-2 text-right">Entry</th>
                  <th className="px-3 py-2 text-right">Exit</th>
                  <th className="px-3 py-2 text-right">P&L</th>
                  <th className="px-3 py-2 text-right">P&L %</th>
                  <th className="px-3 py-2">Reason</th>
                  <th className="px-3 py-2 text-right">Bars</th>
                  <th className="px-3 py-2">Exit Time</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-bah-border/50">
                {trades.map((t) => (
                  <tr key={t.trade_id} className="hover:bg-white/[0.02]">
                    <td className="px-3 py-2 font-mono">{t.strategy}</td>
                    <td className="px-3 py-2">{t.asset}</td>
                    <td className="px-3 py-2 text-right font-mono">${t.entry_price.toLocaleString()}</td>
                    <td className="px-3 py-2 text-right font-mono">${t.exit_price.toLocaleString()}</td>
                    <td className={`px-3 py-2 text-right font-semibold ${t.pnl >= 0 ? "text-green-400" : "text-red-400"}`}>
                      ${t.pnl.toFixed(0)}
                    </td>
                    <td className={`px-3 py-2 text-right ${t.pnl_pct >= 0 ? "text-green-400" : "text-red-400"}`}>
                      {t.pnl_pct >= 0 ? "+" : ""}{t.pnl_pct.toFixed(2)}%
                    </td>
                    <td className="px-3 py-2">
                      <span className={`px-1.5 py-0.5 rounded text-[10px] ${
                        t.exit_reason === "TP" ? "bg-green-500/20 text-green-400" :
                        t.exit_reason === "SL" ? "bg-red-500/20 text-red-400" :
                        "bg-amber-500/20 text-amber-400"
                      }`}>{t.exit_reason}</span>
                    </td>
                    <td className="px-3 py-2 text-right">{t.bars_held}</td>
                    <td className="px-3 py-2 text-bah-muted">{t.exit_time ? new Date(t.exit_time).toLocaleDateString() : "-"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  );
}
