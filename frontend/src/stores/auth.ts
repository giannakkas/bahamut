import { create } from 'zustand';
import { api } from '@/lib/api';
import type { User } from '@/lib/types';

interface AuthStore {
  user: User | null;
  token: string | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string, name: string, workspace: string) => Promise<void>;
  logout: () => void;
  setFromStorage: () => void;
}

export const useAuthStore = create<AuthStore>((set) => ({
  user: null,
  token: null,
  isAuthenticated: false,
  isLoading: false,

  login: async (email, password) => {
    set({ isLoading: true });
    try {
      const res = await api.login(email, password);
      api.setToken(res.access_token);
      localStorage.setItem('bahamut_token', res.access_token);
      localStorage.setItem('bahamut_user', JSON.stringify(res.user));
      set({ user: res.user, token: res.access_token, isAuthenticated: true, isLoading: false });
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
      localStorage.setItem('bahamut_token', res.access_token);
      localStorage.setItem('bahamut_user', JSON.stringify(res.user));
      set({ user: res.user, token: res.access_token, isAuthenticated: true, isLoading: false });
    } catch (e) {
      set({ isLoading: false });
      throw e;
    }
  },

  logout: () => {
    api.clearToken();
    localStorage.removeItem('bahamut_token');
    localStorage.removeItem('bahamut_user');
    set({ user: null, token: null, isAuthenticated: false });
  },

  setFromStorage: () => {
    const token = localStorage.getItem('bahamut_token');
    const userStr = localStorage.getItem('bahamut_user');
    if (token && userStr) {
      api.setToken(token);
      set({ token, user: JSON.parse(userStr), isAuthenticated: true });
    }
  },
}));
