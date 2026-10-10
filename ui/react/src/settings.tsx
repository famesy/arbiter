/* The Settings page: sections with serif titles, read-only fields, health-check rows and
   switches for this browser's preferences. */
import type { ReactNode } from "react";
import { cls } from "./util.js";

export interface SectionProps {
  /** Becomes the element id "set-<id>", for links from the settings nav. */
  id?: string;
  title: ReactNode;
  /** A sentence under the title. */
  sub?: ReactNode;
  children?: ReactNode;
}

/** A settings section card with a serif title and a sentence under it. */
export function Section({ id, title, sub, children }: SectionProps) {
  return <section className="card set-section" id={id ? `set-${id}` : undefined}><h2>{title}</h2>{sub ? <p className="sub">{sub}</p> : null}{children}</section>;
}

export interface FieldProps {
  label: ReactNode;
  value: ReactNode;
  hint?: ReactNode;
  /** Greys out a missing value. */
  muted?: boolean;
}

/** A read-only setting: label, value and an optional hint. */
export function Field({ label, value, hint, muted = false }: FieldProps) {
  return <div className="field"><div className="label">{label}</div><div className={cls("value", muted && "muted")}>{value}</div>{hint ? <div className="hint">{hint}</div> : null}</div>;
}

/** A titled group of fields. */
export function FieldGroup({ title, children }: { title: ReactNode; children?: ReactNode }) {
  return <div className="set-group"><h3>{title}</h3><div className="fields">{children}</div></div>;
}

export interface CheckRowProps {
  status?: "OK" | "WARN" | "FAIL";
  name: ReactNode;
  detail?: ReactNode;
}

/** One health-check result. */
export function CheckRow({ status = "OK", name, detail = "" }: CheckRowProps) {
  return (
    <div className={cls("check-row", status === "FAIL" ? "err" : status === "WARN" ? "warn" : "")}>
      <span className="st">{status === "OK" ? "OK" : status === "WARN" ? "Warn" : "Fail"}</span>
      <span className="n">{name}</span>
      <span className="d">{detail}</span>
    </div>
  );
}

export interface BoardSettingsProps {
  id: string;
  /** Pills beside the name. */
  pills?: ReactNode;
  /** Buttons on the right, e.g. Edit. */
  actions?: ReactNode;
  editing?: boolean;
  children?: ReactNode;
}

/** A card per board in Settings, with its name in serif and pills beside it. */
export function BoardSettings({ id, pills, actions, editing = false, children }: BoardSettingsProps) {
  return (
    <div className={cls("board-set", editing && "editing")}>
      <div className="board-set-head"><h3>{id}</h3>{pills}<span className="spacer" />{actions || null}</div>
      {children}
    </div>
  );
}
