import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Modal } from "../components/Modal";
import { Sheet } from "../components/Sheet";
import { Switch } from "../components/Switch";
import { ActivityList } from "../components/ActivityList";
import { EmptyState } from "../components/EmptyState";
import { useConfirmDialog } from "../components/ConfirmDialog";
import { useToast } from "../components/ToastProvider";
import { PasswordInput } from "../components/PasswordInput";
import { CloseIcon, PlusIcon, UsersIcon } from "../components/Icons";
import { api, ApiError, AppUser, AuditEvent, Client, UserPage } from "../api";
import { useDebounced, useLiveEvents } from "../live";

function appName(c: Client) {
  return c.client_name || c.client_id;
}

function accountApp(u: AppUser) {
  return u.client_name || u.client_id;
}

function personName(u: AppUser) {
  return [u.first_name, u.last_name].filter(Boolean).join(" ") || u.username || "";
}

const PAGE_SIZE = 50;

export function Users() {
  // Other pages link here narrowed to one login group (?pool=) or app (?client=).
  const [params, setParams] = useSearchParams();
  const pool = params.get("pool") ?? "";
  const [page, setPage] = useState<UserPage | null>(null);
  const [currentPage, setCurrentPage] = useState(1);
  const [clients, setClients] = useState<Client[]>([]);
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [clientFilter, setClientFilter] = useState(params.get("client") ?? "");
  const [addOpen, setAddOpen] = useState(false);
  const [openEmail, setOpenEmail] = useState<string | null>(null);
  const request = useRef(0);

  useEffect(() => {
    api.get<Client[]>("/clients").then(setClients);
  }, []);

  // Wait for a pause in typing instead of asking the server on every key.
  useEffect(() => {
    const t = setTimeout(() => {
      setQuery(search.trim());
      setCurrentPage(1);
    }, 300);
    return () => clearTimeout(t);
  }, [search]);

  const load = () => {
    const id = ++request.current;
    const q = new URLSearchParams({ page: String(currentPage), page_size: String(PAGE_SIZE) });
    if (query) q.set("search", query);
    if (clientFilter) q.set("client", clientFilter);
    if (pool) q.set("pool", pool);
    return api.get<UserPage>(`/users?${q}`).then((p) => {
      if (id === request.current) setPage(p);
    });
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [query, clientFilter, pool, currentPage]);

  // Stay current without a refresh: a click on a verification link shows up
  // straight away; new signups and changes from elsewhere reload this page.
  const reloadSoon = useDebounced(() => load(), 500);
  useLiveEvents((m) => {
    if (m === "resync") return void load();
    const userId = typeof m.extra.user_id === "string" ? m.extra.user_id : null;
    if (m.event === "email_verified" && userId) {
      setPage((p) => p && { ...p, items: p.items.map((u) => (u.id === userId ? { ...u, email_verified: true } : u)) });
    } else if (m.event === "signup_success" || m.event.startsWith("user_")) {
      reloadSoon();
    }
  });

  // One row per person: the same email can have an account in several apps.
  const people = useMemo(() => {
    const map = new Map<string, AppUser[]>();
    for (const u of page?.items ?? []) map.set(u.email, [...(map.get(u.email) ?? []), u]);
    return map;
  }, [page]);

  // Changes come back from the server; patch them in instead of reloading.
  const replaceAccount = (updated: AppUser) =>
    setPage((p) => p && { ...p, items: p.items.map((u) => (u.id === updated.id ? updated : u)) });

  const filtered = Boolean(query || clientFilter || pool);

  return (
    <>
      <div className="header">
        <div className="header__title-row">
          <span className="header__icon">
            <UsersIcon />
          </span>
          <h1 className="title">Users</h1>
        </div>
        <button type="button" className="btn btn--primary" onClick={() => setAddOpen(true)}>
          <PlusIcon width={16} height={16} /> Add user
        </button>
      </div>
      <p className="lead">
        Everyone who can log in to your applications. Select a person to change their details,
        stop them logging in, or see what they've been doing.
      </p>

      <div className="filter-bar">
        <input
          type="search"
          aria-label="Search people"
          placeholder="Search by email, name or username…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <select
          aria-label="Application"
          value={clientFilter}
          onChange={(e) => {
            setClientFilter(e.target.value);
            setCurrentPage(1);
          }}
        >
          <option value="">All applications</option>
          {clients.map((c) => (
            <option key={c.id} value={c.client_id}>
              {appName(c)}
            </option>
          ))}
        </select>
        {pool && (
          <span className="filter-chip">
            Login group: {pool}
            <button
              type="button"
              aria-label={`Stop showing only ${pool}`}
              onClick={() => {
                params.delete("pool");
                setParams(params);
                setCurrentPage(1);
              }}
            >
              <CloseIcon width={12} height={12} />
            </button>
          </span>
        )}
      </div>

      {page === null ? (
        <p className="field__hint">Loading…</p>
      ) : people.size === 0 ? (
        <EmptyState
          icon={<UsersIcon width={20} height={20} />}
          title={filtered ? "No one matches" : "No users yet"}
          description={
            filtered
              ? "Try another search, or show every application."
              : "People appear here when they sign up, or when you add them."
          }
          action={
            !filtered && (
              <button type="button" className="btn btn--primary" onClick={() => setAddOpen(true)}>
                <PlusIcon width={16} height={16} /> Add user
              </button>
            )
          }
        />
      ) : (
        <div className="table-wrap">
          <table className="table table--clickable">
            <thead>
              <tr>
                <th>Person</th>
                <th>Can log in to</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {Array.from(people.entries()).map(([email, accounts]) => {
                const active = accounts.filter((a) => a.status === "active");
                const name = personName(accounts[0]);
                return (
                  <tr
                    key={email}
                    tabIndex={0}
                    aria-label={`Open ${email}`}
                    onClick={() => setOpenEmail(email)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        setOpenEmail(email);
                      }
                    }}
                  >
                    <td>
                      <div style={{ fontWeight: 600 }}>{name || email}</div>
                      {name && <div className="cell-sub">{email}</div>}
                    </td>
                    <td>
                      {active.length ? (
                        active.map(accountApp).join(", ")
                      ) : (
                        <span style={{ color: "var(--text-muted)" }}>No applications</span>
                      )}
                    </td>
                    <td>
                      <span className={`status-text status-text--${active.length ? "on" : "off"}`}>
                        {active.length === accounts.length
                          ? "Can log in"
                          : active.length === 0
                            ? "Stopped from logging in"
                            : `Stopped in ${accounts.length - active.length} of ${accounts.length}`}
                      </span>
                      {accounts.some((a) => !a.email_verified) && <span className="cell-sub">Email not verified</span>}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {page && page.total > 0 && (
        <Pagination
          page={page.page}
          pages={page.pages}
          from={(page.page - 1) * page.page_size + 1}
          to={Math.min(page.page * page.page_size, page.total)}
          total={page.total}
          onPage={setCurrentPage}
        />
      )}

      {addOpen && (
        <AddUserModal
          clients={clients}
          onClose={() => setAddOpen(false)}
          onAdded={() => {
            setAddOpen(false);
            setCurrentPage(1);
            load();
          }}
        />
      )}

      {openEmail && people.has(openEmail) && (
        <PersonPanel
          email={openEmail}
          accounts={people.get(openEmail)!}
          clients={clients}
          onClose={() => setOpenEmail(null)}
          onUpdated={replaceAccount}
          onRemoved={() => load()}
        />
      )}
    </>
  );
}

function Pagination({
  page,
  pages,
  from,
  to,
  total,
  onPage,
}: {
  page: number;
  pages: number;
  from: number;
  to: number;
  total: number;
  onPage: (page: number) => void;
}) {
  const shown = Array.from({ length: pages }, (_, i) => i + 1)
    .filter((p) => p === 1 || p === pages || Math.abs(p - page) <= 2)
    .reduce<(number | "gap")[]>((acc, p, i, arr) => {
      if (i > 0 && p - (arr[i - 1] as number) > 1) acc.push("gap");
      acc.push(p);
      return acc;
    }, []);

  return (
    <nav className="pagination" aria-label="Pages">
      <span className="pagination__count">
        {pages > 1 ? `${from}–${to} of ${total.toLocaleString()} accounts` : `${total.toLocaleString()} account${total === 1 ? "" : "s"}`}
      </span>
      {pages > 1 && (
        <div className="pagination__pages">
          <button type="button" className="btn btn--secondary" disabled={page <= 1} onClick={() => onPage(page - 1)}>
            Previous
          </button>
          {shown.map((p, i) =>
            p === "gap" ? (
              <span key={`gap-${i}`} className="pagination__gap">
                …
              </span>
            ) : (
              <button
                key={p}
                type="button"
                className={`btn ${p === page ? "btn--primary" : "btn--secondary"}`}
                aria-current={p === page ? "page" : undefined}
                onClick={() => onPage(p)}
              >
                {p}
              </button>
            ),
          )}
          <button type="button" className="btn btn--secondary" disabled={page >= pages} onClick={() => onPage(page + 1)}>
            Next
          </button>
        </div>
      )}
    </nav>
  );
}

/** One person: every account they have, and what they've been doing. */
function PersonPanel({
  email,
  accounts,
  clients,
  onClose,
  onUpdated,
  onRemoved,
}: {
  email: string;
  accounts: AppUser[];
  clients: Client[];
  onClose: () => void;
  onUpdated: (account: AppUser) => void;
  onRemoved: () => void;
}) {
  const [activity, setActivity] = useState<AuditEvent[] | null>(null);
  const { confirm, dialog } = useConfirmDialog();
  const name = personName(accounts[0]);
  const active = accounts.filter((a) => a.status === "active");

  useEffect(() => {
    api.get<AuditEvent[]>(`/audit?${new URLSearchParams({ q: email, limit: "15" })}`).then(setActivity);
  }, [email]);

  // Their new activity appears here as it happens.
  useLiveEvents((m) => {
    if (m === "resync") return;
    const theirs = m.extra.email === email || accounts.some((a) => a.id === m.extra.user_id);
    if (theirs) setActivity((prev) => prev && [m, ...prev.filter((e) => e.id !== m.id)].slice(0, 15));
  });

  return (
    <>
      <Sheet
        label={`Manage ${email}`}
        title={name || email}
        subtitle={name ? <span className="sheet__subtitle">{email}</span> : undefined}
        narrow
        onClose={onClose}
        summary={
          <ul className="sheet__summary">
            <li>
              <span className="sheet__fact">
                {active.length
                  ? `Can log in to ${active.map(accountApp).join(", ")}`
                  : "Stopped from logging in everywhere"}
              </span>
            </li>
            <li>
              <span className="sheet__fact">
                {accounts.length === 1 ? "1 account" : `${accounts.length} accounts`}
              </span>
            </li>
          </ul>
        }
      >
        <h3 className="sheet__section-title">{accounts.length === 1 ? "Account" : "Accounts"}</h3>
        <p className="sheet__section-lead">
          Each account belongs to the application it was created in. In a login group it also works in
          the group's other apps.
        </p>
        {accounts.map((u) => (
          <AccountCard
            key={u.id}
            account={u}
            clients={clients}
            confirm={confirm}
            onUpdated={onUpdated}
            onRemoved={() => {
              onRemoved();
              if (accounts.length === 1) onClose();
            }}
          />
        ))}

        <div className="panel__head" style={{ marginTop: 28 }}>
          <h3 className="sheet__section-title" style={{ margin: 0 }}>
            Recent activity
          </h3>
          <Link className="panel__link" to={`/admin/analytics?${new URLSearchParams({ user: email })}`}>
            Open in analytics
          </Link>
        </div>
        {activity === null ? (
          <p className="field__hint">Loading…</p>
        ) : activity.length === 0 ? (
          <p className="chart-empty">No activity yet.</p>
        ) : (
          <>
            <ActivityList events={activity} compact />
            <Link className="panel__link" to={`/admin/audit?${new URLSearchParams({ q: email })}`}>
              See all their activity
            </Link>
          </>
        )}
      </Sheet>
      {dialog}
    </>
  );
}

function AccountCard({
  account: u,
  clients,
  confirm,
  onUpdated,
  onRemoved,
}: {
  account: AppUser;
  clients: Client[];
  confirm: ReturnType<typeof useConfirmDialog>["confirm"];
  onUpdated: (account: AppUser) => void;
  onRemoved: () => void;
}) {
  const { show } = useToast();
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState({ email: "", first_name: "", last_name: "", username: "", phone: "", client_id: "" });
  const [error, setError] = useState<string | null>(null);

  const startEdit = () => {
    setForm({
      email: u.email,
      first_name: u.first_name ?? "",
      last_name: u.last_name ?? "",
      username: u.username ?? "",
      phone: u.phone ?? "",
      client_id: "",
    });
    setError(null);
    setEditing(true);
  };

  const toggle = async () => {
    setBusy(true);
    try {
      const updated = await api.post<AppUser>(`/users/${u.id}/toggle-status`);
      onUpdated(updated);
      show(
        updated.status === "active"
          ? `${u.email} can log in to ${accountApp(u)} again`
          : `${u.email} can't log in to ${accountApp(u)} now, and was signed out`,
      );
    } finally {
      setBusy(false);
    }
  };

  const save = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const updated = await api.patch<AppUser>(`/users/${u.id}`, {
        email: form.email,
        first_name: form.first_name.trim() || null,
        last_name: form.last_name.trim() || null,
        username: form.username.trim() || null,
        phone: form.phone.trim() || null,
        client_id: form.client_id,
      });
      onUpdated(updated);
      setEditing(false);
      show(
        form.client_id && form.client_id !== u.client_id
          ? `Moved to ${accountApp(updated)} and signed out everywhere`
          : updated.email !== u.email
            ? "Saved. The new email needs verifying: use Send verification link"
            : "Changes saved",
      );
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't save your changes");
    } finally {
      setBusy(false);
    }
  };

  const sendReset = async () => {
    const { emailed } = await api.post<{ emailed: boolean }>(`/users/${u.id}/send-reset`);
    show(emailed ? `Password reset emailed to ${u.email}` : "Email isn't sending, so the reset link is on the Dashboard");
  };

  const markVerified = async () => {
    onUpdated(await api.post<AppUser>(`/users/${u.id}/mark-verified`));
    show(`${u.email} is now verified`);
  };

  const sendVerification = async () => {
    const { emailed } = await api.post<{ emailed: boolean }>(`/users/${u.id}/send-verification`);
    show(emailed ? `Verification link emailed to ${u.email}` : "Email isn't sending, so the link is on the Dashboard");
  };

  const signOut = async () => {
    await api.post(`/users/${u.id}/sign-out`);
    show(`${u.email} was signed out everywhere`);
  };

  const remove = () =>
    confirm({
      title: `Delete ${u.email}'s account in ${accountApp(u)}?`,
      description:
        "Deletes this account and signs them out straight away. This cannot be undone. Their entries in the Activity log stay.",
      danger: true,
      confirmLabel: "Delete account",
      onConfirm: async () => {
        await api.delete(`/users/${u.id}`);
        show(`${u.email}'s account in ${accountApp(u)} was deleted`);
        onRemoved();
      },
    });

  const field = (key: keyof typeof form, label: string, type = "text") => (
    <div className="field">
      <label htmlFor={`${u.id}-${key}`}>{label}</label>
      <input
        id={`${u.id}-${key}`}
        type={type}
        required={key === "email"}
        value={form[key]}
        onChange={(e) => setForm((f) => ({ ...f, [key]: e.target.value }))}
      />
    </div>
  );

  return (
    <section className={`account-card${u.status === "active" ? "" : " is-off"}`}>
      <div className="setting__main">
        <div className="setting__text">
          <div className="setting__title">{accountApp(u)}</div>
          <div className="setting__hint">
            {u.pool_name ? `In login group ${u.pool_name}` : "Standalone application"}.{" "}
            {u.email_verified ? "Email verified." : "Email not verified yet."}
          </div>
        </div>
        <label className="account-card__switch">
          <span>{u.status === "active" ? "Can log in" : "Stopped"}</span>
          <Switch label={`${u.email} can log in to ${accountApp(u)}`} checked={u.status === "active"} disabled={busy} onChange={toggle} />
        </label>
      </div>

      {editing ? (
        <form onSubmit={save} className="account-card__form">
          {error && <div className="alert alert--error">{error}</div>}
          {field("email", "Email", "email")}
          <div className="field-pair">
            {field("first_name", "First name")}
            {field("last_name", "Last name")}
          </div>
          <div className="field-pair">
            {field("username", "Username")}
            {field("phone", "Phone", "tel")}
          </div>
          <div className="field">
            <label htmlFor={`${u.id}-move`}>Application</label>
            <select id={`${u.id}-move`} value={form.client_id} onChange={(e) => setForm((f) => ({ ...f, client_id: e.target.value }))}>
              <option value="">Keep in {accountApp(u)}</option>
              {clients
                .filter((c) => c.client_id !== u.client_id)
                .map((c) => (
                  <option key={c.id} value={c.client_id}>
                    Move to {appName(c)}
                  </option>
                ))}
            </select>
            {form.client_id && <span className="field__hint">Moving the account signs them out everywhere.</span>}
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            <button type="submit" className="btn btn--primary" disabled={busy}>
              Save changes
            </button>
            <button type="button" className="btn btn--ghost" onClick={() => setEditing(false)}>
              Cancel
            </button>
          </div>
        </form>
      ) : (
        <div className="account-card__actions">
          <button type="button" className="btn btn--secondary" onClick={startEdit}>
            Edit details
          </button>
          {!u.email_verified && (
            <>
              <button type="button" className="btn btn--secondary" onClick={sendVerification}>
                Send verification link
              </button>
              <button type="button" className="btn btn--secondary" onClick={markVerified}>
                Mark email as verified
              </button>
            </>
          )}
          <button type="button" className="btn btn--secondary" onClick={sendReset}>
            Send password reset
          </button>
          <button type="button" className="btn btn--secondary" onClick={signOut}>
            Sign out everywhere
          </button>
          <button type="button" className="btn btn--ghost account-card__delete" onClick={remove}>
            Delete account
          </button>
        </div>
      )}
    </section>
  );
}

function AddUserModal({ clients, onClose, onAdded }: { clients: Client[]; onClose: () => void; onAdded: () => void }) {
  const { show } = useToast();
  const [form, setForm] = useState({
    email: "",
    first_name: "",
    last_name: "",
    username: "",
    phone: "",
    password: "",
    confirm: "",
    client_id: "",
  });
  const [emailVerified, setEmailVerified] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const set = (key: keyof typeof form) => (e: { target: { value: string } }) => setForm((f) => ({ ...f, [key]: e.target.value }));

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    if (form.password !== form.confirm) {
      setError("The two passwords don't match");
      return;
    }
    setSubmitting(true);
    try {
      await api.post("/users", {
        email: form.email,
        username: form.username.trim() || null,
        first_name: form.first_name.trim() || null,
        last_name: form.last_name.trim() || null,
        phone: form.phone.trim() || null,
        password: form.password,
        confirm_password: form.confirm,
        client_id: form.client_id,
        email_verified: emailVerified,
      });
      show(`${form.email} was added`);
      onAdded();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal title="Add a user" onClose={onClose}>
      <p className="modal__lead">For applications where people can't sign up themselves, this is how they get an account.</p>
      {error && <div className="alert alert--error">{error}</div>}
      <form onSubmit={onSubmit}>
        <div className="field">
          <label htmlFor="add-client">Application</label>
          <select id="add-client" required value={form.client_id} onChange={set("client_id")}>
            <option value="">Choose an application…</option>
            {clients.map((c) => (
              <option key={c.id} value={c.client_id}>
                {appName(c)}
              </option>
            ))}
          </select>
          <span className="field__hint">If it's in a login group, the account also works in the group's other apps.</span>
        </div>
        <div className="field">
          <label htmlFor="add-email">Email</label>
          <input id="add-email" type="email" required autoFocus value={form.email} onChange={set("email")} />
        </div>
        <div className="field-pair">
          <div className="field">
            <label htmlFor="add-first-name">First name</label>
            <input id="add-first-name" value={form.first_name} onChange={set("first_name")} />
          </div>
          <div className="field">
            <label htmlFor="add-last-name">Last name</label>
            <input id="add-last-name" value={form.last_name} onChange={set("last_name")} />
          </div>
        </div>
        <div className="field-pair">
          <div className="field">
            <label htmlFor="add-username">
              Username <span className="field__hint">(optional)</span>
            </label>
            <input id="add-username" value={form.username} onChange={set("username")} />
          </div>
          <div className="field">
            <label htmlFor="add-phone">
              Phone <span className="field__hint">(optional)</span>
            </label>
            <input id="add-phone" type="tel" value={form.phone} onChange={set("phone")} />
          </div>
        </div>
        <div className="field">
          <label htmlFor="add-password">Password</label>
          <PasswordInput id="add-password" required minLength={8} value={form.password} onChange={set("password")} />
        </div>
        <div className="field">
          <label htmlFor="add-confirm-password">Confirm password</label>
          <PasswordInput id="add-confirm-password" required minLength={8} value={form.confirm} onChange={set("confirm")} />
        </div>
        <div className="field">
          <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 14, fontWeight: 400 }}>
            <input type="checkbox" checked={emailVerified} onChange={(e) => setEmailVerified(e.target.checked)} />
            Treat their email as already verified
          </label>
          <span className="field__hint">Off: they get a verification email, like someone who signed up themselves.</span>
        </div>
        <button type="submit" className="btn btn--primary btn--block" disabled={submitting}>
          Add user
        </button>
      </form>
    </Modal>
  );
}
