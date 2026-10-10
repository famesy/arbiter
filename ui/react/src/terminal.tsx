/* The board console: a dark monospace terminal with channel tabs, a View menu and a
   pill-shaped command line. The live dashboard streams lines into it; designs pass them in. */
import { cloneElement, isValidElement, useState, type FormEvent, type ReactNode } from "react";
import { cls } from "./util.js";
import { Button, CheckMenu, Tabs, type TabItem } from "./controls.js";

export interface TermView {
  /** Fold boot output into one line. */
  fold: boolean;
  /** Show log timestamps. */
  ts: boolean;
  /** Show shell prompts. */
  prompt: boolean;
}

/** Default display options: fold boot output, hide log timestamps and shell prompts. */
export const TERM_VIEW: TermView = { fold: true, ts: false, prompt: false };

const viewClass = (view: TermView) => cls(view.fold && "fold", !view.ts && "no-ts", !view.prompt && "no-prompt");

export interface TermLineProps {
  text?: ReactNode;
  /** "" | "d" (dim note from arbiter) | "w" (warning) | "e" (error) | "h" (a line you sent) | "a" (a line an agent sent). */
  kind?: "" | "d" | "w" | "e" | "h" | "a";
  /** "[you]" or "[claude-1a2b]" on sent lines. */
  sender?: string;
  /** The sender is you. */
  mine?: boolean;
  /** Channel tag, e.g. "[uart:app] ", shown on the All tab. */
  source?: string;
  /** Log timestamp, hidden unless View shows timestamps. */
  timestamp?: string;
  /** Shell prompt, e.g. "uart:~$ ", hidden unless View shows prompts. */
  prompt?: string;
  /** The line is only a prompt. */
  bare?: boolean;
}

/** One console line. */
export function TermLine({ text = "", kind = "", sender, mine = false, source, timestamp, prompt, bare = false }: TermLineProps) {
  return (
    <div className={cls(kind, bare && "po")}>
      {sender ? <span className={`who ${mine ? "you" : "agent"}`}>{sender}</span> : null}
      {source ? <span className="src">{source}</span> : null}
      {timestamp ? <span className="ts">{timestamp}</span> : null}
      {prompt ? <span className="pr">{prompt}</span> : null}
      {text || (source || timestamp || prompt ? "" : "​")}
    </div>
  );
}

/** A console line: TermLine props, or an element such as a BootBlock. */
export type TermLineInput = TermLineProps | ReactNode;

const line = (l: TermLineInput, i: number) => (isValidElement(l) ? cloneElement(l, { key: i }) : <TermLine key={i} {...(l as TermLineProps)} />);

export interface TerminalProps {
  lines?: TermLineInput[];
  view?: TermView;
  /** The dashboard's styles target #term, so keep the default unless there are two. */
  id?: string;
}

/** The dark console itself. */
export function Terminal({ lines = [], view = TERM_VIEW, id = "term" }: TerminalProps) {
  return <pre id={id || undefined} tabIndex={0} className={viewClass(view)}>{lines.map(line)}</pre>;
}

export interface BootBlockProps {
  /** "Booted Zephyr OS v4.1.0 (12 lines)". */
  summary: ReactNode;
  lines?: TermLineInput[];
  /** "" | "w" | "e" when the boot printed warnings or errors. */
  level?: "" | "w" | "e";
  open?: boolean;
}

/** Boot output gathered into one line that opens on click. */
export function BootBlock({ summary, lines = [], level = "", open = false }: BootBlockProps) {
  const [isOpen, setOpen] = useState(open);
  return (
    <div className={cls("boot", isOpen && "open")} data-n={String(lines.length)}>
      <div className={cls("sum", level)} onClick={() => setOpen(!isOpen)}>{summary}</div>
      <div className="body">{lines.map(line)}</div>
    </div>
  );
}

export interface Suggestion { name: string; help?: string; more?: boolean }

export interface SuggestionsProps {
  options?: Suggestion[];
  /** The highlighted index. */
  active?: number;
  onPick?: (index: number) => void;
  footer?: ReactNode;
}

/** The shell-command autocomplete list that pops up over the command line. */
export function Suggestions({ options = [], active = -1, onPick, footer = "Tab or ↑↓ to pick · Enter to send · Esc to close" }: SuggestionsProps) {
  return (
    <div className="suggest" role="listbox" hidden={options.length ? undefined : true}>
      {options.map((c, i) => (
        <div key={c.name} className={cls("opt", i === active && "on")} onMouseDown={onPick ? (ev) => { ev.preventDefault(); onPick(i); } : undefined}>
          <span className="n">{c.name}{c.more ? " …" : ""}</span><span className="d">{(c.help || "").split("\n")[0]}</span>
        </div>
      ))}
      {options.length && footer ? <div className="foot">{footer}</div> : null}
    </div>
  );
}

export interface CommandBarProps {
  /** Your own input element, to wire behaviour. */
  input?: ReactNode;
  /** Your own send button. */
  send?: ReactNode;
  /** A Suggestions element. */
  suggest?: ReactNode;
  placeholder?: string;
  disabled?: boolean;
  onSubmit?: (value: string) => void;
}

/** The pill-shaped command line under the terminal. */
export function CommandBar({ input, send, suggest, placeholder = "Type a command, Enter to send", disabled = false, onSubmit }: CommandBarProps) {
  const submit = (ev: FormEvent<HTMLFormElement>) => {
    ev.preventDefault();
    const field = ev.currentTarget.querySelector("input");
    if (onSubmit && field) onSubmit(field.value);
  };
  return (
    <form className="term-input" onSubmit={submit}>
      {suggest || <Suggestions />}
      {input || <input placeholder={placeholder} autoComplete="off" spellCheck="false" disabled={disabled || undefined} />}
      {send || <Button label="Send" variant="primary" type="submit" disabled={disabled || undefined} />}
    </form>
  );
}

export interface TermCardProps {
  /** The channel tabs, e.g. All and uart:app · primary. */
  channels?: TabItem[];
  channel?: string;
  view?: TermView;
  lines?: TermLineInput[];
  /** Your own Terminal element, instead of lines. */
  terminal?: ReactNode;
  /** Your own CommandBar element. */
  bar?: ReactNode;
  /** The selected command's help, under the command line. */
  help?: ReactNode;
  /** One line under the command line, e.g. who holds the board. */
  hint?: ReactNode;
  onChannel?: (id: string) => void;
  onView?: (id: string, checked: boolean) => void;
}

/** The terminal card: channel tabs and View menu on top, the terminal, the command line, and a hint line under it. */
export function TermCard({ channels = [{ id: "all", label: "All" }], channel = "all", view = TERM_VIEW, lines = [], terminal, bar, help, hint, onChannel, onView }: TermCardProps) {
  return (
    <div className="card term-card">
      <div className="term-bar">
        <Tabs items={channels} active={channel} onSelect={onChannel} />
        <CheckMenu label="View" onChange={onView} options={[
          { id: "fold", label: "Fold boot output", checked: view.fold },
          { id: "ts", label: "Show log timestamps", checked: view.ts },
          { id: "prompt", label: "Show shell prompts", checked: view.prompt },
        ]} />
      </div>
      {terminal || <Terminal lines={lines} view={view} />}
      {bar || <CommandBar />}
      <div className="hint mono help">{help || ""}</div>
      <div className="hint">{hint || ""}</div>
    </div>
  );
}
