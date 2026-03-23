'use client';

import { useState } from 'react';
import { useAuthStore } from '@/stores/auth';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'https://bahamut-production.up.railway.app';

export default function LoginPage() {
  const [isRegister, setIsRegister] = useState(false);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [fullName, setFullName] = useState('');
  const [workspace, setWorkspace] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [registered, setRegistered] = useState(false);
  const { login } = useAuthStore();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      if (isRegister) {
        const res = await fetch(`${API_URL}/api/v1/auth/waitlist`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ email, full_name: fullName, workspace_name: workspace }),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Something went wrong');
        setRegistered(true);
      } else {
        await login(email, password);
        window.location.href = '/';
      }
    } catch (err: any) {
      setError(err.message || 'Authentication failed');
    } finally {
      setLoading(false);
    }
  };

  // ═══ SPOTS FULL CONFIRMATION ═══
  if (registered) {
    return (
      <div className="min-h-screen bg-bg-primary flex items-center justify-center px-4">
        <div className="w-full max-w-lg text-center">
          <img src="/logo.png" alt="Bahamut.AI" className="h-20 mx-auto mb-6 object-contain" />

          <div className="bg-bg-secondary border border-border-default rounded-xl p-8">
            <div className="w-16 h-16 bg-[#c9a84c]/10 rounded-full flex items-center justify-center mx-auto mb-5">
              <svg className="w-8 h-8 text-[#c9a84c]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
            </div>

            <h1 className="text-xl font-bold text-text-primary mb-2">
              All Spots Are Currently Taken
            </h1>

            <p className="text-text-secondary text-sm leading-relaxed mb-6">
              Due to overwhelming demand, we&apos;ve reached full capacity for new accounts.
              We&apos;re expanding access soon and your name is
              <span className="text-[#c9a84c] font-semibold"> at the top of the list</span>.
            </p>

            <div className="bg-bg-surface border border-border-default rounded-lg p-4 mb-6 text-left">
              <div className="flex items-start gap-3">
                <div className="w-2 h-2 rounded-full bg-[#c9a84c] mt-2 shrink-0" />
                <div>
                  <p className="text-text-primary text-sm font-medium">Priority Access Reserved</p>
                  <p className="text-text-secondary text-xs mt-1">
                    As soon as new spots become available, early registrants get first access.
                    No action needed on your end — we&apos;ll come to you.
                  </p>
                </div>
              </div>
            </div>

            <div className="space-y-2 text-sm text-text-secondary mb-6">
              <p>📧 We&apos;ll notify <span className="text-text-primary font-medium">{email}</span> the moment a spot opens.</p>
              <p>🔒 No credit card required. No commitment.</p>
            </div>

            <div className="border-t border-border-default pt-4">
              <p className="text-xs text-text-secondary">
                Bahamut.AI — Trade · Analyze · Conquer
              </p>
            </div>
          </div>

          <button onClick={() => { setRegistered(false); setIsRegister(false); }}
            className="mt-4 text-sm text-text-secondary hover:text-text-primary transition-colors">
            ← Back to sign in
          </button>
        </div>
      </div>
    );
  }

  // ═══ LOGIN / JOIN US FORM ═══
  return (
    <div className="min-h-screen bg-bg-primary flex items-center justify-center">
      <div className="w-full max-w-md">
        <div className="text-center mb-8">
          <div className="inline-block mb-4">
            <img src="/logo.png" alt="Bahamut.AI" className="h-32 w-auto object-contain" />
          </div>
          <p className="text-text-secondary text-sm">Institutional-Grade Trading Intelligence</p>
        </div>

        <div className="bg-bg-secondary border border-border-default rounded-lg p-6">
          <h2 className="text-lg font-semibold text-text-primary mb-4">
            {isRegister ? 'Join Us' : 'Sign In'}
          </h2>

          {error && (
            <div className="mb-4 p-3 bg-accent-crimson/10 border border-accent-crimson/30 rounded-md text-accent-crimson text-sm">
              {error}
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-4">
            {isRegister && (
              <>
                <div>
                  <label className="block text-sm text-text-secondary mb-1">Full Name</label>
                  <input type="text" value={fullName} onChange={e => setFullName(e.target.value)}
                    className="w-full bg-bg-surface border border-border-default rounded-md px-3 py-2 text-text-primary focus:border-border-focus focus:outline-none"
                    placeholder="Your full name" required />
                </div>
                <div>
                  <label className="block text-sm text-text-secondary mb-1">Trading Firm / Workspace</label>
                  <input type="text" value={workspace} onChange={e => setWorkspace(e.target.value)}
                    className="w-full bg-bg-surface border border-border-default rounded-md px-3 py-2 text-text-primary focus:border-border-focus focus:outline-none"
                    placeholder="Your firm or workspace name" />
                </div>
              </>
            )}
            <div>
              <label className="block text-sm text-text-secondary mb-1">Email</label>
              <input type="email" value={email} onChange={e => setEmail(e.target.value)}
                className="w-full bg-bg-surface border border-border-default rounded-md px-3 py-2 text-text-primary focus:border-border-focus focus:outline-none"
                placeholder="you@example.com" required autoFocus />
            </div>
            {!isRegister && (
              <div>
                <label className="block text-sm text-text-secondary mb-1">Password</label>
                <input type="password" value={password} onChange={e => setPassword(e.target.value)}
                  className="w-full bg-bg-surface border border-border-default rounded-md px-3 py-2 text-text-primary focus:border-border-focus focus:outline-none"
                  placeholder="Password" required minLength={6} />
              </div>
            )}
            <button type="submit" disabled={loading}
              className="w-full bg-accent-violet hover:bg-accent-violet/90 text-white font-semibold py-2.5 rounded-md transition-colors disabled:opacity-50">
              {loading ? 'Processing...' : isRegister ? 'Join Us' : 'Sign In'}
            </button>
          </form>

          <div className="mt-4 text-center">
            <button onClick={() => { setIsRegister(!isRegister); setError(''); }}
              className="text-sm text-accent-violet hover:text-accent-violet/80">
              {isRegister ? 'Already have an account? Sign in' : "Don't have an account? Join us"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
