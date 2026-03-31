/**
 * Wallet API — persistent backend wallet
 * Falls back to localStorage if API is unavailable
 */

const API = process.env.NEXT_PUBLIC_API_URL || '';

function getH(): Record<string, string> {
  const t = typeof window !== 'undefined' ? localStorage.getItem('bahamut_token') : null;
  return t ? { Authorization: `Bearer ${t}`, 'Content-Type': 'application/json' } : { 'Content-Type': 'application/json' };
}

export interface WalletState {
  balance: number;
  allocation: number;
  mode: string;
  transactions: WalletTransaction[];
}

export interface WalletTransaction {
  type: string;
  amount: number;
  balance_after: number;
  allocation_after: number;
  mode: string;
  timestamp: string;
}

export async function fetchWallet(): Promise<WalletState | null> {
  try {
    const r = await fetch(`${API}/api/v1/wallet`, { headers: getH() });
    if (r.ok) return r.json();
  } catch {}
  return null;
}

export async function depositFunds(amount: number, mode: string = 'demo'): Promise<{ balance: number; allocation: number; deposited: number } | null> {
  try {
    const r = await fetch(`${API}/api/v1/wallet/deposit`, {
      method: 'POST',
      headers: getH(),
      body: JSON.stringify({ amount, mode }),
    });
    if (r.ok) return r.json();
  } catch {}
  return null;
}

export async function setAllocation(amount: number, mode: string = 'demo'): Promise<{ balance: number; allocation: number } | null> {
  try {
    const r = await fetch(`${API}/api/v1/wallet/allocation`, {
      method: 'POST',
      headers: getH(),
      body: JSON.stringify({ amount, mode }),
    });
    if (r.ok) return r.json();
  } catch {}
  return null;
}
