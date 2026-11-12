import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useSyncExternalStore,
  type ReactNode,
} from "react";

import { api, unwrap, type Schemas } from "../api/client";
import { getToken, setToken, subscribeToken } from "../lib/session";

import type { Me } from "./portal";

interface AuthState {
  /** "loading" while a stored token is being checked against /auth/me. */
  status: "loading" | "signed-out" | "signed-in" | "unavailable";
  /** Why the session could not be checked, when status is "unavailable". */
  problem: unknown;
  retry: () => void;
  user: Me | null;
  signIn: (email: string, password: string) => Promise<void>;
  register: (fullName: string, email: string, password: string) => Promise<void>;
  signOut: () => void;
  can: (permission: Schemas["Permission"]) => boolean;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const client = useQueryClient();
  const token = useSyncExternalStore(subscribeToken, getToken, () => null);

  // What the user may do comes from the server on every load, never from a cached role.
  const me = useQuery({
    queryKey: ["me", token],
    queryFn: () => unwrap(api.GET("/auth/me")),
    enabled: token !== null,
    retry: false,
    staleTime: 60_000,
  });

  const { refetch } = me;

  const signOut = useCallback(() => {
    setToken(null);
    client.clear();
  }, [client]);

  const signIn = useCallback(
    async (email: string, password: string) => {
      const issued = await unwrap(api.POST("/auth/login", { body: { email, password } }));
      client.clear();
      setToken(issued.access_token);
    },
    [client],
  );

  const register = useCallback(
    async (fullName: string, email: string, password: string) => {
      const issued = await unwrap(
        api.POST("/auth/register", { body: { full_name: fullName, email, password } }),
      );
      client.clear();
      setToken(issued.access_token);
    },
    [client],
  );

  const value = useMemo<AuthState>(() => {
    const user = token !== null && me.data !== undefined ? me.data : null;
    // A 401 clears the token (api/client.ts), which is the only thing that signs someone out.
    // An outage is not a sign-out: say the server is unreachable and keep the session.
    const status =
      token === null
        ? "signed-out"
        : user !== null
          ? "signed-in"
          : me.isError
            ? "unavailable"
            : "loading";
    return {
      status,
      problem: me.error,
      retry: () => {
        void refetch();
      },
      user,
      signIn,
      register,
      signOut,
      can: (permission) => user?.permissions.includes(permission) ?? false,
    };
  }, [token, me.data, me.isError, me.error, refetch, signIn, register, signOut]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

// eslint-disable-next-line react-refresh/only-export-components -- the hook belongs with its provider
export function useAuth(): AuthState {
  const state = useContext(AuthContext);
  if (state === null) throw new Error("useAuth must be used inside <AuthProvider>");
  return state;
}
