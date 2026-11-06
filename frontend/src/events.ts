// Activity log events in plain words. Anything not listed is spelled out
// from its name ("client_role_deleted" -> "Client role deleted").
import { Outcome } from "./api";

const EVENT_LABELS: Record<string, string> = {
  login_success: "Logged in",
  login_failure: "Login failed",
  logout: "Logged out",
  signup_success: "Signed up",
  admin_login_success: "Admin logged in",
  admin_login_failure: "Admin login failed",
  admin_setup_completed: "Console set up",
  password_reset_requested: "Asked to reset password",
  password_reset_completed: "Reset password",
  password_changed: "Changed password",
  email_verified: "Verified email",
  email_verification_required: "Asked to verify their email first",
  client_verified_email_required: "Verified email now required",
  client_verified_email_optional: "Verified email no longer required",
  email_link_held: "Email couldn't be sent",
  webauthn_registered: "Added a passkey",
  passkey_add_failed: "Passkey not added: wrong password",
  user_email_changed: "Email changed by an admin",
  webauthn_login_success: "Logged in with a passkey",
  mtls_auth_failed: "Client certificate rejected",
  anomalous_activity: "Unusual activity",
  token_revoked: "Token revoked",
  session_revoked: "Session ended",
  sessions_revoked_others: "Ended other sessions",
  user_signed_out_by_admin: "Signed out by an admin",
  client_registered: "Application registered itself",
  client_created: "Application added",
  pool_created: "Login group created",
  user_created: "Account added by an admin",
  client_deleted: "Application removed",
  client_enabled: "Application re-enabled",
  client_disabled: "Application disabled",
};

export function eventLabel(event: string): string {
  if (EVENT_LABELS[event]) return EVENT_LABELS[event];
  const words = event.replace(/_/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

export const OUTCOME_LABELS: Record<Outcome, string> = {
  success: "Success",
  warning: "Warning",
  error: "Error",
};

// Detail fields worth showing, in this order, with a readable name.
const DETAIL_LABELS: [string, string][] = [
  ["email", "Person"],
  ["client_id", "App"],
  ["reason", "Reason"],
  ["kind", "Kind"],
  ["ip", "IP"],
  ["user_id", "User ID"],
  ["admin_id", "By admin"],
];

// Codes some events carry, in words.
const VALUE_LABELS: Record<string, string> = {
  smtp_not_configured: "Email isn't set up",
  smtp_failed: "Sending failed",
  password_reset: "Password reset",
  email_verification: "Email verification",
  invalid_credentials: "Wrong email or password",
  invalid_mfa_code: "Wrong 2FA code",
  locked_out: "Too many attempts",
  wrong_password: "Wrong password",
};

export function eventDetails(extra: Record<string, unknown>): { label: string; value: string }[] {
  const known = DETAIL_LABELS.filter(([k]) => extra[k] != null && extra[k] !== "").map(([k, label]) => ({
    label,
    value: VALUE_LABELS[String(extra[k])] ?? String(extra[k]),
  }));
  const rest = Object.entries(extra)
    .filter(([k, v]) => !DETAIL_LABELS.some(([d]) => d === k) && v != null && v !== "")
    .map(([k, v]) => ({ label: k.replace(/_/g, " "), value: String(v) }));
  return [...known, ...rest];
}
