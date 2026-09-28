export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(`/admin/api${path}`, {
    ...init,
    credentials: "include",
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });

  if (!resp.ok) {
    let detail = resp.statusText;
    try {
      const body = await resp.json();
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      /* no JSON body */
    }
    throw new ApiError(resp.status, detail);
  }

  if (resp.status === 204) return undefined as T;
  return (await resp.json()) as T;
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) }),
};

export interface Admin {
  id: string;
  email: string;
  must_change_password: boolean;
}

export interface Pool {
  id: string;
  name: string;
}

export interface Resource {
  resource_id: string;
  name: string;
  metadata_url: string | null;
}

export interface Client {
  id: string;
  client_id: string;
  client_name: string | null;
  client_type: string;
  registration_method: string;
  application_type: string;
  redirect_uris: string[];
  grant_types: string[];
  allowed_scope: string;
  allow_signup: boolean;
  enabled: boolean;
  mtls_cert_thumbprint: string | null;
  cimd_fetched_at: string | null;
  pool_name: string;
  client_secret?: string;
}

export interface AppUser {
  id: string;
  email: string;
  pool_name: string;
  status: string;
  email_verified: boolean;
}

export interface AuditEvent {
  time: string;
  level: string;
  event: string;
  extra: Record<string, unknown>;
}

export interface DashboardData {
  counts: { pools: number; clients: number; resources: number; users: number };
  recent: AuditEvent[];
}
