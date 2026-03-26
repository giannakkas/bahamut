'use client';
import { useState, useEffect } from 'react';
import AppShell from '@/components/layout/AppShell';
import { fetchTopPicks } from '@/lib/traderApi';

const clsBg: Record<string,string> = { stock:"bg-accent-violet", crypto:"bg-accent-emerald", fx:"bg-accent-cyan", commodity:"bg-accent-amber", index:"bg-accent-violet" };
const clsTx: Record<string,string> = { stock:"text-white", crypto:"text-white", fx:"text-white", commodity:"text-black", index:"text-white" };
function getClass(asset: string) {
  if (['BTCUSD','ETHUSD','SOLUSD','XRPUSD'].some(c => asset.includes(c.replace('USD','')))) return 'crypto';
  if (['EURUSD','GBPUSD','USDJPY','AUDUSD','USDCAD','USDCHF','NZDUSD'].some(c => asset === c)) return 'fx';
  if (['XAUUSD','XAGUSD'].includes(asset)) return 'commodity';
  if (['SPY','QQQ','DIA'].includes(asset)) return 'index';
  return 'stock';
}
function fmtPrice(p: number) { return p > 1000 ? p.toLocaleString('en',{minimumFractionDigits:2,maximumFractionDigits:2}) : p < 10 ? p.toFixed(4) : p.toFixed(2); }

function ScoreBar({ value }: { value: number }) {
  return (
    <div className="flex items-center gap-1.5">
      <div className="w-12 h-1.5 bg-bg-tertiary rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${value >= 90 ? "bg-accent-emerald" : value >= 70 ? "bg-accent-cyan" : "bg-text-muted"}`} style={{ width: `${value}%` }} />
      </div>
      <span className={`text-xs font-semibold tabular-nums ${value >= 90 ? "text-accent-emerald" : value >= 70 ? "text-accent-cyan" : "text-text-muted"}`}>{value}</span>
    </div>
  );
}

