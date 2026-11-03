import { FormEvent, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Modal } from "../components/Modal";
import { EmptyState } from "../components/EmptyState";
import { useConfirmDialog } from "../components/ConfirmDialog";
import { useToast } from "../components/ToastProvider";
import { CloseIcon, GroupsIcon, PlusIcon } from "../components/Icons";
import { api, ApiError, Client, Pool } from "../api";

function displayName(client: Client) {
  return client.client_name || client.client_id;
}

export function LoginGroups() {
  const [pools, setPools] = useState<Pool[] | null>(null);
  const [clients, setClients] = useState<Client[] | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [assignPool, setAssignPool] = useState<Pool | null>(null);
  const { confirm, dialog } = useConfirmDialog();
  const { show } = useToast();

  // Two requests, side by side. Each group's people are counted by the server
  // rather than loading every user here.
  const load = () =>
    Promise.all([api.get<Pool[]>("/pools").then(setPools), api.get<Client[]>("/clients").then(setClients)]);

  useEffect(() => {
    load();
  }, []);

  const appsByPool = useMemo(() => {
    const map = new Map<string, Client[]>();
    for (const c of clients ?? []) if (c.pool_name) map.set(c.pool_name, [...(map.get(c.pool_name) ?? []), c]);
    return map;
  }, [clients]);
  const standalone = (clients ?? []).filter((c) => !c.pool_name);

  const removeApp = (pool: Pool, client: Client) =>
    confirm({
      title: `Take ${displayName(client)} out of ${pool.name}?`,
      description: `It keeps its own users, but people from the other apps in ${pool.name} can't log in to it anymore, and its users can't log in to them.`,
      danger: true,
      confirmLabel: "Take it out",
      onConfirm: async () => {
        await api.post(`/pools/${encodeURIComponent(pool.name)}/remove-client`, { client_id: client.client_id });
        show(`${displayName(client)} now has its own accounts`);
        await load();
      },
    });

  const deleteGroup = (pool: Pool, apps: Client[]) =>
    confirm({
      title: `Delete ${pool.name}?`,
      description: apps.length
        ? `${apps.map(displayName).join(", ")} will each keep their own users but stop sharing accounts. No one's account is deleted.`
        : "This group has no applications. No one's account is deleted.",
      danger: true,
      confirmLabel: "Delete group",
      onConfirm: async () => {
        await api.delete(`/pools/${encodeURIComponent(pool.name)}`);
        show(`${pool.name} deleted`);
        await load();
      },
    });

  const loading = pools === null || clients === null;

  return (
    <>
      <div className="header">
        <div className="header__title-row">
          <span className="header__icon">
            <GroupsIcon />
          </span>
          <h1 className="title">Login groups</h1>
        </div>
        <button type="button" className="btn btn--primary" onClick={() => setCreateOpen(true)}>
          <PlusIcon width={16} height={16} /> Create group
        </button>
      </div>
      <p className="lead">
        Applications in the same login group share accounts: people sign up once and use the same email
        and password in every app of the group. An application outside a group has its own accounts.
      </p>

      {loading ? (
        <p className="field__hint">Loading…</p>
      ) : pools.length === 0 ? (
        <EmptyState
          icon={<GroupsIcon width={20} height={20} />}
          title="No login groups yet"
          description="Create a group, then add the applications that should share accounts."
          action={
            <button type="button" className="btn btn--primary" onClick={() => setCreateOpen(true)}>
              <PlusIcon width={16} height={16} /> Create group
            </button>
          }
        />
      ) : (
        <div className="group-list">
          {pools.map((pool) => {
            const apps = appsByPool.get(pool.name) ?? [];
            const people = pool.user_count ?? 0;
            return (
              <section key={pool.id} className="panel group-card" aria-labelledby={`group-${pool.id}`}>
                <div className="group-card__head">
                  <div>
                    <h2 id={`group-${pool.id}`} className="panel__title">
                      {pool.name}
                    </h2>
                    <p className="group-card__sentence">
                      {apps.length === 0
                        ? "No applications yet. Add one to start sharing accounts."
                        : apps.length === 1
                          ? `Only ${displayName(apps[0])} so far. Add another app to share its accounts.`
                          : `One account works in ${apps.map(displayName).join(", ")}.`}
                    </p>
                  </div>
                  <Link className="group-card__people" to={`/admin/users?${new URLSearchParams({ pool: pool.name })}`}>
                    <strong>{people.toLocaleString()}</strong> {people === 1 ? "person" : "people"}
                  </Link>
                </div>

                {apps.length > 0 && (
                  <ul className="app-chips" aria-label={`Applications in ${pool.name}`}>
                    {apps.map((c) => (
                      <li key={c.id} className="app-chip">
                        <span>{displayName(c)}</span>
                        <button type="button" aria-label={`Take ${displayName(c)} out of ${pool.name}`} onClick={() => removeApp(pool, c)}>
                          <CloseIcon width={12} height={12} />
                        </button>
                      </li>
                    ))}
                  </ul>
                )}

                <div className="group-card__actions">
                  <button type="button" className="btn btn--secondary" onClick={() => setAssignPool(pool)} disabled={standalone.length === 0}>
                    Add an application
                  </button>
                  <button type="button" className="btn btn--ghost" onClick={() => deleteGroup(pool, apps)}>
                    Delete group
                  </button>
                </div>
              </section>
            );
          })}

          {standalone.length > 0 && (
            <section className="group-standalone">
              <h2 className="panel__title">Applications with their own accounts</h2>
              <p className="panel__hint" style={{ marginTop: 6 }}>
                {standalone.map(displayName).join(", ")}. Add any of them to a group to share accounts.
              </p>
            </section>
          )}
        </div>
      )}

      {createOpen && (
        <CreateGroupModal
          onClose={() => setCreateOpen(false)}
          onCreated={async (name) => {
            setCreateOpen(false);
            show(`${name} created`);
            await load();
          }}
        />
      )}

      {assignPool && (
        <AssignAppModal
          pool={assignPool}
          availableClients={standalone}
          onClose={() => setAssignPool(null)}
          onAssigned={async (clientName) => {
            setAssignPool(null);
            show(`${clientName} now shares accounts in ${assignPool.name}`);
            await load();
          }}
        />
      )}

      {dialog}
    </>
  );
}

