"use client";

import { AuthGuard } from "@/providers/AuthGuard";
import { Sidebar } from "@/components/layout/Sidebar";
import { ErrorBoundary } from "@/components/ui";

export default function AdminLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <AuthGuard>
      <div className="flex min-h-screen bg-bah-bg font-mono text-[13px] leading-relaxed">
        <Sidebar />
        <main className="flex-1 p-5 overflow-y-auto max-h-screen">
          <ErrorBoundary>{children}</ErrorBoundary>
        </main>
      </div>
    </AuthGuard>
  );
}
