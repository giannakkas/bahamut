'use client';

import { useEffect, useState } from 'react';
import AppShell from '@/components/layout/AppShell';
import { api } from '@/lib/api';

export default function LearningLabPage() {
  const [fitness, setFitness] = useState<any>(null);
  const [recalResult, setRecalResult] = useState<string | null>(null);

  useEffect(() => {
    api.getStrategyFitness().then(setFitness).catch(console.error);
  }, []);

  const handleRecalibrate = async () => {
    try {
      const res = await api.emergencyRecalibrate();
      setRecalResult(`Emergency recalibration applied. Decay rate: ${res.decay_rate}`);
    } catch (e: any) { setRecalResult(`Error: ${e.message}`); }
  };

  return (
    <AppShell>
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold">Learning Lab</h1>
            <p className="text-sm text-text-secondary mt-1">Strategy fitness, trust scores, and calibration controls</p>
          </div>
          <button onClick={handleRecalibrate}
            className="bg-accent-amber hover:bg-accent-amber/90 text-black font-semibold px-4 py-1.5 rounded-md text-sm">
            Emergency Recalibrate
          </button>
        </div>

        {recalResult && (
          <div className="p-3 bg-accent-amber/10 border border-accent-amber/30 rounded-md text-accent-amber text-sm">{recalResult}</div>
        )}

        {fitness && (
          <div className="grid grid-cols-5 gap-4">
            {[
              { label: 'Sharpe (30d)', value: fitness.sharpe_30d, good: fitness.sharpe_30d > 1 },
              { label: 'Win Rate', value: `${(fitness.win_rate_30d * 100).toFixed(1)}%`, good: fitness.win_rate_30d > 0.55 },
              { label: 'Regime Stability', value: fitness.regime_stability, good: fitness.regime_stability === 'stable' },
              { label: 'Model Freshness', value: fitness.model_freshness, good: fitness.model_freshness === 'current' },
              { label: 'BT Divergence', value: `${fitness.backtest_divergence} σ`, good: fitness.backtest_divergence < 2 },
            ].map((m, i) => (
              <div key={i} className="bg-bg-secondary border border-border-default rounded-lg p-4 text-center">
                <div className="text-xs text-text-muted mb-1">{m.label}</div>
                <div className={`text-xl font-mono font-semibold ${m.good ? 'text-accent-emerald' : 'text-accent-crimson'}`}>
                  {typeof m.value === 'number' ? m.value.toFixed(2) : m.value}
                </div>
                <div className={`w-2 h-2 rounded-full mx-auto mt-2 ${m.good ? 'bg-accent-emerald' : 'bg-accent-crimson'}`} />
              </div>
            ))}
          </div>
        )}

        <div className="bg-bg-secondary border border-border-default rounded-lg p-4">
          <p className="text-text-secondary text-sm">Trust score detail charts, calibration timeline, and regime memory browser will be implemented with trade history data. Currently monitoring 9 agents across 15 dimensions each.</p>
          <a href="/agent-council" className="text-sm text-accent-violet hover:underline mt-2 inline-block">View live trust scores in Agent Council →</a>
        </div>
      </div>
    </AppShell>
  );
}
