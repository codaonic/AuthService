import { FormEvent, useEffect, useMemo, useState } from "react";
import { Modal } from "../components/Modal";
import { Badge } from "../components/Badge";
import { Menu } from "../components/Menu";
import { PasswordInput } from "../components/PasswordInput";
import { EmptyState } from "../components/EmptyState";
import { useConfirmDialog } from "../components/ConfirmDialog";
import { useToast } from "../components/ToastProvider";
import { AppsIcon, GroupsIcon, PlusIcon, UsersIcon } from "../components/Icons";
import { api, ApiError, AppUser, Client, Pool } from "../api";

function displayName(client: Client) {
  return client.client_name || "Unnamed application";
}

export function LoginGroups() {
  const [pools, setPools] = useState<Pool[] | null>(null);
  const [clients, setClients] = useState<Client[] | null>(null);
  const [users, setUsers] = useState<AppUser[] | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [addUserPool, setAddUserPool] = useState<string | null>(null);
  const { confirm, dialog } = useConfirmDialog();
  const { show } = useToast();

  const load = () => {
    api.get<Pool[]>("/pools").then(setPools);
    api.get<Client[]>("/clients").then(setClients);
    api.get<AppUser[]>("/users").then(setUsers);
  };

  useEffect(() => {
    load();
  }, []);

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

  const toggleUserStatus = async (u: AppUser) => {
    await api.post(`/users/${u.id}/toggle-status`);
    load();
  };

  const removeUser = (u: AppUser) => {
    confirm({
      title: `Delete ${u.email}?`,
      description:
        "Removes them from this list and immediately blocks all logins and revokes their sessions. Their history is kept, not erased.",
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
    const map = new Map<string, { apps: Client[]; users: AppUser[] }>();
    for (const p of pools ?? []) map.set(p.name, { apps: [], users: [] });
    for (const c of clients ?? []) {
      if (!map.has(c.pool_name)) map.set(c.pool_name, { apps: [], users: [] });
      map.get(c.pool_name)!.apps.push(c);
    }
    for (const u of users ?? []) {
      if (!map.has(u.pool_name)) map.set(u.pool_name, { apps: [], users: [] });
      map.get(u.pool_name)!.users.push(u);
    }
    return map;
  }, [pools, clients, users]);

  const loading = pools === null || clients === null || users === null;

  return (
    <>
      <div className="header">
        <div className="header__title-row">
          <span className="header__icon">
            <GroupsIcon />
          </span>
          <h1 className="title">Login groups</h1>
        </div>
        <button type="button" className="btn btn--primary" onClick={() => setModalOpen(true)}>
          <PlusIcon width={16} height={16} style={{ verticalAlign: -3 }} /> Create group
        </button>
      </div>

      <p className="lead">
        A <strong>login group</strong> is one shared set of accounts. The applications inside it
        share logins — one account works for all of them — and a user you add to any one of them
        is added here, to the whole group, not to a single app. Click a group to expand it.
      </p>

      {!loading && byPool.size === 0 && (
        <EmptyState
          icon={<GroupsIcon width={20} height={20} />}
          title="No login groups yet"
          description="Groups are usually created automatically when you add an application — or create one ahead of time here."
          action={
            <button type="button" className="btn btn--primary" onClick={() => setModalOpen(true)}>
              <PlusIcon width={16} height={16} /> Create group
            </button>
          }
        />
      )}

      <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
        {Array.from(byPool.entries()).map(([poolName, { apps, users: groupUsers }]) => (
          <details
            key={poolName}
            open
            style={{
              background: "var(--surface)",
              border: "1px solid var(--border)",
              borderRadius: "var(--radius-lg)",
              overflow: "hidden",
            }}
          >
            <summary
              style={{
                listStyle: "none",
                cursor: "pointer",
                padding: 20,
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
              }}
            >
              <span style={{ fontSize: 15, fontWeight: 600 }}>
                {poolName}
                <span style={{ fontWeight: 400, color: "var(--text-muted)", fontSize: 13, marginLeft: 10 }}>
                  {apps.length} application{apps.length === 1 ? "" : "s"} · {groupUsers.length} user
                  {groupUsers.length === 1 ? "" : "s"}
                </span>
              </span>
              <button
                type="button"
                className="btn btn--secondary"
                onClick={(e) => {
                  e.preventDefault();
                  setAddUserPool(poolName);
                }}
              >
                + Add user
              </button>
            </summary>

            <div style={{ padding: "0 20px 20px" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12.5, fontWeight: 600, color: "var(--text-muted)", marginBottom: 8 }}>
                <AppsIcon width={14} height={14} /> APPLICATIONS ({apps.length})
              </div>
              {apps.length === 0 ? (
                <p className="field__hint" style={{ marginTop: 0 }}>No applications use this group yet.</p>
              ) : (
                <div className="table-wrap" style={{ marginBottom: 20 }}>
                  <table className="table">
                    <thead>
                      <tr>
                        <th>Application</th>
                        <th>Type</th>
                        <th>Status</th>
                      </tr>
                    </thead>
                    <tbody>
                      {apps.map((c) => (
                        <tr key={c.id} style={{ opacity: c.enabled ? 1 : 0.55 }}>
                          <td>{displayName(c)}</td>
                          <td>{c.client_type}</td>
                          <td>
                            <Badge variant={c.enabled ? "success" : "neutral"}>
                              {c.enabled ? "Active" : "Disabled"}
                            </Badge>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12.5, fontWeight: 600, color: "var(--text-muted)", marginBottom: 8 }}>
                <UsersIcon width={14} height={14} /> USERS ({groupUsers.length})
              </div>
              {groupUsers.length === 0 ? (
                <p className="field__hint" style={{ marginTop: 0 }}>No users in this group yet.</p>
              ) : (
                <div className="table-wrap">
                  <table className="table">
                    <thead>
                      <tr>
                        <th>Email</th>
                        <th>Status</th>
                        <th>Email verified</th>
                        <th></th>
                      </tr>
                    </thead>
                    <tbody>
                      {groupUsers.map((u) => (
                        <tr key={u.id} style={{ opacity: u.status === "active" ? 1 : 0.55 }}>
                          <td>{u.email}</td>
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
                              <button type="button" className="btn btn--secondary" onClick={() => toggleUserStatus(u)}>
                                {u.status === "active" ? "Disable" : "Re-enable"}
                              </button>
                              <Menu items={[{ label: "Delete", danger: true, onSelect: () => removeUser(u) }]} />
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </details>
        ))}
      </div>

      {modalOpen && (
        <Modal title="Create a login group" onClose={() => setModalOpen(false)}>
          <p style={{ fontSize: 13, color: "var(--text-muted)", marginTop: -8 }}>
            Usually unnecessary — adding an application creates its group automatically. Create one
            ahead of time only if you want to name it before any app uses it.
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

      {addUserPool && (
        <AddUserModal
          poolName={addUserPool}
          onClose={() => setAddUserPool(null)}
          onAdded={(email) => {
            setAddUserPool(null);
            show(`${email} can now log into any app in ${addUserPool}`);
            load();
          }}
        />
      )}

      {dialog}
    </>
  );
}

function AddUserModal({
  poolName,
  onClose,
  onAdded,
}: {
  poolName: string;
  onClose: () => void;
  onAdded: (email: string) => void;
}) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [emailVerified, setEmailVerified] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    if (password !== confirmPassword) {
      setError("Passwords do not match");
      return;
    }
    setSubmitting(true);
    try {
      await api.post("/users", {
        email,
        password,
        confirm_password: confirmPassword,
        user_pool: poolName,
        email_verified: emailVerified,
      });
      onAdded(email);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal title={`Add a user to ${poolName}`} onClose={onClose}>
      <p style={{ fontSize: 13, color: "var(--text-muted)", marginTop: -8 }}>
        This adds them to the whole <strong>{poolName}</strong> login group — they'll be able to
        log into every application in it, not just one.
      </p>
      {error && <div className="alert alert--error">{error}</div>}
      <form onSubmit={onSubmit}>
        <div className="field">
          <label htmlFor="group-add-email">Email</label>
          <input id="group-add-email" type="email" required autoFocus value={email} onChange={(e) => setEmail(e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="group-add-password">Password</label>
          <PasswordInput id="group-add-password" required minLength={8} value={password} onChange={(e) => setPassword(e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="group-add-confirm-password">Confirm password</label>
          <PasswordInput
            id="group-add-confirm-password"
            required
            minLength={8}
            value={confirmPassword}
            onChange={(e) => setConfirmPassword(e.target.value)}
          />
        </div>
        <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 14, marginBottom: 16 }}>
          <input type="checkbox" checked={emailVerified} onChange={(e) => setEmailVerified(e.target.checked)} />
          Treat their email as already verified
        </label>
        <button type="submit" className="btn btn--primary btn--block" disabled={submitting}>
          Add user
        </button>
      </form>
    </Modal>
  );
}
