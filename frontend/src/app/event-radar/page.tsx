'use client';

import { useEffect, useState } from 'react';
import AppShell from '@/components/layout/AppShell';
import { api } from '@/lib/api';

function ImpactBadge({ impact }: { impact: string }) {
  const i = (impact || '').toLowerCase();
  const colors: Record<string, string> = {
    high: 'bg-accent-crimson/20 text-accent-crimson border-accent-crimson/30',
    medium: 'bg-accent-amber/20 text-accent-amber border-accent-amber/30',
    low: 'bg-bg-surface text-text-muted border-border-default',
  };
  return (
    <span className={`text-[10px] px-2 py-0.5 rounded-full border font-semibold ${colors[i] || colors.low}`}>
      {(impact || 'LOW').toUpperCase()}
    </span>
  );
}

export default function EventRadarPage() {
  const [events, setEvents] = useState<any[]>([]);
  const [news, setNews] = useState<any[]>([]);
  const [filterImpact, setFilterImpact] = useState<string>('ALL');
  const [newsCategory, setNewsCategory] = useState('general');
  const [eventsSource, setEventsSource] = useState<string>('');
  const [loading, setLoading] = useState(true);

  const loadNews = async (cat: string) => {
    try {
      const n = await api.getNews(cat, 15);
      setNews(n.articles || []);
    } catch {}
  };

  useEffect(() => {
    const load = async () => {
      try {
        const [cal] = await Promise.allSettled([api.getCalendar(7)]);
        if (cal.status === 'fulfilled') {
          setEvents(cal.value.events || []);
          setEventsSource(cal.value.source || 'none');
        }
      } catch (e) { console.error(e); }
      setLoading(false);
    };
    load();
    loadNews(newsCategory);
  }, []);

  const handleCategoryChange = (cat: string) => {
    setNewsCategory(cat);
    loadNews(cat);
  };

  const filteredEvents = events.filter(e => {
    if (filterImpact === 'ALL') return true;
    return (e.impact || '').toLowerCase() === filterImpact.toLowerCase();
  });

  const highImpact = filteredEvents.filter(e => (e.impact || '').toLowerCase() === 'high');
  const otherEvents = filteredEvents.filter(e => (e.impact || '').toLowerCase() !== 'high');

  return (
    <AppShell>
      <div className="space-y-5">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold">Event Radar</h1>
            <div className="flex items-center gap-2 mt-1">
              <span className="text-sm text-text-secondary">Economic calendar and market news</span>
              {eventsSource && eventsSource !== 'none' && (
                <span className="flex items-center gap-1.5 text-sm text-accent-emerald">
                  <span className="relative flex h-2 w-2">
                    <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-accent-emerald opacity-75" style={{ animationDuration: '3s' }}></span>
                    <span className="relative inline-flex rounded-full h-2 w-2 bg-accent-emerald"></span>
                  </span>
                  Real-Time Data
                </span>
              )}
            </div>
          </div>
          <select value={filterImpact} onChange={e => setFilterImpact(e.target.value)}
            className="bg-bg-surface border border-border-default rounded-md px-3 py-1.5 text-sm text-text-primary">
            {['ALL', 'HIGH', 'MEDIUM', 'LOW'].map(v => <option key={v} value={v}>{v === 'ALL' ? 'All Impact' : v}</option>)}
          </select>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
          {/* Calendar - 2 columns */}
          <div className="lg:col-span-2 space-y-4">
            {highImpact.length > 0 && (
              <div>
                <h2 className="text-sm font-semibold text-accent-crimson mb-3 flex items-center gap-2">
                  <span className="w-2 h-2 rounded-full bg-accent-crimson animate-pulse" />
                  High Impact ({highImpact.length})
                </h2>
                <div className="space-y-2">
                  {highImpact.map((ev, i) => (
                    <div key={i} className="bg-bg-secondary border border-accent-crimson/20 rounded-lg p-4">
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-4">
                          <div className="text-center w-20">
                            <div className="text-xs text-text-muted">{ev.date}</div>
                            <div className="font-mono text-xs">{ev.time || ''}</div>
                          </div>
                          <div>
                            <div className="font-semibold text-sm flex items-center gap-2">
                              {ev.event} <ImpactBadge impact={ev.impact} />
                              {ev.currency && <span className="text-xs text-accent-violet font-mono">{ev.currency}</span>}
                            </div>
                            {ev.country && <div className="text-xs text-text-muted mt-0.5">{ev.country}</div>}
                          </div>
                        </div>
                        <div className="flex items-center gap-6 text-sm">
                          {ev.estimate != null && <div className="text-center"><div className="text-[10px] text-text-muted">Forecast</div><div className="font-mono">{ev.estimate}{ev.unit || ''}</div></div>}
                          {ev.prev != null && <div className="text-center"><div className="text-[10px] text-text-muted">Previous</div><div className="font-mono text-text-secondary">{ev.prev}{ev.unit || ''}</div></div>}
                          {ev.actual != null && <div className="text-center"><div className="text-[10px] text-text-muted">Actual</div><div className="font-mono font-semibold">{ev.actual}{ev.unit || ''}</div></div>}
                        </div>
                      </div>
                      <div className="mt-2 pt-2 border-t border-border-default text-xs text-accent-amber">
                        Agent freeze active: signals held for manual approval around this event.
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {otherEvents.length > 0 && (
              <div>
                <h2 className="text-sm font-semibold text-text-secondary mb-3">Other Events ({otherEvents.length})</h2>
                <div className="space-y-1.5">
                  {otherEvents.map((ev, i) => (
                    <div key={i} className="bg-bg-secondary border border-border-default rounded-lg p-3 flex items-center justify-between">
                      <div className="flex items-center gap-4">
                        <div className="w-20 text-xs text-text-muted">{ev.date} {ev.time || ''}</div>
                        <div className="text-sm flex items-center gap-2">
                          {ev.event} <ImpactBadge impact={ev.impact} />
                          {ev.currency && <span className="text-xs text-text-muted font-mono">{ev.currency}</span>}
                        </div>
                      </div>
                      <div className="flex items-center gap-4 text-xs text-text-muted">
                        {ev.estimate != null && <span>F: <span className="font-mono">{ev.estimate}</span></span>}
                        {ev.prev != null && <span>P: <span className="font-mono">{ev.prev}</span></span>}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {events.length === 0 && !loading && (
              <div className="bg-bg-secondary border border-border-default rounded-lg p-8 text-center">
                <div className="text-text-muted text-sm">No economic events found for this week.</div>
                <div className="text-text-muted text-xs mt-1">Calendar refreshes automatically with data from Finnhub.</div>
              </div>
            )}
          </div>

          {/* News Feed - 1 column */}
          <div>
            <div className="flex items-center justify-between mb-3">
              <h2 className="text-sm font-semibold">Market News</h2>
              <select value={newsCategory} onChange={e => handleCategoryChange(e.target.value)}
                className="bg-bg-surface border border-border-default rounded-md px-2 py-1 text-xs text-text-primary">
                <option value="general">General</option>
                <option value="forex">Forex</option>
                <option value="crypto">Crypto</option>
                <option value="merger">M&A</option>
              </select>
            </div>

            {news.length > 0 ? (
              <div className="space-y-2 max-h-[700px] overflow-y-auto pr-1">
                {news.map((article, i) => (
                  <a key={i} href={article.url} target="_blank" rel="noopener noreferrer"
                    className="block bg-bg-secondary border border-border-default rounded-lg p-3 hover:border-border-focus transition-colors">
                    {article.image && (
                      <div className="w-full h-24 rounded-md overflow-hidden mb-2 bg-bg-surface">
                        <img src={article.image} alt="" className="w-full h-full object-cover" onError={(e) => (e.target as HTMLImageElement).style.display = 'none'} />
                      </div>
                    )}
                    <div className="text-sm font-medium leading-tight">{article.title}</div>
                    {article.description && (
                      <div className="text-xs text-text-muted mt-1 leading-relaxed" style={{ display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden' }}>
                        {article.description.slice(0, 150)}
                      </div>
                    )}
                    <div className="flex items-center gap-2 mt-2 text-[10px] text-text-muted">
                      {article.source && <span className="text-accent-violet">{article.source}</span>}
                      {article.published && <span>{new Date(article.published).toLocaleString('en-GB', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}</span>}
                      {article.delayed && <span className="text-accent-amber">(24h delayed)</span>}
                    </div>
                  </a>
                ))}
              </div>
            ) : (
              <div className="bg-bg-secondary border border-border-default rounded-lg p-6 text-center">
                <div className="text-text-muted text-sm">Loading news feed...</div>
              </div>
            )}
          </div>
        </div>
      </div>
    </AppShell>
  );
}
