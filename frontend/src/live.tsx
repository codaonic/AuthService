// One live connection for the whole console (GET /admin/api/stream). Pages
// subscribe with useLiveEvents() and update themselves as things happen,
// instead of waiting for a refresh.
import { createContext, ReactNode, useContext, useEffect, useRef, useState } from "react";
import { AuditEvent } from "./api";

/** "resync": the connection came back after a drop; reload what's shown, as
 * events from while it was down were missed. */
export type LiveMessage = AuditEvent | "resync";
type Listener = (message: LiveMessage) => void;
export type LiveStatus = "connecting" | "live" | "reconnecting";

interface LiveContextValue {
  subscribe: (listener: Listener) => () => void;
  status: LiveStatus;
}

const LiveContext = createContext<LiveContextValue>({ subscribe: () => () => {}, status: "connecting" });

export function LiveEventsProvider({ children }: { children: ReactNode }) {
  const listeners = useRef(new Set<Listener>());
  const [status, setStatus] = useState<LiveStatus>("connecting");

  useEffect(() => {
    // EventSource reconnects by itself (the server asks for 3 seconds).
    const source = new EventSource("/admin/api/stream");
    let dropped = false;
    const emit = (m: LiveMessage) => listeners.current.forEach((l) => l(m));

    source.onopen = () => {
      setStatus("live");
      if (dropped) emit("resync");
      dropped = false;
    };
    source.onerror = () => {
      dropped = true;
      setStatus("reconnecting");
    };
    source.onmessage = (e) => {
      try {
        emit(JSON.parse(e.data) as AuditEvent);
      } catch {
        /* not an event -- ignore */
      }
    };
    return () => source.close();
  }, []);

  const subscribe = (listener: Listener) => {
    listeners.current.add(listener);
    return () => {
      listeners.current.delete(listener);
    };
  };

  return <LiveContext.Provider value={{ subscribe, status }}>{children}</LiveContext.Provider>;
}

/** Calls `handler` for every live event, always with the page's latest state. */
export function useLiveEvents(handler: Listener) {
  const { subscribe } = useContext(LiveContext);
  const latest = useRef(handler);
  latest.current = handler;
  useEffect(() => subscribe((m) => latest.current(m)), [subscribe]);
}

export function useLiveStatus(): LiveStatus {
  return useContext(LiveContext).status;
}

/** A small "Live" / "Reconnecting…" note for page headers. */
export function LiveIndicator() {
  const status = useLiveStatus();
  return (
    <span className={`live-indicator live-indicator--${status}`} role="status">
      <span className="live-indicator__dot" aria-hidden="true" />
      {status === "live" ? "Updating live" : status === "reconnecting" ? "Reconnecting…" : "Connecting…"}
    </span>
  );
}

/** Runs `fn` once things go quiet for `ms`, so a burst of events causes one reload. */
export function useDebounced(fn: () => void, ms: number) {
  const timer = useRef<ReturnType<typeof setTimeout>>();
  const latest = useRef(fn);
  latest.current = fn;
  useEffect(() => () => clearTimeout(timer.current), []);
  return () => {
    clearTimeout(timer.current);
    timer.current = setTimeout(() => latest.current(), ms);
  };
}
