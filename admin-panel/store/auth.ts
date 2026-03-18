import { create } from "zustand";
import {
  isAuthenticated,
  logout as apiLogout,
  setAuthExpiredCallback,
} from "@/lib/api";

interface AuthState {
  user: string | null;
  /** null = not yet checked, false = unauthenticated, true = authenticated */
  isAuthed: boolean | null;
  setUser: (user: string) => void;
  logout: () => void;
  checkAuth: () => void;
}

export const useAuthStore = create<AuthState>((set) => {
  // Register callback so api.ts can trigger logout without circular import
  setAuthExpiredCallback(() => {
    apiLogout();
    set({ user: null, isAuthed: false });
  });

  return {
    user: null,
    isAuthed: null,

    setUser: (user: string) => set({ user, isAuthed: true }),

    logout: () => {
      apiLogout();
      set({ user: null, isAuthed: false });
    },

    checkAuth: () => {
      const authed = isAuthenticated();
      set({ isAuthed: authed });
    },
  };
});
