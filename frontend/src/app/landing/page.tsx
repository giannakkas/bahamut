'use client';

import { useState, useEffect } from 'react';

const STATS = [
  { value: '10', label: 'Assets Monitored', suffix: '' },
  { value: '96', label: 'Daily Analysis Cycles', suffix: '+' },
  { value: '6', label: 'AI Agents Debating', suffix: '' },
  { value: '0', label: 'Seconds Delay on News', suffix: '' },
];

const TESTIMONIALS = [
  { name: 'Marcus T.', role: 'Forex Trader, London', text: "I used to stare at charts for hours trying to decide. Now Bahamut tells me exactly when the odds are in my favor — and when to stay out." },
  { name: 'Elena K.', role: 'Part-time Trader, Berlin', text: "The agent debate feature is incredible. Watching 6 AI specialists argue about my trade and then reaching consensus gives me confidence I never had." },
  { name: 'James W.', role: 'Crypto Investor, Singapore', text: "The breaking news detector caught a Fed announcement 2 minutes before I would have entered a bad trade. Paid for itself that day." },
];

const PAIN_POINTS = [
  { problem: "You enter trades based on gut feeling", solution: "6 AI agents analyze every trade with real data — RSI, MACD, EMAs, volume, news, macro" },
  { problem: "You miss important news that moves prices", solution: "Real-time news from Reuters & CNBC. Breaking news triggers instant analysis" },
  { problem: "You don't know when to exit", solution: "Every signal includes exact entry, stop loss, and take profit levels" },
  { problem: "You overtrade and blow your account", solution: "Risk Agent has VETO power. Circuit breakers halt trading when drawdown hits limits" },
  { problem: "You second-guess every decision", solution: "Watch 6 experts debate your trade. See exactly why they agree or disagree" },
];

const PLANS = [
  {
    name: 'Starter', price: 49, popular: false,
    desc: 'Perfect for learning with AI guidance',
    features: ['4 FX + Gold signals', '6 AI agents on every trade', 'Trade approval cards', 'Risk protection dashboard', 'Trade history journal'],
  },
  {
    name: 'Pro', price: 149, popular: true,
    desc: 'For serious traders who want every edge',
    features: ['All 10 assets (FX, Crypto, Stocks)', 'All timeframes (1H, 4H, Daily)', 'Breaking news alerts (0 delay)', 'AI morning market brief', 'Economic event radar', 'Emergency signal cycles', 'Priority support'],
  },
  {
    name: 'Institutional', price: 499, popular: false,
    desc: 'For funds and professional desks',
    features: ['Everything in Pro', 'Unlimited custom assets', 'API access for automation', 'Multi-user workspace', 'Custom agent weights', 'Dedicated account manager'],
  },
];

function AnimatedCounter({ target, suffix = '' }: { target: string; suffix?: string }) {
  const [count, setCount] = useState(0);
  const numTarget = parseInt(target);
  useEffect(() => {
    let start = 0;
    const duration = 2000;
    const step = Math.ceil(numTarget / (duration / 30));
    const timer = setInterval(() => {
      start += step;
      if (start >= numTarget) { setCount(numTarget); clearInterval(timer); }
      else setCount(start);
    }, 30);
    return () => clearInterval(timer);
  }, []);
  return <>{count}{suffix}</>;
}

