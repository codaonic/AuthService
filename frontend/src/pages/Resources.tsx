import { FormEvent, useEffect, useState } from "react";
import { Modal } from "../components/Modal";
import { Badge } from "../components/Badge";
import { CopyableId } from "../components/CopyableId";
import { EmptyState } from "../components/EmptyState";
import { Menu } from "../components/Menu";
import { useConfirmDialog } from "../components/ConfirmDialog";
import { useToast } from "../components/ToastProvider";
import { PlusIcon, ResourcesIcon } from "../components/Icons";
import { IntegrationModal } from "../components/IntegrationModal";
import { api, ApiError, Resource } from "../api";

export function Resources() {
  const [resources, setResources] = useState<Resource[] | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [editResource, setEditResource] = useState<Resource | null>(null);
  const [guideResource, setGuideResource] = useState<Resource | null>(null);

  const [resourceId, setResourceId] = useState("");
  const [name, setName] = useState("");
  const [metadataUrl, setMetadataUrl] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const [editName, setEditName] = useState("");
  const [editMetadataUrl, setEditMetadataUrl] = useState("");
  const [editError, setEditError] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);

  const { confirm, dialog } = useConfirmDialog();
  const { show } = useToast();

  const load = () => api.get<Resource[]>("/resources").then(setResources);

  useEffect(() => {
    load();
  }, []);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const created = await api.post<Resource>("/resources", {
        resource_id: resourceId.trim(),
        name: name.trim(),
        metadata_url: metadataUrl.trim(),
      });
      setModalOpen(false);
      setResourceId("");
      setName("");
      setMetadataUrl("");
      show(`Registered ${created.name}`);
      load();
      // Directly open integration guide for the newly created resource!
      setGuideResource(created);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong");
    } finally {
      setSubmitting(false);
    }
  };

  const openEdit = (r: Resource) => {
    setEditResource(r);
    setEditName(r.name);
    setEditMetadataUrl(r.metadata_url || "");
    setEditError(null);
  };

  const onSaveEdit = async (e: FormEvent) => {
    e.preventDefault();
    if (!editResource) return;
    setEditing(true);
    setEditError(null);
    try {
      await api.patch(`/resources/${encodeURIComponent(editResource.resource_id)}`, {
        name: editName.trim(),
        metadata_url: editMetadataUrl.trim(),
      });
      setEditResource(null);
      show(`Saved changes to ${editName}`);
      load();
    } catch (err) {
      setEditError(err instanceof ApiError ? err.message : "Something went wrong");
    } finally {
      setEditing(false);
    }
  };

  const onDelete = (r: Resource) => {
    confirm({
      title: `Delete resource ${r.name}?`,
      description:
        "Removes this MCP server or API from the discovery catalog. Any tokens previously issued for it remain valid until expiration.",
      danger: true,
      confirmLabel: "Delete",
      onConfirm: async () => {
        await api.delete(`/resources/${encodeURIComponent(r.resource_id)}`);
        show(`Deleted ${r.name}`);
        load();
      },
    });
  };

  const toggleEnabled = (r: Resource) => {
    confirm({
      title: `${r.enabled ? "Disable" : "Re-enable"} ${r.name}?`,
      description: r.enabled
        ? "Immediately blocks every client from getting a new access token for this resource. Tokens already issued for it keep working until they expire."
        : "Lets clients request access tokens for this resource again.",
      danger: r.enabled,
      confirmLabel: r.enabled ? "Disable" : "Re-enable",
      onConfirm: async () => {
        await api.post(`/resources/${encodeURIComponent(r.resource_id)}/toggle-enabled`);
        show(r.enabled ? `${r.name} disabled` : `${r.name} re-enabled`);
        load();
      },
    });
  };

  return (
    <>
      <div className="header">
        <div className="header__title-row">
          <span className="header__icon">
            <ResourcesIcon />
          </span>
          <h1 className="title">APIs & MCP servers</h1>
        </div>
        <button type="button" className="btn btn--primary" onClick={() => setModalOpen(true)}>
          <PlusIcon width={16} height={16} style={{ verticalAlign: -3 }} /> Register MCP server or API
        </button>
      </div>

      <p className="lead">
        A <strong>resource</strong> is an API or MCP server that <em>accepts and verifies</em> tokens from this
        auth server. Register your MCP servers here so AI assistants (Claude, Cursor, etc.) can discover them
        via Protected Resource Metadata (RFC 9728) and request audience-bound access tokens (RFC 8707).
      </p>

      {resources?.length === 0 ? (
        <EmptyState
          icon={<ResourcesIcon width={20} height={20} />}
          title="No resources registered yet"
          description="Register your first MCP server or API. No secret is required since resource servers only verify tokens locally against the public JWKS."
          action={
            <button type="button" className="btn btn--primary" onClick={() => setModalOpen(true)}>
              <PlusIcon width={16} height={16} /> Register MCP server or API
            </button>
          }
        />
      ) : (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Resource</th>
                <th>Audience / Resource ID</th>
                <th>PRM Metadata</th>
                <th>Status</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {resources?.map((r) => (
                <tr key={r.resource_id} style={{ opacity: r.enabled ? 1 : 0.55 }}>
                  <td>
                    <div style={{ fontWeight: 600 }}>{r.name}</div>
                  </td>
                  <td>
                    <CopyableId value={r.resource_id} max={36} />
                  </td>
                  <td>
                    {r.metadata_url ? (
                      <CopyableId value={r.metadata_url} max={36} />
                    ) : (
                      <span style={{ color: "var(--text-muted)", fontSize: 13 }}>Hosted on auth server</span>
                    )}
                  </td>
                  <td>
                    <Badge variant={r.enabled ? "success" : "neutral"}>{r.enabled ? "Active" : "Disabled"}</Badge>
                  </td>
                  <td>
                    <div className="row-actions">
                      <button
                        type="button"
                        className="btn btn--secondary"
                        onClick={() => setGuideResource(r)}
                      >
                        Integration Guide
                      </button>
                      <Menu
                        items={[
                          { label: "Edit details", onSelect: () => openEdit(r) },
                          { label: "Integration code & snippets", onSelect: () => setGuideResource(r) },
                          {
                            label: r.enabled ? "Disable" : "Re-enable",
                            onSelect: () => toggleEnabled(r),
                            danger: r.enabled,
                          },
                          { label: "Delete", onSelect: () => onDelete(r), danger: true },
                        ]}
                      />
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Register Resource Modal */}
      {modalOpen && (
        <Modal title="Register an MCP server or API" wide onClose={() => setModalOpen(false)}>
          <p style={{ fontSize: 13, color: "var(--text-muted)", marginTop: -8 }}>
            Resource servers verify tokens issued by this server. Once registered, you will get instant
            copy-paste code for FastMCP, Python, and TypeScript.
          </p>
          {error && <div className="alert alert--error">{error}</div>}
          <form onSubmit={onSubmit}>
            <div className="field">
              <label htmlFor="name">Name</label>
              <input
                id="name"
                required
                autoFocus
                placeholder="e.g. Weather MCP Server, Internal Data API"
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
              <span className="field__hint">Human-readable label for discovery metadata.</span>
            </div>
            <div className="field">
              <label htmlFor="resource_id">Resource ID (Audience URI)</label>
              <input
                id="resource_id"
                required
                placeholder="https://mcp.yourdomain.com or http://localhost:9002"
                value={resourceId}
                onChange={(e) => setResourceId(e.target.value)}
              />
              <span className="field__hint">
                The canonical URI representing this server. Stamped as the <code>aud</code> claim in JWTs.
              </span>
            </div>
            <div className="field">
              <label htmlFor="metadata_url">
                Custom Metadata URL <span className="field__hint">(optional)</span>
              </label>
              <input
                id="metadata_url"
                placeholder="https://mcp.yourdomain.com/.well-known/oauth-protected-resource"
                value={metadataUrl}
                onChange={(e) => setMetadataUrl(e.target.value)}
              />
              <span className="field__hint">
                Leave blank to use the auth server's hosted RFC 9728 endpoint for this resource.
              </span>
            </div>
            <button type="submit" className="btn btn--primary btn--block" disabled={submitting}>
              {submitting ? "Registering…" : "Register resource & view code"}
            </button>
          </form>
        </Modal>
      )}

      {/* Edit Resource Modal */}
      {editResource && (
        <Modal title={`Edit ${editResource.name}`} onClose={() => setEditResource(null)}>
          {editError && <div className="alert alert--error">{editError}</div>}
          <form onSubmit={onSaveEdit}>
            <div className="field">
              <label>Resource ID</label>
              <input disabled value={editResource.resource_id} />
              <span className="field__hint">Resource IDs cannot be changed because tokens are bound to them.</span>
            </div>
            <div className="field">
              <label htmlFor="edit-res-name">Name</label>
              <input
                id="edit-res-name"
                required
                value={editName}
                onChange={(e) => setEditName(e.target.value)}
              />
            </div>
            <div className="field">
              <label htmlFor="edit-res-metadata">Metadata URL</label>
              <input
                id="edit-res-metadata"
                value={editMetadataUrl}
                onChange={(e) => setEditMetadataUrl(e.target.value)}
                placeholder="https://mcp.yourdomain.com/.well-known/oauth-protected-resource"
              />
            </div>
            <button type="submit" className="btn btn--primary btn--block" disabled={editing}>
              {editing ? "Saving…" : "Save changes"}
            </button>
          </form>
        </Modal>
      )}

      {/* Integration Guide Modal */}
      {guideResource && (
        <IntegrationModal
          resource={guideResource}
          onClose={() => setGuideResource(null)}
        />
      )}

      {dialog}
    </>
  );
}
