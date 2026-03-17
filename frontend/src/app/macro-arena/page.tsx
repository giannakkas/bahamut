'use client';

import { useEffect, useState } from 'react';
import dynamic from 'next/dynamic';
import AppShell from '@/components/layout/AppShell';
import { api } from '@/lib/api';

const CandlestickChart = dynamic(() => import('@/components/charts/CandlestickChart'), { ssr: false });

const ASSET_GROUPS = [
  {
    name: 'Forex', assets: [
      { symbol: 'EURUSD', name: 'EUR/USD', decimals: 5 },
      { symbol: 'GBPUSD', name: 'GBP/USD', decimals: 5 },
      { symbol: 'USDJPY', name: 'USD/JPY', decimals: 3 },
    ],
  },
  {
    name: 'Commodities', assets: [
      { symbol: 'XAUUSD', name: 'Gold', decimals: 2 },
    ],
  },
  {
    name: 'Crypto', assets: [
      { symbol: 'BTCUSD', name: 'Bitcoin', decimals: 2 },
      { symbol: 'ETHUSD', name: 'Ethereum', decimals: 2 },
    ],
  },
  {
    name: 'US Stocks', assets: [
      { symbol: 'AAPL', name: 'Apple', decimals: 2 },
      { symbol: 'TSLA', name: 'Tesla', decimals: 2 },
      { symbol: 'NVDA', name: 'Nvidia', decimals: 2 },
      { symbol: 'META', name: 'Meta', decimals: 2 },
    ],
  },
];

const ALL_ASSETS = ASSET_GROUPS.flatMap(g => g.assets);

function AssetCard({ asset, cycle, candles, selected, onSelect }: any) {
  const d = cycle?.decision || {};
  const lastCandle = candles?.[candles.length - 1];
  const prevCandle = candles?.[candles.length - 21]; // ~20 candles ago
  const price = lastCandle?.close || cycle?.market_price || 0;
  const prevPrice = prevCandle?.close || price;
  const changePct = prevPrice > 0 ? ((price - prevPrice) / prevPrice) * 100 : 0;

  const dirColor = d.direction === 'LONG' ? 'text-accent-emerald' : d.direction === 'SHORT' ? 'text-accent-crimson' : 'text-text-muted';

  return (
    <div onClick={() => onSelect(asset.symbol)}
      className={`p-3 rounded-lg border cursor-pointer transition-all ${selected ? 'border-accent-violet bg-accent-violet/5' : 'border-border-default bg-bg-secondary hover:border-border-focus'}`}>
      <div className="flex items-center justify-between mb-1">
        <div>
          <div className="font-semibold text-sm">{asset.symbol}</div>
          <div className="text-[10px] text-text-muted">{asset.name}</div>
        </div>
        <div className="text-right">
          <div className="font-mono text-sm font-semibold">{price > 0 ? price.toFixed(asset.decimals) : '—'}</div>
          <div className={`text-[10px] font-mono ${changePct >= 0 ? 'text-accent-emerald' : 'text-accent-crimson'}`}>
            {changePct >= 0 ? '+' : ''}{changePct.toFixed(2)}%
          </div>
        </div>
      </div>
      {d.direction && d.direction !== 'NO_TRADE' && (
        <div className="flex items-center justify-between pt-1 border-t border-border-default mt-1">
          <span className={`text-xs font-bold ${dirColor}`}>
            {d.direction === 'LONG' ? '▲' : '▼'} {d.direction}
          </span>
          <span className="font-mono text-xs text-accent-violet">{d.final_score?.toFixed(2)}</span>
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

        // Load candles for all assets (stagger to avoid rate limit)
        const candleMap: Record<string, any[]> = {};
        for (const asset of ALL_ASSETS) {
          try {
            const res = await api.getCandles(asset.symbol, '4H', 100);
            if (res?.candles) candleMap[asset.symbol] = res.candles;
          } catch {}
          // Small delay to avoid hitting 8/min rate limit
          await new Promise(r => setTimeout(r, 400));
        }
        setAllCandles(candleMap);
      } catch (e) { console.error(e); }
      setLoading(false);
    };
    load();
  }, []);

  const selectedCycle = cycles[selectedAsset];
  const selectedCandles = allCandles[selectedAsset] || [];
  const selectedMeta = ALL_ASSETS.find(a => a.symbol === selectedAsset);

  return (
    <AppShell>
      <div className="space-y-5">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold">Macro Arena</h1>
            <p className="text-sm text-text-secondary mt-1">Cross-asset analysis — FX, Commodities, Crypto, Stocks</p>
          </div>
          {loading && <span className="text-xs text-text-muted">Loading market data...</span>}
        </div>

        {/* Asset groups */}
        {ASSET_GROUPS.map(group => (
          <div key={group.name}>
            <h2 className="text-xs font-semibold text-text-muted uppercase tracking-wider mb-2">{group.name}</h2>
            <div className={`grid gap-3 ${group.assets.length <= 3 ? 'grid-cols-3' : 'grid-cols-4'}`}>
              {group.assets.map(asset => (
                <AssetCard key={asset.symbol} asset={asset} cycle={cycles[asset.symbol]}
                  candles={allCandles[asset.symbol]} selected={selectedAsset === asset.symbol}
                  onSelect={setSelectedAsset} />
              ))}
            </div>
          </div>
        ))}

        {/* Selected asset chart */}
        <div className="bg-bg-secondary border border-border-default rounded-lg p-4">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-semibold">
              {selectedAsset} — {selectedMeta?.name || ''} · 4H
              {selectedCandles.length > 0 && <span className="text-text-muted font-normal ml-2">({selectedCandles.length} candles)</span>}
            </h3>
            {selectedCycle?.decision?.direction && (
              <span className={`text-xs font-bold ${selectedCycle.decision.direction === 'LONG' ? 'text-accent-emerald' : selectedCycle.decision.direction === 'SHORT' ? 'text-accent-crimson' : 'text-text-muted'}`}>
                {selectedCycle.decision.direction} · Score {selectedCycle.decision.final_score?.toFixed(2)} · {selectedCycle.decision.decision}
              </span>
            )}
          </div>
          <CandlestickChart candles={selectedCandles} height={400}
            signalDirection={selectedCycle?.decision?.direction}
            signalPrice={selectedCycle?.market_price} />
        </div>

        {/* Agent breakdown */}
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
