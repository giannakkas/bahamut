'use client';

import { useEffect, useState, useCallback } from 'react';
import AppShell from '@/components/layout/AppShell';
import { api } from '@/lib/api';

const CLASS_COLORS: Record<string, string> = {
  fx: 'bg-blue-500/20 text-blue-400 border-blue-500/30',
  crypto: 'bg-purple-500/20 text-purple-400 border-purple-500/30',
  indices: 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30',
  commodities: 'bg-amber-500/20 text-amber-400 border-amber-500/30',
};

function ScoreBar({ score }: { score: number }) {
  const color = score >= 70 ? 'bg-accent-emerald' : score >= 45 ? 'bg-accent-amber' : 'bg-gray-600';
  return (
    <div className="flex items-center gap-2">
      <div className="w-16 h-2 bg-bg-surface rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${score}%` }} />
      </div>
      <span className={`font-mono text-sm font-bold ${score >= 70 ? 'text-accent-emerald' : score >= 45 ? 'text-accent-amber' : 'text-text-muted'}`}>
        {score}
      </span>
    </div>
  );
}

export default function TopPicksPage() {
  const [data, setData] = useState<any>(null);
  const [filter, setFilter] = useState('all');
  const [scanning, setScanning] = useState(false);
  const [scanProgress, setScanProgress] = useState(0);
  const [loading, setLoading] = useState(true);
  const [countdown, setCountdown] = useState('');
  const [modal, setModal] = useState<{ symbol: string; reasons: string[]; direction: string; score: number } | null>(null);

  const SCAN_INTERVAL = 15 * 60; // 30 minutes in seconds

  const fetchData = useCallback(async () => {
    try {
      const res = await api.getTopPicks();
      setData(res);
    } catch (e) { console.error(e); }
    setLoading(false);
  }, []);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 60000);
    return () => clearInterval(interval);
  }, [fetchData]);

  // Countdown timer — always shows time until next scan
  useEffect(() => {
    const tick = () => {
      if (!data?.scanned_at) { setCountdown('--:--'); return; }
      const scannedAt = new Date(data.scanned_at).getTime();
      const nextScan = scannedAt + SCAN_INTERVAL * 1000;
      let remaining = Math.floor((nextScan - Date.now()) / 1000);
      // If overdue, show countdown to the NEXT 30-min cycle from now
      if (remaining <= 0) {
        const overdue = Math.abs(remaining);
        const cyclesPassed = Math.floor(overdue / SCAN_INTERVAL) + 1;
        remaining = (cyclesPassed * SCAN_INTERVAL) - overdue;
      }
      const min = Math.floor(remaining / 60);
      const sec = remaining % 60;
      setCountdown(`${min}:${sec.toString().padStart(2, '0')}`);
    };
    tick();
    const timer = setInterval(tick, 1000);
    return () => clearInterval(timer);
  }, [data?.scanned_at]);

  const triggerScan = async () => {
    setScanning(true);
    setScanProgress(5);
    try {
      await api.triggerScan();
      for (let i = 0; i < 20; i++) {
        setScanProgress(Math.min(95, 5 + (i + 1) * 4.5));
        await new Promise(r => setTimeout(r, 10000));
        const res = await api.getTopPicks();
        if (res?.total_scanned > 0 && res.scanned_at !== data?.scanned_at) {
          setData(res);
          setScanProgress(100);
          break;
        }
      }
    } catch (e) { console.error(e); }
    setTimeout(() => { setScanning(false); setScanProgress(0); }, 500);
  };

  const allResults = data?.all_results || [];
  const filtered = filter === 'all' ? allResults : allResults.filter((r: any) => r.asset_class === filter);
  const topPicks = data?.top_picks || [];
  const scanTime = data?.scanned_at ? new Date(data.scanned_at).toLocaleString('en-GB', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : '—';

  const classStats = {
    fx: allResults.filter((r: any) => r.asset_class === 'fx').length,
    crypto: allResults.filter((r: any) => r.asset_class === 'crypto').length,
    indices: allResults.filter((r: any) => r.asset_class === 'indices').length,
    commodities: allResults.filter((r: any) => r.asset_class === 'commodities').length,
  };

  return (
    <AppShell>
      <div className="space-y-5">
        {/* Header */}
        <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3">
          <div>
            <h1 className="text-2xl font-bold flex items-center gap-3">
              Top Picks
              <span className="text-xs bg-accent-violet/20 text-accent-violet px-2 py-1 rounded-full font-medium">
                {data?.total_scanned || 0} assets scanned
              </span>
            </h1>
            <p className="text-sm text-text-secondary mt-1">
              AI scanner ranks all assets by opportunity strength · Last scan: {scanTime}
            </p>
          </div>
          <div className="flex items-center gap-3">
            <div className="text-right hidden sm:block">
              <div className="text-[10px] text-text-muted uppercase tracking-wider">Next scan</div>
              <div className="text-sm font-mono font-bold text-accent-violet">{countdown}</div>
            </div>
            <button onClick={triggerScan} disabled={scanning}
              className="bg-accent-violet hover:bg-accent-violet/90 text-white font-semibold px-4 py-1.5 rounded-md text-sm disabled:opacity-50 shrink-0">
              {scanning ? 'Scanning ~2 min...' : 'Scan Now'}
            </button>
          </div>
        </div>

        {/* Scan Progress Bar */}
        {scanning && (
          <div className="space-y-1.5">
            <div className="flex items-center justify-between text-xs">
              <span className="text-accent-violet font-semibold flex items-center gap-2">
                <span className="w-2 h-2 rounded-full bg-accent-violet animate-pulse" />
                Scanning {data?.total_scanned || 45} assets...
              </span>
              <span className="text-text-muted font-mono">{Math.round(scanProgress)}%</span>
            </div>
            <div className="w-full h-2 bg-bg-surface rounded-full overflow-hidden">
              <div className="h-full bg-gradient-to-r from-accent-violet to-accent-emerald rounded-full transition-all duration-1000 ease-out"
                style={{ width: `${scanProgress}%` }} />
            </div>
            <div className="text-[10px] text-text-muted">
              Analyzing technical indicators, whale activity, EMA alignment, RSI, MACD, ADX...
            </div>
          </div>
        )}

        {/* Top 5 Cards */}
        {topPicks.length > 0 && (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-3">
            {topPicks.slice(0, 5).map((pick: any, i: number) => (
              <div key={pick.symbol} className={`bg-bg-secondary border rounded-xl p-4 ${i === 0 ? 'border-accent-violet/50 ring-1 ring-accent-violet/20' : 'border-border-default'}`}>
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-2">
                    {i === 0 && <span className="text-accent-violet text-xs font-bold">#1</span>}
                    {i === 1 && <span className="text-text-muted text-xs font-bold">#2</span>}
                    {i === 2 && <span className="text-text-muted text-xs font-bold">#3</span>}
                    {i > 2 && <span className="text-text-muted text-xs font-bold">#{i+1}</span>}
                    <span className="font-bold text-lg">{pick.symbol}</span>
                  </div>
                  <span className={`px-2 py-0.5 rounded text-xs font-bold border ${CLASS_COLORS[pick.asset_class] || 'bg-gray-500/20 text-gray-400'}`}>
                    {pick.asset_class}
                  </span>
                </div>
                <div className="flex items-center justify-between mb-2">
                  <span className={`text-sm font-bold ${pick.direction === 'LONG' ? 'text-accent-emerald' : pick.direction === 'SHORT' ? 'text-accent-crimson' : 'text-text-muted'}`}>
                    {pick.direction === 'LONG' ? '▲' : pick.direction === 'SHORT' ? '▼' : '─'} {pick.direction}
                  </span>
                  <span className="font-mono text-sm text-text-secondary">${pick.price}</span>
                </div>
                <ScoreBar score={pick.score} />
                <div className="mt-2 flex items-center gap-2">
                  {pick.whale_score > 0 && (
                    <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${
                      pick.whale_score >= 20 ? 'bg-accent-emerald/20 text-accent-emerald' : 'bg-accent-amber/20 text-accent-amber'
                    }`}>
                      🐋 {pick.whale_signal === 'EXTREME_SPIKE' ? 'EXTREME' : pick.whale_signal === 'MAJOR_SPIKE' ? 'MAJOR' : 'ACTIVE'} · Vol {pick.volume_ratio}x
                    </span>
                  )}
                </div>
                <div className="mt-1 text-[10px] text-text-muted leading-tight">
                  {pick.reasons?.slice(0, 2).join(' · ')}
                </div>
                {pick.agent_decision && (
                  <div className={`mt-2 pt-2 border-t border-border-default text-xs font-semibold ${
                    pick.agent_decision === 'SIGNAL' || pick.agent_decision === 'STRONG_SIGNAL' ? 'text-accent-violet' : 'text-text-muted'
                  }`}>
                    Agent: {pick.agent_decision} ({(pick.agent_score * 100).toFixed(0)}%)
                  </div>
                )}
              </div>
            ))}
          </div>
        )}

        {/* Filters */}
        <div className="flex flex-wrap items-center gap-2">
          {[
            { key: 'all', label: `All (${allResults.length})` },
            { key: 'indices', label: `Stocks (${classStats.indices})` },
            { key: 'crypto', label: `Crypto (${classStats.crypto})` },
            { key: 'fx', label: `FX (${classStats.fx})` },
            { key: 'commodities', label: `Commodities (${classStats.commodities})` },
          ].map(f => (
            <button key={f.key} onClick={() => setFilter(f.key)}
              className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
                filter === f.key ? 'bg-accent-violet/20 text-accent-violet' : 'bg-bg-secondary text-text-secondary hover:text-text-primary'
              }`}>
              {f.label}
            </button>
          ))}
        </div>

        {/* Full Table */}
        <div className="bg-bg-secondary border border-border-default rounded-lg overflow-x-auto">
          <table className="w-full min-w-[800px]">
            <thead>
              <tr className="border-b border-border-default text-xs text-text-muted uppercase tracking-wider">
                <th className="text-left py-3 px-4">Rank</th>
                <th className="text-left py-3 px-4">Asset</th>
                <th className="text-left py-3 px-4">Class</th>
                <th className="text-right py-3 px-4">Price</th>
                <th className="text-right py-3 px-4">Change</th>
                <th className="text-center py-3 px-4">Direction</th>
                <th className="text-right py-3 px-4">Score</th>
                <th className="text-center py-3 px-4">Whales</th>
                <th className="text-right py-3 px-4">RSI</th>
                <th className="text-right py-3 px-4">ADX</th>
                <th className="text-left py-3 px-4">Reasons</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr><td colSpan={11} className="py-12 text-center text-text-muted text-sm">Loading scanner results...</td></tr>
              ) : filtered.length === 0 ? (
                <tr><td colSpan={11} className="py-12 text-center text-text-muted text-sm">
                  No scan results yet. Click "Scan Now" to analyze all 57 assets, or wait for the next automatic scan (every 15 min).
                </td></tr>
              ) : (
                filtered.map((r: any, i: number) => {
                  const rank = allResults.indexOf(r) + 1;
                  return (
                    <tr key={r.symbol} className="border-b border-border-default hover:bg-bg-tertiary/50 transition-colors">
                      <td className="py-2.5 px-4 text-sm font-mono text-text-muted">{rank}</td>
                      <td className="py-2.5 px-4">
                        <a href={`/agent-council`} className="font-semibold text-sm hover:text-accent-violet transition-colors">{r.symbol}</a>
                      </td>
                      <td className="py-2.5 px-4">
                        <span className={`px-2 py-0.5 rounded text-[10px] font-medium border ${CLASS_COLORS[r.asset_class] || ''}`}>
                          {r.asset_class}
                        </span>
                      </td>
                      <td className="py-2.5 px-4 text-right font-mono text-sm">{r.price}</td>
                      <td className={`py-2.5 px-4 text-right font-mono text-sm ${r.change_pct >= 0 ? 'text-accent-emerald' : 'text-accent-crimson'}`}>
                        {r.change_pct >= 0 ? '+' : ''}{r.change_pct}%
                      </td>
                      <td className="py-2.5 px-4 text-center">
                        <span className={`text-sm font-bold ${r.direction === 'LONG' ? 'text-accent-emerald' : r.direction === 'SHORT' ? 'text-accent-crimson' : 'text-text-muted'}`}>
                          {r.direction === 'LONG' ? '▲' : r.direction === 'SHORT' ? '▼' : '─'}
                        </span>
                      </td>
                      <td className="py-2.5 px-4 text-right"><ScoreBar score={r.score} /></td>
                      <td className="py-2.5 px-4 text-center">
                        {r.whale_score > 0 ? (
                          <span className={`text-xs font-bold px-1.5 py-0.5 rounded ${
                            r.whale_score >= 20 ? 'bg-accent-emerald/20 text-accent-emerald' :
                            r.whale_score >= 10 ? 'bg-accent-amber/20 text-accent-amber' :
                            'bg-bg-surface text-text-muted'
                          }`} title={`Volume ${r.volume_ratio}x avg`}>
                            🐋 {r.whale_score > 20 ? '+++' : r.whale_score > 10 ? '++' : '+'}
                          </span>
                        ) : r.whale_score < 0 ? (
                          <span className="text-xs font-bold px-1.5 py-0.5 rounded bg-accent-crimson/20 text-accent-crimson">
                            🐋 −
                          </span>
                        ) : (
                          <span className="text-xs text-text-muted">—</span>
                        )}
                      </td>
                      <td className={`py-2.5 px-4 text-right font-mono text-sm ${r.rsi < 30 || r.rsi > 70 ? 'text-accent-amber font-bold' : 'text-text-secondary'}`}>
                        {r.rsi}
                      </td>
                      <td className={`py-2.5 px-4 text-right font-mono text-sm ${r.adx > 25 ? 'text-accent-emerald' : 'text-text-muted'}`}>
                        {r.adx}
                      </td>
                      <td className="py-2.5 px-4">
                        <button
                          onClick={() => setModal({ symbol: r.symbol, reasons: r.reasons || [], direction: r.direction, score: r.score })}
                          className="text-xs text-accent-violet hover:text-accent-violet/80 hover:underline text-left max-w-[200px] truncate cursor-pointer"
                          title="Click to see full analysis"
                        >
                          {r.reasons?.join(' · ') || '—'}
                        </button>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>

        {/* Info */}
        <div className="bg-bg-secondary/50 border border-border-default/50 rounded-xl p-4 text-xs text-text-muted">
          <strong className="text-text-secondary">How the scanner works:</strong> Every 15 minutes, Bahamut scans all 45 assets
          (8 FX pairs, 10 cryptocurrencies, 25 stocks, 2 commodities). Each asset gets a technical score based on RSI, EMA alignment,
          MACD momentum, ADX trend strength, and Bollinger Band breakouts. <strong className="text-text-secondary">Whale detection</strong> adds bonus points for
          unusual volume spikes (🐋) — large volume = institutional/whale activity. The top 10 then get a full 6-agent deep analysis.
          Scores above 70 = strong opportunity. Scores below 30 = no clear setup.
        </div>
      </div>

      {/* Reasons Modal */}
      {modal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4" onClick={() => setModal(null)}>
          <div className="absolute inset-0 bg-black/60" />
          <div className="relative bg-bg-secondary border border-border-default rounded-2xl p-6 max-w-md w-full shadow-2xl" onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-3">
                <span className={`text-2xl font-bold ${modal.direction === 'LONG' ? 'text-accent-emerald' : modal.direction === 'SHORT' ? 'text-accent-crimson' : 'text-text-muted'}`}>
                  {modal.direction === 'LONG' ? '▲' : '▼'}
                </span>
                <div>
                  <div className="text-lg font-bold">{modal.symbol}</div>
                  <div className={`text-sm font-semibold ${modal.direction === 'LONG' ? 'text-accent-emerald' : 'text-accent-crimson'}`}>
                    {modal.direction} · Score {modal.score}/100
                  </div>
                </div>
              </div>
              <button onClick={() => setModal(null)} className="text-text-muted hover:text-text-primary text-xl leading-none p-1">✕</button>
            </div>

            <div className="mb-4">
              <div className="text-xs text-text-muted uppercase tracking-wider mb-2">Why this asset scored high</div>
              <div className="space-y-2">
                {modal.reasons.length > 0 ? modal.reasons.map((reason, i) => (
                  <div key={i} className="flex items-start gap-3 p-3 bg-bg-tertiary rounded-lg border border-border-default">
                    <span className="text-accent-violet font-bold text-sm mt-0.5">{i + 1}</span>
                    <span className="text-sm text-text-primary leading-relaxed">{reason}</span>
                  </div>
                )) : (
                  <div className="text-sm text-text-muted p-3">No specific reasons recorded.</div>
                )}
              </div>
            </div>

            <div className="flex gap-2">
              <a href="/agent-council" className="flex-1 text-center py-2 bg-accent-violet/20 text-accent-violet rounded-lg text-sm font-semibold hover:bg-accent-violet/30 transition-colors">
                Deep Analysis in Agent Council
              </a>
              <button onClick={() => setModal(null)} className="px-4 py-2 bg-bg-tertiary text-text-secondary rounded-lg text-sm hover:bg-bg-surface transition-colors">
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </AppShell>
  );
}
