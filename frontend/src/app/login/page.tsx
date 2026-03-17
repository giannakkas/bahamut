'use client';

import { useState } from 'react';
import { useAuthStore } from '@/stores/auth';

export default function LoginPage() {
  const [isRegister, setIsRegister] = useState(false);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [fullName, setFullName] = useState('');
  const [workspace, setWorkspace] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const { login, register } = useAuthStore();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      if (isRegister) {
        await register(email, password, fullName, workspace);
      } else {
        await login(email, password);
      }
      window.location.href = '/';
    } catch (err: any) {
      setError(err.message || 'Authentication failed');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-bg-primary flex items-center justify-center">
      <div className="w-full max-w-md">
        <div className="text-center mb-8">
          <div className="inline-block mb-4">
            <img src="/logo.png" alt="Bahamut.AI" className="h-24 w-auto object-contain" />
          </div>
          <p className="text-text-secondary text-sm">Institutional-Grade Trading Intelligence</p>
        </div>

        <div className="bg-bg-secondary border border-border-default rounded-lg p-6">
          <h2 className="text-lg font-semibold text-text-primary mb-4">
            {isRegister ? 'Create Account' : 'Sign In'}
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
                    placeholder="Chris Giannakkas" required />
                </div>
                <div>
                  <label className="block text-sm text-text-secondary mb-1">Workspace Name</label>
                  <input type="text" value={workspace} onChange={e => setWorkspace(e.target.value)}
                    className="w-full bg-bg-surface border border-border-default rounded-md px-3 py-2 text-text-primary focus:border-border-focus focus:outline-none"
                    placeholder="Bahamut Trading" required />
                </div>
              </>
            )}
            <div>
              <label className="block text-sm text-text-secondary mb-1">Email</label>
              <input type="email" value={email} onChange={e => setEmail(e.target.value)}
                className="w-full bg-bg-surface border border-border-default rounded-md px-3 py-2 text-text-primary focus:border-border-focus focus:outline-none"
                placeholder="trader@bahamut.ai" required />
            </div>
            <div>
              <label className="block text-sm text-text-secondary mb-1">Password</label>
              <input type="password" value={password} onChange={e => setPassword(e.target.value)}
                className="w-full bg-bg-surface border border-border-default rounded-md px-3 py-2 text-text-primary focus:border-border-focus focus:outline-none"
                placeholder="Password" required minLength={6} />
            </div>
            <button type="submit" disabled={loading}
              className="w-full bg-accent-violet hover:bg-accent-violet/90 text-white font-semibold py-2.5 rounded-md transition-colors disabled:opacity-50">
              {loading ? 'Processing...' : isRegister ? 'Create Account' : 'Sign In'}
            </button>
          </form>

          <div className="mt-4 text-center">
            <button onClick={() => { setIsRegister(!isRegister); setError(''); }}
              className="text-sm text-accent-violet hover:text-accent-violet/80">
              {isRegister ? 'Already have an account? Sign in' : 'Need an account? Register'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
