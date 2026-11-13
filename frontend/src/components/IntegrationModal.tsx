import { useEffect, useState } from "react";
import { Modal } from "./Modal";
import { CodeBlock } from "./CodeBlock";
import { CopyableId } from "./CopyableId";
import { Badge } from "./Badge";
import { api, Client, Resource, SystemEndpoints } from "../api";

interface IntegrationModalProps {
  onClose: () => void;
  resource?: Resource | null;
  client?: Client | null;
  clientSecret?: string | null;
  allClients?: Client[];
  onSelectClient?: (client: Client | null) => void;
  /** When true, hides the MCP resource selector — used from the Applications page */
  appOnly?: boolean;
}

export function IntegrationModal({
  onClose,
  resource,
  client,
  clientSecret,
  allClients: initialClients,
  onSelectClient,
  appOnly,
}: IntegrationModalProps) {
  const [endpoints, setEndpoints] = useState<SystemEndpoints | null>(null);
  const [allResources, setAllResources] = useState<Resource[]>([]);
  const [availableClients, setAvailableClients] = useState<Client[]>(initialClients ?? []);
  const [activeClient, setActiveClient] = useState<Client | null>(client ?? null);
  const [selectedResourceId, setSelectedResourceId] = useState<string>("");
  const [tab, setTab] = useState<string>("");
  const [pastedSecret, setPastedSecret] = useState("");

  // Sync client prop if changed externally
  useEffect(() => {
    if (client !== undefined) {
      setActiveClient(client);
    }
  }, [client]);

  useEffect(() => {
    api.get<SystemEndpoints>("/system/endpoints").then(setEndpoints);
    api.get<Resource[]>("/resources").then((res) => {
      setAllResources(res);
      if (res.length > 0) {
        setSelectedResourceId(res[0].resource_id);
      }
    });
    if (!initialClients || initialClients.length === 0) {
      api.get<Client[]>("/clients").then((cls) => {
        setAvailableClients(cls);
        if (!client && !resource && cls.length > 0) {
          setActiveClient(cls[0]);
        }
      });
    } else if (!client && !resource && initialClients.length > 0) {
      setActiveClient(initialClients[0]);
    }
  }, [initialClients, client, resource]);

  // Set default tab
  useEffect(() => {
    if (resource) setTab("python");
    else if (activeClient?.application_type === "service") setTab("service");
    else if (activeClient?.application_type === "native") setTab("mobile");
    else setTab("website");
  }, [resource, activeClient]);

  if (!endpoints) {
    return (
      <Modal title="Integration Guide" wide onClose={onClose}>
        <div style={{ padding: 24, textAlign: "center", color: "var(--text-muted)" }}>
          Loading integration metadata…
        </div>
      </Modal>
    );
  }

  const isPublicClient = activeClient?.client_type === "public";
  const effectiveSecret = clientSecret || pastedSecret;

  const activeResourceId = resource
    ? resource.resource_id
    : selectedResourceId || "https://mcp.yourdomain.com";

  const prmUrl = `${endpoints.prm_endpoint}?resource=${encodeURIComponent(activeResourceId)}`;
  const issuerBase = endpoints.issuer.replace(/\/$/, "");

  const currentClientId = activeClient?.client_id || "YOUR_CLIENT_ID";
  const currentRedirectUri = activeClient?.redirect_uris?.[0] || "https://yourapp.com/callback";
  const clientDisplayName = activeClient?.client_name || activeClient?.client_id || "Your Application";

  const handleClientChange = (clientId: string) => {
    const found = availableClients.find((c) => c.id === clientId) ?? null;
    setActiveClient(found);
    onSelectClient?.(found);
  };

  return (
    <Modal
      title={
        resource
          ? `Integration Guide: ${resource.name}`
          : activeClient
          ? `Integration Guide: ${clientDisplayName}`
          : "Integration Guide"
      }
      wide
      onClose={onClose}
    >
      {/* Endpoints overview strip */}
      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          gap: 12,
          padding: 12,
          background: "var(--surface-2)",
          border: "1px solid var(--border)",
          borderRadius: "var(--radius-md)",
          marginBottom: 16,
          fontSize: 12.5,
        }}
      >
        <div style={{ flex: "1 1 200px" }}>
          <span style={{ color: "var(--text-muted)", display: "block", fontSize: 11, fontWeight: 600 }}>
            ISSUER
          </span>
          <CopyableId value={endpoints.issuer} max={38} />
        </div>
        <div style={{ flex: "1 1 200px" }}>
          <span style={{ color: "var(--text-muted)", display: "block", fontSize: 11, fontWeight: 600 }}>
            DISCOVERY URL
          </span>
          <CopyableId value={endpoints.openid_configuration} max={38} />
        </div>
        <div style={{ flex: "1 1 200px" }}>
          <span style={{ color: "var(--text-muted)", display: "block", fontSize: 11, fontWeight: 600 }}>
            JWKS URI
          </span>
          <CopyableId value={endpoints.jwks_uri} max={38} />
        </div>
      </div>

      {/* Select Application Dropdown (only in application mode) */}
      {!resource && availableClients.length > 0 && (
        <div className="field" style={{ marginBottom: 14 }}>
          <label htmlFor="active-app-picker" style={{ fontWeight: 600 }}>
            Application
          </label>
          <select
            id="active-app-picker"
            value={activeClient?.id ?? ""}
            onChange={(e) => handleClientChange(e.target.value)}
          >
            {availableClients.map((c) => (
              <option key={c.id} value={c.id}>
                {c.client_name || c.client_id} ({c.client_type}, {c.pool_name ?? "standalone"})
              </option>
            ))}
            <option value="">Example values</option>
          </select>
        </div>
      )}

      {/* Target Resource selector if configuring an Application (hidden in app-only mode) */}
      {!resource && !appOnly && allResources.length > 0 && (
        <div className="field" style={{ marginBottom: 14 }}>
          <label htmlFor="target-resource-select">API or MCP server</label>
          <select
            id="target-resource-select"
            value={selectedResourceId}
            onChange={(e) => setSelectedResourceId(e.target.value)}
          >
            {allResources.map((r) => (
              <option key={r.resource_id} value={r.resource_id}>
                {r.name} ({r.resource_id})
              </option>
            ))}
          </select>
        </div>
      )}

      {/* Client secret handling for confidential applications */}
      {!resource && activeClient && !isPublicClient && (
        <div className="field" style={{ marginBottom: 16 }}>
          <label htmlFor="guide-secret">Client secret</label>
          {clientSecret ? (
            <input id="guide-secret" readOnly value={clientSecret} />
          ) : (
            <input
              id="guide-secret"
              placeholder="Paste it to fill in the examples"
              value={pastedSecret}
              onChange={(e) => setPastedSecret(e.target.value)}
            />
          )}
          <span className="field__hint">
            {clientSecret ? "Shown only once. Save it now." : "Stays in your browser."}
          </span>
        </div>
      )}

      {/* Tab Navigation */}
      <div className="guide-tabs" role="tablist">
        {resource ? (
          <>
            <TabButton active={tab === "python"} onClick={() => setTab("python")}>Python</TabButton>
            <TabButton active={tab === "node"} onClick={() => setTab("node")}>Node</TabButton>
            <TabButton active={tab === "live"} onClick={() => setTab("live")}>Live check</TabButton>
            <TabButton active={tab === "prm"} onClick={() => setTab("prm")}>401 & discovery</TabButton>
          </>
        ) : (
          <>
            <TabButton active={tab === "website"} onClick={() => setTab("website")}>Website</TabButton>
            <TabButton active={tab === "spa"} onClick={() => setTab("spa")}>Single-page app</TabButton>
            <TabButton active={tab === "mobile"} onClick={() => setTab("mobile")}>Mobile</TabButton>
            <TabButton active={tab === "embed"} onClick={() => setTab("embed")}>Embedded</TabButton>
            <TabButton active={tab === "popup"} onClick={() => setTab("popup")}>Popup</TabButton>
            {!appOnly && (
              <TabButton active={tab === "assistants"} onClick={() => setTab("assistants")}>AI assistants</TabButton>
            )}
            <TabButton active={tab === "service"} onClick={() => setTab("service")}>Server to server</TabButton>
            <TabButton active={tab === "logout"} onClick={() => setTab("logout")}>Logout</TabButton>
            <TabButton active={tab === "oauth"} onClick={() => setTab("oauth")}>Raw OAuth</TabButton>
            {activeClient?.application_type === "service" && (
              <TabButton active={tab === "mtls"} onClick={() => setTab("mtls")}>mTLS</TabButton>
            )}
          </>
        )}
      </div>

      {/* Tab Contents: Resource Mode */}
      {resource && (
        <div>
          {tab === "python" && (
            <div>
              <p className="guide-lead">Check each request's token with the <code>auth-client</code> SDK.</p>
              <CodeBlock
                language="bash"
                title="Install"
                code={`pip install "auth-client[fastapi] @ https://github.com/codaonic/auth-client/releases/download/v0.4.0/auth_client-0.4.0-py3-none-any.whl"`}
              />
              <CodeBlock
                language="python"
                title="FastAPI"
                code={`from fastapi import Depends, FastAPI
from auth_client import TokenValidator
from auth_client.fastapi import make_auth_dependency
from auth_client.protected_resource import protected_resource_router

ISSUER = "${endpoints.issuer}"
RESOURCE_ID = "${resource.resource_id}"

validator = TokenValidator(issuer=ISSUER, resource_id=RESOURCE_ID)
require_auth = make_auth_dependency(validator)

app = FastAPI()
app.include_router(protected_resource_router(RESOURCE_ID, ISSUER, resource_name="${resource.name}"))

@app.get("/me")
async def me(claims: dict = Depends(require_auth)):
    return {"sub": claims["sub"], "roles": claims.get("roles", [])}`}
              />
            </div>
          )}

          {tab === "node" && (
            <div>
              <p className="guide-lead">Check each request's token with the <code>auth-client</code> SDK.</p>
              <CodeBlock
                language="bash"
                title="Install"
                code={`npm install "https://github.com/codaonic/auth-client/releases/download/v0.4.0/auth-client-0.4.0.tgz"`}
              />
              <CodeBlock
                language="typescript"
                title="Express"
                code={`import express from "express";
import { TokenValidator, protectedResourceRouter } from "auth-client";
import { makeAuthMiddleware } from "auth-client/express";

const ISSUER = "${endpoints.issuer}";
const RESOURCE_ID = "${resource.resource_id}";

const validator = new TokenValidator(ISSUER, RESOURCE_ID);
const app = express();
app.use(protectedResourceRouter(RESOURCE_ID, ISSUER, "${resource.name}"));

app.get("/me", makeAuthMiddleware(validator), (req, res) => {
  res.json({ sub: req.claims?.sub });
});`}
              />
              <p className="guide-note">
                Without the SDK, any JWT library works: verify against <code>{endpoints.jwks_uri}</code> with issuer{" "}
                <code>{endpoints.issuer}</code> and audience <code>{resource.resource_id}</code>.
              </p>
            </div>
          )}

          {tab === "live" && (
            <div>
              <p className="guide-lead">
                Optional. Ask whether a token is still good, so sign-outs and removed access apply at once.
              </p>
              <CodeBlock
                language="bash"
                title="Token introspection (RFC 7662)"
                description="Use the ID and secret of a confidential application."
                code={`curl -s -u "$CLIENT_ID:$CLIENT_SECRET" \\
  -d "token=$ACCESS_TOKEN" \\
  ${issuerBase}/introspect

# {"active": true, "sub": "...", "aud": "${resource.resource_id}", "scope": "..."}
# {"active": false}`}
              />
            </div>
          )}

          {tab === "prm" && (
            <div>
              <p className="guide-lead">
                Answer requests without a token like this. MCP clients then find this service on their own.
              </p>
              <CodeBlock
                language="http"
                title="401 response"
                code={`HTTP/1.1 401 Unauthorized
WWW-Authenticate: Bearer resource_metadata="${prmUrl}"`}
              />
              <CodeBlock
                language="json"
                title="Protected resource metadata (RFC 9728)"
                code={`{
  "resource": "${resource.resource_id}",
  "authorization_servers": ["${endpoints.issuer}"],
  "bearer_methods_supported": ["header"],
  "resource_name": "${resource.name}"
}`}
              />
            </div>
          )}
        </div>
      )}

      {/* Tab Contents: Application Mode */}
      {!resource && (
        <div>
          {tab === "website" && (
            <div>
              <p className="guide-lead">Any OpenID Connect library works. Give it these settings:</p>
              <SettingsTable
                rows={[
                  ["Discovery URL", endpoints.openid_configuration],
                  ["Client ID", currentClientId],
                  ...(isPublicClient ? [] : ([["Client secret", effectiveSecret || "your client secret"]] as [string, string][])),
                  ["Redirect URI", currentRedirectUri],
                  ["Scopes", "openid email profile"],
                  ["Extra parameter", `resource=${activeResourceId}`],
                ]}
              />
              <CodeBlock
                language="python"
                title="Python (Authlib + FastAPI)"
                code={`from authlib.integrations.starlette_client import OAuth
from fastapi import FastAPI, Request
from starlette.middleware.sessions import SessionMiddleware

app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key="change-me")

oauth = OAuth()
oauth.register(
    "auth",
    server_metadata_url="${endpoints.openid_configuration}",
    client_id="${currentClientId}",${
      isPublicClient ? "" : `\n    client_secret="${effectiveSecret || "<your-client-secret>"}",`
    }
    client_kwargs={"scope": "openid email profile", "code_challenge_method": "S256"},
)

@app.get("/login")
async def login(request: Request):
    return await oauth.auth.authorize_redirect(
        request, "${currentRedirectUri}", resource="${activeResourceId}"
    )

@app.get("/callback")
async def callback(request: Request):
    token = await oauth.auth.authorize_access_token(request)  # checks the ID token
    request.session["user"] = token["userinfo"]  # sub, email, name, roles
    return {"signed_in_as": token["userinfo"]["email"]}`}
              />
            </div>
          )}

          {tab === "spa" && (
            <div>
              <p className="guide-lead">For React, Vue or plain JavaScript. No secret is needed.</p>
              <CodeBlock language="bash" title="Install" code={`npm install oidc-client-ts`} />
              <CodeBlock
                language="typescript"
                title="oidc-client-ts"
                code={`import { UserManager } from "oidc-client-ts";

const auth = new UserManager({
  authority: "${endpoints.issuer}",
  client_id: "${currentClientId}",
  redirect_uri: "${currentRedirectUri}",
  post_logout_redirect_uri: "${activeClient?.post_logout_redirect_uris?.[0] ?? "https://yourapp.com/"}",
  scope: "openid email profile",
  extraQueryParams: { resource: "${activeResourceId}" },
});

// Sign in button
await auth.signinRedirect();

// On your callback page
const user = await auth.signinRedirectCallback();
user.access_token;   // send to your API
user.profile.email;

// Sign out (this app only)
await auth.signoutRedirect();`}
              />
            </div>
          )}

          {tab === "mobile" && (
            <div>
              <p className="guide-lead">
                Use the system browser with AppAuth (iOS and Android) or <code>expo-auth-session</code>. Never a WebView.
              </p>
              <SettingsTable
                rows={[
                  ["Issuer", endpoints.issuer],
                  ["Client ID", currentClientId],
                  ["Redirect URI", currentRedirectUri],
                  ["Scopes", "openid email profile offline_access"],
                  ["Extra parameter", `resource=${activeResourceId}`],
                  ["PKCE", "S256 (on by default in AppAuth)"],
                ]}
              />
              <p className="guide-note">
                Use your app's scheme (<code>com.yourcompany.app:/callback</code>) or an App Link / Universal Link as
                the redirect URI, and add it to this app first.
              </p>
            </div>
          )}

          {tab === "embed" && (
            <div>
              <p className="guide-lead">
                Sign-in inside your own page, in your colors. The password never reaches your page.
              </p>

              {activeClient && activeClient.embed_allowed_origins.length > 0 ? (
                <div className="alert">
                  {clientDisplayName} can be embedded on:{" "}
                  {activeClient.embed_allowed_origins.map((origin, i) => (
                    <span key={origin}>
                      {i > 0 && ", "}
                      <code>{origin}</code>
                    </span>
                  ))}
                </div>
              ) : (
                <div className="alert alert--error">
                  Add your site's callback URL to this app first (Manage → Sign-in &amp; signup).
                </div>
              )}

              <CodeBlock
                language="html"
                title="1. Put it on your page"
                code={`<div id="sign-in"></div>

<script src="${endpoints.auth_elements_js}"></script>
<script>
  const auth = AuthElements({
    clientId: "${currentClientId}",
    resource: "${activeResourceId}",
    scope: "${activeClient?.allowed_scope || "openid profile email"}",
    appearance: {
      colorPrimary: "#4f46e5",
      colorBackground: "#ffffff",   // the card the form sits in
      colorText: "#0f172a",
      borderRadius: "10px",
      fontFamily: "Inter, sans-serif",
      theme: "light",               // or "dark"
    },
  });

  const signIn = auth.create("login");   // or auth.create("signup")
  signIn.on("success", async ({ code, codeVerifier }) => {
    // Hand the code to your backend (step 2), then refresh.
    await fetch("/api/auth/complete", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ code, codeVerifier }),
    });
    location.reload();
  });
  signIn.on("error", (err) => console.error(err));
  signIn.mount("#sign-in");
</script>`}
              />

              <CodeBlock
                language="python"
                title="2. Exchange the code on your backend"
                description="Keep the tokens on your server."
                code={`import httpx

async def complete_sign_in(code: str, code_verifier: str):
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "${endpoints.token_endpoint}",
            data={
                "grant_type": "authorization_code",
                "client_id": "${currentClientId}",${
                  isPublicClient
                    ? ""
                    : `
                "client_secret": "${effectiveSecret || "<paste-your-client-secret>"}",`
                }
                "code": code,
                "code_verifier": code_verifier,
            },
        )
        resp.raise_for_status()
        return resp.json()  # access_token, refresh_token, expires_in`}
              />

              <p className="guide-note">
                Appearance: <code>colorPrimary</code>, <code>colorBackground</code>, <code>colorText</code>,{" "}
                <code>colorBorder</code>, <code>colorDanger</code>, <code>fontFamily</code>, <code>borderRadius</code>,{" "}
                <code>theme</code>.
              </p>
            </div>
          )}

          {tab === "popup" && (
            <div>
              <p className="guide-lead">Open sign-in in a popup. Your page stays where it is.</p>
              <CodeBlock
                language="html"
                title="Popup"
                description="The URL is your own route that starts the sign-in (like /login in the Website tab)."
                code={`<script src="${endpoints.auth_widget_js}"></script>
<button id="sign-in">Sign in</button>
<script>
  document.getElementById("sign-in").onclick = () =>
    AuthWidget.openPopup("/login")
      .then(() => location.reload())
      .catch((err) => err.message !== "cancelled" && alert(err.message));
</script>`}
              />
            </div>
          )}

          {tab === "assistants" && (
            <div>
              <p className="guide-lead">
                Claude, Cursor and other MCP clients only need your MCP server's address. They find this service and
                register themselves.
              </p>
              <CodeBlock
                language="bash"
                title="Claude Code"
                code={`claude mcp add --transport http my-server ${activeResourceId}`}
              />
              <CodeBlock
                language="json"
                title="Cursor (.cursor/mcp.json)"
                code={`{
  "mcpServers": {
    "my-server": { "url": "${activeResourceId}" }
  }
}`}
              />
              <p className="guide-note">
                Claude desktop and claude.ai: Settings → Connectors → Add custom connector, then paste{" "}
                <code>{activeResourceId}</code>.
              </p>
            </div>
          )}

          {tab === "service" && (
            <div>
              <p className="guide-lead">For a backend or script calling your API with no person signed in.</p>
              <CodeBlock
                language="bash"
                title="Get a token"
                code={`curl -s -u "${currentClientId}:${effectiveSecret || "<your-client-secret>"}" \\
  -d "grant_type=client_credentials" \\
  -d "resource=${activeResourceId}" \\
  ${endpoints.token_endpoint}`}
              />
              <CodeBlock
                language="python"
                title="Python"
                code={`import httpx

resp = httpx.post(
    "${endpoints.token_endpoint}",
    auth=("${currentClientId}", "${effectiveSecret || "<your-client-secret>"}"),
    data={"grant_type": "client_credentials", "resource": "${activeResourceId}"},
)
token = resp.json()["access_token"]`}
              />
            </div>
          )}

          {tab === "logout" && (
            <div>
              <p className="guide-lead">Logging out ends the sign-in to this app only. Other apps stay signed in.</p>
              <CodeBlock
                language="text"
                title="Send the browser to"
                description="The return URL must be listed under After-logout URLs."
                code={`${endpoints.end_session_endpoint}?id_token_hint=<the ID token>
  &post_logout_redirect_uri=${encodeURIComponent(
    activeClient?.post_logout_redirect_uris?.[0] ?? "https://yourapp.com/signed-out",
  )}`}
              />
              <CodeBlock
                language="python"
                title="Optional: back-channel logout endpoint"
                description="Set its URL under Sign-in & signup. We POST a signed logout_token when someone is signed out of this app."
                code={`from fastapi import Form, Response
from auth_client import TokenValidator

# The logout token's audience is this app's client ID.
logout_tokens = TokenValidator(issuer="${endpoints.issuer}", resource_id="${currentClientId}")

@app.post("/auth/backchannel-logout")
async def backchannel_logout(logout_token: str = Form(...)):
    claims = logout_tokens.validate(logout_token)
    end_sessions(user_id=claims["sub"], sid=claims.get("sid"))  # your code
    return Response(status_code=200)`}
              />
            </div>
          )}

          {tab === "oauth" && (
            <div>
              <p className="guide-lead">The requests, for when you're not using a library.</p>
              <CodeBlock
                language="http"
                title="1. Send the browser to"
                code={`GET ${endpoints.authorization_endpoint}
  ?response_type=code
  &client_id=${currentClientId}
  &redirect_uri=${encodeURIComponent(currentRedirectUri)}
  &scope=openid%20email%20profile
  &resource=${encodeURIComponent(activeResourceId)}
  &code_challenge=<BASE64URL(SHA256(verifier))>
  &code_challenge_method=S256
  &state=<random>
  &nonce=<random>`}
              />
              <CodeBlock
                language="http"
                title="2. Exchange the code"
                code={`POST ${endpoints.token_endpoint}
Content-Type: application/x-www-form-urlencoded

grant_type=authorization_code
&client_id=${currentClientId}
&code=<code>
&code_verifier=<verifier>
&redirect_uri=${currentRedirectUri}

→ { "access_token", "id_token", "refresh_token", "expires_in" }`}
              />
              <p className="guide-note">
                Also supported: <code>prompt=none</code> (silent check), <code>prompt=login</code>, <code>max_age</code>
                , <code>login_hint</code>, and <code>/introspect</code> and <code>/revoke</code>.
              </p>
            </div>
          )}

          {tab === "mtls" && (
            <div>
              <p style={{ fontSize: 13, color: "var(--text-muted)", marginTop: 0 }}>
                Mutual TLS replaces the shared secret with client certificate verification:
              </p>
              <CodeBlock
                language="bash"
                title="Extract SHA-1 Thumbprint"
                code={`openssl x509 -in client.crt -noout -fingerprint -sha1 | cut -d= -f2 | tr -d ':' | tr 'A-F' 'a-f'`}
              />
              <p style={{ fontSize: 12.5, color: "var(--text-muted)" }}>
                Paste the resulting thumbprint into this app's "mTLS certificate thumbprint" field.
                Once configured, client certificate authentication is enforced on <code>/token</code>.
              </p>
            </div>
          )}
        </div>
      )}

      {/* Security Protocol Badges */}
      <div
        style={{
          marginTop: 20,
          paddingTop: 16,
          borderTop: "1px solid var(--border)",
          display: "flex",
          flexWrap: "wrap",
          gap: 8,
          alignItems: "center",
        }}
      >
        <span style={{ fontSize: 12, fontWeight: 600, color: "var(--text-muted)" }}>
          Standards:
        </span>
        <Badge variant="success">OAuth 2.1</Badge>
        <Badge variant="success">OpenID Connect</Badge>
        <Badge variant="success">PKCE (S256)</Badge>
        <Badge variant="success">RFC 8707 resources</Badge>
        <Badge variant="success">RFC 9728 discovery</Badge>
        <Badge variant="success">Back-channel logout</Badge>
      </div>
    </Modal>
  );
}

function SettingsTable({ rows }: { rows: [string, string][] }) {
  return (
    <dl className="guide-settings">
      {rows.map(([label, value]) => (
        <div key={label}>
          <dt>{label}</dt>
          <dd>
            <CopyableId value={value} max={60} />
          </dd>
        </div>
      ))}
    </dl>
  );
}

function TabButton({
  children,
  active,
  onClick,
}: {
  children: React.ReactNode;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      style={{
        border: "none",
        background: "transparent",
        padding: "8px 12px",
        cursor: "pointer",
        fontWeight: active ? 600 : 500,
        fontSize: 13,
        color: active ? "var(--brand-600)" : "var(--text-muted)",
        borderBottom: `2px solid ${active ? "var(--brand-600)" : "transparent"}`,
        marginBottom: -1,
        whiteSpace: "nowrap",
      }}
    >
      {children}
    </button>
  );
}
