import { useEffect, useState } from "react";
import { api, DashboardData } from "../api";

const LABELS: Record<string, string> = {
  clients: "Applications",
  users: "Users",
  pools: "Login groups",
  resources: "Resources",
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
        <h1 className="title">Dashboard</h1>
      </div>

      <div className="stats">
        {Object.entries(data.counts).map(([key, value]) => (
          <div className="stat" key={key}>
            <p className="stat__value">{value}</p>
            <p className="stat__label">{LABELS[key] ?? key}</p>
          </div>
        ))}
      </div>

      <h2 style={{ fontSize: 15, margin: "32px 0 12px" }}>Recent activity</h2>
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
