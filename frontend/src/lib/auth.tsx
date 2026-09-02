"use client";

import { useRouter } from "next/navigation";
import {
  createContext, useCallback, useContext, useEffect, useMemo, useState,
} from "react";

import { api, setUnauthorizedHandler } from "./api";
import type { Me } from "./types";

interface AuthState {
  user: Me | null;
  loading: boolean;
  signIn: (email: string, password: string) => Promise<void>;
  signOut: () => Promise<void>;
  can: (permission: string) => boolean;
  refresh: () => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);
  const router = useRouter();

  const load = useCallback(async () => {
    try {
      setUser(await api.get<Me>("/auth/me"));
    } catch {
      setUser(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    setUnauthorizedHandler(() => {
      setUser(null);
    });
    void load();
  }, [load]);

  const signIn = useCallback(
    async (email: string, password: string) => {
      const result = await api.post<{ user: Me }>("/auth/login", { email, password });
      setUser(result.user);
      router.push(result.user.permissions.includes("dashboard.view") ? "/dashboard" : "/accounting");
    },
    [router],
  );

  const signOut = useCallback(async () => {
    try {
      await api.post("/auth/logout");
    } finally {
      setUser(null);
      router.push("/login");
    }
  }, [router]);

  const value = useMemo<AuthState>(
    () => ({
      user,
      loading,
      signIn,
      signOut,
      can: (permission: string) => Boolean(user?.permissions.includes(permission)),
      refresh: load,
    }),
    [user, loading, signIn, signOut, load],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used inside AuthProvider");
  return context;
}
