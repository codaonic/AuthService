import { FormEvent, useEffect, useState } from "react";
import { useAdmin } from "../AdminContext";
import { AccountIcon } from "../components/Icons";
import { PasswordInput } from "../components/PasswordInput";
import { ActivityList } from "../components/ActivityList";
import { useToast } from "../components/ToastProvider";
import { api, ApiError, AuditEvent } from "../api";

export function Account() {
  const { admin, refresh } = useAdmin();
  const { show } = useToast();
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [signIns, setSignIns] = useState<AuditEvent[] | null>(null);

  useEffect(() => {
    if (!admin?.email) return;
    api
      .get<AuditEvent[]>(`/audit?${new URLSearchParams({ q: admin.email, limit: "40" })}`)
      .then((events) => setSignIns(events.filter((e) => e.event.startsWith("admin_login")).slice(0, 8)));
  }, [admin?.email]);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    if (newPassword !== confirmPassword) {
      setError("The two new passwords don't match");
      return;
    }
    setSubmitting(true);
    try {
      await api.post("/account/password", {
        current_password: currentPassword,
        new_password: newPassword,
        confirm_password: confirmPassword,
      });
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
      show("Password changed");
      await refresh();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <>
      <div className="header">
        <div className="header__title-row">
          <span className="header__icon">
            <AccountIcon />
          </span>
          <h1 className="title">Account</h1>
        </div>
      </div>
      <p className="lead">
        You're signed in to this console as <strong>{admin?.email}</strong>.
      </p>

      <div className="account-grid">
        <section className="panel">
          <h2 className="panel__title">Change your password</h2>
          <p className="panel__hint" style={{ marginTop: 6 }}>
            At least 8 characters. Other people's passwords are changed from the Users page.
          </p>
          {error && <div className="alert alert--error">{error}</div>}
          <form onSubmit={onSubmit}>
            <div className="field">
              <label htmlFor="current_password">Current password</label>
              <PasswordInput
                id="current_password"
                required
                autoComplete="current-password"
                value={currentPassword}
                onChange={(e) => setCurrentPassword(e.target.value)}
              />
            </div>
            <div className="field">
              <label htmlFor="new_password">New password</label>
              <PasswordInput
                id="new_password"
                required
                minLength={8}
                autoComplete="new-password"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
              />
            </div>
            <div className="field">
              <label htmlFor="confirm_password">New password again</label>
              <PasswordInput
                id="confirm_password"
                required
                minLength={8}
                autoComplete="new-password"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
              />
            </div>
            <button type="submit" className="btn btn--primary" disabled={submitting}>
              {submitting ? "Changing…" : "Change password"}
            </button>
          </form>
        </section>

        <section className="panel">
          <h2 className="panel__title">Your recent sign-ins</h2>
          <p className="panel__hint" style={{ marginTop: 6 }}>
            Sign-ins to this console with your email. If one wasn't you, change your password.
          </p>
          {signIns === null ? (
            <p className="field__hint">Loading…</p>
          ) : signIns.length === 0 ? (
            <p className="chart-empty">None recorded yet.</p>
          ) : (
            <ActivityList events={signIns} compact />
          )}
        </section>
      </div>
    </>
  );
}
