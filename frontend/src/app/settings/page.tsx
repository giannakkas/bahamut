'use client';

import { useEffect, useState } from 'react';
import AppShell from '@/components/layout/AppShell';
import { api } from '@/lib/api';
import { useAuthStore } from '@/stores/auth';

export default function SettingsPage() {
  const { user } = useAuthStore();
  const [thresholds, setThresholds] = useState<any>(null);
  const [health, setHealth] = useState<any>(null);
  const [activeProfile, setActiveProfile] = useState('BALANCED');

  useEffect(() => {
    const load = async () => {
      const [th, ah] = await Promise.allSettled([
        api.getConsensusThresholds(), api.getAgentHealth(),
      ]);
      if (th.status === 'fulfilled') setThresholds(th.value);
      if (ah.status === 'fulfilled') setHealth(ah.value);
    };
    load();
  }, []);

  return (
    <AppShell>
      <div className="space-y-6">
        <h1 className="text-2xl font-bold">Settings</h1>

        {/* Account */}
        <div className="bg-bg-secondary border border-border-default rounded-lg p-5">
          <h2 className="text-sm font-semibold mb-3">Account</h2>
          <div className="grid grid-cols-2 gap-4 text-sm">
            <div><span className="text-text-muted">Name:</span> <span className="font-semibold ml-2">{user?.full_name}</span></div>
            <div><span className="text-text-muted">Email:</span> <span className="font-mono ml-2">{user?.email}</span></div>
            <div><span className="text-text-muted">Role:</span> <span className="ml-2">{user?.role}</span></div>
            <div><span className="text-text-muted">Workspace:</span> <span className="font-mono ml-2">{user?.workspace_id?.slice(0, 8)}...</span></div>
          </div>
        </div>

        {/* System Status */}
        <div className="bg-bg-secondary border border-border-default rounded-lg p-5">
          <h2 className="text-sm font-semibold mb-3">System Status</h2>
          <div className="grid grid-cols-3 gap-4 text-sm">
            <div className="flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-accent-emerald" />
              <span className="text-text-secondary">API</span>
              <span className="ml-auto text-accent-emerald text-xs">Online</span>
            </div>
            <div className="flex items-center gap-2">
              <span className={`w-2 h-2 rounded-full ${health?.data_source !== 'none' ? 'bg-accent-emerald' : 'bg-accent-amber'}`} />
              <span className="text-text-secondary">Data Feed</span>
              <span className={`ml-auto text-xs ${health?.data_source !== 'none' ? 'text-accent-emerald' : 'text-accent-amber'}`}>
                {health?.data_source !== 'none' ? 'Connected' : 'Demo Mode'}
              </span>
            </div>
            <div className="flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-accent-emerald" />
              <span className="text-text-secondary">Agents</span>
              <span className="ml-auto text-accent-emerald text-xs">{health?.agent_count || 0} active</span>
            </div>
          </div>
        </div>

        {/* Trading Profiles */}
        <div className="bg-bg-secondary border border-border-default rounded-lg p-5">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-sm font-semibold">Trading Profiles</h2>
            <div className="flex gap-2">
              {['CONSERVATIVE', 'BALANCED', 'AGGRESSIVE'].map(p => (
                <button key={p} onClick={() => setActiveProfile(p)}
                  className={`px-3 py-1 rounded-md text-xs font-semibold transition-colors ${activeProfile === p ? 'bg-accent-violet text-white' : 'bg-bg-surface text-text-secondary border border-border-default hover:bg-bg-tertiary'}`}>
                  {p}
                </button>
              ))}
            </div>
          </div>

          {thresholds && thresholds[activeProfile] && (
            <div className="grid grid-cols-3 gap-x-8 gap-y-2 text-sm">
              {Object.entries(thresholds[activeProfile]).map(([key, val]: [string, any]) => (
                <div key={key} className="flex justify-between py-1 border-b border-border-default">
                  <span className="text-text-muted text-xs">{key.replace(/_/g, ' ')}</span>
                  <span className="font-mono text-xs">{typeof val === 'number' ? val : String(val)}</span>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Monitored Assets */}
        <div className="bg-bg-secondary border border-border-default rounded-lg p-5">
          <h2 className="text-sm font-semibold mb-3">Monitored Assets</h2>
          <div className="grid grid-cols-5 gap-3">
            {[
              { symbol: 'EURUSD', name: 'Euro / US Dollar', class: 'FX' },
              { symbol: 'BTCUSD', name: 'Bitcoin / US Dollar', class: 'Crypto' },
              { symbol: 'ETHUSD', name: 'Ethereum / US Dollar', class: 'Crypto' },
              { symbol: 'AAPL', name: 'Apple Inc.', class: 'Stock' },
              { symbol: 'TSLA', name: 'Tesla Inc.', class: 'Stock' },
              { symbol: 'NVDA', name: 'Nvidia Corp.', class: 'Stock' },
              { symbol: 'META', name: 'Meta Platforms', class: 'Stock' },
              { symbol: 'GBPUSD', name: 'British Pound / US Dollar', class: 'FX' },
              { symbol: 'USDJPY', name: 'US Dollar / Japanese Yen', class: 'FX' },
              { symbol: 'XAUUSD', name: 'Gold / US Dollar', class: 'Commodity' },
            ].map(a => (
              <div key={a.symbol} className="bg-bg-tertiary rounded-md p-3 border border-border-default">
                <div className="font-semibold text-sm">{a.symbol}</div>
                <div className="text-xs text-text-muted">{a.name}</div>
                <div className="text-[10px] text-accent-emerald mt-1 flex items-center gap-1">
                  <span className="w-1.5 h-1.5 rounded-full bg-accent-emerald" />
                  Active · {a.class}
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Signal Cycle Config */}
        <div className="bg-bg-secondary border border-border-default rounded-lg p-5">
          <h2 className="text-sm font-semibold mb-3">Signal Cycle Configuration</h2>
          <div className="grid grid-cols-2 gap-4 text-sm">
            <div className="flex justify-between"><span className="text-text-muted">Cycle Interval</span><span className="font-mono">Every 15 minutes</span></div>
            <div className="flex justify-between"><span className="text-text-muted">Default Timeframe</span><span className="font-mono">4H</span></div>
            <div className="flex justify-between"><span className="text-text-muted">Candles per Analysis</span><span className="font-mono">200</span></div>
            <div className="flex justify-between"><span className="text-text-muted">Agent Timeout</span><span className="font-mono">10 seconds</span></div>
            <div className="flex justify-between"><span className="text-text-muted">Challenge Rounds</span><span className="font-mono">1-2 (profile dependent)</span></div>
            <div className="flex justify-between"><span className="text-text-muted">Trust Score Dimensions</span><span className="font-mono">15 per agent</span></div>
          </div>
        </div>
      </div>
    </AppShell>
  );
}
