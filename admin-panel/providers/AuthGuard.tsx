"use client";

import { useEffect, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import { useAuthStore } from "@/store/auth";

export function AuthGuard({ children }: { children: ReactNode }) {
  const router = useRouter();
  const { isAuthed, checkAuth } = useAuthStore();

  useEffect(() => {
    checkAuth();
  }, [checkAuth]);

  useEffect(() => {
    // Only redirect when explicitly false (checked and unauthenticated).
    // null means "not yet checked" — do nothing, show spinner.
    if (isAuthed === false) {
      router.replace("/login");
    }
  }, [isAuthed, router]);

  // Still checking or explicitly unauthenticated — show spinner
  if (isAuthed !== true) {
    return (
      <div className="flex items-center justify-center h-screen bg-bah-bg">
        <div className="text-bah-muted text-sm font-mono">Authenticating...</div>
      </div>
    );
  }

  return <>{children}</>;
}
