import { FormEvent, useEffect, useState } from "react";
import { Modal } from "../components/Modal";
import { GroupsIcon, PlusIcon } from "../components/Icons";
import { api, ApiError, Pool } from "../api";

export function LoginGroups() {
  const [pools, setPools] = useState<Pool[] | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const load = () => api.get<Pool[]>("/pools").then(setPools);

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
        A <strong>login group</strong> is a set of user accounts. Applications in the same group
        share logins (one account works across all of them). You'll usually set this
        per-application when you add it, on the Applications page — this page is just for seeing
        what groups exist, or creating one ahead of time with a custom name.
      </p>

      <table className="table">
        <thead>
          <tr>
            <th>Name</th>
            <th>Group ID</th>
          </tr>
        </thead>
        <tbody>
          {pools?.length === 0 && (
            <tr>
              <td colSpan={2}>No login groups yet.</td>
            </tr>
          )}
          {pools?.map((pool) => (
            <tr key={pool.id}>
              <td>{pool.name}</td>
              <td>{pool.id}</td>
            </tr>
          ))}
        </tbody>
      </table>

      {modalOpen && (
        <Modal title="Create a login group" onClose={() => setModalOpen(false)}>
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
    </>
  );
}
