'use client';

import { useState, useEffect, useRef } from 'react';

function CandlestickBG() {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    canvas.width = canvas.offsetWidth * 2;
    canvas.height = canvas.offsetHeight * 2;
    ctx.scale(2, 2);
    const W = canvas.offsetWidth, H = canvas.offsetHeight;

    let price = 150;
    const candles: { o: number; h: number; l: number; c: number; x: number }[] = [];
    for (let i = 0; i < 60; i++) {
      const change = (Math.random() - 0.48) * 4;
      const o = price, c = price + change;
      const h = Math.max(o, c) + Math.random() * 2, l = Math.min(o, c) - Math.random() * 2;
      candles.push({ o, h, l, c, x: i * (W / 55) - 20 });
      price = c;
    }
    const minP = Math.min(...candles.map(c => c.l)), maxP = Math.max(...candles.map(c => c.h));
    const scaleY = (v: number) => H - ((v - minP) / (maxP - minP)) * H * 0.8 - H * 0.1;

    let offset = 0;
    const draw = () => {
      ctx.clearRect(0, 0, W, H);
      offset += 0.12;
      candles.forEach(c => {
        const x = c.x - offset % (W / 55) + W / 55;
        if (x < -20 || x > W + 20) return;
        const opacity = Math.min(1, Math.min(x / 100, (W - x) / 100)) * 0.15;
        const bull = c.c >= c.o;
        const color = bull ? `rgba(34, 197, 94, ${opacity})` : `rgba(239, 68, 68, ${opacity * 0.8})`;
        ctx.strokeStyle = color;
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(x + 5, scaleY(c.h));
        ctx.lineTo(x + 5, scaleY(c.l));
        ctx.stroke();
        ctx.fillStyle = color;
        const top = scaleY(Math.max(c.o, c.c)), bot = scaleY(Math.min(c.o, c.c));
        ctx.fillRect(x, top, 10, Math.max(1, bot - top));
      });
      requestAnimationFrame(draw);
    };
    draw();
  }, []);
  return <canvas ref={canvasRef} className="absolute inset-0 w-full h-full" />;
}

