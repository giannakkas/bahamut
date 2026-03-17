'use client';

import { useEffect, useState } from 'react';
import AppShell from '@/components/layout/AppShell';
import { api } from '@/lib/api';

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
  const [events, setEvents] = useState<any[]>([]);
  const [news, setNews] = useState<any[]>([]);
  const [filterImpact, setFilterImpact] = useState<string>('ALL');
  const [newsQuery, setNewsQuery] = useState('forex market');
  const [eventsSource, setEventsSource] = useState<string>('');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const load = async () => {
      try {
        const [cal, n] = await Promise.allSettled([
          api.getCalendar(7),
          api.getNews(newsQuery, 15),
        ]);
        if (cal.status === 'fulfilled') {
          setEvents(cal.value.events || []);
          setEventsSource(cal.value.source || 'none');
        }
        if (n.status === 'fulfilled') {
          setNews(n.value.articles || []);
        }
      } catch (e) { console.error(e); }
      setLoading(false);
    };
    load();
  }, [newsQuery]);

  const filteredEvents = events.filter(e =>
    filterImpact === 'ALL' || e.impact === filterImpact
  );

  const highImpact = filteredEvents.filter(e => e.impact === 'HIGH');
  const otherEvents = filteredEvents.filter(e => e.impact !== 'HIGH');

  return (
    <AppShell>
      <div className="space-y-5">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold">Event Radar</h1>
            <div className="flex items-center gap-2 mt-1">
              <span className="text-sm text-text-secondary">Economic calendar and market news</span>
              {eventsSource === 'twelvedata' && (
                <span className="flex items-center gap-1.5 text-sm text-accent-emerald">
                  <span className="relative flex h-2 w-2">
                    <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-accent-emerald opacity-75" style={{ animationDuration: '3s' }}></span>
                    <span className="relative inline-flex rounded-full h-2 w-2 bg-accent-emerald"></span>
                  </span>
                  Live Data
                </span>
              )}
            </div>
          </div>
          <div className="flex items-center gap-3">
            <select value={filterImpact} onChange={e => setFilterImpact(e.target.value)}
              className="bg-bg-surface border border-border-default rounded-md px-3 py-1.5 text-sm text-text-primary">
              {['ALL', 'HIGH', 'MEDIUM', 'LOW'].map(v => <option key={v} value={v}>{v === 'ALL' ? 'All Impact' : v}</option>)}
            </select>
          </div>
        </div>

        <div className="grid grid-cols-3 gap-5">
          {/* Economic Calendar - 2 columns */}
          <div className="col-span-2 space-y-4">
            {/* High Impact Events */}
            {highImpact.length > 0 && (
              <div>
                <h2 className="text-sm font-semibold text-accent-crimson mb-3 flex items-center gap-2">
                  <span className="w-2 h-2 rounded-full bg-accent-crimson animate-pulse" />
                  High Impact Events ({highImpact.length})
                </h2>
                <div className="space-y-2">
                  {highImpact.map((ev, i) => (
                    <div key={i} className="bg-bg-secondary border border-accent-crimson/20 rounded-lg p-4">
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-4">
                          <div className="text-center w-16">
                            <div className="font-mono text-xs">{ev.time?.split(' ')[0] || ''}</div>
                            <div className="text-[10px] text-text-muted">{ev.time?.split(' ')[1] || ''}</div>
                          </div>
                          <div>
                            <div className="font-semibold text-sm flex items-center gap-2">
                              {ev.event}
                              <ImpactBadge impact={ev.impact} />
                              {ev.currency && <span className="text-xs text-accent-violet font-mono">{ev.currency}</span>}
                            </div>
                            {ev.country && <div className="text-xs text-text-muted mt-0.5">{ev.country}</div>}
                          </div>
                        </div>
                        <div className="flex items-center gap-6 text-sm">
                          {ev.forecast != null && (
                            <div className="text-center">
                              <div className="text-[10px] text-text-muted">Forecast</div>
                              <div className="font-mono">{ev.forecast}</div>
                            </div>
                          )}
                          {ev.previous != null && (
                            <div className="text-center">
                              <div className="text-[10px] text-text-muted">Previous</div>
                              <div className="font-mono text-text-secondary">{ev.previous}</div>
                            </div>
                          )}
                          {ev.actual != null && (
                            <div className="text-center">
                              <div className="text-[10px] text-text-muted">Actual</div>
                              <div className="font-mono font-semibold">{ev.actual}</div>
                            </div>
                          )}
                        </div>
                      </div>
                      <div className="mt-2 pt-2 border-t border-border-default text-xs text-accent-amber">
                        Agent freeze: Trading signals will be held for manual approval around this event.
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Other events */}
            {otherEvents.length > 0 && (
              <div>
                <h2 className="text-sm font-semibold text-text-secondary mb-3">
                  Other Events ({otherEvents.length})
                </h2>
                <div className="space-y-1.5">
                  {otherEvents.map((ev, i) => (
                    <div key={i} className="bg-bg-secondary border border-border-default rounded-lg p-3 flex items-center justify-between">
                      <div className="flex items-center gap-4">
                        <div className="font-mono text-xs text-text-muted w-16">{ev.time?.split(' ')[0] || ''}</div>
                        <div className="text-sm flex items-center gap-2">
                          {ev.event}
                          <ImpactBadge impact={ev.impact} />
                          {ev.currency && <span className="text-xs text-text-muted font-mono">{ev.currency}</span>}
                        </div>
                      </div>
                      <div className="flex items-center gap-4 text-xs text-text-muted">
                        {ev.forecast != null && <span>F: <span className="font-mono">{ev.forecast}</span></span>}
                        {ev.previous != null && <span>P: <span className="font-mono">{ev.previous}</span></span>}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {events.length === 0 && !loading && (
              <div className="bg-bg-secondary border border-border-default rounded-lg p-8 text-center">
                <div className="text-text-muted text-sm">
                  Economic calendar requires a data source. Events will appear here when available.
                </div>
                <div className="text-text-muted text-xs mt-1">
                  Add NEWSAPI_KEY to Railway for real news headlines.
                </div>
              </div>
            )}
          </div>

          {/* News Feed - 1 column */}
          <div>
            <div className="flex items-center justify-between mb-3">
              <h2 className="text-sm font-semibold">Market News</h2>
              <select value={newsQuery} onChange={e => setNewsQuery(e.target.value)}
                className="bg-bg-surface border border-border-default rounded-md px-2 py-1 text-xs text-text-primary">
                <option value="forex market">Forex</option>
                <option value="cryptocurrency bitcoin">Crypto</option>
                <option value="stock market earnings">Stocks</option>
                <option value="gold commodities">Commodities</option>
                <option value="federal reserve ECB interest rate">Central Banks</option>
              </select>
            </div>

            {news.length > 0 ? (
              <div className="space-y-2">
                {news.map((article, i) => (
                  <a key={i} href={article.url} target="_blank" rel="noopener noreferrer"
                    className="block bg-bg-secondary border border-border-default rounded-lg p-3 hover:border-border-focus transition-colors">
                    <div className="text-sm font-medium leading-tight">{article.title}</div>
                    {article.description && (
                      <div className="text-xs text-text-muted mt-1 leading-relaxed line-clamp-2">{article.description}</div>
                    )}
                    <div className="flex items-center gap-2 mt-2 text-[10px] text-text-muted">
                      {article.source && <span className="text-accent-violet">{article.source}</span>}
                      {article.published && (
                        <span>{new Date(article.published).toLocaleString('en-GB', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}</span>
                      )}
                    </div>
                  </a>
                ))}
              </div>
            ) : (
              <div className="bg-bg-secondary border border-border-default rounded-lg p-6 text-center">
                <div className="text-text-muted text-sm">No news available</div>
                <div className="text-text-muted text-xs mt-1">
                  Add NEWSAPI_KEY to Railway for live financial news.
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </AppShell>
  );
}
