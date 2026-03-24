"use client";

import { useState, useEffect, useRef } from "react";
import { apiBase } from "@/lib/utils";

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
  const [loading, setLoading] = useState(true);
  const [allAssets, setAllAssets] = useState<any>(null);
  const [tab, setTab] = useState<"overview" | "positions" | "trades" | "learning" | "risk" | "assets">("overview");
  const token = typeof window !== "undefined" ? sessionStorage.getItem("bah_token") : null;

  const load = async () => {
    const h = token ? { Authorization: `Bearer ${token}` } : {};
    try {
      const [opsRes, candRes] = await Promise.all([
        fetch(`${apiBase()}/training/operations`, { headers: h }),
        fetch(`${apiBase()}/training/candidates`, { headers: h }),
      ]);
      if (opsRes.ok) setData(await opsRes.json());
      if (candRes.ok) setCandidates(await candRes.json());
    } catch {}
    // Lazy-load assets tab data only when tab is active (heavy endpoint)
    if (tab === "assets" || !allAssets) {
      try {
        const r = await fetch(`${apiBase()}/training/assets`, { headers: h });
        if (r.ok) setAllAssets(await r.json());
      } catch {}
    }
    setLoading(false);
  };

  useEffect(() => { load(); const iv = setInterval(load, 20000); return () => clearInterval(iv); }, []);

  if (loading) return (
    <div className="p-12 text-center">
      <div className="inline-block w-8 h-8 border-2 border-bah-cyan/30 border-t-bah-cyan rounded-full animate-spin mb-4" />
      <p className="text-white/40 text-sm">Loading training operations...</p>
    </div>
  );

  if (!data) return (
    <div className="p-12 text-center">
      <p className="text-lg font-bold text-white mb-2">Training Operations</p>
      <p className="text-sm text-white/40">Waiting for first training cycle (runs every 10 min).</p>
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
  const pnlC = (v: number) => v >= 0 ? "text-emerald-400" : "text-red-400";
  const fmtPct = (v: number) => `${(v * 100).toFixed(1)}%`;
  const fmtT = (s: string) => { if (!s) return "—"; try { return new Date(s).toLocaleString("en-GB", { hour12: false, month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit" }); } catch { return s; } };

  return (
    <div className="p-2 sm:p-4 max-w-[1440px] space-y-3 pt-12 lg:pt-4">
      <style>{`
        @keyframes slideUp { from { opacity:0; transform:translateY(14px); } to { opacity:1; transform:translateY(0); } }
        @keyframes fadeIn { from { opacity:0; } to { opacity:1; } }
        @keyframes barGrow { from { width:0; } }
        @keyframes pulse2 { 0%,100% { opacity:1; } 50% { opacity:0.5; } }
        @keyframes scanPulse { 0%,100% { box-shadow:0 0 6px rgba(0,210,210,0.15); } 50% { box-shadow:0 0 18px rgba(0,210,210,0.35); } }
        .anim-slide { animation: slideUp 0.45s ease forwards; }
        .anim-fade { animation: fadeIn 0.35s ease forwards; }
        .anim-bar { animation: barGrow 0.7s ease forwards; }
        .hover-row:hover { background: rgba(255,255,255,0.025); }
      `}</style>

      {/* ═══ HEADER ═══ */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 anim-slide">
        <div className="flex items-center gap-3 flex-wrap">
          <h1 className="text-base sm:text-lg font-bold text-white tracking-tight">Training Operations</h1>
          <span className="px-2.5 py-0.5 text-[10px] rounded-full font-bold border bg-purple-500/20 text-purple-300 border-purple-500/40 tracking-wider">PAPER ONLY</span>
          <span className="text-[11px] text-white/40">{cs.universe_size || k.universe_size || 0} assets</span>
        </div>
      </div>

      {/* ═══ LIVE CYCLE STATUS STRIP ═══ */}
      <CycleStatusStrip cs={cs} />

      {/* ═══ ALERTS ═══ */}
      {alerts.length > 0 && (
        <div className="space-y-1.5 anim-slide" style={{ animationDelay: "0.06s" }}>
          {alerts.map((a: any, i: number) => (
            <div key={i} className={`px-4 py-2 rounded-lg text-xs font-medium border ${a.level === "WARNING" ? "bg-amber-500/8 border-amber-500/25 text-amber-300" : "bg-white/[0.02] border-white/10 text-white/50"}`}>
              {a.level === "WARNING" ? "⚠️" : "ℹ️"} {a.message}
            </div>
          ))}
        </div>
      )}

      {/* ═══ KPI ROW ═══ */}
      <div className="grid grid-cols-3 sm:grid-cols-5 lg:grid-cols-10 gap-1.5 anim-slide" style={{ animationDelay: "0.08s" }}>
        {[
          { l: "Universe", v: k.universe_size || 0 },
          { l: "Scanned", v: k.assets_scanned || 0 },
          { l: "Open", v: k.open_positions || 0 },
          { l: "Closed", v: k.closed_trades || 0 },
          { l: "Net PnL", v: fmtPnl(k.net_pnl || 0), c: pnlC(k.net_pnl || 0) },
          { l: "Win Rate", v: fmtPct(k.win_rate || 0) },
          { l: "Avg Bars", v: (k.avg_duration_bars || 0).toFixed(1) },
          { l: "Samples", v: k.learning_samples || 0 },
          { l: "Util", v: `${expo.utilization_pct || 0}%` },
          { l: "Risk", v: `${expo.risk_pct || 0}%` },
        ].map((x, i) => (
          <div key={i} className="bg-white/[0.025] border border-white/[0.06] rounded-lg p-2 text-center">
            <div className={`text-sm font-bold ${x.c || "text-white"}`}>{x.v}</div>
            <div className="text-[8px] text-white/30 uppercase tracking-wider font-semibold">{x.l}</div>
          </div>
        ))}
      </div>

      {/* ═══ TRADE CANDIDATES ═══ */}
      <div className="anim-slide" style={{ animationDelay: "0.12s" }}>
        <CandidatesSection candidates={candidates} />
      </div>

      {/* ═══ TABS ═══ */}
      <div className="flex border-b border-white/[0.08] overflow-x-auto">
        {(["overview", "positions", "trades", "assets", "learning", "risk"] as const).map(t => (
          <button key={t} onClick={() => setTab(t)} className={`px-4 py-2.5 text-xs font-semibold border-b-2 transition-all whitespace-nowrap ${tab === t ? "border-bah-cyan text-bah-cyan" : "border-transparent text-white/30 hover:text-white/60"}`}>
            {t === "overview" ? "📊 Overview" : t === "positions" ? `📦 Positions (${k.open_positions || 0})` : t === "trades" ? `🔁 Trades (${k.closed_trades || 0})` : t === "assets" ? `🌐 All Assets (${allAssets?.counts?.total || k.universe_size || 0})` : t === "learning" ? "🧬 Learning" : "⚖️ Risk"}
          </button>
        ))}
      </div>

      {/* ═══ TAB CONTENT ═══ */}
      <div className="anim-fade" key={tab}>
        {tab === "overview" && <OverviewTab strats={strats} classes={classes} rankings={rankings} cy={cy} recentCycles={recentCycles} fmtPnl={fmtPnl} fmtPct={fmtPct} fmtT={fmtT} pnlC={pnlC} />}
        {tab === "positions" && <PositionsTab positions={data.positions || []} fmtPnl={fmtPnl} pnlC={pnlC} />}
        {tab === "trades" && <TradesTab trades={data.closed_trades || []} fmtPnl={fmtPnl} pnlC={pnlC} fmtT={fmtT} />}
        {tab === "assets" && <AssetsTab data={allAssets} />}
        {tab === "learning" && <LearningTab learn={learn} />}
        {tab === "risk" && <RiskTab expo={expo} />}
      </div>
    </div>
  );
}

/* ═══════════════════════════════════════════
   CYCLE STATUS STRIP
   ═══════════════════════════════════════════ */
function CycleStatusStrip({ cs }: { cs: any }) {
  const nextCycle = useCountdown(cs.next_cycle_time);
  const next4H = useCountdown(cs.next_4h_bar_time);

  // Derive auto training label: ON (has run successfully), WARMING UP (never ran), OFF (no Redis)
  const hasRun = !!cs.last_cycle_time;
  const autoLabel = !cs.auto_enabled ? "OFF" : cs.is_running ? "SCANNING" : hasRun ? "ON" : "WARMING UP";
  const autoClr = !cs.auto_enabled ? "text-red-400" : cs.is_running ? "text-bah-cyan" : hasRun ? "text-emerald-400" : "text-amber-300";
  const autoDot = !cs.auto_enabled ? "bg-red-400" : cs.is_running ? "bg-bah-cyan" : hasRun ? "bg-emerald-400" : "bg-amber-400";

  // System status: RUNNING > OK/DEGRADED/FAILED > IDLE > WAITING
  const sysStatus = cs.is_running ? "RUNNING" :
    cs.cycle_status === "OK" ? "SUCCESS" :
    cs.cycle_status === "DEGRADED" ? "DEGRADED" :
    cs.cycle_status === "FAILED" ? "ERROR" :
    cs.cycle_status === "waiting" ? "IDLE" : "IDLE";
  const sysClr = sysStatus === "SUCCESS" ? "text-emerald-400" : sysStatus === "RUNNING" ? "text-bah-cyan" : sysStatus === "DEGRADED" ? "text-amber-300" : sysStatus === "ERROR" ? "text-red-400" : "text-white/40";

  return (
    <div className={`rounded-xl border p-3 flex flex-wrap items-center gap-x-5 gap-y-2 anim-slide ${cs.is_running ? "bg-bah-cyan/[0.04] border-bah-cyan/25" : "bg-white/[0.025] border-white/[0.08]"}`} style={{ animationDelay: "0.03s", ...(cs.is_running ? { animation: "scanPulse 2.5s ease-in-out infinite" } : {}) }}>

      {/* Auto Training ON/OFF/WARMING */}
      <div className="flex items-center gap-2">
        <span className={`w-2.5 h-2.5 rounded-full ${autoDot} ${cs.is_running ? "animate-pulse" : ""}`} />
        <span className="text-[11px] font-bold text-white/70 uppercase tracking-wider">Auto Training</span>
        <span className={`text-[11px] font-extrabold ${autoClr}`}>{autoLabel}</span>
      </div>

      {/* Running progress */}
      {cs.is_running && (
        <div className="flex items-center gap-2">
          <div className="w-20 h-1.5 bg-white/[0.06] rounded-full overflow-hidden">
            <div className="h-full bg-bah-cyan rounded-full transition-all duration-500" style={{ width: `${cs.running_progress ? (cs.running_progress.current / Math.max(1, cs.running_progress.total)) * 100 : 0}%` }} />
          </div>
          <span className="text-[10px] text-bah-cyan font-bold font-mono">{cs.running_progress?.current || 0}/{cs.running_progress?.total || cs.universe_size || 40}</span>
        </div>
      )}

      <div className="hidden sm:block w-px h-5 bg-white/[0.08]" />

      {/* System status */}
      <div className="flex items-center gap-1.5">
        <span className="text-[10px] text-white/30 uppercase tracking-wider">Status</span>
        <span className={`text-[11px] font-bold ${sysClr}`}>{sysStatus}</span>
      </div>

      <div className="hidden sm:block w-px h-5 bg-white/[0.08]" />

      {/* Next cycle countdown */}
      <div className="flex items-center gap-1.5">
        <span className="text-[10px] text-white/30 uppercase tracking-wider">Next cycle</span>
        <span className={`text-[13px] font-bold font-mono tabular-nums ${cs.is_running ? "text-bah-cyan" : nextCycle !== null && nextCycle < 60 ? "text-bah-cyan" : "text-white/80"}`}>
          {cs.is_running ? "NOW" : fmtCountdown(nextCycle)}
        </span>
      </div>

      <div className="hidden sm:block w-px h-5 bg-white/[0.08]" />

      {/* Next 4H bar countdown */}
      <div className="flex items-center gap-1.5">
        <span className="text-[10px] text-white/30 uppercase tracking-wider">Next 4H bar</span>
        <span className="text-[13px] font-bold font-mono tabular-nums text-white/80">{fmtCountdown(next4H)}</span>
      </div>

      <div className="hidden sm:block w-px h-5 bg-white/[0.08]" />

      {/* Interval + last run */}
      <div className="flex items-center gap-3 text-[10px] text-white/25 font-mono">
        <span>every {(cs.cycle_interval_seconds || 600) / 60}m</span>
        {cs.last_cycle_time && <span>last: {new Date(cs.last_cycle_time).toLocaleTimeString("en-GB", { hour12: false })}</span>}
      </div>
    </div>
  );
}

/* ═══════════════════════════════════════════
   TRADE CANDIDATES (upgraded)
   ═══════════════════════════════════════════ */
function CandidatesSection({ candidates }: { candidates: any[] }) {
  const [expanded, setExpanded] = useState(true);
  const THRESHOLD = 80;

  const urgency = (s: number) => s >= THRESHOLD ? { label: "READY", cls: "bg-emerald-500/25 text-emerald-300 border-emerald-500/40" } :
    s >= 60 ? { label: "APPROACHING", cls: "bg-amber-500/20 text-amber-300 border-amber-500/40" } :
    { label: "WEAK", cls: "bg-white/[0.04] text-white/35 border-white/10" };

  const scoreBg = (s: number) => s >= THRESHOLD ? "bg-emerald-400" : s >= 60 ? "bg-amber-400" : s >= 40 ? "bg-white/30" : "bg-white/15";

  const aboveThreshold = candidates.filter(c => c.score >= THRESHOLD).length;

  if (!candidates || candidates.length === 0) {
    return (
      <div className="bg-white/[0.025] border border-white/[0.08] rounded-xl p-5">
        <div className="flex items-center gap-3 mb-3">
          <span className="text-sm font-bold text-white tracking-tight">🔥 Trade Candidates</span>
          <span className="text-[10px] text-white/25">read-only intelligence</span>
        </div>
        <div className="flex items-start gap-3">
          <span className="text-xl mt-0.5">📡</span>
          <div>
            <p className="text-xs text-white/50 font-medium mb-1">All candidates below execution threshold (score ≥ {THRESHOLD})</p>
            <p className="text-[11px] text-white/30">The scanner evaluates 40+ assets against EMA cross and breakout strategies every 10 minutes. Candidates appear when price action converges on trigger conditions. The next opportunity may come at the next 4H bar boundary.</p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="bg-white/[0.025] border border-white/[0.08] rounded-xl overflow-hidden">
      <button onClick={() => setExpanded(!expanded)} className="w-full px-4 py-3.5 flex items-center justify-between hover:bg-white/[0.015] transition-all">
        <div className="flex items-center gap-3">
          <span className="text-sm font-bold text-white tracking-tight">🔥 Trade Candidates</span>
          <span className="px-2.5 py-0.5 text-[11px] font-bold rounded-full bg-bah-cyan/15 text-bah-cyan border border-bah-cyan/30" style={{ animation: "scanPulse 3s ease-in-out infinite" }}>{candidates.length}</span>
          {aboveThreshold > 0 && (
            <span className="px-2 py-0.5 text-[10px] font-bold rounded bg-emerald-500/20 text-emerald-300 border border-emerald-500/35">{aboveThreshold} READY (≥{THRESHOLD})</span>
          )}
          <span className="text-[10px] text-white/25 hidden sm:inline">execution threshold: {THRESHOLD}</span>
        </div>
        <span className="text-xs text-white/25">{expanded ? "▾" : "▸"}</span>
      </button>

      {expanded && (
        <div className="border-t border-white/[0.06] overflow-x-auto">
          <table className="w-full text-[11px] min-w-[1000px]">
            <thead>
              <tr className="border-b border-white/[0.08] text-left text-[9px] text-white/25 uppercase tracking-[0.1em]">
                <th className="px-3 py-2.5 w-[130px]">Score</th><th className="px-3 py-2.5">Asset</th><th className="px-3 py-2.5">Strategy</th>
                <th className="px-3 py-2.5">Dir</th><th className="px-3 py-2.5">Regime</th><th className="px-3 py-2.5">Distance</th>
                <th className="px-3 py-2.5">RSI</th><th className="px-3 py-2.5">EMAs</th><th className="px-3 py-2.5">Setup</th>
              </tr>
            </thead>
            <tbody>
              {candidates.map((c: any, i: number) => {
                const u = urgency(c.score);
                const isTop = i === 0;
                const isAbove = c.score >= THRESHOLD;
                return (
                  <tr key={i} className={`border-b border-white/[0.03] hover-row anim-slide ${isTop ? "bg-bah-cyan/[0.03]" : isAbove ? "bg-white/[0.015]" : ""}`} style={{ animationDelay: `${i * 0.035}s` }}>
                    <td className="px-3 py-2.5">
                      <div className="flex items-center gap-2">
                        <div className="w-12 h-2 bg-white/[0.04] rounded-full overflow-hidden">
                          <div className={`h-full rounded-full anim-bar ${scoreBg(c.score)}`} style={{ width: `${c.score}%`, animationDelay: `${0.2 + i * 0.04}s` }} />
                        </div>
                        <span className={`text-xs font-bold px-2 py-0.5 rounded border min-w-[32px] text-center ${
                          c.score >= THRESHOLD ? "text-emerald-300 bg-emerald-500/25 border-emerald-500/45" :
                          c.score >= 60 ? "text-amber-300 bg-amber-500/20 border-amber-500/40" :
                          "text-white/50 bg-white/[0.04] border-white/10"
                        }`}>{c.score}</span>
                      </div>
                    </td>
                    <td className="px-3 py-2.5">
                      <div className="flex items-center gap-2">
                        <span className={`font-bold ${isTop ? "text-bah-cyan" : "text-white"}`}>{c.asset}</span>
                        <span className={`px-1.5 py-0 text-[8px] font-bold rounded border tracking-wider ${u.cls}`}>{u.label}</span>
                      </div>
                      <div className="text-[9px] text-white/30 mt-0.5">{c.asset_class}</div>
                    </td>
                    <td className="px-3 py-2.5 text-white/55 font-medium">{c.strategy}</td>
                    <td className="px-3 py-2.5"><span className={`font-bold ${c.direction === "LONG" ? "text-emerald-400" : "text-red-400"}`}>{c.direction}</span></td>
                    <td className="px-3 py-2.5"><span className={`px-1.5 py-0.5 rounded text-[9px] font-bold ${
                      c.regime === "TREND" || c.regime === "BREAKOUT" ? "bg-emerald-500/12 text-emerald-300 border border-emerald-500/25" :
                      c.regime === "BEAR" ? "bg-red-500/12 text-red-300 border border-red-500/25" :
                      "bg-white/[0.04] text-white/40 border border-white/10"
                    }`}>{c.regime}</span></td>
                    <td className="px-3 py-2.5 text-[10px] text-white/55 font-mono">{c.distance_to_trigger}</td>
                    <td className="px-3 py-2.5 font-mono"><span className={`font-semibold ${c.indicators?.rsi < 30 ? "text-emerald-400" : c.indicators?.rsi > 70 ? "text-red-400" : "text-white/55"}`}>{c.indicators?.rsi?.toFixed(0) || "—"}</span></td>
                    <td className="px-3 py-2.5"><span className={`px-1.5 py-0.5 rounded text-[9px] font-semibold ${
                      c.indicators?.ema_alignment?.includes("bullish") ? "bg-emerald-500/10 text-emerald-300" :
                      c.indicators?.ema_alignment?.includes("bearish") ? "bg-red-500/10 text-red-300" :
                      "text-white/35"
                    }`}>{c.indicators?.ema_alignment?.replace("_", " ") || "—"}</span></td>
                    <td className="px-3 py-2.5 max-w-[260px]">
                      {(c.reasons || []).slice(0, 3).map((r: string, j: number) => (
                        <div key={j} className="text-[10px] text-white/50 leading-snug">{r}</div>
                      ))}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

/* ═══════════════════════════════════════════
   OVERVIEW TAB
   ═══════════════════════════════════════════ */
function OverviewTab({ strats, classes, rankings, cy, recentCycles, fmtPnl, fmtPct, fmtT, pnlC }: any) {
  return (
    <div className="space-y-4">
      <Section title="Cycle Health">
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <Stat l="Processed" v={cy.assets_processed} /><Stat l="Skipped" v={cy.assets_skipped} />
          <Stat l="Errors" v={cy.errors} c={cy.errors > 0 ? "text-red-400" : ""} /><Stat l="Signals" v={cy.signals_generated} />
        </div>
      </Section>

      {/* Recent Cycles */}
      {recentCycles.length > 0 && (
        <Section title="Recent Cycles">
          <div className="overflow-x-auto">
            <table className="w-full text-[11px]">
              <thead><tr className="border-b border-white/[0.08] text-[9px] text-white/25 uppercase tracking-wider text-left">
                <th className="py-2 pr-3">Time</th><th className="py-2 pr-3">Status</th><th className="py-2 pr-3">Processed</th><th className="py-2 pr-3">Errors</th><th className="py-2 pr-3">Signals</th><th className="py-2 pr-3">Closed</th><th className="py-2 pr-3">Duration</th>
              </tr></thead>
              <tbody>
                {recentCycles.slice(0, 7).map((c: any, i: number) => (
                  <tr key={i} className="border-b border-white/[0.03] hover-row">
                    <td className="py-1.5 pr-3 text-white/50 font-mono">{fmtT(c.last_cycle)}</td>
                    <td className="py-1.5 pr-3"><span className={`text-[9px] font-bold px-1.5 py-0.5 rounded border ${c.status === "OK" ? "bg-emerald-500/15 text-emerald-300 border-emerald-500/25" : c.status === "DEGRADED" ? "bg-amber-500/15 text-amber-300 border-amber-500/25" : "bg-red-500/15 text-red-300 border-red-500/25"}`}>{c.status}</span></td>
                    <td className="py-1.5 pr-3 text-white/60">{c.processed}</td>
                    <td className="py-1.5 pr-3 text-white/60">{c.errors}</td>
                    <td className="py-1.5 pr-3 text-white/60">{c.signals}</td>
                    <td className="py-1.5 pr-3 text-white/60">{c.trades_closed}</td>
                    <td className="py-1.5 pr-3 text-white/40 font-mono">{c.duration_ms}ms</td>
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
            <thead><tr className="border-b border-white/[0.08] text-[9px] text-white/25 uppercase tracking-wider text-left">
              <th className="py-2.5 pr-3">Strategy</th><th className="py-2.5 pr-3">Open</th><th className="py-2.5 pr-3">Closed</th>
              <th className="py-2.5 pr-3">WR</th><th className="py-2.5 pr-3">PF</th><th className="py-2.5 pr-3">PnL</th>
              <th className="py-2.5 pr-3">Avg Bars</th><th className="py-2.5">Status</th>
            </tr></thead>
            <tbody>
              {Object.entries(strats).map(([name, s]: [string, any]) => (
                <tr key={name} className="border-b border-white/[0.04] hover-row">
                  <td className="py-2.5 pr-3 text-white font-semibold">{name}</td>
                  <td className="py-2.5 pr-3 text-white/55">{s.open_trades}</td>
                  <td className="py-2.5 pr-3 text-white/55">{s.closed_trades}</td>
                  <td className="py-2.5 pr-3 text-white/75">{fmtPct(s.win_rate)}</td>
                  <td className="py-2.5 pr-3 text-white/75">{s.profit_factor.toFixed(2)}</td>
                  <td className={`py-2.5 pr-3 font-bold ${pnlC(s.total_pnl)}`}>{fmtPnl(s.total_pnl)}</td>
                  <td className="py-2.5 pr-3 text-white/45">{s.avg_hold_bars?.toFixed(1)}</td>
                  <td className="py-2.5"><span className={`px-2 py-0.5 rounded text-[9px] font-bold border ${s.provisional ? "bg-amber-500/15 text-amber-300 border-amber-500/25" : "bg-emerald-500/15 text-emerald-300 border-emerald-500/25"}`}>{s.provisional ? "WARMING" : "ACTIVE"}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Section>

      <Section title="Asset Class Breakdown">
        <div className="grid grid-cols-2 sm:grid-cols-5 gap-2">
          {Object.entries(classes).map(([cls, s]: [string, any], i) => (
            <div key={cls} className="bg-white/[0.02] border border-white/[0.06] rounded-lg p-3 anim-slide" style={{ animationDelay: `${i * 0.04}s` }}>
              <div className="text-[9px] text-white/35 uppercase tracking-wider font-bold mb-1">{cls}</div>
              <div className="text-xs text-white font-semibold">{s.closed_trades} closed · {s.open_trades} open</div>
              <div className={`text-[11px] font-bold mt-0.5 ${pnlC(s.pnl)}`}>{fmtPnl(s.pnl)} · {fmtPct(s.win_rate)} WR</div>
            </div>
          ))}
        </div>
      </Section>

      {(rankings.best?.length > 0 || rankings.worst?.length > 0) && (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          {rankings.best?.length > 0 && <Section title="🏆 Best Assets">{rankings.best.map((a: any, i: number) => (
            <div key={i} className="flex justify-between items-center py-2 text-xs border-b border-white/[0.04] hover-row px-1 rounded">
              <div><span className="text-white font-semibold">{a.asset}</span> <span className="text-white/30 ml-1 text-[10px]">{a.class}</span></div>
              <div className="text-emerald-400 font-bold">{fmtPnl(a.pnl)} <span className="text-white/25 font-normal">({a.trades}t)</span></div>
            </div>
          ))}</Section>}
          {rankings.worst?.length > 0 && <Section title="⚠️ Worst Assets">{rankings.worst.map((a: any, i: number) => (
            <div key={i} className="flex justify-between items-center py-2 text-xs border-b border-white/[0.04] hover-row px-1 rounded">
              <div><span className="text-white font-semibold">{a.asset}</span> <span className="text-white/30 ml-1 text-[10px]">{a.class}</span></div>
              <div className="text-red-400 font-bold">{fmtPnl(a.pnl)} <span className="text-white/25 font-normal">({a.trades}t)</span></div>
            </div>
          ))}</Section>}
        </div>
      )}
    </div>
  );
}

/* ═══════════════════════════════════════════
   POSITIONS TAB
   ═══════════════════════════════════════════ */
function PositionsTab({ positions, fmtPnl, pnlC }: any) {
  return (
    <Section title={`Open Positions (${positions.length})`}>
      {positions.length > 0 ? (
        <div className="overflow-x-auto"><table className="w-full text-[11px] min-w-[800px]">
          <thead><tr className="border-b border-white/[0.08] text-[9px] text-white/25 uppercase tracking-wider text-left">
            <th className="py-2.5 pr-2">Asset</th><th className="py-2.5 pr-2">Class</th><th className="py-2.5 pr-2">Strategy</th>
            <th className="py-2.5 pr-2">Dir</th><th className="py-2.5 pr-2">Entry</th><th className="py-2.5 pr-2">Current</th>
            <th className="py-2.5 pr-2">SL</th><th className="py-2.5 pr-2">TP</th><th className="py-2.5 pr-2">Unreal PnL</th><th className="py-2.5">Bars</th>
          </tr></thead>
          <tbody>{positions.map((p: any, i: number) => (
            <tr key={i} className="border-b border-white/[0.04] hover-row">
              <td className="py-2 pr-2 text-white font-bold">{p.asset}</td>
              <td className="py-2 pr-2 text-white/40">{p.asset_class}</td>
              <td className="py-2 pr-2 text-white/55">{p.strategy}</td>
              <td className="py-2 pr-2"><span className={`font-bold ${p.direction === "LONG" ? "text-emerald-400" : "text-red-400"}`}>{p.direction}</span></td>
              <td className="py-2 pr-2 font-mono text-white/65">{p.entry_price}</td>
              <td className="py-2 pr-2 font-mono text-white/65">{p.current_price}</td>
              <td className="py-2 pr-2 font-mono text-red-400/50">{p.stop_price || p.stop_loss}</td>
              <td className="py-2 pr-2 font-mono text-emerald-400/50">{p.tp_price || p.take_profit}</td>
              <td className={`py-2 pr-2 font-bold ${pnlC(p.unrealized_pnl || 0)}`}>{fmtPnl(p.unrealized_pnl || 0)}</td>
              <td className="py-2 text-white/45">{p.bars_held || 0}</td>
            </tr>
          ))}</tbody>
        </table></div>
      ) : <div className="text-center py-10 text-white/35 text-sm">No open positions. Signals trigger at 4H bar boundaries when strategy conditions are met.</div>}
    </Section>
  );
}

/* ═══════════════════════════════════════════
   TRADES TAB
   ═══════════════════════════════════════════ */
function TradesTab({ trades, fmtPnl, pnlC, fmtT }: any) {
  return (
    <Section title="Closed Trades (last 50)">
      {trades.length > 0 ? (
        <div className="overflow-x-auto"><table className="w-full text-[11px] min-w-[900px]">
          <thead><tr className="border-b border-white/[0.08] text-[9px] text-white/25 uppercase tracking-wider text-left">
            <th className="py-2.5 pr-2">Asset</th><th className="py-2.5 pr-2">Strategy</th><th className="py-2.5 pr-2">Dir</th>
            <th className="py-2.5 pr-2">Entry</th><th className="py-2.5 pr-2">Exit</th><th className="py-2.5 pr-2">PnL</th>
            <th className="py-2.5 pr-2">Exit</th><th className="py-2.5 pr-2">Bars</th><th className="py-2.5">Closed</th>
          </tr></thead>
          <tbody>{trades.map((t: any, i: number) => (
            <tr key={i} className="border-b border-white/[0.04] hover-row">
              <td className="py-2 pr-2 text-white font-bold">{t.asset}</td>
              <td className="py-2 pr-2 text-white/55">{t.strategy}</td>
              <td className="py-2 pr-2"><span className={`font-bold ${t.direction === "LONG" ? "text-emerald-400" : "text-red-400"}`}>{t.direction}</span></td>
              <td className="py-2 pr-2 font-mono text-white/65">{typeof t.entry_price === "number" ? t.entry_price.toFixed(2) : t.entry_price}</td>
              <td className="py-2 pr-2 font-mono text-white/65">{typeof t.exit_price === "number" ? t.exit_price.toFixed(2) : t.exit_price}</td>
              <td className={`py-2 pr-2 font-bold ${pnlC(t.pnl || 0)}`}>${(t.pnl || 0).toFixed(2)}</td>
              <td className="py-2 pr-2"><span className={`px-1.5 py-0.5 rounded text-[9px] font-bold ${t.exit_reason === "TP" ? "bg-emerald-500/15 text-emerald-300" : t.exit_reason === "SL" ? "bg-red-500/15 text-red-300" : "bg-white/[0.05] text-white/45"}`}>{t.exit_reason}</span></td>
              <td className="py-2 pr-2 text-white/45">{t.bars_held}</td>
              <td className="py-2 text-white/35 text-[10px]">{fmtT(t.exit_time)}</td>
            </tr>
          ))}</tbody>
        </table></div>
      ) : <div className="text-center py-10 text-white/35 text-sm">No closed trades yet. First closes happen after SL/TP/timeout on open positions.</div>}
    </Section>
  );
}

/* ═══════════════════════════════════════════
   LEARNING TAB
   ═══════════════════════════════════════════ */
function LearningTab({ learn }: { learn: any }) {
  return (
    <div className="space-y-4">
      <Section title="Learning Progress">
        <div className="flex items-center gap-4 mb-4">
          <div className="flex-1 bg-white/[0.04] rounded-full h-3.5 overflow-hidden">
            <div className="h-full rounded-full bg-gradient-to-r from-purple-500 via-bah-cyan to-emerald-400 anim-bar" style={{ width: `${learn.progress_pct || 0}%` }} />
          </div>
          <span className="text-sm text-white font-bold">{learn.progress_pct || 0}%</span>
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-5">
          <Stat l="Samples" v={learn.total_samples} />
          <Stat l="Status" v={learn.status?.toUpperCase() || "—"} c={learn.status === "ready" ? "text-emerald-400" : learn.status === "learning" ? "text-bah-cyan" : "text-amber-300"} />
          <Stat l="Trust" v={learn.trust_ready ? "READY" : "WARMING"} c={learn.trust_ready ? "text-emerald-400" : "text-white/30"} />
          <Stat l="Adaptive" v={learn.adaptive_ready ? "READY" : "WARMING"} c={learn.adaptive_ready ? "text-emerald-400" : "text-white/30"} />
        </div>
        <div className="space-y-2">
          {(learn.milestones || []).map((m: any, i: number) => (
            <div key={i} className="flex items-center gap-3 text-xs anim-slide" style={{ animationDelay: `${i * 0.06}s` }}>
              <span className={`w-6 h-6 rounded-full flex items-center justify-center text-[10px] font-bold border ${m.reached ? "bg-emerald-500/20 text-emerald-300 border-emerald-500/40" : "bg-white/[0.03] text-white/25 border-white/10"}`}>{m.reached ? "✓" : i + 1}</span>
              <span className={`font-medium ${m.reached ? "text-white" : "text-white/35"}`}>{m.label}</span>
              <span className="text-[10px] text-white/20">({m.current || 0}/{m.required})</span>
            </div>
          ))}
        </div>
      </Section>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <Section title="By Strategy">
          {Object.keys(learn.by_strategy || {}).length > 0 ? Object.entries(learn.by_strategy).map(([s, c]: [string, any]) => (
            <div key={s} className="flex justify-between py-1.5 text-xs border-b border-white/[0.04]"><span className="text-white font-medium">{s}</span><span className="text-white/45 font-mono">{c}</span></div>
          )) : <p className="text-xs text-white/25">No samples yet</p>}
        </Section>
        <Section title="By Asset Class">
          {Object.keys(learn.by_class || {}).length > 0 ? Object.entries(learn.by_class).map(([c, n]: [string, any]) => (
            <div key={c} className="flex justify-between py-1.5 text-xs border-b border-white/[0.04]"><span className="text-white font-medium">{c}</span><span className="text-white/45 font-mono">{n}</span></div>
          )) : <p className="text-xs text-white/25">No samples yet</p>}
        </Section>
      </div>
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
          <Stat l="Long" v={`$${(expo.long_exposure || 0).toLocaleString()}`} c="text-emerald-400" />
          <Stat l="Short" v={`$${(expo.short_exposure || 0).toLocaleString()}`} c="text-red-400" />
        </div>
      </Section>
      <Section title="Utilization">
        <div className="flex items-center gap-4 mb-3">
          <div className="flex-1 bg-white/[0.04] rounded-full h-3 overflow-hidden">
            <div className="h-full rounded-full bg-bah-cyan/50 anim-bar" style={{ width: `${expo.utilization_pct || 0}%` }} />
          </div>
          <span className="text-sm text-white font-bold">{expo.current_positions || 0} / {expo.max_positions || 20}</span>
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
              <div key={cls} className="bg-white/[0.02] border border-white/[0.06] rounded-lg p-2.5 text-center">
                <div className="text-[9px] text-white/30 uppercase tracking-wider font-semibold">{cls}</div>
                <div className="text-xs text-white font-bold mt-0.5">${val.toLocaleString()}</div>
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

  if (!data || !data.assets) return (
    <Section title="All Assets">
      <div className="text-center py-10 text-white/35 text-sm">Loading asset universe... The first scan may take up to 60 seconds.</div>
    </Section>
  );

  const counts = data.counts || {};
  const assets = data.assets || [];

  // Filter
  let filtered = assets;
  if (filterStatus !== "all") filtered = filtered.filter((a: any) => a.status === filterStatus);
  if (filterClass !== "all") filtered = filtered.filter((a: any) => a.asset_class === filterClass);

  // Sort
  filtered = [...filtered].sort((a: any, b: any) => {
    const va = sortBy === "score" ? a.score : a.asset;
    const vb = sortBy === "score" ? b.score : b.asset;
    if (typeof va === "number") return sortDir === "desc" ? vb - va : va - vb;
    return sortDir === "asc" ? String(va).localeCompare(String(vb)) : String(vb).localeCompare(String(va));
  });

  const toggleSort = (col: "score" | "asset") => {
    if (sortBy === col) setSortDir(d => d === "desc" ? "asc" : "desc");
    else { setSortBy(col); setSortDir(col === "score" ? "desc" : "asc"); }
  };

  const statusCfg: Record<string, { label: string; cls: string }> = {
    ready: { label: "READY", cls: "bg-emerald-500/20 text-emerald-300 border-emerald-500/40" },
    approaching: { label: "APPROACHING", cls: "bg-amber-500/15 text-amber-300 border-amber-500/35" },
    weak: { label: "WEAK", cls: "bg-white/[0.05] text-white/50 border-white/10" },
    no_signal: { label: "NO SIGNAL", cls: "bg-white/[0.02] text-white/25 border-white/[0.06]" },
    no_data: { label: "NO DATA", cls: "bg-red-500/10 text-red-300/50 border-red-500/20" },
    error: { label: "ERROR", cls: "bg-red-500/15 text-red-300 border-red-500/30" },
  };

  const scoreBg = (s: number) => s >= 80 ? "bg-emerald-400" : s >= 60 ? "bg-amber-400" : s >= 20 ? "bg-white/30" : "bg-white/10";
  const uniqueClasses = [...new Set(assets.map((a: any) => a.asset_class))].sort();

  return (
    <div className="space-y-3">
      {/* Summary counts */}
      <div className="flex flex-wrap gap-2">
        {[
          { label: "Total", value: counts.total || 0, cls: "text-white" },
          { label: "Ready", value: counts.ready || 0, cls: "text-emerald-400" },
          { label: "Approaching", value: counts.approaching || 0, cls: "text-amber-300" },
          { label: "Weak", value: counts.weak || 0, cls: "text-white/50" },
          { label: "No Signal", value: counts.no_signal || 0, cls: "text-white/30" },
          { label: "No Data", value: (counts.no_data || 0) + (counts.error || 0), cls: "text-red-400/60" },
        ].map((s, i) => (
          <div key={i} className="bg-white/[0.025] border border-white/[0.06] rounded-lg px-3 py-1.5 flex items-center gap-2">
            <span className={`text-sm font-bold ${s.cls}`}>{s.value}</span>
            <span className="text-[9px] text-white/30 uppercase tracking-wider">{s.label}</span>
          </div>
        ))}
        {data.duration_ms > 0 && (
          <div className="bg-white/[0.015] border border-white/[0.04] rounded-lg px-3 py-1.5 flex items-center">
            <span className="text-[10px] text-white/20 font-mono">scanned in {data.duration_ms}ms</span>
          </div>
        )}
      </div>

      {/* Filters */}
      <div className="flex flex-wrap gap-2 items-center">
        <span className="text-[10px] text-white/30 uppercase tracking-wider">Filter:</span>
        <select value={filterStatus} onChange={e => setFilterStatus(e.target.value)}
          className="bg-white/[0.04] border border-white/[0.08] rounded text-[11px] text-white/70 px-2 py-1 outline-none focus:border-bah-cyan/40">
          <option value="all">All statuses</option>
          <option value="ready">Ready</option>
          <option value="approaching">Approaching</option>
          <option value="weak">Weak</option>
          <option value="no_signal">No Signal</option>
        </select>
        <select value={filterClass} onChange={e => setFilterClass(e.target.value)}
          className="bg-white/[0.04] border border-white/[0.08] rounded text-[11px] text-white/70 px-2 py-1 outline-none focus:border-bah-cyan/40">
          <option value="all">All classes</option>
          {uniqueClasses.map(c => <option key={c} value={c}>{c}</option>)}
        </select>
        <span className="text-[10px] text-white/20 ml-1">{filtered.length} shown</span>
      </div>

      {/* Table */}
      <Section title={`Asset Universe (${filtered.length})`}>
        <div className="overflow-x-auto">
          <table className="w-full text-[11px] min-w-[900px]">
            <thead>
              <tr className="border-b border-white/[0.08] text-[9px] text-white/25 uppercase tracking-wider text-left">
                <th className="py-2.5 px-3 cursor-pointer hover:text-white/50 select-none" onClick={() => toggleSort("score")}>
                  Score {sortBy === "score" ? (sortDir === "desc" ? "↓" : "↑") : ""}
                </th>
                <th className="py-2.5 px-3 cursor-pointer hover:text-white/50 select-none" onClick={() => toggleSort("asset")}>
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
                return (
                  <tr key={i} className={`border-b border-white/[0.03] hover-row ${a.status === "ready" ? "bg-emerald-500/[0.02]" : ""}`}>
                    <td className="py-2 px-3">
                      <div className="flex items-center gap-2">
                        <div className="w-10 h-1.5 bg-white/[0.04] rounded-full overflow-hidden">
                          <div className={`h-full rounded-full ${scoreBg(a.score)}`} style={{ width: `${a.score}%` }} />
                        </div>
                        <span className={`text-xs font-bold min-w-[24px] text-center ${a.score >= 80 ? "text-emerald-300" : a.score >= 60 ? "text-amber-300" : a.score > 0 ? "text-white/50" : "text-white/20"}`}>{a.score}</span>
                      </div>
                    </td>
                    <td className="py-2 px-3 text-white font-semibold">{a.asset}</td>
                    <td className="py-2 px-3 text-white/40">{a.asset_class}</td>
                    <td className="py-2 px-3">
                      <span className={`px-1.5 py-0.5 rounded text-[9px] font-bold border ${st.cls}`}>{st.label}</span>
                    </td>
                    <td className="py-2 px-3 text-white/50">{a.strategy}</td>
                    <td className="py-2 px-3">
                      {a.direction !== "—" ? <span className={`font-bold ${a.direction === "LONG" ? "text-emerald-400" : "text-red-400"}`}>{a.direction}</span> : <span className="text-white/20">—</span>}
                    </td>
                    <td className="py-2 px-3">
                      {a.regime !== "—" ? (
                        <span className={`px-1 py-0.5 rounded text-[9px] font-bold ${
                          a.regime === "TREND" || a.regime === "BREAKOUT" ? "bg-emerald-500/10 text-emerald-300" :
                          a.regime === "BEAR" ? "bg-red-500/10 text-red-300" :
                          "bg-white/[0.03] text-white/35"
                        }`}>{a.regime}</span>
                      ) : <span className="text-white/20">—</span>}
                    </td>
                    <td className="py-2 px-3 text-[10px] text-white/45 font-mono max-w-[160px] truncate">{a.distance_to_trigger}</td>
                    <td className="py-2 px-3 font-mono">
                      {a.indicators?.rsi ? (
                        <span className={a.indicators.rsi < 30 ? "text-emerald-400" : a.indicators.rsi > 70 ? "text-red-400" : "text-white/50"}>{a.indicators.rsi.toFixed(0)}</span>
                      ) : <span className="text-white/15">—</span>}
                    </td>
                    <td className="py-2 px-3 text-[10px] text-white/45 max-w-[220px] truncate">{a.reason}</td>
                  </tr>
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
   SHARED COMPONENTS
   ═══════════════════════════════════════════ */
function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="bg-white/[0.02] border border-white/[0.06] rounded-xl p-4">
      <h3 className="text-[11px] font-bold text-white/70 mb-3 uppercase tracking-[0.08em]">{title}</h3>
      {children}
    </div>
  );
}

function Stat({ l, v, c }: { l: string; v: any; c?: string }) {
  return (
    <div className="text-center">
      <div className={`text-sm font-bold ${c || "text-white"}`}>{v}</div>
      <div className="text-[8px] text-white/25 uppercase tracking-wider font-semibold">{l}</div>
    </div>
  );
}
