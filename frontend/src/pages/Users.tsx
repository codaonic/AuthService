import { FormEvent, useEffect, useState } from "react";
import { Modal } from "../components/Modal";
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
  const [userPool, setUserPool] = useState("default");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

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
    setSubmitting(true);
    setError(null);
    try {
      await api.post("/users", { email, password, user_pool: userPool });
      setModalOpen(false);
      setEmail("");
      setPassword("");
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
  };

  const sendReset = async (id: string) => {
    await api.post(`/users/${id}/send-reset`);
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
                <span className={`badge ${u.status === "active" ? "badge--on" : "badge--off"}`}>
                  {u.status === "active" ? "Active" : "Disabled"}
                </span>
              </td>
              <td>
                <span className={`badge ${u.email_verified ? "badge--on" : "badge--off"}`}>
                  {u.email_verified ? "Verified" : "Unverified"}
                </span>
              </td>
              <td>
                <div className="row-actions">
                  <button type="button" className="btn btn--secondary" onClick={() => toggleStatus(u.id)}>
                    {u.status === "active" ? "Disable" : "Re-enable"}
                  </button>
                  <button type="button" className="btn btn--secondary" onClick={() => signOut(u.id)}>
                    Sign out everywhere
                  </button>
                  <button type="button" className="btn btn--secondary" onClick={() => sendReset(u.id)}>
                    Send password reset
                  </button>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="field__hint" style={{ marginTop: 8 }}>
        <strong>Disable</strong> blocks all sign-in and immediately revokes their active sessions
        and refresh tokens — use it for a compromised or offboarded account.{" "}
        <strong>Sign out everywhere</strong> does the same revocation without disabling the
        account, for something like a lost device.
      </p>

      {modalOpen && (
        <Modal title="Add a user" onClose={() => setModalOpen(false)}>
          <p style={{ fontSize: 13, color: "var(--color-text-secondary)", marginTop: -8 }}>
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
              <label htmlFor="add-pool">Login group</label>
              <input
                id="add-pool"
                list="pool-options"
                required
                value={userPool}
                onChange={(e) => setUserPool(e.target.value)}
              />
              <span className="field__hint">Must match the group the application uses, so this user can log into it.</span>
            </div>
            <button type="submit" className="btn btn--primary btn--block" disabled={submitting}>
              Add user
            </button>
          </form>
        </Modal>
      )}
    </>
  );
}
