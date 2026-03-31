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
  const [showAddFunds, setShowAddFunds] = useState(false);
  const [fundAmount, setFundAmount] = useState('');
  const [editingAlloc, setEditingAlloc] = useState(false);
  const [allocInput, setAllocInput] = useState('');

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

  // Demo/Live state — mode is controlled by sidebar toggle
  const [demoBalance, setDemoBalance] = useState(0);
  const [liveBalance, setLiveBalance] = useState(0);
  const [demoAllocation, setDemoAllocation] = useState(0);
  const [liveAllocation, setLiveAllocation] = useState(0);
  const [tradingMode, setTradingMode] = useState<'demo' | 'live'>('demo');
  useEffect(() => {
    if (typeof window === 'undefined') return;
    const savedDemo = localStorage.getItem('bahamut_demo_balance');
    if (savedDemo) setDemoBalance(parseFloat(savedDemo));
    const savedLive = localStorage.getItem('bahamut_live_balance');
    if (savedLive) setLiveBalance(parseFloat(savedLive));
    const savedDemoAlloc = localStorage.getItem('bahamut_demo_allocation');
    if (savedDemoAlloc) setDemoAllocation(parseFloat(savedDemoAlloc));
    const savedLiveAlloc = localStorage.getItem('bahamut_live_allocation');
    if (savedLiveAlloc) setLiveAllocation(parseFloat(savedLiveAlloc));
    const syncMode = () => {
      const mode = localStorage.getItem('bahamut_trading_mode');
      if (mode === 'live' || mode === 'demo') setTradingMode(mode);
    };
    syncMode();
    const iv = setInterval(syncMode, 1000);
    return () => clearInterval(iv);
  }, []);

  const addFunds = (amount: number) => {
    const newBal = Math.min(100000, demoBalance + amount);
    setDemoBalance(newBal);
    localStorage.setItem('bahamut_demo_balance', String(newBal));
    // Auto-set allocation to balance if allocation was 0 or exceeded
    if (demoAllocation === 0 || demoAllocation > newBal) {
      setDemoAllocation(newBal);
      localStorage.setItem('bahamut_demo_allocation', String(newBal));
    }
    setShowAddFunds(false);
    setFundAmount('');
  };

  const saveAllocation = (val: number) => {
    const capped = Math.min(val, userBalance);
    const key = tradingMode === 'demo' ? 'bahamut_demo_allocation' : 'bahamut_live_allocation';
    if (tradingMode === 'demo') setDemoAllocation(capped);
    else setLiveAllocation(capped);
    localStorage.setItem(key, String(capped));
    setEditingAlloc(false);
    setAllocInput('');
  };

  if (loading) return (
    <AppShell>
      <div className="flex items-center justify-center min-h-[60vh]">
        <div className="w-8 h-8 border-2 border-accent-violet/30 border-t-accent-violet rounded-full animate-spin" />
      </div>
    </AppShell>
  );

  // Balance logic per mode — trader's own numbers, not system training data
  const userBalance = tradingMode === 'demo' ? demoBalance : liveBalance;
  const userAllocation = tradingMode === 'demo' ? demoAllocation : liveAllocation;
  const userPnl = 0; // Trader's personal P&L — will be calculated from their trades once per-user portfolios are built
  const userRetPct = userBalance > 0 ? (userPnl / userBalance) * 100 : 0;

  return (
    <AppShell>
      <div className="max-w-[1400px] mx-auto space-y-4">

        {/* TOP BAR */}
        <div className="bg-bg-secondary/80 border border-border-default rounded-xl px-5 py-3">
          <div className="flex items-center gap-4">
            <div className="flex items-center gap-6 flex-1">
              <div>
                <div className="text-[10px] text-text-muted uppercase tracking-wider font-semibold">Total Balance</div>
                <div className="text-xl font-bold text-text-primary">{fm(userBalance)}</div>
              </div>
              <div className="w-px h-8 bg-border-default" />
              <div>
                <div className="text-[10px] text-text-muted uppercase tracking-wider font-semibold">Trading Allocation</div>
                {editingAlloc ? (
                  <div className="flex items-center gap-1">
                    <span className="text-lg text-text-muted">$</span>
                    <input type="number" autoFocus value={allocInput}
                      onChange={e => setAllocInput(e.target.value)}
                      onKeyDown={e => { if (e.key === 'Enter') saveAllocation(parseFloat(allocInput) || 0); if (e.key === 'Escape') setEditingAlloc(false); }}
                      onBlur={() => { if (allocInput) saveAllocation(parseFloat(allocInput) || 0); else setEditingAlloc(false); }}
                      className="w-28 text-lg font-bold bg-transparent border-b border-accent-violet text-accent-violet outline-none" />
                  </div>
                ) : (
                  <div className="text-xl font-bold text-accent-violet cursor-pointer hover:text-accent-violet/70 transition-all" onClick={() => { setEditingAlloc(true); setAllocInput(String(userAllocation)); }}>
                    {fm(userAllocation)} <span className="text-[9px] text-text-muted">✎</span>
                  </div>
                )}
              </div>
              <div className="w-px h-8 bg-border-default" />
              <div>
                <div className="text-[10px] text-text-muted uppercase tracking-wider font-semibold">P&L</div>
                <div className={`text-lg font-bold ${userPnl >= 0 ? 'text-accent-emerald' : 'text-accent-crimson'}`}>{fmS(userPnl)} <span className="text-xs text-text-muted">{fp(userRetPct)}</span></div>
              </div>
            </div>

            <div className="flex items-center gap-2">
              {tradingMode === 'demo' ? (
                <button onClick={() => setShowAddFunds(!showAddFunds)}
                  className="px-3 py-1.5 text-[10px] font-bold rounded-lg bg-accent-violet/15 text-accent-violet border border-accent-violet/30 hover:bg-accent-violet/25 transition-all">
                  + Add Virtual Funds
                </button>
              ) : (
                <button onClick={() => setShowAddFunds(!showAddFunds)}
                  className="px-3 py-1.5 text-[10px] font-bold rounded-lg bg-accent-emerald/15 text-accent-emerald border border-accent-emerald/30 hover:bg-accent-emerald/25 transition-all">
                  💳 Add Real Funds
                </button>
              )}
              <span className={`w-2 h-2 rounded-full ${wsStatus === 'connected' ? 'bg-accent-emerald animate-pulse' : 'bg-accent-crimson'}`} />
              <span className="text-[10px] text-text-muted font-mono">{wsStatus === 'connected' ? 'LIVE' : 'OFFLINE'}</span>
            </div>
          </div>

          {/* Add Funds Panel — Demo */}
          {showAddFunds && tradingMode === 'demo' && (
            <div className="mt-3 pt-3 border-t border-border-default flex items-center gap-3 flex-wrap">
              <span className="text-[10px] text-text-muted">Add virtual funds (max $100K):</span>
              <div className="flex gap-2">
                {[5000, 10000, 25000, 50000].map(amt => (
                  <button key={amt} onClick={() => addFunds(amt)} disabled={userBalance >= 100000}
                    className="px-3 py-1 text-[10px] font-bold rounded-lg border border-border-default bg-bg-tertiary text-text-secondary hover:bg-accent-violet/10 hover:text-accent-violet hover:border-accent-violet/30 transition-all disabled:opacity-30">
                    +{fm(amt)}
                  </button>
                ))}
              </div>
              <input type="number" placeholder="Custom" value={fundAmount}
                onChange={e => setFundAmount(e.target.value)}
                className="w-24 px-2 py-1 text-[10px] rounded-lg border border-border-default bg-bg-tertiary text-text-primary placeholder-text-muted outline-none focus:border-accent-violet" />
              {fundAmount && (
                <button onClick={() => addFunds(Math.min(parseFloat(fundAmount) || 0, 100000 - userBalance))}
                  className="px-3 py-1 text-[10px] font-bold rounded-lg bg-accent-violet text-white hover:bg-accent-violet/80 transition-all">Add</button>
              )}
              <span className="text-[9px] text-text-muted ml-auto">{fm(userBalance)} / {fm(100000)}</span>
            </div>
          )}

          {/* Add Funds Panel — Live (Stripe placeholder) */}
          {showAddFunds && tradingMode === 'live' && (
            <div className="mt-3 pt-3 border-t border-border-default">
              <div className="flex items-center gap-3 flex-wrap">
                <span className="text-[10px] text-text-muted">Add real funds via card:</span>
                <div className="flex gap-2">
                  {[100, 500, 1000, 5000].map(amt => (
                    <button key={amt} disabled
                      className="px-3 py-1 text-[10px] font-bold rounded-lg border border-border-default bg-bg-tertiary text-text-secondary opacity-50 cursor-not-allowed">
                      ${amt.toLocaleString()}
                    </button>
                  ))}
                </div>
                <span className="text-[9px] text-accent-amber">Coming soon — Stripe integration</span>
              </div>
            </div>
          )}
        </div>

        {/* KPI ROW */}
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
          {[
            { l: 'Equity', v: fm(userBalance), c: 'text-text-primary' },
            { l: 'P&L', v: fmS(userPnl), c: userPnl >= 0 ? 'text-accent-emerald' : 'text-accent-crimson' },
            { l: 'Return', v: fp(userRetPct), c: userRetPct >= 0 ? 'text-accent-emerald' : 'text-accent-crimson' },
            { l: 'Risk/Trade', v: fm(k.risk_per_trade || 500), c: 'text-text-primary' },
            { l: 'Open', v: `${k.open_positions || 0}`, c: 'text-accent-cyan' },
            { l: 'Closed', v: `${k.closed_trades || 0}`, c: 'text-text-primary' },
          ].map((s, i) => (
            <div key={i} className="bg-bg-secondary/60 border border-border-default rounded-xl p-3 text-center">
              <div className={`text-lg font-bold ${s.c}`}>{s.v}</div>
              <div className="text-[9px] text-text-muted uppercase tracking-wider mt-0.5">{s.l}</div>
              {s.sub && <div className="text-[9px] text-text-muted mt-0.5">{s.sub}</div>}
            </div>
          ))}
        </div>

        {/* TRADE CANDIDATES */}
        {candidates.length > 0 && (
          <div className="bg-bg-secondary/60 border border-border-default rounded-xl overflow-hidden">
            <div className="px-4 py-3 flex items-center gap-3 border-b border-border-default">
              <span className="text-sm font-bold text-text-primary">🔥 Trade Candidates</span>
              <span className="px-2 py-0.5 text-[10px] font-bold rounded-full bg-accent-cyan/15 text-accent-cyan border border-accent-cyan/30">{candidates.length}</span>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-[11px] min-w-[900px]">
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
                      <td className="px-3 py-2 text-text-secondary">{c.strategy}</td>
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
            <div className="bg-bg-secondary/60 border border-border-default rounded-xl p-4">
              <div className="flex items-center gap-3 mb-3">
                <span className="text-sm font-bold text-text-primary">⚡ Execution Decisions</span>
                {exec.length > 0 && <span className="px-2 py-0.5 text-[10px] font-bold rounded bg-accent-emerald/20 text-accent-emerald border border-accent-emerald/30">{exec.length} EXECUTE</span>}
                {watch.length > 0 && <span className="px-2 py-0.5 text-[10px] font-bold rounded bg-accent-amber/15 text-accent-amber border border-accent-amber/30">{watch.length} WATCH</span>}
              </div>
              <div className="space-y-1.5">
                {visible.map((d: any, i: number) => (
                  <div key={i} className={`flex items-center gap-3 px-3 py-2 rounded-lg border ${d._g === 'EXECUTE' ? 'bg-accent-emerald/[0.03] border-accent-emerald/15' : 'bg-bg-secondary border-border-default'}`}>
                    <span className={`px-2 py-0.5 text-[9px] font-bold rounded border ${d._g === 'EXECUTE' ? 'bg-accent-emerald/20 text-accent-emerald border-accent-emerald/30' : 'bg-accent-amber/15 text-accent-amber border-accent-amber/30'}`}>{d._g}</span>
                    <span className="text-xs text-text-primary font-bold w-[70px]">{d.asset}</span>
                    <span className="text-[10px] text-text-muted w-[50px]">{d.strategy}</span>
                    <span className={`text-[10px] font-bold ${d.direction === 'LONG' ? 'text-accent-emerald' : 'text-accent-crimson'}`}>{d.direction}</span>
                    <span className="text-[10px] text-text-muted flex-1 truncate">{(d.reasons || []).join(' · ')}</span>
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
              {t === 'overview' ? '📊 Overview' : t === 'positions' ? `📦 Positions (${k.open_positions || 0})` : t === 'trades' ? `🔁 Trades (${k.closed_trades || 0})` : `🚫 Rejected (${failedSignals.length})`}
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
                        <td className="py-2 pr-3 text-text-primary font-semibold">{name}</td>
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
                <table className="w-full text-[11px]">
                  <thead><tr className="border-b border-border-default text-[9px] text-text-muted uppercase tracking-wider text-left">
                    <th className="py-2 px-3">Asset</th><th className="py-2 px-3">Strategy</th><th className="py-2 px-3">Dir</th>
                    <th className="py-2 px-3">Entry</th><th className="py-2 px-3">SL</th><th className="py-2 px-3">TP</th>
                    <th className="py-2 px-3">Risk</th><th className="py-2 px-3">Bars</th><th className="py-2 px-3">PnL</th>
                  </tr></thead>
                  <tbody>
                    {(data.positions || []).map((p: any, i: number) => (
                      <tr key={i} className="border-b border-border-default/50">
                        <td className="py-2 px-3 text-text-primary font-bold">{p.asset}</td>
                        <td className="py-2 px-3 text-text-secondary">{p.strategy}</td>
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
                <table className="w-full text-[11px]">
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
                          <td className="py-2 px-3 text-text-secondary">{t.strategy}</td>
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
              <div className="space-y-1.5">
                {failedSignals.slice(0, 30).map((s: any, i: number) => (
                  <div key={i} className="flex items-center gap-3 px-3 py-2 rounded-lg border border-border-default/50">
                    <span className={`px-2 py-0.5 text-[9px] font-bold rounded border shrink-0 ${
                      s._group === 'REJECT' ? 'bg-accent-crimson/15 text-accent-crimson border-accent-crimson/30' : 'bg-accent-amber/15 text-accent-amber border-accent-amber/30'
                    }`}>{s._group}</span>
                    <span className="text-xs text-text-primary font-bold w-[70px] shrink-0">{s.asset}</span>
                    <span className="text-[10px] text-text-muted w-[80px] shrink-0">{s.strategy}</span>
                    <span className={`text-[10px] font-bold w-[40px] shrink-0 ${s.direction === 'LONG' ? 'text-accent-emerald' : 'text-accent-crimson'}`}>{s.direction}</span>
                    <span className="text-[10px] text-text-muted w-[30px] shrink-0 text-center">{s.readiness_score}</span>
                    <span className="text-[10px] text-text-muted flex-1 truncate">{(s.reasons || []).join(' · ')}</span>
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
