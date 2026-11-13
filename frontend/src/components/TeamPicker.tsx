import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, Team } from "../api";
import { CloseIcon } from "./Icons";

let cached: Promise<Team[]> | null = null;

/** Every team, fetched once per page and shared by every picker on it. */
export function useTeams(): Team[] | null {
  const [teams, setTeams] = useState<Team[] | null>(null);
  useEffect(() => {
    cached ??= api.get<Team[]>("/teams").finally(() => setTimeout(() => (cached = null), 5000));
    cached.then(setTeams).catch(() => setTeams([]));
  }, []);
  return teams;
}

/** What a team gives, in a few words: "Admin portal · owner". */
export function teamSummary(team: Team): string {
  const apps = team.apps.map((a) => a.client_name || a.client_id);
  const roles = team.roles.map((r) => r.role);
  return [...apps, ...roles].join(" · ");
}

/** Teams as removable chips plus a picker to add one. Choosing a team adds
 * it straight away; nothing else to press. */
export function TeamPicker({
  id,
  value,
  onChange,
  disabled,
}: {
  id?: string;
  value: string[];
  onChange: (teamIds: string[]) => void;
  disabled?: boolean;
}) {
  const teams = useTeams();
  if (teams === null) return <p className="field__hint">Loading teams…</p>;
  if (teams.length === 0)
    return (
      <p className="field__hint">
        No teams yet. <Link to="/admin/teams">Create a team</Link>
      </p>
    );

  const chosen = teams.filter((t) => value.includes(t.id));
  const rest = teams.filter((t) => !value.includes(t.id));
  return (
    <div className="team-picker">
      {chosen.length > 0 && (
        <ul className="app-chips" style={{ margin: 0 }}>
          {chosen.map((t) => (
            <li key={t.id} className="app-chip" title={teamSummary(t) || undefined}>
              <span>{t.name}</span>
              <button
                type="button"
                aria-label={`Take out of ${t.name}`}
                disabled={disabled}
                onClick={() => onChange(value.filter((v) => v !== t.id))}
              >
                <CloseIcon width={12} height={12} />
              </button>
            </li>
          ))}
        </ul>
      )}
      {rest.length > 0 && (
        <select
          id={id}
          aria-label="Add to a team"
          value=""
          disabled={disabled}
          onChange={(e) => e.target.value && onChange([...value, e.target.value])}
        >
          <option value="">Add to a team…</option>
          {rest.map((t) => (
            <option key={t.id} value={t.id}>
              {t.name}
              {teamSummary(t) ? ` (${teamSummary(t)})` : ""}
            </option>
          ))}
        </select>
      )}
    </div>
  );
}
