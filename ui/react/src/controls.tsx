/* Buttons, menus, tabs and switches. Everything clickable is a pill with an ink outline. */
import { useRef, type ButtonHTMLAttributes, type MouseEvent, type ReactNode } from "react";
import { cls } from "./util.js";

export interface ButtonProps extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, "children"> {
  label: ReactNode;
  /** "" | "primary" (ink fill, the board's one main action) | "danger" | "link" (underlined text). */
  variant?: "" | "primary" | "danger" | "link";
  /** "" | "small" | "icon" (a square for ×, ↑, ↓). */
  size?: "" | "small" | "icon";
}

/** A pill button. Other button attributes (title, disabled, aria-label, onClick, type) pass through. */
export function Button({ label, variant = "", size = "", className, type = "button", ...attrs }: ButtonProps) {
  return <button type={type} {...attrs} className={cls(variant, size, className)}>{label}</button>;
}

export interface ButtonRowProps {
  /** Buttons; the string "sep" draws a thin divider. */
  items?: Array<ReactNode | "sep">;
  className?: string;
}

/** A row of buttons. */
export function ButtonRow({ items = [], className }: ButtonRowProps) {
  return <div className={cls("btn-row", className)}>{items.map((x, i) => (x === "sep" ? <span key={i} className="sep" /> : x))}</div>;
}

export interface MenuProps {
  label: ReactNode;
  /** The panel's contents: buttons or labels. Clicking a button closes the menu. */
  items?: ReactNode;
  open?: boolean;
  id?: string;
  ariaLabel?: string;
}

/** A pill that opens a small panel below it: the board's Actions ▾ menu, the header's ⋯ menu, the terminal's View menu. */
export function Menu({ label, items, open = false, id, ariaLabel }: MenuProps) {
  const ref = useRef<HTMLDetailsElement>(null);
  const close = (ev: MouseEvent) => {
    if ((ev.target as Element).closest("button")) setTimeout(() => { if (ref.current) ref.current.open = false; }, 0);
  };
  return (
    <details ref={ref} className="menu" id={id} open={open || undefined}>
      <summary aria-label={ariaLabel} title={ariaLabel}>{label}</summary>
      <div className="menu-body" onClick={close}>{items}</div>
    </details>
  );
}

export interface CheckOption { id: string; label: ReactNode; checked?: boolean }

export interface CheckMenuProps {
  label?: ReactNode;
  options?: CheckOption[];
  open?: boolean;
  onChange?: (id: string, checked: boolean) => void;
}

/** A menu of checkboxes, like the terminal's View options. */
export function CheckMenu({ label = "View", options = [], open = false, onChange }: CheckMenuProps) {
  return (
    <Menu label={label} open={open} items={options.map((o) => (
      <label key={o.id}>
        <input type="checkbox" data-view={o.id} defaultChecked={!!o.checked} onChange={onChange ? (ev) => onChange(o.id, ev.target.checked) : undefined} />
        {o.label}
      </label>
    ))} />
  );
}

export interface TabItem { id: string; label: ReactNode; note?: ReactNode; title?: string }

export interface TabsProps {
  items?: TabItem[];
  active?: string;
  onSelect?: (id: string) => void;
}

/** Segmented pill tabs, like the terminal's channel picker. note shows dimmed after the label ("uart:app · primary"). */
export function Tabs({ items = [], active, onSelect }: TabsProps) {
  return (
    <div className="tabs" role="tablist">
      {items.map((t) => (
        <button key={t.id} type="button" role="tab" className={t.id === active ? "on" : ""} aria-selected={t.id === active ? "true" : "false"}
          title={t.title} onClick={onSelect ? () => onSelect(t.id) : undefined}>
          {t.label}{t.note ? <span className="muted">{` · `}{t.note}</span> : null}
        </button>
      ))}
    </div>
  );
}

export interface NavItem { id: string; label: ReactNode; href?: string }

export interface NavTabsProps {
  items?: NavItem[];
  active?: string;
  id?: string;
}

/** The page switcher in the header. */
export function NavTabs({ items = [], active, id = "nav" }: NavTabsProps) {
  return (
    <nav className="tabs" id={id}>
      {items.map((t) => <a key={t.id} href={t.href || "#"} data-page={t.id} className={t.id === active ? "on" : undefined}>{t.label}</a>)}
    </nav>
  );
}

export interface SwitchProps {
  checked?: boolean;
  /** Accessible name, when there's no visible label. */
  label?: string;
  onChange?: (checked: boolean) => void;
}

/** An on/off switch (a styled checkbox). */
export function Switch({ checked = false, label, onChange }: SwitchProps) {
  return <input type="checkbox" className="switch" defaultChecked={!!checked} aria-label={label} onChange={onChange ? (ev) => onChange(ev.target.checked) : undefined} />;
}

export interface ToggleRowProps {
  label: ReactNode;
  hint?: ReactNode;
  checked?: boolean;
  onChange?: (checked: boolean) => void;
}

/** A settings row: label and hint on the left, a switch on the right. */
export function ToggleRow({ label, hint, checked = false, onChange }: ToggleRowProps) {
  return (
    <label className="toggle-row">
      <span><span className="label">{label}</span>{hint ? <span className="hint">{hint}</span> : null}</span>
      <Switch checked={checked} onChange={onChange} />
    </label>
  );
}

export interface CheckProps {
  label: ReactNode;
  checked?: boolean;
  id?: string;
  onChange?: (checked: boolean) => void;
}

/** A small checkbox with its label, like "Selected board only" over the activity feed. */
export function Check({ label, checked = false, id, onChange }: CheckProps) {
  return (
    <label className="check">
      <input type="checkbox" id={id} defaultChecked={!!checked} onChange={onChange ? (ev) => onChange(ev.target.checked) : undefined} />
      {" "}{label}
    </label>
  );
}
