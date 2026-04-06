'use client';
import { useState, useEffect, useCallback, useRef } from 'react';
import AppShell from '@/components/layout/AppShell';

const API = process.env.NEXT_PUBLIC_API_URL || '';
const getH = (): Record<string, string> => {
  const t = typeof window !== 'undefined' ? localStorage.getItem('bahamut_token') : null;
  return t ? { Authorization: `Bearer ${t}` } : {};
};
const fm = (n: number) => `$${Math.abs(n).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const fmS = (n: number) => `${n >= 0 ? '+' : '-'}${fm(n)}`;
const fp = (n: number) => `${n >= 0 ? '+' : ''}${n.toFixed(2)}%`;
const STRAT_NAMES: Record<string, string> = { v5_base: "S1 · EMA Trend", v5_tuned: "S2 · EMA Tuned", v9_breakout: "S3 · Breakout", v10_mean_reversion: "S4 · Mean Reversion" };
const sn = (s: string) => STRAT_NAMES[s] || s;

function useLiveSocket(onEvent: () => void) {
  const [status, setStatus] = useState<'connected' | 'connecting' | 'disconnected'>('disconnected');
  const wsRef = useRef<WebSocket | null>(null);
  const retryRef = useRef(0);
  const cbRef = useRef(onEvent);
  cbRef.current = onEvent;

  useEffect(() => {
    const connect = () => {
      const token = typeof window !== 'undefined' ? localStorage.getItem('bahamut_token') : null;
      if (!token || !API) { setTimeout(connect, 2000); return; }
      try {
        const u = new URL(API);
        const url = `${u.protocol === 'https:' ? 'wss:' : 'ws:'}//${u.host}/ws/admin/live?token=${encodeURIComponent(token)}`;
        setStatus('connecting');
        const ws = new WebSocket(url);
        wsRef.current = ws;
        ws.onopen = () => { setStatus('connected'); retryRef.current = 0; };
        ws.onmessage = (e) => { try { const m = JSON.parse(e.data); if (m.event !== 'pong') cbRef.current(); } catch {} };
        ws.onclose = () => { setStatus('disconnected'); setTimeout(connect, Math.min(30000, 1000 * Math.pow(2, retryRef.current++))); };
        ws.onerror = () => ws.close();
        const iv = setInterval(() => { if (ws.readyState === 1) ws.send(JSON.stringify({ event: 'ping' })); }, 30000);
        ws.addEventListener('close', () => clearInterval(iv));
      } catch { setTimeout(connect, 3000); }
    };
    connect();
    return () => { if (wsRef.current) wsRef.current.close(); };
  }, []);
  return status;
}

