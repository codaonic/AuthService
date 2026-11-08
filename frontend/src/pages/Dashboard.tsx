import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, AuditEvent, DashboardData, HeldEmailLink } from "../api";
import { LiveIndicator, useDebounced, useLiveEvents } from "../live";
import { ActivityList } from "../components/ActivityList";
import { DailyChart, OutcomeTotals } from "../components/charts";
import { useToast } from "../components/ToastProvider";
import { AppsIcon, ChevronIcon, DashboardIcon, GroupsIcon, MailIcon, ResourcesIcon, UsersIcon } from "../components/Icons";

const STAT_META: Record<string, { label: string; icon: typeof AppsIcon; accent: string; soft: string; to: string }> = {
  clients: { label: "Applications", icon: AppsIcon, accent: "#4f46e5", soft: "rgba(79, 70, 229, 0.12)", to: "/admin/clients" },
  users: { label: "Users", icon: UsersIcon, accent: "#16a34a", soft: "rgba(22, 163, 74, 0.12)", to: "/admin/users" },
  pools: { label: "Login groups", icon: GroupsIcon, accent: "#d97706", soft: "rgba(217, 119, 6, 0.12)", to: "/admin/pools" },
  resources: { label: "APIs & MCP servers", icon: ResourcesIcon, accent: "#0891b2", soft: "rgba(8, 145, 178, 0.12)", to: "/admin/resources" },
};

const KIND_LABELS: Record<HeldEmailLink["kind"], string> = {
  password_reset: "Password reset",
  email_verification: "Email verification",
};

// Events after which the list of unsent email links may have changed.
const LINK_EVENTS = new Set(["email_link_held", "email_verified", "password_reset_completed"]);

// Events that change one of the counts at the top.
const changesCounts = (event: string) =>
  event === "signup_success" || /^(client|pool|resource|user)_(created|registered|deleted)$/.test(event);

/** Counts a live event into the last-7-days numbers. */
function addToWeek(week: DashboardData["week"], e: AuditEvent): DashboardData["week"] {
  const day = Math.floor(e.ts / 86400) * 86400;
  const series = week.series.some((d) => d.day === day)
    ? week.series
    : [...week.series.slice(1), { day, success: 0, warning: 0, error: 0 }];
  return {
    totals: { ...week.totals, [e.outcome]: week.totals[e.outcome] + 1 },
    series: series.map((d) => (d.day === day ? { ...d, [e.outcome]: d[e.outcome] + 1 } : d)),
  };
}

function expiresIn(expires: number): string {
  const minutes = Math.max(0, Math.round((expires * 1000 - Date.now()) / 60000));
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.round(minutes / 60);
  return `${hours} hour${hours === 1 ? "" : "s"}`;
}

