'use client';

import AppShell from '@/components/layout/AppShell';

export default function Page() {
  return (
    <AppShell>
      <div className="space-y-6">
        <h1 className="text-2xl font-bold">Event Radar</h1>
        <div className="bg-bg-secondary border border-border-default rounded-lg p-8 text-center">
          <div className="text-text-secondary">Module ready for implementation. Backend APIs are live.</div>
          <div className="text-text-muted text-sm mt-2">Celery workers running signal cycles every 15 minutes.</div>
        </div>
      </div>
    </AppShell>
  );
}
