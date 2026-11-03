import { KeyboardEvent, ReactNode, useEffect, useRef, useState } from "react";
import { DayCounts, Outcome, OutcomeCounts } from "../api";
import { OUTCOME_LABELS } from "../events";
import { ErrorIcon, SuccessIcon, WarningIcon } from "./Icons";

// Status colors, fixed in both themes (see --status-* in styles.css). They
// never carry meaning alone: every use sits next to its icon and label.
export const OUTCOMES: Outcome[] = ["success", "warning", "error"];
const OUTCOME_ICON = { success: SuccessIcon, warning: WarningIcon, error: ErrorIcon };

export function OutcomeIcon({ outcome, size = 14 }: { outcome: Outcome; size?: number }) {
  const Icon = OUTCOME_ICON[outcome];
  return <Icon width={size} height={size} className={`outcome-icon outcome-icon--${outcome}`} aria-hidden="true" />;
}

/** Icon plus word, for a single event's outcome. */
export function OutcomeTag({ outcome }: { outcome: Outcome }) {
  return (
    <span className={`outcome-tag outcome-tag--${outcome}`}>
      <OutcomeIcon outcome={outcome} size={13} />
      {OUTCOME_LABELS[outcome]}
    </span>
  );
}

export function OutcomeLegend() {
  return (
    <ul className="chart-legend" aria-label="Legend">
      {OUTCOMES.map((o) => (
        <li key={o}>
          <span className={`chart-swatch chart-swatch--${o}`} />
          {OUTCOME_LABELS[o]}
        </li>
      ))}
    </ul>
  );
}

const fmt = new Intl.NumberFormat();
export const formatCount = (n: number) => fmt.format(n);

export function formatDay(day: number, long = false) {
  return new Date(day * 1000).toLocaleDateString(undefined, {
    timeZone: "UTC",
    month: "short",
    day: "numeric",
    ...(long ? { weekday: "short" } : {}),
  });
}

const total = (c: OutcomeCounts) => c.success + c.warning + c.error;

/** A clean axis maximum and step: 0 / 5 / 10 / 15 / 20, never 0 / 7 / 14. */
function niceScale(max: number, ticks = 4) {
  if (max <= 0) return { top: ticks, step: 1 };
  const rough = max / ticks;
  const mag = 10 ** Math.floor(Math.log10(rough));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= rough) ?? 10 * mag;
  const roundStep = step < 1 ? 1 : step;
  return { top: Math.ceil(max / roundStep) * roundStep, step: roundStep };
}

function compact(n: number) {
  return n >= 10000 ? `${Math.round(n / 1000)}K` : fmt.format(n);
}

/** Only the top corners rounded, so a column stays anchored to the baseline. */
function topRoundedRect(x: number, y: number, w: number, h: number, r: number) {
  const rr = Math.min(r, w / 2, h);
  return `M${x},${y + h}V${y + rr}Q${x},${y} ${x + rr},${y}H${x + w - rr}Q${x + w},${y} ${x + w},${y + rr}V${y + h}Z`;
}

function useWidth<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    if (!ref.current) return;
    const observer = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width));
    observer.observe(ref.current);
    return () => observer.disconnect();
  }, []);
  return { ref, width };
}

/** Events per day, stacked by outcome, with a hover/keyboard tooltip and a
 * table view of the same numbers. */
