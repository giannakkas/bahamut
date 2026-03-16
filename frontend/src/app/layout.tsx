import '@/styles/globals.css';
import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Bahamut.AI - Trading Intelligence',
  description: 'Institutional-Grade AI Trading Intelligence Platform',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark">
      <body className="bg-bg-primary text-text-primary min-h-screen">
        <div className="flex h-screen overflow-hidden">
          {/* Sidebar */}
          <aside className="w-[260px] bg-bg-secondary border-r border-border-default flex flex-col shrink-0">
            {/* Logo */}
            <div className="h-14 flex items-center px-5 border-b border-border-default">
              <span className="text-xl font-bold text-accent-violet tracking-tight">BAHAMUT</span>
              <span className="text-xl font-bold text-text-muted">.AI</span>
            </div>

            {/* Nav */}
            <nav className="flex-1 py-3 px-3 space-y-0.5 overflow-y-auto">
              <NavItem href="/" label="Command" icon="⊞" active />
              <NavItem href="/macro-arena" label="Macro Arena" icon="◉" />
              <NavItem href="/event-radar" label="Event Radar" icon="◈" />
              <NavItem href="/agent-council" label="Agent Council" icon="◎" />
              <NavItem href="/execution" label="Execution" icon="⚡" />
              <NavItem href="/risk-control" label="Risk Control" icon="◆" />
              <NavItem href="/journal" label="Trade Journal" icon="☰" />
              <NavItem href="/learning-lab" label="Learning Lab" icon="◐" />
              <NavItem href="/intel-reports" label="Intel Reports" icon="▤" />
            </nav>

            {/* Settings pinned bottom */}
            <div className="border-t border-border-default p-3">
              <NavItem href="/settings" label="Settings" icon="⚙" />
            </div>
          </aside>

          {/* Main content */}
          <main className="flex-1 flex flex-col overflow-hidden">
            {/* Top bar */}
            <header className="h-12 bg-bg-secondary border-b border-border-default flex items-center justify-between px-6 shrink-0">
              <div className="text-sm text-text-secondary">Bahamut Command</div>
              <div className="flex items-center gap-4">
                <span className="px-3 py-1 rounded-full text-xs font-semibold bg-accent-amber/20 text-accent-amber border border-accent-amber/30">
                  RISK_ON 78%
                </span>
                <div className="w-8 h-8 rounded-full bg-bg-tertiary border border-border-default flex items-center justify-center text-xs text-text-secondary">
                  CG
                </div>
              </div>
            </header>

            {/* Page content */}
            <div className="flex-1 overflow-y-auto p-6">
              {children}
            </div>
          </main>
        </div>
      </body>
    </html>
  );
}

function NavItem({ href, label, icon, active = false }: {
  href: string; label: string; icon: string; active?: boolean;
}) {
  return (
    <a
      href={href}
      className={`flex items-center gap-3 px-3 py-2 rounded-md text-sm transition-colors ${
        active
          ? 'bg-bg-tertiary text-text-primary border-l-2 border-accent-violet'
          : 'text-text-secondary hover:bg-bg-tertiary hover:text-text-primary'
      }`}
    >
      <span className="w-5 text-center text-base">{icon}</span>
      <span>{label}</span>
    </a>
  );
}
