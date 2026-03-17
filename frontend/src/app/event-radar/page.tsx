'use client';

import { useState } from 'react';
import AppShell from '@/components/layout/AppShell';

// Static economic calendar (in production: pull from API like Trading Economics)
const EVENTS = [
  { time: '08:30', date: 'Today', event: 'US Core CPI m/m', currency: 'USD', impact: 'HIGH', forecast: '0.3%', previous: '0.4%', actual: null, affects: ['EURUSD', 'GBPUSD', 'USDJPY', 'XAUUSD'] },
  { time: '10:00', date: 'Today', event: 'US Consumer Sentiment', currency: 'USD', impact: 'MEDIUM', forecast: '76.5', previous: '79.4', actual: null, affects: ['EURUSD', 'USDJPY'] },
  { time: '13:00', date: 'Today', event: 'FOMC Member Speech', currency: 'USD', impact: 'MEDIUM', forecast: null, previous: null, actual: null, affects: ['EURUSD', 'XAUUSD'] },
  { time: '02:00', date: 'Tomorrow', event: 'UK GDP m/m', currency: 'GBP', impact: 'HIGH', forecast: '0.1%', previous: '-0.1%', actual: null, affects: ['GBPUSD'] },
  { time: '04:30', date: 'Tomorrow', event: 'ECB Interest Rate Decision', currency: 'EUR', impact: 'HIGH', forecast: '3.65%', previous: '3.65%', actual: null, affects: ['EURUSD'] },
  { time: '08:30', date: 'Tomorrow', event: 'US Retail Sales m/m', currency: 'USD', impact: 'HIGH', forecast: '0.2%', previous: '0.4%', actual: null, affects: ['EURUSD', 'GBPUSD', 'USDJPY'] },
  { time: '08:30', date: 'Tomorrow', event: 'US Unemployment Claims', currency: 'USD', impact: 'MEDIUM', forecast: '215K', previous: '211K', actual: null, affects: ['EURUSD', 'USDJPY'] },
  { time: '10:00', date: 'Wed', event: 'US Existing Home Sales', currency: 'USD', impact: 'LOW', forecast: '3.95M', previous: '4.08M', actual: null, affects: ['USDJPY'] },
  { time: '19:00', date: 'Wed', event: 'FOMC Minutes', currency: 'USD', impact: 'HIGH', forecast: null, previous: null, actual: null, affects: ['EURUSD', 'GBPUSD', 'USDJPY', 'XAUUSD'] },
  { time: '04:00', date: 'Thu', event: 'China GDP y/y', currency: 'CNY', impact: 'HIGH', forecast: '5.0%', previous: '5.4%', actual: null, affects: ['XAUUSD'] },
];

function ImpactBadge({ impact }: { impact: string }) {
  const colors: Record<string, string> = {
    HIGH: 'bg-accent-crimson/20 text-accent-crimson border-accent-crimson/30',
    MEDIUM: 'bg-accent-amber/20 text-accent-amber border-accent-amber/30',
    LOW: 'bg-bg-surface text-text-muted border-border-default',
  };
  return (
    <span className={`text-[10px] px-2 py-0.5 rounded-full border font-semibold ${colors[impact] || colors.LOW}`}>
      {impact}
    </span>
  );
}

