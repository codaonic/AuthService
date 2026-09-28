import { Link, NavLink, useNavigate } from "react-router-dom";
import { useAdmin } from "../AdminContext";
import { api } from "../api";
import {
  AccountIcon,
  ActivityIcon,
  AppsIcon,
  DashboardIcon,
  GroupsIcon,
  ResourcesIcon,
  ShieldIcon,
  SignOutIcon,
  UsersIcon,
} from "./Icons";

const NAV_ITEMS = [
  { to: "/admin", label: "Dashboard", end: true, icon: DashboardIcon },
  { to: "/admin/clients", label: "Applications", icon: AppsIcon },
  { to: "/admin/resources", label: "APIs & MCP servers", icon: ResourcesIcon },
  { to: "/admin/users", label: "Users", icon: UsersIcon },
  { to: "/admin/pools", label: "Login groups", icon: GroupsIcon },
  { to: "/admin/audit", label: "Activity log", icon: ActivityIcon },
  { to: "/admin/account", label: "Account", icon: AccountIcon },
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
        <div className="nav__brand">
          <span className="nav__brand-mark">
            <ShieldIcon width={17} height={17} />
          </span>
          Auth Admin
        </div>
        {NAV_ITEMS.map((item) => (
          <NavLink key={item.to} to={item.to} end={item.end}>
            <item.icon />
            {item.label}
          </NavLink>
        ))}
        <form onSubmit={(e) => { e.preventDefault(); signOut(); }}>
          <button type="submit" className="btn btn--secondary btn--block">
            <SignOutIcon width={16} height={16} style={{ marginRight: 6, verticalAlign: -3 }} />
            Sign out
          </button>
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
