'use client';

import { useState } from 'react';

const PLANS = [
  {
    name: 'Starter', price: 49, period: '/mo',
    features: ['4 FX + Gold pairs', '6 AI agents analyzing 24/5', '4H timeframe signals',
               'Trade approval cards', 'Risk control dashboard', 'Trade journal'],
    cta: 'Start Free Trial', highlighted: false,
  },
  {
    name: 'Pro', price: 149, period: '/mo',
    features: ['10 assets (FX, Crypto, Stocks)', 'All timeframes (1H, 4H, 1D)',
               'Breaking news detector', 'AI daily market brief', 'Real-time Finnhub news feed',
               'Emergency signal cycles', 'Priority support'],
    cta: 'Start Free Trial', highlighted: true,
  },
  {
    name: 'Institutional', price: 499, period: '/mo',
    features: ['Everything in Pro', 'Unlimited assets', 'Custom agent weights',
               'REST API access', 'Multi-user workspace', 'Custom integrations',
               'Dedicated account manager'],
    cta: 'Contact Sales', highlighted: false,
  },
];

const AGENTS = [
  { name: 'Technical', desc: 'RSI, MACD, EMA alignment, ADX trend strength', color: '#8B5CF6' },
  { name: 'Macro', desc: 'Yield curves, central bank policy, regime detection', color: '#6C63FF' },
  { name: 'Sentiment', desc: 'Real-time news analysis via AI (Gemini)', color: '#F43F5E' },
  { name: 'Volatility', desc: 'Bollinger bands, realized vol, ATR regime', color: '#F59E0B' },
  { name: 'Liquidity', desc: 'Volume analysis, price structure, sweep detection', color: '#10B981' },
  { name: 'Risk', desc: 'Drawdown limits, correlation, circuit breakers + VETO power', color: '#EF4444' },
];

