import { FormEvent, useEffect, useMemo, useState } from "react";
import { Modal } from "../components/Modal";
import { Badge } from "../components/Badge";
import { Menu } from "../components/Menu";
import { Switch } from "../components/Switch";
import { CopyableId } from "../components/CopyableId";
import { EmptyState } from "../components/EmptyState";
import { useConfirmDialog } from "../components/ConfirmDialog";
import { useToast } from "../components/ToastProvider";
import { AppsIcon, PlusIcon } from "../components/Icons";
import { IntegrationModal } from "../components/IntegrationModal";
import { LinkListInput } from "../components/LinkListInput";
import { api, ApiError, Client } from "../api";
import {
  appendLine,
  DurationUnit,
  durationSeconds,
  EmbedOriginsField,
  GRANT_LABELS,
  PostLogoutUrisField,
  QuickRedirects,
  SessionTimeoutField,
} from "./applicationFields";
import { displayName, ManageApplication } from "./ManageApplication";

type Preset = "website" | "native" | "service";
type Sharing = "shared" | "separate";

const PRESET_DEFAULTS: Record<Preset, { clientType: string; applicationType: string; grants: string[] }> = {
  website: { clientType: "confidential", applicationType: "web", grants: ["authorization_code", "refresh_token"] },
  native: { clientType: "public", applicationType: "native", grants: ["authorization_code", "refresh_token"] },
  service: { clientType: "confidential", applicationType: "service", grants: ["client_credentials"] },
};


