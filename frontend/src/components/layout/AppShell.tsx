'use client';

import { useEffect, useState } from 'react';
import { useAuthStore } from '@/stores/auth';

const NAV_ITEMS = [
  { href: '/', label: 'Command', icon: '⊞' },
  { href: '/macro-arena', label: 'Macro Arena', icon: '◉' },
  { href: '/event-radar', label: 'Event Radar', icon: '◈' },
  { href: '/agent-council', label: 'Agent Council', icon: '◎' },
  { href: '/execution', label: 'Execution', icon: '⚡' },
  { href: '/risk-control', label: 'Risk Control', icon: '◆' },
  { href: '/journal', label: 'Trade Journal', icon: '☰' },
  { href: '/learning-lab', label: 'Learning Lab', icon: '◐' },
  { href: '/intel-reports', label: 'Intel Reports', icon: '▤' },
];

export default function AppShell({ children }: { children: React.ReactNode }) {
  const { user, isAuthenticated, loadFromStorage, logout } = useAuthStore();
  const [mounted, setMounted] = useState(false);
  const [currentPath, setCurrentPath] = useState('/');

  useEffect(() => {
    loadFromStorage();
    setMounted(true);
    if (typeof window !== 'undefined') setCurrentPath(window.location.pathname);
  }, []);

  if (!mounted) return null;

  if (!isAuthenticated) {
    if (typeof window !== 'undefined') window.location.href = '/login';
    return null;
  }

  const initials = user?.full_name?.split(' ').map((n: string) => n[0]).join('').toUpperCase() || 'U';

  return (
    <div className="flex h-screen overflow-hidden">
      <aside className="w-[260px] bg-bg-secondary border-r border-border-default flex flex-col shrink-0">
        <div className="h-14 flex items-center px-5 border-b border-border-default">
          <span className="text-xl font-bold text-accent-violet tracking-tight">BAHAMUT</span>
          <span className="text-xl font-bold text-text-muted">.AI</span>
        </div>
        <nav className="flex-1 py-3 px-3 space-y-0.5 overflow-y-auto">
          {NAV_ITEMS.map(item => (
            <a key={item.href} href={item.href}
              className={`flex items-center gap-3 px-3 py-2 rounded-md text-sm transition-colors ${
                currentPath === item.href
                  ? 'bg-bg-tertiary text-text-primary border-l-2 border-accent-violet'
                  : 'text-text-secondary hover:bg-bg-tertiary hover:text-text-primary'
              }`}>
              <span className="w-5 text-center text-base">{item.icon}</span>
              <span>{item.label}</span>
            </a>
          ))}
        </nav>
        <div className="border-t border-border-default p-3 space-y-1">
          <a href="/settings" className="flex items-center gap-3 px-3 py-2 rounded-md text-sm text-text-secondary hover:bg-bg-tertiary">
            <span className="w-5 text-center">⚙</span><span>Settings</span>
          </a>
          <button onClick={() => { logout(); window.location.href = '/login'; }}
            className="flex items-center gap-3 px-3 py-2 rounded-md text-sm text-accent-crimson hover:bg-bg-tertiary w-full text-left">
            <span className="w-5 text-center">↪</span><span>Sign Out</span>
          </button>
        </div>
      </aside>
      <main className="flex-1 flex flex-col overflow-hidden">
        <header className="h-12 bg-bg-secondary border-b border-border-default flex items-center justify-between px-6 shrink-0">
          <div className="text-sm text-text-secondary">{user?.full_name}</div>
          <div className="flex items-center gap-4">
            <span className="px-3 py-1 rounded-full text-xs font-semibold bg-accent-emerald/20 text-accent-emerald border border-accent-emerald/30">
              RISK_ON 78%
            </span>
            <div className="w-8 h-8 rounded-full bg-accent-violet/20 border border-accent-violet/40 flex items-center justify-center text-xs font-semibold text-accent-violet">
              {initials}
            </div>
          </div>
        </header>
        <div className="flex-1 overflow-y-auto p-6">{children}</div>
      </main>
    </div>
  );
}
