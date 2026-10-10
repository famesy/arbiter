/* What the chips open: the queue, power, test runs and activity, each in a sheet. */
import type { MouseEvent, ReactNode } from "react";
import { cls } from "./util.js";
import { Button } from "./controls.js";
import { Pill, type PillProps } from "./status.js";

export interface SheetProps {
  title: ReactNode;
  children?: ReactNode;
  /** Shows it in place. The dashboard opens it as a modal instead. */
  open?: boolean;
  id?: string;
  onClose?: () => void;
}

/** A sheet: the dialog the chips and Info open over the page, with a serif title and a close button. */
export function Sheet({ title, children, open = false, id = "sheet", onClose }: SheetProps) {
  const close = (ev: MouseEvent<HTMLButtonElement>) => (onClose ? onClose() : ev.currentTarget.closest("dialog")?.close());
  return (
    <dialog id={id || undefined} open={open || undefined} aria-labelledby={id ? `${id}-title` : undefined}>
      <div className="sheet-head">
        <h2 id={id ? `${id}-title` : undefined}>{title}</h2>
        <Button label="×" size="icon" aria-label="Close" onClick={close} />
      </div>
      <div id={id ? `${id}-body` : undefined} className="sheet-body">{children}</div>
    </dialog>
  );
}

export interface QueueRowProps {
  position?: number;
  who: ReactNode;
  reason?: ReactNode;
  priority?: "low" | "normal" | "high" | "urgent";
  /** Placed at the front of the queue. */
  front?: boolean;
  urgent?: boolean;
  /** How long it has waited, e.g. "4m". */
  waiting?: ReactNode;
  /** Leave a callback out to disable its button. */
  onUp?: () => void;
  onDown?: () => void;
  onUrgent?: () => void;
  onRemove?: () => void;
}

/** One agent waiting for a board. Urgent rows show a dark pill. */
export function QueueRow({ position, who, reason, priority = "normal", front = false, urgent = false, waiting, onUp, onDown, onUrgent, onRemove }: QueueRowProps) {
  return (
    <tr>
      <td className="num muted">{position}</td>
      <td><div>{who}</div>{reason ? <div className="sub">{reason}</div> : null}</td>
      <td><span className={cls("pill", urgent && "busy")}>{String(priority)}{front && !urgent ? " · front" : ""}</span></td>
      <td className="num">{waiting}</td>
      <td className="actions">
        <span className="btn-row">
          <Button label="↑" size="icon" disabled={!onUp} title="Move up" aria-label="Move up" onClick={onUp} />
          <Button label="↓" size="icon" disabled={!onDown} title="Move down" aria-label="Move down" onClick={onDown} />
          <Button label="Urgent" size="small" disabled={urgent || !onUrgent} title="Mark urgent and move to the front" onClick={onUrgent} />
          <Button label="Remove" size="small" variant="danger" title="Remove from the queue" onClick={onRemove} />
        </span>
      </td>
    </tr>
  );
}

/** A board's queue, in order. */
export function QueueTable({ rows = [], empty = "Nobody is waiting for this board." }: { rows?: QueueRowProps[]; empty?: ReactNode }) {
  if (!rows.length) return <div className="empty">{empty}</div>;
  return (
    <table>
      <tbody>
        <tr><th>#</th><th>Agent</th><th>Priority</th><th>Waiting</th><th /></tr>
        {rows.map((r, i) => <QueueRow key={i} position={i + 1} {...r} />)}
      </tbody>
    </table>
  );
}

/** One measurement: a small label over a big number. */
export function Stat({ label, value }: { label: ReactNode; value: ReactNode }) {
  return <div className="stat"><div className="k">{label}</div><div className="big">{value}</div></div>;
}

export interface StatStripProps {
  /** [label, value] pairs: average, peak, ... */
  stats?: Array<[ReactNode, ReactNode]>;
  /** Turns the strip yellow. */
  warn?: boolean;
  note?: ReactNode;
}

/** A sage strip of measurements. */
export function StatStrip({ stats = [], warn = false, note }: StatStripProps) {
  return (
    <div className={cls("stats", warn && "warn")}>
      {stats.map(([label, value], i) => <Stat key={i} label={label} value={value} />)}
      {note ? <div style={{ flexBasis: "100%" }}>{note}</div> : null}
    </div>
  );
}

export interface SparkPoint { avg?: number; peak?: number }

export interface SparklineProps {
  points?: SparkPoint[];
  caption?: ReactNode;
}

