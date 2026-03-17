const API_URL = 'https://bahamut-production.up.railway.app';

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
    return this.request<any>('/auth/login', { method: 'POST', body: JSON.stringify({ email, password }) });
  }
  async register(email: string, password: string, full_name: string, workspace_name: string) {
    return this.request<any>('/auth/register', { method: 'POST', body: JSON.stringify({ email, password, full_name, workspace_name }) });
  }
  async getMe() { return this.request<any>('/auth/me'); }

  // Agents
  async triggerCycle(asset: string, asset_class: string = 'fx', timeframe: string = '4H', trading_profile: string = 'BALANCED') {
    return this.request<any>('/agents/trigger', { method: 'POST', body: JSON.stringify({ asset, asset_class, timeframe, trading_profile }) });
  }
  async getLatestCycle(asset: string) { return this.request<any>(`/agents/latest-cycle/${asset}`); }
  async getAllLatestCycles() { return this.request<any>('/agents/latest-cycles'); }
  async getTrustScores() { return this.request<any>('/agents/trust-scores'); }
  async getAgentHealth() { return this.request<any>('/agents/health'); }

  // Consensus
  async getThresholds() { return this.request<any>('/consensus/thresholds'); }
  async getWeights(assetClass: string) { return this.request<any>(`/consensus/weights/${assetClass}`); }

  // Market Data
  async getCandles(symbol: string, timeframe: string = '4H', count: number = 200) {
    return this.request<any>(`/market/candles/${symbol}?timeframe=${timeframe}&count=${count}`);
  }
  async getPrice(symbol: string) { return this.request<any>(`/market/price/${symbol}`); }

  // Risk
  async getRiskDashboard() { return this.request<any>('/risk/dashboard'); }

  // Execution
  async killSwitch() { return this.request<any>('/execution/kill-switch', { method: 'POST' }); }

  // Learning
  async getStrategyFitness() { return this.request<any>('/learning/fitness'); }
  async emergencyRecalibrate() { return this.request<any>('/learning/emergency-recalibrate', { method: 'POST' }); }

  // Reports
  async getDailyBrief() { return this.request<any>('/reports/daily-brief'); }
}

export const api = new ApiClient();
