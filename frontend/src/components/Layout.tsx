import { Link, NavLink, useNavigate } from "react-router-dom";
import { useAdmin } from "../AdminContext";
import { api } from "../api";

const NAV_ITEMS = [
  { to: "/admin", label: "Dashboard", end: true },
  { to: "/admin/clients", label: "Applications" },
  { to: "/admin/resources", label: "APIs & MCP servers" },
  { to: "/admin/users", label: "Users" },
  { to: "/admin/pools", label: "Login groups" },
  { to: "/admin/audit", label: "Activity log" },
  { to: "/admin/account", label: "Account" },
];

export function Layout({ children }: { children: React.ReactNode }) {
  const { admin, setAdmin } = useAdmin();
  const navigate = useNavigate();

  const signOut = async () => {
    await api.post("/logout");
    setAdmin(null);
    navigate("/admin/login");
  };

  return (
    <div className="shell">
      <nav className="nav">
        <div className="nav__brand">Auth Admin</div>
        {NAV_ITEMS.map((item) => (
          <NavLink key={item.to} to={item.to} end={item.end}>
            {item.label}
          </NavLink>
        ))}
        <form onSubmit={(e) => { e.preventDefault(); signOut(); }}>
          <button type="submit" className="btn btn--secondary btn--block">Sign out</button>
        </form>
      </nav>
      <main className="main">
        {admin?.must_change_password && (
          <div className="alert alert--error" style={{ marginBottom: 24 }}>
            You're signed in with the default admin password.{" "}
            <Link to="/admin/account" style={{ fontWeight: 600 }}>Change it now</Link>.
          </div>
        )}
        {children}
      </main>
    </div>
  );
}
