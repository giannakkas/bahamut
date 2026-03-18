"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { login, isAuthenticated } from "@/lib/api";
import { useAuthStore } from "@/store/auth";
import { Button } from "@/components/ui";

export default function LoginPage() {
  const router = useRouter();
  const setUser = useAuthStore((s) => s.setUser);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  // Redirect if already authenticated
  useEffect(() => {
    if (isAuthenticated()) {
      router.replace("/dashboard");
    }
  }, [router]);

  const handleLogin = async () => {
    if (!username || !password) {
      setError("Username and password required");
      return;
    }

    setLoading(true);
    setError("");

    try {
      const res = await login(username, password);
      setUser(res.user);
      router.replace("/dashboard");
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Login failed. Check credentials."
      );
    } finally {
      setLoading(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") handleLogin();
  };

  return (
    <div className="flex items-center justify-center min-h-screen bg-bah-bg">
      <div className="relative overflow-hidden w-[360px] rounded-xl border border-bah-border bg-bah-surface/80 p-8 backdrop-blur-xl">
        {/* Glow */}
        <div className="absolute top-0 left-0 right-0 h-0.5 opacity-60 bg-gradient-to-r from-transparent via-bah-cyan to-transparent" />

        {/* Header */}
        <div className="text-center mb-6">
          <div className="text-[28px] font-extrabold tracking-[0.08em] bg-gradient-to-r from-bah-cyan to-bah-purple bg-clip-text text-transparent">
            BAHAMUT
          </div>
          <div className="text-[9px] text-bah-muted tracking-[0.2em] uppercase mt-1">
            Trading Intelligence Control Center
          </div>
        </div>

        {/* Form */}
        <div className="flex flex-col gap-3">
          <input
            className="w-full bg-white/[0.04] border border-bah-border rounded-lg px-3 py-2.5 text-xs text-bah-heading font-mono outline-none focus:border-bah-cyan/40 placeholder:text-bah-muted"
            placeholder="Username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            onKeyDown={handleKeyDown}
            autoFocus
          />
          <input
            className="w-full bg-white/[0.04] border border-bah-border rounded-lg px-3 py-2.5 text-xs text-bah-heading font-mono outline-none focus:border-bah-cyan/40 placeholder:text-bah-muted"
            type="password"
            placeholder="Password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            onKeyDown={handleKeyDown}
          />

          {error && (
            <div className="text-[10px] text-bah-red">{error}</div>
          )}

          <Button
            onClick={handleLogin}
            disabled={loading}
            className="w-full py-2.5 text-xs mt-1 justify-center"
          >
            {loading ? "Authenticating..." : "Sign In"}
          </Button>
        </div>
      </div>
    </div>
  );
}
