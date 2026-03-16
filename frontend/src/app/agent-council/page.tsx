'use client';

import { useEffect, useState } from 'react';
import AppShell from '@/components/layout/AppShell';
import { api } from '@/lib/api';
import { AGENT_META } from '@/lib/types';

export default function AgentCouncilPage() {
  const [trustScores, setTrustScores] = useState<any>(null);
  const [cycling, setCycling] = useState(false);
  const [cycleResult, setCycleResult] = useState<string | null>(null);
  const [selectedAsset, setSelectedAsset] = useState('EURUSD');
  const [selectedTF, setSelectedTF] = useState('4H');
  const [selectedProfile, setSelectedProfile] = useState('BALANCED');
  const [thresholds, setThresholds] = useState<any>(null);

  useEffect(() => {
    const load = async () => {
      try {
        const [ts, th] = await Promise.allSettled([
          api.getTrustScores(),
          api.getThresholds(),
        ]);
        if (ts.status === 'fulfilled') setTrustScores(ts.value);
        if (th.status === 'fulfilled') setThresholds(th.value);
      } catch (e) { console.error(e); }
    };
    load();
  }, []);

  const triggerCycle = async () => {
    setCycling(true);
    setCycleResult(null);
    try {
      const res = await api.triggerCycle(selectedAsset, 'fx', selectedTF, selectedProfile);
      setCycleResult(`Signal cycle queued: Task ${res.task_id?.slice(0, 8)}... for ${selectedAsset} ${selectedTF}`);
    } catch (e: any) {
      setCycleResult(`Error: ${e.message}`);
    } finally {
      setCycling(false);
    }
  };

  const agents = Object.keys(AGENT_META);

  return (
    <AppShell>
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold">Agent Council</h1>
            <p className="text-sm text-text-secondary mt-1">Multi-agent analysis, debate, and consensus engine</p>
          </div>
          <div className="flex items-center gap-3">
            <select value={selectedAsset} onChange={e => setSelectedAsset(e.target.value)}
              className="bg-bg-surface border border-border-default rounded-md px-3 py-1.5 text-sm text-text-primary">
              <option value="EURUSD">EURUSD</option>
              <option value="XAUUSD">XAUUSD</option>
              <option value="GBPUSD">GBPUSD</option>
              <option value="USDJPY">USDJPY</option>
            </select>
            <select value={selectedTF} onChange={e => setSelectedTF(e.target.value)}
              className="bg-bg-surface border border-border-default rounded-md px-3 py-1.5 text-sm text-text-primary">
              <option value="1H">1H</option>
              <option value="4H">4H</option>
              <option value="1D">1D</option>
            </select>
            <select value={selectedProfile} onChange={e => setSelectedProfile(e.target.value)}
              className="bg-bg-surface border border-border-default rounded-md px-3 py-1.5 text-sm text-text-primary">
              <option value="CONSERVATIVE">Conservative</option>
              <option value="BALANCED">Balanced</option>
              <option value="AGGRESSIVE">Aggressive</option>
            </select>
            <button onClick={triggerCycle} disabled={cycling}
              className="bg-accent-violet hover:bg-accent-violet/90 text-white font-semibold px-4 py-1.5 rounded-md text-sm transition-colors disabled:opacity-50">
              {cycling ? 'Running...' : 'Trigger Signal Cycle'}
            </button>
          </div>
        </div>

        {cycleResult && (
          <div className={`p-3 rounded-md text-sm border ${cycleResult.startsWith('Error') ? 'bg-accent-crimson/10 border-accent-crimson/30 text-accent-crimson' : 'bg-accent-emerald/10 border-accent-emerald/30 text-accent-emerald'}`}>
            {cycleResult}
          </div>
        )}

        {/* Thresholds Panel */}
        {thresholds && (
          <div className="bg-bg-secondary border border-border-default rounded-lg p-4">
            <h3 className="text-sm font-semibold mb-3">Decision Thresholds by Profile</h3>
            <div className="grid grid-cols-3 gap-4">
              {Object.entries(thresholds).map(([profile, vals]: [string, any]) => (
                <div key={profile} className={`p-3 rounded-md border ${profile === selectedProfile ? 'border-accent-violet bg-accent-violet/5' : 'border-border-default'}`}>
                  <div className={`text-sm font-semibold mb-2 ${profile === selectedProfile ? 'text-accent-violet' : 'text-text-primary'}`}>{profile}</div>
                  <div className="space-y-1 text-xs">
                    <div className="flex justify-between"><span className="text-text-muted">Strong Signal</span><span className="font-mono">{'>='} {vals.strong_signal}</span></div>
                    <div className="flex justify-between"><span className="text-text-muted">Signal</span><span className="font-mono">{'>='} {vals.signal}</span></div>
                    <div className="flex justify-between"><span className="text-text-muted">Weak Signal</span><span className="font-mono">{'>='} {vals.weak_signal}</span></div>
                    <div className="flex justify-between"><span className="text-text-muted">Min Agreement</span><span className="font-mono">{vals.min_agreement}/9</span></div>
                    <div className="flex justify-between"><span className="text-text-muted">Min Confidence</span><span className="font-mono">{vals.min_confidence}</span></div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Agent Trust Scores Grid */}
        <div className="bg-bg-secondary border border-border-default rounded-lg p-4">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-sm font-semibold">Agent Trust Scores</h3>
            {trustScores && <span className="text-[10px] text-accent-emerald">LIVE FROM API</span>}
          </div>
          <div className="grid grid-cols-3 gap-3">
            {agents.map(agentId => {
              const meta = AGENT_META[agentId];
              const scores = trustScores?.[agentId] || {};
              const globalScore = scores?.global?.score ?? 1.0;
              const samples = scores?.global?.samples ?? 0;

              return (
                <div key={agentId} className="bg-bg-tertiary border border-border-default rounded-md p-3">
                  <div className="flex items-center gap-2 mb-2">
                    <div className="w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold text-white"
                      style={{ backgroundColor: meta.color }}>{meta.icon}</div>
                    <div>
                      <div className="text-sm font-semibold">{meta.name}</div>
                      <div className="text-[10px] text-text-muted">{agentId}</div>
                    </div>
                  </div>
                  <div className="space-y-1">
                    <div className="flex justify-between text-xs">
                      <span className="text-text-muted">Global Trust</span>
                      <span className={`font-mono font-semibold ${globalScore > 1.1 ? 'text-accent-emerald' : globalScore < 0.9 ? 'text-accent-crimson' : 'text-text-primary'}`}>
                        {globalScore.toFixed(4)}
                      </span>
                    </div>
                    <div className="flex justify-between text-xs">
                      <span className="text-text-muted">Samples</span>
                      <span className="font-mono text-text-secondary">{samples}</span>
                    </div>
                    {/* Trust bar */}
                    <div className="h-1.5 bg-bg-surface rounded-full overflow-hidden mt-1">
                      <div className={`h-full rounded-full ${globalScore > 1.1 ? 'bg-accent-emerald' : globalScore < 0.9 ? 'bg-accent-crimson' : 'bg-accent-violet'}`}
                        style={{ width: `${Math.min(100, (globalScore / 2) * 100)}%` }} />
                    </div>
                    {/* Dimension previews */}
                    <div className="mt-2 flex flex-wrap gap-1">
                      {Object.entries(scores).slice(0, 4).map(([dim, val]: [string, any]) => (
                        dim !== 'global' && (
                          <span key={dim} className="text-[9px] px-1.5 py-0.5 bg-bg-surface rounded text-text-muted">
                            {dim.replace('regime:', '').replace('asset:', '')}: {val.score?.toFixed(2)}
                          </span>
                        )
                      ))}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </AppShell>
  );
}
