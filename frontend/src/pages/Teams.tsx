import { FormEvent, useEffect, useMemo, useState } from "react";
import { Modal } from "../components/Modal";
import { Sheet } from "../components/Sheet";
import { EmptyState } from "../components/EmptyState";
import { useConfirmDialog } from "../components/ConfirmDialog";
import { useToast } from "../components/ToastProvider";
import { CloseIcon, PlusIcon, TeamsIcon } from "../components/Icons";
import { LiveIndicator, useDebounced, useLiveEvents } from "../live";
import { api, ApiError, AppUser, Client, Team, TeamMember, UserPage } from "../api";

const appName = (clients: Client[], id: string) => {
  const c = clients.find((x) => x.client_id === id);
  return c?.client_name || id;
};

/** Teams in tree order: each parent followed by its sub-teams, with depth. */
function asTree(teams: Team[]): { team: Team; depth: number }[] {
  const children = new Map<string | null, Team[]>();
  const ids = new Set(teams.map((t) => t.id));
  for (const t of teams) {
    const parent = t.parent_id && ids.has(t.parent_id) ? t.parent_id : null;
    children.set(parent, [...(children.get(parent) ?? []), t]);
  }
  const out: { team: Team; depth: number }[] = [];
  const walk = (parent: string | null, depth: number) => {
    for (const t of children.get(parent) ?? []) {
      out.push({ team: t, depth });
      walk(t.id, depth + 1);
    }
  };
  walk(null, 0);
  return out;
}

/** The names of a team's parents, outermost first. */
function parentsOf(team: Team, teams: Team[]): Team[] {
  const byId = new Map(teams.map((t) => [t.id, t]));
  const chain: Team[] = [];
  let next = team.parent_id ? byId.get(team.parent_id) : undefined;
  while (next && !chain.includes(next)) {
    chain.unshift(next);
    next = next.parent_id ? byId.get(next.parent_id) : undefined;
  }
  return chain;
}