export default function TopPicks() {
  const [picks, setPicks] = useState<any[]>([]);
  const [filter, setFilter] = useState("all");
  const [loading, setLoading] = useState(true);
  const [lastScan, setLastScan] = useState("");

  useEffect(() => {
    (async () => {
      const data = await fetchTopPicks();
      if (data.length > 0) setPicks(data);
      setLastScan(new Date().toLocaleString('en-GB', { day:'numeric', month:'short', hour:'2-digit', minute:'2-digit' }));
      setLoading(false);
    })();
    const iv = setInterval(async () => {
      const data = await fetchTopPicks();
      if (data.length > 0) setPicks(data);
      setLastScan(new Date().toLocaleString('en-GB', { day:'numeric', month:'short', hour:'2-digit', minute:'2-digit' }));
    }, 60000);
    return () => clearInterval(iv);
  }, []);

  const enriched = picks.map((p, i) => ({ ...p, rank: i + 1, cls: getClass(p.asset) }));
  const classCounts = { all: enriched.length, stock: enriched.filter(p => p.cls === 'stock').length, crypto: enriched.filter(p => p.cls === 'crypto').length, fx: enriched.filter(p => p.cls === 'fx').length, commodity: enriched.filter(p => p.cls === 'commodity').length };
  const filtered = filter === "all" ? enriched : enriched.filter(p => p.cls === filter);
  const top5 = filtered.slice(0, 5);

  return (
    <AppShell>
      <div className="w-full space-y-5">
        <div className="flex flex-col sm:flex-row sm:justify-between sm:items-start gap-3">
          <div>
            <div className="flex items-center gap-3 flex-wrap">
              <h1 className="text-xl sm:text-2xl font-bold">Top Picks</h1>
              <span className="px-2.5 py-0.5 rounded-full bg-accent-emerald/15 text-accent-emerald text-xs font-semibold">{enriched.length} assets scanned</span>
              {picks[0]?.source === 'live' && <span className="px-2 py-0.5 rounded-full bg-accent-cyan/15 text-accent-cyan text-[9px] font-bold">LIVE DATA</span>}
            </div>
            <div className="text-xs text-text-muted mt-1">AI scanner ranks all assets by opportunity strength · Last scan: {lastScan}</div>
          </div>
          <button onClick={() => window.location.reload()} className="px-4 py-2 rounded-lg bg-gradient-to-r from-accent-violet to-[#4c3ad1] text-white font-bold text-xs shadow-lg shadow-accent-violet/20 hover:brightness-110">Scan Now</button>
        </div>

        {loading ? (
          <div className="text-center py-20 text-text-muted">Loading real-time data...</div>
        ) : (
          <>
            <div className="flex gap-3 overflow-x-auto pb-1 -mx-3 px-3 sm:mx-0 sm:px-0 sm:grid sm:grid-cols-3 lg:grid-cols-5 sm:overflow-visible">
              {top5.map((p, i) => (
                <div key={i} className="min-w-[180px] sm:min-w-0 bg-bg-secondary/60 border border-border-default rounded-xl p-3.5 shrink-0">
                  <div className="flex justify-between items-start mb-1.5">
                    <div className="flex items-baseline gap-1.5"><span className="text-xs text-text-muted">#{p.rank}</span><span className="text-base font-extrabold">{p.asset}</span></div>
                    <span className={`px-2 py-0.5 rounded text-[9px] font-bold ${clsBg[p.cls] || 'bg-bg-tertiary'} ${clsTx[p.cls] || 'text-white'}`}>{p.cls}</span>
                  </div>
                  <div className="flex justify-between items-center mb-2">
                    <span className={`text-sm font-extrabold ${p.direction === "LONG" ? "text-accent-emerald" : p.direction === "SHORT" ? "text-accent-crimson" : "text-text-secondary"}`}>{p.direction === "SHORT" ? "▼" : "▲"} {p.direction}</span>
                    {p.price > 0 && <span className="text-sm font-semibold text-text-secondary tabular-nums">${fmtPrice(p.price)}</span>}
                  </div>
                  <div className="h-1.5 bg-bg-tertiary rounded-full overflow-hidden mb-1"><div className="h-full rounded-full bg-accent-emerald" style={{ width: `${p.score}%` }} /></div>
                  <div className="text-xs font-bold text-accent-emerald mb-1">{p.score}</div>
                  <div className="text-[10px] text-text-muted leading-snug">{p.label} · {p.regime}</div>
                </div>
              ))}
            </div>

            <div className="flex gap-1.5 overflow-x-auto pb-1 -mx-3 px-3 sm:mx-0 sm:px-0">
              {[{ id:"all", l:`All (${classCounts.all})` },{ id:"stock", l:`Stocks (${classCounts.stock})` },{ id:"crypto", l:`Crypto (${classCounts.crypto})` },{ id:"fx", l:`FX (${classCounts.fx})` },{ id:"commodity", l:`Commodities (${classCounts.commodity})` }].map(tab => (
                <button key={tab.id} onClick={() => setFilter(tab.id)} className={`px-3.5 py-1.5 rounded-md text-xs font-semibold border whitespace-nowrap transition-all shrink-0 ${filter === tab.id ? "bg-accent-cyan/10 text-accent-cyan border-accent-cyan/25" : "text-text-muted border-transparent hover:text-text-secondary"}`}>{tab.l}</button>
              ))}
            </div>

            <div className="hidden lg:block rounded-xl overflow-hidden border border-border-default">
              <div className="grid grid-cols-[minmax(40px,0.5fr)_minmax(70px,1.2fr)_minmax(60px,0.8fr)_minmax(90px,1.2fr)_minmax(70px,1fr)_minmax(90px,1.4fr)_minmax(50px,0.6fr)_minmax(45px,0.7fr)_minmax(100px,2fr)] px-4 py-2.5 bg-bg-tertiary/50 border-b border-border-default">
                {["RANK","ASSET","CLASS","PRICE","DIRECTION","SCORE","RSI","ADX","LABEL"].map(h => <span key={h} className="text-[10px] font-semibold text-text-muted uppercase tracking-wider">{h}</span>)}
              </div>
              {filtered.map((p, i) => (
                <div key={i} className={`grid grid-cols-[minmax(40px,0.5fr)_minmax(70px,1.2fr)_minmax(60px,0.8fr)_minmax(90px,1.2fr)_minmax(70px,1fr)_minmax(90px,1.4fr)_minmax(50px,0.6fr)_minmax(45px,0.7fr)_minmax(100px,2fr)] px-4 py-2.5 items-center border-b border-border-default/30 hover:bg-bg-tertiary/30 transition-colors ${i%2===0 ? "" : "bg-bg-secondary/20"}`}>
                  <span className="text-sm text-text-muted">{p.rank}</span>
                  <span className="text-sm font-bold">{p.asset}</span>
                  <span><span className={`px-2 py-0.5 rounded text-[9px] font-bold ${clsBg[p.cls] || 'bg-bg-tertiary'} ${clsTx[p.cls] || 'text-white'}`}>{p.cls}</span></span>
                  <span className="text-sm text-text-secondary tabular-nums">{p.price > 0 ? `$${fmtPrice(p.price)}` : "—"}</span>
                  <span className={`text-xs font-bold ${p.direction === "LONG" ? "text-accent-emerald" : p.direction === "SHORT" ? "text-accent-crimson" : "text-accent-amber"}`}>{p.direction === "SHORT" ? "▼" : "▲"} {p.direction}</span>
                  <ScoreBar value={p.score} />
                  <span className={`text-xs font-semibold tabular-nums ${p.rsi <= 30 ? "text-accent-crimson" : p.rsi >= 70 ? "text-accent-emerald" : "text-text-muted"}`}>{p.rsi}</span>
                  <span className="text-xs text-text-muted tabular-nums">{p.adx}</span>
                  <span className="text-xs text-text-muted truncate">{p.label} · {p.regime}</span>
                </div>
              ))}
            </div>
            <div className="lg:hidden space-y-2">
              {filtered.map((p, i) => (
                <div key={i} className="bg-bg-secondary/60 border border-border-default rounded-xl p-3.5">
                  <div className="flex justify-between items-center mb-2">
                    <div className="flex items-center gap-2">
                      <span className="text-xs text-text-muted font-semibold">#{p.rank}</span>
                      <span className="text-sm font-bold">{p.asset}</span>
                      <span className={`px-1.5 py-0.5 rounded text-[8px] font-bold ${clsBg[p.cls] || 'bg-bg-tertiary'} ${clsTx[p.cls] || 'text-white'}`}>{p.cls}</span>
                    </div>
                    <span className={`text-sm font-bold ${p.direction === "LONG" ? "text-accent-emerald" : p.direction === "SHORT" ? "text-accent-crimson" : "text-text-muted"}`}>{p.direction === "SHORT" ? "▼" : "▲"} {p.direction}</span>
                  </div>
                  <div className="flex items-center justify-between">
                    <ScoreBar value={p.score} />
                    <div className="flex gap-3 text-xs"><span className="text-text-muted tabular-nums">RSI {p.rsi}</span><span className="text-text-muted tabular-nums">ADX {p.adx}</span></div>
                  </div>
                  <div className="text-[10px] text-text-muted mt-1.5">{p.label} · {p.regime}</div>
                </div>
              ))}
            </div>
          </>
        )}
      </div>
    </AppShell>
  );
}