export default function LandingPage() {
  return (
    <div className="min-h-screen bg-[#060610] text-white overflow-hidden">
      {/* Gradient orbs for atmosphere */}
      <div className="fixed inset-0 pointer-events-none overflow-hidden">
        <div className="absolute -top-40 -right-40 w-96 h-96 bg-[#6C63FF]/8 rounded-full blur-[120px]" />
        <div className="absolute top-1/3 -left-40 w-80 h-80 bg-[#E94560]/5 rounded-full blur-[100px]" />
        <div className="absolute bottom-0 right-1/4 w-96 h-96 bg-[#10B981]/5 rounded-full blur-[120px]" />
      </div>

      <div className="relative z-10">
        {/* Nav */}
        <nav className="flex items-center justify-between px-8 py-5 max-w-7xl mx-auto">
          <img src="/logo.png" alt="Bahamut.AI" className="h-10" />
          <div className="flex items-center gap-8">
            <a href="#how" className="text-sm text-white/50 hover:text-white transition-colors">How It Works</a>
            <a href="#pricing" className="text-sm text-white/50 hover:text-white transition-colors">Pricing</a>
            <a href="/login" className="text-sm text-white/50 hover:text-white transition-colors">Sign In</a>
            <a href="/login" className="relative group">
              <div className="absolute -inset-1 bg-gradient-to-r from-[#6C63FF] to-[#E94560] rounded-lg blur opacity-40 group-hover:opacity-70 transition-opacity" />
              <div className="relative bg-[#6C63FF] text-white font-semibold px-6 py-2.5 rounded-lg text-sm">
                Start Free Trial
              </div>
            </a>
          </div>
        </nav>

        {/* Hero */}
        <section className="px-8 pt-20 pb-16 max-w-5xl mx-auto text-center">
          <div className="inline-flex items-center gap-2 px-4 py-2 rounded-full bg-white/5 border border-white/10 mb-8">
            <span className="relative flex h-2 w-2">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-[#10B981] opacity-75"></span>
              <span className="relative inline-flex rounded-full h-2 w-2 bg-[#10B981]"></span>
            </span>
            <span className="text-sm text-white/70">Live now — analyzing 10 assets in real time</span>
          </div>

          <h1 className="text-6xl font-extrabold leading-[1.1] mb-6 tracking-tight">
            Stop Guessing.<br />
            <span className="bg-gradient-to-r from-[#6C63FF] via-[#9F7AFF] to-[#E94560] bg-clip-text text-transparent">
              Start Knowing.
            </span>
          </h1>

          <p className="text-xl text-white/50 max-w-2xl mx-auto mb-10 leading-relaxed">
            6 AI agents read the news, analyze the charts, debate each other, and tell you 
            <span className="text-white font-semibold"> exactly</span> when to trade — and when to 
            <span className="text-white font-semibold"> stay out</span>.
          </p>

          <div className="flex items-center justify-center gap-4 mb-6">
            <a href="/login" className="relative group">
              <div className="absolute -inset-1 bg-gradient-to-r from-[#6C63FF] to-[#E94560] rounded-xl blur opacity-50 group-hover:opacity-80 transition-opacity" />
              <div className="relative bg-[#6C63FF] hover:bg-[#5B54EE] text-white font-bold px-10 py-4 rounded-xl text-lg transition-colors">
                Start Your 14-Day Free Trial
              </div>
            </a>
          </div>
          <p className="text-sm text-white/30">No credit card · No commitment · Cancel anytime</p>
        </section>

        {/* Stats */}
        <section className="px-8 py-12 max-w-5xl mx-auto">
          <div className="grid grid-cols-4 gap-6">
            {STATS.map((stat, i) => (
              <div key={i} className="text-center p-6 rounded-2xl bg-white/[0.03] border border-white/[0.06]">
                <div className="text-4xl font-extrabold bg-gradient-to-r from-[#6C63FF] to-[#9F7AFF] bg-clip-text text-transparent">
                  <AnimatedCounter target={stat.value} suffix={stat.suffix} />
                </div>
                <div className="text-sm text-white/40 mt-1">{stat.label}</div>
              </div>
            ))}
          </div>
        </section>

        {/* Pain Points */}
        <section className="px-8 py-20 max-w-5xl mx-auto">
          <h2 className="text-3xl font-bold text-center mb-3">Sound Familiar?</h2>
          <p className="text-center text-white/40 mb-12">Every amateur trader faces these problems. Bahamut solves all of them.</p>

          <div className="space-y-4">
            {PAIN_POINTS.map((item, i) => (
              <div key={i} className="grid grid-cols-2 gap-0 rounded-xl overflow-hidden border border-white/[0.06]">
                <div className="bg-[#E94560]/5 p-5 flex items-center gap-3 border-r border-white/[0.06]">
                  <span className="text-[#E94560] text-xl">✕</span>
                  <span className="text-white/70 text-sm">{item.problem}</span>
                </div>
                <div className="bg-[#10B981]/5 p-5 flex items-center gap-3">
                  <span className="text-[#10B981] text-xl">✓</span>
                  <span className="text-white/70 text-sm">{item.solution}</span>
                </div>
              </div>
            ))}
          </div>
        </section>

        {/* How it works */}
        <section id="how" className="px-8 py-20 bg-gradient-to-b from-transparent via-[#6C63FF]/[0.03] to-transparent">
          <div className="max-w-5xl mx-auto">
            <h2 className="text-3xl font-bold text-center mb-3">Your AI Trading Team</h2>
            <p className="text-center text-white/40 mb-12">6 specialists analyze every trade. They don't always agree — and that's the point.</p>

            <div className="grid grid-cols-3 gap-5 mb-12">
              {[
                { name: 'Technical', icon: 'T', color: '#8B5CF6', desc: 'Reads charts — RSI, MACD, moving averages, trend strength. Finds the patterns.' },
                { name: 'Macro', icon: 'M', color: '#6C63FF', desc: 'Studies the big picture — interest rates, inflation, central bank moves. Sees the context.' },
                { name: 'Sentiment', icon: 'S', color: '#F43F5E', desc: 'Reads Reuters & CNBC in real-time. Knows what the market is feeling right now.' },
                { name: 'Volatility', icon: 'V', color: '#F59E0B', desc: 'Measures danger. When markets are too wild, it warns everyone to slow down.' },
                { name: 'Liquidity', icon: 'L', color: '#10B981', desc: 'Watches volume and price structure. Spots institutional money moving in or out.' },
                { name: 'Risk', icon: 'R', color: '#EF4444', desc: 'The bodyguard. Has VETO power. If the trade is too risky, it blocks it. Period.' },
              ].map(agent => (
                <div key={agent.name} className="p-5 rounded-xl bg-white/[0.02] border border-white/[0.06] hover:border-white/[0.15] transition-colors">
                  <div className="w-12 h-12 rounded-xl flex items-center justify-center text-white font-bold mb-3 text-lg"
                    style={{ backgroundColor: agent.color + '20', color: agent.color }}>
                    {agent.icon}
                  </div>
                  <div className="font-semibold mb-1">{agent.name} Agent</div>
                  <div className="text-sm text-white/40 leading-relaxed">{agent.desc}</div>
                </div>
              ))}
            </div>

            {/* Process */}
            <div className="flex items-center justify-center gap-3 text-sm text-white/40">
              {['Data In', '→', '6 Agents Analyze', '→', 'They Debate', '→', 'Vote', '→', 'You Decide'].map((step, i) => (
                <span key={i} className={step === '→' ? 'text-[#6C63FF]' : 'px-3 py-1.5 rounded-lg bg-white/[0.03] border border-white/[0.06] text-white/60'}>
                  {step}
                </span>
              ))}
            </div>
          </div>
        </section>

        {/* Safety section */}
        <section className="px-8 py-20 max-w-5xl mx-auto">
          <h2 className="text-3xl font-bold text-center mb-3">Your Money is Protected</h2>
          <p className="text-center text-white/40 mb-12">Multiple layers of safety. Because losing money is not an option.</p>

          <div className="grid grid-cols-3 gap-5">
            {[
              { title: 'Risk Agent Veto', desc: 'If ANY trade is too risky, the Risk Agent blocks it instantly. No override possible.', icon: '🛡️' },
              { title: 'Circuit Breakers', desc: 'Hit daily loss limit? System auto-halts all trading. Just like the stock exchange does.', icon: '⚡' },
              { title: 'Kill Switch', desc: 'One click closes everything. All positions. All orders. Immediately.', icon: '🔴' },
              { title: 'News Freeze', desc: 'Before major events (Fed, CPI), system freezes trading to avoid volatility traps.', icon: '❄️' },
              { title: 'Drawdown Limits', desc: 'Daily, weekly, and total loss limits. System gets more conservative as losses grow.', icon: '📊' },
              { title: 'You Approve Every Trade', desc: "Nothing executes without your OK. See the full trade card, agent opinions, and risk analysis first.", icon: '✅' },
            ].map(item => (
              <div key={item.title} className="p-5 rounded-xl bg-white/[0.02] border border-white/[0.06]">
                <div className="text-2xl mb-3">{item.icon}</div>
                <div className="font-semibold mb-1">{item.title}</div>
                <div className="text-sm text-white/40 leading-relaxed">{item.desc}</div>
              </div>
            ))}
          </div>
        </section>

        {/* Testimonials */}
        <section className="px-8 py-20 bg-gradient-to-b from-transparent via-[#6C63FF]/[0.03] to-transparent">
          <div className="max-w-5xl mx-auto">
            <h2 className="text-3xl font-bold text-center mb-12">Traders Love Bahamut</h2>
            <div className="grid grid-cols-3 gap-6">
              {TESTIMONIALS.map((t, i) => (
                <div key={i} className="p-6 rounded-xl bg-white/[0.02] border border-white/[0.06]">
                  <div className="text-white/50 text-sm leading-relaxed mb-4">"{t.text}"</div>
                  <div className="flex items-center gap-3 pt-4 border-t border-white/[0.06]">
                    <div className="w-9 h-9 rounded-full bg-[#6C63FF]/20 flex items-center justify-center text-[#6C63FF] font-bold text-sm">
                      {t.name[0]}
                    </div>
                    <div>
                      <div className="text-sm font-semibold">{t.name}</div>
                      <div className="text-xs text-white/30">{t.role}</div>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* Pricing */}
        <section id="pricing" className="px-8 py-20 max-w-5xl mx-auto">
          <h2 className="text-3xl font-bold text-center mb-3">One Bad Trade Costs More Than a Year of Bahamut</h2>
          <p className="text-center text-white/40 mb-12">Start free. Upgrade when you're convinced.</p>

          <div className="grid grid-cols-3 gap-6">
            {PLANS.map(plan => (
              <div key={plan.name} className={`rounded-2xl p-6 ${plan.popular ? 'bg-gradient-to-b from-[#6C63FF]/10 to-transparent border-2 border-[#6C63FF]/50 relative' : 'bg-white/[0.02] border border-white/[0.06]'}`}>
                {plan.popular && (
                  <div className="absolute -top-3 left-1/2 -translate-x-1/2 px-4 py-1 bg-[#6C63FF] text-white text-xs font-bold rounded-full">
                    MOST POPULAR
                  </div>
                )}
                <div className="text-lg font-bold mb-1">{plan.name}</div>
                <div className="text-sm text-white/40 mb-4">{plan.desc}</div>
                <div className="flex items-baseline gap-1 mb-6">
                  <span className="text-5xl font-extrabold">${plan.price}</span>
                  <span className="text-white/30">/month</span>
                </div>
                <ul className="space-y-2.5 mb-6">
                  {plan.features.map((f, i) => (
                    <li key={i} className="text-sm text-white/50 flex items-start gap-2.5">
                      <span className="text-[#10B981] mt-0.5 text-xs">●</span> {f}
                    </li>
                  ))}
                </ul>
                <a href="/login" className={`block text-center py-3 rounded-xl font-semibold text-sm transition-colors ${plan.popular ? 'bg-[#6C63FF] hover:bg-[#5B54EE] text-white' : 'bg-white/5 hover:bg-white/10 text-white/70 border border-white/[0.06]'}`}>
                  Start 14-Day Free Trial
                </a>
              </div>
            ))}
          </div>
        </section>

        {/* Final CTA */}
        <section className="px-8 py-24 text-center">
          <h2 className="text-4xl font-bold mb-4">Ready to Trade Smarter?</h2>
          <p className="text-white/40 mb-8 max-w-xl mx-auto">Join traders who stopped guessing and started letting AI do the heavy lifting. 14 days free, no credit card.</p>
          <a href="/login" className="relative group inline-block">
            <div className="absolute -inset-1 bg-gradient-to-r from-[#6C63FF] to-[#E94560] rounded-xl blur opacity-50 group-hover:opacity-80 transition-opacity" />
            <div className="relative bg-[#6C63FF] hover:bg-[#5B54EE] text-white font-bold px-12 py-4 rounded-xl text-lg">
              Start Your Free Trial Now
            </div>
          </a>
        </section>

        {/* Footer */}
        <footer className="px-8 py-12 border-t border-white/[0.06] max-w-7xl mx-auto">
          <div className="flex items-center justify-between">
            <div>
              <img src="/logo.png" alt="Bahamut.AI" className="h-8 mb-2" />
              <p className="text-xs text-white/20">Institutional-grade AI trading intelligence</p>
            </div>
            <div className="text-right">
              <p className="text-xs text-white/20">© 2026 Bahamut.AI. All rights reserved.</p>
              <p className="text-xs text-white/20 mt-1">Trading involves risk. Past performance does not guarantee future results. Not financial advice.</p>
            </div>
          </div>
        </footer>
      </div>
    </div>
  );
}