export function Teams() {
  const [teams, setTeams] = useState<Team[] | null>(null);
  const [clients, setClients] = useState<Client[]>([]);
  const [editing, setEditing] = useState<Team | "new" | null>(null);
  const [managing, setManaging] = useState<string | null>(null);
  const { confirm, dialog } = useConfirmDialog();
  const { show } = useToast();

  const load = () =>
    Promise.all([api.get<Team[]>("/teams").then(setTeams), api.get<Client[]>("/clients").then(setClients)]);
  useEffect(() => {
    load();
  }, []);

  const reloadSoon = useDebounced(() => load(), 500);
  useLiveEvents((m) => {
    if (m === "resync" || m.event.startsWith("team_") || /^client_(created|deleted)$/.test(m.event)) reloadSoon();
  });

  const tree = useMemo(() => asTree(teams ?? []), [teams]);
  const open = teams?.find((t) => t.id === managing) ?? null;

  const remove = (team: Team) =>
    confirm({
      title: `Delete ${team.name}?`,
      description: `${team.member_count === 1 ? "1 person loses" : `${team.member_count} people lose`} the access and roles it gives. Accounts aren't deleted.`,
      danger: true,
      confirmLabel: "Delete team",
      onConfirm: async () => {
        try {
          await api.delete(`/teams/${team.id}`);
          show(`${team.name} deleted`);
          await load();
        } catch (err) {
          show(err instanceof ApiError ? err.message : "Couldn't delete the team", "error");
        }
      },
    });

  return (
    <>
      <div className="header">
        <div className="header__title-row">
          <span className="header__icon">
            <TeamsIcon />
          </span>
          <h1 className="title">Teams</h1>
        </div>
        <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
          <LiveIndicator />
          <button type="button" className="btn btn--primary" onClick={() => setEditing("new")}>
            <PlusIcon width={16} height={16} /> Create team
          </button>
        </div>
      </div>
      <p className="lead">Give a group of people the same app access and roles in one place.</p>

      {teams === null ? (
        <p className="field__hint">Loading…</p>
      ) : teams.length === 0 ? (
        <EmptyState
          icon={<TeamsIcon width={20} height={20} />}
          title="No teams yet"
          description="For example “Support” or “Owners”."
          action={
            <button type="button" className="btn btn--primary" onClick={() => setEditing("new")}>
              <PlusIcon width={16} height={16} /> Create team
            </button>
          }
        />
      ) : (
        <div className="group-list">
          {tree.map(({ team, depth }) => {
            const parents = parentsOf(team, teams);
            const gives = team.apps.length + team.roles.length;
            return (
              <section
                key={team.id}
                className={`panel group-card team-card${depth ? " team-card--sub" : ""}`}
                style={{ ["--depth" as string]: Math.min(depth, 4) }}
                aria-labelledby={`team-${team.id}`}
              >
                <div className="group-card__head">
                  <div style={{ minWidth: 0 }}>
                    {parents.length > 0 && (
                      <p className="team-card__path">Inside {parents.map((p) => p.name).join(" › ")}</p>
                    )}
                    <h2 id={`team-${team.id}`} className="panel__title">
                      {team.name}
                    </h2>
                    <p className="group-card__sentence">
                      {team.description ||
                        (gives === 0 && parents.length === 0
                          ? "Gives nothing yet."
                          : null)}
                    </p>
                  </div>
                  <button type="button" className="group-card__people team-card__people" onClick={() => setManaging(team.id)}>
                    <strong>{team.member_count.toLocaleString()}</strong> {team.member_count === 1 ? "person" : "people"}
                  </button>
                </div>

                {gives > 0 && (
                  <dl className="team-gives">
                    {team.apps.length > 0 && (
                      <div>
                        <dt>Can sign in to</dt>
                        <dd>
                          {team.apps.map((a) => (
                            <span key={a.client_id} className="tag">
                              {a.client_name || a.client_id}
                            </span>
                          ))}
                        </dd>
                      </div>
                    )}
                    {team.roles.length > 0 && (
                      <div>
                        <dt>Roles</dt>
                        <dd>
                          {team.roles.map((r) => (
                            <span key={`${r.client_id}/${r.role}`} className="tag">
                              {appName(clients, r.client_id)}: <strong>{r.role}</strong>
                            </span>
                          ))}
                        </dd>
                      </div>
                    )}
                  </dl>
                )}

                <div className="group-card__actions">
                  <button type="button" className="btn btn--secondary" onClick={() => setManaging(team.id)}>
                    Manage
                  </button>
                  <button type="button" className="btn btn--ghost" onClick={() => setEditing(team)}>
                    Edit
                  </button>
                  <button type="button" className="btn btn--ghost" onClick={() => remove(team)}>
                    Delete
                  </button>
                </div>
              </section>
            );
          })}
        </div>
      )}

      {editing && (
        <TeamModal
          team={editing === "new" ? null : editing}
          teams={teams ?? []}
          clients={clients}
          onClose={() => setEditing(null)}
          onSaved={async (saved, created) => {
            setEditing(null);
            show(created ? `${saved.name} created` : `${saved.name} saved`);
            await load();
            if (created) setManaging(saved.id);
          }}
        />
      )}

      {open && (
        <ManageTeam
          team={open}
          parents={parentsOf(open, teams ?? [])}
          clients={clients}
          onChanged={(t) => setTeams((all) => all && all.map((x) => (x.id === t.id ? t : x)))}
          onMembersChanged={load}
          onClose={() => setManaging(null)}
        />
      )}
      {dialog}
    </>
  );
}

