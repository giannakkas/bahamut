'use client';

import { useEffect, useState } from 'react';
import AppShell from '@/components/layout/AppShell';
import { api } from '@/lib/api';

// ═══════════════════════════════════════════
// TYPES
// ═══════════════════════════════════════════

interface AssetImpact {
  arrow: 'up' | 'down' | 'neutral';
  label: 'bullish' | 'bearish' | 'mixed';
  confidence: number;
  strength: 'low' | 'medium' | 'high';
  reason: string;
}

interface EnrichedEvent {
  id?: string;
  event: string;
  date: string;
  time?: string;
  country?: string;
  currency?: string;
  impact: string;
  actual?: number | null;
  estimate?: number | null;
  prev?: number | null;
  unit?: string;
  source?: string;
  category?: string;
  ai_asset_impacts?: Record<string, AssetImpact>;
  ai_summary?: string;
  freeze_recommended?: boolean;
  freeze_reason?: string;
  surprise_direction?: string;
  surprise_magnitude?: number;
}

const TRACKED = ['BTCUSD','ETHUSD','SPX','NQ','DXY','XAUUSD','EURUSD','USDJPY'];
const SHORT: Record<string,string> = {BTCUSD:'BTC',ETHUSD:'ETH',SPX:'SPX',NQ:'NQ',DXY:'DXY',XAUUSD:'XAU',EURUSD:'EUR',USDJPY:'JPY'};

// ═══════════════════════════════════════════
// COMPONENTS
// ═══════════════════════════════════════════

function ImpactBadge({ impact }: { impact: string }) {
  const i = (impact||'').toLowerCase();
  const c: Record<string,string> = {
    high: 'bg-accent-crimson/20 text-accent-crimson border-accent-crimson/30',
    medium: 'bg-accent-amber/20 text-accent-amber border-accent-amber/30',
    low: 'bg-bg-surface text-text-muted border-border-default',
  };
  return <span className={`text-[10px] px-2 py-0.5 rounded-full border font-bold tracking-wider ${c[i]||c.low}`}>{(impact||'LOW').toUpperCase()}</span>;
}

