import { CopyIcon } from "./Icons";
import { useToast } from "./ToastProvider";

// Truncates the middle so the start (often meaningful, e.g. a URL's host)
// and the end both stay visible -- e.g. "https://mcp.exam…12345" instead of
// cutting off the tail.
function truncateMiddle(value: string, max = 36): string {
  if (value.length <= max) return value;
  const half = Math.floor((max - 1) / 2);
  return `${value.slice(0, half)}…${value.slice(value.length - half)}`;
}

export function CopyableId({ value, max }: { value: string; max?: number }) {
  const { show } = useToast();

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(value);
      show("Copied to clipboard");
    } catch {
      show("Couldn't copy -- your browser blocked clipboard access", "error");
    }
  };

  return (
    <span className="copyable-id">
      <span className="copyable-id__value" title={value}>
        {truncateMiddle(value, max)}
      </span>
      <button type="button" className="copyable-id__btn" aria-label="Copy to clipboard" onClick={copy}>
        <CopyIcon width={14} height={14} />
      </button>
    </span>
  );
}