function TeamModal({
  team,
  teams,
  clients,
  onClose,
  onSaved,
}: {
  team: Team | null;
  teams: Team[];
  clients: Client[];
  onClose: () => void;
  onSaved: (team: Team, created: boolean) => void;
}) {
  const [name, setName] = useState(team?.name ?? "");
  const [description, setDescription] = useState(team?.description ?? "");
  const [parentId, setParentId] = useState(team?.parent_id ?? "");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  // Only when creating: what it gives, picked in the same step.
  const [appIds, setAppIds] = useState<string[]>([]);
  const [roleKeys, setRoleKeys] = useState<string[]>([]);
  const [rolesByApp, setRolesByApp] = useState<{ client: Client; roles: string[] }[]>([]);
  const restricted = clients.filter((c) => c.restrict_access);
  useEffect(() => {
    if (team) return;
    const withRoles = clients.filter((c) => c.roles_enabled);
    Promise.all(
      withRoles.map((c) => api.get<string[]>(`/clients/${encodeURIComponent(c.client_id)}/roles`).then((roles) => ({ client: c, roles }))),
    ).then((rows) => setRolesByApp(rows.filter((r) => r.roles.length > 0)));
  }, [team, clients]);
  const toggleIn = (list: string[], set: (l: string[]) => void, v: string) =>
    set(list.includes(v) ? list.filter((x) => x !== v) : [...list, v]);

  // A team can't go inside itself or its own sub-teams.
  const choices = useMemo(() => {
    if (!team) return teams;
    const blocked = new Set([team.id]);
    let grew = true;
    while (grew) {
      grew = false;
      for (const t of teams)
        if (t.parent_id && blocked.has(t.parent_id) && !blocked.has(t.id)) {
          blocked.add(t.id);
          grew = true;
        }
    }
    return teams.filter((t) => !blocked.has(t.id));
  }, [team, teams]);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setError(null);
    const body = {
      name,
      description,
      parent_id: parentId || null,
      ...(team
        ? {}
        : {
            apps: appIds,
            roles: roleKeys.map((k) => {
              const [client_id, ...rest] = k.split("\u0000");
              return { client_id, role: rest.join("") };
            }),
          }),
    };
    try {
      const saved = team ? await api.patch<Team>(`/teams/${team.id}`, body) : await api.post<Team>("/teams", body);
      onSaved(saved, !team);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal title={team ? `Edit ${team.name}` : "Create a team"} onClose={onClose}>

      {error && <div className="alert alert--error">{error}</div>}
      <form onSubmit={onSubmit}>
        <div className="field">
          <label htmlFor="team-name">Name</label>
          <input id="team-name" required autoFocus maxLength={80} placeholder="e.g. Support" value={name} onChange={(e) => setName(e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="team-description">
            Description <span className="field__hint">(optional)</span>
          </label>
          <input id="team-description" placeholder="Who belongs here" value={description} onChange={(e) => setDescription(e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="team-parent">Inside another team</label>
          <select id="team-parent" value={parentId} onChange={(e) => setParentId(e.target.value)}>
            <option value="">No, a top-level team</option>
            {choices.map((t) => (
              <option key={t.id} value={t.id}>
                {t.name}
              </option>
            ))}
          </select>
          <span className="field__hint">A sub-team gets everything its parent gives.</span>
        </div>
        {!team && restricted.length > 0 && (
          <fieldset className="field choice-chips">
            <legend>Lets them into</legend>
            <div>
              {restricted.map((c) => (
                <label key={c.client_id} className={`choice-chip${appIds.includes(c.client_id) ? " is-on" : ""}`}>
                  <input
                    type="checkbox"
                    checked={appIds.includes(c.client_id)}
                    onChange={() => toggleIn(appIds, setAppIds, c.client_id)}
                  />
                  {c.client_name || c.client_id}
                </label>
              ))}
            </div>
            <span className="field__hint">Only apps that limit who can log in are listed.</span>
          </fieldset>
        )}
        {!team && rolesByApp.length > 0 && (
          <fieldset className="field choice-chips">
            <legend>Gives these roles</legend>
            {rolesByApp.map(({ client, roles }) => (
              <div key={client.client_id} className="choice-chips__group">
                <span className="choice-chips__app">{client.client_name || client.client_id}</span>
                {roles.map((r) => {
                  const key = `${client.client_id}\u0000${r}`;
                  return (
                    <label key={key} className={`choice-chip${roleKeys.includes(key) ? " is-on" : ""}`}>
                      <input type="checkbox" checked={roleKeys.includes(key)} onChange={() => toggleIn(roleKeys, setRoleKeys, key)} />
                      {r}
                    </label>
                  );
                })}
              </div>
            ))}
          </fieldset>
        )}
        <button type="submit" className="btn btn--primary btn--block" disabled={saving}>
          {team ? "Save" : "Create team"}
        </button>
      </form>
    </Modal>
  );
}

function ManageTeam({
  team,
  parents,
  clients,
  onChanged,
  onMembersChanged,
  onClose,
}: {
  team: Team;
  parents: Team[];
  clients: Client[];
  onChanged: (team: Team) => void;
  onMembersChanged: () => void;
  onClose: () => void;
}) {
  const { show } = useToast();
  const [members, setMembers] = useState<TeamMember[] | null>(null);
  const loadMembers = () => api.get<TeamMember[]>(`/teams/${team.id}/members`).then(setMembers);
  useEffect(() => {
    loadMembers();
  }, [team.id]);

  const fail = (err: unknown) => show(err instanceof ApiError ? err.message : "Something went wrong", "error");

  const removeMember = async (m: TeamMember) => {
    try {
      await api.delete(`/teams/${team.id}/members/${m.user_id}`);
      setMembers((list) => list && list.filter((x) => x.user_id !== m.user_id));
      onMembersChanged();
    } catch (err) {
      fail(err);
    }
  };

  const changeMember = async (m: TeamMember, patch: Partial<Pick<TeamMember, "is_manager" | "expires_at">>) => {
    const next = { is_manager: m.is_manager, expires_at: m.expires_at, ...patch };
    try {
      await api.patch(`/teams/${team.id}/members/${m.user_id}`, next);
      setMembers((list) => list && list.map((x) => (x.user_id === m.user_id ? { ...x, ...next } : x)));
      show(patch.is_manager !== undefined ? (next.is_manager ? `${m.email} now manages ${team.name}` : `${m.email} no longer manages ${team.name}`) : "Saved");
    } catch (err) {
      fail(err);
    }
  };

  const change = async (call: Promise<Team>) => {
    try {
      onChanged(await call);
    } catch (err) {
      fail(err);
    }
  };

  return (
    <Sheet
      label={`Manage ${team.name}`}
      title={team.name}
      subtitle={
        parents.length ? <span className="sheet__subtitle">Inside {parents.map((p) => p.name).join(" › ")}</span> : undefined
      }
      narrow
      onClose={onClose}
    >
      <h3 className="sheet__section-title">
        People{members && members.length > 0 ? ` (${members.length})` : ""}
      </h3>
      <AddPerson
        exclude={new Set(members?.map((m) => m.user_id))}
        onAdd={async (u) => {
          try {
            await api.post(`/teams/${team.id}/members`, { user_id: u.id });
            show(`${u.email} added to ${team.name}`);
            await loadMembers();
            onMembersChanged();
          } catch (err) {
            fail(err);
          }
        }}
      />
      {members === null ? (
        <p className="field__hint">Loading…</p>
      ) : members.length === 0 ? (
        <p className="chart-empty">No one yet.</p>
      ) : (
        <ul className="team-members">
          {members.map((m) => (
            <li key={m.user_id}>
              <div style={{ minWidth: 0, flex: 1 }}>
                <strong className="team-members__name">
                  {m.name || m.email}
                  {m.is_manager && <span className="tag team-members__badge">Manager</span>}
                </strong>
                <span className="team-members__meta">
                  {m.name ? `${m.email} · ` : ""}
                  {m.pool_name ? `${m.pool_name} login group` : `${m.client_name || m.client_id} account`}
                  {m.expires_at ? ` · until ${new Date(m.expires_at).toLocaleDateString()}` : ""}
                </span>
              </div>
              <details className="team-members__more">
                <summary aria-label={`Options for ${m.email}`}>Options</summary>
                <div className="team-members__menu">
                  <label className="team-members__check">
                    <input type="checkbox" checked={m.is_manager} onChange={(e) => changeMember(m, { is_manager: e.target.checked })} />
                    Team manager
                    <span>Can add and remove people.</span>
                  </label>
                  <label className="team-members__date">
                    Ends on
                    <input
                      type="date"
                      min={new Date().toISOString().slice(0, 10)}
                      value={m.expires_at ? m.expires_at.slice(0, 10) : ""}
                      onChange={(e) =>
                        changeMember(m, { expires_at: e.target.value ? new Date(`${e.target.value}T23:59:59`).toISOString() : null })
                      }
                    />
                  </label>
                  <button type="button" className="btn btn--ghost team-members__remove" onClick={() => removeMember(m)}>
                    Remove from {team.name}
                  </button>
                </div>
              </details>
            </li>
          ))}
        </ul>
      )}
      <h3 className="sheet__section-title" style={{ marginTop: 28 }}>
        Apps
      </h3>

      <ChipList
        items={team.apps.map((a) => ({
          key: a.client_id,
          label: a.client_name || a.client_id,
          note: clients.find((c) => c.client_id === a.client_id)?.restrict_access ? undefined : "open to everyone",
          onRemove: () => change(api.delete<Team>(`/teams/${team.id}/apps/${encodeURIComponent(a.client_id)}`)),
        }))}
        empty="No apps yet."
      />
      <AddApp
        clients={clients.filter((c) => !team.apps.some((a) => a.client_id === c.client_id))}
        onAdd={(client_id) => change(api.post<Team>(`/teams/${team.id}/apps`, { client_id }))}
      />

      <h3 className="sheet__section-title" style={{ marginTop: 28 }}>
        Roles
      </h3>

      {(team.roles.length > 0 || clients.some((c) => c.roles_enabled)) && (
        <ChipList
          items={team.roles.map((r) => ({
            key: `${r.client_id}/${r.role}`,
            label: `${appName(clients, r.client_id)}: ${r.role}`,
            onRemove: () =>
              change(
                api.delete<Team>(`/teams/${team.id}/roles/${encodeURIComponent(r.client_id)}/${encodeURIComponent(r.role)}`),
              ),
          }))}
          empty="No roles yet."
        />
      )}
      <AddRole
        clients={clients.filter((c) => c.roles_enabled)}
        taken={team.roles}
        onAdd={(client_id, role) => change(api.post<Team>(`/teams/${team.id}/roles`, { client_id, role }))}
      />

    </Sheet>
  );
}

function ChipList({
  items,
  empty,
}: {
  items: { key: string; label: string; note?: string; onRemove: () => void }[];
  empty: string;
}) {
  if (items.length === 0) return <p className="chart-empty">{empty}</p>;
  return (
    <ul className="app-chips" style={{ marginTop: 0 }}>
      {items.map((i) => (
        <li key={i.key} className="app-chip" title={i.note}>
          <span>
            {i.label}
            {i.note && <span className="app-chip__note"> · {i.note}</span>}
          </span>
          <button type="button" aria-label={`Remove ${i.label}`} onClick={i.onRemove}>
            <CloseIcon width={12} height={12} />
          </button>
        </li>
      ))}
    </ul>
  );
}

function AddApp({ clients, onAdd }: { clients: Client[]; onAdd: (clientId: string) => void }) {
  const [value, setValue] = useState("");
  if (clients.length === 0) return null;
  return (
    <div className="team-add">
      <select aria-label="App to add" value={value} onChange={(e) => setValue(e.target.value)}>
        <option value="">Choose an app…</option>
        {clients.map((c) => (
          <option key={c.client_id} value={c.client_id}>
            {c.client_name || c.client_id}
            {c.restrict_access ? "" : " (open to everyone)"}
          </option>
        ))}
      </select>
      <button
        type="button"
        className="btn btn--secondary"
        disabled={!value}
        onClick={() => {
          onAdd(value);
          setValue("");
        }}
      >
        Add
      </button>
    </div>
  );
}

function AddRole({
  clients,
  taken,
  onAdd,
}: {
  clients: Client[];
  taken: Team["roles"];
  onAdd: (clientId: string, role: string) => void;
}) {
  const [clientId, setClientId] = useState("");
  const [roles, setRoles] = useState<string[]>([]);
  const [role, setRole] = useState("");

  useEffect(() => {
    setRole("");
    if (!clientId) return setRoles([]);
    api.get<string[]>(`/clients/${encodeURIComponent(clientId)}/roles`).then(setRoles);
  }, [clientId]);

  if (clients.length === 0)
    return <p className="field__hint">No app uses roles yet.</p>;
  const free = roles.filter((r) => !taken.some((t) => t.client_id === clientId && t.role === r));
  return (
    <div className="team-add">
      <select aria-label="App" value={clientId} onChange={(e) => setClientId(e.target.value)}>
        <option value="">Choose an app…</option>
        {clients.map((c) => (
          <option key={c.client_id} value={c.client_id}>
            {c.client_name || c.client_id}
          </option>
        ))}
      </select>
      <select aria-label="Role" value={role} disabled={!clientId} onChange={(e) => setRole(e.target.value)}>
        <option value="">{clientId && roles.length === 0 ? "This app has no roles yet" : "Role…"}</option>
        {free.map((r) => (
          <option key={r} value={r}>
            {r}
          </option>
        ))}
      </select>
      <button
        type="button"
        className="btn btn--secondary"
        disabled={!role}
        onClick={() => {
          onAdd(clientId, role);
          setRole("");
        }}
      >
        Add
      </button>
    </div>
  );
}

function AddPerson({ exclude, onAdd }: { exclude: Set<string>; onAdd: (u: AppUser) => void }) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<AppUser[] | null>(null);
  // Reads the latest `query` when it fires.
  const search = useDebounced(() => {
    const q = query.trim();
    if (q.length < 2) return setResults(null);
    api.get<UserPage>(`/users?${new URLSearchParams({ search: q, page_size: "8" })}`).then((p) => setResults(p.items));
  }, 250);

  return (
    <div className="team-person-search">
      <input
        type="search"
        aria-label="Find a person to add"
        autoFocus
        placeholder="Add someone: name or email"
        value={query}
        onChange={(e) => {
          setQuery(e.target.value);
          search();
        }}
      />
      {results !== null && (
        <ul className="team-person-search__results">
          {results.length === 0 ? (
            <li className="field__hint">No one matches.</li>
          ) : (
            results.map((u) => {
              const inTeam = exclude.has(u.id);
              return (
                <li key={u.id}>
                  <div style={{ minWidth: 0 }}>
                    <strong className="team-members__name">{[u.first_name, u.last_name].filter(Boolean).join(" ") || u.email}</strong>
                    <span className="team-members__meta">
                      {u.email} · {u.pool_name ? `${u.pool_name} login group` : `${u.client_name || u.client_id} account`}
                    </span>
                  </div>
                  <button type="button" className="btn btn--secondary" disabled={inTeam} onClick={() => onAdd(u)}>
                    {inTeam ? "In team" : "Add"}
                  </button>
                </li>
              );
            })
          )}
        </ul>
      )}
    </div>
  );
}
