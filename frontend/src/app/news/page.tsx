'use client';
import { useState, useEffect } from 'react';
import AppShell from '@/components/layout/AppShell';
import { fetchCalendar, fetchNews } from '@/lib/traderApi';

const timeAgo = (iso: string) => { if (!iso) return ""; const d = Date.now() - new Date(iso).getTime(); const m = Math.floor(d/60000); if (m < 60) return `${m}m ago`; const h = Math.floor(m/60); if (h < 24) return `${h}h ago`; return `${Math.floor(h/24)}d ago`; };

export default function NewsFeed() {
  const [events, setEvents] = useState<any[]>([]);
  const [articles, setArticles] = useState<any[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [impactFilter, setImpactFilter] = useState<string>('all');
  const [newsCategory, setNewsCategory] = useState('general');

  const loadNews = async (cat: string) => {
    const arts = await fetchNews(cat, 15);
    if (arts) setArticles(arts);
  };

  useEffect(() => {
    (async () => {
      const [cal, arts] = await Promise.all([fetchCalendar(), fetchNews('general', 15)]);
      if (cal) setEvents(cal);
      if (arts) setArticles(arts);
      setLoaded(true);
    })();
    const iv = setInterval(async () => { const arts = await fetchNews(newsCategory, 15); if (arts) setArticles(arts); }, 120000);
    return () => clearInterval(iv);
  }, []);

  const impactClr = (i: string) => {
    const il = (i||'').toLowerCase();
    return il === 'high' ? 'bg-accent-crimson text-white' : il === 'medium' ? 'bg-accent-amber text-black' : 'bg-bg-tertiary text-text-muted';
  };
  const curClr: Record<string,string> = { EUR:"bg-accent-cyan/15 text-accent-cyan", GBP:"bg-accent-violet/15 text-accent-violet", USD:"bg-accent-emerald/15 text-accent-emerald", JPY:"bg-accent-amber/15 text-accent-amber", AUD:"bg-blue-500/15 text-blue-400", CAD:"bg-accent-crimson/15 text-accent-crimson", CHF:"bg-text-muted/15 text-text-secondary" };

  const filteredEvents = impactFilter === 'all' ? events : events.filter(e => (e.impact||'').toLowerCase() === impactFilter);
  const highCount = events.filter(e => (e.impact||'').toLowerCase() === 'high').length;

  return (
    <AppShell>
      <div className="w-full space-y-5">
        <div className={`flex flex-col sm:flex-row sm:justify-between sm:items-start gap-3 transition-all duration-700 ${loaded ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-3'}`}>
          <div>
            <h1 className="text-xl sm:text-2xl font-bold">News Feed</h1>
            <div className="flex items-center gap-2 mt-1">
              <span className="text-xs text-text-muted">Economic calendar and market news</span>
              {events.length > 0 && <span className="flex items-center gap-1"><span className="w-1.5 h-1.5 rounded-full bg-accent-emerald animate-pulse" /><span className="text-xs text-accent-emerald font-semibold">Real-Time Data</span></span>}
            </div>
          </div>
          <select value={impactFilter} onChange={e => setImpactFilter(e.target.value)} className="px-3 py-1.5 rounded-lg bg-bg-secondary border border-border-default text-sm text-text-secondary cursor-pointer focus:outline-none">
            <option value="all">All Impact</option>
            <option value="high">High Only</option>
            <option value="medium">Medium Only</option>
          </select>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-[1fr_380px] 2xl:grid-cols-[1fr_480px] gap-5">
          {/* Economic Calendar */}
          <div className={`space-y-3 transition-all duration-700 delay-100 ${loaded ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-3'}`}>
            <div className="flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-accent-crimson" />
              <span className="text-sm font-bold">High Impact ({highCount})</span>
              <span className="text-xs text-text-muted ml-2">{events.length} total events</span>
            </div>
            {filteredEvents.length === 0 && loaded && <div className="bg-bg-secondary/60 border border-border-default rounded-xl p-8 text-center text-text-muted">No economic events found for this period.</div>}
            <div className="space-y-2">
              {filteredEvents.map((ev, i) => (
                <div key={i} className={`bg-bg-secondary/60 border border-border-default rounded-xl p-4 hover:border-accent-violet/15 transition-all duration-300 ${loaded ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-3'}`} style={{ transitionDelay: `${150 + i * 50}ms` }}>
                  <div className="flex flex-col sm:flex-row sm:items-start gap-3">
                    <div className="text-[10px] text-text-muted font-mono leading-tight min-w-[90px] shrink-0">
                      {ev.date || ev.time || '—'}<br/>{ev.time_label || ''}
                    </div>
                    <div className="flex-1">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="text-sm font-bold">{ev.title || ev.event || ev.name || '—'}</span>
                        <span className={`px-2 py-0.5 text-[9px] font-bold rounded ${impactClr(ev.impact)}`}>{(ev.impact||'LOW').toUpperCase()}</span>
                        {(ev.currency || ev.country || '').split(',').filter(Boolean).map((c: string) => (
                          <span key={c} className={`px-2 py-0.5 text-[9px] font-bold rounded ${curClr[c.trim()] || "bg-bg-tertiary text-text-muted"}`}>{c.trim()}</span>
                        ))}
                      </div>
                      {(ev.impact||'').toLowerCase() === 'high' && <div className="text-xs text-accent-amber mt-2">Agent freeze active: signals held for manual approval around this event.</div>}
                    </div>
                    <div className="flex gap-6 text-right shrink-0">
                      {ev.forecast != null && <div><div className="text-[9px] text-text-muted uppercase">Forecast</div><div className="text-sm font-bold tabular-nums">{ev.forecast}</div></div>}
                      {ev.previous != null && <div><div className="text-[9px] text-text-muted uppercase">Previous</div><div className="text-sm font-bold tabular-nums text-text-secondary">{ev.previous}</div></div>}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Market News */}
          <div className={`transition-all duration-700 delay-200 ${loaded ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-3'}`}>
            <div className="flex justify-between items-center mb-3">
              <span className="text-sm font-bold">Market News</span>
              <select value={newsCategory} onChange={e => { setNewsCategory(e.target.value); loadNews(e.target.value); }} className="px-2 py-1 rounded-md bg-bg-secondary border border-border-default text-[10px] text-text-muted cursor-pointer focus:outline-none">
                <option value="general">General</option>
                <option value="crypto">Crypto</option>
                <option value="forex">Forex</option>
                <option value="merger">M&A</option>
              </select>
            </div>
            {articles.length === 0 && loaded && <div className="bg-bg-secondary/60 border border-border-default rounded-xl p-8 text-center text-text-muted">No news articles available.</div>}
            <div className="space-y-3">
              {articles.map((a, i) => (
                <a key={i} href={a.url || a.link || '#'} target="_blank" rel="noopener noreferrer" className={`block bg-bg-secondary/60 border border-border-default rounded-xl overflow-hidden hover:border-accent-cyan/15 transition-all duration-300 cursor-pointer group ${loaded ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-3'}`} style={{ transitionDelay: `${250 + i * 60}ms` }}>
                  <div className="flex items-start gap-3 p-3.5">
                    {a.image && <img src={a.image} alt="" className="w-16 h-16 rounded-lg object-cover shrink-0 group-hover:scale-105 transition-transform duration-300" onError={(e) => { (e.target as HTMLImageElement).style.display = 'none'; }} />}
                    <div className="flex-1 min-w-0">
                      <div className="text-xs font-bold leading-snug line-clamp-2 group-hover:text-accent-cyan transition-colors">{a.headline || a.title || '—'}</div>
                      <div className="text-[10px] text-text-muted mt-1 line-clamp-2 leading-relaxed">{a.summary || a.description || ''}</div>
                      <div className="flex items-center gap-2 mt-1.5">
                        <span className="text-[9px] text-accent-cyan font-semibold">{a.source || a.publisher || '—'}</span>
                        <span className="text-[9px] text-text-muted">{a.datetime ? timeAgo(new Date(a.datetime * 1000).toISOString()) : a.published_at ? timeAgo(a.published_at) : ''}</span>
                      </div>
                    </div>
                  </div>
                </a>
              ))}
            </div>
          </div>
        </div>
      </div>
    </AppShell>
  );
}
