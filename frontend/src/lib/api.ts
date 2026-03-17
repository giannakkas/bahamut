const API_URL = 'https://bahamut-production.up.railway.app';

class ApiClient {
  private token: string | null = null;
  setToken(token: string) { this.token = token; }
  clearToken() { this.token = null; }

  private async request<T>(path: string, options: RequestInit = {}): Promise<T> {
    const headers: Record<string, string> = { 'Content-Type': 'application/json', ...(options.headers as Record<string, string> || {}) };
    if (this.token) headers['Authorization'] = `Bearer ${this.token}`;
    const res = await fetch(`${API_URL}/api/v1${path}`, { ...options, headers });
    if (!res.ok) { const err = await res.json().catch(() => ({ message: res.statusText })); throw new Error(err.detail || err.message || `API error ${res.status}`); }
    return res.json();
  }

  // Auth
  async login(e: string, p: string) { return this.request<any>('/auth/login', { method: 'POST', body: JSON.stringify({ email: e, password: p }) }); }
  async register(e: string, p: string, n: string, w: string) { return this.request<any>('/auth/register', { method: 'POST', body: JSON.stringify({ email: e, password: p, full_name: n, workspace_name: w }) }); }
  async getMe() { return this.request<any>('/auth/me'); }

  // Agents
  async triggerCycle(asset: string, ac: string = 'fx', tf: string = '4H', p: string = 'BALANCED') {
    return this.request<any>('/agents/trigger', { method: 'POST', body: JSON.stringify({ asset, asset_class: ac, timeframe: tf, trading_profile: p }) });
  }
  async getLatestCycle(asset: string) { return this.request<any>(`/agents/latest-cycle/${asset}`); }
  async getAllLatestCycles() { return this.request<any>('/agents/latest-cycles'); }
  async getTrustScores() { return this.request<any>('/agents/trust-scores'); }
  async getAgentHealth() { return this.request<any>('/agents/health'); }
  async getCycleHistory(asset?: string, limit: number = 50) {
    const q = asset ? `?asset=${asset}&limit=${limit}` : `?limit=${limit}`;
    return this.request<any[]>(`/agents/history${q}`);
  }

  // Consensus
  async getThresholds() { return this.request<any>('/consensus/thresholds'); }
  async getWeights(ac: string) { return this.request<any>(`/consensus/weights/${ac}`); }

  // Market
  async getCandles(symbol: string, tf: string = '4H', count: number = 200) {
    return this.request<any>(`/market/candles/${symbol}?timeframe=${tf}&count=${count}`);
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
  async getBreakingAlerts() { return this.request<any>("/agents/breaking-alerts"); }
  async getPlans() { return this.request<any>("/billing/plans"); }
  async getBillingStatus() { return this.request<any>("/billing/status"); }

  // News & Calendar
  async getCalendar(days: number = 7) { return this.request<any>(`/market/calendar?days=${days}`); }
  async getNews(query: string = "forex market", count: number = 10) { return this.request<any>(`/market/news?query=${query}&count=${count}`); }
  async getAssetNews(symbol: string) { return this.request<any>(`/market/news/${symbol}`); }

  // Paper Trading / Self-Learning
  async getPaperPortfolio() { return this.request<any>('/paper-trading/portfolio'); }
  async getPaperPositions(status?: string, asset?: string, limit: number = 50) {
    const params = new URLSearchParams();
    if (status) params.set('status', status);
    if (asset) params.set('asset', asset);
    params.set('limit', String(limit));
    return this.request<any>(`/paper-trading/positions?${params}`);
  }
  async getPaperLeaderboard() { return this.request<any>('/paper-trading/leaderboard'); }
  async getPaperAgentDetail(agent: string) { return this.request<any>(`/paper-trading/agent-performance/${agent}`); }
  async getPaperLearningLog(limit: number = 30) { return this.request<any>(`/paper-trading/learning-log?limit=${limit}`); }
  async getPaperStats() { return this.request<any>('/paper-trading/stats'); }
  async resetPaperPortfolio() { return this.request<any>('/paper-trading/reset', { method: 'POST' }); }
  async togglePaperTrading(active: boolean) { return this.request<any>(`/paper-trading/toggle?active=${active}`, { method: 'POST' }); }

  // Scanner
  async getTopPicks() { return this.request<any>('/scanner/top-picks'); }
  async getAllScanned(assetClass?: string, minScore?: number, direction?: string) {
    const params = new URLSearchParams();
    if (assetClass) params.set('asset_class', assetClass);
    if (minScore) params.set('min_score', String(minScore));
    if (direction) params.set('direction', direction);
    return this.request<any>(`/scanner/all?${params}`);
  }
  async triggerScan() { return this.request<any>('/scanner/trigger', { method: 'POST' }); }
  async getDeepResults() { return this.request<any>('/scanner/deep-results'); }
}

export const api = new ApiClient();
