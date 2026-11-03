import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { ActivityIcon } from "../components/Icons";
import { ActivityList } from "../components/ActivityList";
import { EmptyState } from "../components/EmptyState";
import { OUTCOMES, OutcomeIcon } from "../components/charts";
import { OUTCOME_LABELS } from "../events";
import { api, AuditEvent, Outcome } from "../api";

const PAGE = 100;

export function AuditLog() {
  const [events, setEvents] = useState<AuditEvent[] | null>(null);
  const [outcome, setOutcome] = useState<Outcome | "">("");
  // A person's panel links here already searched for them (?q=email).
  const [params] = useSearchParams();
  const [search, setSearch] = useState(params.get("q") ?? "");
  const [query, setQuery] = useState(params.get("q") ?? "");
  const [hasMore, setHasMore] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const request = useRef(0);

  // Wait for a pause in typing instead of asking the server on every key.
  useEffect(() => {
    const t = setTimeout(() => setQuery(search.trim()), 300);
    return () => clearTimeout(t);
  }, [search]);

  const fetchPage = (before?: number) => {
    const params = new URLSearchParams({ limit: String(PAGE) });
    if (outcome) params.set("outcome", outcome);
    if (query) params.set("q", query);
    if (before !== undefined) params.set("before", String(before));
    return api.get<AuditEvent[]>(`/audit?${params}`);
  };

  useEffect(() => {
    const id = ++request.current;
    setEvents(null);
    fetchPage().then((page) => {
      // Ignore answers to filters the admin has already changed.
      if (id !== request.current) return;
      setEvents(page);
      setHasMore(page.length === PAGE);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [outcome, query]);

  const loadOlder = async () => {
    if (!events?.length) return;
    setLoadingMore(true);
    try {
      const page = await fetchPage(events[events.length - 1].ts);
      setEvents((prev) => [...(prev ?? []), ...page]);
      setHasMore(page.length === PAGE);
    } finally {
      setLoadingMore(false);
    }
  };

  const filtered = Boolean(outcome || query);

  return (
    <>
      <div className="header">
        <div className="header__title-row">
          <span className="header__icon">
            <ActivityIcon />
          </span>
          <h1 className="title">Activity log</h1>
        </div>
      </div>
      <p className="lead">
        Sign-ins, signups and changes made in this console. Entries are kept for 90 days by default
        (AUDIT_RETENTION_DAYS).
      </p>

      <div className="filter-bar">
        <input
          type="search"
          aria-label="Search activity"
          placeholder="Search by email, application, IP…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <div className="segmented" role="radiogroup" aria-label="Show">
          <button type="button" role="radio" aria-checked={outcome === ""} onClick={() => setOutcome("")}>
            All
          </button>
          {OUTCOMES.map((o) => (
            <button key={o} type="button" role="radio" aria-checked={outcome === o} onClick={() => setOutcome(o)}>
              <OutcomeIcon outcome={o} size={13} />
              {OUTCOME_LABELS[o]}
            </button>
          ))}
        </div>
      </div>

      {events === null ? (
        <p className="field__hint">Loading…</p>
      ) : events.length === 0 ? (
        <EmptyState
          icon={<ActivityIcon width={20} height={20} />}
          title={filtered ? "Nothing matches" : "No activity yet"}
          description={
            filtered
              ? "Try another search, or show all outcomes."
              : "Sign-ins, signups and admin changes will appear here as they happen."
          }
        />
      ) : (
        <>
          <ActivityList events={events} />
          {hasMore && (
            <button type="button" className="btn btn--secondary" style={{ marginTop: 16 }} disabled={loadingMore} onClick={loadOlder}>
              {loadingMore ? "Loading…" : "Show older activity"}
            </button>
          )}
        </>
      )}
    </>
  );
}
