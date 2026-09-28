import { FormEvent, useEffect, useState } from "react";
import { Modal } from "../components/Modal";
import { PlusIcon, ResourcesIcon } from "../components/Icons";
import { api, ApiError, Resource } from "../api";

export function Resources() {
  const [resources, setResources] = useState<Resource[] | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [resourceId, setResourceId] = useState("");
  const [name, setName] = useState("");
  const [metadataUrl, setMetadataUrl] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const load = () => api.get<Resource[]>("/resources").then(setResources);

  useEffect(() => {
    load();
  }, []);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await api.post("/resources", { resource_id: resourceId, name, metadata_url: metadataUrl });
      setModalOpen(false);
      setResourceId("");
      setName("");
      setMetadataUrl("");
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
            <ResourcesIcon />
          </span>
          <h1 className="title">Resources</h1>
        </div>
        <button type="button" className="btn btn--primary" onClick={() => setModalOpen(true)}>
          <PlusIcon width={16} height={16} style={{ verticalAlign: -3 }} /> Register resource
        </button>
      </div>

      <p className="lead">
        A <strong>resource</strong> is an API or MCP server that <em>accepts</em> tokens from this
        auth server, rather than one that logs users in. Register your MCP server or API here so
        it shows up in discovery metadata — no secret is issued, since resources only verify
        tokens.
      </p>

      <table className="table">
        <thead>
          <tr>
            <th>Resource ID</th>
            <th>Name</th>
          </tr>
        </thead>
        <tbody>
          {resources?.length === 0 && (
            <tr>
              <td colSpan={2}>No resources yet.</td>
            </tr>
          )}
          {resources?.map((r) => (
            <tr key={r.resource_id}>
              <td>{r.resource_id}</td>
              <td>{r.name}</td>
            </tr>
          ))}
        </tbody>
      </table>

      {modalOpen && (
        <Modal title="Register a resource" onClose={() => setModalOpen(false)}>
          {error && <div className="alert alert--error">{error}</div>}
          <form onSubmit={onSubmit}>
            <div className="field">
              <label htmlFor="resource_id">Resource ID</label>
              <input
                id="resource_id"
                required
                autoFocus
                placeholder="https://api.yourdomain.com"
                value={resourceId}
                onChange={(e) => setResourceId(e.target.value)}
              />
            </div>
            <div className="field">
              <label htmlFor="name">Name</label>
              <input
                id="name"
                required
                placeholder="Your API"
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
            </div>
            <div className="field">
              <label htmlFor="metadata_url">
                Metadata URL <span className="field__hint">(optional)</span>
              </label>
              <input
                id="metadata_url"
                placeholder="https://api.yourdomain.com/.well-known/oauth-protected-resource"
                value={metadataUrl}
                onChange={(e) => setMetadataUrl(e.target.value)}
              />
            </div>
            <button type="submit" className="btn btn--primary btn--block" disabled={submitting}>
              Register resource
            </button>
          </form>
        </Modal>
      )}
    </>
  );
}
