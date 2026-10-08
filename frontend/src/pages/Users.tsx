import { Fragment, FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { Modal } from "../components/Modal";
import { Badge } from "../components/Badge";
import { Menu } from "../components/Menu";
import { useConfirmDialog } from "../components/ConfirmDialog";
import { useToast } from "../components/ToastProvider";
import { PasswordInput } from "../components/PasswordInput";
import { ChevronIcon, PlusIcon, UsersIcon } from "../components/Icons";
import { api, ApiError, AppUser, Client, UserPage } from "../api";

function displayName(c: Client) {
  return c.client_name || c.client_id;
}

const PAGE_SIZE = 50;

export function Users() {
  const [page, setPage] = useState<UserPage | null>(null);
  const [currentPage, setCurrentPage] = useState(1);
  const [clients, setClients] = useState<Client[]>([]);
  const [search, setSearch] = useState("");
  const [clientFilter, setClientFilter] = useState("");
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [modalOpen, setModalOpen] = useState(false);
  const [email, setEmail] = useState("");
  const [username, setUsername] = useState("");
  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [phone, setPhone] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [emailVerified, setEmailVerified] = useState(true);
  const [selectedClientId, setSelectedClientId] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [editing, setEditing] = useState<AppUser | null>(null);
  const [editEmail, setEditEmail] = useState("");
  const [editUsername, setEditUsername] = useState("");
  const [editFirstName, setEditFirstName] = useState("");
  const [editLastName, setEditLastName] = useState("");
  const [editPhone, setEditPhone] = useState("");
  const [editClientId, setEditClientId] = useState("");
  const [editError, setEditError] = useState<string | null>(null);
  const [editSubmitting, setEditSubmitting] = useState(false);
  const { confirm, dialog } = useConfirmDialog();
  const { show } = useToast();

  const load = (q = search, cid = clientFilter, pg = currentPage) => {
    const params = new URLSearchParams({ page: String(pg), page_size: String(PAGE_SIZE) });
    if (q.trim()) params.set("search", q.trim());
    if (cid) params.set("client", cid);
    api.get<UserPage>(`/users?${params}`).then(setPage);
  };

  // Debounced search — fires 350 ms after the user stops typing.
  const onSearchChange = (value: string) => {
    setSearch(value);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      setCurrentPage(1);
      load(value, clientFilter, 1);
    }, 350);
  };

  const onClientChange = (value: string) => {
    setClientFilter(value);
    setCurrentPage(1);
    load(search, value, 1);
  };

  useEffect(() => {
    load();
    api.get<Client[]>("/clients").then(setClients);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Group accounts by email within the current page.
  const grouped = useMemo(() => {
    const map = new Map<string, AppUser[]>();
    for (const u of page?.items ?? []) {
      if (!map.has(u.email)) map.set(u.email, []);
      map.get(u.email)!.push(u);
    }
    return map;
  }, [page]);

  const toggleExpanded = (email: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(email)) next.delete(email);
      else next.add(email);
      return next;
    });
  };

  const goToPage = (pg: number) => {
    setCurrentPage(pg);
    load(search, clientFilter, pg);
  };

  const onCreate = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    if (password !== confirmPassword) {
      setError("Passwords do not match");
      return;
    }
    if (!selectedClientId.trim()) {
      setError("Please select an application");
      return;
    }
    setSubmitting(true);
    try {
      await api.post("/users", {
        email,
        username: username.trim() || null,
        first_name: firstName.trim() || null,
        last_name: lastName.trim() || null,
        phone: phone.trim() || null,
        password,
        confirm_password: confirmPassword,
        client_id: selectedClientId.trim(),
        email_verified: emailVerified,
      });
      setModalOpen(false);
      setEmail("");
      setUsername("");
      setFirstName("");
      setLastName("");
      setPhone("");
      setPassword("");
      setConfirmPassword("");
      setSelectedClientId("");
      setCurrentPage(1);
      load(search, clientFilter, 1);
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
      await api.patch(`/users/${editing.id}`, {
        email: editEmail,
        username: editUsername.trim() || null,
        first_name: editFirstName.trim() || null,
        last_name: editLastName.trim() || null,
        phone: editPhone.trim() || null,
        client_id: editClientId.trim(),
      });
      setEditing(null);
      show(
        editClientId.trim() && editClientId.trim() !== editing.client_id
          ? `Moved to ${editClientId.trim()} — they've been signed out everywhere`
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

      <div style={{ display: "flex", gap: 8, marginBottom: 16, flexWrap: "wrap" }}>
        <input
          placeholder="Search by email, name or username…"
          value={search}
          onChange={(e) => onSearchChange(e.target.value)}
          style={{ flex: "1 1 220px", maxWidth: 340 }}
        />
        <select
          value={clientFilter}
          onChange={(e) => onClientChange(e.target.value)}
          style={{ flex: "1 1 160px", maxWidth: 240 }}
        >
          <option value="">All applications</option>
          {clients.map((c) => (
            <option key={c.id} value={c.client_id}>{displayName(c)}</option>
          ))}
        </select>
        {(search || clientFilter) && (
          <button
            type="button"
            className="btn btn--ghost"
            onClick={() => { setSearch(""); setClientFilter(""); setCurrentPage(1); load("", "", 1); }}
          >
            Clear
          </button>
        )}
      </div>

      <div className="table-wrap">
      <table className="table">
        <thead>
          <tr>
            <th>Email</th>
            <th>Name</th>
            <th>Applications</th>
            <th>Status</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {page === null && (
            <tr><td colSpan={5} style={{ color: "var(--text-muted)" }}>Loading…</td></tr>
          )}
          {page !== null && grouped.size === 0 && (
            <tr>
              <td colSpan={5}>No users yet.</td>
            </tr>
          )}
          {Array.from(grouped.entries()).map(([userEmail, accounts]) => {
            const isOpen = expanded.has(userEmail);
            const activeCount = accounts.filter((a) => a.status === "active").length;
            // Show first account's name/username as summary (all accounts share the same person).
            const first = accounts[0];
            const displayFullName = [first.first_name, first.last_name].filter(Boolean).join(" ");
            return (
              <Fragment key={userEmail}>
                <tr className="table-row--expandable" onClick={() => toggleExpanded(userEmail)}>
                  <td style={{ fontWeight: 600 }}>{userEmail}</td>
                  <td style={{ fontSize: 13, color: displayFullName || first.username ? undefined : "var(--text-muted)" }}>
                    {displayFullName || first.username || <em>—</em>}
                  </td>
                  <td>
                    {accounts.length} application{accounts.length === 1 ? "" : "s"}
                  </td>
                  <td>
                    <Badge variant={activeCount > 0 ? "success" : "neutral"}>
                      {activeCount === accounts.length
                        ? "Active"
                        : activeCount === 0
                        ? "Disabled everywhere"
                        : `Active in ${activeCount} of ${accounts.length}`}
                    </Badge>
                  </td>
                  <td>
                    <button
                      type="button"
                      className="table-row__toggle"
                      aria-label={isOpen ? "Collapse" : "Expand"}
                      aria-expanded={isOpen}
                      onClick={(e) => {
                        e.stopPropagation();
                        toggleExpanded(userEmail);
                      }}
                    >
                      <ChevronIcon
                        width={16}
                        height={16}
                        style={{ transform: isOpen ? "rotate(90deg)" : "none", transition: "transform 120ms" }}
                      />
                    </button>
                  </td>
                </tr>
                {isOpen && (
                  <tr key={`${userEmail}-expanded`}>
                    <td colSpan={5} className="table-row__detail">
                      <div className="table-row__detail-inner">
                      <table className="table table--nested">
                        <thead>
                          <tr>
                            <th>Application</th>
                            <th>Login group</th>
                            <th>Status</th>
                            <th>Email verified</th>
                            <th></th>
                          </tr>
                        </thead>
                        <tbody>
                          {accounts.map((u) => (
                            <tr key={u.id} style={{ opacity: u.status === "active" ? 1 : 0.55 }}>
                              <td style={{ fontWeight: 500 }}>{u.client_name || u.client_id}</td>
                              <td style={{ fontSize: 13, color: "var(--text-muted)" }}>
                                {u.pool_name ?? <span style={{ color: "var(--text-muted)" }}>Standalone</span>}
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
                                  <button
                                    type="button"
                                    className="btn btn--secondary"
                                    onClick={() => {
                                      setEditEmail(u.email);
                                      setEditUsername(u.username ?? "");
                                      setEditFirstName(u.first_name ?? "");
                                      setEditLastName(u.last_name ?? "");
                                      setEditPhone(u.phone ?? "");
                                      setEditClientId("");
                                      setEditError(null);
                                      setEditing(u);
                                    }}
                                  >
                                    Edit
                                  </button>
                                  <button
                                    type="button"
                                    className="btn btn--secondary"
                                    onClick={() => toggleStatus(u.id)}
                                  >
                                    {u.status === "active" ? "Disable" : "Enable"}
                                  </button>
                                  <Menu
                                    items={[
                                      { label: "Sign out everywhere", onSelect: () => signOut(u.id) },
                                      { label: "Send password reset", onSelect: () => sendReset(u.id) },
                                      {
                                        label: "Delete",
                                        danger: true,
                                        onSelect: () =>
                                          confirm({
                                            title: `Delete ${u.email} in ${u.client_name || u.client_id}?`,
                                            description:
                                              "Permanently removes this account and immediately revokes all active sessions.",
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
                    </td>
                  </tr>
                )}
              </Fragment>
            );
          })}
        </tbody>
      </table>
      </div>

      {/* Pagination */}
      {page && page.pages > 1 && (
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginTop: 12, flexWrap: "wrap", gap: 8 }}>
          <span style={{ fontSize: 13, color: "var(--text-muted)" }}>
            {((page.page - 1) * page.page_size) + 1}–{Math.min(page.page * page.page_size, page.total)} of {page.total.toLocaleString()} users
          </span>
          <div style={{ display: "flex", gap: 4, alignItems: "center" }}>
            <button
              className="btn btn--secondary"
              disabled={page.page <= 1}
              onClick={() => goToPage(page.page - 1)}
            >← Prev</button>
            {Array.from({ length: page.pages }, (_, i) => i + 1)
              .filter((p) => p === 1 || p === page.pages || Math.abs(p - page.page) <= 2)
              .reduce<(number | "…")[]>((acc, p, idx, arr) => {
                if (idx > 0 && p - (arr[idx - 1] as number) > 1) acc.push("…");
                acc.push(p);
                return acc;
              }, [])
              .map((p, i) =>
                p === "…" ? (
                  <span key={`ellipsis-${i}`} style={{ padding: "0 4px", color: "var(--text-muted)" }}>…</span>
                ) : (
                  <button
                    key={p}
                    className={`btn ${p === page.page ? "btn--primary" : "btn--secondary"}`}
                    style={{ minWidth: 36 }}
                    onClick={() => goToPage(p as number)}
                  >{p}</button>
                )
              )}
            <button
              className="btn btn--secondary"
              disabled={page.page >= page.pages}
              onClick={() => goToPage(page.page + 1)}
            >Next →</button>
          </div>
        </div>
      )}
      {page && page.pages <= 1 && page.total > 0 && (
        <p style={{ fontSize: 13, color: "var(--text-muted)", marginTop: 8 }}>
          {page.total.toLocaleString()} user{page.total === 1 ? "" : "s"} total
        </p>
      )}

      <p className="field__hint" style={{ marginTop: 12 }}>
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
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0 12px" }}>
              <div className="field">
                <label htmlFor="add-first-name">First name</label>
                <input id="add-first-name" value={firstName} onChange={(e) => setFirstName(e.target.value)} />
              </div>
              <div className="field">
                <label htmlFor="add-last-name">Last name</label>
                <input id="add-last-name" value={lastName} onChange={(e) => setLastName(e.target.value)} />
              </div>
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0 12px" }}>
              <div className="field">
                <label htmlFor="add-username">Username</label>
                <input id="add-username" value={username} onChange={(e) => setUsername(e.target.value)} />
              </div>
              <div className="field">
                <label htmlFor="add-phone">Phone <span style={{ fontWeight: 400, color: "var(--text-muted)" }}>(optional)</span></label>
                <input id="add-phone" type="tel" value={phone} onChange={(e) => setPhone(e.target.value)} />
              </div>
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
              <label htmlFor="add-client">Application</label>
              <select
                id="add-client"
                required
                value={selectedClientId}
                onChange={(e) => setSelectedClientId(e.target.value)}
              >
                <option value="">Select an application…</option>
                {clients.map((c) => (
                  <option key={c.id} value={c.client_id}>{displayName(c)}</option>
                ))}
              </select>
              <span className="field__hint">
                The user will be added to this application. If it belongs to a login group,
                they'll also be able to log into all other apps in that group.
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
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0 12px" }}>
              <div className="field">
                <label htmlFor="edit-first-name">First name</label>
                <input id="edit-first-name" value={editFirstName} onChange={(e) => setEditFirstName(e.target.value)} />
              </div>
              <div className="field">
                <label htmlFor="edit-last-name">Last name</label>
                <input id="edit-last-name" value={editLastName} onChange={(e) => setEditLastName(e.target.value)} />
              </div>
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0 12px" }}>
              <div className="field">
                <label htmlFor="edit-username">Username</label>
                <input id="edit-username" value={editUsername} onChange={(e) => setEditUsername(e.target.value)} />
              </div>
              <div className="field">
                <label htmlFor="edit-phone">Phone <span style={{ fontWeight: 400, color: "var(--text-muted)" }}>(optional)</span></label>
                <input id="edit-phone" type="tel" value={editPhone} onChange={(e) => setEditPhone(e.target.value)} />
              </div>
            </div>
            <div className="field">
              <label htmlFor="edit-client">Application</label>
              <select
                id="edit-client"
                value={editClientId}
                onChange={(e) => setEditClientId(e.target.value)}
              >
                <option value="">Keep current ({editing.client_name || editing.client_id})</option>
                {clients.map((c) => (
                  <option key={c.id} value={c.client_id}>{displayName(c)}</option>
                ))}
              </select>
              <span className="field__hint">
                Moving them to a different application signs them out everywhere.
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