function PriceTicker() {
  const [prices, setPrices] = useState([
    { s: 'EUR/USD', p: 1.1519, c: 0.48 }, { s: 'GBP/USD', p: 1.2938, c: -0.12 },
    { s: 'BTC/USD', p: 83724, c: 2.34 }, { s: 'GOLD', p: 2998.5, c: 0.87 },
    { s: 'AAPL', p: 252.78, c: -1.23 }, { s: 'TSLA', p: 265.30, c: 3.15 },
    { s: 'NVDA', p: 138.75, c: -0.45 }, { s: 'ETH/USD', p: 1918.3, c: 1.67 },
  ]);
  useEffect(() => {
    const i = setInterval(() => {
      setPrices(prev => prev.map(p => ({ ...p, p: p.p * (1 + (Math.random() - 0.5) * 0.001), c: p.c + (Math.random() - 0.5) * 0.08 })));
    }, 2500);
    return () => clearInterval(i);
  }, []);
  return (
    <div className="overflow-hidden border-y border-[#1a1a1a] bg-[#0a0a0a]">
      <div className="flex animate-scroll gap-8 py-2.5 px-4">
        {[...prices, ...prices].map((p, i) => (
          <div key={i} className="flex items-center gap-3 whitespace-nowrap">
            <span className="text-xs font-semibold text-[#C9A94E]">{p.s}</span>
            <span className="text-xs font-mono text-white/50">{p.p < 100 ? p.p.toFixed(4) : p.p.toFixed(2)}</span>
            <span className={`text-xs font-mono ${p.c >= 0 ? 'text-emerald-500' : 'text-red-500'}`}>{p.c >= 0 ? '+' : ''}{p.c.toFixed(2)}%</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function Counter({ target, suffix = '' }: { target: string; suffix?: string }) {
  const [c, setC] = useState(0);
  const n = parseInt(target);
  useEffect(() => { let s = 0; const step = Math.ceil(n / 60); const t = setInterval(() => { s += step; if (s >= n) { setC(n); clearInterval(t); } else setC(s); }, 25); return () => clearInterval(t); }, []);
  return <>{c}{suffix}</>;
}

export default function LandingPage() {
  return (
    <div className="min-h-screen bg-[#050505] text-white" style={{ fontFamily: "Outfit, sans-serif" }}>

      <style jsx global>{`
        @import url('https://fonts.googleapis.com/css2?family=DM+Serif+Display:ital@0;1&family=Outfit:wght@300;400;500;600;700;800;900&display=swap');
        @keyframes scroll { from { transform: translateX(0); } to { transform: translateX(-50%); } }
        .animate-scroll { animation: scroll 30s linear infinite; }
        @keyframes fadeUp { from { opacity: 0; transform: translateY(30px); } to { opacity: 1; transform: translateY(0); } }
        .fade-up { animation: fadeUp 0.8s ease-out forwards; }
        .fade-d1 { animation: fadeUp 0.8s 0.1s ease-out forwards; opacity: 0; }
        .fade-d2 { animation: fadeUp 0.8s 0.2s ease-out forwards; opacity: 0; }
        .fade-d3 { animation: fadeUp 0.8s 0.3s ease-out forwards; opacity: 0; }
        @keyframes goldShimmer { 0%{background-position:200% 0} 100%{background-position:-200% 0} }
        .gold-shimmer { background: linear-gradient(90deg, #C9A94E, #E8D48B, #C9A94E, #A07C30, #C9A94E); background-size: 200% 100%; animation: goldShimmer 4s linear infinite; -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
        @keyframes glow { 0%,100%{box-shadow:0 0 15px rgba(201,169,78,0.3)} 50%{box-shadow:0 0 30px rgba(201,169,78,0.6)} }
        .gold-glow { animation: glow 3s ease-in-out infinite; }
      `}</style>

      {/* Nav */}
      <nav className="flex items-center justify-between px-8 py-4 max-w-7xl mx-auto relative z-20 border-b border-[#1a1a1a]">
        <img src="/logo.png" alt="Bahamut.AI" className="h-20 -my-3" />
        <div className="flex items-center gap-8">
          <a href="#agents" className="text-sm text-white/30 hover:text-[#C9A94E] transition-colors">AI Agents</a>
          <a href="#safety" className="text-sm text-white/30 hover:text-[#C9A94E] transition-colors">Safety</a>
          <a href="#pricing" className="text-sm text-white/30 hover:text-[#C9A94E] transition-colors">Pricing</a>
          <a href="/login" className="text-sm text-white/30 hover:text-[#C9A94E] transition-colors">Sign In</a>
          <a href="/login" className="bg-gradient-to-r from-[#C9A94E] to-[#A07C30] hover:from-[#D4B85C] hover:to-[#B08C3A] text-black font-bold px-6 py-2.5 rounded-lg text-sm transition-all gold-glow">
            Start Free Trial
          </a>
        </div>
      </nav>

      <PriceTicker />

      {/* Hero */}
      <section className="relative px-8 pt-28 pb-24 max-w-5xl mx-auto text-center overflow-hidden">
        <div className="absolute inset-0 opacity-40"><CandlestickBG /></div>
        <div className="absolute inset-0 bg-gradient-to-b from-[#050505] via-transparent to-[#050505]" />

        <div className="relative z-10">
          <div className="inline-flex items-center gap-2 px-4 py-2 rounded-full border border-[#C9A94E]/20 bg-[#C9A94E]/5 mb-8 fade-up">
            <span className="relative flex h-2 w-2">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-500 opacity-75"></span>
              <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500"></span>
            </span>
            <span className="text-sm text-[#C9A94E]/80">Live — analyzing 10 assets across FX, Crypto & Stocks</span>
          </div>

          <h1 className="text-7xl leading-[1.05] mb-7 tracking-tight fade-d1" style={{ fontFamily: "DM Serif Display, Georgia, serif" }}>
            Stop Guessing.<br />
            <span className="gold-shimmer">Start Knowing.</span>
          </h1>

          <p className="text-xl text-white/35 max-w-2xl mx-auto mb-10 leading-relaxed fade-d2">
            6 AI agents read the news, analyze the charts, debate each other, and tell you
            <span className="text-white/80 font-semibold"> exactly</span> when to trade — and when to
            <span className="text-white/80 font-semibold"> stay out</span>.
          </p>

          <div className="fade-d3">
            <a href="/login" className="inline-block bg-gradient-to-r from-[#C9A94E] to-[#A07C30] hover:from-[#D4B85C] hover:to-[#B08C3A] text-black font-black px-14 py-4 rounded-xl text-lg transition-all gold-glow hover:scale-105">
              Start Your 14-Day Free Trial
            </a>
            <p className="text-sm text-white/15 mt-4">No credit card · Cancel anytime</p>
          </div>
        </div>
      </section>

      {/* Stats */}
      <section className="px-8 py-8 max-w-5xl mx-auto">
        <div className="grid grid-cols-4 gap-4">
          {[
            { v: '10', l: 'Assets Monitored', s: '' },
            { v: '96', l: 'Daily Cycles', s: '+' },
            { v: '6', l: 'AI Agents', s: '' },
            { v: '0', l: 'News Delay', s: 's' },
          ].map((stat, i) => (
            <div key={i} className="text-center p-5 rounded-xl bg-[#0a0a0a] border border-[#1a1a1a]">
              <div className="text-3xl font-black text-[#C9A94E] font-mono"><Counter target={stat.v} suffix={stat.s} /></div>
              <div className="text-[10px] text-white/20 mt-1 uppercase tracking-[0.2em]">{stat.l}</div>
            </div>
          ))}
        </div>
      </section>

      {/* Pain Points */}
      <section className="px-8 py-20 max-w-5xl mx-auto">
        <h2 className="text-4xl text-center mb-3" style={{ fontFamily: "DM Serif Display, Georgia, serif" }}>Sound Familiar?</h2>
        <p className="text-center text-white/20 mb-12">Every trader faces these. Bahamut fixes all of them.</p>
        <div className="space-y-3">
          {[
            { bad: "You trade on gut feeling and hope", good: "6 AI agents analyze with real data — RSI, MACD, EMAs, news, macro" },
            { bad: "You miss news that crashes your position", good: "Real-time Reuters & CNBC. Breaking news triggers instant re-analysis" },
            { bad: "You never know where to set your stop loss", good: "Every signal includes exact entry, stop loss, and take profit" },
            { bad: "You overtrade and blow your account", good: "Risk Agent has VETO power. Circuit breakers halt at your loss limit" },
            { bad: "You second-guess every single decision", good: "Watch 6 AI specialists debate. See exactly why they agree or disagree" },
          ].map((item, i) => (
            <div key={i} className="grid grid-cols-2 rounded-xl overflow-hidden border border-[#1a1a1a]">
              <div className="bg-red-500/[0.03] p-4 flex items-center gap-3 border-r border-[#1a1a1a]">
                <span className="text-red-500/80 font-bold">✕</span>
                <span className="text-white/40 text-sm">{item.bad}</span>
              </div>
              <div className="bg-emerald-500/[0.03] p-4 flex items-center gap-3">
                <span className="text-emerald-500/80 font-bold">✓</span>
                <span className="text-white/40 text-sm">{item.good}</span>
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* Agents */}
      <section id="agents" className="px-8 py-20 bg-[#080808] border-y border-[#1a1a1a]">
        <div className="max-w-5xl mx-auto">
          <h2 className="text-4xl text-center mb-3" style={{ fontFamily: "DM Serif Display, Georgia, serif" }}>Your AI Trading Council</h2>
          <p className="text-center text-white/20 mb-12">6 specialists. They argue. They challenge. Then they vote.</p>

          <div className="grid grid-cols-3 gap-4">
            {[
              { n: 'Technical', i: 'T', c: '#3B82F6', d: 'Reads charts — RSI, MACD, moving averages, trend strength. Finds the patterns humans miss.' },
              { n: 'Macro', i: 'M', c: '#8B5CF6', d: 'Studies interest rates, inflation, central bank moves. Sees where the economy is heading.' },
              { n: 'Sentiment', i: 'S', c: '#C9A94E', d: 'Reads Reuters & CNBC in real-time. Knows what the market is feeling right now.' },
              { n: 'Volatility', i: 'V', c: '#D97706', d: 'Measures danger. When markets are too wild, it warns everyone to pull back.' },
              { n: 'Liquidity', i: 'L', c: '#059669', d: 'Watches volume and price structure. Spots when big money is moving in or out.' },
              { n: 'Risk', i: 'R', c: '#DC2626', d: 'The guardian. Has VETO power. If the trade is too dangerous, it blocks it. No exceptions.' },
            ].map(a => (
              <div key={a.n} className="p-5 rounded-xl bg-[#0a0a0a] border border-[#1a1a1a] hover:border-[#C9A94E]/30 transition-all duration-300 hover:-translate-y-1">
                <div className="w-11 h-11 rounded-lg flex items-center justify-center font-bold mb-3"
                  style={{ backgroundColor: a.c + '10', color: a.c, border: `1px solid ${a.c}25` }}>{a.i}</div>
                <div className="font-bold mb-1.5 text-white/80">{a.n} Agent</div>
                <div className="text-sm text-white/25 leading-relaxed">{a.d}</div>
              </div>
            ))}
          </div>

          <div className="flex items-center justify-center gap-2 mt-12 text-sm">
            {['📊 Data', '→', '🧠 Analyze', '→', '⚔️ Debate', '→', '🗳️ Vote', '→', '✅ You Decide'].map((s, i) => (
              <span key={i} className={s === '→' ? 'text-[#C9A94E]/60' : 'px-3 py-2 rounded-lg bg-[#0a0a0a] border border-[#1a1a1a] text-white/35 text-xs'}>
                {s}
              </span>
            ))}
          </div>
        </div>
      </section>

      {/* Safety */}
      <section id="safety" className="px-8 py-20 max-w-5xl mx-auto">
        <h2 className="text-4xl text-center mb-3" style={{ fontFamily: "DM Serif Display, Georgia, serif" }}>Your Capital is Protected</h2>
        <p className="text-center text-white/20 mb-12">Multiple layers of protection. No exceptions.</p>
        <div className="grid grid-cols-3 gap-4">
          {[
            { t: 'Risk Agent VETO', d: 'Too risky? Blocked instantly. No override possible.', i: '🛡️' },
            { t: 'Circuit Breakers', d: 'Hit loss limit? All trading halts automatically.', i: '⚡' },
            { t: 'Emergency Kill Switch', d: 'One click. Everything closes. Immediately.', i: '🔴' },
            { t: 'Event Freeze', d: 'Before Fed/CPI events, new trades are paused.', i: '❄️' },
            { t: 'Drawdown Limits', d: 'Daily + weekly + total limits that tighten as losses grow.', i: '📉' },
            { t: 'Manual Approval', d: 'Nothing executes without your OK. Full analysis first.', i: '✅' },
          ].map(item => (
            <div key={item.t} className="p-5 rounded-xl bg-[#0a0a0a] border border-[#1a1a1a]">
              <div className="text-2xl mb-3">{item.i}</div>
              <div className="font-bold mb-1 text-white/70">{item.t}</div>
              <div className="text-sm text-white/25">{item.d}</div>
            </div>
          ))}
        </div>
      </section>

      {/* Social Proof */}
      <section className="px-8 py-16 bg-[#080808] border-y border-[#1a1a1a]">
        <div className="max-w-5xl mx-auto grid grid-cols-3 gap-6">
          {[
            { n: 'Marcus T.', r: 'Forex Trader', t: "I used to stare at charts for hours. Now Bahamut tells me exactly when the odds are in my favor — and when to stay out." },
            { n: 'Elena K.', r: 'Part-time Trader', t: "Watching 6 AI specialists argue about my trade gives me confidence I never had on my own." },
            { n: 'James W.', r: 'Crypto Investor', t: "The breaking news detector caught a Fed announcement 2 minutes before I would have entered a bad trade." },
          ].map((t, i) => (
            <div key={i} className="p-6 rounded-xl bg-[#0a0a0a] border border-[#1a1a1a]">
              <div className="text-[#C9A94E] text-lg mb-3">★★★★★</div>
              <div className="text-sm text-white/35 leading-relaxed mb-4">"{t.t}"</div>
              <div className="pt-4 border-t border-[#1a1a1a] flex items-center gap-3">
                <div className="w-9 h-9 rounded-full bg-[#C9A94E]/10 border border-[#C9A94E]/20 flex items-center justify-center text-[#C9A94E] font-bold text-sm">{t.n[0]}</div>
                <div>
                  <div className="text-sm font-semibold text-white/60">{t.n}</div>
                  <div className="text-xs text-white/20">{t.r}</div>
                </div>
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* Pricing */}
      <section id="pricing" className="px-8 py-20 max-w-5xl mx-auto">
        <h2 className="text-4xl text-center mb-3" style={{ fontFamily: "DM Serif Display, Georgia, serif" }}>One Bad Trade Costs More<br />Than a Year of Bahamut</h2>
        <p className="text-center text-white/20 mb-12">Start free. Upgrade when you see results.</p>
        <div className="grid grid-cols-3 gap-5">
          {[
            { n: 'Starter', p: 49, d: 'Learn with AI guidance', pop: false,
              f: ['4 FX + Gold pairs', '6 AI agents per trade', 'Trade approval cards', 'Risk dashboard', 'Trade journal'] },
            { n: 'Pro', p: 149, d: 'Every edge. Every asset.', pop: true,
              f: ['All 10 assets (FX, Crypto, Stocks)', 'All timeframes', 'Breaking news (0 delay)', 'AI daily market brief', 'Economic event radar', 'Emergency signal cycles', 'Priority support'] },
            { n: 'Institutional', p: 499, d: 'For funds & pro desks', pop: false,
              f: ['Everything in Pro', 'Unlimited assets', 'API access', 'Multi-user workspace', 'Custom agent weights', 'Dedicated manager'] },
          ].map(plan => (
            <div key={plan.n} className={`rounded-2xl p-6 relative ${plan.pop ? 'bg-[#C9A94E]/[0.04] border-2 border-[#C9A94E]/30' : 'bg-[#0a0a0a] border border-[#1a1a1a]'}`}>
              {plan.pop && <div className="absolute -top-3 left-1/2 -translate-x-1/2 px-4 py-1 bg-gradient-to-r from-[#C9A94E] to-[#A07C30] text-black text-xs font-black rounded-full">MOST POPULAR</div>}
              <div className="font-bold text-lg text-white/80">{plan.n}</div>
              <div className="text-sm text-white/25 mb-4">{plan.d}</div>
              <div className="flex items-baseline gap-1 mb-6">
                <span className="text-5xl font-black text-white/90">${plan.p}</span>
                <span className="text-white/15">/mo</span>
              </div>
              <ul className="space-y-2.5 mb-6">
                {plan.f.map((feat, i) => (
                  <li key={i} className="text-sm text-white/30 flex items-start gap-2">
                    <span className="text-[#C9A94E] mt-0.5 text-xs">●</span> {feat}
                  </li>
                ))}
              </ul>
              <a href="/login" className={`block text-center py-3 rounded-xl font-bold text-sm transition-all ${plan.pop ? 'bg-gradient-to-r from-[#C9A94E] to-[#A07C30] text-black gold-glow hover:scale-[1.02]' : 'bg-white/[0.03] hover:bg-white/[0.06] text-white/40 border border-[#1a1a1a]'}`}>
                Start 14-Day Free Trial
              </a>
            </div>
          ))}
        </div>
      </section>

      {/* Final CTA */}
      <section className="px-8 py-28 text-center relative overflow-hidden">
        <div className="absolute inset-0 opacity-25"><CandlestickBG /></div>
        <div className="absolute inset-0 bg-gradient-to-b from-[#050505] via-transparent to-[#050505]" />
        <div className="relative z-10">
          <h2 className="text-5xl mb-5" style={{ fontFamily: "DM Serif Display, Georgia, serif" }}>Ready to Trade<br /><span className="gold-shimmer">With Confidence?</span></h2>
          <p className="text-white/25 mb-8 max-w-lg mx-auto">Join traders who stopped guessing and started letting AI protect and grow their capital.</p>
          <a href="/login" className="inline-block bg-gradient-to-r from-[#C9A94E] to-[#A07C30] text-black font-black px-14 py-4 rounded-xl text-lg gold-glow hover:scale-105 transition-all">
            Start Free Trial Now
          </a>
        </div>
      </section>

      <footer className="px-8 py-8 border-t border-[#1a1a1a]">
        <div className="max-w-7xl mx-auto flex items-center justify-between">
          <img src="/logo.png" alt="Bahamut.AI" className="h-10 opacity-30" />
          <p className="text-[10px] text-white/10">© 2026 Bahamut.AI · Trading involves risk · Not financial advice</p>
        </div>
      </footer>
    </div>
  );
}