export function Dashboard() {
  const [data, setData] = useState<DashboardData | null>(null);

  // Everything on this page comes from one request...
  const load = () => api.get<DashboardData>("/dashboard").then(setData);
  useEffect(() => {
    load();
  }, []);

  // ...and then stays current as things happen, without a refresh.
  const reloadSoon = useDebounced(() => load(), 800);
  useLiveEvents((m) => {
    if (m === "resync") return void load();
    if (changesCounts(m.event)) return void reloadSoon();
    setData((d) => d && { ...d, recent: [m, ...d.recent.filter((e) => e.id !== m.id)].slice(0, 8), week: addToWeek(d.week, m) });
    if (LINK_EVENTS.has(m.event)) {
      api.get<DashboardData["email_links"]>("/email-links").then((links) => setData((d) => d && { ...d, email_links: links }));
    }
  });

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
        <LiveIndicator />
      </div>

      {data.email_links.links.length > 0 && (
        <HeldLinks
          smtpConfigured={data.email_links.smtp_configured}
          links={data.email_links.links}
          onDismissed={(id) =>
            setData((d) => d && { ...d, email_links: { ...d.email_links, links: d.email_links.links.filter((l) => l.id !== id) } })
          }
        />
      )}

      <div className="stats">
        {Object.entries(data.counts).map(([key, value]) => {
          const meta = STAT_META[key];
          return (
            <Link
              to={meta?.to ?? "/admin"}
              className="stat"
              key={key}
              style={{ ["--stat-accent" as string]: meta?.accent, ["--stat-accent-soft" as string]: meta?.soft }}
            >
              {meta && (
                <span className="stat__icon">
                  <meta.icon width={17} height={17} />
                </span>
              )}
              <p className="stat__value">{value}</p>
              <p className="stat__label">{meta?.label ?? key}</p>
            </Link>
          );
        })}
      </div>

      {data.counts.clients === 0 && (
        <section className="panel panel--onboarding">
          <div>
            <h2 className="panel__title">Connect your first application</h2>
            <p className="panel__hint">
              Add the website, app or AI assistant that should let people log in, and get ready-to-copy code.
            </p>
          </div>
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
            <Link to="/admin/resources" className="btn btn--secondary">
              Register an API or MCP server
            </Link>
            <Link to="/admin/clients" className="btn btn--primary">
              Add an application
            </Link>
          </div>
        </section>
      )}

      <div className="dashboard__split">
        <section className="panel">
          <div className="panel__head">
            <h2 className="panel__title">Last 7 days</h2>
            <Link to="/admin/analytics" className="panel__link">
              Open analytics
            </Link>
          </div>
          <OutcomeTotals totals={data.week.totals} />
          <DailyChart series={data.week.series} height={160} label="Events per day over the last 7 days, by outcome" />
        </section>

        <section className="panel">
          <div className="panel__head">
            <h2 className="panel__title">Recent activity</h2>
            <Link to="/admin/audit" className="panel__link">
              See all activity
            </Link>
          </div>
          {data.recent.length === 0 ? (
            <p className="chart-empty">Nothing yet. Sign-ins and changes will show up here.</p>
          ) : (
            <ActivityList events={data.recent} compact />
          )}
        </section>
      </div>
    </>
  );
}

function HeldLinks({
  smtpConfigured,
  links,
  onDismissed,
}: {
  smtpConfigured: boolean;
  links: HeldEmailLink[];
  onDismissed: (id: string) => void;
}) {
  const { show } = useToast();
  // Each link is one short line; its details and actions open below it.
  const [open, setOpen] = useState<string | null>(null);

  const copy = async (link: HeldEmailLink) => {
    try {
      await navigator.clipboard.writeText(link.link);
      show(`Link for ${link.email} copied`);
    } catch {
      show("Couldn't copy -- your browser blocked clipboard access", "error");
    }
  };

  const dismiss = async (link: HeldEmailLink) => {
    await api.delete(`/email-links/${link.id}`);
    onDismissed(link.id);
  };

  // One card per waiting link: what it is, who it's for and its actions on
  // one row; the arrow opens why it's waiting and when it expires.
  return (
    <section className="held-links" aria-label={links.length === 1 ? "1 email couldn't be sent" : `${links.length} emails couldn't be sent`}>
      {links.map((l) => {
        const expanded = open === l.id;
        return (
          <article key={l.id} className={`held-card${expanded ? " is-open" : ""}`}>
            <div className="held-card__row">
              <span className="held-card__icon" aria-hidden="true">
                <MailIcon width={15} height={15} />
              </span>
              <strong className="held-card__kind">{KIND_LABELS[l.kind]}</strong>
              <span className="held-card__email" title={l.email}>
                {l.email}
              </span>
              <button type="button" className="btn btn--secondary" onClick={() => copy(l)}>
                Copy link
              </button>
              <button type="button" className="btn btn--ghost" onClick={() => dismiss(l)}>
                Dismiss
              </button>
              <button
                type="button"
                className="held-card__toggle"
                aria-expanded={expanded}
                aria-controls={`held-${l.id}`}
                aria-label={expanded ? "Hide details" : "Show details"}
                onClick={() => setOpen(expanded ? null : l.id)}
              >
                <ChevronIcon width={16} height={16} />
              </button>
            </div>
            {expanded && (
              <p id={`held-${l.id}`} className="held-card__detail">
                {l.reason === "smtp_failed" || smtpConfigured
                  ? "Sending this email failed"
                  : "Email isn't set up on this server (SMTP_HOST)"}
                , so send this link to {l.email} yourself. Anyone with it can use it until it expires in{" "}
                {expiresIn(l.expires)}.
              </p>
            )}
          </article>
        );
      })}
    </section>
  );
}
