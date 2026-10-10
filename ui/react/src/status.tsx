/* Status labels and messages. Yellow (warn) and red (err) only ever mean "look at this". */
import type { ReactNode } from "react";
import { cls } from "./util.js";

export type Tone = "" | "free" | "busy" | "warn" | "err";

export interface PillProps {
  text: ReactNode;
  /** "" | "free" (outlined) | "busy" (ink) | "warn" (yellow) | "err" (red). */
  tone?: Tone;
  dot?: boolean;
}

/** A rounded status label. */
export function Pill({ text, tone = "", dot = true }: PillProps) {
  return <span className={cls("pill", tone)}>{dot ? <span className="dot" /> : null}{text}</span>;
}

/** The header's connection pill: "Live", or red "Reconnecting to arbiterd". */
export function ConnPill({ up = true }: { up?: boolean }) {
  return (
    <span id="conn" className={cls("pill", !up && "down")}>
      <span className="dot" /><span id="conn-text">{up ? "Live" : "Reconnecting to arbiterd"}</span>
    </span>
  );
}

/** A small outlined tag, like "applies now" or "after restart" on a settings field. */
export function Tag({ text, restart = false }: { text: ReactNode; restart?: boolean }) {
  return <span className={cls("tag", restart && "restart")}>{text}</span>;
}

export interface AlertProps {
  text: ReactNode;
  /** "warn" (a person needs to act) | "err" (something failed) | "note" (plain information). */
  level?: "warn" | "err" | "note";
  /** Buttons on the right. */
  actions?: ReactNode;
}

/** A banner across the top of the page, used for approvals an agent is waiting on. */
export function Alert({ text, level = "warn", actions }: AlertProps) {
  const has = Array.isArray(actions) ? actions.length > 0 : !!actions;
  return (
    <div className={`alert ${level}`} role={level === "note" ? undefined : "status"}>
      <span className="text">{text}</span>
      {has ? <span className="btn-row">{actions}</span> : null}
    </div>
  );
}

export interface IssueProps {
  text: ReactNode;
  level?: "warn" | "err";
}

/** One problem with a board, shown under its name. */
export function Issue({ text, level = "warn" }: IssueProps) {
  return <div className={`issue ${level}`}>{text}</div>;
}

/** A short message in the corner. */
export function Toast({ text, level = "" }: { text: ReactNode; level?: "" | "warn" | "err" }) {
  return <div className={cls("toast", level)} role="status">{text}</div>;
}

/** Grey placeholder text for an empty list, with optional buttons after it. */
export function Empty({ text, children }: { text: ReactNode; children?: ReactNode }) {
  return <div className="empty">{text}{children}</div>;
}
