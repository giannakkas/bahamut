'use client';
import { useState, useEffect } from 'react';
import AppShell from '@/components/layout/AppShell';

const EVENTS = [
  { time:"2026-03-24T04:30:00", name:"German Flash Manufacturing PMI", impact:"HIGH", currencies:["EUR"], forecast:49.6, previous:50.7 },
  { time:"2026-03-24T04:30:00", name:"German Flash Services PMI", impact:"HIGH", currencies:["EUR"], forecast:52.5, previous:53.4 },
  { time:"2026-03-24T05:30:00", name:"Flash Manufacturing PMI", impact:"HIGH", currencies:["GBP"], forecast:50.0, previous:52.0 },
  { time:"2026-03-24T05:30:00", name:"Flash Services PMI", impact:"HIGH", currencies:["GBP"], forecast:52.8, previous:53.9 },
  { time:"2026-03-24T09:45:00", name:"Flash Manufacturing PMI", impact:"HIGH", currencies:["USD"], forecast:51.5, previous:51.2 },
  { time:"2026-03-24T09:45:00", name:"Flash Services PMI", impact:"HIGH", currencies:["USD"], forecast:52.0, previous:52.3 },
  { time:"2026-03-24T10:00:00", name:"CB Consumer Confidence", impact:"MEDIUM", currencies:["USD"], forecast:94.2, previous:98.3 },
  { time:"2026-03-24T14:00:00", name:"FOMC Meeting Minutes", impact:"HIGH", currencies:["USD"], forecast:null, previous:null },
  { time:"2026-03-25T04:00:00", name:"Ifo Business Climate", impact:"MEDIUM", currencies:["EUR"], forecast:86.8, previous:85.2 },
  { time:"2026-03-25T08:30:00", name:"Durable Goods Orders", impact:"MEDIUM", currencies:["USD"], forecast:-0.8, previous:3.2 },
  { time:"2026-03-25T10:30:00", name:"Crude Oil Inventories", impact:"MEDIUM", currencies:["USD"], forecast:-1.5, previous:-3.3 },
  { time:"2026-03-26T08:30:00", name:"GDP (QoQ)", impact:"HIGH", currencies:["USD"], forecast:2.3, previous:3.2 },
];

const NEWS_ARTICLES = [
  { title:"Tom Brady says he's asked NFL about potential comeback: 'They don't like that idea very much'", summary:"Tom Brady has asked the NFL about its policy of allowing minority owners to return as players, but he has no plans on returning the field, he told CNBC.", source:"CNBC", time:"26 Mar, 14:55", img:"🏈" },
  { title:"Jim Cramer's top 10 things to watch in the stock market Thursday", summary:"Oil prices, bond yields and talks with Iran are all going the wrong way for the stock market.", source:"CNBC", time:"26 Mar, 14:30", img:"📊" },
  { title:"Meta's court defeats add to Zuckerberg's recent woes, represent 'watershed event' for social media", summary:"Meta suffered stinging defeats in two separate trials involving child safety that underscore shifting public sentiment toward the social media industry.", source:"CNBC", time:"26 Mar, 14:10", img:"📱" },
  { title:"Family offices make opportunistic bets on real estate as investors sit on sidelines", summary:"Wealthy family offices are finding opportunities in a challenging real estate environment.", source:"CNBC", time:"26 Mar, 13:44", img:"🏠" },
  { title:"Iran war cools early summer tourist interest in Cyprus, Greece", summary:"The conflict has dampened tourism bookings for the Eastern Mediterranean region.", source:"Reuters", time:"26 Mar, 13:21", img:"✈️" },
  { title:"A Google AI breakthrough is pressuring memory chip stocks from Samsung to Micron", summary:"Google's latest AI advancement has significant implications for the memory chip industry.", source:"CNBC", time:"26 Mar, 12:58", img:"🧠" },
  { title:"OECD: Iran war erases global growth upgrade, fans inflation", summary:"The OECD warns that ongoing conflict is undoing economic gains and stoking price pressures worldwide.", source:"Reuters", time:"26 Mar, 12:07", img:"🌍" },
  { title:"Germany limits fuel price hikes as Iran conflict drives surge", summary:"The German government implements price controls amid rising energy costs.", source:"Reuters", time:"26 Mar, 11:48", img:"⛽" },
  { title:"China urges peace talks in Iran war", summary:"Beijing calls for diplomatic resolution as the conflict enters a new phase.", source:"Reuters", time:"26 Mar, 11:19", img:"🇨🇳" },
];

