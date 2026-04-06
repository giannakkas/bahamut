"use client";

import { AuthGuard } from "@/providers/AuthGuard";
import { AdminSocketProvider } from "@/providers/AdminSocketProvider";
import { Sidebar } from "@/components/layout/Sidebar";
import { ErrorBoundary } from "@/components/ui";

export default function AdminLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <AuthGuard>
      <AdminSocketProvider>
        <div className="flex min-h-screen bg-bah-bg font-mono text-[13px] leading-relaxed overflow-x-hidden max-w-[100vw]">
          <Sidebar />
          <main className="flex-1 p-3 sm:p-5 pt-12 lg:pt-5 overflow-y-auto overflow-x-hidden max-h-screen w-full min-w-0 max-w-[100vw] lg:max-w-none">
            <ErrorBoundary>{children}</ErrorBoundary>
          </main>
        </div>
      </AdminSocketProvider>
    </AuthGuard>
  );
}
