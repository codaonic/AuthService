import { FormEvent, useEffect, useState } from "react";
import { Modal } from "../components/Modal";
import { Badge } from "../components/Badge";
import { Menu } from "../components/Menu";
import { useConfirmDialog } from "../components/ConfirmDialog";
import { useToast } from "../components/ToastProvider";
import { PasswordInput } from "../components/PasswordInput";
import { PlusIcon, UsersIcon } from "../components/Icons";
import { api, ApiError, AppUser, Pool } from "../api";

export function Users() {
  const [users, setUsers] = useState<AppUser[] | null>(null);
  const [pools, setPools] = useState<Pool[]>([]);
  const [poolFilter, setPoolFilter] = useState("");
  const [modalOpen, setModalOpen] = useState(false);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [emailVerified, setEmailVerified] = useState(true);
  // Empty, not "default" -- a pre-filled value is what the datalist below
  // matches against, so starting non-empty silently hid every other group
  // (the browser only suggests datalist entries that match the current
  // text as a prefix). Falls back to "default" on submit instead.
  const [userPool, setUserPool] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [editing, setEditing] = useState<AppUser | null>(null);
  const [editEmail, setEditEmail] = useState("");
  const [editPool, setEditPool] = useState("");
  const [editError, setEditError] = useState<string | null>(null);
  const [editSubmitting, setEditSubmitting] = useState(false);
  const { confirm, dialog } = useConfirmDialog();
  const { show } = useToast();

  const load = (pool = poolFilter) =>
    api.get<AppUser[]>(`/users${pool ? `?pool=${encodeURIComponent(pool)}` : ""}`).then(setUsers);

  useEffect(() => {
    load();
    api.get<Pool[]>("/pools").then(setPools);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const onFilter = (e: FormEvent) => {
    e.preventDefault();
    load(poolFilter);
  };

  const onCreate = async (e: FormEvent) => {
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
        user_pool: userPool.trim() || "default",
        email_verified: emailVerified,
      });
      setModalOpen(false);
      setEmail("");
      setPassword("");
      setConfirmPassword("");
      setUserPool("");
      load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong");
    } finally {
      setSubmitting(false);
    }
  };

  const toggleStatus = async (id: string) => {
    await api.post(`/users/${id}/toggle-status`);
    load();
  };

  const signOut = async (id: string) => {
    await api.post(`/users/${id}/sign-out`);
    show("Signed out everywhere");
  };

  const sendReset = async (id: string) => {
    await api.post(`/users/${id}/send-reset`);
    show("Password reset email sent");
  };

  const deleteUser = async (u: AppUser) => {
    await api.delete(`/users/${u.id}`);
    show(`${u.email} deleted`);
    load();
  };

  const onEditSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!editing) return;
    setEditSubmitting(true);
    setEditError(null);
    try {
      await api.patch(`/users/${editing.id}`, { email: editEmail, user_pool: editPool.trim() });
      setEditing(null);
      show(
        editPool.trim() && editPool.trim() !== editing.pool_name
          ? `Moved to ${editPool.trim()} — they've been signed out everywhere`
          : "Saved",
      );
      load();
    } catch (err) {
      setEditError(err instanceof ApiError ? err.message : "Something went wrong");
    } finally {
      setEditSubmitting(false);
    }
  };

  return (
    <>
      <div className="header">
        <div className="header__title-row">
          <span className="header__icon">
            <UsersIcon />
          </span>
          <h1 className="title">Users</h1>
        </div>
        <button type="button" className="btn btn--primary" onClick={() => setModalOpen(true)}>
          <PlusIcon width={16} height={16} style={{ verticalAlign: -3 }} /> Add user
        </button>
      </div>

      <form
        onSubmit={onFilter}
        style={{ display: "flex", gap: 8, marginBottom: 16, maxWidth: 360 }}
      >
        <input
          list="pool-options"
          placeholder="Filter by login group"
          value={poolFilter}
          onChange={(e) => setPoolFilter(e.target.value)}
        />
        <datalist id="pool-options">
          {pools.map((p) => (
            <option value={p.name} key={p.id} />
          ))}
        </datalist>
        <button type="submit" className="btn btn--secondary">Filter</button>
      </form>

      <div className="table-wrap">
      <table className="table">
        <thead>
          <tr>
            <th>Email</th>
            <th>Login group</th>
            <th>Status</th>
            <th>Email verified</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {users?.length === 0 && (
            <tr>
              <td colSpan={5}>No users yet.</td>
            </tr>
          )}
          {users?.map((u) => (
            <tr key={u.id} style={{ opacity: u.status === "active" ? 1 : 0.55 }}>
              <td>{u.email}</td>
              <td>{u.pool_name}</td>
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
                  <button type="button" className="btn btn--secondary" onClick={() => toggleStatus(u.id)}>
                    {u.status === "active" ? "Disable" : "Re-enable"}
                  </button>
                  <Menu
                    items={[
                      {
                        label: "Edit",
                        onSelect: () => {
                          setEditEmail(u.email);
                          setEditPool("");
                          setEditError(null);
                          setEditing(u);
                        },
                      },
                      { label: "Sign out everywhere", onSelect: () => signOut(u.id) },
                      { label: "Send password reset", onSelect: () => sendReset(u.id) },
                      {
                        label: "Delete",
                        danger: true,
                        onSelect: () =>
                          confirm({
                            title: `Delete ${u.email}?`,
                            description:
                              "Removes them from this list and immediately blocks all logins and revokes their sessions. Their history is kept, not erased — contact support if you ever need it restored.",
                            danger: true,
                            confirmLabel: "Delete",
                            onConfirm: () => deleteUser(u),
                          }),
                      },
                    ]}
                  />
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      </div>
      <p className="field__hint" style={{ marginTop: 8 }}>
        <strong>Disable</strong> blocks all sign-in and immediately revokes their active sessions
        and refresh tokens — use it for a compromised or offboarded account.{" "}
        <strong>Sign out everywhere</strong> does the same revocation without disabling the
        account, for something like a lost device.
      </p>

      {modalOpen && (
        <Modal title="Add a user" onClose={() => setModalOpen(false)}>
          <p style={{ fontSize: 13, color: "var(--text-muted)", marginTop: -8 }}>
            For applications where you've turned off self-service signup, this is how users get
            added.
          </p>
          {error && <div className="alert alert--error">{error}</div>}
          <form onSubmit={onCreate}>
            <div className="field">
              <label htmlFor="add-email">Email</label>
              <input id="add-email" type="email" required autoFocus value={email} onChange={(e) => setEmail(e.target.value)} />
            </div>
            <div className="field">
              <label htmlFor="add-password">Password</label>
              <PasswordInput
                id="add-password"
                required
                minLength={8}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </div>
            <div className="field">
              <label htmlFor="add-confirm-password">Confirm password</label>
              <PasswordInput
                id="add-confirm-password"
                required
                minLength={8}
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
              />
            </div>
            <div className="field">
              <label htmlFor="add-pool">Login group</label>
              <input
                id="add-pool"
                list="pool-options"
                placeholder="default"
                value={userPool}
                onChange={(e) => setUserPool(e.target.value)}
              />
              <span className="field__hint">
                Must match the group the application uses, so this user can log into it. Leave blank
                for the default group, or click in to see every existing group.
              </span>
            </div>
            <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 14, marginBottom: 16 }}>
              <input type="checkbox" checked={emailVerified} onChange={(e) => setEmailVerified(e.target.checked)} />
              Treat their email as already verified
            </label>
            <span className="field__hint" style={{ display: "block", marginTop: -12, marginBottom: 16 }}>
              Off: they get the same "Unverified" badge and verification email a self-signup gets.
            </span>
            <button type="submit" className="btn btn--primary btn--block" disabled={submitting}>
              Add user
            </button>
          </form>
        </Modal>
      )}

      {editing && (
        <Modal title={`Edit ${editing.email}`} onClose={() => setEditing(null)}>
          {editError && <div className="alert alert--error">{editError}</div>}
          <form onSubmit={onEditSubmit}>
            <div className="field">
              <label htmlFor="edit-email">Email</label>
              <input
                id="edit-email"
                type="email"
                required
                autoFocus
                value={editEmail}
                onChange={(e) => setEditEmail(e.target.value)}
              />
            </div>
            <div className="field">
              <label htmlFor="edit-pool">Login group</label>
              <input
                id="edit-pool"
                list="pool-options"
                placeholder={editing.pool_name}
                value={editPool}
                onChange={(e) => setEditPool(e.target.value)}
              />
              <span className="field__hint">
                Currently <strong>{editing.pool_name}</strong>. Leave blank to keep it — moving them to
                a different group signs them out everywhere and changes which apps they can log into.
              </span>
            </div>
            <button type="submit" className="btn btn--primary btn--block" disabled={editSubmitting}>
              Save
            </button>
          </form>
        </Modal>
      )}

      {dialog}
    </>
  );
}
