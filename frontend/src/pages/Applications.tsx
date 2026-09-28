import { FormEvent, useEffect, useState } from "react";
import { Modal } from "../components/Modal";
import { AppsIcon, PlusIcon } from "../components/Icons";
import { api, ApiError, Client, Pool } from "../api";

const GRANT_LABELS: Record<string, string> = {
  authorization_code: "Let a person log in",
  refresh_token: "Keep them signed in without repeating login",
  client_credentials: "Talk directly to the server with no person involved",
};

type Preset = "website" | "native" | "service";
type Sharing = "shared" | "isolated" | "custom";

const PRESET_DEFAULTS: Record<Preset, { clientType: string; applicationType: string; grants: string[] }> = {
  website: { clientType: "confidential", applicationType: "web", grants: ["authorization_code", "refresh_token"] },
  native: { clientType: "public", applicationType: "native", grants: ["authorization_code", "refresh_token"] },
  service: { clientType: "confidential", applicationType: "service", grants: ["client_credentials"] },
};

export function Applications() {
  const [clients, setClients] = useState<Client[] | null>(null);
  const [pools, setPools] = useState<Pool[]>([]);
  const [modalOpen, setModalOpen] = useState(false);
  const [created, setCreated] = useState<Client | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const [preset, setPreset] = useState<Preset>("website");
  const [clientId, setClientId] = useState("");
  const [redirectUris, setRedirectUris] = useState("");
  const [sharing, setSharing] = useState<Sharing>("shared");
  const [customPool, setCustomPool] = useState("");
  const [allowSignup, setAllowSignup] = useState(true);
  const [clientType, setClientType] = useState("confidential");
  const [grants, setGrants] = useState<string[]>(PRESET_DEFAULTS.website.grants);
  const [scope, setScope] = useState("");

  const load = () => api.get<Client[]>("/clients").then(setClients);

  useEffect(() => {
    load();
    api.get<Pool[]>("/pools").then(setPools);
  }, []);

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
    if (sharing === "shared") return "default";
    if (sharing === "isolated") return clientId.trim() || "default";
    return customPool.trim() || "default";
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
        client_type: clientType,
        redirect_uris: redirectUris,
        grant_types: grants,
        scope,
        application_type: PRESET_DEFAULTS[preset].applicationType,
        user_pool: resolvedPool(),
        allow_signup: allowSignup,
      });
      setModalOpen(false);
      setCreated(result);
      setClientId("");
      setRedirectUris("");
      setScope("");
      load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong");
    } finally {
      setSubmitting(false);
    }
  };

  const toggleEnabled = async (id: string) => {
    await api.post(`/clients/${id}/toggle-enabled`);
    load();
  };

  const toggleSignup = async (id: string) => {
    await api.post(`/clients/${id}/toggle-signup`);
    load();
  };

  const saveMtls = async (id: string, thumbprint: string) => {
    await api.post(`/clients/${id}/mtls`, { thumbprint });
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
        <button type="button" className="btn btn--primary" onClick={() => setModalOpen(true)}>
          <PlusIcon width={16} height={16} style={{ verticalAlign: -3 }} /> Add application
        </button>
      </div>

      <p className="lead">
        An <strong>application</strong> is anything that lets people log in — a website, a mobile
        app, or an AI assistant like ChatGPT or Claude connecting to your service. Click "Add
        application" above for every app you want to connect.
      </p>

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
            <th>mTLS thumbprint</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {clients?.length === 0 && (
            <tr>
              <td colSpan={8}>No applications yet — click "Add application" above to add your first one.</td>
            </tr>
          )}
          {clients?.map((c) => (
            <ClientRow
              key={c.id}
              client={c}
              onToggleEnabled={() => toggleEnabled(c.client_id)}
              onToggleSignup={() => toggleSignup(c.client_id)}
              onSaveMtls={(t) => saveMtls(c.client_id, t)}
            />
          ))}
        </tbody>
      </table>
      </div>
      <p className="field__hint" style={{ marginTop: 8 }}>
        <strong>Disable</strong> immediately blocks an app from letting anyone log in or refresh a
        token, without deleting it — use this for a compromised secret or a retired app while
        keeping its history. mTLS thumbprint is only checked for apps that talk directly to the
        server (not ones a person logs into through a browser) — leave blank unless you've set up
        mutual TLS for it.
      </p>

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

            <div className="field">
              <label htmlFor="client_id">Give it a name</label>
              <input
                id="client_id"
                required
                placeholder="e.g. marketing-site, support-bot"
                value={clientId}
                onChange={(e) => setClientId(e.target.value)}
              />
              <span className="field__hint">Just an internal label so you can recognize it later.</span>
            </div>

            {preset !== "service" && (
              <div className="field">
                <label htmlFor="redirect_uris">
                  Where should we send people back to after login? <span className="field__hint">(one per line)</span>
                </label>
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
                  title="Share logins with my other apps"
                  desc="One account works everywhere — recommended for most apps in the same company. Also covers AI assistants that connect automatically."
                />
                <SharingCard
                  checked={sharing === "isolated"}
                  onSelect={() => setSharing("isolated")}
                  title="Keep this app's users separate"
                  desc="Its own private list of accounts — good for an internal admin tool or a client-specific deployment."
                />
                <SharingCard
                  checked={sharing === "custom"}
                  onSelect={() => setSharing("custom")}
                  title="Use a specific existing group"
                  desc="Pick this if you've already set up a named login group for a subset of your apps."
                />
              </div>
              {sharing === "custom" && (
                <input
                  style={{ marginTop: 10 }}
                  list="pool-options"
                  placeholder="group name"
                  value={customPool}
                  onChange={(e) => setCustomPool(e.target.value)}
                />
              )}
              <datalist id="pool-options">
                {pools.map((p) => (
                  <option value={p.name} key={p.id} />
                ))}
              </datalist>
            </div>

            {preset !== "service" && (
              <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 14 }}>
                <input type="checkbox" checked={allowSignup} onChange={(e) => setAllowSignup(e.target.checked)} />
                Let new users sign themselves up (turn off if only you should add users, in Users)
              </label>
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
              </div>
            </details>

            <button type="submit" className="btn btn--primary btn--block" disabled={submitting}>
              Add application
            </button>
          </form>
        </Modal>
      )}

      {created && (
        <Modal title="Application created" onClose={() => setCreated(null)}>
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
          <button type="button" className="btn btn--primary btn--block" onClick={() => setCreated(null)}>
            Done
          </button>
        </Modal>
      )}
    </>
  );
}

