/* Boards and agents: the rail on the left, and the bar over the selected board's terminal.
   Boards are tinted by state: sage free, pink in use, peach held or paused, lilac in
   maintenance. Problems turn them yellow or red. */
import { useRef, type MouseEvent, type ReactNode } from "react";
import { cls } from "./util.js";
import { Pill, Issue, type PillProps, type IssueProps } from "./status.js";
import { Button } from "./controls.js";

/** Board states, lower case, as the CSS tints them. */
export const BOARD_STATES = ["available", "leased", "paused", "human", "maintenance", "offline", "needs_recover"] as const;
export type BoardState = (typeof BOARD_STATES)[number];

export interface BoardCardProps {
  /** The board's name, e.g. "nrf9161dk-1". */
  id: string;
  state?: BoardState;
  /** The pill on the right. Defaults to the state, outlined when available. */
  status?: PillProps;
  /** "" | "warn" | "err" when something needs attention. */
  level?: "" | "warn" | "err";
  selected?: boolean;
  /** The line under the name: who holds it, its platform, or what's wrong. */
  line?: ReactNode;
  lineLevel?: "" | "warn" | "err";
  /** Extra classes for the line, e.g. "muted mono" for a platform name. */
  lineClass?: string;
  onSelect?: () => void;
}

/** One board in the rail: name, status pill and one line under it. */
export function BoardCard({ id, state = "available", status, level = "", selected = false, line, lineLevel = "", lineClass = "", onSelect }: BoardCardProps) {
  return (
    <div className={cls("board", `st-${state}`, selected && "sel", level)} tabIndex={0} role="button" aria-pressed={selected ? "true" : "false"}
      onClick={onSelect}
      onKeyDown={onSelect ? (ev) => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); onSelect(); } } : undefined}>
      <div className="top"><span className="name">{id}</span><Pill {...(status || { text: state, tone: state === "available" ? "free" : "busy" })} /></div>
      {line ? <div className={cls("line", lineLevel, lineClass)}>{line}</div> : null}
    </div>
  );
}

/** A dashed button under the boards when a probe is plugged in but not set up. */
export function ProbeChip({ count = 1, onClick }: { count?: number; onClick?: () => void }) {
  return <button type="button" className="probe-chip" onClick={onClick}><b>{`${count} new probe${count === 1 ? "" : "s"}`}</b>{" found · Add"}</button>;
}

export interface AgentRowProps {
  label: ReactNode;
  /** "" (idle) | "on" (holds a board) | "warn" (not responding). */
  dot?: "" | "on" | "warn";
  /** What it's doing, on the right: "nrf9161dk-1", "waiting for sim-1", "idle". */
  what?: ReactNode;
  title?: string;
}

/** One agent in the rail. Put rows inside an element with id "sessions" to get the rail's layout. */
export function AgentRow({ label, dot = "", what, title }: AgentRowProps) {
  return <div className="agent" title={title}><span className={cls("dot", dot)} /><b className="who">{label}</b><span className="what">{what || ""}</span></div>;
}

export interface HolderRowProps {
  /** Who holds the board. Leave out for a free board, which shows its platform instead. */
  holder?: ReactNode;
  paused?: boolean;
  /** Time left on the lease, e.g. "12m 40s", set large. */
  left?: string;
  /** What the holder is doing now, e.g. "test · 1m 05s". */
  op?: ReactNode;
  /** The reason the agent gave for taking the board. */
  reason?: string;
  platform?: ReactNode;
}

/** Who has the board, framed, with the time left set large. */
export function HolderRow({ holder, paused = false, left, op, reason, platform }: HolderRowProps) {
  if (!holder) return <div className="holder-row"><span className="muted mono">{platform || ""}</span></div>;
  return (
    <div className="holder-row">
      <span className="holder"><span className="k">{paused ? "Paused" : "Held by"}</span><b>{holder}</b></span>
      {left ? <span className="left"><span className="big-num">{left}</span>{left === "on hold" || left.startsWith("ends") ? "" : " left"}</span> : null}
      {op ? <span className="op">{op}</span> : null}
      {reason ? <span className="reason" title={reason}>{`“${reason}”`}</span> : null}
    </div>
  );
}

export interface ChipProps {
  label: ReactNode;
  value?: ReactNode;
  /** "" | "on" (pink) | "ok" (sage) | "warn" | "err". */
  tone?: "" | "on" | "ok" | "warn" | "err";
  onClick?: () => void;
}

/** A chip under the board's name that opens a panel. */
export function Chip({ label, value, tone = "", onClick }: ChipProps) {
  return <button type="button" className={cls("chip", tone)} onClick={onClick}><span className="k">{label}</span>{value ? <b>{value}</b> : null}</button>;
}

/** The row of chips: Queue, Power, Tests, Activity. */
export function ChipStrip({ chips = [] }: { chips?: ChipProps[] }) {
  return <div className="strip">{chips.map((c, i) => <Chip key={i} {...c} />)}</div>;
}

export interface BoardActionsProps {
  /** The one main button, usually primary. */
  main?: ReactNode;
  /** The rest, under Actions ▾. */
  more?: ReactNode[];
  onInfo?: () => void;
}

/** The board's actions: its one main button, the rest under Actions ▾, and Info. */
export function BoardActions({ main, more = [], onInfo }: BoardActionsProps) {
  const ref = useRef<HTMLDetailsElement>(null);
  const close = (ev: MouseEvent) => {
    if ((ev.target as Element).closest("button")) setTimeout(() => { if (ref.current) ref.current.open = false; }, 0);
  };
  return (
    <div className="head-actions">
      {main || null}
      {more.length ? <details ref={ref} className="menu"><summary>Actions ▾</summary><div className="menu-body" onClick={close}>{more}</div></details> : null}
      <Button label="Info" onClick={onInfo} />
    </div>
  );
}

export interface BoardBarProps {
  id: string;
  state?: BoardState;
  level?: "" | "warn" | "err";
  status?: PillProps;
  /** A BoardActions element. */
  actions?: ReactNode;
  /** A HolderRow element. */
  holder?: ReactNode;
  chips?: ChipProps[];
  issues?: IssueProps[];
}

/** The bar over the terminal: the board's name in large serif, status, actions, holder, chips and problems. Tinted like the rail card. */
export function BoardBar({ id, state = "available", level = "", status, actions, holder, chips = [], issues = [] }: BoardBarProps) {
  return (
    <div className={cls("boardbar", `st-${state}`, level)}>
      <div className="head-row">
        <div className="head-main"><span className="name">{id}</span>{status ? <Pill {...status} /> : null}</div>
        {actions || null}
      </div>
      <div className="meta-row">{holder || null}<ChipStrip chips={chips} /></div>
      <div className="issues">{issues.map((x, i) => <Issue key={i} {...x} />)}</div>
    </div>
  );
}

/** One label/value row; tone colours the value ("warn", "err"). Falsy rows are skipped. */
export type KeyValuesRow = [ReactNode, ReactNode, string?] | null | false | undefined;

/** Label/value pairs in two columns, as in the board's Info sheet. */
export function KeyValues({ rows = [] }: { rows?: KeyValuesRow[] }) {
  return (
    <div className="kv">
      {rows.filter((r): r is [ReactNode, ReactNode, string?] => !!r).map(([k, v, tone], i) => [
        <span key={`k${i}`} className="k">{k}</span>,
        <span key={`v${i}`} className={cls("v", tone)}>{v}</span>,
      ])}
    </div>
  );
}
