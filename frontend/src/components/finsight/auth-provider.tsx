"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import { useRouter, usePathname } from "next/navigation";
import {
  type AuthUser,
  getToken,
  getUser,
  setAuth,
  clearAuth,
} from "@/lib/auth";

interface AuthContextValue {
  user: AuthUser | null;
  token: string | null;
  isLoading: boolean;
  login: (token: string, user: AuthUser) => void;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue>({
  user: null,
  token: null,
  isLoading: true,
  login: () => {},
  logout: () => {},
});

export function useAuth() {
  return useContext(AuthContext);
}

const PUBLIC_PATHS = ["/", "/login"];

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    // Hydrating auth state from localStorage on mount. SSR can't read
    // localStorage so this must run client-side after first render.
    const t = getToken();
    const u = getUser();
    if (t && u) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setToken(t);
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setUser(u);
    }
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setIsLoading(false);
  }, []);

  // Redirect to login if not authenticated and not on a public path
  useEffect(() => {
    if (isLoading) return;
    if (!token && !PUBLIC_PATHS.includes(pathname)) {
      router.replace("/login");
    }
  }, [isLoading, token, pathname, router]);

  const login = useCallback((newToken: string, newUser: AuthUser) => {
    setAuth(newToken, newUser);
    setToken(newToken);
    setUser(newUser);
  }, []);

  const logout = useCallback(() => {
    clearAuth();
    setToken(null);
    setUser(null);
    router.replace("/login");
  }, [router]);

  return (
    <AuthContext.Provider value={{ user, token, isLoading, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}
