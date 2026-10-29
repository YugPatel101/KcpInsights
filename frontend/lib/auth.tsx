"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { api, setCsrfToken } from "@/lib/api";
import type { Session, User } from "@/lib/types";

interface AuthState {
  user: User | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (display_name: string, email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  refresh: () => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  const apply = (s: Session | null) => {
    setUser(s?.user ?? null);
    setCsrfToken(s?.csrf_token ?? null);
  };

  const refresh = useCallback(async () => {
    try {
      apply(await api<Session | null>("/api/auth/me"));
    } catch {
      apply(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    let alive = true;
    api<Session | null>("/api/auth/me")
      .then((s) => alive && apply(s))
      .catch(() => alive && apply(null))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, []);

  const value = useMemo<AuthState>(
    () => ({
      user,
      loading,
      refresh,
      login: async (email, password) => apply(await api<Session>("/api/auth/login", { body: { email, password } })),
      register: async (display_name, email, password) =>
        apply(await api<Session>("/api/auth/register", { body: { display_name, email, password } })),
      logout: async () => {
        try {
          await api("/api/auth/logout", { method: "POST" });
        } finally {
          apply(null);
        }
      },
    }),
    [user, loading, refresh],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}
