import { InputHTMLAttributes, useState } from "react";
import { EyeIcon, EyeOffIcon } from "./Icons";

export function PasswordInput(props: InputHTMLAttributes<HTMLInputElement>) {
  const [visible, setVisible] = useState(false);

  return (
    <div className="input-group">
      <input {...props} type={visible ? "text" : "password"} />
      <button
        type="button"
        className="toggle-visibility"
        aria-label={visible ? "Hide password" : "Show password"}
        aria-pressed={visible}
        onClick={() => setVisible((v) => !v)}
      >
        {visible ? <EyeOffIcon /> : <EyeIcon />}
      </button>
    </div>
  );
}
