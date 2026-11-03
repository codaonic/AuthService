import { FormEvent, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAdmin } from "../AdminContext";
import { PasswordInput } from "../components/PasswordInput";
import { AuthIcon } from "../components/AuthIcon";
import { Admin, api, ApiError } from "../api";

export function Setup() {
  const { setAdmin, setNeedsSetup } = useAdmin();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const admin = await api.post<Admin>("/setup", { email, password, confirm_password: confirmPassword });
      setNeedsSetup(false);
      setAdmin(admin);
      navigate("/admin");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="auth-page">
      <div className="auth-card">
        <div className="auth-card__icon">
          <AuthIcon size={52} />
        </div>
        <h1 className="auth-card__title">Create your admin account</h1>
        <p className="auth-card__subtitle">
          This is the first start, so there's no admin yet. Choose the email and password you'll use to
          manage this service. There is no default password.
        </p>
        {error && <div className="alert alert--error" role="alert">{error}</div>}
        <form onSubmit={onSubmit}>
          <div className="field">
            <label htmlFor="email">Email</label>
            <input
              id="email"
              type="email"
              required
              autoFocus
              autoComplete="username"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </div>
          <div className="field">
            <label htmlFor="password">
              Password <span className="field__hint">(at least 8 characters)</span>
            </label>
            <PasswordInput
              id="password"
              required
              minLength={8}
              autoComplete="new-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </div>
          <div className="field">
            <label htmlFor="confirm_password">Password again</label>
            <PasswordInput
              id="confirm_password"
              required
              autoComplete="new-password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
            />
          </div>
          <button type="submit" className="btn btn--primary btn--block" disabled={submitting}>
            {submitting ? "Creating account…" : "Create admin account"}
          </button>
        </form>
      </div>
    </div>
  );
}
