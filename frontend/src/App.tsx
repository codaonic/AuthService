import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { AdminProvider, useAdmin } from "./AdminContext";
import { Layout } from "./components/Layout";
import { Login } from "./pages/Login";
import { Dashboard } from "./pages/Dashboard";
import { Applications } from "./pages/Applications";
import { Resources } from "./pages/Resources";
import { Users } from "./pages/Users";
import { LoginGroups } from "./pages/LoginGroups";
import { AuditLog } from "./pages/AuditLog";
import { Account } from "./pages/Account";

function RequireAdmin({ children }: { children: JSX.Element }) {
  const { admin, loading } = useAdmin();
  const location = useLocation();

  if (loading) return null;
  if (!admin) return <Navigate to="/admin/login" state={{ from: location }} replace />;
  return children;
}

function AppRoutes() {
  return (
    <Routes>
      <Route path="/admin/login" element={<Login />} />
      <Route
        path="/admin"
        element={
          <RequireAdmin>
            <Layout>
              <Dashboard />
            </Layout>
          </RequireAdmin>
        }
      />
      <Route
        path="/admin/clients"
        element={
          <RequireAdmin>
            <Layout>
              <Applications />
            </Layout>
          </RequireAdmin>
        }
      />
      <Route
        path="/admin/resources"
        element={
          <RequireAdmin>
            <Layout>
              <Resources />
            </Layout>
          </RequireAdmin>
        }
      />
      <Route
        path="/admin/users"
        element={
          <RequireAdmin>
            <Layout>
              <Users />
            </Layout>
          </RequireAdmin>
        }
      />
      <Route
        path="/admin/pools"
        element={
          <RequireAdmin>
            <Layout>
              <LoginGroups />
            </Layout>
          </RequireAdmin>
        }
      />
      <Route
        path="/admin/audit"
        element={
          <RequireAdmin>
            <Layout>
              <AuditLog />
            </Layout>
          </RequireAdmin>
        }
      />
      <Route
        path="/admin/account"
        element={
          <RequireAdmin>
            <Layout>
              <Account />
            </Layout>
          </RequireAdmin>
        }
      />
      <Route path="*" element={<Navigate to="/admin" replace />} />
    </Routes>
  );
}

export function App() {
  return (
    <AdminProvider>
      <AppRoutes />
    </AdminProvider>
  );
}