function ArrowBadge({ impact, asset, focused }: { impact?: AssetImpact; asset: string; focused: boolean }) {
  if (!impact) return null;
  const a = impact.arrow;
  const s = SHORT[asset] || asset;
  const ch = a === 'up' ? '▲' : a === 'down' ? '▼' : '●';
  const clr = a === 'up' ? 'text-accent-emerald' : a === 'down' ? 'text-accent-crimson' : 'text-text-muted';
  const bg = a === 'up' ? 'bg-accent-emerald/10 border-accent-emerald/20' : a === 'down' ? 'bg-accent-crimson/10 border-accent-crimson/20' : 'bg-bg-surface border-border-default';
  return (
    <div className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded border text-[10px] font-semibold ${bg} ${focused ? 'ring-1 ring-accent-cyan scale-110' : ''}`}
      title={`${s}: ${impact.reason} (${Math.round(impact.confidence*100)}%)`}>
      <span className={`${clr} font-black`}>{ch}</span>
      <span className="text-text-secondary">{s}</span>
    </div>
  );
}

function FreezePill({ freeze, reason }: { freeze?: boolean; reason?: string }) {
  if (freeze) return <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold bg-accent-crimson/15 text-accent-crimson border border-accent-crimson/25" title={reason||''}>🛑 Freeze Signals</span>;
  return null;
}

function SurpriseBadge({ direction }: { direction?: string }) {
  if (!direction || direction === 'unknown' || direction === 'in_line') return null;
  const label = direction.replace(/_/g, ' ');
  const isHot = ['hotter_than_expected','hawkish','worse_than_expected'].includes(direction);
  const clr = isHot ? 'text-accent-crimson bg-accent-crimson/10 border-accent-crimson/20' : 'text-accent-emerald bg-accent-emerald/10 border-accent-emerald/20';
  return <span className={`text-[10px] px-2 py-0.5 rounded-full border font-semibold capitalize ${clr}`}>{label}</span>;
}

function EventCard({ ev, focus }: { ev: EnrichedEvent; focus: string }) {
  const isHigh = (ev.impact||'').toLowerCase() === 'high';
  const impacts = ev.ai_asset_impacts || {};

  return (
    <div className={`bg-bg-secondary border rounded-lg p-4 ${isHigh ? 'border-accent-crimson/25' : 'border-border-default'}`}>
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-start gap-3 flex-1 min-w-0">
          <div className="text-center w-16 shrink-0 pt-0.5">
            <div className="text-[11px] text-text-muted">{ev.date}</div>
            <div className="font-mono text-[11px] text-text-secondary">{ev.time||''}</div>
          </div>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="font-semibold text-sm text-text-primary">{ev.event}</span>
              <ImpactBadge impact={ev.impact} />
              <SurpriseBadge direction={ev.surprise_direction} />
              <FreezePill freeze={ev.freeze_recommended} reason={ev.freeze_reason} />
              {ev.category && ev.category !== 'other' && <span className="text-[9px] text-accent-violet font-mono uppercase">{ev.category}</span>}
            </div>
            {ev.ai_summary && <div className="text-[11px] text-text-secondary mt-1">{ev.ai_summary}</div>}
          </div>
        </div>
        <div className="flex items-center gap-4 text-[11px] shrink-0">
          {ev.estimate!=null && <div className="text-center"><div className="text-[9px] text-text-muted">Fcst</div><div className="font-mono">{ev.estimate}{ev.unit||''}</div></div>}
          {ev.prev!=null && <div className="text-center"><div className="text-[9px] text-text-muted">Prev</div><div className="font-mono text-text-secondary">{ev.prev}{ev.unit||''}</div></div>}
          {ev.actual!=null && <div className="text-center"><div className="text-[9px] text-text-muted">Act</div><div className="font-mono font-semibold">{ev.actual}{ev.unit||''}</div></div>}
        </div>
      </div>
      {Object.keys(impacts).length > 0 && (
        <div className="mt-2.5 pt-2.5 border-t border-border-default flex flex-wrap gap-1.5">
          {TRACKED.map(a => <ArrowBadge key={a} impact={impacts[a]} asset={a} focused={focus !== 'ALL' && focus === a} />)}
        </div>
      )}
    </div>
  );
}

// ═══════════════════════════════════════════
// MAIN PAGE
// ═══════════════════════════════════════════

export default function EventRadarPage() {
  const [events, setEvents] = useState<EnrichedEvent[]>([]);
  const [news, setNews] = useState<any[]>([]);
  const [filterImpact, setFilterImpact] = useState('ALL');
  const [focus, setFocus] = useState('ALL');
  const [newsCategory, setNewsCategory] = useState('general');
  const [eventsSource, setEventsSource] = useState('');
  const [aiEnabled, setAiEnabled] = useState(false);
  const [loading, setLoading] = useState(true);

  const loadNews = async (cat: string) => { try { const n = await api.getNews(cat, 15); setNews(n.articles||[]); } catch {} };

  useEffect(() => {
    const load = async () => {
      try {
        const [cal] = await Promise.allSettled([api.getCalendar(7)]);
        if (cal.status === 'fulfilled') {
          setEvents(cal.value.events || []);
          setEventsSource(cal.value.source || 'none');
          setAiEnabled(cal.value.ai_enabled || false);
        }
      } catch (e) { console.error(e); }
      setLoading(false);
    };
    load();
    loadNews(newsCategory);
  }, []);

  const filtered = events.filter(e => filterImpact === 'ALL' || (e.impact||'').toLowerCase() === filterImpact.toLowerCase());
  const high = filtered.filter(e => (e.impact||'').toLowerCase() === 'high');
  const other = filtered.filter(e => (e.impact||'').toLowerCase() !== 'high');

  return (
    <AppShell>
      <div className="space-y-5">
        <div className="flex items-center justify-between flex-wrap gap-3">
          <div>
            <h1 className="text-2xl font-bold">Event Radar</h1>
            <div className="flex items-center gap-2 mt-1">
              <span className="text-sm text-text-secondary">AI-enriched market impact calendar</span>
              {aiEnabled && <span className="flex items-center gap-1 text-[11px] text-accent-cyan font-semibold"><span className="w-1.5 h-1.5 rounded-full bg-accent-cyan animate-pulse" />AI</span>}
              {eventsSource !== 'none' && eventsSource && <span className="text-[11px] text-accent-emerald">{eventsSource}</span>}
            </div>
          </div>
          <div className="flex items-center gap-2">
            <select value={focus} onChange={e => setFocus(e.target.value)} className="bg-bg-surface border border-border-default rounded-md px-3 py-1.5 text-xs text-text-primary">
              <option value="ALL">All Assets</option>
              {TRACKED.map(a => <option key={a} value={a}>{SHORT[a]}</option>)}
            </select>
            <select value={filterImpact} onChange={e => setFilterImpact(e.target.value)} className="bg-bg-surface border border-border-default rounded-md px-3 py-1.5 text-xs text-text-primary">
              {['ALL','HIGH','MEDIUM','LOW'].map(v => <option key={v} value={v}>{v === 'ALL' ? 'All Impact' : v}</option>)}
            </select>
          </div>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
          <div className="lg:col-span-2 space-y-4">
            {high.length > 0 && (
              <div>
                <h2 className="text-sm font-semibold text-accent-crimson mb-3 flex items-center gap-2">
                  <span className="w-2 h-2 rounded-full bg-accent-crimson animate-pulse" />High Impact ({high.length})
                </h2>
                <div className="space-y-2">{high.map((ev,i) => <EventCard key={ev.id||i} ev={ev} focus={focus} />)}</div>
              </div>
            )}
            {other.length > 0 && (
              <div>
                <h2 className="text-sm font-semibold text-text-secondary mb-3">Other Events ({other.length})</h2>
                <div className="space-y-1.5">{other.map((ev,i) => <EventCard key={ev.id||i} ev={ev} focus={focus} />)}</div>
              </div>
            )}
            {events.length === 0 && !loading && (
              <div className="bg-bg-secondary border border-border-default rounded-lg p-8 text-center">
                <div className="text-text-muted text-sm">No economic events found.</div>
              </div>
            )}
          </div>

          <div>
            <div className="flex items-center justify-between mb-3">
              <h2 className="text-sm font-semibold">Market News</h2>
              <select value={newsCategory} onChange={e => { setNewsCategory(e.target.value); loadNews(e.target.value); }} className="bg-bg-surface border border-border-default rounded-md px-2 py-1 text-xs text-text-primary">
                <option value="general">General</option><option value="forex">Forex</option><option value="crypto">Crypto</option><option value="merger">M&A</option>
              </select>
            </div>
            {news.length > 0 ? (
              <div className="space-y-2 max-h-[700px] overflow-y-auto pr-1">
                {news.map((a,i) => (
                  <a key={i} href={a.url} target="_blank" rel="noopener noreferrer" className="block bg-bg-secondary border border-border-default rounded-lg p-3 hover:border-border-focus transition-colors">
                    {a.image && <div className="w-full h-24 rounded-md overflow-hidden mb-2 bg-bg-surface"><img src={a.image} alt="" className="w-full h-full object-cover" onError={e => (e.target as HTMLImageElement).style.display='none'} /></div>}
                    <div className="text-sm font-medium leading-tight">{a.title}</div>
                    {a.description && <div className="text-xs text-text-muted mt-1" style={{display:'-webkit-box',WebkitLineClamp:2,WebkitBoxOrient:'vertical',overflow:'hidden'}}>{a.description.slice(0,150)}</div>}
                    <div className="flex items-center gap-2 mt-2 text-[10px] text-text-muted">
                      {a.source && <span className="text-accent-violet">{a.source}</span>}
                      {a.published && <span>{new Date(a.published).toLocaleString('en-GB',{month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'})}</span>}
                    </div>
                  </a>
                ))}
              </div>
            ) : <div className="bg-bg-secondary border border-border-default rounded-lg p-6 text-center text-text-muted text-sm">Loading news...</div>}
          </div>
        </div>
      </div>
    </AppShell>
  );
}
