import { Link, NavLink, useNavigate } from "react-router-dom";
import { useAdmin } from "../AdminContext";
import { useTheme } from "../theme";
import { api } from "../api";
import {
  AccountIcon,
  ActivityIcon,
  AppsIcon,
  DashboardIcon,
  GroupsIcon,
  MoonIcon,
  ResourcesIcon,
  ShieldIcon,
  SignOutIcon,
  SunIcon,
  UsersIcon,
  WarningIcon,
} from "./Icons";

const NAV_GROUPS = [
  { label: null, items: [{ to: "/admin", label: "Dashboard", end: true, icon: DashboardIcon }] },
  {
    label: "Manage",
    items: [
      { to: "/admin/clients", label: "Applications", icon: AppsIcon },
      { to: "/admin/resources", label: "APIs & MCP servers", icon: ResourcesIcon },
      { to: "/admin/users", label: "Users", icon: UsersIcon },
      { to: "/admin/pools", label: "Login groups", icon: GroupsIcon },
    ],
  },
  {
    label: "System",
    items: [
      { to: "/admin/audit", label: "Activity log", icon: ActivityIcon },
      { to: "/admin/account", label: "Account", icon: AccountIcon },
    ],
  },
] as const;

export function Layout({ children }: { children: React.ReactNode }) {
  const { admin, setAdmin } = useAdmin();
  const { theme, toggle } = useTheme();
  const navigate = useNavigate();

  const signOut = async () => {
    await api.post("/logout");
    setAdmin(null);
    navigate("/admin/login");
  };

  const initial = admin?.email?.[0]?.toUpperCase() ?? "?";

  return (
    <div className="shell">
      <nav className="nav">
        <div className="nav__brand">
          <span className="nav__brand-mark">
            <ShieldIcon width={17} height={17} />
          </span>
          Auth Admin
        </div>

        {NAV_GROUPS.map((group, i) => (
          <div key={i}>
            {group.label && <div className="nav__group-label">{group.label}</div>}
            {group.items.map((item) => (
              <NavLink key={item.to} to={item.to} end={"end" in item ? item.end : false}>
                <item.icon />
                {item.label}
              </NavLink>
            ))}
          </div>
        ))}

        <div className="nav__footer">
          <div className="nav__account">
            <span className="nav__avatar">{initial}</span>
            <span className="nav__email" title={admin?.email}>
              {admin?.email}
            </span>
            <button
              type="button"
              className="theme-toggle"
              onClick={toggle}
              aria-label={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
            >
              {theme === "dark" ? <SunIcon width={16} height={16} /> : <MoonIcon width={16} height={16} />}
            </button>
          </div>
          <form onSubmit={(e) => { e.preventDefault(); signOut(); }}>
            <button type="submit" className="btn btn--secondary btn--block">
              <SignOutIcon width={16} height={16} /> Sign out
            </button>
          </form>
        </div>
      </nav>
      <main className="main">
        {admin?.must_change_password && (
          <div className="banner" role="alert">
            <WarningIcon width={18} height={18} />
            You're using the default admin password.
            <span className="banner__spacer" />
            <Link to="/admin/account" className="btn btn--secondary" style={{ height: 28, padding: "0 12px", fontSize: 12.5 }}>
              Change password
            </Link>
          </div>
        )}
        {children}
      </main>
    </div>
  );
}
