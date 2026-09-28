import { useEffect, useState } from "react";
import { api, DashboardData } from "../api";
import { ActivityIcon, AppsIcon, DashboardIcon, GroupsIcon, ResourcesIcon, UsersIcon } from "../components/Icons";

const STAT_META: Record<string, { label: string; icon: typeof AppsIcon; accent: string; soft: string }> = {
  clients: { label: "Applications", icon: AppsIcon, accent: "#4f46e5", soft: "rgba(79, 70, 229, 0.12)" },
  users: { label: "Users", icon: UsersIcon, accent: "#16a34a", soft: "rgba(22, 163, 74, 0.12)" },
  pools: { label: "Login groups", icon: GroupsIcon, accent: "#d97706", soft: "rgba(217, 119, 6, 0.12)" },
  resources: { label: "Resources", icon: ResourcesIcon, accent: "#0891b2", soft: "rgba(8, 145, 178, 0.12)" },
};

export function Dashboard() {
  const [data, setData] = useState<DashboardData | null>(null);

  useEffect(() => {
    api.get<DashboardData>("/dashboard").then(setData);
  }, []);

  if (!data) return null;

  return (
    <>
      <div className="header">
        <div className="header__title-row">
          <span className="header__icon">
            <DashboardIcon />
          </span>
          <h1 className="title">Dashboard</h1>
        </div>
      </div>

      <div className="stats">
        {Object.entries(data.counts).map(([key, value]) => {
          const meta = STAT_META[key];
          return (
            <div className="stat" key={key} style={{ ["--stat-accent" as string]: meta?.accent, ["--stat-accent-soft" as string]: meta?.soft }}>
              {meta && (
                <span className="stat__icon">
                  <meta.icon width={17} height={17} />
                </span>
              )}
              <p className="stat__value">{value}</p>
              <p className="stat__label">{meta?.label ?? key}</p>
            </div>
          );
        })}
      </div>

      <h2 style={{ fontSize: 15, margin: "32px 0 12px", display: "flex", alignItems: "center", gap: 8 }}>
        <ActivityIcon width={16} height={16} />
        Recent activity
      </h2>
      <table className="table">
        <thead>
          <tr>
            <th>Time</th>
            <th>Event</th>
            <th>Details</th>
          </tr>
        </thead>
        <tbody>
          {data.recent.length === 0 && (
            <tr>
              <td colSpan={3}>Nothing yet.</td>
            </tr>
          )}
          {data.recent.map((event, i) => (
            <tr key={i}>
              <td style={{ whiteSpace: "nowrap" }}>{event.time}</td>
              <td>{event.event}</td>
              <td style={{ color: "var(--color-text-secondary)", fontSize: 12.5 }}>
                {Object.entries(event.extra)
                  .map(([k, v]) => `${k}=${v}`)
                  .join(" ")}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}
