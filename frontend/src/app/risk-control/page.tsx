'use client';

import { useEffect, useState } from 'react';
import AppShell from '@/components/layout/AppShell';
import { api } from '@/lib/api';

export default function RiskControlPage() {
  const [risk, setRisk] = useState<any>(null);
  const [killConfirm, setKillConfirm] = useState(false);
  const [killResult, setKillResult] = useState<string | null>(null);

  useEffect(() => {
    api.getRiskDashboard().then(setRisk).catch(console.error);
  }, []);

  const handleKillSwitch = async () => {
    if (!killConfirm) { setKillConfirm(true); return; }
    try {
      const res = await api.killSwitch();
      setKillResult(`Kill switch activated. Positions closed: ${res.positions_closed}`);
      setKillConfirm(false);
    } catch (e: any) { setKillResult(`Error: ${e.message}`); }
  };

  const dd = risk?.drawdown || {};
  const limits = risk?.limits || {};

  return (
    <AppShell>
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold">Risk Control</h1>
            <p className="text-sm text-text-secondary mt-1">Drawdown monitoring, circuit breakers, and emergency controls</p>
          </div>
          <button onClick={handleKillSwitch}
            className={`px-6 py-2 rounded-md font-bold text-white transition-colors ${killConfirm ? 'bg-red-600 animate-pulse' : 'bg-accent-crimson hover:bg-accent-crimson/90'}`}>
            {killConfirm ? 'CONFIRM KILL SWITCH' : 'KILL SWITCH'}
          </button>
        </div>

        {killResult && (
          <div className="p-3 bg-accent-crimson/10 border border-accent-crimson/30 rounded-md text-accent-crimson text-sm">{killResult}</div>
        )}

        {/* Drawdown Meters */}
        <div className="bg-bg-secondary border border-border-default rounded-lg p-6">
          <h3 className="text-sm font-semibold mb-4">Drawdown Meters</h3>
          <div className="space-y-4">
            {[
              { label: 'Daily', val: dd.daily || 0, max: limits.daily || 0.03 },
              { label: 'Weekly', val: dd.weekly || 0, max: limits.weekly || 0.06 },
              { label: 'Total', val: dd.total || 0, max: limits.total || 0.15 },
            ].map(d => {
              const pct = Math.min(100, (d.val / d.max) * 100);
              const color = pct > 80 ? 'bg-accent-crimson' : pct > 50 ? 'bg-accent-amber' : 'bg-accent-emerald';
              return (
                <div key={d.label} className="flex items-center gap-4">
                  <span className="w-16 text-sm text-text-secondary">{d.label}</span>
                  <div className="flex-1 h-4 bg-bg-surface rounded-full overflow-hidden">
                    <div className={`h-full rounded-full transition-all duration-700 ${color}`} style={{ width: `${pct}%` }} />
                  </div>
                  <span className="font-mono text-sm w-32 text-right">{(d.val * 100).toFixed(2)}% / {(d.max * 100).toFixed(1)}%</span>
                  <span className={`text-xs font-semibold ${pct > 80 ? 'text-accent-crimson' : 'text-accent-emerald'}`}>
                    {pct > 80 ? 'DANGER' : pct > 50 ? 'CAUTION' : 'OK'}
                  </span>
                </div>
              );
            })}
          </div>
        </div>

        <div className="grid grid-cols-2 gap-4">
          {/* Circuit Breakers */}
          <div className="bg-bg-secondary border border-border-default rounded-lg p-4">
            <h3 className="text-sm font-semibold mb-3">Circuit Breakers</h3>
            <div className="space-y-2">
              {risk?.circuit_breakers?.map((cb: any, i: number) => (
                <div key={i} className="flex items-center justify-between py-2 border-b border-border-default last:border-0">
                  <div className="flex items-center gap-2">
                    <span className={`w-3 h-3 rounded-full ${cb.active ? 'bg-accent-amber animate-pulse' : 'bg-accent-emerald'}`} />
                    <span className="text-sm">{cb.name}</span>
                  </div>
                  <span className={`text-xs font-mono ${cb.active ? 'text-accent-amber' : 'text-accent-emerald'}`}>
                    {cb.active ? cb.reason || 'ACTIVE' : 'OFF'}
                  </span>
                </div>
              ))}
            </div>
          </div>

          {/* Exposure */}
          <div className="bg-bg-secondary border border-border-default rounded-lg p-4">
            <h3 className="text-sm font-semibold mb-3">Portfolio Exposure</h3>
            <div className="space-y-3">
              <div className="flex justify-between"><span className="text-text-secondary">Net Exposure</span><span className="font-mono font-semibold">{((risk?.exposure?.net || 0) * 100).toFixed(1)}%</span></div>
              <div className="flex justify-between"><span className="text-text-secondary">Long</span><span className="font-mono text-accent-emerald">{((risk?.exposure?.long || 0) * 100).toFixed(1)}%</span></div>
              <div className="flex justify-between"><span className="text-text-secondary">Short</span><span className="font-mono text-accent-crimson">{((risk?.exposure?.short || 0) * 100).toFixed(1)}%</span></div>
              <div className="flex justify-between"><span className="text-text-secondary">Max Correlation</span><span className="font-mono">{risk?.correlation?.max?.toFixed(2) || 'N/A'}</span></div>
              <div className="flex justify-between"><span className="text-text-secondary">Threshold</span><span className="font-mono text-text-muted">{risk?.correlation?.threshold?.toFixed(2) || 'N/A'}</span></div>
            </div>
          </div>
        </div>
      </div>
    </AppShell>
  );
}
