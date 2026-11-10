import { FormEvent, useEffect, useState } from "react";
import { Modal } from "../components/Modal";
import { Switch } from "../components/Switch";
import { CopyableId } from "../components/CopyableId";
import { EmptyState } from "../components/EmptyState";
import { Menu } from "../components/Menu";
import { useConfirmDialog } from "../components/ConfirmDialog";
import { useToast } from "../components/ToastProvider";
import { PlusIcon, ResourcesIcon } from "../components/Icons";
import { IntegrationModal } from "../components/IntegrationModal";
import { api, ApiError, Resource } from "../api";
import { LiveIndicator, useDebounced, useLiveEvents } from "../live";

export function Resources() {
  const [resources, setResources] = useState<Resource[] | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [editResource, setEditResource] = useState<Resource | null>(null);
  const [guideResource, setGuideResource] = useState<Resource | null>(null);

  const [resourceId, setResourceId] = useState("");
  const [name, setName] = useState("");
  const [metadataUrl, setMetadataUrl] = useState("");
  const [requireVerified, setRequireVerified] = useState(true);
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

  // Stays current without a refresh: token counts grow as tokens are issued,
  // and the list reloads when a server is added, changed or removed elsewhere.
  const reloadSoon = useDebounced(() => load(), 600);
  useLiveEvents((m) => {
    if (m === "resync") return void load();
    if (m.event === "token_issued" && typeof m.extra.resource === "string") {
      const issuedFor = m.extra.resource;
      setResources(
        (prev) => prev?.map((r) => (r.resource_id === issuedFor ? { ...r, tokens_30d: (r.tokens_30d ?? 0) + 1 } : r)) ?? prev,
      );
    } else if (m.event.startsWith("resource_")) {
      reloadSoon();
    }
  });

  const setVerifiedEmail = (r: Resource, on: boolean) => {
    const apply = async () => {
      const updated = await api.post<Resource>(`/resources/${encodeURIComponent(r.resource_id)}/toggle-require-verified-email`);
      setResources((prev) => prev?.map((x) => (x.resource_id === r.resource_id ? { ...x, ...updated } : x)) ?? prev);
      show(updated.require_verified_email ? `${r.name} now needs a verified email` : `${r.name} no longer needs a verified email`);
    };
    if (!on) return void apply();
    confirm({
      title: `Require a verified email for ${r.name}?`,
      description:
        "Anyone signing in to use it, from any app or AI client, must confirm their email first. People who haven't will see \"Check your email\" and carry on once they open the link.",
      confirmLabel: "Require it",
      onConfirm: apply,
    });
  };

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const created = await api.post<Resource>("/resources", {
        resource_id: resourceId.trim(),
        name: name.trim(),
        metadata_url: metadataUrl.trim(),
        require_verified_email: requireVerified,
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
      title: `Remove ${r.name}?`,
      description:
        "Permanently deletes this resource from the database — not a disable, there's no undo. Any tokens previously issued for it remain valid until they expire. If you just want to block new tokens without losing the record, use Disable instead.",
      danger: true,
      confirmLabel: "Remove",
      onConfirm: async () => {
        await api.delete(`/resources/${encodeURIComponent(r.resource_id)}`);
        show(`${r.name} removed`);
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
        const updated = await api.post<Resource>(`/resources/${encodeURIComponent(r.resource_id)}/toggle-enabled`);
        // Patched in place; the token count doesn't change by toggling.
        setResources((prev) => prev?.map((x) => (x.resource_id === r.resource_id ? { ...x, ...updated } : x)) ?? prev);
        show(updated.enabled ? `${r.name} accepts new tokens again` : `${r.name} no longer gets new tokens`);
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
        <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
          <LiveIndicator />
          {resources && resources.length > 0 && (
            <button
              type="button"
              className="btn btn--secondary"
              onClick={() => setGuideResource(resources[0])}
            >
              Integration Guide
            </button>
          )}
          <button type="button" className="btn btn--primary" onClick={() => setModalOpen(true)}>
            <PlusIcon width={16} height={16} style={{ verticalAlign: -3 }} /> Register MCP server or API
          </button>
        </div>
      </div>

      <p className="lead">
        The APIs and MCP servers that accept this service's sign-ins. Register one so apps and AI
        assistants such as Claude or Cursor can find it and get access tokens made for it, and nothing
        else (RFC 9728 and RFC 8707).
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
                <th>API or MCP server</th>
                <th>Address (token audience)</th>
                <th style={{ textAlign: "right" }}>Tokens, last 30 days</th>
                <th>Accepting new tokens</th>
                <th>Verified email</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {resources?.map((r) => (
                <tr key={r.resource_id} style={{ opacity: r.enabled ? 1 : 0.6 }}>
                  <td>
                    <div style={{ fontWeight: 600 }}>{r.name}</div>
                    <div className="cell-sub">
                      {r.metadata_url ? "Publishes its own discovery document" : "Discovery document hosted here"}
                    </div>
                  </td>
                  <td>
                    <CopyableId value={r.resource_id} max={40} />
                  </td>
                  <td style={{ textAlign: "right", fontVariantNumeric: "tabular-nums" }}>
                    {(r.tokens_30d ?? 0).toLocaleString()}
                  </td>
                  <td>
                    <label className="signup-cell">
                      <Switch label={`${r.name} accepts new tokens`} checked={r.enabled} onChange={() => toggleEnabled(r)} />
                      <span>{r.enabled ? "Yes" : "Stopped"}</span>
                    </label>
                  </td>
                  <td>
                    <label className="signup-cell">
                      <Switch
                        label={`${r.name} requires a verified email`}
                        checked={r.require_verified_email}
                        onChange={(on) => setVerifiedEmail(r, on)}
                      />
                      <span>{r.require_verified_email ? "Required" : "Not required"}</span>
                    </label>
                  </td>
                  <td>
                    <div className="row-actions">
                      <button type="button" className="btn btn--secondary" onClick={() => setGuideResource(r)}>
                        Get code
                      </button>
                      <Menu
                        items={[
                          { label: "Edit", onSelect: () => openEdit(r) },
                          { label: "Remove", onSelect: () => onDelete(r), danger: true },
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
            <div className="field">
              <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 14 }}>
                <input type="checkbox" checked={requireVerified} onChange={(e) => setRequireVerified(e.target.checked)} />
                Require a verified email before anyone gets access
              </label>
              <span className="field__hint">
                Applies to every app and AI client that connects to it, including ones that register
                themselves. People who haven't verified see "Check your email" first.
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
