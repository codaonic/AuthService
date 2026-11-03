import { AuditEvent } from "../api";
import { eventDetails, eventLabel } from "../events";
import { OutcomeTag } from "./charts";

function dayHeading(ts: number): string {
  const d = new Date(ts * 1000);
  const today = new Date();
  const yesterday = new Date();
  yesterday.setDate(today.getDate() - 1);
  if (d.toDateString() === today.toDateString()) return "Today";
  if (d.toDateString() === yesterday.toDateString()) return "Yesterday";
  return d.toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric" });
}

const timeOf = (ts: number) => new Date(ts * 1000).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });

/** Events grouped under the day they happened, newest first, in local time. */
export function ActivityList({ events, compact }: { events: AuditEvent[]; compact?: boolean }) {
  const groups: { heading: string; events: AuditEvent[] }[] = [];
  for (const e of events) {
    const heading = dayHeading(e.ts);
    if (groups[groups.length - 1]?.heading !== heading) groups.push({ heading, events: [] });
    groups[groups.length - 1].events.push(e);
  }

  return (
    <div className={`activity${compact ? " activity--compact" : ""}`}>
      {groups.map((g) => (
        <section key={g.heading} className="activity__day">
          <h3 className="activity__heading">{g.heading}</h3>
          <ol className="activity__list">
            {g.events.map((e, i) => {
              const details = eventDetails(e.extra);
              return (
                <li key={e.id ?? `${e.ts}-${i}`} className="activity__item">
                  <time className="activity__time" dateTime={new Date(e.ts * 1000).toISOString()} title={e.time}>
                    {timeOf(e.ts)}
                  </time>
                  <OutcomeTag outcome={e.outcome} />
                  <div className="activity__body">
                    <span className="activity__event">
                      {eventLabel(e.event)}
                      {e.event === "email_link_held" && (
                        <span className="activity__note"> The link is waiting on the Dashboard.</span>
                      )}
                    </span>
                    {details.length > 0 && (
                      <dl className="activity__details">
                        {(compact ? details.slice(0, 2) : details).map((d) => (
                          <div key={d.label}>
                            <dt>{d.label}</dt>
                            <dd title={d.value}>{d.value}</dd>
                          </div>
                        ))}
                      </dl>
                    )}
                  </div>
                </li>
              );
            })}
          </ol>
        </section>
      ))}
    </div>
  );
}