export function Applications() {
  const [clients, setClients] = useState<Client[] | null>(null);
  const [search, setSearch] = useState("");
  const [modalOpen, setModalOpen] = useState(false);
  const [created, setCreated] = useState<Client | null>(null);
  const [managing, setManaging] = useState<Client | null>(null);
  const [guideClient, setGuideClient] = useState<Client | null>(null);
  const [guideOpen, setGuideOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const { confirm, dialog } = useConfirmDialog();
  const { show } = useToast();

  const [preset, setPreset] = useState<Preset>("website");
  const [clientId, setClientId] = useState("");
  const [redirectUris, setRedirectUris] = useState("");
  const [sharing, setSharing] = useState<Sharing>("shared");
  const [sharedPool, setSharedPool] = useState("");
  const [allowSignup, setAllowSignup] = useState(true);
  const [clientType, setClientType] = useState("confidential");
  const [grants, setGrants] = useState<string[]>(PRESET_DEFAULTS.website.grants);
  const [scope, setScope] = useState("");
  const [logoUrl, setLogoUrl] = useState("");
  const [brandColor, setBrandColor] = useState("");
  const [ttlEnabled, setTtlEnabled] = useState(true);
  const [ttlValue, setTtlValue] = useState("7");
  const [ttlUnit, setTtlUnit] = useState<DurationUnit>("days");
  const [postLogoutUris, setPostLogoutUris] = useState("");
  const [embedOrigins, setEmbedOrigins] = useState("");

  const load = () => api.get<Client[]>("/clients").then(setClients);

  useEffect(() => {
    load();
  }, []);

  // Keep the drawer in sync with the underlying row after a toggle/save.
  useEffect(() => {
    if (managing) setManaging((prev) => clients?.find((c) => c.id === prev?.id) ?? null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [clients]);

  // Which existing login groups are available to join, described by the
  // app(s) already using them -- so picking one reads as "sign in with the
  // same account as App X" instead of naming an abstract group.
  const sharablePools = useMemo(() => {
    if (!clients) return [];
    const byPool = new Map<string, string[]>();
    for (const c of clients) {
      if (!c.pool_name) continue; // standalone clients can't be shared
      const label = c.client_name || "Unnamed application";
      byPool.set(c.pool_name, [...(byPool.get(c.pool_name) ?? []), label]);
    }
    return Array.from(byPool.entries()).map(([poolName, names]) => ({ poolName, label: names.join(", ") }));
  }, [clients]);

  // Default to "separate" when there's nothing yet to share with, and once
  // apps exist, default the picker to the first one.
  useEffect(() => {
    if (sharablePools.length === 0) {
      setSharing("separate");
    } else if (!sharedPool) {
      setSharedPool(sharablePools[0].poolName);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sharablePools]);

  const filtered = useMemo(() => {
    if (!clients) return clients;
    const q = search.trim().toLowerCase();
    if (!q) return clients;
    return clients.filter(
      (c) => (c.client_name ?? "").toLowerCase().includes(q) || c.client_id.toLowerCase().includes(q),
    );
  }, [clients, search]);

  const applyPreset = (p: Preset) => {
    setPreset(p);
    const d = PRESET_DEFAULTS[p];
    setClientType(d.clientType);
    setGrants(d.grants);
    // Only websites get a sign-in limit by default; AI assistants, MCP
    // clients and services keep the standard rules unless switched on.
    setTtlEnabled(p === "website");
    if (p === "service") {
      setRedirectUris("");
      setAllowSignup(false);
    }
  };

  const resolvedPool = () => {
    if (sharing === "separate") return ""; // standalone — no pool
    return sharedPool || sharablePools[0]?.poolName || "";
  };

  const toggleGrant = (g: string) => {
    setGrants((prev) => (prev.includes(g) ? prev.filter((x) => x !== g) : [...prev, g]));
  };

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const result = await api.post<Client>("/clients", {
        client_id: clientId,
        client_name: clientId,
        client_type: clientType,
        redirect_uris: redirectUris,
        grant_types: grants,
        scope,
        application_type: PRESET_DEFAULTS[preset].applicationType,
        user_pool: resolvedPool(),
        allow_signup: allowSignup,
        logo_url: logoUrl,
        brand_color: brandColor,
        session_ttl_seconds:
          preset === "service" || !ttlEnabled ? 0 : durationSeconds(ttlValue, ttlUnit),
        post_logout_redirect_uris: preset === "service" ? "" : postLogoutUris,
        embed_origins: preset === "service" ? "" : embedOrigins,
      });
      setModalOpen(false);
      setCreated(result);
      setClientId("");
      setRedirectUris("");
      setTtlEnabled(preset === "website");
      setTtlValue("7");
      setTtlUnit("days");
      setPostLogoutUris("");
      setEmbedOrigins("");
      setScope("");
      setLogoUrl("");
      setBrandColor("");
      load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong");
    } finally {
      setSubmitting(false);
    }
  };

  const toggleEnabled = async (client: Client) => {
    await api.post(`/clients/${client.client_id}/toggle-enabled`);
    show(client.enabled ? `${displayName(client)} disabled` : `${displayName(client)} re-enabled`);
    load();
  };

  const toggleSignup = async (client: Client) => {
    await api.post(`/clients/${client.client_id}/toggle-signup`);
    show(client.allow_signup ? `Signup turned off for ${displayName(client)}` : `Signup turned on for ${displayName(client)}`);
    load();
  };

  const deleteClient = async (client: Client) => {
    await api.delete(`/clients/${client.client_id}`);
    show(`${displayName(client)} deleted`);
    setManaging(null);
    load();
  };

  return (
    <>
      <div className="header">
        <div className="header__title-row">
          <span className="header__icon">
            <AppsIcon />
          </span>
          <h1 className="title">Applications</h1>
        </div>
        <div style={{ display: "flex", gap: 10 }}>
          <button
            type="button"
            className="btn btn--secondary"
            onClick={() => {
              setGuideClient(clients && clients.length > 0 ? clients[0] : null);
              setGuideOpen(true);
            }}
          >
            Integration Guide
          </button>
          <button type="button" className="btn btn--primary" onClick={() => setModalOpen(true)}>
            <PlusIcon width={16} height={16} /> Add application
          </button>
        </div>
      </div>

      <p className="lead">
        An <strong>application</strong> is anything that lets people log in — a website, a mobile
        app, or an AI assistant like ChatGPT or Claude connecting to your service.
      </p>

      {clients && clients.length > 0 && (
        <input
          type="search"
          placeholder="Search by name or client ID…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          style={{ maxWidth: 320, marginBottom: 16, display: "block" }}
        />
      )}

      {clients?.length === 0 ? (
        <EmptyState
          icon={<AppsIcon width={20} height={20} />}
          title="No applications yet"
          description="Add the first website, mobile app, or AI assistant that should let people log in."
          action={
            <button type="button" className="btn btn--primary" onClick={() => setModalOpen(true)}>
              <PlusIcon width={16} height={16} /> Add application
            </button>
          }
        />
      ) : (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Application</th>
                <th>Type</th>
                <th>Login group</th>
                <th>Status</th>
                <th>Signup</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {filtered?.length === 0 && (
                <tr>
                  <td colSpan={6}>No applications match "{search}".</td>
                </tr>
              )}
              {filtered?.map((c) => (
                <ClientRow
                  key={c.id}
                  client={c}
                  onManage={() => setManaging(c)}
                  onToggleSignup={() => toggleSignup(c)}
                  onDisable={() =>
                    confirm({
                      title: `${c.enabled ? "Disable" : "Re-enable"} ${displayName(c)}?`,
                      description: c.enabled
                        ? "This immediately blocks anyone from logging in or refreshing a token with this application, without deleting it or losing its history. You can re-enable it any time."
                        : "This lets the application accept logins and token refreshes again.",
                      danger: c.enabled,
                      confirmLabel: c.enabled ? "Disable" : "Re-enable",
                      onConfirm: () => toggleEnabled(c),
                    })
                  }
                  onDelete={() =>
                    confirm({
                      title: `Remove ${displayName(c)}?`,
                      description:
                        "Permanently removes this application and immediately blocks all logins and token refreshes. This cannot be undone.",
                      danger: true,
                      confirmLabel: "Remove",
                      onConfirm: () => deleteClient(c),
                    })
                  }
                />
              ))}
            </tbody>
          </table>
        </div>
      )}

      {modalOpen && (
        <Modal title="Add an application" wide onClose={() => setModalOpen(false)}>
          {error && <div className="alert alert--error">{error}</div>}
          <form onSubmit={onSubmit} style={{ display: "flex", flexDirection: "column", gap: 20 }}>
            <div className="field">
              <label htmlFor="preset">What are you connecting?</label>
              <select id="preset" value={preset} onChange={(e) => applyPreset(e.target.value as Preset)}>
                <option value="website">Website or backend app</option>
                <option value="native">Mobile app, CLI tool, or AI assistant (e.g. ChatGPT, an MCP client)</option>
                <option value="service">Machine-to-machine service — no human ever logs in</option>
              </select>
            </div>

            {preset === "native" && (
              <div
                style={{
                  padding: "10px 14px",
                  background: "var(--info-bg)",
                  color: "var(--info-fg)",
                  borderRadius: "var(--radius-sm)",
                  fontSize: 12.5,
                  marginTop: -8,
                }}
              >
                <strong>AI Assistants & MCP Clients:</strong> Public clients use Authorization Code + PKCE (S256).
                No secret is required or stored. Once created, you will get ready-to-copy configs for Claude Desktop and Cursor.
              </div>
            )}

            <div className="field">
              <label htmlFor="client_id">Give it a name</label>
              <input
                id="client_id"
                required
                placeholder="e.g. marketing-site, support-bot, claude-desktop"
                value={clientId}
                onChange={(e) => setClientId(e.target.value)}
              />
              <span className="field__hint">Just an internal label so you can recognize it later.</span>
            </div>

            {preset !== "service" && (
              <div className="field">
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
                  <label htmlFor="redirect_uris">
                    Where should we send people back to after login?
                  </label>
                  {preset === "native" && (
                    <QuickRedirects onAdd={(uri) => setRedirectUris((prev) => appendLine(prev, uri))} />
                  )}
                </div>
                <LinkListInput
                  id="redirect_uris"
                  required
                  placeholder="https://yourapp.com/callback"
                  value={redirectUris}
                  onChange={setRedirectUris}
                />
              </div>
            )}

            <div className="field">
              <label>Who should be able to log in?</label>
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                <SharingCard
                  checked={sharing === "shared"}
                  onSelect={() => setSharing("shared")}
                  disabled={sharablePools.length === 0}
                  title="Use accounts from an existing application (single sign-on)"
                  desc={
                    sharablePools.length > 0
                      ? "One account works for both — picking a person's existing login, not creating a new kind of account."
                      : "No other applications yet — add this one as separate, then new apps can share its accounts."
                  }
                />
                {sharing === "shared" && sharablePools.length > 0 && (
                  <select
                    style={{ marginLeft: 26, maxWidth: 320 }}
                    value={sharedPool || sharablePools[0].poolName}
                    onChange={(e) => setSharedPool(e.target.value)}
                  >
                    {sharablePools.map((p) => (
                      <option value={p.poolName} key={p.poolName}>
                        Same accounts as: {p.label}
                      </option>
                    ))}
                  </select>
                )}
                <SharingCard
                  checked={sharing === "separate"}
                  onSelect={() => setSharing("separate")}
                  title="Keep this app's users separate"
                  desc="Its own private list of accounts — good for an internal admin tool or a client-specific deployment."
                />
              </div>
            </div>

            {preset !== "service" && (
              <div className="field">
                <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 14 }}>
                  <input type="checkbox" checked={allowSignup} onChange={(e) => setAllowSignup(e.target.checked)} />
                  Let people create their own account from this app's login page
                </label>
                <span className="field__hint">
                  On: anyone can sign up themselves (from this app, or any other app in the same
                  login group). Off: only you can add users — from Manage on this app, or the
                  Users page.
                </span>
              </div>
            )}

            {preset !== "service" && (
              <>
                <SessionTimeoutField
                  enabled={ttlEnabled}
                  value={ttlValue}
                  unit={ttlUnit}
                  onChange={(on, v, u) => {
                    setTtlEnabled(on);
                    setTtlValue(v);
                    setTtlUnit(u);
                  }}
                />
                <PostLogoutUrisField value={postLogoutUris} onChange={setPostLogoutUris} />
              </>
            )}

            <details>
              <summary style={{ cursor: "pointer", fontSize: 13, fontWeight: 600, color: "var(--text-muted)" }}>
                Advanced settings (rarely needed)
              </summary>
              <div style={{ marginTop: 14 }}>
                <div className="field">
                  <label htmlFor="client_type">Can this app keep a secret safely?</label>
                  <select id="client_type" value={clientType} onChange={(e) => setClientType(e.target.value)}>
                    <option value="public">No — it's public (browser, mobile app, or AI assistant)</option>
                    <option value="confidential">Yes — it runs on my own server</option>
                  </select>
                </div>
                <div className="field">
                  <label>What is it allowed to do</label>
                  <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                    {Object.entries(GRANT_LABELS).map(([g, label]) => (
                      <label key={g} style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 14 }}>
                        <input type="checkbox" checked={grants.includes(g)} onChange={() => toggleGrant(g)} />
                        {label}
                      </label>
                    ))}
                  </div>
                </div>
                <div className="field">
                  <label htmlFor="scope">
                    Allowed scopes <span className="field__hint">(space-separated — leave blank for the default access level)</span>
                  </label>
                  <input id="scope" placeholder="openid profile email" value={scope} onChange={(e) => setScope(e.target.value)} />
                </div>
                <div className="field">
                  <label htmlFor="logo_url">
                    Logo URL <span className="field__hint">(optional — shown on this app's login/signup/consent pages)</span>
                  </label>
                  <input
                    id="logo_url"
                    placeholder="https://yourapp.com/logo.png"
                    value={logoUrl}
                    onChange={(e) => setLogoUrl(e.target.value)}
                  />
                </div>
                <div className="field">
                  <label htmlFor="brand_color">
                    Brand color <span className="field__hint">(optional — CSS color, e.g. #1d4ed8)</span>
                  </label>
                  <input
                    id="brand_color"
                    placeholder="#1d4ed8"
                    value={brandColor}
                    onChange={(e) => setBrandColor(e.target.value)}
                  />
                </div>
                {preset !== "service" && <EmbedOriginsField value={embedOrigins} onChange={setEmbedOrigins} />}
              </div>
            </details>

            <button type="submit" className="btn btn--primary btn--block" disabled={submitting}>
              Add application
            </button>
          </form>
        </Modal>
      )}

      {created && (
        <Modal title="Application created" wide onClose={() => setCreated(null)}>
          <p className="field__hint" style={{ marginTop: -8 }}>
            <strong>{created.client_name || created.client_id}</strong> was added.
          </p>
          <div className="field">
            <label>Client ID</label>
            <input readOnly value={created.client_id} onFocus={(e) => e.currentTarget.select()} />
          </div>
          {created.client_secret && (
            <div className="field">
              <label>Client secret</label>
              <input readOnly value={created.client_secret} onFocus={(e) => e.currentTarget.select()} />
              <span className="field__hint">Shown once — copy it now, it can't be recovered later.</span>
            </div>
          )}
          <div style={{ display: "flex", gap: 10, marginTop: 16 }}>
            <button
              type="button"
              className="btn btn--primary"
              style={{ flex: 1 }}
              onClick={() => {
                const c = created;
                setCreated(null);
                setGuideClient(c);
                setGuideOpen(true);
              }}
            >
              View Integration Guide & Code
            </button>
            <button type="button" className="btn btn--secondary" onClick={() => setCreated(null)}>
              Done
            </button>
          </div>
        </Modal>
      )}

      {managing && (
        <ManageApplication
          client={managing}
          allClients={clients ?? []}
          onClose={() => setManaging(null)}
          onChanged={load}
          onToggleEnabled={() => toggleEnabled(managing)}
          onDelete={() => deleteClient(managing)}
        />
      )}

      {guideOpen && (
        <IntegrationModal
          client={guideClient}
          allClients={clients ?? []}
          clientSecret={guideClient?.client_secret}
          onSelectClient={(c) => setGuideClient(c)}
          appOnly
          onClose={() => {
            setGuideOpen(false);
            setGuideClient(null);
          }}
        />
      )}

      {dialog}
    </>
  );
}

