// Fields and labels shared by "Add an application" and its Manage panel, so
// a setting reads the same in both places.

import { LinkListInput } from "../components/LinkListInput";

export const GRANT_LABELS: Record<string, string> = {
  authorization_code: "Let a person log in",
  refresh_token: "Keep them signed in without repeating login",
  client_credentials: "Talk directly to the server with no person involved",
};

export const CLIENT_TYPE_LABELS: Record<string, string> = {
  confidential: "Confidential — runs on your own server, can keep a secret safely",
  public: "Public — runs in a browser or on a device, can't keep a secret safely",
};

export type DurationUnit = "minutes" | "hours" | "days";
const UNIT_SECONDS: Record<DurationUnit, number> = { minutes: 60, hours: 3600, days: 86400 };
const DEFAULT_SESSION_TTL_SECONDS = 7 * 86400;

export function splitDuration(seconds: number): { value: string; unit: DurationUnit } {
  if (seconds <= 0) seconds = DEFAULT_SESSION_TTL_SECONDS;
  for (const unit of ["days", "hours"] as const) {
    if (seconds % UNIT_SECONDS[unit] === 0) return { value: String(seconds / UNIT_SECONDS[unit]), unit };
  }
  return { value: String(Math.round(seconds / 60)), unit: "minutes" };
}

export function durationSeconds(value: string, unit: DurationUnit): number {
  return Math.round(Number(value) * UNIT_SECONDS[unit]);
}

/** "7 days", "1 hour", "90 minutes". */
export function describeDuration(seconds: number): string {
  const { value, unit } = splitDuration(seconds);
  return `${value} ${value === "1" ? unit.slice(0, -1) : unit}`;
}

export function SessionTimeoutField({
  enabled,
  value,
  unit,
  onChange,
}: {
  enabled: boolean;
  value: string;
  unit: DurationUnit;
  onChange: (enabled: boolean, value: string, unit: DurationUnit) => void;
}) {
  return (
    <div className="field">
      <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 14 }}>
        <input type="checkbox" checked={enabled} onChange={(e) => onChange(e.target.checked, value, unit)} />
        Make people log in again after a set time
      </label>
      {enabled && (
        <div style={{ display: "flex", gap: 8 }}>
          <input
            aria-label="Sign-in lasts"
            type="number"
            min={1}
            required
            style={{ maxWidth: 120 }}
            value={value}
            onChange={(e) => onChange(enabled, e.target.value, unit)}
          />
          <select
            aria-label="Unit"
            style={{ maxWidth: 140 }}
            value={unit}
            onChange={(e) => onChange(enabled, value, e.target.value as DurationUnit)}
          >
            <option value="minutes">minutes</option>
            <option value="hours">hours</option>
            <option value="days">days</option>
          </select>
        </div>
      )}
      <span className="field__hint">
        {enabled
          ? "Counted from when the person last entered their password or passkey. After that they must log in again, even if the app keeps them signed in. Between 5 minutes and 30 days."
          : "Off: no limit of its own — the standard rules apply. Recommended for AI assistants, MCP clients and APIs, which would otherwise have to reconnect."}
      </span>
    </div>
  );
}

export function PostLogoutUrisField({ value, onChange }: { value: string; onChange: (value: string) => void }) {
  return (
    <div className="field">
      <label htmlFor="post_logout_uris">
        After-logout URLs <span className="field__hint">(optional)</span>
      </label>
      <LinkListInput id="post_logout_uris" placeholder="https://yourapp.com/signed-out" value={value} onChange={onChange} />
      <span className="field__hint">
        Where the logout endpoint may send the browser back to. Only needed if the app logs
        people out by redirecting their browser.
      </span>
    </div>
  );
}

export function EmbedOriginsField({ value, onChange }: { value: string; onChange: (value: string) => void }) {
  return (
    <div className="field">
      <label htmlFor="embed_origins">
        Embed origins <span className="field__hint">(optional)</span>
      </label>
      <LinkListInput id="embed_origins" placeholder="https://yourapp.com" value={value} onChange={onChange} />
      <span className="field__hint">
        Sites allowed to show this app's sign-in inside their own pages, styled to match them
        (auth-elements.js). Just the origin — no path. Leave empty to keep sign-in on its own page.
      </span>
    </div>
  );
}

const QUICK_REDIRECTS = [
  { label: "localhost:5173", uri: "http://localhost:5173/callback" },
  { label: "127.0.0.1:8080", uri: "http://127.0.0.1:8080/callback" },
  { label: "VS Code", uri: "vscode://callback" },
];

/** One-click redirect URIs for apps on a device (mobile, CLI, AI assistant). */
export function QuickRedirects({ onAdd }: { onAdd: (uri: string) => void }) {
  return (
    <div style={{ display: "flex", gap: 5, flexWrap: "wrap" }}>
      {QUICK_REDIRECTS.map((q) => (
        <button
          key={q.uri}
          type="button"
          className="btn btn--secondary"
          style={{ height: 22, fontSize: 11, padding: "0 6px" }}
          onClick={() => onAdd(q.uri)}
        >
          + {q.label}
        </button>
      ))}
    </div>
  );
}

export function appendLine(text: string, line: string): string {
  return text ? `${text}\n${line}` : line;
}
