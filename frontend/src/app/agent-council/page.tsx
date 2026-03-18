'use client';

import { useEffect, useState } from 'react';
import dynamic from 'next/dynamic';
import AppShell from '@/components/layout/AppShell';
import { api } from '@/lib/api';
import { AGENT_META } from '@/lib/types';

// Dynamic import - Lightweight Charts needs browser APIs
const CandlestickChart = dynamic(() => import('@/components/charts/CandlestickChart'), { ssr: false });

export default function AgentCouncilPage() {
  const [trustScores, setTrustScores] = useState<any>(null);
  const [cycling, setCycling] = useState(false);
  const [cycleResult, setCycleResult] = useState<any>(null);
  const [selectedAsset, setSelectedAsset] = useState('EURUSD');
  const [selectedTF, setSelectedTF] = useState('4H');
  const [selectedProfile, setSelectedProfile] = useState('BALANCED');
  const [thresholds, setThresholds] = useState<any>(null);
  const [agentHealth, setAgentHealth] = useState<any>(null);
  const [candles, setCandles] = useState<any[]>([]);
  const [chartLoading, setChartLoading] = useState(false);


  const getAssetClass = (symbol: string) => {
    if (['XAUUSD', 'XAGUSD', 'WTIUSD', 'BCOUSD'].includes(symbol)) return 'commodities';
    if (['BTCUSD', 'ETHUSD', 'SOLUSD', 'BNBUSD', 'XRPUSD', 'ADAUSD', 'DOGEUSD', 'AVAXUSD', 'DOTUSD', 'LINKUSD', 'MATICUSD', 'SHIBUSD'].includes(symbol)) return 'crypto';
    if (symbol.includes('USD') && symbol.length === 6) return 'fx';
    if (['EURGBP'].includes(symbol)) return 'fx';
    return 'indices';
  };

  const loadData = async (asset?: string) => {
    const a = asset || selectedAsset;
    const [ts, th, ah, lc] = await Promise.allSettled([
      api.getTrustScores(), api.getThresholds(), api.getAgentHealth(),
      api.getLatestCycle(a),
    ]);
    if (ts.status === 'fulfilled') setTrustScores(ts.value);
    if (th.status === 'fulfilled') setThresholds(th.value);
    if (ah.status === 'fulfilled') setAgentHealth(ah.value);
    if (lc.status === 'fulfilled' && lc.value?.decision) setCycleResult(lc.value);
  };

  const loadCandles = async (asset?: string) => {
    setChartLoading(true);
    const a = asset || selectedAsset;
    for (let attempt = 0; attempt < 3; attempt++) {
      try {
        const res = await api.getCandles(a, selectedTF, 200);
        if (res?.candles?.length > 0) {
          setCandles(res.candles);
          setChartLoading(false);
          return;
        }
      } catch (e) { console.error('Chart data error:', e); }
      // Wait before retry
      if (attempt < 2) await new Promise(r => setTimeout(r, 2000));
    }
    setChartLoading(false);
  };

  useEffect(() => {
    loadData();
    loadCandles();
  }, []);

  const handleAssetChange = (asset: string) => {
    setSelectedAsset(asset);
    setCycleResult(null);
    // Don't clear candles — keep old chart visible while new data loads
    loadData(asset);
    loadCandles(asset);
  };

  const triggerCycle = async () => {
    setCycling(true);
    setCycleResult(null);
    try {
      await api.triggerCycle(selectedAsset, getAssetClass(selectedAsset), selectedTF, selectedProfile);
      for (let i = 0; i < 15; i++) {
        await new Promise(r => setTimeout(r, 2000));
        try {
          const result = await api.getLatestCycle(selectedAsset);
          if (result?.decision) { setCycleResult(result); break; }
        } catch {}
      }
      loadCandles(); // refresh chart
    } catch (e: any) {
      setCycleResult({ error: e.message });
    } finally {
      setCycling(false);
    }
  };

  const decision = cycleResult?.decision;
  const agentOutputs = cycleResult?.agent_outputs || [];
  const challenges = cycleResult?.challenges || [];

  return (
    <AppShell>
      <div className="space-y-5">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold">Agent Council</h1>
            <div className="flex items-center gap-2 mt-1">
              <span className="text-sm text-text-secondary">{agentHealth?.agent_count || 0} agents active</span>
              {agentHealth?.data_source && agentHealth.data_source !== 'none' ? (
                <span className="flex items-center gap-1.5 text-sm text-accent-emerald">
                  <span className="relative flex h-2 w-2">
                    <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-accent-emerald opacity-75" style={{ animationDuration: '3s' }}></span>
                    <span className="relative inline-flex rounded-full h-2 w-2 bg-accent-emerald"></span>
                  </span>
                  Live Data Connected
                </span>
              ) : (
                <span className="text-sm text-accent-amber">· Demo data</span>
              )}
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2 sm:gap-3">
            <select value={selectedAsset} onChange={e => handleAssetChange(e.target.value)}
              className="bg-bg-surface border border-border-default rounded-md px-3 py-1.5 text-sm text-text-primary">
              {[
                // FX
                'EURUSD','GBPUSD','USDJPY','AUDUSD','USDCHF','USDCAD','NZDUSD','EURGBP',
                // Commodities
                'XAUUSD','XAGUSD',
                // Crypto
                'BTCUSD','ETHUSD','SOLUSD','BNBUSD','XRPUSD','ADAUSD','DOGEUSD','AVAXUSD','DOTUSD','LINKUSD','MATICUSD','SHIBUSD',
                // Stocks
                'AAPL','MSFT','GOOGL','AMZN','NVDA','META','TSLA','JPM','V','UNH','MA','HD','PG','JNJ',
                'AMD','CRM','NFLX','ADBE','INTC','PYPL','UBER','SQ','SHOP','SNOW','PLTR','COIN','RBLX','MARA','RIOT',
              ].map(a => <option key={a} value={a}>{a}</option>)}
            </select>
            <select value={selectedTF} onChange={e => { setSelectedTF(e.target.value); loadCandles(); }}
              className="bg-bg-surface border border-border-default rounded-md px-3 py-1.5 text-sm text-text-primary">
              {['1H','4H','1D'].map(t => <option key={t} value={t}>{t}</option>)}
            </select>
            <select value={selectedProfile} onChange={e => setSelectedProfile(e.target.value)}
              className="bg-bg-surface border border-border-default rounded-md px-3 py-1.5 text-sm text-text-primary">
              {['CONSERVATIVE','BALANCED','AGGRESSIVE'].map(p => <option key={p} value={p}>{p}</option>)}
            </select>
            <button onClick={triggerCycle} disabled={cycling}
              className="bg-accent-violet hover:bg-accent-violet/90 text-white font-semibold px-4 py-1.5 rounded-md text-sm disabled:opacity-50">
              {cycling ? 'Running cycle...' : 'Trigger Signal Cycle'}
            </button>
          </div>
        </div>

        {/* Price Chart */}
        <div className="bg-bg-secondary border border-border-default rounded-lg p-4">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-semibold">{selectedAsset} · {selectedTF}
              {candles.length > 0 && <span className="text-text-muted font-normal ml-2">({candles.length} candles)</span>}
            </h3>
            {chartLoading && <span className="text-xs text-text-muted">Loading...</span>}
          </div>
          <CandlestickChart loading={chartLoading}
            candles={candles}
            height={350}
            signalDirection={decision?.direction}
            signalPrice={cycleResult?.market_price}
          />
        </div>

        {/* Consensus Panel */}
        {decision && !cycleResult?.error && (
          <div className="bg-bg-secondary border border-border-default rounded-lg p-5">
            <div className="flex items-center gap-6">
              <div className="flex-shrink-0 w-24 h-24 relative">
                <svg viewBox="0 0 100 100" className="w-full h-full -rotate-90">
                  <circle cx="50" cy="50" r="42" stroke="#2A2A4A" strokeWidth="8" fill="none" />
                  <circle cx="50" cy="50" r="42" strokeWidth="8" fill="none"
                    stroke={decision.final_score > 0.7 ? '#10B981' : decision.final_score > 0.5 ? '#F59E0B' : '#E94560'}
                    strokeDasharray={`${decision.final_score * 264} 264`} strokeLinecap="round" />
                </svg>
                <div className="absolute inset-0 flex items-center justify-center">
                  <span className="font-mono text-2xl font-bold">{(decision.final_score * 100).toFixed(0)}</span>
                </div>
              </div>
              <div className="flex-1 grid grid-cols-4 gap-4">
                <div>
                  <div className="text-xs text-text-muted">Direction</div>
                  <div className={`text-lg font-bold ${decision.direction === 'LONG' ? 'text-accent-emerald' : decision.direction === 'SHORT' ? 'text-accent-crimson' : 'text-text-muted'}`}>
                    {decision.direction === 'LONG' ? '▲' : decision.direction === 'SHORT' ? '▼' : '─'} {decision.direction}
                  </div>
                </div>
                <div>
                  <div className="text-xs text-text-muted">Decision</div>
                  <div className={`text-lg font-bold ${decision.decision === 'STRONG_SIGNAL' || decision.decision === 'SIGNAL' ? 'text-accent-violet' : 'text-text-secondary'}`}>{decision.decision}</div>
                </div>
                <div>
                  <div className="text-xs text-text-muted">Agreement</div>
                  <div className="text-lg font-mono font-bold">{(decision.agreement_pct * 100).toFixed(0)}%</div>
                </div>
                <div>
                  <div className="text-xs text-text-muted">Mode</div>
                  <div className="text-lg font-bold">{decision.execution_mode}</div>
                </div>
              </div>
            </div>
            <div className="mt-3 flex items-center gap-3">
              <span className="flex items-center gap-1.5 text-[11px] text-accent-emerald">
                <span className="relative flex h-1.5 w-1.5">
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-accent-emerald opacity-75" style={{ animationDuration: '3s' }}></span>
                  <span className="relative inline-flex rounded-full h-1.5 w-1.5 bg-accent-emerald"></span>
                </span>
                Live Data
              </span>
              {cycleResult.market_price && (
                <span className="text-xs text-text-muted">Price: <span className="font-mono text-text-primary">{cycleResult.market_price}</span></span>
              )}
              <span className="text-xs text-text-muted">Elapsed: <span className="font-mono">{cycleResult.elapsed_ms}ms</span></span>
            </div>
          </div>
        )}

        {cycleResult?.error && (
          <div className="p-3 bg-accent-crimson/10 border border-accent-crimson/30 rounded-md text-accent-crimson text-sm">{cycleResult.error}</div>
        )}

        {/* Decision Explanation */}
        {cycleResult?.explanation && (
          <div className="bg-bg-secondary border border-border-default rounded-lg p-4">
            <h3 className="text-sm font-semibold mb-2">Decision Reasoning</h3>
            <p className="text-xs text-text-secondary mb-3">{cycleResult.explanation.narrative}</p>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
              {cycleResult.explanation.factors?.map((f: any, i: number) => {
                const color = f.impact === 'positive' ? 'text-accent-emerald' :
                              f.impact === 'negative' ? 'text-accent-amber' :
                              f.impact === 'blocking' ? 'text-accent-crimson' : 'text-text-secondary';
                const bg = f.impact === 'positive' ? 'bg-accent-emerald/5 border-accent-emerald/20' :
                           f.impact === 'negative' ? 'bg-accent-amber/5 border-accent-amber/20' :
                           f.impact === 'blocking' ? 'bg-accent-crimson/5 border-accent-crimson/20' :
                           'bg-bg-primary border-border-default';
                return (
                  <div key={i} className={`rounded border p-2 ${bg}`}>
                    <div className="flex items-center justify-between mb-0.5">
                      <span className="text-[10px] text-text-muted uppercase">{f.name}</span>
                      <span className={`text-[10px] font-semibold ${color}`}>{f.status}</span>
                    </div>
                    {f.value !== 0 && <div className={`text-sm font-mono font-semibold ${color}`}>{f.value.toFixed(2)}</div>}
                    <div className="text-[10px] text-text-muted mt-0.5 leading-tight">{f.detail}</div>
                  </div>
                );
              })}
            </div>
            {cycleResult.explanation.blocked_flags?.length > 0 && (
              <div className="mt-2 pt-2 border-t border-border-default">
                {cycleResult.explanation.blocked_flags.map((f: string, i: number) => (
                  <span key={i} className="text-[10px] font-mono text-accent-crimson mr-2">{f}</span>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Agent Outputs */}
        {agentOutputs.length > 0 && (
          <div className="bg-bg-secondary border border-border-default rounded-lg p-4">
            <h3 className="text-sm font-semibold mb-3">Agent Outputs ({agentOutputs.length} agents)</h3>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
              {agentOutputs.map((output: any) => {
                const meta = AGENT_META[output.agent_id] || { name: output.agent_id, icon: '?', color: '#888' };
                const arrow = output.directional_bias === 'LONG' ? '▲' : output.directional_bias === 'SHORT' ? '▼' : '─';
                const arrowColor = output.directional_bias === 'LONG' ? 'text-accent-emerald' : output.directional_bias === 'SHORT' ? 'text-accent-crimson' : 'text-text-muted';
                return (
                  <div key={output.agent_id} className="bg-bg-tertiary border border-border-default rounded-md p-3">
                    <div className="flex items-center gap-2 mb-2">
                      <div className="w-7 h-7 rounded-full flex items-center justify-center text-[10px] font-bold text-white" style={{ backgroundColor: meta.color }}>{meta.icon}</div>
                      <div className="text-sm font-semibold">{meta.name}</div>
                      <div className={`ml-auto text-lg font-bold ${arrowColor}`}>{arrow}</div>
                    </div>
                    <div className="flex justify-between text-xs mb-1">
                      <span className="text-text-muted">Confidence</span>
                      <span className="font-mono font-semibold">{(output.confidence * 100).toFixed(0)}%</span>
                    </div>
                    <div className="h-1.5 bg-bg-surface rounded-full overflow-hidden mb-2">
                      <div className="h-full bg-accent-violet rounded-full" style={{ width: `${output.confidence * 100}%` }} />
                    </div>
                    {output.evidence?.[0] && (
                      <div className="text-[10px] text-text-muted leading-tight">{output.evidence[0].claim}</div>
                    )}
                    {output.risk_notes?.length > 0 && (
                      <div className="text-[10px] text-accent-amber mt-1">{output.risk_notes[0]}</div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* Challenges */}
        {challenges.length > 0 && (
          <div className="bg-bg-secondary border border-border-default rounded-lg p-4">
            <h3 className="text-sm font-semibold mb-3">Challenge Log ({challenges.length})</h3>
            <div className="space-y-2">
              {challenges.map((ch: any, i: number) => (
                <div key={i} className="flex items-center gap-3 p-2 bg-bg-tertiary rounded-md text-sm">
                  <span className="text-accent-amber font-mono text-xs">[{i + 1}]</span>
                  <span className="text-text-secondary">{ch.challenger}</span>
                  <span className="text-text-muted">→</span>
                  <span className="text-text-secondary">{ch.target_agent}</span>
                  <span className="text-text-muted">({ch.challenge_type})</span>
                  <span className={`ml-auto font-semibold text-xs ${ch.response === 'PARTIAL' ? 'text-accent-amber' : ch.response === 'VETO' ? 'text-accent-crimson' : 'text-text-muted'}`}>{ch.response}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Trust Scores */}
        <div className="bg-bg-secondary border border-border-default rounded-lg p-4">
          <h3 className="text-sm font-semibold mb-3">Agent Trust Scores</h3>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            {Object.keys(AGENT_META).map(agentId => {
              const meta = AGENT_META[agentId];
              const scores = trustScores?.[agentId] || {};
              const globalScore = scores?.global?.score ?? 1.0;
              return (
                <div key={agentId} className="bg-bg-tertiary border border-border-default rounded-md p-3">
                  <div className="flex items-center gap-2 mb-2">
                    <div className="w-6 h-6 rounded-full flex items-center justify-center text-[9px] font-bold text-white" style={{ backgroundColor: meta.color }}>{meta.icon}</div>
                    <span className="text-sm font-semibold">{meta.name}</span>
                    <span className={`ml-auto font-mono text-sm font-bold ${globalScore > 1.05 ? 'text-accent-emerald' : globalScore < 0.95 ? 'text-accent-crimson' : 'text-text-primary'}`}>
                      {globalScore.toFixed(3)}
                    </span>
                  </div>
                  <div className="h-1.5 bg-bg-surface rounded-full overflow-hidden">
                    <div className={`h-full rounded-full ${globalScore > 1.05 ? 'bg-accent-emerald' : globalScore < 0.95 ? 'bg-accent-crimson' : 'bg-accent-violet'}`}
                      style={{ width: `${Math.min(100, (globalScore / 2) * 100)}%` }} />
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* Thresholds */}
        {thresholds && (
          <div className="bg-bg-secondary border border-border-default rounded-lg p-4">
            <h3 className="text-sm font-semibold mb-3">Decision Thresholds</h3>
            <div className="grid grid-cols-3 gap-4">
              {Object.entries(thresholds).map(([profile, vals]: [string, any]) => (
                <div key={profile} className={`p-3 rounded-md border ${profile === selectedProfile ? 'border-accent-violet bg-accent-violet/5' : 'border-border-default'}`}>
                  <div className={`text-sm font-semibold mb-2 ${profile === selectedProfile ? 'text-accent-violet' : 'text-text-primary'}`}>{profile}</div>
                  <div className="space-y-1 text-xs">
                    {Object.entries(vals).map(([k, v]: [string, any]) => (
                      <div key={k} className="flex justify-between"><span className="text-text-muted">{k.replace(/_/g, ' ')}</span><span className="font-mono">{v}</span></div>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </AppShell>
  );
}