function SharingCard({
  checked,
  onSelect,
  title,
  desc,
}: {
  checked: boolean;
  onSelect: () => void;
  title: string;
  desc: string;
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
        cursor: "pointer",
      }}
    >
      <span style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <input type="radio" checked={checked} onChange={onSelect} />
        <span style={{ fontWeight: 600, fontSize: 13.5 }}>{title}</span>
      </span>
      <span style={{ fontSize: 12.5, color: "var(--text-muted)" }}>{desc}</span>
    </label>
  );
}

function ClientRow({
  client,
  onToggleEnabled,
  onToggleSignup,
  onSaveMtls,
}: {
  client: Client;
  onToggleEnabled: () => void;
  onToggleSignup: () => void;
  onSaveMtls: (thumbprint: string) => void;
}) {
  const [thumbprint, setThumbprint] = useState(client.mtls_cert_thumbprint ?? "");
  const shownId =
    client.registration_method === "cimd" && client.client_id.length > 40
      ? `${client.client_id.slice(0, 40)}…`
      : client.client_id;

  return (
    <tr style={{ opacity: client.enabled ? 1 : 0.55 }}>
      <td>
        {client.client_name ? (
          <>
            {client.client_name} <span className="field__hint">({shownId})</span>
          </>
        ) : (
          shownId
        )}
      </td>
      <td>{client.client_type}</td>
      <td>
        {client.registration_method === "cimd" && <span className="badge badge--off">CIMD</span>}
        {client.registration_method === "dcr" && <span className="badge badge--off">DCR</span>}
        {client.registration_method === "static" && <span className="badge badge--off">Added by you</span>}
      </td>
      <td>{client.pool_name}</td>
      <td>
        <span className={`badge ${client.enabled ? "badge--on" : "badge--off"}`}>
          {client.enabled ? "Active" : "Disabled"}
        </span>
      </td>
      <td>
        <span className={`badge ${client.allow_signup ? "badge--on" : "badge--off"}`}>
          {client.allow_signup ? "Allowed" : "Admin-only"}
        </span>
      </td>
      <td>
        {client.registration_method === "cimd" ? (
          <span className="field__hint">not applicable</span>
        ) : (
          <div style={{ display: "flex", gap: 6 }}>
            <input
              value={thumbprint}
              onChange={(e) => setThumbprint(e.target.value)}
              placeholder="SHA-256 cert thumbprint"
              style={{ fontSize: 12.5, padding: "6px 8px", width: 170 }}
            />
            <button type="button" className="btn btn--secondary" onClick={() => onSaveMtls(thumbprint)}>
              Save
            </button>
          </div>
        )}
      </td>
      <td>
        <div style={{ display: "flex", flexDirection: "column", gap: 6, alignItems: "flex-start" }}>
          <button type="button" className="btn btn--secondary" onClick={onToggleEnabled}>
            {client.enabled ? "Disable" : "Re-enable"}
          </button>
          {client.registration_method !== "cimd" && (
            <button type="button" className="btn btn--secondary" onClick={onToggleSignup}>
              {client.allow_signup ? "Disable signup" : "Enable signup"}
            </button>
          )}
        </div>
      </td>
    </tr>
  );
}
