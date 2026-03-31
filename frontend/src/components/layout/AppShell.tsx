'use client';

import { useEffect, useState } from 'react';
import { useAuthStore } from '@/stores/auth';

const NAV_ITEMS = [
  { href: '/', label: 'Dashboard', icon: '◉', minRole: 'user' },
  { href: '/wallet', label: 'Wallet', icon: '💰', minRole: 'user' },
  { href: '/performance', label: 'Performance', icon: '📈', minRole: 'user' },
  { href: '/activity', label: 'Activity', icon: '📋', minRole: 'user' },
];

const ROLE_LEVELS: Record<string, number> = {
  user: 0, viewer: 0, trader: 1, admin: 2, super_admin: 3,
};

export default function AppShell({ children }: { children: React.ReactNode }) {
  const { user, isAuthenticated, loadFromStorage, logout } = useAuthStore();
  const [mounted, setMounted] = useState(false);
  const [currentPath, setCurrentPath] = useState('/');
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [tradingMode, setTradingMode] = useState<'demo' | 'live'>('demo');

  useEffect(() => {
    if (typeof window !== 'undefined') {
      const params = new URLSearchParams(window.location.search);
      const ssoToken = params.get('token');
      if (ssoToken) {
        localStorage.setItem('bahamut_token', ssoToken);
        localStorage.setItem('bahamut_user', JSON.stringify({ email: 'admin', role: 'super_admin', full_name: 'Admin' }));
        window.history.replaceState({}, '', window.location.pathname);
      }
      const saved = localStorage.getItem('bahamut_trading_mode');
      if (saved === 'live' || saved === 'demo') setTradingMode(saved);
    }
    loadFromStorage();
    setMounted(true);
    setCurrentPath(window.location.pathname);
  }, []);

  const switchMode = (m: 'demo' | 'live') => {
    setTradingMode(m);
    if (typeof window !== 'undefined') localStorage.setItem('bahamut_trading_mode', m);
  };

  if (!mounted) return <div className="min-h-screen bg-bg-primary" />;
  if (!isAuthenticated) { if (typeof window !== 'undefined') window.location.href = '/landing'; return null; }

  const initials = user?.full_name?.split(' ').map((n: string) => n[0]).join('').toUpperCase() || 'U';
  const userRole = user?.role || 'user';
  const userLevel = ROLE_LEVELS[userRole] ?? 0;
  const visibleNav = NAV_ITEMS.filter(item => userLevel >= (ROLE_LEVELS[item.minRole] ?? 0));

  return (
    <div className="flex h-screen overflow-hidden">
      {sidebarOpen && <div className="fixed inset-0 bg-black/50 z-30 lg:hidden" onClick={() => setSidebarOpen(false)} />}

      <aside className={`fixed lg:static inset-y-0 left-0 z-40 w-[200px] bg-bg-secondary border-r border-border-default flex flex-col shrink-0 transform transition-transform duration-200 ${sidebarOpen ? 'translate-x-0' : '-translate-x-full lg:translate-x-0'}`}>
        <div className="h-14 flex items-center justify-center px-3 border-b border-border-default">
          <img src="/logo.png" alt="Bahamut.AI" className="h-14 w-auto object-contain" />
        </div>

        {/* Demo / Live Toggle */}
        <div className="px-3 py-3 border-b border-border-default">
          <div className="text-[9px] text-text-muted uppercase tracking-widest font-semibold mb-2">Trading Mode</div>
          <div className="flex bg-bg-primary rounded-lg p-[3px] border border-border-default">
            <button onClick={() => switchMode('demo')} className={`flex-1 py-1.5 rounded-md text-[11px] font-bold transition-all ${tradingMode === 'demo' ? 'bg-accent-violet/20 text-accent-violet' : 'text-text-muted'}`}>Demo</button>
            <button onClick={() => switchMode('live')} className={`flex-1 py-1.5 rounded-md text-[11px] font-bold transition-all ${tradingMode === 'live' ? 'bg-accent-emerald/20 text-accent-emerald' : 'text-text-muted'}`}>Live</button>
          </div>
          <div className="text-[8px] text-text-muted text-center mt-1.5">{tradingMode === 'demo' ? 'Virtual money — practice safely' : 'Real money — trade live markets'}</div>
        </div>

        <nav className="flex-1 py-2 px-2 space-y-0.5 overflow-y-auto">
          {visibleNav.map(item => (
            <a key={item.href} href={item.href} onClick={() => setSidebarOpen(false)}
              className={`flex items-center gap-2.5 px-3 py-2 rounded-md text-sm transition-colors ${currentPath === item.href ? 'bg-bg-tertiary text-accent-cyan border-l-2 border-accent-cyan font-semibold' : 'text-text-secondary hover:bg-bg-tertiary hover:text-text-primary'}`}>
              <span className="text-xs opacity-60 w-4 text-center">{item.icon}</span>{item.label}
            </a>
          ))}
        </nav>

        <div className="border-t border-border-default p-2 space-y-0.5">
          <div className="flex items-center gap-2 px-3 py-1.5">
            <span className={`w-1.5 h-1.5 rounded-full animate-pulse ${tradingMode === 'demo' ? 'bg-accent-violet' : 'bg-accent-emerald'}`} />
            <span className={`text-[10px] font-semibold ${tradingMode === 'demo' ? 'text-accent-violet' : 'text-accent-emerald'}`}>{tradingMode === 'demo' ? 'Demo Mode' : 'Live Trading'}</span>
          </div>
          {(userRole === 'super_admin' || userRole === 'admin') && (
            <a href="#" onClick={(e) => { e.preventDefault(); const token = localStorage.getItem('bahamut_token') || ''; window.open(`https://admin.bahamut.ai/login?token=${encodeURIComponent(token)}`, '_blank'); }} className="flex items-center gap-2.5 px-3 py-2 rounded-md text-sm text-accent-violet hover:bg-bg-tertiary font-semibold">
              <span className="text-xs opacity-80 w-4 text-center">⚡</span> Admin Panel
            </a>
          )}
          <a href="/settings" onClick={() => setSidebarOpen(false)} className="flex items-center gap-2.5 px-3 py-2 rounded-md text-sm text-text-secondary hover:bg-bg-tertiary"><span className="text-xs opacity-60 w-4 text-center">⚙</span> Settings</a>
          <button onClick={() => { logout(); window.location.href = '/landing'; }} className="flex items-center gap-2.5 px-3 py-2 rounded-md text-sm text-accent-crimson hover:bg-bg-tertiary w-full text-left"><span className="text-xs opacity-60 w-4 text-center">⏻</span> Sign Out</button>
        </div>
      </aside>

      <main className="flex-1 overflow-y-auto overflow-x-hidden min-w-0">
        <div className="sticky top-0 z-20 bg-bg-primary/80 backdrop-blur-sm border-b border-border-default">
          <div className="flex items-center justify-between px-3 sm:px-4 lg:px-6 py-2.5">
            <div className="flex items-center gap-3">
              <button onClick={() => setSidebarOpen(true)} className="lg:hidden p-1.5 -ml-1 rounded-md hover:bg-bg-tertiary text-text-secondary">
                <svg width="20" height="20" viewBox="0 0 20 20" fill="none"><path d="M3 5h14M3 10h14M3 15h14" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/></svg>
              </button>
              <span className="text-sm text-text-secondary">{user?.full_name || 'Trader'}</span>
            </div>
            <div className="flex items-center gap-3">
              <span className="hidden sm:inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[10px] font-bold bg-bg-tertiary text-text-secondary border border-border-default">
                {user?.role === 'super_admin' ? '⚡ Super Admin' : user?.role === 'admin' ? '🔧 Admin' : '📊 Trader'}
              </span>
              <div className="w-7 h-7 rounded-full bg-accent-violet flex items-center justify-center text-[10px] font-bold text-white">{initials}</div>
            </div>
          </div>
        </div>
        <div className="p-3 sm:p-4 lg:p-6">{children}</div>
      </main>
    </div>
  );
}
