import { useEffect, useRef, useState } from "react";
import { ChartIcon } from "../components/Icons";
import { BreakdownBars, DailyChart, formatCount, OutcomeTag, OutcomeTotals } from "../components/charts";
import { eventLabel } from "../events";
import { Analytics as AnalyticsData, api, Client } from "../api";

const PERIODS = [7, 30, 90];

export function Analytics() {
  const [days, setDays] = useState(30);
  const [clientId, setClientId] = useState("");
  const [person, setPerson] = useState("");
  const [personInput, setPersonInput] = useState("");
  const [data, setData] = useState<AnalyticsData | null>(null);
  const [clients, setClients] = useState<Client[]>([]);
  const request = useRef(0);

  // The application list only changes elsewhere, so it's loaded once.
  useEffect(() => {
    api.get<Client[]>("/clients").then(setClients);
  }, []);

  useEffect(() => {
    const t = setTimeout(() => setPerson(personInput.trim()), 400);
    return () => clearTimeout(t);
  }, [personInput]);

  useEffect(() => {
    const id = ++request.current;
    const params = new URLSearchParams({ days: String(days) });
    if (clientId) params.set("client_id", clientId);
    if (person) params.set("user", person);
    api.get<AnalyticsData>(`/analytics?${params}`).then((d) => {
      if (id === request.current) setData(d);
    });
  }, [days, clientId, person]);

  const names = new Map(clients.map((c) => [c.client_id, c.client_name || c.client_id]));
  const appName = (id: string) => names.get(id) ?? id;
  const scope = [clientId && appName(clientId), person].filter(Boolean).join(" and ");
  const pickPerson = (p: string) => {
    const next = person === p ? "" : p;
    setPersonInput(next);
    setPerson(next);
  };

  return (
    <>
      <div className="header">
        <div className="header__title-row">
          <span className="header__icon">
            <ChartIcon />
          </span>
          <h1 className="title">Analytics</h1>
        </div>
        <div className="segmented" role="radiogroup" aria-label="Period">
          {PERIODS.map((p) => (
            <button key={p} type="button" role="radio" aria-checked={days === p} onClick={() => setDays(p)}>
              {p} days
            </button>
          ))}
        </div>
      </div>
      <p className="lead">
        What happened {scope ? <>for <strong>{scope}</strong></> : "across every application"} over the
        last {days} days, from the Activity log.
      </p>

      <div className="filter-bar">
        <select aria-label="Application" value={clientId} onChange={(e) => setClientId(e.target.value)}>
          <option value="">All applications</option>
          {clients.map((c) => (
            <option key={c.client_id} value={c.client_id}>
              {c.client_name || c.client_id}
            </option>
          ))}
        </select>
        <input
          type="search"
          aria-label="Person"
          placeholder="One person's email or user ID"
          value={personInput}
          onChange={(e) => setPersonInput(e.target.value)}
        />
        {(clientId || person) && (
          <button
            type="button"
            className="btn btn--ghost"
            onClick={() => {
              setClientId("");
              setPersonInput("");
              setPerson("");
            }}
          >
            Show everything
          </button>
        )}
      </div>

      {!data ? (
        <p className="field__hint">Loading…</p>
      ) : (
        <div className="analytics">
          <OutcomeTotals totals={data.totals} />

          <section className="panel">
            <h2 className="panel__title">Events per day</h2>
            <DailyChart series={data.series} label={`Events per day over the last ${days} days, by outcome`} />
          </section>

          <div className="analytics__split">
            <section className="panel">
              <h2 className="panel__title">By application</h2>
              <p className="panel__hint">Select one to see only its activity.</p>
              <BreakdownBars
                rows={data.applications.map((a) => ({
                  ...a,
                  key: a.client_id,
                  label: a.client_name || appName(a.client_id),
                  sublabel: a.client_name ? a.client_id : undefined,
                }))}
                selected={clientId}
                onSelect={(k) => setClientId(clientId === k ? "" : k)}
                empty="No activity tied to an application in this period."
              />
            </section>
            <section className="panel">
              <h2 className="panel__title">By person</h2>
              <p className="panel__hint">The 10 people with the most activity.</p>
              <BreakdownBars
                rows={data.users.map((u) => ({ ...u, key: u.user, label: u.user }))}
                selected={person}
                onSelect={pickPerson}
                empty="No activity tied to a person in this period."
              />
            </section>
          </div>

          <section className="panel">
            <h2 className="panel__title">Most common events</h2>
            {data.events.length === 0 ? (
              <p className="chart-empty">Nothing happened in this period.</p>
            ) : (
              <ol className="event-ranking">
                {data.events.map((e) => (
                  <li key={`${e.event}-${e.outcome}`}>
                    <OutcomeTag outcome={e.outcome} />
                    <span className="event-ranking__name">{eventLabel(e.event)}</span>
                    <span className="event-ranking__count">{formatCount(e.count)}</span>
                  </li>
                ))}
              </ol>
            )}
          </section>

          <p className="analytics__note">
            <strong>How events are counted.</strong> Error: something failed, such as a wrong password or a
            rejected certificate. Warning: worth a look but not a failure, such as unusual activity or an
            email that couldn't be sent. Success: everything else. Days are in UTC.
          </p>
        </div>
      )}
    </>
  );
}