function SharingCard({
  checked,
  onSelect,
  title,
  desc,
  disabled,
}: {
  checked: boolean;
  onSelect: () => void;
  title: string;
  desc: string;
  disabled?: boolean;
}) {
  return (
    <label
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 3,
        padding: "12px 14px",
        border: `1px solid ${checked ? "var(--brand-600)" : "var(--border)"}`,
        background: checked ? "var(--brand-soft)" : "transparent",
        borderRadius: "var(--radius-sm)",
        cursor: disabled ? "not-allowed" : "pointer",
        opacity: disabled ? 0.55 : 1,
      }}
    >
      <span style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <input type="radio" checked={checked} onChange={onSelect} disabled={disabled} />
        <span style={{ fontWeight: 600, fontSize: 13.5 }}>{title}</span>
      </span>
      <span style={{ fontSize: 12.5, color: "var(--text-muted)" }}>{desc}</span>
    </label>
  );
}

function ClientRow({
  client,
  onManage,
  onToggleSignup,
  onDisable,
  onDelete,
}: {
  client: Client;
  onManage: () => void;
  onToggleSignup: () => void;
  onDisable: () => void;
  onDelete: () => void;
}) {
  return (
    <tr style={{ opacity: client.enabled ? 1 : 0.55 }}>
      <td>
        <div style={{ fontWeight: 600 }}>{client.client_name || <em style={{ fontWeight: 400 }}>Unnamed application</em>}</div>
        <CopyableId value={client.client_id} max={32} />
      </td>
      <td>{client.client_type}</td>
      <td>{client.pool_name ?? <span style={{ color: "var(--text-muted)", fontStyle: "italic" }}>Standalone</span>}</td>
      <td>
        <Badge variant={client.enabled ? "success" : "neutral"}>{client.enabled ? "Active" : "Disabled"}</Badge>
      </td>
      <td>
        {client.registration_method === "cimd" || !client.grant_types.includes("authorization_code") ? (
          <span style={{ color: "var(--text-muted)" }}>—</span>
        ) : (
          <label className="signup-cell">
            <Switch
              label={`Let people sign up to ${displayName(client)}`}
              checked={client.allow_signup}
              onChange={onToggleSignup}
            />
            <span>{client.allow_signup ? "Open" : "Admins only"}</span>
          </label>
        )}
      </td>
      <td>
        <div className="row-actions">
          <button type="button" className="btn btn--secondary" onClick={onManage}>
            Manage
          </button>
          <button type="button" className="btn btn--danger" onClick={onDelete}>
            Remove
          </button>
          <Menu
            items={[
              { label: client.enabled ? "Disable" : "Re-enable", onSelect: onDisable, danger: client.enabled },
            ]}
          />
        </div>
      </td>
    </tr>
  );
}
