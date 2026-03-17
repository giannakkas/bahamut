'use client';

import { useState, useEffect, useRef } from 'react';

// Animated candlestick background
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

    const W = canvas.offsetWidth;
    const H = canvas.offsetHeight;

    // Generate realistic candle data
    let price = 150;
    const candles: { o: number; h: number; l: number; c: number; x: number }[] = [];
    for (let i = 0; i < 60; i++) {
      const change = (Math.random() - 0.48) * 4;
      const o = price;
      const c = price + change;
      const h = Math.max(o, c) + Math.random() * 2;
      const l = Math.min(o, c) - Math.random() * 2;
      candles.push({ o, h, l, c, x: i * (W / 55) - 20 });
      price = c;
    }

    const minP = Math.min(...candles.map(c => c.l));
    const maxP = Math.max(...candles.map(c => c.h));
    const scaleY = (v: number) => H - ((v - minP) / (maxP - minP)) * H * 0.8 - H * 0.1;

    let offset = 0;
    const draw = () => {
      ctx.clearRect(0, 0, W, H);
      offset += 0.15;

      candles.forEach((c, i) => {
        const x = c.x - offset % (W / 55) + W / 55;
        if (x < -20 || x > W + 20) return;

        const opacity = Math.min(1, Math.min(x / 100, (W - x) / 100)) * 0.25;
        const bullish = c.c >= c.o;
        const color = bullish ? `rgba(16, 185, 129, ${opacity})` : `rgba(239, 68, 68, ${opacity})`;

        // Wick
        ctx.strokeStyle = color;
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(x + 5, scaleY(c.h));
        ctx.lineTo(x + 5, scaleY(c.l));
        ctx.stroke();

        // Body
        ctx.fillStyle = color;
        const bodyTop = scaleY(Math.max(c.o, c.c));
        const bodyBot = scaleY(Math.min(c.o, c.c));
        ctx.fillRect(x, bodyTop, 10, Math.max(1, bodyBot - bodyTop));
      });

      requestAnimationFrame(draw);
    };
    draw();
  }, []);

  return <canvas ref={canvasRef} className="absolute inset-0 w-full h-full" />;
}

