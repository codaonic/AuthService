import { FormEvent, useEffect, useMemo, useState } from "react";
import { Modal } from "../components/Modal";
import { Badge } from "../components/Badge";
import { Menu } from "../components/Menu";
import { CopyableId } from "../components/CopyableId";
import { EmptyState } from "../components/EmptyState";
import { PasswordInput } from "../components/PasswordInput";
import { useConfirmDialog } from "../components/ConfirmDialog";
import { useToast } from "../components/ToastProvider";
import { AppsIcon, PlusIcon } from "../components/Icons";
import { IntegrationModal } from "../components/IntegrationModal";
import { AccessGrant, api, ApiError, AppUser, Client, UserPage, UserRoleRow } from "../api";

const GRANT_LABELS: Record<string, string> = {
  authorization_code: "Let a person log in",
  refresh_token: "Keep them signed in without repeating login",
  client_credentials: "Talk directly to the server with no person involved",
};

const CLIENT_TYPE_LABELS: Record<string, string> = {
  confidential: "Confidential — runs on your own server, can keep a secret safely",
  public: "Public — runs in a browser or on a device, can't keep a secret safely",
};

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
      });
      setModalOpen(false);
      setCreated(result);
      setClientId("");
      setRedirectUris("");
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
    load();
  };

  const toggleRestrictAccess = async (client: Client) => {
    await api.post(`/clients/${client.client_id}/toggle-restrict-access`);
    load();
  };

  const toggleRolesEnabled = async (client: Client) => {
    await api.post(`/clients/${client.client_id}/toggle-roles-enabled`);
    load();
  };

  const toggleSignupRoleSelection = async (client: Client) => {
    await api.post(`/clients/${client.client_id}/toggle-signup-role-selection`);
    load();
  };

  // One button in the Manage modal saves everything at once -- the fact
  // that this is three separate API calls under the hood is not the
  // admin's problem.
  const saveAll = async (client: Client, fields: SaveFields) => {
    const calls: Promise<unknown>[] = [];
    if (fields.details) {
      calls.push(
        api.patch(`/clients/${client.client_id}`, {
          client_name: fields.details.name,
          redirect_uris: fields.details.uris,
          scope: fields.details.scope,
        }),
      );
    }
    if (fields.branding) {
      calls.push(
        api.post(`/clients/${client.client_id}/branding`, {
          logo_url: fields.branding.logoUrl,
          brand_color: fields.branding.brandColor,
        }),
      );
    }
    if (fields.thumbprint !== undefined) {
      calls.push(api.post(`/clients/${client.client_id}/mtls`, { thumbprint: fields.thumbprint }));
    }
    if (calls.length === 0) return;
    await Promise.all(calls);
    show("Saved");
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
                <th>Source</th>
                <th>Login group</th>
                <th>Status</th>
                <th>Signup</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {filtered?.length === 0 && (
                <tr>
                  <td colSpan={7}>No applications match "{search}".</td>
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
                    Where should we send people back to after login? <span className="field__hint">(one per line)</span>
                  </label>
                  {preset === "native" && (
                    <div style={{ display: "flex", gap: 5, marginBottom: 4 }}>
                      <button
                        type="button"
                        className="btn btn--secondary"
                        style={{ height: 22, fontSize: 11, padding: "0 6px" }}
                        onClick={() =>
                          setRedirectUris((prev) =>
                            prev ? `${prev}\nhttp://localhost:5173/callback` : "http://localhost:5173/callback"
                          )
                        }
                      >
                        + Localhost:5173
                      </button>
                      <button
                        type="button"
                        className="btn btn--secondary"
                        style={{ height: 22, fontSize: 11, padding: "0 6px" }}
                        onClick={() =>
                          setRedirectUris((prev) =>
                            prev ? `${prev}\nhttp://127.0.0.1:8080/callback` : "http://127.0.0.1:8080/callback"
                          )
                        }
                      >
                        + 127.0.0.1:8080
                      </button>
                      <button
                        type="button"
                        className="btn btn--secondary"
                        style={{ height: 22, fontSize: 11, padding: "0 6px" }}
                        onClick={() =>
                          setRedirectUris((prev) => (prev ? `${prev}\nvscode://callback` : "vscode://callback"))
                        }
                      >
                        + VS Code
                      </button>
                    </div>
                  )}
                </div>
                <textarea
                  id="redirect_uris"
                  rows={2}
                  required
                  placeholder="https://yourapp.com/callback"
                  value={redirectUris}
                  onChange={(e) => setRedirectUris(e.target.value)}
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
            <strong>{created.client_id}</strong> was added.
          </p>
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
        <ManageDrawer
          client={managing}
          onClose={() => setManaging(null)}
          onSave={(fields) => saveAll(managing, fields)}
          onToggleRestrictAccess={() => toggleRestrictAccess(managing)}
          onToggleRolesEnabled={() => toggleRolesEnabled(managing)}
          onToggleSignupRoleSelection={() => toggleSignupRoleSelection(managing)}
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

function displayName(client: Client) {
  return client.client_name || "Unnamed application";
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
      <td>
        {client.registration_method === "cimd" && <Badge variant="neutral">CIMD</Badge>}
        {client.registration_method === "dcr" && <Badge variant="neutral">DCR</Badge>}
        {client.registration_method === "static" && <Badge variant="neutral">Added by you</Badge>}
      </td>
      <td>{client.pool_name ?? <span style={{ color: "var(--text-muted)", fontStyle: "italic" }}>Standalone</span>}</td>
      <td>
        <Badge variant={client.enabled ? "success" : "neutral"}>{client.enabled ? "Active" : "Disabled"}</Badge>
      </td>
      <td>
        <Badge variant={client.allow_signup ? "success" : "neutral"}>
          {client.allow_signup ? "Allowed" : "Admin-only"}
        </Badge>
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
              ...(client.registration_method !== "cimd"
                ? [{ label: client.allow_signup ? "Disable signup" : "Enable signup", onSelect: onToggleSignup }]
                : []),
              { label: client.enabled ? "Disable" : "Re-enable", onSelect: onDisable, danger: client.enabled },
            ]}
          />
        </div>
      </td>
    </tr>
  );
}

