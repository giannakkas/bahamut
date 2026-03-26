'use client';
import { useState } from 'react';
import AppShell from '@/components/layout/AppShell';

const PICKS = [
  { rank:1, asset:"MSFT", cls:"indices", price:381.87, chg:-0.30, dir:"SHORT", score:100, whales:null, rsi:28.5, adx:36.3, reason:"Bearish EMA alignment · Below 200...", active:false },
  { rank:2, asset:"TSLA", cls:"indices", price:367.97, chg:-1.31, dir:"SHORT", score:100, whales:null, rsi:29, adx:42.1, reason:"Bearish EMA alignment · Below 200...", active:false },
  { rank:3, asset:"ABT", cls:"indices", price:105.55, chg:-0.59, dir:"SHORT", score:100, whales:"👁 👀", rsi:31.7, adx:29.9, reason:"Bearish EMA alignment · Below 200...", active:true, activeLabel:"ACTIVE · Vol 1.5x" },
  { rank:4, asset:"GILD", cls:"indices", price:137.25, chg:-0.95, dir:"SHORT", score:100, whales:null, rsi:26.3, adx:50.1, reason:"Bearish EMA alignment · Below 200...", active:false },
  { rank:5, asset:"KO", cls:"indices", price:74.78, chg:-0.23, dir:"SHORT", score:100, whales:null, rsi:25.9, adx:54, reason:"Bearish EMA alignment · Below 200...", active:false },
  { rank:6, asset:"PEP", cls:"indices", price:150.11, chg:-1.21, dir:"SHORT", score:100, whales:null, rsi:19.1, adx:62.7, reason:"Bearish EMA alignment · Below 200...", active:false },
  { rank:7, asset:"SEDG", cls:"indices", price:51.71, chg:-0.79, dir:"NEUTRAL", score:100, whales:null, rsi:76.4, adx:64.9, reason:"Bullish EMA alignment · Above 200...", active:false },
  { rank:8, asset:"SMCI", cls:"indices", price:28.56, chg:-5.69, dir:"SHORT", score:100, whales:"👁 👀", rsi:17.2, adx:67.3, reason:"Bearish EMA alignment · Below 200...", active:false },
  { rank:9, asset:"HON", cls:"indices", price:221.63, chg:-0.14, dir:"SHORT", score:100, whales:null, rsi:27.3, adx:58.3, reason:"Bearish EMA alignment · Below 200...", active:false },
  { rank:10, asset:"CCI", cls:"indices", price:82.41, chg:-1.62, dir:"SHORT", score:100, whales:"👁 👀", rsi:28.5, adx:54.3, reason:"Bearish EMA alignment · RSI overso...", active:false },
  { rank:11, asset:"ABBV", cls:"indices", price:205.07, chg:-0.82, dir:"SHORT", score:98, whales:"👁 👀", rsi:23.7, adx:59.6, reason:"Bearish EMA alignment · Below 200...", active:false },
  { rank:12, asset:"BTCUSD", cls:"crypto", price:67842.50, chg:1.22, dir:"LONG", score:92, whales:"👁 👀", rsi:58.3, adx:44.1, reason:"Bullish EMA alignment · Above 200...", active:false },
  { rank:13, asset:"ETHUSD", cls:"crypto", price:3421.80, chg:0.87, dir:"LONG", score:88, whales:"👁", rsi:52.7, adx:38.6, reason:"Bullish trend · Momentum building...", active:false },
  { rank:14, asset:"EURUSD", cls:"fx", price:1.0842, chg:-0.15, dir:"SHORT", score:85, whales:null, rsi:41.2, adx:29.8, reason:"Dollar strength · Below 200 DMA...", active:false },
];

