import { createContext, ReactNode, useContext, useEffect, useState } from "react";
import { Admin, api, ApiError } from "./api";

interface AdminContextValue {
  admin: Admin | null;
  loading: boolean;
  refresh: () => Promise<void>;
  setAdmin: (admin: Admin | null) => void;
}

const AdminContext = createContext<AdminContextValue | null>(null);

export function AdminProvider({ children }: { children: ReactNode }) {
  const [admin, setAdmin] = useState<Admin | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = async () => {
    try {
      setAdmin(await api.get<Admin>("/me"));
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) setAdmin(null);
      else throw err;
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <AdminContext.Provider value={{ admin, loading, refresh, setAdmin }}>{children}</AdminContext.Provider>
  );
}

export function useAdmin() {
  const ctx = useContext(AdminContext);
  if (!ctx) throw new Error("useAdmin must be used within AdminProvider");
  return ctx;
}
