"use client";

import React, { useState, useEffect, useRef, useCallback } from "react";
import { apiBase } from "@/lib/utils";
import { useAdminSocket } from "@/providers/AdminSocketProvider";

const STRAT_NAMES: Record<string, string> = {
  v5_base: "S1 · EMA Trend",
  v5_tuned: "S2 · EMA Tuned",
  v9_breakout: "S3 · Breakout",
  v10_mean_reversion: "S4 · Mean Reversion",
};
const sn = (s: string) => STRAT_NAMES[s] || s;

/* ═══════════════════════════════════════════
   COUNTDOWN HOOK — ticks every second
   ═══════════════════════════════════════════ */
function useCountdown(targetIso: string | null) {
  const [secs, setSecs] = useState<number | null>(null);
  useEffect(() => {
    if (!targetIso) { setSecs(null); return; }
    const target = new Date(targetIso).getTime();
    const tick = () => setSecs(Math.max(0, Math.floor((target - Date.now()) / 1000)));
    tick();
    const iv = setInterval(tick, 1000);
    return () => clearInterval(iv);
  }, [targetIso]);
  return secs;
}

function fmtCountdown(s: number | null): string {
  if (s === null || s === undefined) return "--:--";
  const m = Math.floor(s / 60), sec = s % 60;
  if (m >= 60) { const h = Math.floor(m / 60); return `${h}h ${m % 60}m`; }
  return `${m}:${sec.toString().padStart(2, "0")}`;
}

/* ═══════════════════════════════════════════
   MAIN PAGE
   ═══════════════════════════════════════════ */