export default function Dashboard() {
  const [data, setData] = useState<any>({});
  const [candidates, setCandidates] = useState<any[]>([]);
  const [decisions, setDecisions] = useState<any>(null);
  const [tab, setTab] = useState<'overview' | 'positions' | 'trades' | 'rejected'>('overview');
  const [loading, setLoading] = useState(true);
  const [showAllDec, setShowAllDec] = useState(false);

  const k = data.kpi || {};
  const strats = data.strategy_breakdown || {};
  const classes = data.class_breakdown || {};
  const failedSignals = [
    ...(decisions?.rejected || []).map((s: any) => ({ ...s, _group: 'REJECT' })),
    ...(decisions?.watchlist || []).filter((s: any) => !(decisions?.execute || []).find((e: any) => e.asset === s.asset)).map((s: any) => ({ ...s, _group: 'WATCHLIST' })),
  ];

  const load = useCallback(async () => {
    try {
      const [r1, r2, r3] = await Promise.all([
        fetch(`${API}/api/v1/training/operations`, { headers: getH() }),
        fetch(`${API}/api/v1/training/candidates`, { headers: getH() }),
        fetch(`${API}/api/v1/training/execution-decisions`, { headers: getH() }),
      ]);
      if (r1.ok) setData(await r1.json());
      if (r2.ok) { const d = await r2.json(); if (d?.length > 0) setCandidates(d); }
      if (r3.ok) setDecisions(await r3.json());
    } catch {}
    setLoading(false);
  }, []);

  const wsStatus = useLiveSocket(load);

  useEffect(() => {
    load();
    const iv = setInterval(load, 10000);
    return () => clearInterval(iv);
  }, [load]);

  if (loading) return (
    <AppShell>
      <div className="flex items-center justify-center min-h-[60vh]">
        <div className="w-8 h-8 border-2 border-accent-violet/30 border-t-accent-violet rounded-full animate-spin" />
      </div>
    </AppShell>
  );

  // Use exact same values as backend/admin panel
  const sysEquity = k.equity || k.virtual_capital || 100000;
  const sysPnl = (k.net_pnl || 0) + (k.unrealized_pnl || 0);
  const sysReturn = k.return_pct || 0;
  const sysWinRate = (k.win_rate || 0) * 100;
  const sysRiskPerTrade = k.risk_per_trade || 500;
  const sysOpen = k.open_positions || 0;
  const sysClosed = k.closed_trades || 0;

  return (
    <AppShell>
      <div className="max-w-[1400px] mx-auto space-y-3 sm:space-y-4 px-2 sm:px-0">

        {/* TOP BAR — matches admin panel */}
        <div className="bg-bg-secondary/80 border border-border-default rounded-xl px-3 sm:px-5 py-3">
          <div className="flex flex-wrap items-center gap-3 sm:gap-6">
            <div className="flex flex-wrap items-center gap-3 sm:gap-6 flex-1 min-w-0">
              <div className="min-w-0">
                <div className="text-[10px] text-text-muted uppercase tracking-wider font-semibold">Equity</div>
                <div className="text-lg sm:text-xl font-bold text-text-primary">{fm(sysEquity)}</div>
              </div>
              <div className="hidden sm:block w-px h-8 bg-border-default" />
              <div className="min-w-0">
                <div className="text-[10px] text-text-muted uppercase tracking-wider font-semibold">P&L</div>
                <div className={`text-base sm:text-lg font-bold ${sysPnl >= 0 ? 'text-accent-emerald' : 'text-accent-crimson'}`}>{fmS(sysPnl)}</div>
              </div>
              <div className="hidden sm:block w-px h-8 bg-border-default" />
              <div className="min-w-0">
                <div className="text-[10px] text-text-muted uppercase tracking-wider font-semibold">Return</div>
                <div className={`text-base sm:text-lg font-bold ${sysReturn >= 0 ? 'text-accent-emerald' : 'text-accent-crimson'}`}>{fp(sysReturn)}</div>
              </div>
              <div className="hidden sm:block w-px h-8 bg-border-default" />
              <div className="min-w-0">
                <div className="text-[10px] text-text-muted uppercase tracking-wider font-semibold">Win Rate</div>
                <div className="text-base sm:text-lg font-bold text-text-primary">{sysWinRate.toFixed(1)}%</div>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <span className={`w-2 h-2 rounded-full shrink-0 ${wsStatus === 'connected' ? 'bg-accent-emerald animate-pulse' : 'bg-accent-crimson'}`} />
              <span className="text-[10px] text-text-muted font-mono hidden sm:inline">{wsStatus === 'connected' ? 'LIVE' : 'OFFLINE'}</span>
            </div>
          </div>
        </div>

        {/* KPI ROW */}
        <div className="grid grid-cols-3 sm:grid-cols-3 lg:grid-cols-6 gap-2 sm:gap-3">
          {[
            { l: 'Equity', v: fm(sysEquity), c: 'text-text-primary' },
            { l: 'P&L', v: fmS(sysPnl), c: sysPnl >= 0 ? 'text-accent-emerald' : 'text-accent-crimson' },
            { l: 'Return', v: fp(sysReturn), c: sysReturn >= 0 ? 'text-accent-emerald' : 'text-accent-crimson' },
            { l: 'Risk/Trade', v: fm(sysRiskPerTrade), c: 'text-text-primary' },
            { l: 'Open', v: `${sysOpen}`, c: 'text-accent-cyan' },
            { l: 'Closed', v: `${sysClosed}`, c: 'text-text-primary' },
          ].map((s, i) => (
            <div key={i} className="bg-bg-secondary/60 border border-border-default rounded-xl p-2 sm:p-3 text-center">
              <div className={`text-sm sm:text-lg font-bold ${s.c}`}>{s.v}</div>
              <div className="text-[8px] sm:text-[9px] text-text-muted uppercase tracking-wider mt-0.5">{s.l}</div>
            </div>
          ))}
        </div>

        {/* OPEN POSITIONS */}
        {(data.positions || []).length > 0 && (
          <div className="bg-bg-secondary/60 border border-border-default rounded-xl overflow-hidden">
            <div className="px-4 py-3 flex items-center gap-3 border-b border-border-default">
              <span className="text-sm font-bold text-text-primary">📦 Open Positions</span>
              <span className="px-2 py-0.5 text-[10px] font-bold rounded-full bg-accent-emerald/15 text-accent-emerald border border-accent-emerald/30">{(data.positions || []).length}</span>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-[10px] sm:text-[11px] min-w-[700px]">
                <thead><tr className="border-b border-border-default text-[9px] text-text-muted uppercase tracking-wider text-left">
                  <th className="py-2 px-3">Asset</th><th className="py-2 px-3">Strategy</th><th className="py-2 px-3">Dir</th>
                  <th className="py-2 px-3">Entry</th><th className="py-2 px-3">SL</th><th className="py-2 px-3">TP</th>
                  <th className="py-2 px-3">Risk</th><th className="py-2 px-3">Bars</th><th className="py-2 px-3">PnL</th>
                </tr></thead>
                <tbody>
                  {(data.positions || []).map((p: any, i: number) => (
                    <tr key={i} className="border-b border-border-default/50 hover:bg-bg-tertiary/30">
                      <td className="py-2 px-3 text-text-primary font-bold">{p.asset}</td>
                      <td className="py-2 px-3 text-text-secondary">{sn(p.strategy)}</td>
                      <td className="py-2 px-3"><span className={`font-bold ${p.direction === 'LONG' ? 'text-accent-emerald' : 'text-accent-crimson'}`}>{p.direction}</span></td>
                      <td className="py-2 px-3 text-text-primary font-mono">{fm(p.entry_price)}</td>
                      <td className="py-2 px-3 text-accent-crimson font-mono">{fm(p.stop_price)}</td>
                      <td className="py-2 px-3 text-accent-emerald font-mono">{fm(p.tp_price)}</td>
                      <td className="py-2 px-3 text-text-secondary font-mono">{fm(p.risk_amount)}</td>
                      <td className="py-2 px-3 text-text-muted">{p.bars_held}/{p.max_hold_bars}</td>
                      <td className={`py-2 px-3 font-bold ${(p.unrealized_pnl || 0) >= 0 ? 'text-accent-emerald' : 'text-accent-crimson'}`}>{fmS(p.unrealized_pnl || 0)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* TRADE CANDIDATES */}
        {candidates.length > 0 && (
          <div className="bg-bg-secondary/60 border border-border-default rounded-xl overflow-hidden">
            <div className="px-4 py-3 flex items-center gap-3 border-b border-border-default">
              <span className="text-sm font-bold text-text-primary">🔥 Trade Candidates</span>
              <span className="px-2 py-0.5 text-[10px] font-bold rounded-full bg-accent-cyan/15 text-accent-cyan border border-accent-cyan/30">{candidates.length}</span>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-[10px] sm:text-[11px] min-w-[700px]">
                <thead>
                  <tr className="border-b border-border-default text-left text-[9px] text-text-muted uppercase tracking-wider">
                    <th className="px-3 py-2">Score</th><th className="px-3 py-2">Asset</th><th className="px-3 py-2">Strategy</th>
                    <th className="px-3 py-2">Dir</th><th className="px-3 py-2">Regime</th><th className="px-3 py-2">Distance</th>
                    <th className="px-3 py-2">RSI</th><th className="px-3 py-2">Setup</th>
                  </tr>
                </thead>
                <tbody>
                  {candidates.slice(0, 10).map((c: any, i: number) => (
                    <tr key={i} className="border-b border-border-default/50 hover:bg-bg-tertiary/30">
                      <td className="px-3 py-2">
                        <div className="flex items-center gap-2">
                          <div className="w-10 h-1.5 bg-border-default rounded-full overflow-hidden">
                            <div className={`h-full rounded-full ${c.score >= 80 ? 'bg-accent-emerald' : c.score >= 50 ? 'bg-accent-amber' : 'bg-accent-cyan'}`} style={{ width: `${c.score}%` }} />
                          </div>
                          <span className="text-xs font-bold text-text-primary">{c.score}</span>
                        </div>
                      </td>
                      <td className="px-3 py-2"><span className="font-bold text-text-primary">{c.asset}</span> <span className="text-[9px] text-text-muted">{c.asset_class}</span></td>
                      <td className="px-3 py-2 text-text-secondary">{sn(c.strategy)}</td>
                      <td className="px-3 py-2"><span className={`font-bold ${c.direction === 'LONG' ? 'text-accent-emerald' : 'text-accent-crimson'}`}>{c.direction}</span></td>
                      <td className="px-3 py-2"><span className={`font-bold text-xs ${c.regime === 'TREND' ? 'text-accent-emerald' : c.regime === 'CRASH' ? 'text-accent-crimson' : 'text-accent-amber'}`}>{c.regime}</span></td>
                      <td className="px-3 py-2 text-text-secondary font-mono text-[10px]">{c.distance_to_trigger}</td>
                      <td className="px-3 py-2 font-mono text-text-primary">{c.indicators?.rsi?.toFixed(0) || '—'}</td>
                      <td className="px-3 py-2 max-w-[250px]">
                        {(c.reasons || []).slice(0, 2).map((r: string, j: number) => (
                          <div key={j} className="text-[9px] text-text-muted leading-snug truncate">{r}</div>
                        ))}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* EXECUTION DECISIONS */}
        {decisions && (decisions.execute?.length > 0 || decisions.watchlist?.length > 0) && (() => {
          const exec = decisions.execute || [];
          const watch = decisions.watchlist || [];
          const all = [...exec.map((d: any) => ({ ...d, _g: 'EXECUTE' })), ...watch.map((d: any) => ({ ...d, _g: 'WATCHLIST' }))];
          const visible = showAllDec ? all : all.slice(0, 5);
          return (
            <div className="bg-bg-secondary/60 border border-border-default rounded-xl p-2 sm:p-4">
              <div className="flex flex-wrap items-center gap-2 sm:gap-3 mb-3">
                <span className="text-xs sm:text-sm font-bold text-text-primary">⚡ Execution Decisions</span>
                {exec.length > 0 && <span className="px-2 py-0.5 text-[9px] font-bold rounded bg-accent-emerald/20 text-accent-emerald border border-accent-emerald/30">{exec.length} EXECUTE</span>}
                {watch.length > 0 && <span className="px-2 py-0.5 text-[9px] font-bold rounded bg-accent-amber/15 text-accent-amber border border-accent-amber/30">{watch.length} WATCH</span>}
              </div>
              <div className="space-y-1.5 overflow-x-auto">
                {visible.map((d: any, i: number) => (
                  <div key={i} className={`flex items-center gap-2 sm:gap-3 px-2 sm:px-3 py-1.5 sm:py-2 rounded-lg border min-w-[500px] ${d._g === 'EXECUTE' ? 'bg-accent-emerald/[0.03] border-accent-emerald/15' : 'bg-bg-secondary border-border-default'}`}>
                    <span className={`px-1.5 sm:px-2 py-0.5 text-[8px] sm:text-[9px] font-bold rounded border shrink-0 ${d._g === 'EXECUTE' ? 'bg-accent-emerald/20 text-accent-emerald border-accent-emerald/30' : 'bg-accent-amber/15 text-accent-amber border-accent-amber/30'}`}>{d._g}</span>
                    <span className="text-[10px] sm:text-xs text-text-primary font-bold w-[60px] sm:w-[70px] shrink-0">{d.asset}</span>
                    <span className="text-[9px] sm:text-[10px] text-text-muted w-[45px] sm:w-[50px] shrink-0">{sn(d.strategy)}</span>
                    <span className={`text-[9px] sm:text-[10px] font-bold ${d.direction === 'LONG' ? 'text-accent-emerald' : 'text-accent-crimson'}`}>{d.direction}</span>
                    <span className="text-[9px] sm:text-[10px] text-text-muted flex-1 truncate">{(d.reasons || []).join(' · ')}</span>
                  </div>
                ))}
              </div>
              {all.length > 5 && (
                <button onClick={() => setShowAllDec(!showAllDec)} className="w-full mt-2 py-2 text-[10px] font-bold text-accent-violet hover:text-accent-violet/80 border border-border-default rounded-lg hover:bg-accent-violet/5">
                  {showAllDec ? '▲ Show less' : `▼ Show all ${all.length} decisions`}
                </button>
              )}
            </div>
          );
        })()}

        {/* TABS */}
        <div className="flex border-b border-border-default overflow-x-auto">
          {(['overview', 'positions', 'trades', 'rejected'] as const).map(t => (
            <button key={t} onClick={() => setTab(t)} className={`px-4 py-2.5 text-xs font-semibold border-b-2 transition-all whitespace-nowrap ${tab === t ? 'border-accent-violet text-accent-violet' : 'border-transparent text-text-muted hover:text-text-secondary'}`}>
              {t === 'overview' ? '📊 Overview' : t === 'positions' ? `📦 Positions (${traderPositions})` : t === 'trades' ? `🔁 Trades (${traderClosed})` : `🚫 Rejected (${failedSignals.length})`}
            </button>
          ))}
        </div>

        {/* TAB CONTENT */}
        {tab === 'overview' && (
          <div className="space-y-4">
            <Section title="Strategy Performance">
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead><tr className="border-b border-border-default text-[9px] text-text-muted uppercase tracking-wider text-left">
                    <th className="py-2 pr-3">Strategy</th><th className="py-2 pr-3">Closed</th>
                    <th className="py-2 pr-3">WR</th><th className="py-2 pr-3">PF</th><th className="py-2 pr-3">PnL</th><th className="py-2">Status</th>
                  </tr></thead>
                  <tbody>
                    {Object.entries(strats).map(([name, s]: [string, any]) => (
                      <tr key={name} className="border-b border-border-default/50">
                        <td className="py-2 pr-3 text-text-primary font-semibold">{sn(name)}</td>
                        <td className="py-2 pr-3 text-text-secondary">{s.closed_trades}</td>
                        <td className="py-2 pr-3 text-text-primary">{(s.win_rate * 100).toFixed(1)}%</td>
                        <td className="py-2 pr-3 text-text-primary">{s.profit_factor?.toFixed(2)}</td>
                        <td className={`py-2 pr-3 font-bold ${s.total_pnl >= 0 ? 'text-accent-emerald' : 'text-accent-crimson'}`}>{fmS(s.total_pnl)}</td>
                        <td className="py-2"><span className={`px-2 py-0.5 rounded text-[9px] font-bold border ${s.provisional ? 'bg-accent-amber/15 text-accent-amber border-accent-amber/25' : 'bg-accent-emerald/15 text-accent-emerald border-accent-emerald/25'}`}>{s.provisional ? 'WARMING' : 'ACTIVE'}</span></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Section>
            <Section title="Asset Class Performance">
              <div className="grid grid-cols-2 sm:grid-cols-5 gap-2">
                {Object.entries(classes).map(([cls, s]: [string, any]) => (
                  <div key={cls} className="bg-bg-tertiary/50 border border-border-default rounded-lg p-3">
                    <div className="text-[9px] text-text-muted uppercase tracking-wider font-bold mb-1">{cls}</div>
                    <div className="text-xs text-text-primary font-semibold">{s.closed_trades} closed · {s.open_trades} open</div>
                    <div className={`text-[11px] font-bold mt-0.5 ${s.pnl >= 0 ? 'text-accent-emerald' : 'text-accent-crimson'}`}>{fmS(s.pnl)} · {(s.win_rate * 100).toFixed(1)}% WR</div>
                  </div>
                ))}
              </div>
            </Section>
          </div>
        )}

        {tab === 'positions' && (
          <Section title={`Open Positions (${(data.positions || []).length})`}>
            {(data.positions || []).length === 0 ? (
              <p className="text-xs text-text-muted py-4 text-center">No open positions</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-[10px] sm:text-[11px]">
                  <thead><tr className="border-b border-border-default text-[9px] text-text-muted uppercase tracking-wider text-left">
                    <th className="py-2 px-3">Asset</th><th className="py-2 px-3">Strategy</th><th className="py-2 px-3">Dir</th>
                    <th className="py-2 px-3">Entry</th><th className="py-2 px-3">SL</th><th className="py-2 px-3">TP</th>
                    <th className="py-2 px-3">Risk</th><th className="py-2 px-3">Bars</th><th className="py-2 px-3">PnL</th>
                  </tr></thead>
                  <tbody>
                    {(data.positions || []).map((p: any, i: number) => (
                      <tr key={i} className="border-b border-border-default/50">
                        <td className="py-2 px-3 text-text-primary font-bold">{p.asset}</td>
                        <td className="py-2 px-3 text-text-secondary">{sn(p.strategy)}</td>
                        <td className="py-2 px-3"><span className={`font-bold ${p.direction === 'LONG' ? 'text-accent-emerald' : 'text-accent-crimson'}`}>{p.direction}</span></td>
                        <td className="py-2 px-3 text-text-primary font-mono">{fm(p.entry_price)}</td>
                        <td className="py-2 px-3 text-accent-crimson font-mono">{fm(p.stop_price)}</td>
                        <td className="py-2 px-3 text-accent-emerald font-mono">{fm(p.tp_price)}</td>
                        <td className="py-2 px-3 text-text-secondary font-mono">{fm(p.risk_amount)}</td>
                        <td className="py-2 px-3 text-text-muted">{p.bars_held}/{p.max_hold_bars}</td>
                        <td className={`py-2 px-3 font-bold ${(p.unrealized_pnl || 0) >= 0 ? 'text-accent-emerald' : 'text-accent-crimson'}`}>{fmS(p.unrealized_pnl || 0)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Section>
        )}

        {tab === 'trades' && (
          <Section title={`Closed Trades (${(data.closed_trades || []).length})`}>
            {(data.closed_trades || []).length === 0 ? (
              <p className="text-xs text-text-muted py-4 text-center">No closed trades yet</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-[10px] sm:text-[11px]">
                  <thead><tr className="border-b border-border-default text-[9px] text-text-muted uppercase tracking-wider text-left">
                    <th className="py-2 px-3">Asset</th><th className="py-2 px-3">Strategy</th><th className="py-2 px-3">Dir</th>
                    <th className="py-2 px-3">Entry</th><th className="py-2 px-3">Exit</th><th className="py-2 px-3">PnL</th>
                    <th className="py-2 px-3">Result</th><th className="py-2 px-3">Reason</th><th className="py-2 px-3">Bars</th>
                  </tr></thead>
                  <tbody>
                    {(data.closed_trades || []).slice(0, 30).map((t: any, i: number) => {
                      const pnl = t.pnl || 0;
                      const isFlat = Math.abs(pnl) < 0.01;
                      return (
                        <tr key={i} className="border-b border-border-default/50">
                          <td className="py-2 px-3 text-text-primary font-bold">{t.asset}</td>
                          <td className="py-2 px-3 text-text-secondary">{sn(t.strategy)}</td>
                          <td className="py-2 px-3"><span className={`font-bold ${t.direction === 'LONG' ? 'text-accent-emerald' : 'text-accent-crimson'}`}>{t.direction}</span></td>
                          <td className="py-2 px-3 text-text-primary font-mono">{fm(t.entry_price)}</td>
                          <td className="py-2 px-3 text-text-primary font-mono">{fm(t.exit_price)}</td>
                          <td className={`py-2 px-3 font-bold ${isFlat ? 'text-text-muted' : pnl > 0 ? 'text-accent-emerald' : 'text-accent-crimson'}`}>{fmS(pnl)}</td>
                          <td className="py-2 px-3"><span className={`px-1.5 py-0.5 rounded text-[9px] font-bold ${isFlat ? 'bg-border-default text-text-muted' : pnl > 0 ? 'bg-accent-emerald/15 text-accent-emerald' : 'bg-accent-crimson/15 text-accent-crimson'}`}>{isFlat ? 'FLAT' : pnl > 0 ? 'WIN' : 'LOSS'}</span></td>
                          <td className="py-2 px-3 text-text-muted text-[10px]">{t.exit_reason}</td>
                          <td className="py-2 px-3 text-text-muted">{t.bars_held}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </Section>
        )}

        {tab === 'rejected' && (
          <Section title={`Rejected / Watchlisted (${failedSignals.length})`}>
            {failedSignals.length === 0 ? (
              <p className="text-xs text-text-muted py-4 text-center">No rejected signals in current window</p>
            ) : (
              <div className="space-y-1.5 overflow-x-auto">
                {failedSignals.slice(0, 30).map((s: any, i: number) => (
                  <div key={i} className="flex items-center gap-2 sm:gap-3 px-2 sm:px-3 py-1.5 sm:py-2 rounded-lg border border-border-default/50 min-w-[450px]">
                    <span className={`px-1.5 sm:px-2 py-0.5 text-[8px] sm:text-[9px] font-bold rounded border shrink-0 ${
                      s._group === 'REJECT' ? 'bg-accent-crimson/15 text-accent-crimson border-accent-crimson/30' : 'bg-accent-amber/15 text-accent-amber border-accent-amber/30'
                    }`}>{s._group}</span>
                    <span className="text-[10px] sm:text-xs text-text-primary font-bold w-[55px] sm:w-[70px] shrink-0">{s.asset}</span>
                    <span className="text-[9px] sm:text-[10px] text-text-muted w-[65px] sm:w-[80px] shrink-0">{sn(s.strategy)}</span>
                    <span className={`text-[9px] sm:text-[10px] font-bold w-[35px] sm:w-[40px] shrink-0 ${s.direction === 'LONG' ? 'text-accent-emerald' : 'text-accent-crimson'}`}>{s.direction}</span>
                    <span className="text-[9px] sm:text-[10px] text-text-muted w-[25px] sm:w-[30px] shrink-0 text-center">{s.readiness_score}</span>
                    <span className="text-[9px] sm:text-[10px] text-text-muted flex-1 truncate">{(s.reasons || []).join(' · ')}</span>
                  </div>
                ))}
              </div>
            )}
          </Section>
        )}
      </div>
    </AppShell>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="bg-bg-secondary/60 border border-border-default rounded-xl overflow-hidden">
      <div className="px-4 py-3 border-b border-border-default">
        <span className="text-sm font-bold text-text-primary">{title}</span>
      </div>
      <div className="p-4">{children}</div>
    </div>
  );
}