/** A small line chart of recent measurements: solid average, dashed peak. */
export function Sparkline({ points = [], caption }: SparklineProps) {
  const W = 420, H = 64, pad = 3;
  const max = Math.max(...points.map((x) => x.peak || x.avg || 0)) || 1;
  const xs = (i: number) => pad + (i * (W - 2 * pad)) / Math.max(1, points.length - 1);
  const ys = (v: number) => H - pad - (v / max) * (H - 2 * pad);
  const pts = (k: "avg" | "peak") => points.map((x, i) => `${xs(i).toFixed(1)},${ys(x[k] || 0).toFixed(1)}`).join(" ");
  return (
    <div className="spark">
      {caption ? <div className="hint" style={{ margin: "0 0 var(--s2)" }}>{caption}</div> : null}
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none">
        {([["peak", "4 4", "0.45"], ["avg", "", "1"]] as const).map(([k, dash, op]) => (
          <polyline key={k} points={pts(k)} fill="none" stroke="currentColor" strokeWidth="2" strokeLinejoin="round"
            vectorEffect="non-scaling-stroke" opacity={op} strokeDasharray={dash || undefined} />
        ))}
      </svg>
    </div>
  );
}

export interface PowerPanelProps {
  on?: boolean;
  /** A fault reported by the supply, shown as a red pill. */
  fault?: string;
  /** Voltage now, e.g. "3.70 V", set large. */
  volts?: ReactNode;
  /** e.g. "safe range 3.0–4.2 V". */
  range?: ReactNode;
  /** Buttons for on/off/cycle/voltage. Leave out when there's no switch. */
  controls?: ReactNode;
  /** An agent holds the board. */
  locked?: boolean;
  stats?: StatStripProps;
  history?: SparklineProps;
  /** Shown instead of stats when there are none. */
  empty?: ReactNode;
}

/** The power sheet. */
export function PowerPanel({ on = true, fault, volts, range, controls, locked = false, stats, history, empty }: PowerPanelProps) {
  return (
    <div className="power-panel">
      <div className="power-top">
        <Pill tone={fault ? "err" : on ? "busy" : "warn"} text={fault ? `Fault: ${fault}` : on ? "On" : "Off"} />
        {volts ? <span className="big">{volts}</span> : null}
        {range ? <span className="muted small-text">{range}</span> : null}
      </div>
      {controls ? <div className="power-row btn-row">{controls}</div> : null}
      {locked ? <div className="hint">An agent holds this board. Pause it or take over to change power.</div> : null}
      {stats ? <StatStrip {...stats} /> : empty ? <div className="hint">{empty}</div> : null}
      {history && history.points && history.points.length > 1 ? <Sparkline {...history} /> : null}
    </div>
  );
}

export interface TestRunRowProps {
  started: ReactNode;
  agent: ReactNode;
  /** The result pill, e.g. { text: "11 passed", tone: "free" }. */
  result: PillProps;
  failed?: boolean;
  time?: ReactNode;
  logPath?: string;
  junit?: string;
  /** The last log lines. */
  tail?: string[];
}

/** One test run. */
export function TestRunRow({ started, agent, result, failed = false, time, logPath, junit, tail }: TestRunRowProps) {
  return (
    <tr className={failed ? "err" : undefined}>
      <td className="num muted">{started}</td>
      <td>{agent}</td>
      <td className="result">
        <Pill {...result} />
        {(tail && tail.length) || logPath ? (
          <details style={{ marginTop: "var(--s1)" }}>
            <summary>Log</summary>
            <div className="mono sub">{logPath || ""}</div>
            {junit ? <div className="mono sub">{`junit: ${junit}`}</div> : null}
            {tail ? <pre className="tail">{tail.join("\n")}</pre> : null}
          </details>
        ) : null}
      </td>
      <td className="num">{time}</td>
    </tr>
  );
}

/** A board's test runs, newest first. */
export function TestRunsTable({ rows = [], empty = "No test runs on this board yet." }: { rows?: TestRunRowProps[]; empty?: ReactNode }) {
  if (!rows.length) return <div className="empty">{empty}</div>;
  return (
    <table>
      <tbody>
        <tr><th>Started</th><th>Agent</th><th>Result</th><th>Time</th></tr>
        {rows.map((r, i) => <TestRunRow key={i} {...r} />)}
      </tbody>
    </table>
  );
}

/** One line of the activity feed. */
export function EventRow({ time, text, level = "" }: { time: ReactNode; text: ReactNode; level?: "" | "warn" | "err" }) {
  return <div className={cls("ev", level)}><span className="t">{time}</span><span>{text}</span></div>;
}
