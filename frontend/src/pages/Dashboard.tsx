import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, DashboardData, HeldEmailLink } from "../api";
import { ActivityList } from "../components/ActivityList";
import { DailyChart, OutcomeTotals } from "../components/charts";
import { useToast } from "../components/ToastProvider";
import { AppsIcon, DashboardIcon, GroupsIcon, MailIcon, ResourcesIcon, UsersIcon } from "../components/Icons";

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

function expiresIn(expires: number): string {
  const minutes = Math.max(0, Math.round((expires * 1000 - Date.now()) / 60000));
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.round(minutes / 60);
  return `${hours} hour${hours === 1 ? "" : "s"}`;
}

export function Dashboard() {
  const [data, setData] = useState<DashboardData | null>(null);

  // Everything on this page comes from one request.
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

  return (
    <section className="panel held-links" aria-labelledby="held-links-title">
      <div className="held-links__intro">
        <span className="held-links__icon">
          <MailIcon width={18} height={18} />
        </span>
        <div>
          <h2 id="held-links-title" className="panel__title">
            {links.length === 1 ? "1 email couldn't be sent" : `${links.length} emails couldn't be sent`}
          </h2>
          <p className="panel__hint">
            {smtpConfigured
              ? "Sending failed, so these links are waiting here. "
              : "Email isn't set up (SMTP_HOST), so these links are waiting here. "}
            Send each one to the person it's for. Anyone with a link can use it until it expires.
          </p>
        </div>
      </div>
      <ul className="held-links__list">
        {links.map((l) => (
          <li key={l.id}>
            <div className="held-links__who">
              <strong>{KIND_LABELS[l.kind]}</strong>
              <span>{l.email}</span>
            </div>
            <span className="held-links__expires">Expires in {expiresIn(l.expires)}</span>
            <div className="held-links__actions">
              <button type="button" className="btn btn--secondary" onClick={() => copy(l)}>
                Copy link
              </button>
              <button type="button" className="btn btn--ghost" onClick={() => dismiss(l)}>
                Dismiss
              </button>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}
