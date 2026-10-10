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
    if (resource) {
      setTab("fastmcp");
    } else if (appOnly) {
      setTab(activeClient?.application_type === "service" ? "curl" : "widget");
    } else if (activeClient) {
      if (activeClient.application_type === "native") {
        setTab("claude");
      } else if (activeClient.application_type === "service") {
        setTab("curl");
      } else {
        setTab("claude");
      }
    } else {
      setTab("claude");
    }
  }, [resource, activeClient, appOnly]);

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
            Application to Configure
          </label>
          <select
            id="active-app-picker"
            value={activeClient?.id ?? ""}
            onChange={(e) => handleClientChange(e.target.value)}
          >
            {availableClients.map((c) => (
              <option key={c.id} value={c.id}>
                {c.client_name || c.client_id} ({c.client_type}, {c.pool_name})
              </option>
            ))}
            <option value="">Generic Reference (Placeholder values)</option>
          </select>
          <span className="field__hint">
            Selecting an application pre-fills its Client ID, redirect URIs, and credentials in the snippets below.
          </span>
        </div>
      )}

      {/* Target Resource selector if configuring an Application (hidden in app-only mode) */}
      {!resource && !appOnly && allResources.length > 0 && (
        <div className="field" style={{ marginBottom: 14 }}>
          <label htmlFor="target-resource-select">Target MCP Server / API (Resource Indicator)</label>
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
          <span className="field__hint">
            Under RFC 8707, access tokens are audience-bound to this resource. Selecting it ensures
            the snippets below generate the matching audience parameter.
          </span>
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
              placeholder="Paste the secret you saved when this app was created to fill snippets"
              value={pastedSecret}
              onChange={(e) => setPastedSecret(e.target.value)}
            />
          )}
          <span className="field__hint">
            {clientSecret
              ? "Shown once, right after creation — already filled in below."
              : "Client secrets are hashed and cannot be retrieved after creation. Paste it here to fill in the snippets for copying — it is never sent back to the server."}
          </span>
        </div>
      )}

      {/* Tab Navigation */}
      <div
        style={{
          display: "flex",
          gap: 6,
          borderBottom: "1px solid var(--border)",
          marginBottom: 16,
          overflowX: "auto",
        }}
      >
        {resource ? (
          <>
            <TabButton active={tab === "fastmcp"} onClick={() => setTab("fastmcp")}>
              FastMCP / Python
            </TabButton>
            <TabButton active={tab === "typescript"} onClick={() => setTab("typescript")}>
              TypeScript / Node
            </TabButton>
            <TabButton active={tab === "prm"} onClick={() => setTab("prm")}>
              Protected Resource Metadata (PRM)
            </TabButton>
          </>
        ) : (
          <>
            {!appOnly && (
              <>
                <TabButton active={tab === "claude"} onClick={() => setTab("claude")}>
                  Claude Desktop
                </TabButton>
                <TabButton active={tab === "cursor"} onClick={() => setTab("cursor")}>
                  Cursor MCP
                </TabButton>
                <TabButton active={tab === "python_agent"} onClick={() => setTab("python_agent")}>
                  Python AI Agent
                </TabButton>
              </>
            )}
            <TabButton active={tab === "curl"} onClick={() => setTab("curl")}>
              cURL (Token Request)
            </TabButton>
            <TabButton active={tab === "widget"} onClick={() => setTab("widget")}>
              Popup Widget (HTML)
            </TabButton>
            <TabButton active={tab === "bff"} onClick={() => setTab("bff")}>
              BFF Backend (Python)
            </TabButton>
            <TabButton active={tab === "pkce"} onClick={() => setTab("pkce")}>
              OAuth Endpoints & PKCE
            </TabButton>
            {activeClient?.application_type === "service" && (
              <TabButton active={tab === "mtls"} onClick={() => setTab("mtls")}>
                Mutual TLS (mTLS)
              </TabButton>
            )}
          </>
        )}
      </div>

      {/* Tab Contents: Resource Mode */}
      {resource && (
        <div>
          {tab === "fastmcp" && (
            <div>
              <p style={{ fontSize: 13, color: "var(--text-muted)", marginTop: 0 }}>
                Integrate your Python MCP server using <code>authservice-client</code>. It validates
                JWTs against the cached JWKS and serves RFC 9728 Protected Resource Metadata at{" "}
                <code>/.well-known/oauth-protected-resource</code>.
              </p>
              <CodeBlock
                language="bash"
                title="1. Install Client SDK"
                code={`uv add "authservice-client @ git+https://github.com/codaonic/AuthService_Client.git@main"`}
              />
              <CodeBlock
                language="python"
                title="2. Server Integration Code"
                code={`from fastapi import FastAPI, Depends
from authservice_client import TokenValidator
from authservice_client.fastapi import make_auth_dependency
from authservice_client.protected_resource import protected_resource_router

ISSUER = "${endpoints.issuer}"
RESOURCE_ID = "${resource.resource_id}"

# Validates RS256 JWTs locally against cached JWKS with aud=RESOURCE_ID
validator = TokenValidator(issuer=ISSUER, resource_id=RESOURCE_ID)
require_auth = make_auth_dependency(validator)

app = FastAPI(title="${resource.name}")

# Mounts /.well-known/oauth-protected-resource so MCP clients discover the auth server
app.include_router(protected_resource_router(RESOURCE_ID, ISSUER, resource_name="${resource.name}"))

@app.post("/mcp/tools/call")
async def call_tool(claims: dict = Depends(require_auth)):
    # claims contains verified sub, email, and scopes
    return {"status": "ok", "caller_id": claims["sub"]}`}
              />
            </div>
          )}

          {tab === "typescript" && (
            <div>
              <p style={{ fontSize: 13, color: "var(--text-muted)", marginTop: 0 }}>
                In TypeScript / Node, verify tokens locally with the standard <code>jose</code>{" "}
                library against the public JWKS.
              </p>
              <CodeBlock
                language="bash"
                title="1. Install jose"
                code={`npm install jose`}
              />
              <CodeBlock
                language="typescript"
                title="2. Token Verification Middleware"
                code={`import { createRemoteJWKSet, jwtVerify } from "jose";

const ISSUER = "${endpoints.issuer}";
const RESOURCE_ID = "${resource.resource_id}";
const JWKS = createRemoteJWKSet(new URL("${endpoints.jwks_uri}"));

export async function verifyMcpToken(authHeader?: string) {
  if (!authHeader?.startsWith("Bearer ")) {
    throw new Error("Missing or invalid authorization header");
  }
  const token = authHeader.slice(7);
  const { payload } = await jwtVerify(token, JWKS, {
    issuer: ISSUER,
    audience: RESOURCE_ID,
  });
  return payload; // { sub, email, ... }
}`}
              />
            </div>
          )}

          {tab === "prm" && (
            <div>
              <p style={{ fontSize: 13, color: "var(--text-muted)", marginTop: 0 }}>
                Under RFC 9728, when an MCP client calls your server without authentication, return{" "}
                <code>401 Unauthorized</code> pointing to this metadata document.
              </p>
              <CodeBlock
                language="http"
                title="401 Challenge Header"
                code={`HTTP/1.1 401 Unauthorized
WWW-Authenticate: Bearer error="invalid_token", resource_metadata="${prmUrl}"`}
              />
              <CodeBlock
                language="json"
                title="Published PRM Document"
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
          {tab === "claude" && (
            <div>
              <p style={{ fontSize: 13, color: "var(--text-muted)", marginTop: 0 }}>
                Add this to your <code>claude_desktop_config.json</code> to connect Claude Desktop to
                your MCP server through this Auth Service:
              </p>
              <CodeBlock
                language="json"
                title="claude_desktop_config.json"
                code={`{
  "mcpServers": {
    "${currentClientId}": {
      "url": "${activeResourceId}/sse",
      "auth": {
        "type": "oauth2",
        "issuer": "${endpoints.issuer}",
        "client_id": "${currentClientId}",
        "resource": "${activeResourceId}",
        "scopes": ["openid", "profile"]
      }
    }
  }
}`}
              />
              <div
                style={{
                  padding: 12,
                  background: "var(--info-bg)",
                  color: "var(--info-fg)",
                  borderRadius: "var(--radius-sm)",
                  fontSize: 12.5,
                }}
              >
                <strong>Security Protocol Note:</strong> Claude Desktop executes the PKCE (S256) flow
                automatically. Under OAuth 2.1, native desktop clients do not use client secrets.
              </div>
            </div>
          )}

          {tab === "cursor" && (
            <div>
              <p style={{ fontSize: 13, color: "var(--text-muted)", marginTop: 0 }}>
                Add this to your Cursor MCP settings (in Settings → Features → MCP):
              </p>
              <CodeBlock
                language="json"
                title="Cursor MCP Settings"
                code={`{
  "mcp": {
    "servers": {
      "${currentClientId}": {
        "transport": "sse",
        "url": "${activeResourceId}/sse",
        "oauth": {
          "clientId": "${currentClientId}",
          "issuer": "${endpoints.issuer}",
          "resource": "${activeResourceId}"
        }
      }
    }
  }
}`}
              />
            </div>
          )}

          {tab === "python_agent" && (
            <div>
              <p style={{ fontSize: 13, color: "var(--text-muted)", marginTop: 0 }}>
                Python AI Agent / Backend client calling an MCP Server using tokens minted for{" "}
                <strong>{currentClientId}</strong>:
              </p>
              <CodeBlock
                language="python"
                title="Python AI Agent Token & Tool Call"
                code={`import httpx

ISSUER = "${endpoints.issuer}"
CLIENT_ID = "${currentClientId}"
CLIENT_SECRET = "${effectiveSecret || "<paste-your-client-secret>"}"
RESOURCE_ID = "${activeResourceId}"

async def get_access_token():
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{ISSUER}/token",
            data={
                "grant_type": "client_credentials",
                "client_id": CLIENT_ID,${
                  isPublicClient
                    ? ""
                    : `\n                "client_secret": CLIENT_SECRET,`
                }
                "resource": RESOURCE_ID,
            },
        )
        resp.raise_for_status()
        return resp.json()["access_token"]

async def call_mcp_tool(tool_name: str, arguments: dict):
    token = await get_access_token()
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{RESOURCE_ID}/mcp/tools/call",
            headers=headers,
            json={"name": tool_name, "arguments": arguments},
        )
        resp.raise_for_status()
        return resp.json()`}
              />
            </div>
          )}

          {tab === "curl" && (
            <div>
              <p style={{ fontSize: 13, color: "var(--text-muted)", marginTop: 0 }}>
                Direct token exchange request via cURL:
              </p>
              <CodeBlock
                language="bash"
                title="Token Request cURL"
                code={`curl -X POST "${endpoints.token_endpoint}" \\
  -H "Content-Type: application/x-www-form-urlencoded" \\
  -d "grant_type=client_credentials" \\
  -d "client_id=${currentClientId}" \\${
    isPublicClient
      ? ""
      : `\n  -d "client_secret=${effectiveSecret || "<paste-your-client-secret>"}" \\`
  }
  -d "resource=${activeResourceId}"`}
              />
            </div>
          )}

          {tab === "widget" && (
            <div>
              <p style={{ fontSize: 13, color: "var(--text-muted)", marginTop: 0 }}>
                Embed the popup login widget directly into your website. The password and login form
                run in this service's hosted popup, keeping credentials isolated from your site:
              </p>
              <CodeBlock
                language="html"
                title="Embedded Popup Widget"
                code={`<script src="${endpoints.auth_widget_js}"></script>
<button id="sign-in-btn">Sign in with ${clientDisplayName}</button>

<script>
  document.getElementById("sign-in-btn").addEventListener("click", () => {
    AuthWidget.openPopup("/login?popup=1")
      .then(() => location.reload())
      .catch((err) => {
        if (err.message !== "cancelled") alert(err.message);
      });
  });
</script>`}
              />
            </div>
          )}

          {tab === "bff" && (
            <div>
              <p style={{ fontSize: 13, color: "var(--text-muted)", marginTop: 0 }}>
                Website Backend-for-Frontend (BFF) pattern: your server exchanges the authorization
                code for tokens and stores them in an HttpOnly session cookie:
              </p>
              <CodeBlock
                language="python"
                title="BFF Authorization Code Exchange (Python)"
                code={`import httpx

async def handle_callback(code: str, code_verifier: str):
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "${endpoints.token_endpoint}",
            data={
                "grant_type": "authorization_code",
                "client_id": "${currentClientId}",
                "client_secret": "${effectiveSecret || "<paste-your-client-secret>"}",
                "code": code,
                "code_verifier": code_verifier,
                "redirect_uri": "${currentRedirectUri}",
                "resource": "${activeResourceId}",
            },
        )
        tokens = resp.json()
        return tokens  # Store tokens server-side in user session`}
              />
              <p style={{ fontSize: 13, color: "var(--text-muted)" }}>
                Logout signs the person out of <strong>this application only</strong> — other
                applications stay signed in, including ones in the same login group. Call it from
                your own logout button; it has no page of its own. Use either form:
              </p>
              <CodeBlock
                language="python"
                title="Logout from your server (returns JSON)"
                code={`import httpx

async def handle_logout(refresh_token: str):
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "${endpoints.end_session_endpoint}",
            data={
                "client_id": "${currentClientId}",${
                  isPublicClient
                    ? ""
                    : `
                "client_secret": "${effectiveSecret || "<paste-your-client-secret>"}",`
                }
                "refresh_token": refresh_token,
            },
        )
        resp.raise_for_status()  # {"status": "signed_out", ...}
    # then clear your own session cookie`}
              />
              <CodeBlock
                language="text"
                title="Logout by redirecting the browser"
                code={`${endpoints.end_session_endpoint}?client_id=${encodeURIComponent(currentClientId)}&post_logout_redirect_uri=${encodeURIComponent(
                  activeClient?.post_logout_redirect_uris?.[0] ?? "https://yourapp.com/signed-out",
                )}&state=<optional>`}
                description="The return URL must be listed under After-logout URLs for this application."
              />
            </div>
          )}

          {tab === "pkce" && (
            <div>
              <p style={{ fontSize: 13, color: "var(--text-muted)", marginTop: 0 }}>
                Full OAuth 2.1 Authorization Code + PKCE (S256) Flow:
              </p>
              <CodeBlock
                language="http"
                title="1. Authorization Request"
                code={`GET ${endpoints.authorization_endpoint}?
  response_type=code
  &client_id=${currentClientId}
  &redirect_uri=${encodeURIComponent(currentRedirectUri)}
  &scope=openid%20profile
  &resource=${encodeURIComponent(activeResourceId)}
  &code_challenge=BASE64URL_SHA256_VERIFIER
  &code_challenge_method=S256`}
              />
              <CodeBlock
                language="http"
                title="2. Token Exchange (POST /token)"
                code={`POST ${endpoints.token_endpoint}
Content-Type: application/x-www-form-urlencoded

grant_type=authorization_code
&client_id=${currentClientId}
&code=AUTHORIZATION_CODE
&code_verifier=RAW_CODE_VERIFIER
&redirect_uri=${currentRedirectUri}`}
              />
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
          Protocols Enforced:
        </span>
        <Badge variant="success">OAuth 2.1 (RFC 6749)</Badge>
        <Badge variant="success">PKCE Mandatory (S256)</Badge>
        <Badge variant="success">RFC 8707 Resource Scoped</Badge>
        <Badge variant="success">RFC 9728 PRM</Badge>
        <Badge variant="success">One-time Refresh Token Rotation</Badge>
      </div>
    </Modal>
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