function CreateGroupModal({ onClose, onCreated }: { onClose: () => void; onCreated: (name: string) => void }) {
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await api.post("/pools", { name: name.trim() });
      onCreated(name.trim());
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal title="Create a login group" onClose={onClose}>
      <p className="modal__lead">Then add the applications that should share accounts.</p>
      {error && <div className="alert alert--error">{error}</div>}
      <form onSubmit={onSubmit}>
        <div className="field">
          <label htmlFor="group-name">Name</label>
          <input id="group-name" required autoFocus placeholder="e.g. acme-customers" value={name} onChange={(e) => setName(e.target.value)} />
          <span className="field__hint">Only you see this name.</span>
        </div>
        <button type="submit" className="btn btn--primary btn--block" disabled={submitting}>
          Create group
        </button>
      </form>
    </Modal>
  );
}

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
      await api.post(`/pools/${encodeURIComponent(pool.name)}/assign-client`, { client_id: selectedId });
      const chosen = availableClients.find((c) => c.client_id === selectedId);
      onAssigned(chosen ? displayName(chosen) : selectedId);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal title={`Add an application to ${pool.name}`} onClose={onClose}>
      <p className="modal__lead">
        Its users will be able to log in to every app in <strong>{pool.name}</strong>, and the group's
        users to it. Check that no one has two accounts with the same email across these apps first.
      </p>
      {error && <div className="alert alert--error">{error}</div>}
      <form onSubmit={onSubmit}>
        <div className="field">
          <label htmlFor="assign-app">Application</label>
          <select id="assign-app" required value={selectedId} onChange={(e) => setSelectedId(e.target.value)}>
            <option value="">Choose an application…</option>
            {availableClients.map((c) => (
              <option key={c.id} value={c.client_id}>
                {displayName(c)}
              </option>
            ))}
          </select>
          <span className="field__hint">Only applications with their own accounts are listed. To move an app between groups, use Manage on the Applications page.</span>
        </div>
        <button type="submit" className="btn btn--primary btn--block" disabled={submitting || !selectedId}>
          Add to group
        </button>
      </form>
    </Modal>
  );
}
