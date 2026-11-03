import { ClipboardEvent, KeyboardEvent, useRef, useState } from "react";
import { CloseIcon } from "./Icons";

// scheme://something -- https, http on localhost, or an app scheme like vscode://
const LINK = /^[a-z][a-z0-9+.-]*:\/\/\S+$/i;

const split = (value: string) => value.split("\n").map((l) => l.trim()).filter(Boolean);

/** A list of links shown as removable chips. Type a link and press Enter to
 * add it; pasting several lines adds them all. The value stays one link per
 * line, the same as the API takes. */
export function LinkListInput({
  id,
  value,
  onChange,
  placeholder,
  required,
}: {
  id?: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  /** Requires at least one link before the surrounding form submits. */
  required?: boolean;
}) {
  const links = split(value);
  const [text, setText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // Adds what's been typed; anything that isn't a link stays in the box with
  // the reason underneath.
  const add = (raw: string) => {
    const candidates = split(raw.replace(/[\s,]+/g, "\n"));
    if (candidates.length === 0) return true;
    const invalid = candidates.filter((c) => !LINK.test(c));
    const fresh = candidates.filter((c) => LINK.test(c) && !links.includes(c));
    if (fresh.length) onChange([...links, ...new Set(fresh)].join("\n"));
    setText(invalid.join(" "));
    setError(invalid.length ? `"${invalid[0]}" isn't a full link. Start it with https:// (or the app's own scheme).` : null);
    return invalid.length === 0;
  };

  const remove = (link: string) => {
    onChange(links.filter((l) => l !== link).join("\n"));
    inputRef.current?.focus();
  };

  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" || e.key === ",") {
      // Enter adds the link instead of submitting the form.
      e.preventDefault();
      add(text);
    } else if (e.key === "Backspace" && text === "" && links.length) {
      onChange(links.slice(0, -1).join("\n"));
    }
  };

  const onPaste = (e: ClipboardEvent<HTMLInputElement>) => {
    const pasted = e.clipboardData.getData("text");
    if (/[\s,]/.test(pasted.trim())) {
      e.preventDefault();
      add(`${text} ${pasted}`);
    }
  };

  return (
    <div className="link-list">
      <div className={`link-list__box${error ? " link-list__box--error" : ""}`} onClick={() => inputRef.current?.focus()}>
        {links.map((link) => (
          <span key={link} className="link-chip">
            <span className="link-chip__text" title={link}>
              {link}
            </span>
            <button
              type="button"
              className="link-chip__remove"
              aria-label={`Remove ${link}`}
              onClick={(e) => {
                e.stopPropagation();
                remove(link);
              }}
            >
              <CloseIcon width={12} height={12} />
            </button>
          </span>
        ))}
        <input
          id={id}
          ref={inputRef}
          className="link-list__input"
          type="text"
          inputMode="url"
          autoComplete="off"
          spellCheck={false}
          value={text}
          placeholder={links.length ? "Add another link" : placeholder}
          // Only blocks the form while there's no link at all.
          required={required && links.length === 0}
          aria-invalid={error ? true : undefined}
          onChange={(e) => {
            setText(e.target.value);
            setError(null);
          }}
          onKeyDown={onKeyDown}
          onPaste={onPaste}
          // A link typed but not yet entered still counts, so it isn't lost on Save.
          onBlur={() => add(text)}
        />
      </div>
      {error ? (
        <span className="field__hint field__hint--error">{error}</span>
      ) : (
        text.trim() && <span className="field__hint">Press Enter to add it.</span>
      )}
    </div>
  );
}
