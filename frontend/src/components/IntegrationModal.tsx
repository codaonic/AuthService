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
}

export function IntegrationModal({
  onClose,
  resource,
  client,
  clientSecret,
}: IntegrationModalProps) {
  const [endpoints, setEndpoints] = useState<SystemEndpoints | null>(null);
  const [allResources, setAllResources] = useState<Resource[]>([]);
  const [selectedResourceId, setSelectedResourceId] = useState<string>("");
  const [tab, setTab] = useState<string>("");
  // client_secret only ever comes back from the one-time create response --
  // GET /clients never includes it again. Reopening this guide later for an
  // existing client has nothing to prefill, so let the admin paste their
  // own saved secret back in rather than silently printing a fake one.
  const [pastedSecret, setPastedSecret] = useState("");
  const isPublicClient = client?.client_type === "public";
  const effectiveSecret = clientSecret || pastedSecret;

  useEffect(() => {
    api.get<SystemEndpoints>("/system/endpoints").then(setEndpoints);
    api.get<Resource[]>("/resources").then((res) => {
      setAllResources(res);
      if (res.length > 0) {
        setSelectedResourceId(res[0].resource_id);
      }
    });
  }, []);

  // Determine initial tab once data or mode is ready
  useEffect(() => {
    if (resource) {
      setTab("fastmcp");
    } else if (client) {
      if (client.application_type === "native") {
        setTab("claude");
      } else if (client.application_type === "service") {
        setTab("curl");
      } else {
        setTab("widget");
      }
    }
  }, [resource, client]);

  if (!endpoints) {
    return (
      <Modal title="Integration Guide" wide onClose={onClose}>
        <div style={{ padding: 24, textAlign: "center", color: "var(--text-muted)" }}>
          Loading integration metadata…
        </div>
      </Modal>
    );
  }

  const activeResourceId = resource
    ? resource.resource_id
    : selectedResourceId || "https://mcp.yourdomain.com";

  const prmUrl = `${endpoints.prm_endpoint}?resource=${encodeURIComponent(activeResourceId)}`;

  return (
    <Modal
      title={
        resource
          ? `Integration Guide: ${resource.name}`
          : client
          ? `Integration Guide: ${client.client_name || client.client_id}`
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
          marginBottom: 20,
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

      {/* Target Resource selector if configuring an Application */}
      {client && allResources.length > 0 && (
        <div className="field" style={{ marginBottom: 16 }}>
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

      {client && !isPublicClient && (
        <div className="field" style={{ marginBottom: 16 }}>
          <label htmlFor="guide-secret">Client secret</label>
          {clientSecret ? (
            <input id="guide-secret" readOnly value={clientSecret} />
          ) : (
            <input
              id="guide-secret"
              placeholder="Paste the secret you saved when this app was created"
              value={pastedSecret}
              onChange={(e) => setPastedSecret(e.target.value)}
            />
          )}
          <span className="field__hint">
            {clientSecret
              ? "Shown once, right after creation — already filled in below."
              : "Not retrievable after creation and never sent back by this page. Paste it here only to fill in the snippets below for copying — it's not saved anywhere."}
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
            {client?.application_type === "native" && (
              <>
                <TabButton active={tab === "claude"} onClick={() => setTab("claude")}>
                  Claude Desktop
                </TabButton>
                <TabButton active={tab === "cursor"} onClick={() => setTab("cursor")}>
                  Cursor MCP
                </TabButton>
                <TabButton active={tab === "pkce"} onClick={() => setTab("pkce")}>
                  PKCE Auth Flow
                </TabButton>
              </>
            )}
            {client?.application_type === "web" && (
              <>
                <TabButton active={tab === "widget"} onClick={() => setTab("widget")}>
                  Popup Widget (HTML)
                </TabButton>
                <TabButton active={tab === "bff"} onClick={() => setTab("bff")}>
                  BFF Backend (Python)
                </TabButton>
                <TabButton active={tab === "pkce"} onClick={() => setTab("pkce")}>
                  OAuth Endpoints
                </TabButton>
              </>
            )}
            {client?.application_type === "service" && (
              <>
                <TabButton active={tab === "curl"} onClick={() => setTab("curl")}>
                  cURL Command
                </TabButton>
                <TabButton active={tab === "mtls"} onClick={() => setTab("mtls")}>
                  Mutual TLS (mTLS)
                </TabButton>
                <TabButton active={tab === "python"} onClick={() => setTab("python")}>
                  Python HTTPX
                </TabButton>
              </>
            )}
            {/* Fallback tabs if generic */}
            {!["native", "web", "service"].includes(client?.application_type ?? "") && (
              <>
                <TabButton active={tab === "curl"} onClick={() => setTab("curl")}>
                  cURL
                </TabButton>
                <TabButton active={tab === "pkce"} onClick={() => setTab("pkce")}>
                  PKCE Flow
                </TabButton>
              </>
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

      {/* Tab Contents: Client Mode */}
      {client && (
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
    "${client.client_id}": {
      "url": "${activeResourceId}/sse",
      "auth": {
        "type": "oauth2",
        "issuer": "${endpoints.issuer}",
        "client_id": "${client.client_id}",
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
                automatically. As a public client, no client secret is needed or allowed.
              </div>
            </div>
          )}

          {tab === "cursor" && (
            <div>
              <p style={{ fontSize: 13, color: "var(--text-muted)", marginTop: 0 }}>
                Add this to your Cursor MCP settings:
              </p>
              <CodeBlock
                language="json"
                title="Cursor MCP Settings"
                code={`{
  "mcp": {
    "servers": {
      "${client.client_id}": {
        "transport": "sse",
        "url": "${activeResourceId}/sse",
        "oauth": {
          "clientId": "${client.client_id}",
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
<button id="sign-in-btn">Sign in</button>

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
                "client_id": "${client.client_id}",${
                  isPublicClient
                    ? ""
                    : `\n                "client_secret": "${effectiveSecret || "<paste-your-client-secret>"}",`
                }
                "code": code,
                "code_verifier": code_verifier,
                "redirect_uri": "${client.redirect_uris[0] || "https://yourapp.com/callback"}",
                "resource": "${activeResourceId}",
            },
        )
        tokens = resp.json()
        return tokens # Store tokens server-side in user session`}
              />
            </div>
          )}

          {tab === "curl" && (
            <div>
              <p style={{ fontSize: 13, color: "var(--text-muted)", marginTop: 0 }}>
                Service-to-service <code>client_credentials</code> grant request:
              </p>
              <CodeBlock
                language="bash"
                title="Token Request cURL"
                code={`curl -X POST "${endpoints.token_endpoint}" \\
  -H "Content-Type: application/x-www-form-urlencoded" \\
  -d "grant_type=client_credentials" \\
  -d "client_id=${client.client_id}" \\${
    isPublicClient ? "" : `\n  -d "client_secret=${effectiveSecret || "<paste-your-client-secret>"}" \\`
  }
  -d "resource=${activeResourceId}"`}
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
  &client_id=${client.client_id}
  &redirect_uri=${encodeURIComponent(client.redirect_uris[0] || "https://yourapp.com/callback")}
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
&client_id=${client.client_id}
&code=AUTHORIZATION_CODE
&code_verifier=RAW_CODE_VERIFIER
&redirect_uri=${client.redirect_uris[0] || "https://yourapp.com/callback"}`}
              />
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
