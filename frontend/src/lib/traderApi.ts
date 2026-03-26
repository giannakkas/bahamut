/**
 * Bahamut Trader API — fetches real data from backend.
 * All endpoints use JWT auth from localStorage.
 */

const API = process.env.NEXT_PUBLIC_API_URL || 'https://bahamut-production.up.railway.app';

function getHeaders(): Record<string, string> {
  const token = typeof window !== 'undefined' ? localStorage.getItem('bahamut_token') : null;
  return token
    ? { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }
    : { 'Content-Type': 'application/json' };
}

async function get<T = any>(path: string): Promise<T | null> {
  try {
    const r = await fetch(`${API}/api/v1${path}`, {
      headers: getHeaders(),
      signal: AbortSignal.timeout(10000),
    });
    if (r.ok) return r.json();
    console.warn(`API ${path} → ${r.status}`);
    return null;
  } catch (e) {
    console.warn(`API ${path} failed:`, e);
    return null;
  }
}

// ─── Dashboard ───
export async function fetchDashboard() {
  const [portfolio, accuracy, exploration, overview] = await Promise.all([
    get('/paper-trading/stats'),
    get('/monitoring/trading-accuracy'),
    get('/monitoring/exploration-status'),
    get('/signals/macro-overview'),
  ]);

  return {
    balance: portfolio?.portfolio?.balance ?? 100000,
    totalPnl: portfolio?.portfolio?.total_pnl ?? 0,
    totalPnlPct: portfolio?.portfolio?.total_pnl_pct ?? 0,
    winRate: accuracy?.strict_accuracy_pct ?? portfolio?.portfolio?.win_rate ?? 0,
    tradesClosed: accuracy?.strict_total_trades ?? portfolio?.portfolio?.total_trades ?? 0,
    maxDrawdown: portfolio?.portfolio?.max_drawdown ?? 0,
    exploration,
    // Build opportunities from macro overview (real prices + indicators)
    opportunities: overview ? Object.entries(overview).map(([asset, data]: [string, any]) => ({
      asset: asset.replace('USD', ' / USD').replace('XAU', 'Gold'),
      price: data.price || 0,
      trend: data.trend || 'MIXED',
      rsi: data.rsi || 50,
      adx: data.adx || 20,
      momentum: data.momentum || 'WEAK',
      source: data.source || 'demo',
    })).filter(a => a.price > 0) : [],
  };
}

// ─── Portfolio (open positions) ───
export async function fetchPositions() {
  const data = await get('/paper-trading/positions?status=OPEN&limit=20');
  return data?.positions ?? [];
}

// ─── Trades (closed) ───
export async function fetchClosedTrades() {
  const data = await get('/paper-trading/positions?status=CLOSED&limit=50');
  // Also get non-CLOSED statuses (TP, SL, TIMEOUT)
  const data2 = await get('/paper-trading/positions?limit=50');
  const all = (data2?.positions ?? []).filter((p: any) => p.status !== 'OPEN');
  return all.length > 0 ? all : (data?.positions ?? []);
}

// ─── Trade Stats ───
export async function fetchTradeStats() {
  return get('/paper-trading/stats');
}

// ─── News ───
export async function fetchNews(category: string = 'general', count: number = 15) {
  const data = await get(`/data/news?query=${category}&count=${count}`);
  return data?.articles ?? [];
}

// ─── Economic Calendar ───
export async function fetchCalendar() {
  const data = await get('/data/calendar');
  return data?.events ?? [];
}

// ─── Candles (for charts) ───
export async function fetchCandles(symbol: string, timeframe: string = '4H', count: number = 100) {
  const data = await get(`/data/candles/${symbol}?timeframe=${timeframe}&count=${count}`);
  return data?.candles ?? [];
}

// ─── Top Picks (latest cycles with scores) ───
export async function fetchTopPicks() {
  const data = await get('/signals/latest-cycles');
  if (!data) return [];
  return Object.entries(data).map(([asset, cycle]: [string, any]) => {
    const d = cycle.decision || {};
    return {
      asset,
      score: Math.round((d.final_score || 0) * 100),
      direction: d.direction || 'NEUTRAL',
      label: d.decision || 'NO_TRADE',
      price: cycle.features?.indicators?.close || 0,
      rsi: Math.round(cycle.features?.indicators?.rsi_14 || 50),
      adx: Math.round(cycle.features?.indicators?.adx_14 || 20),
      regime: cycle.regime || 'UNKNOWN',
      source: cycle.data_source || 'demo',
    };
  }).sort((a, b) => b.score - a.score);
}

// ─── Macro overview (for opportunities) ───
export async function fetchMacroOverview() {
  return get('/signals/macro-overview');
}

// ─── Trading accuracy ───
export async function fetchAccuracy() {
  return get('/monitoring/trading-accuracy');
}

// ─── Exploration status ───
export async function fetchExploration() {
  return get('/monitoring/exploration-status');
}
