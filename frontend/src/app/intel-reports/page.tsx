'use client';

import { useEffect, useState } from 'react';
import AppShell from '@/components/layout/AppShell';
import { api } from '@/lib/api';

export default function IntelReportsPage() {
  const [brief, setBrief] = useState<any>(null);

  useEffect(() => {
    api.getDailyBrief().then(setBrief).catch(console.error);
  }, []);

  return (
    <AppShell>
      <div className="space-y-6">
        <h1 className="text-2xl font-bold">Intel Reports</h1>

        {brief && (
          <div className="bg-bg-secondary border border-border-default rounded-lg p-6">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-lg font-semibold">Daily Brief — {brief.date}</h2>
              <span className="px-2 py-1 bg-accent-emerald/20 text-accent-emerald text-xs rounded-full">{brief.regime}</span>
            </div>
            <p className="text-text-primary leading-relaxed">{brief.summary}</p>
            <div className="mt-4 grid grid-cols-3 gap-4">
              <div className="text-center p-3 bg-bg-tertiary rounded-md">
                <div className="text-2xl font-mono font-semibold">{brief.signals_generated}</div>
                <div className="text-xs text-text-muted">Signals Generated</div>
              </div>
              <div className="text-center p-3 bg-bg-tertiary rounded-md">
                <div className="text-2xl font-mono font-semibold">{brief.trades_executed}</div>
                <div className="text-xs text-text-muted">Trades Executed</div>
              </div>
              <div className="text-center p-3 bg-bg-tertiary rounded-md">
                <div className="text-2xl font-mono font-semibold">{brief.risk_events}</div>
                <div className="text-xs text-text-muted">Risk Events</div>
              </div>
            </div>
          </div>
        )}
      </div>
    </AppShell>
  );
}