// Animated price ticker
function PriceTicker() {
  const [prices, setPrices] = useState([
    { symbol: 'EUR/USD', price: 1.1519, change: 0.48 },
    { symbol: 'GBP/USD', price: 1.2938, change: -0.12 },
    { symbol: 'BTC/USD', price: 83724, change: 2.34 },
    { symbol: 'GOLD', price: 2998.5, change: 0.87 },
    { symbol: 'AAPL', price: 252.78, change: -1.23 },
    { symbol: 'TSLA', price: 265.30, change: 3.15 },
    { symbol: 'NVDA', price: 138.75, change: -0.45 },
    { symbol: 'ETH/USD', price: 1918.3, change: 1.67 },
  ]);

  useEffect(() => {
    const interval = setInterval(() => {
      setPrices(prev => prev.map(p => ({
        ...p,
        price: p.price * (1 + (Math.random() - 0.5) * 0.001),
        change: p.change + (Math.random() - 0.5) * 0.1,
      })));
    }, 2000);
    return () => clearInterval(interval);
  }, []);

  return (
    <div className="overflow-hidden border-y border-[#1a2332]">
      <div className="flex animate-scroll gap-8 py-3 px-4">
        {[...prices, ...prices].map((p, i) => (
          <div key={i} className="flex items-center gap-3 whitespace-nowrap">
            <span className="text-sm font-semibold text-white/80">{p.symbol}</span>
            <span className="text-sm font-mono text-white/60">{p.price < 100 ? p.price.toFixed(4) : p.price.toFixed(2)}</span>
            <span className={`text-xs font-mono font-semibold ${p.change >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
              {p.change >= 0 ? '+' : ''}{p.change.toFixed(2)}%
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

function AnimatedCounter({ target, suffix = '' }: { target: string; suffix?: string }) {
  const [count, setCount] = useState(0);
  const numTarget = parseInt(target);
  useEffect(() => {
    let start = 0;
    const step = Math.ceil(numTarget / 60);
    const timer = setInterval(() => {
      start += step;
      if (start >= numTarget) { setCount(numTarget); clearInterval(timer); }
      else setCount(start);
    }, 25);
    return () => clearInterval(timer);
  }, []);
  return <>{count}{suffix}</>;
}

const AGENTS = [
  { name: 'Technical', icon: 'T', color: '#3B82F6', desc: 'Reads charts — RSI, MACD, moving averages, trend strength. Finds the patterns humans miss.' },
  { name: 'Macro', icon: 'M', color: '#6366F1', desc: 'Studies the big picture — interest rates, inflation, central banks. Sees where the economy is heading.' },
  { name: 'Sentiment', icon: 'S', color: '#8B5CF6', desc: 'Reads Reuters & CNBC headlines in real-time. Knows what the market is feeling right now.' },
  { name: 'Volatility', icon: 'V', color: '#D97706', desc: 'Measures danger. When markets are too wild, it warns everyone to pull back.' },
  { name: 'Liquidity', icon: 'L', color: '#059669', desc: 'Watches volume and price structure. Spots when big institutions are moving money.' },
  { name: 'Risk', icon: 'R', color: '#DC2626', desc: 'The guardian. Has VETO power. If the trade is too dangerous, it blocks it. No exceptions.' },
];

export default function LandingPage() {
  return (
    <div className="min-h-screen bg-[#0a0e17] text-white">
      <style jsx global>{`
        @keyframes scroll { from { transform: translateX(0); } to { transform: translateX(-50%); } }
        .animate-scroll { animation: scroll 30s linear infinite; }
        @keyframes fadeUp { from { opacity: 0; transform: translateY(30px); } to { opacity: 1; transform: translateY(0); } }
        .fade-up { animation: fadeUp 0.8s ease-out forwards; }
        .fade-up-d1 { animation: fadeUp 0.8s ease-out 0.1s forwards; opacity: 0; }
        .fade-up-d2 { animation: fadeUp 0.8s ease-out 0.2s forwards; opacity: 0; }
        .fade-up-d3 { animation: fadeUp 0.8s ease-out 0.3s forwards; opacity: 0; }
        @keyframes glow { 0%, 100% { box-shadow: 0 0 20px rgba(59, 130, 246, 0.3); } 50% { box-shadow: 0 0 40px rgba(59, 130, 246, 0.6); } }
        .glow-btn { animation: glow 3s ease-in-out infinite; }
        @keyframes pulse-line { 0% { transform: scaleX(0); opacity: 1; } 100% { transform: scaleX(1); opacity: 0; } }
      `}</style>

      {/* Nav */}
      <nav className="flex items-center justify-between px-8 py-4 max-w-7xl mx-auto relative z-20">
        <img src="/logo.png" alt="Bahamut.AI" className="h-10" />
        <div className="flex items-center gap-8">
          <a href="#agents" className="text-sm text-white/40 hover:text-white transition-colors">AI Agents</a>
          <a href="#safety" className="text-sm text-white/40 hover:text-white transition-colors">Safety</a>
          <a href="#pricing" className="text-sm text-white/40 hover:text-white transition-colors">Pricing</a>
          <a href="/login" className="text-sm text-white/40 hover:text-white transition-colors">Sign In</a>
          <a href="/login" className="bg-blue-600 hover:bg-blue-500 text-white font-semibold px-5 py-2 rounded-lg text-sm transition-colors glow-btn">
            Start Free Trial
          </a>
        </div>
      </nav>

      {/* Price Ticker */}
      <PriceTicker />

      {/* Hero with animated candles */}
      <section className="relative px-8 pt-24 pb-20 max-w-5xl mx-auto text-center overflow-hidden">
        <div className="absolute inset-0 opacity-30"><CandlestickBG /></div>
        <div className="absolute inset-0 bg-gradient-to-b from-[#0a0e17] via-transparent to-[#0a0e17]" />

        <div className="relative z-10">
          <div className="inline-flex items-center gap-2 px-4 py-2 rounded-full bg-blue-500/10 border border-blue-500/20 mb-8 fade-up">
            <span className="relative flex h-2 w-2">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
              <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-400"></span>
            </span>
            <span className="text-sm text-white/60">Live — analyzing 10 assets across FX, Crypto & Stocks</span>
          </div>

          <h1 className="text-7xl font-black leading-[1.05] mb-6 tracking-tight fade-up-d1">
            Stop Guessing.<br />
            <span className="bg-gradient-to-r from-blue-400 via-blue-500 to-cyan-400 bg-clip-text text-transparent">
              Start Knowing.
            </span>
          </h1>

          <p className="text-xl text-white/40 max-w-2xl mx-auto mb-10 leading-relaxed fade-up-d2">
            6 AI agents read the news, analyze the charts, debate each other, and tell you
            <span className="text-white font-semibold"> exactly</span> when to trade — and when to
            <span className="text-white font-semibold"> stay out</span>.
          </p>

          <div className="fade-up-d3">
            <a href="/login" className="inline-block bg-blue-600 hover:bg-blue-500 text-white font-bold px-12 py-4 rounded-xl text-lg transition-all glow-btn hover:scale-105">
              Start Your 14-Day Free Trial
            </a>
            <p className="text-sm text-white/20 mt-4">No credit card · Cancel anytime</p>
          </div>
        </div>
      </section>

      {/* Stats */}
      <section className="px-8 py-8 max-w-5xl mx-auto">
        <div className="grid grid-cols-4 gap-4">
          {[
            { value: '10', label: 'Assets Monitored', suffix: '' },
            { value: '96', label: 'Daily Cycles', suffix: '+' },
            { value: '6', label: 'AI Agents', suffix: '' },
            { value: '0', label: 'News Delay', suffix: 's' },
          ].map((s, i) => (
            <div key={i} className="text-center p-5 rounded-xl bg-[#111827] border border-[#1e293b]">
              <div className="text-3xl font-black text-blue-400 font-mono">
                <AnimatedCounter target={s.value} suffix={s.suffix} />
              </div>
              <div className="text-xs text-white/30 mt-1 uppercase tracking-wider">{s.label}</div>
            </div>
          ))}
        </div>
      </section>

      {/* Pain Points */}
      <section className="px-8 py-20 max-w-5xl mx-auto">
        <h2 className="text-4xl font-black text-center mb-4">Sound Familiar?</h2>
        <p className="text-center text-white/30 mb-12">Every trader faces these. Bahamut fixes all of them.</p>

        <div className="space-y-3">
          {[
            { bad: "You enter trades on gut feeling", good: "6 AI agents analyze with real data — RSI, MACD, EMAs, news, macro" },
            { bad: "You miss news that crashes your position", good: "Real-time Reuters & CNBC. Breaking news triggers instant re-analysis" },
            { bad: "You never know where to set your stop loss", good: "Every signal includes exact entry, stop loss, and take profit" },
            { bad: "You overtrade and blow your account", good: "Risk Agent has VETO power. Circuit breakers halt trading at loss limits" },
            { bad: "You second-guess every single decision", good: "Watch 6 AI specialists debate your trade. See exactly why they agree or disagree" },
          ].map((item, i) => (
            <div key={i} className="grid grid-cols-2 gap-0 rounded-xl overflow-hidden border border-[#1e293b]">
              <div className="bg-red-500/5 p-4 flex items-center gap-3 border-r border-[#1e293b]">
                <span className="text-red-400 text-lg font-bold">✕</span>
                <span className="text-white/60 text-sm">{item.bad}</span>
              </div>
              <div className="bg-emerald-500/5 p-4 flex items-center gap-3">
                <span className="text-emerald-400 text-lg font-bold">✓</span>
                <span className="text-white/60 text-sm">{item.good}</span>
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* Agents */}
      <section id="agents" className="px-8 py-20 bg-[#0d1117]">
        <div className="max-w-5xl mx-auto">
          <h2 className="text-4xl font-black text-center mb-4">Your AI Trading Team</h2>
          <p className="text-center text-white/30 mb-12">6 specialists. They argue. They challenge. Then they vote.</p>

          <div className="grid grid-cols-3 gap-4">
            {AGENTS.map(agent => (
              <div key={agent.name} className="p-5 rounded-xl bg-[#111827] border border-[#1e293b] hover:border-blue-500/30 transition-all hover:-translate-y-1 duration-300">
                <div className="w-12 h-12 rounded-xl flex items-center justify-center font-bold text-lg mb-3"
                  style={{ backgroundColor: agent.color + '15', color: agent.color, border: `1px solid ${agent.color}30` }}>
                  {agent.icon}
                </div>
                <div className="font-bold mb-2">{agent.name} Agent</div>
                <div className="text-sm text-white/35 leading-relaxed">{agent.desc}</div>
              </div>
            ))}
          </div>

          <div className="flex items-center justify-center gap-2 mt-12 text-sm">
            {['📊 Data In', '→', '🧠 6 Agents Analyze', '→', '⚔️ They Debate', '→', '🗳️ Vote', '→', '✅ You Decide'].map((s, i) => (
              <span key={i} className={s === '→' ? 'text-blue-400' : 'px-3 py-2 rounded-lg bg-[#111827] border border-[#1e293b] text-white/50'}>
                {s}
              </span>
            ))}
          </div>
        </div>
      </section>

      {/* Safety */}
      <section id="safety" className="px-8 py-20 max-w-5xl mx-auto">
        <h2 className="text-4xl font-black text-center mb-4">Your Money is Protected</h2>
        <p className="text-center text-white/30 mb-12">Multiple layers of safety. No exceptions.</p>

        <div className="grid grid-cols-3 gap-4">
          {[
            { title: 'Risk Agent VETO', desc: 'Too risky? Blocked instantly. No override.', icon: '🛡️', border: 'border-red-500/20' },
            { title: 'Circuit Breakers', desc: 'Hit loss limit? All trading stops automatically.', icon: '⚡', border: 'border-amber-500/20' },
            { title: 'Kill Switch', desc: 'One click. Everything closes. Immediately.', icon: '🔴', border: 'border-red-500/20' },
            { title: 'News Freeze', desc: 'Before Fed/CPI events, trading pauses automatically.', icon: '❄️', border: 'border-blue-500/20' },
            { title: 'Drawdown Limits', desc: 'Daily + weekly + total limits. Gets stricter as losses grow.', icon: '📉', border: 'border-amber-500/20' },
            { title: 'You Approve Every Trade', desc: 'Nothing executes without your OK. See the full analysis first.', icon: '✅', border: 'border-emerald-500/20' },
          ].map(item => (
            <div key={item.title} className={`p-5 rounded-xl bg-[#111827] border ${item.border}`}>
              <div className="text-2xl mb-3">{item.icon}</div>
              <div className="font-bold mb-1">{item.title}</div>
              <div className="text-sm text-white/35">{item.desc}</div>
            </div>
          ))}
        </div>
      </section>

      {/* Pricing */}
      <section id="pricing" className="px-8 py-20 bg-[#0d1117]">
        <div className="max-w-5xl mx-auto">
          <h2 className="text-4xl font-black text-center mb-3">One Bad Trade Costs More<br />Than a Year of Bahamut</h2>
          <p className="text-center text-white/30 mb-12">Start free. Upgrade when you see the results.</p>

          <div className="grid grid-cols-3 gap-6">
            {[
              { name: 'Starter', price: 49, desc: 'Learn with AI guidance', popular: false,
                features: ['4 FX + Gold pairs', '6 AI agents on every trade', 'Trade approval cards', 'Risk dashboard', 'Trade journal'] },
              { name: 'Pro', price: 149, desc: 'Every edge, every asset', popular: true,
                features: ['All 10 assets (FX, Crypto, Stocks)', 'All timeframes', 'Breaking news alerts (0 delay)', 'AI daily market brief', 'Economic event radar', 'Emergency cycles', 'Priority support'] },
              { name: 'Institutional', price: 499, desc: 'For funds & pro desks', popular: false,
                features: ['Everything in Pro', 'Unlimited assets', 'API access', 'Multi-user workspace', 'Custom agent weights', 'Dedicated manager'] },
            ].map(plan => (
              <div key={plan.name} className={`rounded-2xl p-6 relative ${plan.popular ? 'bg-blue-600/10 border-2 border-blue-500/40' : 'bg-[#111827] border border-[#1e293b]'}`}>
                {plan.popular && (
                  <div className="absolute -top-3 left-1/2 -translate-x-1/2 px-4 py-1 bg-blue-600 text-white text-xs font-bold rounded-full">
                    MOST POPULAR
                  </div>
                )}
                <div className="text-lg font-bold">{plan.name}</div>
                <div className="text-sm text-white/30 mb-4">{plan.desc}</div>
                <div className="flex items-baseline gap-1 mb-6">
                  <span className="text-5xl font-black">${plan.price}</span>
                  <span className="text-white/20">/mo</span>
                </div>
                <ul className="space-y-2.5 mb-6">
                  {plan.features.map((f, i) => (
                    <li key={i} className="text-sm text-white/40 flex items-start gap-2">
                      <span className="text-emerald-400 mt-0.5">✓</span> {f}
                    </li>
                  ))}
                </ul>
                <a href="/login" className={`block text-center py-3 rounded-xl font-semibold text-sm transition-all ${plan.popular ? 'bg-blue-600 hover:bg-blue-500 text-white glow-btn' : 'bg-white/5 hover:bg-white/10 text-white/60 border border-[#1e293b]'}`}>
                  Start 14-Day Free Trial
                </a>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* CTA */}
      <section className="px-8 py-24 text-center relative overflow-hidden">
        <div className="absolute inset-0 opacity-20"><CandlestickBG /></div>
        <div className="absolute inset-0 bg-gradient-to-b from-[#0a0e17] via-transparent to-[#0a0e17]" />
        <div className="relative z-10">
          <h2 className="text-4xl font-black mb-4">Ready to Trade Smarter?</h2>
          <p className="text-white/30 mb-8 max-w-lg mx-auto">Join traders who stopped guessing and started letting AI do the heavy lifting.</p>
          <a href="/login" className="inline-block bg-blue-600 hover:bg-blue-500 text-white font-bold px-12 py-4 rounded-xl text-lg glow-btn hover:scale-105 transition-all">
            Start Free Trial Now
          </a>
        </div>
      </section>

      {/* Footer */}
      <footer className="px-8 py-10 border-t border-[#1e293b]">
        <div className="max-w-7xl mx-auto flex items-center justify-between">
          <img src="/logo.png" alt="Bahamut.AI" className="h-8 opacity-50" />
          <p className="text-xs text-white/15">© 2026 Bahamut.AI · Trading involves risk · Not financial advice</p>
        </div>
      </footer>
    </div>
  );
}
