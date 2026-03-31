'use client';
import { useState, useEffect, useCallback } from 'react';
import AppShell from '@/components/layout/AppShell';
import { fetchWallet, depositFunds, setAllocation, WalletTransaction } from '@/lib/walletApi';

const fm = (n: number) => `$${Math.abs(n).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const fmS = (n: number) => `${n >= 0 ? '+' : '-'}${fm(n)}`;

export default function WalletPage() {
  const [balance, setBalance] = useState(0);
  const [allocation, setAlloc] = useState(0);
  const [history, setHistory] = useState<WalletTransaction[]>([]);
  const [fundAmount, setFundAmount] = useState('');
  const [allocInput, setAllocInput] = useState('');
  const [mode, setMode] = useState<'demo' | 'live'>('demo');
  const [toast, setToast] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const loadWallet = useCallback(async () => {
    const w = await fetchWallet();
    if (w) {
      setBalance(w.balance);
      setAlloc(w.allocation);
      setHistory(w.transactions);
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    loadWallet();
    if (typeof window === 'undefined') return;
    const m = localStorage.getItem('bahamut_trading_mode');
    if (m === 'live' || m === 'demo') setMode(m);
    const iv = setInterval(() => {
      const m2 = localStorage.getItem('bahamut_trading_mode');
      if (m2 === 'live' || m2 === 'demo') setMode(m2);
    }, 1000);
    return () => clearInterval(iv);
  }, [loadWallet]);

  const showToast = (msg: string) => { setToast(msg); setTimeout(() => setToast(null), 3000); };

  const addFunds = async (amount: number) => {
    const result = await depositFunds(amount, mode);
    if (result) {
      setBalance(result.balance);
      setAlloc(result.allocation);
      showToast(`${fm(result.deposited)} deposited! Will be invested in the next trade.`);
      loadWallet(); // Refresh history
    }
    setFundAmount('');
  };

  const updateAllocation = async () => {
    const val = parseFloat(allocInput) || 0;
    const result = await setAllocation(val, mode);
    if (result) {
      setBalance(result.balance);
      setAlloc(result.allocation);
      showToast(`Allocation set to ${fm(result.allocation)}. Will be invested in the next trade.`);
      loadWallet();
    }
    setAllocInput('');
  };

  const timeAgo = (iso: string) => {
    if (!iso) return '';
    const d = Date.now() - new Date(iso).getTime();
    const m = Math.floor(d / 60000);
    if (m < 1) return 'just now';
    if (m < 60) return `${m}m ago`;
    const h = Math.floor(m / 60);
    if (h < 24) return `${h}h ago`;
    return `${Math.floor(h / 24)}d ago`;
  };

  if (loading) return <AppShell><div className="flex items-center justify-center min-h-[60vh]"><div className="w-8 h-8 border-2 border-accent-violet/30 border-t-accent-violet rounded-full animate-spin" /></div></AppShell>;

  return (
    <AppShell>
      <div className="max-w-[900px] mx-auto space-y-4 px-2 sm:px-0">
        {toast && (
          <div className="fixed top-4 left-1/2 -translate-x-1/2 z-50 animate-slide-in w-[90vw] sm:w-auto">
            <div className="bg-accent-violet/90 text-white px-4 py-2.5 rounded-xl shadow-lg text-xs sm:text-sm font-semibold flex items-center gap-2">
              💰 {toast} <button onClick={() => setToast(null)} className="ml-2 text-white/60 hover:text-white">✕</button>
            </div>
          </div>
        )}

        <h1 className="text-lg font-bold text-text-primary">Wallet</h1>

        {/* Balance Cards */}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          <div className="bg-bg-secondary/60 border border-border-default rounded-xl p-4 text-center">
            <div className="text-[10px] text-text-muted uppercase tracking-wider mb-1">Total Balance</div>
            <div className="text-2xl font-bold text-text-primary">{fm(balance)}</div>
            <div className="text-[9px] text-text-muted mt-1">{mode === 'demo' ? 'Virtual funds' : 'Real funds'}</div>
          </div>
          <div className="bg-bg-secondary/60 border border-border-default rounded-xl p-4 text-center">
            <div className="text-[10px] text-text-muted uppercase tracking-wider mb-1">Trading Allocation</div>
            <div className="text-2xl font-bold text-accent-violet">{fm(allocation)}</div>
            <div className="text-[9px] text-text-muted mt-1">Actively invested</div>
          </div>
          <div className="bg-bg-secondary/60 border border-border-default rounded-xl p-4 text-center">
            <div className="text-[10px] text-text-muted uppercase tracking-wider mb-1">Available</div>
            <div className="text-2xl font-bold text-accent-cyan">{fm(Math.max(0, balance - allocation))}</div>
            <div className="text-[9px] text-text-muted mt-1">Not allocated</div>
          </div>
        </div>

        {/* Add Funds */}
        <div className="bg-bg-secondary/60 border border-border-default rounded-xl p-4">
          <h2 className="text-sm font-bold text-text-primary mb-3">{mode === 'demo' ? '+ Add Virtual Funds' : '💳 Add Real Funds'}</h2>
          {mode === 'demo' ? (
            <div className="flex flex-wrap items-center gap-2">
              {[5000, 10000, 25000, 50000].map(amt => (
                <button key={amt} onClick={() => addFunds(amt)} disabled={balance >= 100000}
                  className="px-3 py-1.5 text-[11px] font-bold rounded-lg border border-border-default bg-bg-tertiary text-text-secondary hover:bg-accent-violet/10 hover:text-accent-violet hover:border-accent-violet/30 transition-all disabled:opacity-30">
                  +{fm(amt)}
                </button>
              ))}
              <input type="number" placeholder="Custom" value={fundAmount} onChange={e => setFundAmount(e.target.value)}
                className="w-24 px-2 py-1.5 text-[11px] rounded-lg border border-border-default bg-bg-tertiary text-text-primary placeholder-text-muted outline-none focus:border-accent-violet" />
              {fundAmount && (
                <button onClick={() => addFunds(parseFloat(fundAmount) || 0)}
                  className="px-3 py-1.5 text-[11px] font-bold rounded-lg bg-accent-violet text-white hover:bg-accent-violet/80">Add</button>
              )}
              <span className="text-[10px] text-text-muted ml-auto">{fm(balance)} / {fm(100000)}</span>
            </div>
          ) : (
            <div className="flex flex-wrap items-center gap-2">
              {[100, 500, 1000, 5000].map(amt => (
                <button key={amt} disabled className="px-3 py-1.5 text-[11px] font-bold rounded-lg border border-border-default bg-bg-tertiary text-text-secondary opacity-50 cursor-not-allowed">
                  ${amt.toLocaleString()}
                </button>
              ))}
              <span className="text-[10px] text-accent-amber">Coming soon — Stripe integration</span>
            </div>
          )}
        </div>

        {/* Change Allocation */}
        <div className="bg-bg-secondary/60 border border-border-default rounded-xl p-4">
          <h2 className="text-sm font-bold text-text-primary mb-3">Change Trading Allocation</h2>
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-[11px] text-text-muted">Current: {fm(allocation)}</span>
            <input type="number" placeholder="New allocation" value={allocInput} onChange={e => setAllocInput(e.target.value)}
              className="w-32 px-2 py-1.5 text-[11px] rounded-lg border border-border-default bg-bg-tertiary text-text-primary placeholder-text-muted outline-none focus:border-accent-violet" />
            {allocInput && (
              <button onClick={updateAllocation}
                className="px-3 py-1.5 text-[11px] font-bold rounded-lg bg-accent-violet text-white hover:bg-accent-violet/80">Update</button>
            )}
            <span className="text-[9px] text-text-muted">Max: {fm(balance)}</span>
          </div>
        </div>

        {/* Transaction History */}
        <div className="bg-bg-secondary/60 border border-border-default rounded-xl overflow-hidden">
          <div className="px-4 py-3 border-b border-border-default">
            <span className="text-sm font-bold text-text-primary">Transaction History</span>
          </div>
          <div className="p-4">
            {history.length === 0 ? (
              <p className="text-xs text-text-muted text-center py-6">No transactions yet. Add funds to get started.</p>
            ) : (
              <div className="space-y-2">
                {history.map((e, i) => (
                  <div key={i} className="flex items-center gap-3 py-2 border-b border-border-default/30 last:border-0">
                    <span className={`w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold shrink-0 ${
                      e.type === 'deposit' ? 'bg-accent-emerald/15 text-accent-emerald' : 'bg-accent-violet/15 text-accent-violet'
                    }`}>
                      {e.type === 'deposit' ? '↓' : '↕'}
                    </span>
                    <div className="flex-1 min-w-0">
                      <div className="text-xs text-text-primary font-semibold">
                        {e.type === 'deposit' ? 'Deposit' : 'Allocation Change'}
                      </div>
                      <div className="text-[10px] text-text-muted">
                        {e.type === 'deposit' ? `Added ${fm(e.amount)}` : `Set to ${fm(e.amount)}`} · Balance: {fm(e.balance_after)}
                      </div>
                    </div>
                    <div className="text-right shrink-0">
                      <div className={`text-xs font-bold ${e.type === 'deposit' ? 'text-accent-emerald' : 'text-accent-violet'}`}>
                        {e.type === 'deposit' ? fmS(e.amount) : fm(e.amount)}
                      </div>
                      <div className="text-[9px] text-text-muted">{timeAgo(e.timestamp)}</div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </AppShell>
  );
}
