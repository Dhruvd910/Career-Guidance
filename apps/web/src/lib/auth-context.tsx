"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { api, ApiError, getToken, setToken, StudentProfile } from "./api";

interface AuthContextValue {
  profile: StudentProfile | null;
  loading: boolean;
  isAuthenticated: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string, name: string, classLevel: number) => Promise<void>;
  logout: () => void;
  refreshProfile: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [profile, setProfile] = useState<StudentProfile | null>(null);
  const [loading, setLoading] = useState(true);

  const refreshProfile = useCallback(async () => {
    if (!getToken()) {
      setProfile(null);
      return;
    }
    try {
      const p = await api.student.getProfile();
      setProfile(p);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        setToken(null);
        setProfile(null);
      }
    }
  }, []);

  useEffect(() => {
    refreshProfile().finally(() => setLoading(false));
  }, [refreshProfile]);

  const login = useCallback(
    async (email: string, password: string) => {
      const { access_token } = await api.auth.login({ email, password });
      setToken(access_token);
      await refreshProfile();
    },
    [refreshProfile]
  );

  const register = useCallback(
    async (email: string, password: string, name: string, classLevel: number) => {
      const { access_token } = await api.auth.register({ email, password, name, class_level: classLevel });
      setToken(access_token);
      await refreshProfile();
    },
    [refreshProfile]
  );

  const logout = useCallback(() => {
    setToken(null);
    setProfile(null);
  }, []);

  return (
    <AuthContext.Provider value={{ profile, loading, isAuthenticated: !!profile, login, register, logout, refreshProfile }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
