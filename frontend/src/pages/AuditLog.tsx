import { useEffect, useState } from "react";
import { api, AuditEvent } from "../api";

export function AuditLog() {
  const [events, setEvents] = useState<AuditEvent[] | null>(null);

  useEffect(() => {
    api.get<AuditEvent[]>("/audit").then(setEvents);
  }, []);

  return (
    <>
      <div className="header">
        <h1 className="title">Activity log</h1>
      </div>

      <table className="table">
        <thead>
          <tr>
            <th>Time</th>
            <th>Level</th>
            <th>Event</th>
            <th>Details</th>
          </tr>
        </thead>
        <tbody>
          {events?.length === 0 && (
            <tr>
              <td colSpan={4}>No activity yet.</td>
            </tr>
          )}
          {events?.map((event, i) => (
            <tr key={i}>
              <td style={{ whiteSpace: "nowrap" }}>{event.time}</td>
              <td>{event.level}</td>
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