export default function NewsFeed() {
  const [loaded, setLoaded] = useState(false);
  const [impactFilter, setImpactFilter] = useState<'all'|'high'|'medium'>('all');
  const [newsCategory, setNewsCategory] = useState('General');
  useEffect(() => { setTimeout(() => setLoaded(true), 100); }, []);

  const filteredEvents = impactFilter === 'all' ? EVENTS : EVENTS.filter(e => e.impact.toLowerCase() === impactFilter);
  const highCount = EVENTS.filter(e => e.impact === "HIGH").length;

  const impactClr = (i: string) => i === "HIGH" ? "bg-accent-crimson text-white" : "bg-accent-amber text-black";
  const curClr: Record<string,string> = { EUR:"bg-accent-cyan/15 text-accent-cyan", GBP:"bg-accent-violet/15 text-accent-violet", USD:"bg-accent-emerald/15 text-accent-emerald" };

  const fmtTime = (iso: string) => {
    const d = new Date(iso);
    return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}T${String(d.getHours()).padStart(2,'0')}:${String(d.getMinutes()).padStart(2,'0')}:00-\n04:00`;
  };
  const shortTime = (iso: string) => {
    const d = new Date(iso);
    return `${String(d.getHours()).padStart(2,'0')}:${String(d.getMinutes()).padStart(2,'0')}`;
  };

  return (
    <AppShell>
      <div className="w-full space-y-5">
        <div className={`flex flex-col sm:flex-row sm:justify-between sm:items-start gap-3 transition-all duration-700 ${loaded ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-3'}`}>
          <div>
            <h1 className="text-xl sm:text-2xl font-bold">News Feed</h1>
            <div className="flex items-center gap-2 mt-1">
              <span className="text-xs text-text-muted">Economic calendar and market news</span>
              <span className="flex items-center gap-1"><span className="w-1.5 h-1.5 rounded-full bg-accent-emerald animate-pulse" /><span className="text-xs text-accent-emerald font-semibold">Real-Time Data</span></span>
            </div>
          </div>
          <select value={impactFilter} onChange={e => setImpactFilter(e.target.value as any)} className="px-3 py-1.5 rounded-lg bg-bg-secondary border border-border-default text-sm text-text-secondary cursor-pointer focus:outline-none">
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
            </div>
            <div className="space-y-2">
              {filteredEvents.map((ev, i) => (
                <div key={i} className={`bg-bg-secondary/60 border border-border-default rounded-xl p-4 hover:border-accent-violet/15 transition-all duration-300 ${loaded ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-3'}`} style={{ transitionDelay: `${150 + i * 50}ms` }}>
                  <div className="flex flex-col sm:flex-row sm:items-start gap-3">
                    <div className="text-[10px] text-text-muted font-mono leading-tight min-w-[90px] shrink-0">
                      {new Date(ev.time).toLocaleDateString('en-GB', { year:'numeric', month:'2-digit', day:'2-digit' })}<br/>
                      {shortTime(ev.time)}
                    </div>
                    <div className="flex-1">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="text-sm font-bold">{ev.name}</span>
                        <span className={`px-2 py-0.5 text-[9px] font-bold rounded ${impactClr(ev.impact)}`}>{ev.impact}</span>
                        {ev.currencies.map(c => <span key={c} className={`px-2 py-0.5 text-[9px] font-bold rounded ${curClr[c] || "bg-bg-tertiary text-text-muted"}`}>{c}</span>)}
                      </div>
                      <div className="text-xs text-accent-amber mt-2">Agent freeze active: signals held for manual approval around this event.</div>
                    </div>
                    <div className="flex gap-6 text-right shrink-0">
                      {ev.forecast !== null && (
                        <div><div className="text-[9px] text-text-muted uppercase">Forecast</div><div className="text-sm font-bold tabular-nums">{ev.forecast}</div></div>
                      )}
                      {ev.previous !== null && (
                        <div><div className="text-[9px] text-text-muted uppercase">Previous</div><div className="text-sm font-bold tabular-nums text-text-secondary">{ev.previous}</div></div>
                      )}
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
              <select value={newsCategory} onChange={e => setNewsCategory(e.target.value)} className="px-2 py-1 rounded-md bg-bg-secondary border border-border-default text-[10px] text-text-muted cursor-pointer focus:outline-none">
                <option>General</option>
                <option>Crypto</option>
                <option>Forex</option>
                <option>Commodities</option>
              </select>
            </div>
            <div className="space-y-3">
              {NEWS_ARTICLES.map((article, i) => (
                <div key={i} className={`bg-bg-secondary/60 border border-border-default rounded-xl overflow-hidden hover:border-accent-cyan/15 transition-all duration-300 cursor-pointer group ${loaded ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-3'}`} style={{ transitionDelay: `${250 + i * 60}ms` }}>
                  <div className="flex items-center gap-3 p-3.5">
                    <div className="w-16 h-16 rounded-lg bg-bg-tertiary flex items-center justify-center text-2xl shrink-0 group-hover:scale-105 transition-transform duration-300">{article.img}</div>
                    <div className="flex-1 min-w-0">
                      <div className="text-xs font-bold leading-snug line-clamp-2 group-hover:text-accent-cyan transition-colors">{article.title}</div>
                      <div className="text-[10px] text-text-muted mt-1 line-clamp-2 leading-relaxed">{article.summary}</div>
                      <div className="flex items-center gap-2 mt-1.5">
                        <span className="text-[9px] text-accent-cyan font-semibold">{article.source}</span>
                        <span className="text-[9px] text-text-muted">{article.time}</span>
                      </div>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </AppShell>
  );
}
