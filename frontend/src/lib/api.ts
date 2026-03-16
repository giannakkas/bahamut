const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

class ApiClient {
  private token: string | null = null;

  setToken(token: string) { this.token = token; }
  clearToken() { this.token = null; }

  private async request<T>(path: string, options: RequestInit = {}): Promise<T> {
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      ...(options.headers as Record<string, string> || {}),
    };
    if (this.token) headers['Authorization'] = `Bearer ${this.token}`;

    const res = await fetch(`${API_URL}/api/v1${path}`, { ...options, headers });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ message: res.statusText }));
      throw new Error(err.detail || err.message || `API error ${res.status}`);
    }
    return res.json();
  }

  // Auth
  async login(email: string, password: string) {
    return this.request<{ access_token: string; refresh_token: string; user: any }>(
      '/auth/login', { method: 'POST', body: JSON.stringify({ email, password }) }
    );
  }

  async register(email: string, password: string, full_name: string, workspace_name: string) {
    return this.request<{ access_token: string; refresh_token: string; user: any }>(
      '/auth/register', { method: 'POST', body: JSON.stringify({ email, password, full_name, workspace_name }) }
    );
  }

  async getMe() { return this.request<any>('/auth/me'); }

  // Signals
  async getActiveSignals() { return this.request<any[]>('/agents/health'); }
  async triggerCycle(asset: string, timeframe: string) {
    return this.request<any>('/agents/trigger', {
      method: 'POST', body: JSON.stringify({ asset, timeframe }),
    });
  }

  // Trust scores
  async getTrustScores() { return this.request<any>('/learning/trust-scores'); }

  // Risk
  async getRiskDashboard() { return this.request<any>('/risk/health'); }

  // Health
  async getHealth() { return this.request<any>('/health'.replace('/api/v1', '')); }
}

export const api = new ApiClient();
