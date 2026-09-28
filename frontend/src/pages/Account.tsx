import { FormEvent, useState } from "react";
import { useAdmin } from "../AdminContext";
import { api, ApiError } from "../api";

export function Account() {
  const { admin, refresh } = useAdmin();
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    setSuccess(null);
    try {
      await api.post("/account/password", {
        current_password: currentPassword,
        new_password: newPassword,
        confirm_password: confirmPassword,
      });
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
      setSuccess("Password updated");
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
        <h1 className="title">Account</h1>
      </div>

      <p className="lead">Signed in as <strong>{admin?.email}</strong>.</p>

      <div style={{ maxWidth: 420 }}>
        <h2 style={{ fontSize: 15, marginBottom: 16 }}>Change password</h2>
        {error && <div className="alert alert--error">{error}</div>}
        {success && (
          <div className="alert" style={{ background: "var(--color-success-soft)", color: "var(--color-success)" }}>
            {success}
          </div>
        )}
        <form onSubmit={onSubmit}>
          <div className="field">
            <label htmlFor="current_password">Current password</label>
            <input
              id="current_password"
              type="password"
              required
              value={currentPassword}
              onChange={(e) => setCurrentPassword(e.target.value)}
            />
          </div>
          <div className="field">
            <label htmlFor="new_password">New password</label>
            <input
              id="new_password"
              type="password"
              required
              minLength={8}
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
            />
          </div>
          <div className="field">
            <label htmlFor="confirm_password">Confirm new password</label>
            <input
              id="confirm_password"
              type="password"
              required
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
            />
          </div>
          <button type="submit" className="btn btn--primary btn--block" disabled={submitting}>
            Update password
          </button>
        </form>
      </div>
    </>
  );
}
