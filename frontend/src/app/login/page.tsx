'use client';

import { useState } from 'react';
import { useAuthStore } from '@/stores/auth';

export default function LoginPage() {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const { login } = useAuthStore();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      await login(email, password);
      window.location.href = '/';
    } catch (err: any) {
      setError(err.message || 'Invalid email or password');
    } finally {
      setLoading(false);
    }
  };

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
          <h2 className="text-lg font-semibold text-text-primary mb-4">Sign In</h2>

          {error && (
            <div className="mb-4 p-3 bg-accent-crimson/10 border border-accent-crimson/30 rounded-md text-accent-crimson text-sm">
              {error}
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="block text-sm text-text-secondary mb-1">Email</label>
              <input type="email" value={email} onChange={e => setEmail(e.target.value)}
                className="w-full bg-bg-surface border border-border-default rounded-md px-3 py-2 text-text-primary focus:border-border-focus focus:outline-none"
                placeholder="trader@bahamut.ai" required autoFocus />
            </div>
            <div>
              <label className="block text-sm text-text-secondary mb-1">Password</label>
              <input type="password" value={password} onChange={e => setPassword(e.target.value)}
                className="w-full bg-bg-surface border border-border-default rounded-md px-3 py-2 text-text-primary focus:border-border-focus focus:outline-none"
                placeholder="Password" required minLength={6} />
            </div>
            <button type="submit" disabled={loading}
              className="w-full bg-accent-violet hover:bg-accent-violet/90 text-white font-semibold py-2.5 rounded-md transition-colors disabled:opacity-50">
              {loading ? 'Signing in...' : 'Sign In'}
            </button>
          </form>

          <div className="mt-4 text-center text-xs text-text-muted">
            Contact your administrator to create an account
          </div>
        </div>
      </div>
    </div>
  );
}