export default function TrainingOperationsPage() {
  const [data, setData] = useState<any>(null);
  const [candidates, setCandidates] = useState<any[]>([]);
  const [decisions, setDecisions] = useState<any>(null);
  const [adaptive, setAdaptive] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [allAssets, setAllAssets] = useState<any>(null);
  const [failedSignals, setFailedSignals] = useState<any[]>([]);
  const [tab, setTab] = useState<"overview" | "positions" | "trades" | "failed" | "learning" | "risk" | "assets">("overview");
  const [cycleTriggered, setCycleTriggered] = useState(false);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [secondsAgo, setSecondsAgo] = useState(0);
  const [soundEnabled, setSoundEnabled] = useState(true);
  const prevCounts = useRef<{ open: number; closed: number; signals: number }>({ open: 0, closed: 0, signals: 0 });
  const audioCtxRef = useRef<AudioContext | null>(null);
  const prevLastCycle = useRef<string | null>(null);
  const token = typeof window !== "undefined" ? sessionStorage.getItem("bah_token") : null;

  // Reset "Triggered" button when cycle actually starts running or when new cycle data arrives
  useEffect(() => {
    if (!data) return;
    const cs = data.cycle_status || {};
    // Cycle is running → clear triggered (animation takes over)
    if (cs.is_running && cycleTriggered) {
      setCycleTriggered(false);
    }
    // New cycle completed (last_cycle_time changed) → clear triggered
    const lastCycleTime = cs.last_cycle_time || "";
    if (prevLastCycle.current && lastCycleTime !== prevLastCycle.current && cycleTriggered) {
      setCycleTriggered(false);
    }
    prevLastCycle.current = lastCycleTime;
  }, [data]);

  // ── Trade sound effects via Web Audio API ──
  const getAudioCtx = () => {
    if (!audioCtxRef.current) {
      audioCtxRef.current = new (window.AudioContext || (window as any).webkitAudioContext)();
    }
    return audioCtxRef.current;
  };

  const playTradeOpenSound = () => {
    try {
      const ctx = getAudioCtx();
      // Rising two-tone chime — trade opened
      [520, 780].forEach((freq, i) => {
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.type = "sine";
        osc.frequency.value = freq;
        gain.gain.setValueAtTime(0.18, ctx.currentTime + i * 0.12);
        gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + i * 0.12 + 0.3);
        osc.connect(gain).connect(ctx.destination);
        osc.start(ctx.currentTime + i * 0.12);
        osc.stop(ctx.currentTime + i * 0.12 + 0.3);
      });
    } catch {}
  };

  const playTradeCloseSound = () => {
    try {
      const ctx = getAudioCtx();
      // Falling two-tone — trade closed
      [660, 440].forEach((freq, i) => {
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.type = "triangle";
        osc.frequency.value = freq;
        gain.gain.setValueAtTime(0.15, ctx.currentTime + i * 0.12);
        gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + i * 0.12 + 0.25);
        osc.connect(gain).connect(ctx.destination);
        osc.start(ctx.currentTime + i * 0.12);
        osc.stop(ctx.currentTime + i * 0.12 + 0.25);
      });
    } catch {}
  };

  const playSignalSound = () => {
    try {
      const ctx = getAudioCtx();
      // Quick blip — new signal/execution decision
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = "sine";
      osc.frequency.value = 880;
      gain.gain.setValueAtTime(0.1, ctx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.15);
      osc.connect(gain).connect(ctx.destination);
      osc.start(); osc.stop(ctx.currentTime + 0.15);
    } catch {}
  };

  // Detect trade changes and play sounds
  const checkTradeChanges = (newData: any) => {
    if (!soundEnabled || !newData?.kpi) return;
    const open = newData.kpi.open_positions || 0;
    const closed = newData.kpi.closed_trades || 0;
    const signals = newData.cycle_health?.signals_generated || 0;
    const prev = prevCounts.current;

    if (prev.open > 0 || prev.closed > 0) { // Skip first load
      if (open > prev.open) playTradeOpenSound();
      if (closed > prev.closed) playTradeCloseSound();
      if (signals > prev.signals) playSignalSound();
    }
    prevCounts.current = { open, closed, signals };
  };

  // Tick "seconds ago" every second
  useEffect(() => {
    const i = setInterval(() => {
      if (lastUpdated) setSecondsAgo(Math.round((Date.now() - lastUpdated.getTime()) / 1000));
    }, 1000);
    return () => clearInterval(i);
  }, [lastUpdated]);

  const load = async () => {
    const h: Record<string, string> = token ? { Authorization: `Bearer ${token}` } : {};

    // ── Phase 1: Fast endpoints → render immediately ──
    try {
      const [opsRes, decRes, adaptRes, assetsRes] = await Promise.all([
        fetch(`${apiBase()}/training/operations`, { headers: h }),
        fetch(`${apiBase()}/training/execution-decisions`, { headers: h }),
        fetch(`${apiBase()}/training/adaptive`, { headers: h }),
        fetch(`${apiBase()}/training/assets`, { headers: h }),
      ]);
      if (opsRes.ok) setData(await opsRes.json());
      if (decRes.ok) setDecisions(await decRes.json());
      if (adaptRes.ok) setAdaptive(await adaptRes.json());
      if (assetsRes.ok) {
        const newAssets = await assetsRes.json();
        const hasRealData = newAssets?.assets?.some((a: any) => a.status !== "no_data");
        setAllAssets((prev: any) => hasRealData || !prev ? newAssets : prev);
      }
    } catch {}
    setLoading(false);

    // ── Phase 2: Candidates → background, never overwrite good data with empty ──
    fetch(`${apiBase()}/training/candidates`, { headers: h })
      .then(r => r.ok ? r.json() : null)
      .then(d => { if (d && d.length > 0) setCandidates(d); })
      .catch(() => {});

    // ── Phase 3: Failed signals → background ──
    try {
      const [failRes, prodFailRes] = await Promise.all([
        fetch(`${apiBase()}/training/execution-decisions`, { headers: h }),
        fetch(`${apiBase()}/monitoring/failed-signals`, { headers: h }),
      ]);
      const combined: any[] = [];
      if (failRes.ok) {
        const d = await failRes.json();
        for (const r of (d.rejected || [])) combined.push({ ...r, source: "training", _group: "REJECT" });
        for (const w of (d.watchlist || [])) combined.push({ ...w, source: "training", _group: "WATCHLIST" });
      }
      if (prodFailRes.ok) {
        const p = await prodFailRes.json();
        for (const s of (p.signals || [])) combined.push({ ...s, source: "production", _group: "BLOCKED" });
      }
      setFailedSignals(combined);
    } catch {}
  };

  // Fast refresh: live data (positions, KPIs, cycle status) — every 5s like Daily Operations
  const fastRefresh = useCallback(async () => {
    const h: Record<string, string> = token ? { Authorization: `Bearer ${token}` } : {};
    try {
      const r = await fetch(`${apiBase()}/training/operations`, { headers: h });
      if (r.ok) {
        const newData = await r.json();
        checkTradeChanges(newData);
        setData(newData);
        setLastUpdated(new Date());
      }
    } catch {}
  }, [token]);

  // WebSocket: instant refresh when events arrive
  const { status: wsStatus, addListener, removeListener } = useAdminSocket();
  useEffect(() => {
    const handler = (evt: { event: string }) => {
      if (["cycle_completed", "position_opened", "position_closed", "selector_updated", "learning_updated"].includes(evt.event)) {
        fastRefresh();
      }
    };
    addListener(handler);
    return () => removeListener(handler);
  }, [addListener, removeListener, fastRefresh]);

  // Initial full load, then: fast=5s for live data, slow=60s for heavy data
  useEffect(() => {
    load();
    const fast = setInterval(fastRefresh, 5_000);
    const slow = setInterval(load, 60_000);
    return () => { clearInterval(fast); clearInterval(slow); };
  }, []);

  if (loading) return (
    <div className="p-12 text-center">
      <div className="inline-block w-8 h-8 border-2 border-bah-cyan/30 border-t-bah-cyan rounded-full animate-spin mb-4" />
      <p className="text-bah-muted text-sm">Loading training operations...</p>
    </div>
  );

  if (!data) return (
    <div className="p-12 text-center">
      <p className="text-lg font-bold text-bah-heading mb-2">Training Operations</p>
      <p className="text-sm text-bah-muted">Waiting for first training cycle (runs every 10 min).</p>
    </div>
  );

  const k = data.kpi || {};
  const cs = data.cycle_status || {};
  const cy = data.cycle_health || {};
  const strats = data.strategy_breakdown || {};
  const classes = data.class_breakdown || {};
  const rankings = data.asset_rankings || {};
  const learn = data.learning || {};
  const expo = data.exposure || {};
  const alerts = data.alerts || [];
  const recentCycles = data.recent_cycles || [];

  const fmtPnl = (v: number) => v >= 0 ? `+$${v.toLocaleString(undefined, { minimumFractionDigits: 0 })}` : `-$${Math.abs(v).toLocaleString(undefined, { minimumFractionDigits: 0 })}`;
  const pnlC = (v: number) => Math.abs(v) < 0.01 ? "text-white/50" : v > 0 ? "text-green-400" : "text-red-400";
  const fmtPct = (v: number) => `${(v * 100).toFixed(1)}%`;
  const fmtT = (s: string) => { if (!s) return "—"; try { return new Date(s).toLocaleString("en-GB", { hour12: false, month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit" }); } catch { return s; } };

  return (
    <div className="p-2 sm:p-4 mx-auto space-y-3 lg:pt-4 overflow-x-hidden w-full lg:max-w-[1440px]">
      <style>{`
        @keyframes slideUp { from { opacity:0; transform:translateY(14px); } to { opacity:1; transform:translateY(0); } }
        @keyframes fadeIn { from { opacity:0; } to { opacity:1; } }
        @keyframes barGrow { from { width:0; } }
        @keyframes pulse2 { 0%,100% { opacity:1; } 50% { opacity:0.5; } }
        @keyframes scanPulse { 0%,100% { box-shadow:0 0 6px rgba(0,210,210,0.15); } 50% { box-shadow:0 0 18px rgba(0,210,210,0.35); } }
        .anim-slide { animation: slideUp 0.45s ease forwards; }
        .anim-fade { animation: fadeIn 0.35s ease forwards; }
        .anim-bar { animation: barGrow 0.7s ease forwards; }
        .hover-row:hover { background: rgba(6,182,212,0.03); }
      `}</style>

      {/* ═══ HEADER ═══ */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 anim-slide">
        <div className="flex items-center gap-3 flex-wrap">
          <h1 className="text-base sm:text-lg font-bold text-bah-heading tracking-tight">Training Operations</h1>
          <span className="px-2.5 py-0.5 text-[10px] rounded-full font-bold border bg-bah-cyan/15 text-bah-cyan border-bah-cyan/40 tracking-wider">PAPER TRADING</span>
          <span className="text-[11px] text-bah-muted">{cs.universe_size || k.universe_size || 0} assets</span>
          <span style={{fontSize: "8px", color: "#666"}}>v2.1</span>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={() => { setSoundEnabled((s: boolean) => !s); if (!soundEnabled) playSignalSound(); }}
            className={`px-2 py-0.5 rounded text-[10px] font-bold border transition-all ${
              soundEnabled
                ? "bg-bah-cyan/10 border-bah-cyan/30 text-bah-cyan"
                : "bg-bah-surface border-bah-border text-bah-muted"
            }`}
            title={soundEnabled ? "Sound alerts ON — click to mute" : "Sound alerts OFF — click to enable"}
          >
            {soundEnabled ? "🔔" : "🔇"}
          </button>
          <span className="w-2 h-2 rounded-full bg-green-400 animate-pulse" />
          <span className="text-[10px] text-green-400 font-bold">LIVE</span>
        </div>
      </div>

      {/* ═══ LIVE CYCLE STATUS STRIP ═══ */}
      <CycleStatusStrip cs={cs} cycleTriggered={cycleTriggered} onRunCycle={async () => {
        const h: Record<string, string> = { ...(token ? { Authorization: `Bearer ${token}` } : {}) };
        try {
          const r = await fetch(`${apiBase()}/training/run-cycle`, { method: "POST", headers: h });
          if (r.ok) { setCycleTriggered(true); }
        } catch {}
      }} />

      {/* ═══ ALERTS ═══ */}
      {alerts.length > 0 && (
        <div className="space-y-1.5 anim-slide" style={{ animationDelay: "0.06s" }}>
          {alerts.map((a: any, i: number) => (
            <div key={i} className={`px-4 py-2 rounded-lg text-xs font-medium border ${a.level === "WARNING" ? "bg-amber-500/8 border-amber-500/25 text-amber-300" : "bg-bah-surface border-bah-border text-bah-muted"}`}>
              {a.level === "WARNING" ? "⚠️" : "ℹ️"} {a.message}
            </div>
          ))}
        </div>
      )}

      {/* ═══ KEY METRICS (matches Daily Operations style) ═══ */}
      <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-7 gap-2 anim-slide" style={{ animationDelay: "0.08s" }}>
        {(() => {
          const eq = k.equity || k.virtual_capital || 100000;
          const pnl = (k.net_pnl || 0) + (k.unrealized_pnl || 0);
          const ret = k.return_pct || 0;
          const wr = (k.win_rate || 0) * 100;
          return [
            { l: "Equity", v: `$${eq.toLocaleString(undefined,{maximumFractionDigits:0})}`, c: "text-bah-heading" },
            { l: "P&L", v: `${pnl>=0?"+":""}$${Math.abs(pnl).toLocaleString(undefined,{maximumFractionDigits:0})}`, c: pnl>=0?"text-green-400":"text-red-400" },
            { l: "Return", v: `${ret>=0?"+":""}${ret.toFixed(2)}%`, c: ret>=0?"text-green-400":"text-red-400" },
            { l: "Win Rate", v: `${wr.toFixed(1)}%`, c: wr>=60?"text-green-400":wr>=45?"text-amber-400":wr>0?"text-red-400":"text-bah-muted", sub: `${k.wins||0}W ${k.losses||0}L ${k.flat_trades||0}F` },
            { l: "Risk/Trade", v: `$${(k.risk_per_trade||500).toLocaleString()}`, c: "text-bah-cyan", sub: `${k.risk_per_trade_pct||0.5}%` },
            { l: "Open", v: `${k.open_positions||0}`, c: (k.open_positions||0)>0?"text-bah-cyan":"text-bah-muted", sub: `of ${k.universe_size||40}` },
            { l: "Closed", v: `${k.closed_trades||0}`, c: (k.closed_trades||0)>0?"text-green-400":"text-bah-muted", sub: `${(k.avg_duration_bars||0).toFixed(1)} avg bars` },
          ];
        })().map((m: any) => (
          <div key={m.l} className="bg-bah-surface border border-bah-border rounded-xl p-1.5 sm:p-2.5 text-center">
            <div className={`text-sm sm:text-lg font-bold font-mono ${m.c}`}>{m.v}</div>
            <div className="text-[8px] sm:text-[9px] text-bah-muted uppercase mt-0.5">{m.l}</div>
            {m.sub && <div className="text-[7px] sm:text-[8px] text-bah-muted/50 mt-0.5">{m.sub}</div>}
          </div>
        ))}
      </div>

      {/* ═══ OPEN POSITIONS ═══ */}
      {(data.positions || []).length > 0 && (
        <div className="anim-slide" style={{ animationDelay: "0.08s" }}>
          <div className="bg-bah-surface border border-bah-border rounded-xl overflow-hidden">
            <div className="px-4 py-3.5 flex items-center gap-3">
              <span className="text-sm font-bold text-bah-heading tracking-tight">📦 Open Positions</span>
              <span className="px-2.5 py-0.5 text-[11px] font-bold rounded-full bg-green-500/15 text-green-400 border border-green-500/30">{(data.positions || []).length}</span>
            </div>
            <div className="border-t border-bah-border overflow-x-auto">
              <table className="w-full text-[11px] min-w-[900px]">
                <thead><tr className="border-b border-bah-border text-[9px] text-bah-muted uppercase tracking-[0.1em] text-left">
                  <th className="px-3 py-2.5">Asset</th><th className="px-3 py-2.5">Strategy</th><th className="px-3 py-2.5">Dir</th>
                  <th className="px-3 py-2.5 text-right">Entry</th><th className="px-3 py-2.5 text-right">Current</th>
                  <th className="px-3 py-2.5 text-right">SL</th><th className="px-3 py-2.5 text-right">TP</th>
                  <th className="px-3 py-2.5 text-right">Risk</th><th className="px-3 py-2.5 text-right">Unreal P&L</th>
                  <th className="px-3 py-2.5">Bars</th>
                </tr></thead>
                <tbody>{(data.positions || []).map((p: any, i: number) => {
                  const unreal = p.unrealized_pnl || 0;
                  const fmtM = (v: number) => `$${Math.abs(v).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
                  return (
                    <tr key={i} className="border-b border-bah-border/50 hover:bg-bah-surface/50 transition-colors">
                      <td className="px-3 py-2.5"><div className="text-bah-heading font-bold">{p.asset}</div><div className="text-[9px] text-bah-muted">{p.asset_class}</div></td>
                      <td className="px-3 py-2.5 text-bah-text">{sn(p.strategy)}</td>
                      <td className="px-3 py-2.5"><span className={`font-bold ${p.direction === "LONG" ? "text-green-400" : "text-red-400"}`}>{p.direction}</span></td>
                      <td className="px-3 py-2.5 font-mono text-right text-bah-text">{fmtM(p.entry_price || 0)}</td>
                      <td className="px-3 py-2.5 font-mono text-right text-bah-heading">{fmtM(p.current_price || 0)}</td>
                      <td className="px-3 py-2.5 font-mono text-right text-red-400/60">{fmtM(p.stop_price || p.stop_loss || 0)}</td>
                      <td className="px-3 py-2.5 font-mono text-right text-green-400/60">{fmtM(p.tp_price || p.take_profit || 0)}</td>
                      <td className="px-3 py-2.5 font-mono text-right text-amber-400/70">{fmtM(p.risk_amount || 0)}</td>
                      <td className={`px-3 py-2.5 font-mono font-bold text-right ${unreal >= 0 ? "text-green-400" : "text-red-400"}`}>{`${unreal >= 0 ? "+" : "-"}$${Math.abs(unreal).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`}</td>
                      <td className="px-3 py-2.5 text-bah-muted text-center">{p.bars_held || 0}</td>
                    </tr>
                  );
                })}</tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {/* ═══ TRADE CANDIDATES ═══ */}
      <div className="anim-slide" style={{ animationDelay: "0.12s" }}>
        <CandidatesSection candidates={candidates} />
      </div>

      {/* ═══ EXECUTION DECISIONS ═══ */}
      {decisions && (decisions.execute?.length > 0 || decisions.watchlist?.length > 0) && (
        <div className="anim-slide" style={{ animationDelay: "0.15s" }}>
          <ExecutionDecisions decisions={decisions} />
        </div>
      )}

      {/* ═══ TABS ═══ */}
      <div className="flex border-b border-bah-border overflow-x-auto">
        {(["overview", "positions", "trades", "failed", "assets", "learning", "risk"] as const).map(t => (
          <button key={t} onClick={() => setTab(t)} className={`px-4 py-2.5 text-xs font-semibold border-b-2 transition-all whitespace-nowrap ${tab === t ? "border-bah-cyan text-bah-cyan" : "border-transparent text-bah-muted hover:text-bah-text"}`}>
            {t === "overview" ? "📊 Overview" : t === "positions" ? `📦 Positions (${k.open_positions || 0})` : t === "trades" ? `🔁 Trades (${k.closed_trades || 0})` : t === "failed" ? `🚫 Rejected (${failedSignals.length})` : t === "assets" ? `🌐 All Assets (${allAssets?.counts?.total || k.universe_size || 0})` : t === "learning" ? "🧬 Learning" : "⚖️ Risk"}
          </button>
        ))}
      </div>

      {/* ═══ TAB CONTENT ═══ */}
      <div className="anim-fade" key={tab}>
        {tab === "overview" && <OverviewTab strats={strats} classes={classes} rankings={rankings} cy={cy} recentCycles={recentCycles} fmtPnl={fmtPnl} fmtPct={fmtPct} fmtT={fmtT} pnlC={pnlC} />}
        {tab === "positions" && <PositionsTab positions={data.positions || []} fmtPnl={fmtPnl} pnlC={pnlC} />}
        {tab === "trades" && <TradesTab trades={data.closed_trades || []} fmtPnl={fmtPnl} pnlC={pnlC} fmtT={fmtT} />}
        {tab === "failed" && <FailedTab signals={failedSignals} />}
        {tab === "assets" && <AssetsTab data={allAssets} />}
        {tab === "learning" && <LearningTab learn={learn} adaptive={adaptive} token={token} />}
        {tab === "risk" && <RiskTab expo={expo} />}
      </div>
    </div>
  );
}

/* ═══════════════════════════════════════════
   CYCLE STATUS STRIP
   ═══════════════════════════════════════════ */
function CycleStatusStrip({ cs, onRunCycle, cycleTriggered }: { cs: any; onRunCycle: () => void; cycleTriggered: boolean }) {
  const nextCycle = useCountdown(cs.next_cycle_time);
  const next4H = useCountdown(cs.next_4h_bar_time);

  const hasRun = !!cs.last_cycle_time;
  const autoLabel = !cs.auto_enabled ? "OFF" : cs.is_running ? "SCANNING" : "ON";
  const autoClr = !cs.auto_enabled ? "text-red-400" : cs.is_running ? "text-bah-cyan" : "text-green-400";
  const autoDot = !cs.auto_enabled ? "bg-red-400" : cs.is_running ? "bg-bah-cyan" : "bg-green-400";

  const lastStatus = cs.last_cycle_status || cs.cycle_status;
  const sysStatus = cs.is_running ? "RUNNING" :
    lastStatus === "OK" ? "WAITING" :
    lastStatus === "DEGRADED" ? "DEGRADED" :
    lastStatus === "FAILED" ? "ERROR" : "WAITING";
  const sysClr = sysStatus === "WAITING" ? "text-green-400" :
    sysStatus === "RUNNING" ? "text-bah-cyan" :
    sysStatus === "DEGRADED" ? "text-amber-300" :
    sysStatus === "ERROR" ? "text-red-400" : "text-bah-muted";

  const nextCycleTime = cs.next_cycle_time ? new Date(cs.next_cycle_time).toLocaleTimeString("en-GB", { hour12: false, hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "";

  return (
    <div className={`rounded-xl border p-2 sm:p-3 flex flex-wrap items-center gap-x-3 sm:gap-x-5 gap-y-2 text-[10px] sm:text-[11px] anim-slide ${cs.is_running ? "bg-bah-cyan/[0.04] border-bah-cyan/25" : "bg-bah-surface border-bah-border"}`} style={{ animationDelay: "0.03s", ...(cs.is_running ? { animation: "scanPulse 2.5s ease-in-out infinite" } : {}) }}>

      {/* Auto Training */}
      <div className="flex items-center gap-2">
        <span className={`w-2.5 h-2.5 rounded-full ${autoDot} ${cs.is_running ? "animate-pulse" : ""}`} />
        <span className="text-[11px] font-bold text-bah-text uppercase tracking-wider">Auto Training</span>
        <span className={`text-[11px] font-extrabold ${autoClr}`}>{autoLabel}</span>
      </div>

      {cs.is_running && (
        <div className="flex items-center gap-2">
          <div className="w-20 h-1.5 bg-bah-border rounded-full overflow-hidden">
            <div className="h-full bg-bah-cyan rounded-full transition-all duration-500" style={{ width: `${cs.running_progress ? (cs.running_progress.current / Math.max(1, cs.running_progress.total)) * 100 : 0}%` }} />
          </div>
          <span className="text-[10px] text-bah-cyan font-bold font-mono">{cs.running_progress?.current || 0}/{cs.running_progress?.total || cs.universe_size || 40}</span>
        </div>
      )}

      <div className="hidden sm:block w-px h-5 bg-bah-border" />

      <div className="flex items-center gap-1.5">
        <span className="text-[10px] text-bah-muted uppercase tracking-wider">Status</span>
        <span className={`text-[11px] font-bold ${sysClr}`}>{sysStatus}</span>
      </div>

      <div className="hidden sm:block w-px h-5 bg-bah-border" />

      <div className="flex items-center gap-1.5">
        <span className="text-[10px] text-bah-muted uppercase tracking-wider">Next cycle</span>
        <span className={`text-[13px] font-bold font-mono tabular-nums ${
          cs.is_running ? "text-bah-cyan" :
          nextCycle !== null && nextCycle <= 0 ? "text-red-400" :
          nextCycle !== null && nextCycle < 60 ? "text-bah-cyan" :
          "text-bah-heading"
        }`}>
          {cs.is_running ? "NOW" : nextCycle !== null && nextCycle <= 0 ? "OVERDUE" : fmtCountdown(nextCycle)}
        </span>
        {nextCycleTime && !cs.is_running && nextCycle !== null && nextCycle > 0 && (
          <span className="text-[10px] text-bah-muted font-mono">({nextCycleTime})</span>
        )}
      </div>

      <div className="hidden sm:block w-px h-5 bg-bah-border" />

      <div className="flex items-center gap-1.5">
        <span className="text-[10px] text-bah-muted uppercase tracking-wider">Next 4H bar</span>
        <span className="text-[13px] font-bold font-mono tabular-nums text-bah-heading">{fmtCountdown(next4H)}</span>
      </div>

      <div className="hidden sm:block w-px h-5 bg-bah-border" />

      {/* ── Run Cycle Button ── */}
      <button
        onClick={onRunCycle}
        disabled={cs.is_running || cycleTriggered}
        className={`px-3 py-1 rounded-lg text-[10px] font-bold uppercase tracking-wider border transition-all ${
          cs.is_running
            ? "bg-bah-cyan/15 border-bah-cyan/40 text-bah-cyan animate-pulse cursor-wait"
            : cycleTriggered
            ? "bg-amber-500/10 border-amber-500/30 text-amber-300 cursor-wait"
            : "bg-bah-cyan/10 border-bah-cyan/30 text-bah-cyan hover:bg-bah-cyan/20 hover:border-bah-cyan/50 active:scale-95"
        }`}
      >
        {cs.is_running ? "⏳ Running…" : cycleTriggered ? "⏳ Starting…" : "▶ Run Cycle"}
      </button>

      <div className="flex items-center gap-2 text-[10px] text-bah-muted font-mono">
        <span>every {(cs.cycle_interval_seconds || 600) / 60}m</span>
        {cs.last_cycle_time && (
          <>
            <span className="text-bah-muted/40">·</span>
            <span>last: {new Date(cs.last_cycle_time).toLocaleTimeString("en-GB", { hour12: false })}</span>
            {cs.last_cycle_status && (
              <span className={cs.last_cycle_status === "OK" ? "text-green-400/60" : cs.last_cycle_status === "DEGRADED" ? "text-amber-300/60" : "text-red-400/60"}>
                {cs.last_cycle_status}
              </span>
            )}
            {cs.last_cycle_duration_ms != null && (
              <span className="text-bah-muted/60">{cs.last_cycle_duration_ms}ms</span>
            )}
          </>
        )}
        {!cs.last_cycle_time && <span className="text-bah-muted/60">awaiting first cycle</span>}
      </div>
    </div>
  );
}

/* ═══════════════════════════════════════════
   TRADE CANDIDATES (upgraded)
   ═══════════════════════════════════════════ */
function CandidatesSection({ candidates }: { candidates: any[] }) {
  const [expanded, setExpanded] = useState(false);
  const THRESHOLD = 80;

  const urgency = (s: number) => s >= THRESHOLD ? { label: "READY", cls: "bg-green-500/25 text-green-400 border-green-500/40" } :
    s >= 60 ? { label: "APPROACHING", cls: "bg-amber-500/20 text-amber-300 border-amber-500/40" } :
    { label: "WEAK", cls: "", style: {color: "rgba(255,255,255,0.5)", background: "rgba(255,255,255,0.05)", border: "1px solid rgba(255,255,255,0.1)"} };

  const scoreBg = (s: number) => s >= THRESHOLD ? "bg-green-400" : s >= 60 ? "bg-amber-400" : s >= 40 ? "bg-bah-cyan" : "bg-bah-border";

  const aboveThreshold = candidates.filter(c => c.score >= THRESHOLD).length;

  if (!candidates || candidates.length === 0) {
    return (
      <div className="bg-bah-surface border border-bah-border rounded-xl p-5">
        <div className="flex items-center gap-3 mb-3">
          <span className="text-sm font-bold text-bah-heading tracking-tight">🔥 Trade Candidates</span>
          <span className="text-[10px] text-bah-muted">read-only intelligence</span>
        </div>
        <div className="flex items-start gap-3">
          <span className="text-xl mt-0.5">📡</span>
          <div>
            <p className="text-xs text-bah-muted font-medium mb-1">All candidates below execution threshold (score ≥ {THRESHOLD})</p>
            <p className="text-[11px] text-bah-muted">The scanner evaluates 40+ assets against EMA cross and breakout strategies every 10 minutes. Candidates appear when price action converges on trigger conditions. The next opportunity may come at the next 4H bar boundary.</p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="bg-bah-surface border border-bah-border rounded-xl overflow-hidden">
      <div className="px-4 py-3.5 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span className="text-sm font-bold text-bah-heading tracking-tight">🔥 Trade Candidates</span>
          <span className="px-2.5 py-0.5 text-[11px] font-bold rounded-full bg-bah-cyan/15 text-bah-cyan border border-bah-cyan/30">{candidates.length}</span>
          {aboveThreshold > 0 && (
            <span className="px-2 py-0.5 text-[10px] font-bold rounded bg-green-500/20 text-green-400 border border-green-500/35">{aboveThreshold} READY (≥{THRESHOLD})</span>
          )}
          <span className="text-[10px] text-bah-muted hidden sm:inline">execution threshold: {THRESHOLD}</span>
        </div>
      </div>

      <div className="border-t border-bah-border overflow-x-auto">
          <table className="w-full text-[11px] min-w-[1000px]">
            <thead>
              <tr className="border-b border-bah-border text-left text-[9px] text-bah-muted uppercase tracking-[0.1em]">
                <th className="px-3 py-2.5 w-[130px]">Score</th><th className="px-3 py-2.5">Asset</th><th className="px-3 py-2.5">Strategy</th>
                <th className="px-3 py-2.5">Dir</th><th className="px-3 py-2.5">Regime</th><th className="px-3 py-2.5">Distance</th>
                <th className="px-3 py-2.5">RSI</th><th className="px-3 py-2.5">EMAs</th><th className="px-3 py-2.5">Setup</th>
              </tr>
            </thead>
            <tbody>
              {(expanded ? candidates : candidates.slice(0, 5)).map((c: any, i: number) => {
                const u = urgency(c.score);
                const isTop = i === 0;
                const isAbove = c.score >= THRESHOLD;
                return (
                  <tr key={i} className={`border-b border-bah-border/50 hover:bg-bah-surface/50 transition-colors anim-slide ${isTop ? "bg-bah-cyan/[0.04]" : isAbove ? "bg-bah-surface/50" : ""}`} style={{ animationDelay: `${i * 0.035}s` }}>
                    <td className="px-3 py-2.5">
                      <div className="flex items-center gap-2">
                        <div className="w-12 h-2 rounded-full overflow-hidden" style={{background: "rgba(255,255,255,0.1)"}}>
                          <div className={`h-full rounded-full anim-bar ${scoreBg(c.score)}`} style={{ width: `${c.score}%`, animationDelay: `${0.2 + i * 0.04}s` }} />
                        </div>
                        <span style={{color: "white", fontWeight: 700, fontSize: "12px", minWidth: "24px", textAlign: "center" as const}}>{c.score}</span>
                      </div>
                    </td>
                    <td className="px-3 py-2.5">
                      <div className="flex items-center gap-2">
                        <span style={{color: isTop ? "#00d2d2" : "white", fontWeight: 700}}>{c.asset}</span>
                        <span className={`px-1.5 py-0 text-[8px] font-bold rounded border tracking-wider ${u.cls}`} style={(u as any).style || {}}>{u.label}</span>
                      </div>
                      <div style={{fontSize: "9px", color: "rgba(255,255,255,0.4)", marginTop: "2px"}}>{c.asset_class}</div>
                    </td>
                    <td className="px-3 py-2.5" style={{color: "white", fontWeight: 500}}>{sn(c.strategy)}</td>
                    <td className="px-3 py-2.5"><span style={{color: c.direction === "LONG" ? "#4ade80" : "#f87171", fontWeight: 700}}>{c.direction}</span></td>
                    <td className="px-3 py-2.5">
                      <span style={{
                        color: (c.regime === "TREND" || c.regime === "BREAKOUT") ? "#4ade80" : (c.regime === "BEAR" || c.regime === "CRASH") ? "#f87171" : "#fcd34d",
                        fontWeight: 700, fontSize: "12px"
                      }}>{c.regime}</span>
                    </td>
                    <td className="px-3 py-2.5" style={{color: "white", fontSize: "10px", fontFamily: "monospace"}}>{c.distance_to_trigger}</td>
                    <td className="px-3 py-2.5" style={{fontFamily: "monospace"}}><span style={{color: (c.indicators?.rsi < 30) ? "#4ade80" : (c.indicators?.rsi > 70) ? "#f87171" : "white", fontWeight: 700}}>{c.indicators?.rsi?.toFixed(0) || "—"}</span></td>
                    <td className="px-3 py-2.5">
                      <span style={{
                        color: c.indicators?.ema_alignment?.includes("bullish") ? "#4ade80" : c.indicators?.ema_alignment?.includes("bearish") ? "#f87171" : "rgba(255,255,255,0.7)",
                        fontSize: "10px", fontWeight: 700
                      }}>{c.indicators?.ema_alignment?.replace("_", " ") || "—"}</span>
                    </td>
                    <td className="px-3 py-2.5" style={{maxWidth: "260px"}}>
                      {(c.reasons || []).slice(0, 3).map((r: string, j: number) => (
                        <div key={j} style={{fontSize: "10px", color: "rgba(255,255,255,0.6)", lineHeight: 1.4}}>{r}</div>
                      ))}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        {candidates.length > 5 && (
          <button onClick={() => setExpanded(!expanded)}
            className="w-full py-2.5 text-[11px] font-bold text-bah-cyan hover:bg-bah-cyan/5 border-t border-bah-border transition-all flex items-center justify-center gap-1.5">
            {expanded ? '▲ Show Less' : `▼ Show All ${candidates.length} Candidates`}
          </button>
        )}
    </div>
  );
}

/* ═══════════════════════════════════════════
   OVERVIEW TAB
   ═══════════════════════════════════════════ */
function OverviewTab({ strats, classes, rankings, cy, recentCycles, fmtPnl, fmtPct, fmtT, pnlC }: any) {
  const stratName: Record<string, string> = {
    v5_base: "S1 · EMA Trend",
    v5_tuned: "S2 · EMA Tuned",
    v9_breakout: "S3 · Breakout",
    v10_mean_reversion: "S4 · Mean Reversion",
  };
  return (
    <div className="space-y-4">
      <Section title="Cycle Health">
        <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
          <Stat l="Processed" v={cy.assets_processed} /><Stat l="Skipped" v={cy.assets_skipped} />
          <Stat l="Errors" v={cy.errors} c={cy.errors > 0 ? "text-red-400" : ""} /><Stat l="Signals" v={cy.signals_generated} /><Stat l="Opened" v={cy.trades_opened || 0} c={cy.trades_opened > 0 ? "text-green-400" : ""} />
        </div>
      </Section>

      {/* Recent Cycles */}
      {recentCycles.length > 0 && (
        <Section title="Recent Cycles">
          <div className="overflow-x-auto">
            <table className="w-full text-[11px]">
              <thead><tr className="border-b border-bah-border text-[9px] text-bah-muted uppercase tracking-wider text-left">
                <th className="py-2 pr-3">Time</th><th className="py-2 pr-3">Status</th><th className="py-2 pr-3">Processed</th><th className="py-2 pr-3">Errors</th><th className="py-2 pr-3">Signals</th><th className="py-2 pr-3">Selected</th><th className="py-2 pr-3">Opened</th><th className="py-2 pr-3">Closed</th><th className="py-2 pr-3">Duration</th>
              </tr></thead>
              <tbody>
                {recentCycles.slice(0, 7).map((c: any, i: number) => (
                  <tr key={i} className="border-b border-bah-border hover-row">
                    <td className="py-1.5 pr-3 text-bah-muted font-mono">{fmtT(c.last_cycle)}</td>
                    <td className="py-1.5 pr-3"><span className={`text-[9px] font-bold px-1.5 py-0.5 rounded border ${c.status === "OK" ? "bg-green-500/15 text-green-400 border-green-500/25" : c.status === "DEGRADED" ? "bg-amber-500/15 text-amber-300 border-amber-500/25" : "bg-red-500/15 text-red-300 border-red-500/25"}`}>{c.status}</span></td>
                    <td className="py-1.5 pr-3 text-bah-text">{c.processed}</td>
                    <td className="py-1.5 pr-3 text-bah-text">{c.errors}</td>
                    <td className="py-1.5 pr-3 text-bah-text">{c.signals}</td>
                    <td className="py-1.5 pr-3 text-bah-text">{c.selected || 0}</td>
                    <td className={`py-1.5 pr-3 font-bold ${c.trades_opened > 0 ? "text-green-400" : "text-bah-text"}`}>{c.trades_opened || 0}</td>
                    <td className="py-1.5 pr-3 text-bah-text">{c.trades_closed}</td>
                    <td className="py-1.5 pr-3 text-bah-muted font-mono">{c.duration_ms}ms</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Section>
      )}

      <Section title="Strategy Breakdown">
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead><tr className="border-b border-bah-border text-[9px] text-bah-muted uppercase tracking-wider text-left">
              <th className="py-2.5 pr-3">Strategy</th><th className="py-2.5 pr-3">Open</th><th className="py-2.5 pr-3">Closed</th>
              <th className="py-2.5 pr-3">WR</th><th className="py-2.5 pr-3">PF</th><th className="py-2.5 pr-3">PnL</th>
              <th className="py-2.5 pr-3">Avg Bars</th><th className="py-2.5">Status</th>
            </tr></thead>
            <tbody>
              {Object.entries(strats).map(([name, s]: [string, any]) => (
                <tr key={name} className="border-b border-bah-border hover-row">
                  <td className="py-2.5 pr-3 text-bah-heading font-semibold">{stratName[name] || name} <span className="text-[8px] text-bah-muted font-normal">{name}</span></td>
                  <td className="py-2.5 pr-3 text-bah-text">{s.open_trades}</td>
                  <td className="py-2.5 pr-3 text-bah-text">{s.closed_trades}</td>
                  <td className="py-2.5 pr-3 text-bah-heading">{fmtPct(s.win_rate)}</td>
                  <td className="py-2.5 pr-3 text-bah-heading">{s.profit_factor.toFixed(2)}</td>
                  <td className={`py-2.5 pr-3 font-bold ${pnlC(s.total_pnl)}`}>{fmtPnl(s.total_pnl)}</td>
                  <td className="py-2.5 pr-3 text-bah-muted">{s.avg_hold_bars?.toFixed(1)}</td>
                  <td className="py-2.5"><span className={`px-2 py-0.5 rounded text-[9px] font-bold border ${s.provisional ? "bg-amber-500/15 text-amber-300 border-amber-500/25" : "bg-green-500/15 text-green-400 border-green-500/25"}`}>{s.provisional ? "WARMING" : "ACTIVE"}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Section>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Section title="Asset Class Breakdown">
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
            {Object.entries(classes).map(([cls, s]: [string, any], i) => (
              <div key={cls} className="bg-bah-surface border border-bah-border rounded-lg p-3 anim-slide" style={{ animationDelay: `${i * 0.04}s` }}>
                <div className="text-[9px] text-bah-muted uppercase tracking-wider font-bold mb-1">{cls}</div>
                <div className="text-xs text-bah-heading font-semibold">{s.closed_trades} closed · {s.open_trades} open</div>
                <div className={`text-[11px] font-bold mt-0.5 ${pnlC(s.pnl)}`}>{fmtPnl(s.pnl)} · {fmtPct(s.win_rate)} WR</div>
              </div>
            ))}
          </div>
        </Section>

        <div className="space-y-4">
          {rankings.best?.length > 0 && <Section title="🏆 Best Assets">{rankings.best.map((a: any, i: number) => (
            <div key={i} className="flex justify-between items-center py-2 text-xs border-b border-bah-border hover-row px-1 rounded">
              <div><span className="text-bah-heading font-semibold">{a.asset}</span> <span className="text-bah-muted ml-1 text-[10px]">{a.class}</span></div>
              <div className="text-green-400 font-bold">{fmtPnl(a.pnl)} <span className="text-bah-muted font-normal">({a.trades}t)</span></div>
            </div>
          ))}</Section>}
          {rankings.worst?.length > 0 && <Section title="⚠️ Worst Assets">{rankings.worst.map((a: any, i: number) => (
            <div key={i} className="flex justify-between items-center py-2 text-xs border-b border-bah-border hover-row px-1 rounded">
              <div><span className="text-bah-heading font-semibold">{a.asset}</span> <span className="text-bah-muted ml-1 text-[10px]">{a.class}</span></div>
              <div className="text-red-400 font-bold">{fmtPnl(a.pnl)} <span className="text-bah-muted font-normal">({a.trades}t)</span></div>
            </div>
          ))}</Section>}
        </div>
      </div>
    </div>
  );
}

/* ═══════════════════════════════════════════
   POSITIONS TAB
   ═══════════════════════════════════════════ */
function PositionsTab({ positions, fmtPnl, pnlC }: any) {
  const fmtMoney = (v: number) => `$${Math.abs(v).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  const fmtSize = (v: number) => v >= 1 ? v.toFixed(4) : v.toFixed(6);
  return (
    <Section title={`Open Positions (${positions.length})`}>
      {positions.length > 0 ? (
        <div className="overflow-x-auto"><table className="w-full text-[11px] min-w-[1000px]">
          <thead><tr className="border-b border-bah-border text-[9px] text-bah-muted uppercase tracking-wider text-left">
            <th className="py-2.5 pr-2">Asset</th><th className="py-2.5 pr-2">Strategy</th>
            <th className="py-2.5 pr-2">Dir</th><th className="py-2.5 pr-2">Type</th>
            <th className="py-2.5 pr-2 text-right">Entry</th><th className="py-2.5 pr-2 text-right">Current</th>
            <th className="py-2.5 pr-2 text-right">SL</th><th className="py-2.5 pr-2 text-right">TP</th>
            <th className="py-2.5 pr-2 text-right">Size</th><th className="py-2.5 pr-2 text-right">Risk</th>
            <th className="py-2.5 pr-2 text-right">Value</th>
            <th className="py-2.5 pr-2 text-right">Unreal P&L</th><th className="py-2.5">Bars</th>
            <th className="py-2.5">Opened</th>
          </tr></thead>
          <tbody>{positions.map((p: any, i: number) => {
            const unreal = p.unrealized_pnl || 0;
            const value = (p.size || 0) * (p.current_price || p.entry_price || 0);
            return (
              <tr key={i} className="border-b border-bah-border/50 hover:bg-bah-surface/50 transition-colors">
                <td className="py-2.5 pr-2">
                  <div className="text-bah-heading font-bold">{p.asset}</div>
                  <div className="text-[9px] text-bah-muted">{p.asset_class}</div>
                </td>
                <td className="py-2.5 pr-2 text-bah-text">{sn(p.strategy)}</td>
                <td className="py-2.5 pr-2"><span className={`font-bold ${p.direction === "LONG" ? "text-green-400" : "text-red-400"}`}>{p.direction}</span></td>
                <td className="py-2.5 pr-2"><ExecBadge type={p.execution_type} /></td>
                <td className="py-2.5 pr-2 font-mono text-right text-bah-text">{fmtMoney(p.entry_price || 0)}</td>
                <td className="py-2.5 pr-2 font-mono text-right text-bah-heading">{fmtMoney(p.current_price || 0)}</td>
                <td className="py-2.5 pr-2 font-mono text-right text-red-400/60">{fmtMoney(p.stop_price || p.stop_loss || 0)}</td>
                <td className="py-2.5 pr-2 font-mono text-right text-green-400/60">{fmtMoney(p.tp_price || p.take_profit || 0)}</td>
                <td className="py-2.5 pr-2 font-mono text-right text-bah-muted">{fmtSize(p.size || 0)}</td>
                <td className="py-2.5 pr-2 font-mono text-right text-amber-400/70">{fmtMoney(p.risk_amount || 0)}</td>
                <td className="py-2.5 pr-2 font-mono text-right text-bah-text">{fmtMoney(value)}</td>
                <td className={`py-2.5 pr-2 font-mono font-bold text-right ${pnlC(unreal)}`}>{fmtPnl(unreal)}</td>
                <td className="py-2.5 text-bah-muted text-center">{p.bars_held || 0}</td>
                <td className="py-2.5 text-bah-muted text-[10px]">{p.entry_time ? new Date(p.entry_time).toLocaleString("en-GB", { hour12: false, month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "—"}</td>
              </tr>
            );
          })}</tbody>
        </table></div>
      ) : <div className="text-center py-10 text-bah-muted text-sm">No open positions. Signals trigger at 4H bar boundaries when strategy conditions are met.</div>}
    </Section>
  );
}

/* ═══════════════════════════════════════════
   TRADES TAB
   ═══════════════════════════════════════════ */
function TradesTab({ trades, fmtPnl, pnlC, fmtT }: any) {
  const fmtMoney = (v: number) => `$${Math.abs(v).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  return (
    <Section title={`Closed Trades (${trades.length})`}>
      {trades.length > 0 ? (
        <div className="overflow-x-auto"><table className="w-full text-[11px] min-w-[1100px]">
          <thead><tr className="border-b border-bah-border text-[9px] text-bah-muted uppercase tracking-wider text-left">
            <th className="py-2.5 pr-2">Asset</th><th className="py-2.5 pr-2">Strategy</th><th className="py-2.5 pr-2">Dir</th>
            <th className="py-2.5 pr-2 text-right">Entry</th><th className="py-2.5 pr-2 text-right">Exit</th>
            <th className="py-2.5 pr-2 text-right">Risk</th><th className="py-2.5 pr-2 text-right">P&L</th>
            <th className="py-2.5 pr-2 text-right">R-Mult</th>
            <th className="py-2.5 pr-2">Result</th><th className="py-2.5 pr-2">Reason</th>
            <th className="py-2.5 pr-2 text-center">Bars</th><th className="py-2.5 pr-2">Opened</th><th className="py-2.5">Closed</th>
          </tr></thead>
          <tbody>{trades.map((t: any, i: number) => {
            const pnl = t.pnl || 0;
            const risk = t.risk_amount || 0;
            const rMult = risk > 0 ? pnl / risk : 0;
            const isWin = pnl > 0.01;
            const isFlat = Math.abs(pnl) < 0.01;
            const resultLabel = isFlat ? "FLAT" : isWin ? "WIN" : "LOSS";
            const resultCls = isFlat ? "bg-white/10 text-white/50 border border-white/15" : isWin ? "bg-green-500/15 text-green-400 border border-green-500/25" : "bg-red-500/15 text-red-400 border border-red-500/25";
            return (
              <tr key={i} className="border-b border-bah-border/50 hover:bg-bah-surface/50 transition-colors">
                <td className="py-2.5 pr-2">
                  <div className="text-bah-heading font-bold">{t.asset}</div>
                  <div className="text-[9px] text-bah-muted">{t.asset_class || ""}</div>
                </td>
                <td className="py-2.5 pr-2 text-bah-text">{sn(t.strategy)}</td>
                <td className="py-2.5 pr-2"><span className={`font-bold ${t.direction === "LONG" ? "text-green-400" : "text-red-400"}`}>{t.direction}</span></td>
                <td className="py-2.5 pr-2 font-mono text-right text-bah-text">{fmtMoney(t.entry_price || 0)}</td>
                <td className="py-2.5 pr-2 font-mono text-right text-bah-text">{fmtMoney(t.exit_price || 0)}</td>
                <td className="py-2.5 pr-2 font-mono text-right text-amber-400/70">{fmtMoney(risk)}</td>
                <td className={`py-2.5 pr-2 font-mono font-bold text-right ${pnlC(pnl)}`}>{pnl >= 0 ? "+" : "-"}{fmtMoney(pnl)}</td>
                <td className={`py-2.5 pr-2 font-mono font-bold text-right ${pnlC(pnl)}`}>{rMult >= 0 ? "+" : ""}{rMult.toFixed(1)}R</td>
                <td className="py-2.5 pr-2">
                  <span className={`px-2 py-0.5 rounded text-[9px] font-bold ${resultCls}`}>
                    {resultLabel}
                  </span>
                </td>
                <td className="py-2.5 pr-2">
                  <span className={`px-1.5 py-0.5 rounded text-[9px] font-bold ${
                    t.exit_reason === "TP" ? "bg-green-500/10 text-green-400" :
                    t.exit_reason === "SL" ? "bg-red-500/10 text-red-400" :
                    "bg-bah-surface text-bah-muted"
                  }`}>{t.exit_reason}</span>
                </td>
                <td className="py-2.5 pr-2 text-bah-muted text-center">{t.bars_held}</td>
                <td className="py-2.5 pr-2 text-bah-muted text-[10px]">{fmtT(t.entry_time)}</td>
                <td className="py-2.5 text-bah-muted text-[10px]">{fmtT(t.exit_time)}</td>
              </tr>
            );
          })}</tbody>
        </table></div>
      ) : <div className="text-center py-10 text-bah-muted text-sm">No closed trades yet. First closes happen after SL/TP/timeout on open positions.</div>}
    </Section>
  );
}

/* ═══════════════════════════════════════════
   FAILED SIGNALS TAB
   ═══════════════════════════════════════════ */
function FailedTab({ signals }: { signals: any[] }) {
  const [expanded, setExpanded] = useState<Set<number>>(new Set());
  const toggle = (i: number) => setExpanded((prev: Set<number>) => { const s = new Set(prev); s.has(i) ? s.delete(i) : s.add(i); return s; });

  const fmtT = (iso: string) => { if (!iso) return "—"; try { return new Date(iso).toLocaleString("en-GB", { hour12: false, month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }); } catch { return iso; } };

  const groupClr: Record<string, string> = {
    REJECT: "bg-red-500/15 text-red-300 border-red-500/30",
    BLOCKED: "bg-red-500/15 text-red-300 border-red-500/30",
    WATCHLIST: "bg-amber-500/15 text-amber-300 border-amber-500/30",
  };
  const gateClr: Record<string, string> = {
    SIGNAL_LABEL: "text-amber-300",
    "SIGNAL_LABEL+EXPLORATION": "text-amber-300",
    DISAGREEMENT: "text-red-400",
    EXECUTION_POLICY: "text-red-300",
    PORTFOLIO: "text-orange-300",
    SCORE: "text-amber-200",
    REGIME: "text-red-400",
  };

  // Separate training (rejected/watchlist) from production (blocked)
  const training = signals.filter(s => s.source === "training");
  const production = signals.filter(s => s.source === "production");

  return (
    <div className="space-y-4">
      {/* Summary counts */}
      <div className="flex gap-3 items-center">
        <span className="text-sm font-bold text-bah-heading">Rejected Signals</span>
        {training.length > 0 && <span className="px-2 py-0.5 text-[10px] font-bold rounded bg-amber-500/15 text-amber-300 border border-amber-500/30">{training.length} Training</span>}
        {production.length > 0 && <span className="px-2 py-0.5 text-[10px] font-bold rounded bg-red-500/15 text-red-300 border border-red-500/30">{production.length} Production</span>}
        {signals.length === 0 && <span className="text-xs text-bah-muted">No rejected signals in current window</span>}
      </div>

      {/* Production rejected signals */}
      {production.length > 0 && (
        <Section title={`Production Blocked (${production.length})`}>
          <div className="space-y-1">
            {production.map((s: any, i: number) => {
              const idx = i;
              const isOpen = expanded.has(idx);
              return (
                <div key={idx}>
                  <button onClick={() => toggle(idx)} className="w-full flex items-center gap-3 px-3 py-2 rounded-lg border border-bah-border bg-bah-surface hover:bg-bah-surface transition-colors text-left cursor-pointer">
                    <span className={`px-2 py-0.5 text-[9px] font-bold rounded border shrink-0 ${groupClr[s._group] || groupClr.BLOCKED}`}>{s._group}</span>
                    <span className="text-xs text-bah-heading font-bold w-[70px] shrink-0">{s.asset}</span>
                    <span className={`text-[10px] font-bold w-[40px] shrink-0 ${s.direction === "LONG" ? "text-green-400" : "text-red-400"}`}>{s.direction}</span>
                    <span className="text-[10px] text-bah-muted w-[35px] shrink-0 text-center font-mono">{typeof s.score === "number" ? (s.score * 100).toFixed(0) : s.score}</span>
                    <span className="text-[10px] text-bah-muted w-[65px] shrink-0">{s.label}</span>
                    <span className="text-[10px] text-bah-muted flex-1 truncate">{s.reason}</span>
                    <span className="text-[10px] text-bah-muted/60 w-[100px] shrink-0 text-right">{fmtT(s.timestamp)}</span>
                    <span className="text-[10px] text-bah-muted/60 shrink-0">{isOpen ? "▼" : "▶"}</span>
                  </button>
                  {isOpen && (
                    <div className="ml-6 mt-1 mb-2 p-3 rounded-lg bg-black/30 border border-bah-border space-y-1.5 text-[10px] font-mono">
                      <div className="text-bah-muted uppercase text-[8px] tracking-widest font-bold mb-2">Rejection Trace</div>
                      <div className="flex gap-2"><span className="text-bah-muted w-[60px] shrink-0">Asset</span><span className="text-bah-heading">{s.asset}</span></div>
                      <div className="flex gap-2"><span className="text-bah-muted w-[60px] shrink-0">Direction</span><span className={s.direction === "LONG" ? "text-green-400" : "text-red-400"}>{s.direction}</span></div>
                      <div className="flex gap-2"><span className="text-bah-muted w-[60px] shrink-0">Score</span><span className="text-bah-heading">{typeof s.score === "number" ? s.score.toFixed(4) : s.score}</span></div>
                      <div className="flex gap-2"><span className="text-bah-muted w-[60px] shrink-0">Label</span><span className="text-bah-heading">{s.label}</span></div>
                      <div className="flex gap-2"><span className="text-bah-muted w-[60px] shrink-0">Regime</span><span className="text-bah-heading">{s.regime}</span></div>
                      <div className="flex gap-2"><span className="text-bah-muted w-[60px] shrink-0">Gate</span><span className={gateClr[s.gate] || "text-bah-heading"}>{s.gate || "—"}</span></div>
                      <div className="flex gap-2"><span className="text-bah-muted w-[60px] shrink-0">Mode</span><span className="text-bah-heading">{s.mode}</span></div>
                      <div className="border-t border-bah-border pt-1.5 mt-1">
                        <span className="text-bah-muted">Reason:</span>
                        <span className="text-red-300 ml-2">{s.reason}</span>
                      </div>
                      {s.blockers && s.blockers.length > 0 && (
                        <div className="border-t border-bah-border pt-1.5 mt-1">
                          <div className="text-bah-muted mb-1">Blockers:</div>
                          {s.blockers.map((b: string, bi: number) => (
                            <div key={bi} className="text-red-400/80 pl-3">• {b}</div>
                          ))}
                        </div>
                      )}
                      <div className="flex gap-2 pt-1 text-bah-muted/60"><span className="w-[60px] shrink-0">Time</span><span>{s.timestamp}</span></div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </Section>
      )}

      {/* Training rejected/watchlisted signals */}
      {training.length > 0 && (
        <Section title={`Training Rejected / Watchlisted (${training.length})`}>
          <div className="space-y-1">
            {training.map((s: any, i: number) => {
              const idx = production.length + i;
              const isOpen = expanded.has(idx);
              return (
                <div key={idx}>
                  <button onClick={() => toggle(idx)} className="w-full flex items-center gap-3 px-3 py-2 rounded-lg border border-bah-border bg-bah-surface hover:bg-bah-surface transition-colors text-left cursor-pointer">
                    <span className={`px-2 py-0.5 text-[9px] font-bold rounded border shrink-0 ${groupClr[s._group] || groupClr.REJECT}`}>{s._group}</span>
                    <span className="text-xs text-bah-heading font-bold w-[70px] shrink-0">{s.asset}</span>
                    <span className="text-[10px] text-bah-muted w-[55px] shrink-0">{sn(s.strategy)}</span>
                    <span className={`text-[10px] font-bold w-[40px] shrink-0 ${s.direction === "LONG" ? "text-green-400" : "text-red-400"}`}>{s.direction}</span>
                    <span className="text-[10px] text-bah-muted w-[30px] shrink-0 text-center">{s.readiness_score}</span>
                    <span className="text-[10px] text-bah-muted flex-1 truncate">{(s.reasons || []).join(" · ")}</span>
                    <span className="text-[10px] text-bah-muted/60 shrink-0">{isOpen ? "▼" : "▶"}</span>
                  </button>
                  {isOpen && (
                    <div className="ml-6 mt-1 mb-2 p-3 rounded-lg bg-black/30 border border-bah-border space-y-1.5 text-[10px] font-mono">
                      <div className="text-bah-muted uppercase text-[8px] tracking-widest font-bold mb-2">Decision Trace</div>
                      <div className="flex gap-2"><span className="text-bah-muted w-[70px] shrink-0">Asset</span><span className="text-bah-heading">{s.asset} ({s.asset_class})</span></div>
                      <div className="flex gap-2"><span className="text-bah-muted w-[70px] shrink-0">Strategy</span><span className="text-bah-heading">{sn(s.strategy)}</span></div>
                      <div className="flex gap-2"><span className="text-bah-muted w-[70px] shrink-0">Direction</span><span className={s.direction === "LONG" ? "text-green-400" : "text-red-400"}>{s.direction}</span></div>
                      <div className="flex gap-2"><span className="text-bah-muted w-[70px] shrink-0">Readiness</span><span className="text-bah-heading">{s.readiness_score}/100</span></div>
                      <div className="flex gap-2"><span className="text-bah-muted w-[70px] shrink-0">Priority</span><span className="text-bah-heading">{s.priority_score}</span></div>
                      <div className="flex gap-2"><span className="text-bah-muted w-[70px] shrink-0">Regime</span><span className="text-bah-heading">{s.regime}</span></div>
                      <div className="flex gap-2"><span className="text-bah-muted w-[70px] shrink-0">Decision</span><span className={s.decision === "REJECT" ? "text-red-400" : "text-amber-300"}>{s.decision}</span></div>
                      {s.priority_breakdown && (
                        <div className="border-t border-bah-border pt-1.5 mt-1">
                          <div className="text-bah-muted mb-1">Priority Breakdown:</div>
                          {Object.entries(s.priority_breakdown as Record<string, number>).map(([k, v]) => (
                            <div key={k} className="flex gap-2 pl-3"><span className="text-bah-muted w-[100px]">{k}</span><span className="text-bah-heading">{String(v)}</span></div>
                          ))}
                        </div>
                      )}
                      <div className="border-t border-bah-border pt-1.5 mt-1">
                        <div className="text-bah-muted mb-1">Reasons:</div>
                        {(s.reasons || []).map((r: string, ri: number) => (
                          <div key={ri} className="text-amber-300/80 pl-3">• {r}</div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </Section>
      )}
    </div>
  );
}

/* ═══════════════════════════════════════════
   LEARNING TAB
   ═══════════════════════════════════════════ */
function LearningTab({ learn, adaptive, token }: { learn: any; adaptive: any; token: string | null }) {
  const ap = adaptive?.profile || {};
  const am = adaptive?.metrics || {};
  const ah = adaptive?.history || [];
  const [diagText, setDiagText] = useState<string>("");
  const [diagLoading, setDiagLoading] = useState(false);
  const [copied, setCopied] = useState(false);

  const modeClr = (m: string): string => m === "AGGRESSIVE" ? "text-bah-cyan" : m === "CONSERVATIVE" ? "text-amber-300" : m === "BALANCED" ? "text-green-400" : "text-bah-muted";
  const modeBg = (m: string): string => m === "AGGRESSIVE" ? "bg-bah-cyan/15 border-bah-cyan/30" : m === "CONSERVATIVE" ? "bg-amber-500/15 border-amber-500/30" : m === "BALANCED" ? "bg-green-500/15 border-green-500/30" : "bg-bah-border/50 border-bah-border";

  return (
    <div className="space-y-4">
      {/* Adaptive Thresholds */}
      <Section title="Adaptive Thresholds">
        <div className="grid grid-cols-2 sm:grid-cols-5 gap-3 mb-4">
          <div className="text-center">
            <span className={`text-sm font-bold px-2.5 py-1 rounded border ${modeBg(ap.mode)}`}>
              <span className={modeClr(ap.mode)}>{ap.mode || "—"}</span>
            </span>
            <div className="text-[8px] text-bah-muted uppercase tracking-wider font-semibold mt-1">Mode</div>
          </div>
          <Stat l="Std Threshold" v={ap.standard_threshold ?? "—"} />
          <Stat l="Early Threshold" v={ap.early_threshold ?? "—"} />
          <Stat l="Early/Cycle" v={ap.max_early_per_cycle ?? "—"} />
          <Stat l="Early Risk" v={ap.early_risk_multiplier ? `${(ap.early_risk_multiplier * 100).toFixed(0)}%` : "—"} />
        </div>
        <div className="flex flex-wrap gap-3 text-[10px] mb-3">
          <span className={`px-2 py-0.5 rounded border ${ap.early_execution_enabled ? "bg-green-500/10 text-green-400 border-green-500/25" : "bg-red-500/10 text-red-300/60 border-red-500/20"}`}>
            Early Exec: {ap.early_execution_enabled ? "ON" : "OFF"}
          </span>
          <span className="text-bah-muted">Samples: {ap.total_samples || 0}</span>
          {ap.last_adjustment_reason && <span className="text-bah-muted max-w-[400px] truncate">{ap.last_adjustment_reason}</span>}
        </div>

        {/* Rolling metrics */}
        {am.total_trades > 0 && (
          <div className="grid grid-cols-3 sm:grid-cols-6 gap-2 pt-3 border-t border-bah-border">
            <Stat l="Win Rate" v={`${((am.win_rate || 0) * 100).toFixed(0)}%`} c={(am.win_rate || 0) >= 0.5 ? "text-green-400" : "text-red-400"} />
            <Stat l="Profit Factor" v={(am.profit_factor || 0).toFixed(1)} c={(am.profit_factor || 0) >= 1.0 ? "text-green-400" : "text-red-400"} />
            <Stat l="Expectancy" v={`$${(am.expectancy || 0).toFixed(0)}`} c={(am.expectancy || 0) >= 0 ? "text-green-400" : "text-red-400"} />
            <Stat l="Drawdown" v={`${(am.drawdown_pct || 0).toFixed(1)}%`} c={(am.drawdown_pct || 0) < 3 ? "text-green-400" : "text-amber-300"} />
            <Stat l="Stop-Out" v={`${((am.stop_out_rate || 0) * 100).toFixed(0)}%`} />
            <Stat l="Trades" v={am.total_trades || 0} />
          </div>
        )}

        {/* Early vs Standard comparison */}
        {(am.early_count > 0 || am.standard_count > 0) && (
          <div className="grid grid-cols-2 gap-3 mt-3 pt-3 border-t border-bah-border">
            <div className="bg-bah-surface border border-bah-border rounded-lg p-2.5">
              <div className="text-[9px] text-bah-muted uppercase tracking-wider font-bold mb-1">Standard</div>
              <div className="text-xs text-bah-heading">{am.standard_count || 0} trades · {((am.standard_win_rate || 0) * 100).toFixed(0)}% WR</div>
            </div>
            <div className="bg-bah-surface border border-bah-border rounded-lg p-2.5">
              <div className="text-[9px] text-amber-300/60 uppercase tracking-wider font-bold mb-1">⚡ Early</div>
              <div className="text-xs text-bah-heading">{am.early_count || 0} trades · {((am.early_win_rate || 0) * 100).toFixed(0)}% WR</div>
            </div>
          </div>
        )}
      </Section>

      {/* Adjustment History */}
      {ah.length > 0 && (
        <Section title="Adjustment History">
          <div className="space-y-1.5">
            {ah.slice(0, 8).map((h: any, i: number) => (
              <div key={i} className="flex items-center gap-3 text-[10px] py-1.5 border-b border-bah-border">
                <span className="text-bah-muted font-mono w-[130px] shrink-0">{h.timestamp ? new Date(h.timestamp).toLocaleString("en-GB", { hour12: false, month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "—"}</span>
                <span className={`px-1.5 py-0.5 rounded border font-bold ${modeBg(h.new_mode)} ${modeClr(h.new_mode)}`}>{h.new_mode}</span>
                <span className="text-bah-muted">std:{h.new_standard_threshold} early:{h.new_early_threshold}</span>
                <span className="text-bah-muted flex-1 truncate">{h.reason}</span>
              </div>
            ))}
          </div>
        </Section>
      )}

      {/* Learning Progress (existing) */}
      <Section title="Learning Progress">
        <div className="flex items-center gap-4 mb-4">
          <div className="flex-1 bg-bah-border/50 rounded-full h-3.5 overflow-hidden">
            <div className="h-full rounded-full bg-gradient-to-r from-purple-500 via-bah-cyan to-emerald-400 anim-bar" style={{ width: `${learn.progress_pct || 0}%` }} />
          </div>
          <span className="text-sm text-bah-heading font-bold">{learn.progress_pct || 0}%</span>
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-5">
          <Stat l="Samples" v={learn.total_samples} />
          <Stat l="Status" v={learn.status?.toUpperCase() || "—"} c={learn.status === "ready" ? "text-green-400" : learn.status === "learning" ? "text-bah-cyan" : "text-amber-300"} />
          <Stat l="Trust" v={learn.trust_ready ? "READY" : "WARMING"} c={learn.trust_ready ? "text-green-400" : "text-bah-muted"} />
          <Stat l="Adaptive" v={ap.mode && ap.mode !== "WARMING_UP" ? "ACTIVE" : "WARMING"} c={ap.mode && ap.mode !== "WARMING_UP" ? "text-green-400" : "text-bah-muted"} />
        </div>
        <div className="space-y-2">
          {(learn.milestones || []).map((m: any, i: number) => (
            <div key={i} className="flex items-center gap-3 text-xs anim-slide" style={{ animationDelay: `${i * 0.06}s` }}>
              <span className={`w-6 h-6 rounded-full flex items-center justify-center text-[10px] font-bold border ${m.reached ? "bg-green-500/20 text-green-400 border-green-500/40" : "bg-bah-surface text-bah-muted border-bah-border"}`}>{m.reached ? "✓" : i + 1}</span>
              <span className={`font-medium ${m.reached ? "text-bah-heading" : "text-bah-muted"}`}>{m.label}</span>
              <span className="text-[10px] text-bah-muted/60">({m.current || 0}/{m.required})</span>
            </div>
          ))}
        </div>
      </Section>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <Section title="By Strategy">
          {Object.keys(learn.by_strategy || {}).length > 0 ? Object.entries(learn.by_strategy).map(([s, c]: [string, any]) => (
            <div key={s} className="flex justify-between py-1.5 text-xs border-b border-bah-border"><span className="text-bah-heading font-medium">{s}</span><span className="text-bah-muted font-mono">{c}</span></div>
          )) : <p className="text-xs text-bah-muted">No samples yet</p>}
        </Section>
        <Section title="By Asset Class">
          {Object.keys(learn.by_class || {}).length > 0 ? Object.entries(learn.by_class).map(([c, n]: [string, any]) => (
            <div key={c} className="flex justify-between py-1.5 text-xs border-b border-bah-border"><span className="text-bah-heading font-medium">{c}</span><span className="text-bah-muted font-mono">{n}</span></div>
          )) : <p className="text-xs text-bah-muted">No samples yet</p>}
        </Section>
      </div>

      {/* ═══ AI DIAGNOSTIC LOGS ═══ */}
      <Section title="🤖 AI Diagnostic Logs">
        <p className="text-[10px] text-bah-muted mb-3">
          Copy these logs and paste into Claude to diagnose issues, identify weak patterns, and improve trading accuracy.
        </p>
        <div className="flex gap-2 mb-3">
          <button
            onClick={async () => {
              setDiagLoading(true);
              setCopied(false);
              try {
                const h: Record<string, string> = token ? { Authorization: `Bearer ${token}` } : {};
                const res = await fetch(`${apiBase()}/training/diagnostics`, { headers: h });
                if (res.ok) {
                  const data = await res.json();
                  const lines: string[] = [];
                  lines.push(`BAHAMUT AI DIAGNOSTICS — ${data.generated_at}`);
                  lines.push("=".repeat(70));
                  for (const sec of data.sections || []) {
                    lines.push("");
                    lines.push(`## ${sec.title}`);
                    if (sec.error) { lines.push(`  ERROR: ${sec.error}`); continue; }
                    if (sec.data && Object.keys(sec.data).length > 0) {
                      lines.push(JSON.stringify(sec.data, null, 2));
                    }
                    for (const row of sec.rows || []) {
                      const parts = Object.entries(row).map(([k, v]) => {
                        if (typeof v === "object" && v !== null) return `${k}=${JSON.stringify(v)}`;
                        return `${k}=${v}`;
                      });
                      lines.push(`  ${parts.join("  ")}`);
                    }
                  }
                  lines.push("");
                  lines.push("=".repeat(70));
                  lines.push("END DIAGNOSTICS — paste above into Claude for analysis");
                  setDiagText(lines.join("\n"));
                } else {
                  setDiagText(`Error: ${res.status} ${res.statusText}`);
                }
              } catch (e: any) {
                setDiagText(`Fetch error: ${e.message}`);
              }
              setDiagLoading(false);
            }}
            disabled={diagLoading}
            className="px-3 py-1.5 text-xs font-bold rounded-lg border border-bah-cyan/40 bg-bah-cyan/10 text-bah-cyan hover:bg-bah-cyan/20 transition-all disabled:opacity-50"
          >
            {diagLoading ? "⏳ Generating..." : "📋 Generate Diagnostic Logs"}
          </button>
          {diagText && (
            <button
              onClick={() => { navigator.clipboard.writeText(diagText); setCopied(true); setTimeout(() => setCopied(false), 2000); }}
              className="px-3 py-1.5 text-xs font-bold rounded-lg border border-green-500/40 bg-green-500/10 text-green-400 hover:bg-green-500/20 transition-all"
            >
              {copied ? "✓ Copied!" : "📎 Copy to Clipboard"}
            </button>
          )}
        </div>
        {diagText && (
          <pre className="bg-black/40 border border-bah-border rounded-lg p-4 text-[10px] text-green-300/80 font-mono overflow-x-auto max-h-[500px] overflow-y-auto whitespace-pre-wrap select-all leading-relaxed">
            {diagText}
          </pre>
        )}
      </Section>
    </div>
  );
}

/* ═══════════════════════════════════════════
   RISK TAB
   ═══════════════════════════════════════════ */
function RiskTab({ expo }: { expo: any }) {
  return (
    <div className="space-y-4">
      <Section title="Exposure">
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <Stat l="Gross" v={`$${(expo.gross_exposure || 0).toLocaleString()}`} />
          <Stat l="Net" v={`$${(expo.net_exposure || 0).toLocaleString()}`} />
          <Stat l="Long" v={`$${(expo.long_exposure || 0).toLocaleString()}`} c="text-green-400" />
          <Stat l="Short" v={`$${(expo.short_exposure || 0).toLocaleString()}`} c="text-red-400" />
        </div>
      </Section>
      <Section title="Utilization">
        <div className="flex items-center gap-4 mb-3">
          <div className="flex-1 bg-bah-border/50 rounded-full h-3 overflow-hidden">
            <div className="h-full rounded-full bg-bah-cyan/50 anim-bar" style={{ width: `${expo.utilization_pct || 0}%` }} />
          </div>
          <span className="text-sm text-bah-heading font-bold">{expo.current_positions || 0} / {expo.max_positions || 20}</span>
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
          <Stat l="Total Risk" v={`$${(expo.total_risk || 0).toLocaleString()}`} />
          <Stat l="Risk %" v={`${expo.risk_pct || 0}%`} />
          <Stat l="Utilization" v={`${expo.utilization_pct || 0}%`} />
        </div>
      </Section>
      {Object.keys(expo.per_class || {}).length > 0 && (
        <Section title="By Class">
          <div className="grid grid-cols-2 sm:grid-cols-5 gap-2">
            {Object.entries(expo.per_class).map(([cls, val]: [string, any]) => (
              <div key={cls} className="bg-bah-surface border border-bah-border rounded-lg p-2.5 text-center">
                <div className="text-[9px] text-bah-muted uppercase tracking-wider font-semibold">{cls}</div>
                <div className="text-xs text-bah-heading font-bold mt-0.5">${val.toLocaleString()}</div>
              </div>
            ))}
          </div>
        </Section>
      )}
    </div>
  );
}

/* ═══════════════════════════════════════════
   ALL ASSETS TAB
   ═══════════════════════════════════════════ */
function AssetsTab({ data }: { data: any }) {
  const [sortBy, setSortBy] = useState<"score" | "asset">("score");
  const [sortDir, setSortDir] = useState<"desc" | "asc">("desc");
  const [filterStatus, setFilterStatus] = useState<string>("all");
  const [filterClass, setFilterClass] = useState<string>("all");
  const [expandedAsset, setExpandedAsset] = useState<string | null>(null);

  if (!data || !data.assets) return (
    <Section title="All Assets">
      <div className="text-center py-10 text-bah-muted text-sm">Loading asset universe... The first scan may take up to 60 seconds.</div>
    </Section>
  );

  const counts: Record<string, number> = data.counts || {};
  const assets: Array<Record<string, any>> = data.assets || [];

  // Filter
  let filtered: Array<Record<string, any>> = assets;
  if (filterStatus !== "all") filtered = filtered.filter(a => a.status === filterStatus);
  if (filterClass !== "all") filtered = filtered.filter(a => a.asset_class === filterClass);

  // Sort
  filtered = [...filtered].sort((a, b) => {
    if (sortBy === "score") {
      const va = Number(a.score) || 0;
      const vb = Number(b.score) || 0;
      return sortDir === "desc" ? vb - va : va - vb;
    }
    const va = String(a.asset || "");
    const vb = String(b.asset || "");
    return sortDir === "asc" ? va.localeCompare(vb) : vb.localeCompare(va);
  });

  const toggleSort = (col: "score" | "asset") => {
    if (sortBy === col) setSortDir(d => d === "desc" ? "asc" : "desc");
    else { setSortBy(col); setSortDir(col === "score" ? "desc" : "asc"); }
  };

  const statusCfg: Record<string, { label: string; cls: string }> = {
    ready: { label: "READY", cls: "bg-green-500/20 text-green-400 border-green-500/40" },
    approaching: { label: "APPROACHING", cls: "bg-amber-500/15 text-amber-300 border-amber-500/35" },
    weak: { label: "WEAK", cls: "bg-bah-surface text-bah-muted border-bah-border" },
    no_signal: { label: "NO SIGNAL", cls: "bg-bah-surface text-bah-muted border-bah-border" },
    no_data: { label: "NO DATA", cls: "bg-red-500/10 text-red-300/50 border-red-500/20" },
    error: { label: "ERROR", cls: "bg-red-500/15 text-red-300 border-red-500/30" },
  };

  const scoreBg = (s: number): string => s >= 80 ? "bg-green-400" : s >= 60 ? "bg-amber-400" : s >= 20 ? "bg-bah-cyan" : "bg-bah-border/50";
  const classSet = new Set<string>();
  assets.forEach(a => { if (a.asset_class) classSet.add(String(a.asset_class)); });
  const uniqueClasses: string[] = Array.from(classSet).sort();

  return (
    <div className="space-y-3">
      {/* Summary counts */}
      <div className="flex flex-wrap gap-2">
        {[
          { label: "Total", value: counts.total || 0, cls: "text-bah-heading" },
          { label: "Ready", value: counts.ready || 0, cls: "text-green-400" },
          { label: "Approaching", value: counts.approaching || 0, cls: "text-amber-300" },
          { label: "Weak", value: counts.weak || 0, cls: "text-bah-muted" },
          { label: "No Signal", value: counts.no_signal || 0, cls: "text-bah-muted" },
          { label: "No Data", value: (counts.no_data || 0) + (counts.error || 0), cls: "text-red-400/60" },
        ].map((s, i) => (
          <div key={i} className="bg-bah-surface border border-bah-border rounded-lg px-3 py-1.5 flex items-center gap-2">
            <span className={`text-sm font-bold ${s.cls}`}>{s.value}</span>
            <span className="text-[9px] text-bah-muted uppercase tracking-wider">{s.label}</span>
          </div>
        ))}
        {data.duration_ms > 0 && (
          <div className="bg-bah-surface border border-bah-border rounded-lg px-3 py-1.5 flex items-center">
            <span className="text-[10px] text-bah-muted/60 font-mono">scanned in {data.duration_ms}ms</span>
          </div>
        )}
      </div>

      {/* Filters */}
      <div className="flex flex-wrap gap-2 items-center">
        <span className="text-[10px] text-bah-muted uppercase tracking-wider">Filter:</span>
        <select value={filterStatus} onChange={e => setFilterStatus(e.target.value)}
          className="bg-bah-border/50 border border-bah-border rounded text-[11px] text-bah-text px-2 py-1 outline-none focus:border-bah-cyan/40">
          <option value="all">All statuses</option>
          <option value="ready">Ready</option>
          <option value="approaching">Approaching</option>
          <option value="weak">Weak</option>
          <option value="no_signal">No Signal</option>
        </select>
        <select value={filterClass} onChange={e => setFilterClass(e.target.value)}
          className="bg-bah-border/50 border border-bah-border rounded text-[11px] text-bah-text px-2 py-1 outline-none focus:border-bah-cyan/40">
          <option value="all">All classes</option>
          {uniqueClasses.map(c => <option key={c} value={c}>{c}</option>)}
        </select>
        <span className="text-[10px] text-bah-muted/60 ml-1">{filtered.length} shown</span>
      </div>

      {/* Table */}
      <Section title={`Asset Universe (${filtered.length})`}>
        <div className="overflow-x-auto">
          <table className="w-full text-[11px] min-w-[900px]">
            <thead>
              <tr className="border-b border-bah-border text-[9px] text-bah-muted uppercase tracking-wider text-left">
                <th className="py-2.5 px-3 cursor-pointer hover:text-bah-muted select-none" onClick={() => toggleSort("score")}>
                  Score {sortBy === "score" ? (sortDir === "desc" ? "↓" : "↑") : ""}
                </th>
                <th className="py-2.5 px-3 cursor-pointer hover:text-bah-muted select-none" onClick={() => toggleSort("asset")}>
                  Asset {sortBy === "asset" ? (sortDir === "asc" ? "↑" : "↓") : ""}
                </th>
                <th className="py-2.5 px-3">Class</th>
                <th className="py-2.5 px-3">Status</th>
                <th className="py-2.5 px-3">Strategy</th>
                <th className="py-2.5 px-3">Dir</th>
                <th className="py-2.5 px-3">Regime</th>
                <th className="py-2.5 px-3">Distance</th>
                <th className="py-2.5 px-3">RSI</th>
                <th className="py-2.5 px-3">Reason</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((a: any, i: number) => {
                const st = statusCfg[a.status] || statusCfg.no_signal;
                const isExpanded = expandedAsset === a.asset;
                return (
                  <React.Fragment key={i}>
                  <tr onClick={() => setExpandedAsset(isExpanded ? null : a.asset)}
                      className={`border-b border-bah-border hover-row cursor-pointer ${a.status === "ready" ? "bg-green-500/[0.02]" : ""} ${isExpanded ? "bg-bah-surface" : ""}`}>
                    <td className="py-2 px-3">
                      <div className="flex items-center gap-2">
                        <div className="w-10 h-1.5 bg-bah-border/50 rounded-full overflow-hidden">
                          <div className={`h-full rounded-full ${scoreBg(a.score)}`} style={{ width: `${a.score}%` }} />
                        </div>
                        <span className={`text-xs font-bold min-w-[24px] text-center ${a.score >= 80 ? "text-green-400" : a.score >= 60 ? "text-amber-300" : a.score > 0 ? "text-bah-muted" : "text-bah-muted/60"}`}>{a.score}</span>
                      </div>
                    </td>
                    <td className="py-2 px-3">
                      <div className="flex items-center gap-1.5">
                        <span className="text-[10px] text-bah-muted">{isExpanded ? "▾" : "▸"}</span>
                        <span className="text-bah-heading font-semibold">{a.asset}</span>
                      </div>
                    </td>
                    <td className="py-2 px-3 text-bah-muted">{a.asset_class}</td>
                    <td className="py-2 px-3">
                      <span className={`px-1.5 py-0.5 rounded text-[9px] font-bold border ${st.cls}`}>{st.label}</span>
                    </td>
                    <td className="py-2 px-3 text-bah-muted">{sn(a.strategy)}</td>
                    <td className="py-2 px-3">
                      {a.direction !== "—" ? <span className={`font-bold ${a.direction === "LONG" ? "text-green-400" : "text-red-400"}`}>{a.direction}</span> : <span className="text-bah-muted/60">—</span>}
                    </td>
                    <td className="py-2 px-3">
                      {a.regime !== "—" ? (
                        <span className={`px-1 py-0.5 rounded text-[9px] font-bold ${
                          a.regime === "TREND" || a.regime === "BREAKOUT" ? "bg-green-500/10 text-green-400" :
                          a.regime === "BEAR" ? "bg-red-500/10 text-red-300" :
                          "bg-bah-surface text-bah-muted"
                        }`}>{a.regime}</span>
                      ) : <span className="text-bah-muted/60">—</span>}
                    </td>
                    <td className="py-2 px-3 text-[10px] text-bah-muted font-mono max-w-[160px] truncate">{a.distance_to_trigger}</td>
                    <td className="py-2 px-3 font-mono">
                      {a.indicators?.rsi ? (
                        <span className={a.indicators.rsi < 30 ? "text-green-400" : a.indicators.rsi > 70 ? "text-red-400" : "text-bah-muted"}>{a.indicators.rsi.toFixed(0)}</span>
                      ) : <span className="text-bah-muted/40">—</span>}
                    </td>
                    <td className="py-2 px-3 text-[10px] text-bah-muted max-w-[220px] truncate">{a.reason}</td>
                  </tr>
                  {isExpanded && (
                    <tr className="bg-bah-surface">
                      <td colSpan={10} className="px-4 py-3">
                        <AssetBreakdown asset={a} />
                      </td>
                    </tr>
                  )}
                  </React.Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      </Section>
    </div>
  );
}

/* ═══════════════════════════════════════════
   EXECUTION DECISIONS
   ═══════════════════════════════════════════ */
function ExecutionDecisions({ decisions }: { decisions: any }) {
  const [showAll, setShowAll] = useState(false);
  const exec = decisions.execute || [];
  const watch = decisions.watchlist || [];
  const rej = decisions.rejected || [];
  const summary = decisions.summary || {};

  const decClr: Record<string, string> = {
    EXECUTE: "bg-green-500/20 text-green-400 border-green-500/40",
    WATCHLIST: "bg-amber-500/15 text-amber-300 border-amber-500/35",
    REJECT: "bg-bah-surface text-bah-muted border-bah-border",
  };

  const allItems = [
    ...exec.map((d: any) => ({ ...d, _group: "EXECUTE" })),
    ...watch.map((d: any) => ({ ...d, _group: "WATCHLIST" })),
  ];

  if (allItems.length === 0) return null;

  const VISIBLE = 5;
  const visible = showAll ? allItems : allItems.slice(0, VISIBLE);
  const hasMore = allItems.length > VISIBLE;

  return (
    <div className="bg-bah-surface border border-bah-border rounded-xl p-2 sm:p-4">
      <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
        <div className="flex items-center gap-2 sm:gap-3 flex-wrap">
          <span className="text-xs sm:text-sm font-bold text-bah-heading tracking-tight">⚡ Execution Decisions</span>
          {exec.length > 0 && (
            <span className="px-2 py-0.5 text-[9px] sm:text-[10px] font-bold rounded bg-green-500/20 text-green-400 border border-green-500/35">{exec.length} EXECUTE</span>
          )}
          {watch.length > 0 && (
            <span className="px-2 py-0.5 text-[9px] sm:text-[10px] font-bold rounded bg-amber-500/15 text-amber-300 border border-amber-500/30">{watch.length} WATCH</span>
          )}
        </div>
        <span className="text-[9px] sm:text-[10px] text-bah-muted font-mono hidden sm:inline">
          {summary.total_signals || 0} signals → {summary.selected || 0} selected · threshold ≥{summary.config?.execution_threshold || 80}
        </span>
      </div>

      <div className="space-y-1.5 overflow-x-auto">
        {visible.map((d: any, i: number) => (
          <div key={i} className={`flex items-center gap-2 sm:gap-3 px-2 sm:px-3 py-1.5 sm:py-2 rounded-lg border min-w-[600px] ${d._group === "EXECUTE" ? "bg-green-500/[0.03] border-green-500/15" : "bg-bah-surface border-bah-border"}`}>
            <span className={`px-2 py-0.5 text-[9px] font-bold rounded border shrink-0 ${decClr[d._group]}`}>{d._group}</span>
            <span className="text-xs text-bah-heading font-bold w-[70px] shrink-0">{d.asset}</span>
            <span className="text-[10px] text-bah-muted w-[50px] shrink-0">{sn(d.strategy)}</span>
            <span className={`text-[10px] font-bold w-[40px] shrink-0 ${d.direction === "LONG" ? "text-green-400" : "text-red-400"}`}>{d.direction}</span>
            <ExecBadge type={d.execution_type} />
            <span className="text-[10px] text-bah-muted w-[30px] shrink-0 text-center">{d.readiness_score}</span>
            <span className="text-[10px] text-bah-muted w-[30px] shrink-0 text-center font-mono">{d.priority_score}</span>

            {d.priority_breakdown && (
              <div className="flex gap-0.5 shrink-0">
                {Object.entries(d.priority_breakdown as Record<string, number>).slice(0, 5).map(([k, v]) => (
                  <div key={k} title={`${k}: ${v}`} className="w-3 bg-bah-border rounded-sm overflow-hidden" style={{ height: "12px" }}>
                    <div className={`w-full rounded-sm ${Number(v) > 10 ? "bg-green-400/60" : Number(v) > 0 ? "bg-bah-border" : "bg-transparent"}`} style={{ height: `${Math.min(100, (Number(v) / 20) * 100)}%`, marginTop: "auto" }} />
                  </div>
                ))}
              </div>
            )}

            <span className="text-[10px] text-bah-muted flex-1 truncate">{(d.reasons || []).join(" · ")}</span>
          </div>
        ))}
      </div>

      {hasMore && (
        <button onClick={() => setShowAll(!showAll)}
          className="w-full mt-2 py-2 text-[10px] font-bold text-bah-cyan hover:text-bah-cyan/80 border border-bah-border rounded-lg hover:bg-bah-cyan/5 transition-all">
          {showAll ? `▲ Show less` : `▼ Show all ${allItems.length} decisions`}
        </button>
      )}
    </div>
  );
}

/* ═══════════════════════════════════════════
   ASSET SCORE BREAKDOWN (expandable row)
   ═══════════════════════════════════════════ */
function AssetBreakdown({ asset: a }: { asset: any }) {
  const bd = a.score_breakdown || {};
  const missing = a.missing_conditions || [];
  const explanation = a.explanation || "";
  const reasons = a.reasons || [];

  // Compute max component value for bar scaling
  const components = Object.entries(bd).filter(([_, v]) => typeof v === "number") as Array<[string, number]>;
  const maxVal = Math.max(35, ...components.map(([_, v]) => Math.abs(v)));

  const labelMap: Record<string, string> = {
    regime: "Regime", ema_proximity: "EMA Proximity", ema_convergence: "EMA Convergence",
    rsi: "RSI", volume: "Volume", breakout_proximity: "Breakout Proximity",
    confirmation: "Confirmation", volatility: "Volatility", crash_penalty: "Crash Penalty",
  };

  const barClr = (v: number): string => v >= 20 ? "bg-green-400" : v >= 10 ? "bg-green-400/60" : v > 0 ? "bg-bah-cyan" : v < 0 ? "bg-red-400" : "bg-bah-border/50";

  if (!components.length && !explanation) {
    return <div className="text-xs text-bah-muted">No breakdown available for this asset.</div>;
  }

  return (
    <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
      {/* Score Breakdown */}
      <div>
        <div className="text-[10px] text-bah-muted uppercase tracking-wider font-bold mb-2">Score Breakdown</div>
        <div className="space-y-1.5">
          {components.map(([key, val]) => (
            <div key={key} className="flex items-center gap-2">
              <span className="text-[10px] text-bah-muted w-[100px] truncate">{labelMap[key] || key}</span>
              <div className="flex-1 h-1.5 bg-bah-border/50 rounded-full overflow-hidden">
                {val >= 0 ? (
                  <div className={`h-full rounded-full ${barClr(val)}`} style={{ width: `${(val / maxVal) * 100}%` }} />
                ) : (
                  <div className="h-full flex justify-end">
                    <div className="bg-red-400 rounded-full h-full" style={{ width: `${(Math.abs(val) / maxVal) * 100}%` }} />
                  </div>
                )}
              </div>
              <span className={`text-[10px] font-bold w-[28px] text-right ${val > 0 ? "text-green-400" : val < 0 ? "text-red-300" : "text-bah-muted/60"}`}>
                {val > 0 ? `+${val}` : val}
              </span>
            </div>
          ))}
          <div className="flex items-center gap-2 pt-1 border-t border-bah-border">
            <span className="text-[10px] text-bah-text w-[100px] font-bold">Total</span>
            <div className="flex-1" />
            <span className="text-xs font-bold text-bah-heading">{a.score}</span>
          </div>
        </div>
      </div>

      {/* Explanation */}
      <div>
        <div className="text-[10px] text-bah-muted uppercase tracking-wider font-bold mb-2">AI Explanation</div>
        <p className="text-[11px] text-bah-text leading-relaxed mb-3">{explanation || "No explanation available."}</p>
        {reasons.length > 0 && (
          <>
            <div className="text-[10px] text-bah-muted uppercase tracking-wider font-bold mb-1.5">Factors</div>
            <div className="space-y-1">
              {reasons.slice(0, 5).map((r: string, i: number) => (
                <div key={i} className="text-[10px] text-bah-muted flex items-start gap-1.5">
                  <span className="text-bah-muted/60 mt-0.5">•</span>
                  <span>{r}</span>
                </div>
              ))}
            </div>
          </>
        )}
      </div>

      {/* Missing Conditions */}
      <div>
        <div className="text-[10px] text-bah-muted uppercase tracking-wider font-bold mb-2">Missing to Trigger</div>
        {missing.length > 0 ? (
          <div className="space-y-1.5">
            {missing.map((m: string, i: number) => (
              <div key={i} className="flex items-start gap-2 text-[11px]">
                <span className="text-amber-400/70 mt-0.5 shrink-0">⚡</span>
                <span className="text-bah-text">{m}</span>
              </div>
            ))}
          </div>
        ) : (
          <div className="text-[11px] text-green-400/60">All conditions met — signal may fire on next bar evaluation.</div>
        )}
      </div>
    </div>
  );
}

/* ═══════════════════════════════════════════
   SHARED COMPONENTS
   ═══════════════════════════════════════════ */
function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="bg-bah-surface border border-bah-border rounded-xl p-4">
      <h3 className="text-[11px] font-bold text-bah-text mb-3 uppercase tracking-[0.08em]">{title}</h3>
      {children}
    </div>
  );
}

function ExecBadge({ type }: { type: string | undefined }) {
  if (type === "early") return <span className="px-1.5 py-0.5 rounded text-[8px] font-bold bg-amber-500/20 text-amber-300 border border-amber-500/30">⚡ EARLY</span>;
  return <span className="px-1.5 py-0.5 rounded text-[8px] font-bold bg-green-500/10 text-green-400/60 border border-green-500/15">STD</span>;
}

function Stat({ l, v, c }: { l: string; v: any; c?: string }) {
  return (
    <div className="text-center">
      <div className={`text-sm font-bold ${c || "text-bah-heading"}`}>{v}</div>
      <div className="text-[8px] text-bah-muted uppercase tracking-wider font-semibold">{l}</div>
    </div>
  );
}
