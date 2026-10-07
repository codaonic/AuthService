import { useState } from "react";
import { CheckIcon, CopyIcon } from "./Icons";

interface CodeBlockProps {
  code: string;
  language?: string;
  title?: string;
  description?: string;
}

export function CodeBlock({ code, language, title, description }: CodeBlockProps) {
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      /* clipboard API might fail if unpermitted */
    }
  };

  return (
    <div
      style={{
        border: "1px solid var(--border)",
        borderRadius: "var(--radius-md)",
        overflow: "hidden",
        background: "var(--surface-2)",
        marginBottom: 16,
      }}
    >
      {(title || language) && (
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            padding: "8px 12px",
            borderBottom: "1px solid var(--border)",
            background: "var(--surface)",
            fontSize: 12.5,
            fontWeight: 600,
            color: "var(--text-muted)",
          }}
        >
          <span>{title || language}</span>
          <button
            type="button"
            onClick={copy}
            className="btn btn--secondary"
            style={{
              padding: "3px 8px",
              height: 26,
              fontSize: 12,
              display: "inline-flex",
              alignItems: "center",
              gap: 5,
            }}
          >
            {copied ? (
              <>
                <CheckIcon width={13} height={13} style={{ color: "var(--success-fg)" }} />
                <span>Copied!</span>
              </>
            ) : (
              <>
                <CopyIcon width={13} height={13} />
                <span>Copy</span>
              </>
            )}
          </button>
        </div>
      )}
      {description && (
        <p
          style={{
            margin: 0,
            padding: "8px 12px",
            fontSize: 12.5,
            color: "var(--text-muted)",
            borderBottom: "1px solid var(--border)",
            background: "var(--surface)",
          }}
        >
          {description}
        </p>
      )}
      <div style={{ position: "relative" }}>
        {!title && !language && (
          <button
            type="button"
            onClick={copy}
            className="btn btn--secondary"
            style={{
              position: "absolute",
              top: 8,
              right: 8,
              padding: "3px 8px",
              height: 26,
              fontSize: 12,
              display: "inline-flex",
              alignItems: "center",
              gap: 5,
              zIndex: 1,
            }}
          >
            {copied ? (
              <>
                <CheckIcon width={13} height={13} style={{ color: "var(--success-fg)" }} />
                <span>Copied!</span>
              </>
            ) : (
              <>
                <CopyIcon width={13} height={13} />
                <span>Copy</span>
              </>
            )}
          </button>
        )}
        <pre
          style={{
            margin: 0,
            padding: "12px 14px",
            fontSize: 12.5,
            fontFamily: "var(--font-mono)",
            lineHeight: 1.55,
            overflowX: "auto",
            color: "var(--text)",
            whiteSpace: "pre-wrap",
            wordBreak: "break-all",
          }}
        >
          <code>{code}</code>
        </pre>
      </div>
    </div>
  );
}

