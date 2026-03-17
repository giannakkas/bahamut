'use client';

import { useEffect, useState } from 'react';
import AppShell from '@/components/layout/AppShell';
import PriceChart from '@/components/charts/PriceChart';
import { api } from '@/lib/api';

function IndicatorCell({ label, value, good, format = 'number' }: {
  label: string; value: any; good?: boolean; format?: string;
}) {
  const color = good === undefined ? 'text-text-primary' : good ? 'text-accent-emerald' : 'text-accent-crimson';
  const formatted = format === 'percent' ? (value * 100).toFixed(1) + '%'
    : typeof value === 'number' ? value.toFixed(value > 100 ? 2 : 5) : value;
  return (
    <div className="text-center p-2">
      <div className="text-[10px] text-text-muted uppercase">{label}</div>
      <div className={`font-mono text-sm font-semibold ${color}`}>{formatted}</div>
    </div>
  );
}

function AssetRow({ asset, data }: { asset: string; data: any }) {
  if (data?.error) return null;

  const trendColor = data.trend === 'BULLISH' ? 'text-accent-emerald' : data.trend === 'BEARISH' ? 'text-accent-crimson' : 'text-accent-amber';
  const rsiColor = data.rsi > 70 ? 'text-accent-crimson' : data.rsi < 30 ? 'text-accent-emerald' : 'text-text-primary';

  return (
    <div className="bg-bg-secondary border border-border-default rounded-lg p-4">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-3">
          <span className="text-lg font-bold">{asset}</span>
          <span className="font-mono text-lg text-text-primary">{data.price?.toFixed(asset.includes('JPY') ? 3 : 5)}</span>
        </div>
        <div className="flex items-center gap-2">
          <span className={`px-2 py-0.5 rounded text-xs font-semibold ${trendColor} bg-bg-tertiary`}>{data.trend}</span>
          <span className={`px-2 py-0.5 rounded text-xs ${data.momentum === 'STRONG' ? 'text-accent-violet' : 'text-text-muted'} bg-bg-tertiary`}>
            ADX {data.adx} ({data.momentum})
          </span>
          {data.source === 'twelvedata_live' && (
            <span className="flex items-center gap-1 text-[10px] text-accent-emerald">
              <span className="relative flex h-1.5 w-1.5">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-accent-emerald opacity-75" style={{ animationDuration: '3s' }}></span>
                <span className="relative inline-flex rounded-full h-1.5 w-1.5 bg-accent-emerald"></span>
              </span>
              Live
            </span>
          )}
        </div>
      </div>

      <div className="grid grid-cols-8 gap-1 bg-bg-tertiary rounded-md p-1">
        <IndicatorCell label="RSI" value={data.rsi} good={data.rsi > 40 && data.rsi < 70} />
        <IndicatorCell label="MACD" value={data.macd} good={data.macd > 0} />
        <IndicatorCell label="Stoch" value={data.stoch_k} good={data.stoch_k > 20 && data.stoch_k < 80} />
        <IndicatorCell label="ATR" value={data.atr} />
        <IndicatorCell label="EMA 20" value={data.ema_20} />
        <IndicatorCell label="EMA 50" value={data.ema_50} />
        <IndicatorCell label="Vol 20d" value={data.vol_20} format="percent" />
        <IndicatorCell label="BB Width" value={data.bb_upper && data.bb_lower ? ((data.bb_upper - data.bb_lower) / data.price).toFixed(4) : 'N/A'} />
      </div>

      {/* Mini RSI bar */}
      <div className="mt-2 flex items-center gap-2 text-xs">
        <span className="text-text-muted w-6">30</span>
        <div className="flex-1 h-2 bg-bg-surface rounded-full overflow-hidden relative">
          <div className="absolute left-[30%] w-px h-full bg-border-default" />
          <div className="absolute left-[70%] w-px h-full bg-border-default" />
          <div className={`absolute h-full w-1.5 rounded-full ${rsiColor === 'text-accent-crimson' ? 'bg-accent-crimson' : rsiColor === 'text-accent-emerald' ? 'bg-accent-emerald' : 'bg-accent-violet'}`}
            style={{ left: `${Math.min(98, Math.max(2, data.rsi))}%`, transform: 'translateX(-50%)' }} />
        </div>
        <span className="text-text-muted w-6 text-right">70</span>
      </div>
    </div>
  );
}

export default function MacroArenaPage() {
  const [overview, setOverview] = useState<any>(null);
  const [selectedAsset, setSelectedAsset] = useState('EURUSD');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.getMacroOverview().then(data => { setOverview(data); setLoading(false); }).catch(e => { console.error(e); setLoading(false); });
  }, []);

  const assets = overview ? Object.keys(overview) : [];

  return (
    <AppShell>
      <div className="space-y-6">
        <div>
          <h1 className="text-2xl font-bold">Macro Arena</h1>
          <p className="text-sm text-text-secondary mt-1">Cross-asset technical overview with live indicators</p>
        </div>

        {/* Chart */}
        <div>
          <div className="flex items-center gap-2 mb-3">
            {['EURUSD', 'GBPUSD', 'USDJPY', 'XAUUSD'].map(a => (
              <button key={a} onClick={() => setSelectedAsset(a)}
                className={`px-3 py-1 rounded-md text-sm transition-colors ${selectedAsset === a ? 'bg-accent-violet text-white' : 'bg-bg-tertiary text-text-secondary hover:text-text-primary'}`}>
                {a}
              </button>
            ))}
          </div>
          <PriceChart asset={selectedAsset} timeframe="4H" height={350} />
        </div>

        {/* Asset Cards */}
        <div>
          <h2 className="text-sm font-semibold mb-3">Cross-Asset Analysis</h2>
          {loading ? (
            <div className="text-sm text-text-muted p-4 text-center">Loading macro data...</div>
          ) : (
            <div className="space-y-4">
              {assets.map(asset => (
                <AssetRow key={asset} asset={asset} data={overview[asset]} />
              ))}
            </div>
          )}
        </div>

        {/* Correlation hint */}
        <div className="bg-bg-secondary border border-border-default rounded-lg p-4">
          <h3 className="text-sm font-semibold mb-2">Market Structure</h3>
          <div className="grid grid-cols-4 gap-4 text-center text-sm">
            {assets.map(asset => {
              const d = overview?.[asset];
              if (!d) return null;
              const aboveEma = d.price > d.ema_200;
              return (
                <div key={asset} className="p-3 bg-bg-tertiary rounded-md">
                  <div className="font-semibold">{asset}</div>
                  <div className={`text-xs mt-1 ${aboveEma ? 'text-accent-emerald' : 'text-accent-crimson'}`}>
                    {aboveEma ? 'Above' : 'Below'} 200-EMA
                  </div>
                  <div className={`text-xs ${d.trend === 'BULLISH' ? 'text-accent-emerald' : d.trend === 'BEARISH' ? 'text-accent-crimson' : 'text-accent-amber'}`}>
                    {d.trend}
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