export default function EventRadarPage() {
  const [filterImpact, setFilterImpact] = useState<string>('ALL');
  const [filterCurrency, setFilterCurrency] = useState<string>('ALL');

  const filtered = EVENTS.filter(e => {
    if (filterImpact !== 'ALL' && e.impact !== filterImpact) return false;
    if (filterCurrency !== 'ALL' && e.currency !== filterCurrency) return false;
    return true;
  });

  const todayEvents = filtered.filter(e => e.date === 'Today');
  const futureEvents = filtered.filter(e => e.date !== 'Today');

  return (
    <AppShell>
      <div className="space-y-5">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold">Event Radar</h1>
            <p className="text-sm text-text-secondary mt-1">Economic calendar with AI impact analysis</p>
          </div>
          <div className="flex items-center gap-3">
            <select value={filterImpact} onChange={e => setFilterImpact(e.target.value)}
              className="bg-bg-surface border border-border-default rounded-md px-3 py-1.5 text-sm text-text-primary">
              {['ALL', 'HIGH', 'MEDIUM', 'LOW'].map(v => <option key={v} value={v}>{v === 'ALL' ? 'All Impact' : v}</option>)}
            </select>
            <select value={filterCurrency} onChange={e => setFilterCurrency(e.target.value)}
              className="bg-bg-surface border border-border-default rounded-md px-3 py-1.5 text-sm text-text-primary">
              {['ALL', 'USD', 'EUR', 'GBP', 'CNY'].map(v => <option key={v} value={v}>{v === 'ALL' ? 'All Currencies' : v}</option>)}
            </select>
          </div>
        </div>

        {/* Today */}
        {todayEvents.length > 0 && (
          <div>
            <h2 className="text-sm font-semibold text-accent-amber mb-3 flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-accent-amber animate-pulse" />
              Today ({todayEvents.length} events)
            </h2>
            <div className="space-y-2">
              {todayEvents.map((ev, i) => (
                <div key={i} className="bg-bg-secondary border border-border-default rounded-lg p-4">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-4">
                      <div className="text-center w-14">
                        <div className="font-mono text-sm font-semibold">{ev.time}</div>
                        <div className="text-[10px] text-text-muted">UTC</div>
                      </div>
                      <div>
                        <div className="font-semibold text-sm flex items-center gap-2">
                          {ev.event}
                          <ImpactBadge impact={ev.impact} />
                        </div>
                        <div className="text-xs text-text-muted mt-0.5">
                          <span className="font-semibold text-text-secondary">{ev.currency}</span>
                          {ev.affects.length > 0 && <span className="ml-2">Affects: {ev.affects.join(', ')}</span>}
                        </div>
                      </div>
                    </div>
                    <div className="flex items-center gap-6 text-sm">
                      <div className="text-center">
                        <div className="text-[10px] text-text-muted">Forecast</div>
                        <div className="font-mono">{ev.forecast || '—'}</div>
                      </div>
                      <div className="text-center">
                        <div className="text-[10px] text-text-muted">Previous</div>
                        <div className="font-mono text-text-secondary">{ev.previous || '—'}</div>
                      </div>
                      <div className="text-center">
                        <div className="text-[10px] text-text-muted">Actual</div>
                        <div className="font-mono">{ev.actual || '—'}</div>
                      </div>
                    </div>
                  </div>
                  {ev.impact === 'HIGH' && (
                    <div className="mt-2 pt-2 border-t border-border-default">
                      <div className="text-xs text-accent-amber">
                        Agent Council event freeze: Signals within {ev.currency === 'USD' ? '2' : '1'} hours of release will be held for approval regardless of auto-trade settings.
                      </div>
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Upcoming */}
        {futureEvents.length > 0 && (
          <div>
            <h2 className="text-sm font-semibold text-text-secondary mb-3">Upcoming ({futureEvents.length} events)</h2>
            <div className="space-y-2">
              {futureEvents.map((ev, i) => (
                <div key={i} className="bg-bg-secondary border border-border-default rounded-lg p-3 flex items-center justify-between">
                  <div className="flex items-center gap-4">
                    <div className="text-center w-20">
                      <div className="text-xs text-text-muted">{ev.date}</div>
                      <div className="font-mono text-xs">{ev.time}</div>
                    </div>
                    <div>
                      <div className="text-sm flex items-center gap-2">
                        {ev.event} <ImpactBadge impact={ev.impact} />
                      </div>
                      <div className="text-xs text-text-muted">
                        <span className="font-semibold text-text-secondary">{ev.currency}</span>
                        <span className="ml-2">{ev.affects.join(', ')}</span>
                      </div>
                    </div>
                  </div>
                  <div className="flex items-center gap-4 text-xs">
                    <span className="text-text-muted">F: <span className="font-mono">{ev.forecast || '—'}</span></span>
                    <span className="text-text-muted">P: <span className="font-mono">{ev.previous || '—'}</span></span>
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