const CC = { all:215, stocks:145, crypto:38, fx:26, commodities:6 };
const clsBg: Record<string,string> = { indices:"bg-accent-violet", crypto:"bg-accent-emerald", fx:"bg-accent-cyan", commodities:"bg-accent-amber" };
const clsTx: Record<string,string> = { indices:"text-white", crypto:"text-white", fx:"text-white", commodities:"text-black" };

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
  const [filter, setFilter] = useState("all");
  const filtered = filter === "all" ? PICKS : PICKS.filter(p => filter === "stocks" ? p.cls === "indices" : p.cls === filter);
  const top5 = filtered.slice(0, 5);

  return (
    <AppShell>
      <div className="w-full space-y-5">
        {/* Header */}
        <div className="flex flex-col sm:flex-row sm:justify-between sm:items-start gap-3">
          <div>
            <div className="flex items-center gap-3 flex-wrap">
              <h1 className="text-xl sm:text-2xl font-bold">Top Picks</h1>
              <span className="px-2.5 py-0.5 rounded-full bg-accent-emerald/15 text-accent-emerald text-xs font-semibold">{CC.all} assets scanned</span>
            </div>
            <div className="text-xs text-text-muted mt-1">AI scanner ranks all assets by opportunity strength · Last scan: 21 Mar, 20:54</div>
          </div>
          <div className="flex items-center gap-3">
            <div className="text-right hidden sm:block">
              <div className="text-[9px] text-text-muted uppercase tracking-wider">Next Scan</div>
              <div className="text-base font-bold tabular-nums">6:47</div>
            </div>
            <button className="px-4 py-2 rounded-lg bg-gradient-to-r from-accent-violet to-[#4c3ad1] text-white font-bold text-xs shadow-lg shadow-accent-violet/20 hover:brightness-110">Scan Now</button>
          </div>
        </div>

        {/* Top 5 Cards — horizontal scroll on mobile */}
        <div className="flex gap-3 overflow-x-auto pb-1 -mx-3 px-3 sm:mx-0 sm:px-0 sm:grid sm:grid-cols-3 lg:grid-cols-5 xl:grid-cols-5 2xl:grid-cols-5 sm:overflow-visible">
          {top5.map((p, i) => (
            <div key={i} className="min-w-[180px] sm:min-w-0 bg-bg-secondary/60 border border-border-default rounded-xl p-3.5 shrink-0">
              <div className="flex justify-between items-start mb-1.5">
                <div className="flex items-baseline gap-1.5"><span className="text-xs text-text-muted">#{p.rank}</span><span className="text-base font-extrabold">{p.asset}</span></div>
                <span className={`px-2 py-0.5 rounded text-[9px] font-bold ${clsBg[p.cls]} ${clsTx[p.cls]}`}>{p.cls}</span>
              </div>
              <div className="flex justify-between items-center mb-2">
                <span className={`text-sm font-extrabold ${p.dir === "LONG" ? "text-accent-emerald" : p.dir === "SHORT" ? "text-accent-crimson" : "text-text-secondary"}`}>{p.dir === "SHORT" ? "▼" : "▲"} {p.dir}</span>
                <span className="text-sm font-semibold text-text-secondary tabular-nums">${p.price > 1000 ? p.price.toLocaleString("en",{minimumFractionDigits:2}) : p.price.toFixed(2)}</span>
              </div>
              <div className="h-1.5 bg-bg-tertiary rounded-full overflow-hidden mb-1"><div className="h-full rounded-full bg-accent-emerald" style={{ width: `${p.score}%` }} /></div>
              <div className="text-xs font-bold text-accent-emerald mb-1">{p.score}</div>
              <div className="text-[10px] text-text-muted leading-snug">{p.reason}</div>
              {p.active && <div className="mt-2"><span className="px-2 py-0.5 rounded text-[9px] font-bold bg-accent-emerald/15 text-accent-emerald">{p.activeLabel}</span></div>}
            </div>
          ))}
        </div>

        {/* Filter Tabs — scrollable on mobile */}
        <div className="flex gap-1.5 overflow-x-auto pb-1 -mx-3 px-3 sm:mx-0 sm:px-0">
          {[{ id:"all", l:`All (${CC.all})` },{ id:"stocks", l:`Stocks (${CC.stocks})` },{ id:"crypto", l:`Crypto (${CC.crypto})` },{ id:"fx", l:`FX (${CC.fx})` },{ id:"commodities", l:`Commodities (${CC.commodities})` }].map(tab => (
            <button key={tab.id} onClick={() => setFilter(tab.id)} className={`px-3.5 py-1.5 rounded-md text-xs font-semibold border whitespace-nowrap transition-all shrink-0 ${filter === tab.id ? "bg-accent-cyan/10 text-accent-cyan border-accent-cyan/25" : "text-text-muted border-transparent hover:text-text-secondary"}`}>{tab.l}</button>
          ))}
        </div>

        {/* Table — desktop */}
        <div className="hidden lg:block rounded-xl overflow-hidden border border-border-default">
          <div className="grid grid-cols-[minmax(40px,0.5fr)_minmax(60px,1fr)_minmax(60px,0.8fr)_minmax(80px,1.2fr)_minmax(65px,1fr)_minmax(50px,0.6fr)_minmax(90px,1.4fr)_minmax(55px,0.8fr)_minmax(45px,0.7fr)_minmax(45px,0.7fr)_minmax(120px,3fr)] px-4 py-2.5 bg-bg-tertiary/50 border-b border-border-default">
            {["RANK","ASSET","CLASS","PRICE","CHANGE","DIR","SCORE","WHALES","RSI","ADX","REASONS"].map(h => <span key={h} className="text-[10px] font-semibold text-text-muted uppercase tracking-wider">{h}</span>)}
          </div>
          {filtered.map((p, i) => (
            <div key={i} className={`grid grid-cols-[minmax(40px,0.5fr)_minmax(60px,1fr)_minmax(60px,0.8fr)_minmax(80px,1.2fr)_minmax(65px,1fr)_minmax(50px,0.6fr)_minmax(90px,1.4fr)_minmax(55px,0.8fr)_minmax(45px,0.7fr)_minmax(45px,0.7fr)_minmax(120px,3fr)] px-4 py-2.5 items-center border-b border-border-default/30 hover:bg-bg-tertiary/30 transition-colors ${i%2===0 ? "" : "bg-bg-secondary/20"}`}>
              <span className="text-sm text-text-muted">{p.rank}</span>
              <span className="text-sm font-bold">{p.asset}</span>
              <span><span className={`px-2 py-0.5 rounded text-[9px] font-bold ${clsBg[p.cls]} ${clsTx[p.cls]}`}>{p.cls}</span></span>
              <span className="text-sm text-text-secondary tabular-nums">{p.price < 10 ? p.price.toFixed(4) : p.price > 1000 ? p.price.toLocaleString("en",{minimumFractionDigits:2,maximumFractionDigits:2}) : p.price.toFixed(2)}</span>
              <span className={`text-xs font-semibold tabular-nums ${p.chg >= 0 ? "text-accent-emerald" : "text-accent-crimson"}`}>{p.chg >= 0 ? "+" : ""}{p.chg.toFixed(2)}%</span>
              <span className={`text-xs ${p.dir === "LONG" ? "text-accent-emerald" : p.dir === "SHORT" ? "text-accent-crimson" : "text-accent-amber"}`}>{p.dir === "SHORT" ? "▼" : "▲"}</span>
              <ScoreBar value={p.score} />
              <span className="text-xs">{p.whales || "—"}</span>
              <span className={`text-xs font-semibold tabular-nums ${p.rsi <= 30 ? "text-accent-crimson" : p.rsi >= 70 ? "text-accent-emerald" : "text-text-muted"}`}>{p.rsi}</span>
              <span className="text-xs text-text-muted tabular-nums">{p.adx}</span>
              <span className="text-xs text-text-muted truncate">{p.reason}</span>
            </div>
          ))}
        </div>

        {/* Table — mobile/tablet card view */}
        <div className="lg:hidden space-y-2">
          {filtered.map((p, i) => (
            <div key={i} className="bg-bg-secondary/60 border border-border-default rounded-xl p-3.5">
              <div className="flex justify-between items-center mb-2">
                <div className="flex items-center gap-2">
                  <span className="text-xs text-text-muted font-semibold">#{p.rank}</span>
                  <span className="text-sm font-bold">{p.asset}</span>
                  <span className={`px-1.5 py-0.5 rounded text-[8px] font-bold ${clsBg[p.cls]} ${clsTx[p.cls]}`}>{p.cls}</span>
                </div>
                <span className={`text-sm font-bold ${p.dir === "LONG" ? "text-accent-emerald" : p.dir === "SHORT" ? "text-accent-crimson" : "text-text-muted"}`}>{p.dir === "SHORT" ? "▼" : "▲"} {p.dir}</span>
              </div>
              <div className="flex items-center justify-between mb-2">
                <span className="text-sm font-semibold text-text-secondary tabular-nums">${p.price > 1000 ? p.price.toLocaleString("en",{minimumFractionDigits:2}) : p.price < 10 ? p.price.toFixed(4) : p.price.toFixed(2)}</span>
                <span className={`text-xs font-semibold tabular-nums ${p.chg >= 0 ? "text-accent-emerald" : "text-accent-crimson"}`}>{p.chg >= 0 ? "+" : ""}{p.chg.toFixed(2)}%</span>
              </div>
              <div className="flex items-center justify-between">
                <ScoreBar value={p.score} />
                <div className="flex gap-3 text-xs">
                  <span className={`tabular-nums ${p.rsi <= 30 ? "text-accent-crimson" : "text-text-muted"}`}>RSI {p.rsi}</span>
                  <span className="text-text-muted tabular-nums">ADX {p.adx}</span>
                  {p.whales && <span>{p.whales}</span>}
                </div>
              </div>
              <div className="text-[10px] text-text-muted mt-2">{p.reason}</div>
            </div>
          ))}
        </div>
      </div>
    </AppShell>
  );
}
