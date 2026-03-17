'use client';

import { useEffect, useState } from 'react';
import dynamic from 'next/dynamic';
import AppShell from '@/components/layout/AppShell';
import { api } from '@/lib/api';

const CandlestickChart = dynamic(() => import('@/components/charts/CandlestickChart'), { ssr: false });

const ASSETS = [
  { symbol: 'EURUSD', name: 'EUR/USD', class: 'fx' },
  { symbol: 'GBPUSD', name: 'GBP/USD', class: 'fx' },
  { symbol: 'USDJPY', name: 'USD/JPY', class: 'fx' },
  { symbol: 'XAUUSD', name: 'Gold', class: 'commodities' },
];

function AssetRow({ asset, cycle, candles, selected, onSelect }: any) {
  const d = cycle?.decision || {};
  const price = cycle?.market_price;
  const dirColor = d.direction === 'LONG' ? 'text-accent-emerald' : d.direction === 'SHORT' ? 'text-accent-crimson' : 'text-text-muted';
  const arrow = d.direction === 'LONG' ? '▲' : d.direction === 'SHORT' ? '▼' : '─';

  // Mini sparkline from last 20 candles
  const sparkData = candles?.slice(-20) || [];
  const firstClose = sparkData[0]?.close || 0;
  const lastClose = sparkData[sparkData.length - 1]?.close || 0;
  const changePct = firstClose > 0 ? ((lastClose - firstClose) / firstClose) * 100 : 0;

  return (
    <div onClick={() => onSelect(asset.symbol)}
      className={`p-4 rounded-lg border cursor-pointer transition-all ${selected ? 'border-accent-violet bg-accent-violet/5' : 'border-border-default bg-bg-secondary hover:border-border-focus'}`}>
      <div className="flex items-center justify-between mb-2">
        <div>
          <div className="font-semibold text-sm">{asset.name}</div>
          <div className="text-xs text-text-muted">{asset.class}</div>
        </div>
        <div className="text-right">
          <div className="font-mono text-lg font-semibold">{price ? Number(price).toFixed(asset.symbol === 'XAUUSD' ? 2 : 5) : '—'}</div>
          <div className={`text-xs font-mono ${changePct >= 0 ? 'text-accent-emerald' : 'text-accent-crimson'}`}>
            {changePct >= 0 ? '+' : ''}{changePct.toFixed(2)}%
          </div>
        </div>
      </div>
      {d.direction && (
        <div className="flex items-center justify-between mt-2 pt-2 border-t border-border-default">
          <div className="flex items-center gap-2">
            <span className={`text-sm font-bold ${dirColor}`}>{arrow} {d.direction}</span>
            <span className="text-xs text-text-muted">{d.decision}</span>
          </div>
          <span className="font-mono text-sm text-accent-violet font-semibold">{d.final_score?.toFixed(2)}</span>
        </div>
      )}
    </div>
  );
}

export default function MacroArenaPage() {
  const [cycles, setCycles] = useState<any>({});
  const [allCandles, setAllCandles] = useState<Record<string, any[]>>({});
  const [selectedAsset, setSelectedAsset] = useState('EURUSD');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const load = async () => {
      try {
        const c = await api.getAllLatestCycles();
        setCycles(c);

        // Load candles for all assets
        const candlePromises = ASSETS.map(async a => {
          try {
            const res = await api.getCandles(a.symbol, '4H', 100);
            return { symbol: a.symbol, candles: res?.candles || [] };
          } catch { return { symbol: a.symbol, candles: [] }; }
        });
        const results = await Promise.all(candlePromises);
        const candleMap: Record<string, any[]> = {};
        results.forEach(r => { candleMap[r.symbol] = r.candles; });
        setAllCandles(candleMap);
      } catch (e) { console.error(e); }
      setLoading(false);
    };
    load();
    const interval = setInterval(load, 120000);
    return () => clearInterval(interval);
  }, []);

  const selectedCycle = cycles[selectedAsset];
  const selectedCandles = allCandles[selectedAsset] || [];

  return (
    <AppShell>
      <div className="space-y-5">
        <div>
          <h1 className="text-2xl font-bold">Macro Arena</h1>
          <p className="text-sm text-text-secondary mt-1">Cross-asset analysis and market overview</p>
        </div>

        <div className="grid grid-cols-4 gap-3">
          {ASSETS.map(asset => (
            <AssetRow key={asset.symbol} asset={asset} cycle={cycles[asset.symbol]}
              candles={allCandles[asset.symbol]} selected={selectedAsset === asset.symbol}
              onSelect={setSelectedAsset} />
          ))}
        </div>

        {/* Selected asset chart */}
        <div className="bg-bg-secondary border border-border-default rounded-lg p-4">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-semibold">{selectedAsset} · 4H</h3>
            <div className="flex items-center gap-2">
              {selectedCycle?.decision?.direction && (
                <span className={`text-xs font-semibold ${selectedCycle.decision.direction === 'LONG' ? 'text-accent-emerald' : selectedCycle.decision.direction === 'SHORT' ? 'text-accent-crimson' : 'text-text-muted'}`}>
                  {selectedCycle.decision.direction} · Score {selectedCycle.decision.final_score?.toFixed(2)}
                </span>
              )}
            </div>
          </div>
          <CandlestickChart candles={selectedCandles} height={400}
            signalDirection={selectedCycle?.decision?.direction}
            signalPrice={selectedCycle?.market_price} />
        </div>

        {/* Agent breakdown for selected */}
        {selectedCycle?.agent_outputs && (
          <div className="bg-bg-secondary border border-border-default rounded-lg p-4">
            <h3 className="text-sm font-semibold mb-3">Agent Analysis — {selectedAsset}</h3>
            <div className="grid grid-cols-6 gap-2">
              {selectedCycle.agent_outputs.map((a: any) => {
                const ac = a.directional_bias === 'LONG' ? 'text-accent-emerald' : a.directional_bias === 'SHORT' ? 'text-accent-crimson' : 'text-text-muted';
                return (
                  <div key={a.agent_id} className="bg-bg-tertiary rounded-md p-2 text-center">
                    <div className="text-xs text-text-secondary mb-1">{a.agent_id.replace('_agent', '')}</div>
                    <div className={`text-sm font-bold ${ac}`}>
                      {a.directional_bias === 'LONG' ? '▲' : a.directional_bias === 'SHORT' ? '▼' : '─'} {(a.confidence * 100).toFixed(0)}%
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </div>
    </AppShell>
  );
}