export default function LandingPage() {
  const [email, setEmail] = useState('');

  return (
    <div className="min-h-screen bg-[#0A0A14] text-[#E8E8F0]">
      {/* Nav */}
      <nav className="flex items-center justify-between px-8 py-4 border-b border-[#2A2A4A]">
        <img src="/logo.png" alt="Bahamut.AI" className="h-10" />
        <div className="flex items-center gap-6">
          <a href="#features" className="text-sm text-[#8888AA] hover:text-white">Features</a>
          <a href="#agents" className="text-sm text-[#8888AA] hover:text-white">Agents</a>
          <a href="#pricing" className="text-sm text-[#8888AA] hover:text-white">Pricing</a>
          <a href="/login" className="text-sm text-[#8888AA] hover:text-white">Sign In</a>
          <a href="/login" className="bg-[#6C63FF] hover:bg-[#6C63FF]/90 text-white font-semibold px-5 py-2 rounded-md text-sm">
            Start Free Trial
          </a>
        </div>
      </nav>

      {/* Hero */}
      <section className="px-8 py-24 text-center max-w-4xl mx-auto">
        <div className="inline-block px-4 py-1.5 rounded-full bg-[#6C63FF]/10 border border-[#6C63FF]/30 text-[#6C63FF] text-sm font-semibold mb-6">
          6 AI Agents · Real-Time Data · Multi-Asset
        </div>
        <h1 className="text-5xl font-bold leading-tight mb-6">
          Institutional-Grade AI<br />
          <span className="text-[#6C63FF]">Trading Intelligence</span>
        </h1>
        <p className="text-xl text-[#8888AA] max-w-2xl mx-auto mb-8">
          6 specialized AI agents analyze markets, debate each other, and reach weighted consensus — 
          powered by real-time data from Reuters, CNBC, and live price feeds. Every 15 minutes. For every asset you track.
        </p>
        <div className="flex items-center justify-center gap-4">
          <a href="/login" className="bg-[#6C63FF] hover:bg-[#6C63FF]/90 text-white font-bold px-8 py-3 rounded-md text-lg">
            Start 14-Day Free Trial
          </a>
          <a href="#agents" className="border border-[#2A2A4A] hover:border-[#6C63FF] text-[#8888AA] hover:text-white font-semibold px-8 py-3 rounded-md text-lg">
            See How It Works
          </a>
        </div>
        <p className="text-xs text-[#555570] mt-4">No credit card required · Cancel anytime</p>
      </section>

      {/* How it works */}
      <section id="features" className="px-8 py-20 max-w-6xl mx-auto">
        <h2 className="text-3xl font-bold text-center mb-4">How Bahamut.AI Works</h2>
        <p className="text-center text-[#8888AA] mb-12 max-w-2xl mx-auto">Every 15 minutes, a complete intelligence cycle runs for each asset you monitor</p>

        <div className="grid grid-cols-5 gap-4">
          {[
            { step: '1', title: 'Data Ingestion', desc: 'Real-time prices from Twelve Data. Live news from Finnhub. Economic calendar from Forex Factory.' },
            { step: '2', title: 'Agent Analysis', desc: '6 specialized agents independently analyze technical, macro, sentiment, volatility, liquidity, and risk.' },
            { step: '3', title: 'Agent Debate', desc: 'Agents challenge each other. Macro vs Technical. Risk vetos unsafe signals. Confidence adjusts.' },
            { step: '4', title: 'Consensus Vote', desc: 'Weighted voting based on trust scores. Agents with better track records get more influence.' },
            { step: '5', title: 'Signal / Alert', desc: 'STRONG_SIGNAL, SIGNAL, or NO_TRADE. Trade card with entry, SL, TP. You approve or reject.' },
          ].map(item => (
            <div key={item.step} className="bg-[#0F0F1E] border border-[#2A2A4A] rounded-lg p-5 text-center">
              <div className="w-10 h-10 rounded-full bg-[#6C63FF]/20 text-[#6C63FF] font-bold flex items-center justify-center mx-auto mb-3 text-lg">{item.step}</div>
              <div className="font-semibold text-sm mb-2">{item.title}</div>
              <div className="text-xs text-[#8888AA] leading-relaxed">{item.desc}</div>
            </div>
          ))}
        </div>
      </section>

      {/* Agents */}
      <section id="agents" className="px-8 py-20 bg-[#0F0F1E]">
        <div className="max-w-6xl mx-auto">
          <h2 className="text-3xl font-bold text-center mb-4">6 AI Agents. One Consensus.</h2>
          <p className="text-center text-[#8888AA] mb-12">Each agent is a specialist. They argue, challenge, and vote. The best track record wins.</p>

          <div className="grid grid-cols-3 gap-4">
            {AGENTS.map(agent => (
              <div key={agent.name} className="bg-[#161628] border border-[#2A2A4A] rounded-lg p-5">
                <div className="w-10 h-10 rounded-full flex items-center justify-center text-white font-bold mb-3"
                  style={{ backgroundColor: agent.color }}>
                  {agent.name[0]}
                </div>
                <div className="font-semibold mb-1">{agent.name} Agent</div>
                <div className="text-sm text-[#8888AA]">{agent.desc}</div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Data Sources */}
      <section className="px-8 py-20 max-w-6xl mx-auto">
        <h2 className="text-3xl font-bold text-center mb-12">Real Data. No Guessing.</h2>
        <div className="grid grid-cols-4 gap-6 text-center">
          {[
            { name: 'Live Prices', desc: '200 candles per asset, 10 assets, every 15 minutes', stat: 'Twelve Data' },
            { name: 'Real-Time News', desc: 'Reuters, CNBC, Bloomberg — zero delay', stat: 'Finnhub' },
            { name: 'Economic Calendar', desc: 'CPI, FOMC, GDP, NFP with forecasts', stat: 'Forex Factory' },
            { name: 'AI Sentiment', desc: 'Gemini reads headlines, scores impact', stat: 'Google Gemini' },
          ].map(item => (
            <div key={item.name} className="bg-[#0F0F1E] border border-[#2A2A4A] rounded-lg p-6">
              <div className="text-sm text-[#6C63FF] font-semibold mb-2">{item.stat}</div>
              <div className="font-semibold mb-1">{item.name}</div>
              <div className="text-xs text-[#8888AA]">{item.desc}</div>
            </div>
          ))}
        </div>
      </section>

      {/* Pricing */}
      <section id="pricing" className="px-8 py-20 bg-[#0F0F1E]">
        <div className="max-w-5xl mx-auto">
          <h2 className="text-3xl font-bold text-center mb-4">Simple Pricing</h2>
          <p className="text-center text-[#8888AA] mb-12">14-day free trial on all plans. No credit card required.</p>

          <div className="grid grid-cols-3 gap-6">
            {PLANS.map(plan => (
              <div key={plan.name} className={`rounded-lg p-6 ${plan.highlighted ? 'bg-[#6C63FF]/10 border-2 border-[#6C63FF]' : 'bg-[#161628] border border-[#2A2A4A]'}`}>
                {plan.highlighted && <div className="text-[#6C63FF] text-xs font-bold mb-2">MOST POPULAR</div>}
                <div className="text-xl font-bold mb-1">{plan.name}</div>
                <div className="flex items-baseline gap-1 mb-4">
                  <span className="text-4xl font-bold">${plan.price}</span>
                  <span className="text-[#8888AA]">{plan.period}</span>
                </div>
                <ul className="space-y-2 mb-6">
                  {plan.features.map((f, i) => (
                    <li key={i} className="text-sm text-[#8888AA] flex items-start gap-2">
                      <span className="text-[#10B981] mt-0.5">✓</span> {f}
                    </li>
                  ))}
                </ul>
                <a href="/login" className={`block text-center py-2.5 rounded-md font-semibold text-sm ${plan.highlighted ? 'bg-[#6C63FF] text-white' : 'bg-[#1C1C35] text-[#8888AA] border border-[#2A2A4A] hover:text-white'}`}>
                  {plan.cta}
                </a>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Footer */}
      <footer className="px-8 py-12 border-t border-[#2A2A4A] text-center">
        <img src="/logo.png" alt="Bahamut.AI" className="h-8 mx-auto mb-4" />
        <p className="text-sm text-[#555570]">Institutional-grade AI trading intelligence. Built for serious traders.</p>
        <p className="text-xs text-[#555570] mt-2">© 2026 Bahamut.AI. Not financial advice. Trading involves risk.</p>
      </footer>
    </div>
  );
}