interface SaveFields {
  // Each section is only present when it actually changed from the
  // client's current saved values -- Save changes is one button, but it
  // must not blindly re-POST branding/mtls (or overwrite them with stale
  // values) just because the admin only touched the name or scope.
  details?: { name: string; uris: string; scope: string };
  branding?: { logoUrl: string; brandColor: string };
  thumbprint?: string;
}

function ManageDrawer({
  client,
  onClose,
  onSave,
  onToggleRestrictAccess,
  onToggleRolesEnabled,
  onToggleSignupRoleSelection,
}: {
  client: Client;
  onClose: () => void;
  onSave: (fields: SaveFields) => void;
  onToggleRestrictAccess: () => void;
  onToggleRolesEnabled: () => void;
  onToggleSignupRoleSelection: () => void;
}) {
  const editable = client.registration_method !== "cimd";
  const showBranding = editable && client.grant_types.includes("authorization_code");

  const [thumbprint, setThumbprint] = useState(client.mtls_cert_thumbprint ?? "");
  const [logoUrl, setLogoUrl] = useState(client.logo_url ?? "");
  const [brandColor, setBrandColor] = useState(client.brand_color ?? "");
  const [name, setName] = useState(client.client_name ?? "");
  const [redirectUris, setRedirectUris] = useState(client.redirect_uris.join("\n"));
  const [scope, setScope] = useState(client.allowed_scope);
  const [grants, setGrants] = useState<AccessGrant[] | null>(null);
  const [poolUsers, setPoolUsers] = useState<AppUser[]>([]);
  const [grantUserId, setGrantUserId] = useState("");
  const [grantBusy, setGrantBusy] = useState(false);
  const [roleNames, setRoleNames] = useState<string[]>([]);
  const [userRoles, setUserRoles] = useState<UserRoleRow[] | null>(null);
  const [newRoleName, setNewRoleName] = useState("");
  const [roleBusy, setRoleBusy] = useState(false);
  const [addUserOpen, setAddUserOpen] = useState(false);
  const [userEmail, setUserEmail] = useState("");
  const [userPassword, setUserPassword] = useState("");
  const [userConfirmPassword, setUserConfirmPassword] = useState("");
  const [userEmailVerified, setUserEmailVerified] = useState(true);
  const [userError, setUserError] = useState<string | null>(null);
  const [addingUser, setAddingUser] = useState(false);
  const { show } = useToast();

  const onAddUser = async (e: FormEvent) => {
    e.preventDefault();
    setUserError(null);
    if (userPassword !== userConfirmPassword) {
      setUserError("Passwords do not match");
      return;
    }
    setAddingUser(true);
    try {
      const created = await api.post<{ id: string }>("/users", {
        email: userEmail,
        password: userPassword,
        confirm_password: userConfirmPassword,
        client_id: client.client_id,
        email_verified: userEmailVerified,
      });
      if (client.restrict_access) {
        await api.post(`/clients/${client.client_id}/access`, { user_id: created.id });
      }
      setAddUserOpen(false);
      setUserEmail("");
      setUserPassword("");
      setUserConfirmPassword("");
      show(`${userEmail} can now log into ${displayName(client)}`);
      loadAccess();
    } catch (err) {
      setUserError(err instanceof ApiError ? err.message : "Something went wrong");
    } finally {
      setAddingUser(false);
    }
  };

  const loadAccess = () => {
    if (client.restrict_access) api.get<AccessGrant[]>(`/clients/${client.client_id}/access`).then(setGrants);
  };

  const loadRoles = () => {
    if (!client.roles_enabled) return;
    api.get<string[]>(`/clients/${client.client_id}/roles`).then(setRoleNames);
    api.get<UserRoleRow[]>(`/clients/${client.client_id}/user-roles`).then(setUserRoles);
  };

  useEffect(() => {
    const userParam = client.pool_name
      ? `pool=${encodeURIComponent(client.pool_name)}`
      : `client=${encodeURIComponent(client.client_id)}`;
    api.get<UserPage>(`/users?${userParam}&page_size=500`).then((p) => setPoolUsers(p.items));
    loadAccess();
    loadRoles();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [client.restrict_access, client.roles_enabled, client.client_id, client.pool_name]);

  const grantAccess = async () => {
    if (!grantUserId) return;
    setGrantBusy(true);
    try {
      await api.post(`/clients/${client.client_id}/access`, { user_id: grantUserId });
      setGrantUserId("");
      loadAccess();
    } finally {
      setGrantBusy(false);
    }
  };

  const revokeAccess = async (userId: string) => {
    await api.delete(`/clients/${client.client_id}/access/${userId}`);
    loadAccess();
  };

  const addRole = async () => {
    const name = newRoleName.trim();
    if (!name) return;
    setRoleBusy(true);
    try {
      await api.post(`/clients/${client.client_id}/roles`, { name });
      setNewRoleName("");
      loadRoles();
    } finally {
      setRoleBusy(false);
    }
  };

  const removeRole = async (name: string) => {
    await api.delete(`/clients/${client.client_id}/roles/${encodeURIComponent(name)}`);
    loadRoles();
  };

  const toggleUserRole = async (userId: string, roleName: string, has: boolean) => {
    if (has) {
      await api.delete(`/users/${userId}/roles/${client.client_id}/${encodeURIComponent(roleName)}`);
    } else {
      await api.post(`/users/${userId}/roles`, { client_id: client.client_id, role: roleName });
    }
    loadRoles();
  };

  return (
    <Modal title={displayName(client)} wide onClose={onClose}>
      <div className="field">
        <label>Client ID</label>
        <CopyableId value={client.client_id} max={9999} />
      </div>
      <div className="field">
        <label>Type</label>
        <span style={{ fontSize: 14 }}>{CLIENT_TYPE_LABELS[client.client_type] ?? client.client_type}</span>
      </div>
      <div className="field">
        <label>Grant types</label>
        <span style={{ fontSize: 14 }}>{client.grant_types.map((g) => GRANT_LABELS[g] ?? g).join(", ")}</span>
      </div>
      <div className="field">
        <label>Login group</label>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
          <span style={{ fontSize: 14 }}>{client.pool_name ?? <em style={{ color: "var(--text-muted)" }}>None (standalone)</em>}</span>
          <button type="button" className="btn btn--secondary" onClick={() => setAddUserOpen(true)}>
            + Add user
          </button>
        </div>
        <span className="field__hint">
          {client.restrict_access
            ? client.pool_name
              ? "Users in other login groups can't log in here — and within this group, only the people granted access below can."
              : "Only the users explicitly granted access below can log in."
            : client.pool_name
              ? "Anyone added here can log into this app. Users in other login groups can't."
              : "Any user of this application can log in."}
        </span>
      </div>

      {editable && (
        <div className="field">
          <label style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <input type="checkbox" checked={client.restrict_access} onChange={onToggleRestrictAccess} />
            Restrict which users in this group can use this app
          </label>
          <span className="field__hint">
            {client.pool_name
              ? <>Off (default): everyone in <strong>{client.pool_name}</strong> can log in here. On: only
                people explicitly granted below can — same group, same passwords, but this one app is
                locked down to a subset. The same pattern as Okta's or Entra ID's "app assignment."</>
              : <>Off (default): all users of this app can log in. On: only people explicitly granted
                below can — useful for keeping most accounts out of a privileged interface.</>}
          </span>

          {client.restrict_access && (
            <div style={{ marginTop: 12 }}>
              {grants === null ? (
                <p className="field__hint">Loading...</p>
              ) : grants.length === 0 ? (
                <p className="field__hint">No one has been granted access yet — this app is unreachable until you add someone below.</p>
              ) : (
                <ul style={{ listStyle: "none", margin: "0 0 10px", padding: 0, display: "flex", flexDirection: "column", gap: 6 }}>
                  {grants.map((g) => (
                    <li key={g.user_id} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", fontSize: 13.5 }}>
                      {g.email}
                      <button type="button" className="btn btn--secondary" onClick={() => revokeAccess(g.user_id)}>
                        Revoke
                      </button>
                    </li>
                  ))}
                </ul>
              )}

              <div style={{ display: "flex", gap: 8 }}>
                <select value={grantUserId} onChange={(e) => setGrantUserId(e.target.value)} style={{ flex: 1 }}>
                  <option value="">Choose a user{client.pool_name ? ` from ${client.pool_name}` : ""}...</option>
                  {poolUsers
                    .filter((u) => !grants?.some((g) => g.user_id === u.id))
                    .map((u) => (
                      <option value={u.id} key={u.id}>
                        {u.email}
                      </option>
                    ))}
                </select>
                <button type="button" className="btn btn--secondary" disabled={!grantUserId || grantBusy} onClick={grantAccess}>
                  Grant
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      {editable && (
        <div className="field">
          <label style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <input type="checkbox" checked={client.roles_enabled} onChange={onToggleRolesEnabled} />
            Use custom roles for this app
          </label>
          <span className="field__hint">
            Off (default). On: define role names below (e.g. "editor", "billing") and assign them
            to users. This service only reports a user's roles to your app — as a "roles" claim
            from /userinfo — it never decides what a role is allowed to do. That's up to your app.
          </span>

          {client.roles_enabled && (
            <div style={{ marginTop: 12 }}>
              {client.allow_signup && (
                <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13.5, marginBottom: 12 }}>
                  <input
                    type="checkbox"
                    checked={client.allow_signup_role_selection}
                    onChange={onToggleSignupRoleSelection}
                  />
                  Let people choose a role when they sign up (off by default — otherwise an admin assigns it here)
                </label>
              )}

              <div style={{ display: "flex", gap: 8, marginBottom: 12 }}>
                <input
                  placeholder="Role name, e.g. editor"
                  value={newRoleName}
                  onChange={(e) => setNewRoleName(e.target.value)}
                  style={{ flex: 1 }}
                />
                <button type="button" className="btn btn--secondary" disabled={!newRoleName.trim() || roleBusy} onClick={addRole}>
                  Add role
                </button>
              </div>

              {roleNames.length === 0 ? (
                <p className="field__hint">No roles defined yet.</p>
              ) : userRoles === null ? (
                <p className="field__hint">Loading...</p>
              ) : (
                <div className="table-wrap">
                  <table className="table">
                    <thead>
                      <tr>
                        <th>User</th>
                        {roleNames.map((r) => (
                          <th key={r}>
                            {r}{" "}
                            <button
                              type="button"
                              className="btn btn--ghost"
                              title={`Delete role "${r}"`}
                              onClick={() => removeRole(r)}
                            >
                              ×
                            </button>
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {userRoles.map((row) => (
                        <tr key={row.user_id}>
                          <td style={{ fontSize: 13.5 }}>{row.email}</td>
                          {roleNames.map((r) => {
                            const has = row.roles.includes(r);
                            return (
                              <td key={r} style={{ textAlign: "center" }}>
                                <input
                                  type="checkbox"
                                  checked={has}
                                  onChange={() => toggleUserRole(row.user_id, r, has)}
                                />
                              </td>
                            );
                          })}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {addUserOpen && (
        <Modal title={`Add a user to ${displayName(client)}`} onClose={() => setAddUserOpen(false)}>
          <p style={{ fontSize: 13, color: "var(--text-muted)", marginTop: -8 }}>
            {client.pool_name
              ? <>This user will be able to log into <strong>{displayName(client)}</strong> (and any other
                app in the <strong>{client.pool_name}</strong> login group).</>
              : <>This user will be able to log into <strong>{displayName(client)}</strong>.</>}
          </p>
          {userError && <div className="alert alert--error">{userError}</div>}
          <form onSubmit={onAddUser}>
            <div className="field">
              <label htmlFor="drawer-add-email">Email</label>
              <input
                id="drawer-add-email"
                type="email"
                required
                autoFocus
                value={userEmail}
                onChange={(e) => setUserEmail(e.target.value)}
              />
            </div>
            <div className="field">
              <label htmlFor="drawer-add-password">Password</label>
              <PasswordInput
                id="drawer-add-password"
                required
                minLength={8}
                value={userPassword}
                onChange={(e) => setUserPassword(e.target.value)}
              />
            </div>
            <div className="field">
              <label htmlFor="drawer-add-confirm-password">Confirm password</label>
              <PasswordInput
                id="drawer-add-confirm-password"
                required
                minLength={8}
                value={userConfirmPassword}
                onChange={(e) => setUserConfirmPassword(e.target.value)}
              />
            </div>
            <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 14, marginBottom: 16 }}>
              <input
                type="checkbox"
                checked={userEmailVerified}
                onChange={(e) => setUserEmailVerified(e.target.checked)}
              />
              Treat their email as already verified
            </label>
            <span className="field__hint" style={{ display: "block", marginTop: -12, marginBottom: 16 }}>
              Off: they get the same "Unverified" badge and verification email a self-signup gets.
            </span>
            <button type="submit" className="btn btn--primary btn--block" disabled={addingUser}>
              Add user
            </button>
          </form>
        </Modal>
      )}

      {editable && (
        <>
          <hr style={{ border: "none", borderTop: "1px solid var(--border)", margin: "20px 0" }} />

          <div className="field">
            <label htmlFor="edit-name">Name</label>
            <input id="edit-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="Unnamed application" />
          </div>
          {client.application_type !== "service" && (
            <div className="field">
              <label htmlFor="edit-redirects">
                Redirect URIs <span className="field__hint">(one per line)</span>
              </label>
              <textarea
                id="edit-redirects"
                rows={2}
                style={{ fontFamily: "var(--font-mono)", fontSize: 12.5 }}
                value={redirectUris}
                onChange={(e) => setRedirectUris(e.target.value)}
              />
            </div>
          )}
          <div className="field">
            <label htmlFor="edit-scope">
              Allowed scopes <span className="field__hint">(space-separated)</span>
            </label>
            <input id="edit-scope" value={scope} onChange={(e) => setScope(e.target.value)} placeholder="openid profile email" />
          </div>

          {showBranding && (
            <>
              <div className="field">
                <label htmlFor="logo_url">
                  Logo URL <span className="field__hint">(shown on this app's login/signup/consent pages)</span>
                </label>
                <input id="logo_url" value={logoUrl} onChange={(e) => setLogoUrl(e.target.value)} placeholder="https://yourapp.com/logo.png" />
              </div>
              <div className="field">
                <label htmlFor="brand_color">Brand color</label>
                <input id="brand_color" value={brandColor} onChange={(e) => setBrandColor(e.target.value)} placeholder="#1d4ed8" />
              </div>
            </>
          )}

          <div className="field">
            <label htmlFor="mtls">
              mTLS certificate thumbprint <span className="field__hint">(rarely needed)</span>
            </label>
            <input
              id="mtls"
              value={thumbprint}
              onChange={(e) => setThumbprint(e.target.value)}
              placeholder="Cert thumbprint (hex)"
              style={{ fontFamily: "var(--font-mono)" }}
            />
            <span className="field__hint">
              Only checked for apps that talk directly to the server (not ones a person logs into
              through a browser) — leave blank unless you've set up mutual TLS for it.
            </span>
          </div>

          <button
            type="button"
            className="btn btn--primary btn--block"
            onClick={() => {
              const fields: SaveFields = {};
              if (
                name !== (client.client_name ?? "") ||
                redirectUris !== client.redirect_uris.join("\n") ||
                scope !== client.allowed_scope
              ) {
                fields.details = { name, uris: redirectUris, scope };
              }
              if (showBranding && (logoUrl !== (client.logo_url ?? "") || brandColor !== (client.brand_color ?? ""))) {
                fields.branding = { logoUrl, brandColor };
              }
              if (thumbprint !== (client.mtls_cert_thumbprint ?? "")) {
                fields.thumbprint = thumbprint;
              }
              if (!fields.details && !fields.branding && fields.thumbprint === undefined) {
                show("Nothing to save");
                return;
              }
              onSave(fields);
            }}
          >
            Save changes
          </button>

        </>
      )}
    </Modal>
  );
}