export function DailyChart({ series, height = 220, label }: { series: DayCounts[]; height?: number; label: string }) {
  const { ref, width } = useWidth<HTMLDivElement>();
  const [active, setActive] = useState<number | null>(null);
  const [asTable, setAsTable] = useState(false);

  const margin = { top: 10, right: 4, bottom: 24, left: 40 };
  const innerW = Math.max(0, width - margin.left - margin.right);
  const innerH = height - margin.top - margin.bottom;
  const { top, step } = niceScale(Math.max(0, ...series.map(total)));
  const y = (v: number) => innerH - (v / top) * innerH;
  const band = series.length ? innerW / series.length : 0;
  const barW = Math.max(2, Math.min(28, band * 0.62));
  // Enough room between date labels that they never collide.
  const labelEvery = Math.max(1, Math.ceil(64 / Math.max(band, 1)));

  const onKeyDown = (e: KeyboardEvent<SVGSVGElement>) => {
    if (!series.length) return;
    if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
      e.preventDefault();
      const delta = e.key === "ArrowRight" ? 1 : -1;
      setActive((a) => Math.min(series.length - 1, Math.max(0, (a ?? (delta > 0 ? -1 : series.length)) + delta)));
    } else if (e.key === "Escape") {
      setActive(null);
    }
  };

  const activeDay = active !== null ? series[active] : null;

  return (
    <div className="chart">
      <div className="chart__toolbar">
        <OutcomeLegend />
        <button type="button" className="btn btn--ghost chart__view-toggle" onClick={() => setAsTable((t) => !t)}>
          {asTable ? "Show chart" : "Show as table"}
        </button>
      </div>

      {asTable ? (
        <div className="table-wrap chart__table">
          <table className="table">
            <thead>
              <tr>
                <th>Day</th>
                {OUTCOMES.map((o) => (
                  <th key={o} style={{ textAlign: "right" }}>
                    {OUTCOME_LABELS[o]}
                  </th>
                ))}
                <th style={{ textAlign: "right" }}>Total</th>
              </tr>
            </thead>
            <tbody>
              {series.map((d) => (
                <tr key={d.day}>
                  <td>{formatDay(d.day, true)}</td>
                  {OUTCOMES.map((o) => (
                    <td key={o} style={{ textAlign: "right" }}>
                      {formatCount(d[o])}
                    </td>
                  ))}
                  <td style={{ textAlign: "right", fontWeight: 600 }}>{formatCount(total(d))}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="chart__plot" ref={ref} style={{ height }}>
          {width > 0 && (
            <svg
              width={width}
              height={height}
              role="img"
              aria-label={`${label}. Use the left and right arrow keys to read each day.`}
              tabIndex={0}
              onKeyDown={onKeyDown}
              onMouseLeave={() => setActive(null)}
              onBlur={() => setActive(null)}
            >
              <g transform={`translate(${margin.left},${margin.top})`}>
                {Array.from({ length: Math.round(top / step) + 1 }, (_, i) => i * step).map((t) => (
                  <g key={t}>
                    <line className="chart__grid" x1={0} x2={innerW} y1={y(t)} y2={y(t)} />
                    <text className="chart__tick" x={-8} y={y(t)} dy="0.32em" textAnchor="end">
                      {compact(t)}
                    </text>
                  </g>
                ))}

                {series.map((d, i) => {
                  const cx = i * band + band / 2;
                  let base = innerH;
                  const visible = OUTCOMES.filter((o) => d[o] > 0);
                  return (
                    <g key={d.day}>
                      {active === i && (
                        <rect className="chart__hover-band" x={i * band} y={0} width={band} height={innerH} rx={4} />
                      )}
                      {visible.map((o, k) => {
                        const h = innerH - y(d[o]);
                        const isTop = k === visible.length - 1;
                        // A 2px surface gap between stacked segments.
                        const gap = isTop ? 0 : Math.min(2, h / 2);
                        const segY = base - h;
                        base = segY;
                        const segH = Math.max(1, h - gap);
                        return isTop ? (
                          <path key={o} className={`chart__mark chart__mark--${o}`} d={topRoundedRect(cx - barW / 2, segY, barW, segH, 4)} />
                        ) : (
                          <rect key={o} className={`chart__mark chart__mark--${o}`} x={cx - barW / 2} y={segY + gap} width={barW} height={segH} />
                        );
                      })}
                      {/* Counted back from today, so the newest day always has a label. */}
                      {(series.length - 1 - i) % labelEvery === 0 && (
                          <text className="chart__tick" x={cx} y={innerH + 16} textAnchor="middle">
                            {formatDay(d.day)}
                          </text>
                        )}
                      {/* Hit area: the whole day, taller and wider than the column. */}
                      <rect
                        x={i * band}
                        y={0}
                        width={band}
                        height={innerH}
                        fill="transparent"
                        onMouseEnter={() => setActive(i)}
                      />
                    </g>
                  );
                })}
                <line className="chart__baseline" x1={0} x2={innerW} y1={innerH} y2={innerH} />
              </g>
            </svg>
          )}

          {activeDay && active !== null && (
            <div
              className="chart-tooltip"
              role="status"
              // Beside the day it describes, flipping to the left near the right edge.
              style={
                margin.left + (active + 1) * band + 180 < width
                  ? { left: margin.left + (active + 1) * band + 6, top: margin.top }
                  : { left: margin.left + active * band - 6, top: margin.top, transform: "translateX(-100%)" }
              }
            >
              <div className="chart-tooltip__title">{formatDay(activeDay.day, true)}</div>
              {OUTCOMES.map((o) => (
                <div key={o} className="chart-tooltip__row">
                  <OutcomeIcon outcome={o} size={13} />
                  <span>{OUTCOME_LABELS[o]}</span>
                  <strong>{formatCount(activeDay[o])}</strong>
                </div>
              ))}
              <div className="chart-tooltip__row chart-tooltip__total">
                <span>Total</span>
                <strong>{formatCount(total(activeDay))}</strong>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export interface BreakdownRow extends OutcomeCounts {
  key: string;
  label: ReactNode;
  sublabel?: string;
  total: number;
}

/** Ranked horizontal bars, each split by outcome. Clicking a row picks it. */
export function BreakdownBars({
  rows,
  onSelect,
  selected,
  empty,
}: {
  rows: BreakdownRow[];
  onSelect?: (key: string) => void;
  selected?: string;
  empty: string;
}) {
  if (rows.length === 0) return <p className="chart-empty">{empty}</p>;
  const max = Math.max(...rows.map((r) => r.total), 1);
  return (
    <ol className="breakdown">
      {rows.map((row) => {
        const breakdown = OUTCOMES.filter((o) => row[o] > 0)
          .map((o) => `${formatCount(row[o])} ${OUTCOME_LABELS[o].toLowerCase()}`)
          .join(", ");
        const content = (
          <>
            <span className="breakdown__label">
              <span className="breakdown__name">{row.label}</span>
              {row.sublabel && <span className="breakdown__sub">{row.sublabel}</span>}
            </span>
            <span className="breakdown__track" aria-hidden="true">
              <span className="breakdown__bar" style={{ width: `${(row.total / max) * 100}%` }}>
                {OUTCOMES.filter((o) => row[o] > 0).map((o) => (
                  <span key={o} className={`breakdown__seg chart__mark--${o}`} style={{ flexGrow: row[o] }} />
                ))}
              </span>
            </span>
            <span className="breakdown__total">{formatCount(row.total)}</span>
            <span className="breakdown__tip" role="tooltip">
              {breakdown}
            </span>
          </>
        );
        return (
          <li key={row.key}>
            {onSelect ? (
              <button
                type="button"
                className={`breakdown__row${selected === row.key ? " is-selected" : ""}`}
                aria-label={`${typeof row.label === "string" ? row.label : row.key}: ${breakdown}. Show only this.`}
                aria-pressed={selected === row.key}
                onClick={() => onSelect(row.key)}
              >
                {content}
              </button>
            ) : (
              <div className="breakdown__row" aria-label={breakdown}>
                {content}
              </div>
            )}
          </li>
        );
      })}
    </ol>
  );
}

/** The three totals for a period, each with its icon and word. */
export function OutcomeTotals({ totals }: { totals: OutcomeCounts }) {
  const all = total(totals);
  return (
    <dl className="outcome-totals">
      <div className="outcome-totals__item outcome-totals__item--all">
        <dt>Events</dt>
        <dd>{formatCount(all)}</dd>
      </div>
      {OUTCOMES.map((o) => (
        <div key={o} className="outcome-totals__item">
          <dt>
            <OutcomeIcon outcome={o} />
            {OUTCOME_LABELS[o]}
          </dt>
          <dd>
            {formatCount(totals[o])}
            {all > 0 && <span className="outcome-totals__share">{Math.round((totals[o] / all) * 100)}%</span>}
          </dd>
        </div>
      ))}
    </dl>
  );
}
