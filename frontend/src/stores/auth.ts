import { create } from 'zustand';
import { api } from '@/lib/api';

interface User {
  id: string;
  email: string;
  full_name: string;
  role: string;
  workspace_id: string;
}

interface AuthStore {
  user: User | null;
  token: string | null;
  refreshToken: string | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string, name: string, workspace: string) => Promise<void>;
  logout: () => void;
  loadFromStorage: () => void;
}

export const useAuthStore = create<AuthStore>((set) => ({
  user: null,
  token: null,
  refreshToken: null,
  isAuthenticated: false,
  isLoading: false,

  login: async (email, password) => {
    set({ isLoading: true });
    try {
      const res = await api.login(email, password);
      api.setToken(res.access_token);
      api.setRefreshToken(res.refresh_token);
      if (typeof window !== 'undefined') {
        localStorage.setItem('bahamut_token', res.access_token);
        localStorage.setItem('bahamut_refresh_token', res.refresh_token);
        localStorage.setItem('bahamut_user', JSON.stringify(res.user));
      }
      set({ user: res.user, token: res.access_token, refreshToken: res.refresh_token, isAuthenticated: true, isLoading: false });
    } catch (e) {
      set({ isLoading: false });
      throw e;
    }
  },

  register: async (email, password, name, workspace) => {
    set({ isLoading: true });
    try {
      const res = await api.register(email, password, name, workspace);
      api.setToken(res.access_token);
      api.setRefreshToken(res.refresh_token);
      if (typeof window !== 'undefined') {
        localStorage.setItem('bahamut_token', res.access_token);
        localStorage.setItem('bahamut_refresh_token', res.refresh_token);
        localStorage.setItem('bahamut_user', JSON.stringify(res.user));
      }
      set({ user: res.user, token: res.access_token, refreshToken: res.refresh_token, isAuthenticated: true, isLoading: false });
    } catch (e) {
      set({ isLoading: false });
      throw e;
    }
  },

  logout: () => {
    api.clearToken();
    if (typeof window !== 'undefined') {
      localStorage.removeItem('bahamut_token');
      localStorage.removeItem('bahamut_refresh_token');
      localStorage.removeItem('bahamut_user');
    }
    set({ user: null, token: null, refreshToken: null, isAuthenticated: false });
  },

  loadFromStorage: () => {
    if (typeof window === 'undefined') return;
    const token = localStorage.getItem('bahamut_token');
    const refreshToken = localStorage.getItem('bahamut_refresh_token');
    const userStr = localStorage.getItem('bahamut_user');
    if (token && userStr) {
      api.setToken(token);
      if (refreshToken) api.setRefreshToken(refreshToken);
      set({ token, refreshToken, user: JSON.parse(userStr), isAuthenticated: true });
    }
  },
}));

// Wire up the API client's logout callback to the store
api.onLogout(() => {
  useAuthStore.getState().logout();
});
