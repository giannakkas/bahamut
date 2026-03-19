'use client';

import { useEffect, useState } from 'react';
import { useAuthStore } from '@/stores/auth';

const NAV_ITEMS = [
  { href: '/', label: 'Command', icon: '⊞' },
  { href: '/top-picks', label: 'Top Picks', icon: '🎯' },
  { href: '/macro-arena', label: 'Macro Arena', icon: '◉' },
  { href: '/event-radar', label: 'Event Radar', icon: '◈' },
  { href: '/agent-council', label: 'Agent Council', icon: '◎' },
  { href: '/execution', label: 'Execution', icon: '⚡' },
  { href: '/risk-control', label: 'Risk Control', icon: '◆' },
  { href: '/journal', label: 'Trade Journal', icon: '☰' },
  { href: '/paper-trading', label: 'Self-Learning', icon: '🧠' },
  { href: '/learning-lab', label: 'Learning Lab', icon: '◐' },
  { href: '/intel-reports', label: 'Intel Reports', icon: '▤' },
];

export default function AppShell({ children }: { children: React.ReactNode }) {
  const { user, isAuthenticated, loadFromStorage, logout } = useAuthStore();
  const [mounted, setMounted] = useState(false);
  const [currentPath, setCurrentPath] = useState('/');
  const [sidebarOpen, setSidebarOpen] = useState(false);

  useEffect(() => {
    loadFromStorage();
    setMounted(true);
    setCurrentPath(window.location.pathname);
  }, []);

  if (!mounted) return <div className="min-h-screen bg-bg-primary" />;

  if (!isAuthenticated) {
    if (typeof window !== 'undefined') window.location.href = '/login';
    return null;
  }

  const initials = user?.full_name?.split(' ').map((n: string) => n[0]).join('').toUpperCase() || 'U';

  return (
    <div className="flex h-screen overflow-hidden">
      {/* Mobile overlay */}
      {sidebarOpen && (
        <div className="fixed inset-0 bg-black/50 z-30 lg:hidden" onClick={() => setSidebarOpen(false)} />
      )}

      {/* Sidebar */}
      <aside className={`fixed lg:static inset-y-0 left-0 z-40 w-[220px] lg:w-[220px] bg-bg-secondary border-r border-border-default flex flex-col shrink-0 transform transition-transform duration-200 ${sidebarOpen ? 'translate-x-0' : '-translate-x-full lg:translate-x-0'}`}>
        <div className="h-14 flex items-center justify-center px-3 border-b border-border-default">
          <img src="/logo.png" alt="Bahamut.AI" className="h-14 w-auto object-contain" />
        </div>
        <nav className="flex-1 py-2 px-2 space-y-0.5 overflow-y-auto">
          {NAV_ITEMS.map(item => (
            <a key={item.href} href={item.href} onClick={() => setSidebarOpen(false)}
              className={`flex items-center gap-2.5 px-3 py-2 rounded-md text-sm transition-colors ${
                currentPath === item.href
                  ? 'bg-bg-tertiary text-text-primary border-l-2 border-accent-violet'
                  : 'text-text-secondary hover:bg-bg-tertiary hover:text-text-primary'
              }`}>
              <span className="text-xs opacity-60 w-4 text-center">{item.icon}</span>
              {item.label}
            </a>
          ))}
        </nav>
        <div className="border-t border-border-default p-2 space-y-0.5">
          <a href="/settings" onClick={() => setSidebarOpen(false)} className="flex items-center gap-2.5 px-3 py-2 rounded-md text-sm text-text-secondary hover:bg-bg-tertiary">
            <span className="text-xs opacity-60 w-4 text-center">⚙</span> Settings
          </a>
          <button onClick={() => { logout(); window.location.href = '/landing'; }}
            className="flex items-center gap-2.5 px-3 py-2 rounded-md text-sm text-accent-crimson hover:bg-bg-tertiary w-full text-left">
            <span className="text-xs opacity-60 w-4 text-center">⏻</span> Sign Out
          </button>
        </div>
      </aside>

      {/* Main content */}
      <main className="flex-1 overflow-y-auto">
        {/* Top bar */}
        <div className="sticky top-0 z-20 bg-bg-primary/80 backdrop-blur-sm border-b border-border-default">
          <div className="flex items-center justify-between px-4 lg:px-6 py-2.5">
            <div className="flex items-center gap-3">
              {/* Hamburger — mobile only */}
              <button onClick={() => setSidebarOpen(true)} className="lg:hidden p-1.5 -ml-1 rounded-md hover:bg-bg-tertiary text-text-secondary">
                <svg width="20" height="20" viewBox="0 0 20 20" fill="none"><path d="M3 5h14M3 10h14M3 15h14" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/></svg>
              </button>
              <span className="text-sm text-text-secondary">{user?.full_name || 'Trader'}</span>
            </div>
            <div className="flex items-center gap-3">
              <span className="hidden sm:inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[10px] font-bold bg-accent-emerald/20 text-accent-emerald border border-accent-emerald/30">
                RISK_ON 78%
              </span>
              <div className="w-7 h-7 rounded-full bg-accent-violet flex items-center justify-center text-[10px] font-bold text-white">{initials}</div>
            </div>
          </div>
        </div>
        <div className="p-4 lg:p-6">
          {children}
        </div>
      </main>
    </div>
  );
}
