"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";

import { api } from "@/lib/api";
import type { Account } from "@/lib/types";

type AccountContextValue = {
  accounts: Account[];
  account: Account | null;
  loading: boolean;
  setAccountId: (id: string) => void;
  refresh: () => Promise<void>;
};

const AccountContext = createContext<AccountContextValue | null>(null);

export function AccountProvider({ children }: { children: React.ReactNode }) {
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [accountId, setAccountIdState] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      const next = await api<Account[]>("/accounts", { cache: "reload" });
      setAccounts(next);
      const stored = window.localStorage.getItem("journalme-account");
      setAccountIdState((current) => {
        const preferred = current ?? stored;
        const resolved = next.some((item) => item.id === preferred)
          ? preferred
          : (next[0]?.id ?? null);
        if (resolved) window.localStorage.setItem("journalme-account", resolved);
        else window.localStorage.removeItem("journalme-account");
        return resolved;
      });
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    const onFocus = () => void refresh();
    window.addEventListener("focus", onFocus);
    return () => window.removeEventListener("focus", onFocus);
  }, [refresh]);

  const setAccountId = useCallback((id: string) => {
    setAccountIdState(id);
    window.localStorage.setItem("journalme-account", id);
  }, []);
  const account = accounts.find((item) => item.id === accountId) ?? null;
  const value = useMemo(
    () => ({ accounts, account, loading, setAccountId, refresh }),
    [accounts, account, loading, setAccountId, refresh],
  );
  return (
    <AccountContext.Provider value={value}>{children}</AccountContext.Provider>
  );
}

export function useAccount() {
  const value = useContext(AccountContext);
  if (!value) throw new Error("useAccount must be used inside AccountProvider.");
  return value;
}

