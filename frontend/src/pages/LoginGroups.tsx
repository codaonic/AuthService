import { FormEvent, useEffect, useMemo, useState } from "react";
import { Modal } from "../components/Modal";
import { Badge } from "../components/Badge";
import { Menu } from "../components/Menu";
import { EmptyState } from "../components/EmptyState";
import { useConfirmDialog } from "../components/ConfirmDialog";
import { useToast } from "../components/ToastProvider";
import { AppsIcon, ChevronIcon, GroupsIcon, PlusIcon, UsersIcon } from "../components/Icons";
import { api, ApiError, AppUser, Client, Pool, UserPage } from "../api";

function displayName(client: Client) {
  return client.client_name || client.client_id;
}

function fullName(u: AppUser) {
  return [u.first_name, u.last_name].filter(Boolean).join(" ");
}

// ── Individual pool card ──────────────────────────────────────────────────────

const APPS_VISIBLE = 3;
const USERS_VISIBLE = 4;

function PoolCard({
  pool,
  apps,
  users,
  onAddApp,
  onRemoveApp,
  onToggleUser,
  onDeleteUser,
}: {
  pool: Pool;
  apps: Client[];
  users: AppUser[];
  onAddApp: () => void;
  onRemoveApp: (c: Client) => void;
  onToggleUser: (u: AppUser) => void;
  onDeleteUser: (u: AppUser) => void;
}) {
  const [open, setOpen] = useState(false);
  const [appsOpen, setAppsOpen] = useState(true);
  const [usersOpen, setUsersOpen] = useState(true);
  const [appsExpanded, setAppsExpanded] = useState(false);
  const [usersExpanded, setUsersExpanded] = useState(false);
  const [appSearch, setAppSearch] = useState("");
  const [userSearch, setUserSearch] = useState("");

  const searchedApps = useMemo(() => {
    const q = appSearch.trim().toLowerCase();
    if (!q) return apps;
    return apps.filter(
      (c) =>
        c.client_id.toLowerCase().includes(q) ||
        (c.client_name ?? "").toLowerCase().includes(q),
    );
  }, [apps, appSearch]);

  const searchedUsers = useMemo(() => {
    const q = userSearch.trim().toLowerCase();
    if (!q) return users;
    return users.filter(
      (u) =>
        u.email.toLowerCase().includes(q) ||
        fullName(u).toLowerCase().includes(q) ||
        (u.username ?? "").toLowerCase().includes(q) ||
        (u.client_name ?? u.client_id).toLowerCase().includes(q),
    );
  }, [users, userSearch]);

  // Truncate unless expanded (search bypasses the limit)
  const filteredApps = appSearch ? searchedApps : searchedApps.slice(0, appsExpanded ? undefined : APPS_VISIBLE);
  const filteredUsers = userSearch ? searchedUsers : searchedUsers.slice(0, usersExpanded ? undefined : USERS_VISIBLE);
  const appsHidden = !appSearch && !appsExpanded && searchedApps.length > APPS_VISIBLE;
  const usersHidden = !userSearch && !usersExpanded && searchedUsers.length > USERS_VISIBLE;

  return (
    <div
      style={{
        background: "var(--surface)",
        border: "1px solid var(--border)",
        borderRadius: "var(--radius-lg)",
        overflow: "hidden",
      }}
    >
      {/* ── Group header ── */}
      <div
        style={{
          padding: "16px 20px",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          cursor: "pointer",
          userSelect: "none",
        }}
        onClick={() => setOpen((o) => !o)}
      >
        <span style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <ChevronIcon
            width={16}
            height={16}
            style={{
              transform: open ? "rotate(90deg)" : "none",
              transition: "transform 150ms",
              color: "var(--text-muted)",
              flexShrink: 0,
            }}
          />
          <span style={{ fontSize: 15, fontWeight: 600 }}>{pool.name}</span>
          <span style={{ fontWeight: 400, color: "var(--text-muted)", fontSize: 13 }}>
            {apps.length} app{apps.length === 1 ? "" : "s"} · {users.length} user{users.length === 1 ? "" : "s"}
          </span>
        </span>
        <button
          type="button"
          className="btn btn--secondary"
          onClick={(e) => {
            e.stopPropagation();
            onAddApp();
          }}
        >
          + Add application
        </button>
      </div>

      {/* ── Expandable body ── */}
      {open && (
        <div style={{ borderTop: "1px solid var(--border)", padding: "0 20px 20px" }}>

          {/* ── Applications subsection ── */}
          <div style={{ marginTop: 16 }}>
            <div
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                cursor: "pointer",
                marginBottom: appsOpen ? 10 : 0,
              }}
              onClick={() => setAppsOpen((o) => !o)}
            >
              <span style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12.5, fontWeight: 600, color: "var(--text-muted)" }}>
                <ChevronIcon
                  width={13}
                  height={13}
                  style={{ transform: appsOpen ? "rotate(90deg)" : "none", transition: "transform 150ms" }}
                />
                <AppsIcon width={14} height={14} />
                APPLICATIONS ({apps.length})
              </span>
            </div>

            {appsOpen && (
              <>
                {apps.length > 2 && (
                  <input
                    placeholder="Search applications…"
                    value={appSearch}
                    onChange={(e) => setAppSearch(e.target.value)}
                    style={{ marginBottom: 10, width: "100%", maxWidth: 320 }}
                    onClick={(e) => e.stopPropagation()}
                  />
                )}
                {apps.length === 0 ? (
                  <p className="field__hint" style={{ margin: "4px 0 0" }}>
                    No applications yet. Use "Add application" above.
                  </p>
                ) : filteredApps.length === 0 ? (
                  <p className="field__hint" style={{ margin: "4px 0 0" }}>No applications match "{appSearch}".</p>
                ) : (
                  <>
                    <div className="table-wrap" style={{ marginBottom: 4 }}>
                      <table className="table">
                        <thead>
                          <tr>
                            <th>Application</th>
                            <th>Type</th>
                            <th>Status</th>
                            <th></th>
                          </tr>
                        </thead>
                        <tbody>
                          {filteredApps.map((c) => (
                            <tr key={c.id} style={{ opacity: c.enabled ? 1 : 0.55 }}>
                              <td>
                                <div style={{ fontWeight: 500 }}>{displayName(c)}</div>
                                <div style={{ fontSize: 12, color: "var(--text-muted)" }}>{c.client_id}</div>
                              </td>
                              <td>{c.client_type}</td>
                              <td>
                                <Badge variant={c.enabled ? "success" : "neutral"}>
                                  {c.enabled ? "Active" : "Disabled"}
                                </Badge>
                              </td>
                              <td>
                                <div className="row-actions">
                                  <button
                                    type="button"
                                    className="btn btn--danger"
                                    onClick={() => onRemoveApp(c)}
                                  >
                                    Remove
                                  </button>
                                </div>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                    {appsHidden && (
                      <button type="button" className="btn btn--ghost" style={{ fontSize: 13, marginTop: 2 }} onClick={() => setAppsExpanded(true)}>
                        Show {searchedApps.length - APPS_VISIBLE} more application{searchedApps.length - APPS_VISIBLE === 1 ? "" : "s"}
                      </button>
                    )}
                    {appsExpanded && searchedApps.length > APPS_VISIBLE && (
                      <button type="button" className="btn btn--ghost" style={{ fontSize: 13, marginTop: 2 }} onClick={() => setAppsExpanded(false)}>
                        Show less
                      </button>
                    )}
                  </>
                )}
              </>
            )}
          </div>

          {/* ── Users subsection ── */}
          <div style={{ marginTop: 20 }}>
            <div
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                cursor: "pointer",
                marginBottom: usersOpen ? 10 : 0,
              }}
              onClick={() => setUsersOpen((o) => !o)}
            >
              <span style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12.5, fontWeight: 600, color: "var(--text-muted)" }}>
                <ChevronIcon
                  width={13}
                  height={13}
                  style={{ transform: usersOpen ? "rotate(90deg)" : "none", transition: "transform 150ms" }}
                />
                <UsersIcon width={14} height={14} />
                USERS ({users.length})
              </span>
            </div>

            {usersOpen && (
              <>
                {users.length > 3 && (
                  <input
                    placeholder="Search by email, name or application…"
                    value={userSearch}
                    onChange={(e) => setUserSearch(e.target.value)}
                    style={{ marginBottom: 10, width: "100%", maxWidth: 380 }}
                    onClick={(e) => e.stopPropagation()}
                  />
                )}
                {users.length === 0 ? (
                  <p className="field__hint" style={{ margin: "4px 0 0" }}>
                    No users yet. Add users from the Applications page.
                  </p>
                ) : filteredUsers.length === 0 ? (
                  <p className="field__hint" style={{ margin: "4px 0 0" }}>No users match "{userSearch}".</p>
                ) : (
                  <>
                    <div className="table-wrap">
                      <table className="table">
                        <thead>
                          <tr>
                            <th>Email</th>
                            <th>Name</th>
                            <th>Application</th>
                            <th>Status</th>
                            <th>Email verified</th>
                            <th></th>
                          </tr>
                        </thead>
                        <tbody>
                          {filteredUsers.map((u) => {
                            const name = fullName(u) || u.username || "";
                            return (
                              <tr key={u.id} style={{ opacity: u.status === "active" ? 1 : 0.55 }}>
                                <td>{u.email}</td>
                                <td style={{ fontSize: 13, color: name ? undefined : "var(--text-muted)" }}>
                                  {name || <em>—</em>}
                                </td>
                                <td style={{ fontSize: 13, color: "var(--text-muted)" }}>
                                  {u.client_name || u.client_id}
                                </td>
                                <td>
                                  <Badge variant={u.status === "active" ? "success" : "neutral"}>
                                    {u.status === "active" ? "Active" : "Disabled"}
                                  </Badge>
                                </td>
                                <td>
                                  <Badge variant={u.email_verified ? "success" : "warning"}>
                                    {u.email_verified ? "Verified" : "Unverified"}
                                  </Badge>
                                </td>
                                <td>
                                  <div className="row-actions">
                                    <button type="button" className="btn btn--secondary" onClick={() => onToggleUser(u)}>
                                      {u.status === "active" ? "Disable" : "Enable"}
                                    </button>
                                    <Menu items={[{ label: "Delete", danger: true, onSelect: () => onDeleteUser(u) }]} />
                                  </div>
                                </td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    </div>
                    {usersHidden && (
                      <button type="button" className="btn btn--ghost" style={{ fontSize: 13, marginTop: 2 }} onClick={() => setUsersExpanded(true)}>
                        Show {searchedUsers.length - USERS_VISIBLE} more user{searchedUsers.length - USERS_VISIBLE === 1 ? "" : "s"}
                      </button>
                    )}
                    {usersExpanded && searchedUsers.length > USERS_VISIBLE && (
                      <button type="button" className="btn btn--ghost" style={{ fontSize: 13, marginTop: 2 }} onClick={() => setUsersExpanded(false)}>
                        Show less
                      </button>
                    )}
                  </>
                )}
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Page ─────────────────────────────────────────────────────────────────────

export function LoginGroups() {
  const [pools, setPools] = useState<Pool[] | null>(null);
  const [clients, setClients] = useState<Client[] | null>(null);
  const [users, setUsers] = useState<AppUser[] | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [assignPool, setAssignPool] = useState<Pool | null>(null);
  const { confirm, dialog } = useConfirmDialog();
  const { show } = useToast();

  const load = () => {
    api.get<Pool[]>("/pools").then(setPools);
    api.get<Client[]>("/clients").then(setClients);
    api.get<UserPage>("/users?page_size=500").then((p) => setUsers(p.items));
  };

  useEffect(() => { load(); }, []);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await api.post("/pools", { name });
      setModalOpen(false);
      setName("");
      load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong");
    } finally {
      setSubmitting(false);
    }
  };

  const removeClientFromPool = (pool: Pool, client: Client) => {
    confirm({
      title: `Remove ${displayName(client)} from ${pool.name}?`,
      description:
        "The application becomes standalone — its users stay, but no longer share identity with the other apps in this group.",
      danger: true,
      confirmLabel: "Remove",
      onConfirm: async () => {
        await api.post(`/pools/${encodeURIComponent(pool.name)}/remove-client`, {
          client_id: client.client_id,
        });
        show(`${displayName(client)} removed from ${pool.name}`);
        load();
      },
    });
  };

  const toggleUserStatus = async (u: AppUser) => {
    await api.post(`/users/${u.id}/toggle-status`);
    load();
  };

  const removeUser = (u: AppUser) => {
    confirm({
      title: `Delete ${u.email}?`,
      description:
        "Permanently removes this account and immediately revokes all active sessions.",
      danger: true,
      confirmLabel: "Delete",
      onConfirm: async () => {
        await api.delete(`/users/${u.id}`);
        show(`${u.email} deleted`);
        load();
      },
    });
  };

  const byPool = useMemo(() => {
    const map = new Map<string, { pool: Pool; apps: Client[]; users: AppUser[] }>();
    for (const p of pools ?? []) map.set(p.name, { pool: p, apps: [], users: [] });
    for (const c of clients ?? []) {
      if (c.pool_name && map.has(c.pool_name)) map.get(c.pool_name)!.apps.push(c);
    }
    const clientToPool = new Map<string, string>();
    for (const c of clients ?? []) {
      if (c.pool_name) clientToPool.set(c.client_id, c.pool_name);
    }
    for (const u of users ?? []) {
      const pName = clientToPool.get(u.client_id);
      if (pName && map.has(pName)) map.get(pName)!.users.push(u);
    }
    return map;
  }, [pools, clients, users]);

  const standaloneClients = useMemo(
    () => (clients ?? []).filter((c) => !c.pool_name),
    [clients],
  );

  const loading = pools === null || clients === null || users === null;

  return (
    <>
      <div className="header">
        <div className="header__title-row">
          <span className="header__icon"><GroupsIcon /></span>
          <h1 className="title">Login groups</h1>
        </div>
        <button type="button" className="btn btn--primary" onClick={() => setModalOpen(true)}>
          <PlusIcon width={16} height={16} style={{ verticalAlign: -3 }} /> Create group
        </button>
      </div>

      <p className="lead">
        A <strong>login group</strong> combines applications so their users share one identity —
        sign up once and log into any of them. Applications outside a group have their own isolated
        users.
      </p>

      {!loading && byPool.size === 0 && (
        <EmptyState
          icon={<GroupsIcon width={20} height={20} />}
          title="No login groups yet"
          description="Create a group here, then assign applications to it."
          action={
            <button type="button" className="btn btn--primary" onClick={() => setModalOpen(true)}>
              <PlusIcon width={16} height={16} /> Create group
            </button>
          }
        />
      )}

      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        {Array.from(byPool.entries()).map(([poolName, { pool, apps, users: groupUsers }]) => (
          <PoolCard
            key={poolName}
            pool={pool}
            apps={apps}
            users={groupUsers}
            onAddApp={() => setAssignPool(pool)}
            onRemoveApp={(c) => removeClientFromPool(pool, c)}
            onToggleUser={toggleUserStatus}
            onDeleteUser={removeUser}
          />
        ))}
      </div>

      {modalOpen && (
        <Modal title="Create a login group" onClose={() => setModalOpen(false)}>
          <p style={{ fontSize: 13, color: "var(--text-muted)", marginTop: -8 }}>
            Create a group here, then add applications to it. Users of any app in the group can
            log into all the others.
          </p>
          {error && <div className="alert alert--error">{error}</div>}
          <form onSubmit={onSubmit}>
            <div className="field">
              <label htmlFor="name">Name</label>
              <input
                id="name"
                required
                autoFocus
                placeholder="e.g. acme-staff"
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
            </div>
            <button type="submit" className="btn btn--primary btn--block" disabled={submitting}>
              Create group
            </button>
          </form>
        </Modal>
      )}

      {assignPool && (
        <AssignAppModal
          pool={assignPool}
          availableClients={standaloneClients}
          onClose={() => setAssignPool(null)}
          onAssigned={(clientName) => {
            setAssignPool(null);
            show(`${clientName} added to ${assignPool.name}`);
            load();
          }}
        />
      )}

      {dialog}
    </>
  );
}

// ── Assign-app modal ──────────────────────────────────────────────────────────

function AssignAppModal({
  pool,
  availableClients,
  onClose,
  onAssigned,
}: {
  pool: Pool;
  availableClients: Client[];
  onClose: () => void;
  onAssigned: (clientName: string) => void;
}) {
  const [selectedId, setSelectedId] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!selectedId) return;
    setError(null);
    setSubmitting(true);
    try {
      await api.post(`/pools/${encodeURIComponent(pool.name)}/assign-client`, {
        client_id: selectedId,
      });
      const chosen = availableClients.find((c) => c.client_id === selectedId);
      onAssigned(chosen ? (chosen.client_name || chosen.client_id) : selectedId);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal title={`Add application to ${pool.name}`} onClose={onClose}>
      <p style={{ fontSize: 13, color: "var(--text-muted)", marginTop: -8 }}>
        Pick a standalone application to join this group. Its users will be able to log into all
        other apps in <strong>{pool.name}</strong>, and vice versa.
      </p>
      {availableClients.length === 0 && (
        <div className="alert alert--error" style={{ marginBottom: 12 }}>
          No standalone applications available. All existing apps are already in a group.
        </div>
      )}
      {error && <div className="alert alert--error">{error}</div>}
      <form onSubmit={onSubmit}>
        <div className="field">
          <label htmlFor="assign-app">Application</label>
          <select
            id="assign-app"
            required
            value={selectedId}
            onChange={(e) => setSelectedId(e.target.value)}
            disabled={availableClients.length === 0}
          >
            <option value="">Select an application…</option>
            {availableClients.map((c) => (
              <option key={c.id} value={c.client_id}>
                {c.client_name || c.client_id}
              </option>
            ))}
          </select>
          <span className="field__hint">
            Only standalone applications (not already in a group) are listed here.
          </span>
        </div>
        <button
          type="submit"
          className="btn btn--primary btn--block"
          disabled={submitting || !selectedId || availableClients.length === 0}
        >
          Add to group
        </button>
      </form>
    </Modal>
  );
}
