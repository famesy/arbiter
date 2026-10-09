/* The board console: a dark monospace terminal with channel tabs, a View menu and a
   pill-shaped command line. The live dashboard streams lines into it; stories pass them in. */
import { h, cls, fill } from "./dom.js";
import { Button, CheckMenu, Tabs } from "./controls.js";

/** Default display options: fold boot output, hide log timestamps and shell prompts. */
export const TERM_VIEW = { fold: true, ts: false, prompt: false };

/** Apply view options ({ fold, ts, prompt }) to a Terminal element. */
export function setTermView(pre, view) {
  pre.classList.toggle("fold", !!view.fold);
  pre.classList.toggle("no-ts", !view.ts);
  pre.classList.toggle("no-prompt", !view.prompt);
}

/** The dark console itself. lines: TermLine props or elements. */
export function Terminal({ lines = [], view = TERM_VIEW, id = "term" } = {}) {
  const pre = h("pre", { id: id || null, tabindex: "0" });
  setTermView(pre, view);
  pre.append(...lines.map((l) => (l instanceof Node ? l : TermLine(l))));
  return pre;
}

/**
 * One console line. kind: "" | "d" (dim note from arbiter) | "w" (warning) | "e" (error)
 * | "h" (a line you sent) | "a" (a line an agent sent). sender: "[you]" or "[claude-1a2b]"
 * on sent lines. source, timestamp and prompt get their own spans so the View menu can
 * hide them; bare marks a line that is only a prompt.
 */
export function TermLine({ text = "", kind = "", sender, mine = false, source, timestamp, prompt, bare = false } = {}) {
  return h("div", { class: cls(kind, bare && "po") || null },
    sender ? h("span", { class: `who ${mine ? "you" : "agent"}` }, sender) : null,
    source ? h("span", { class: "src" }, source) : null,
    timestamp ? h("span", { class: "ts" }, timestamp) : null,
    prompt ? h("span", { class: "pr" }, prompt) : null,
    text || (source || timestamp || prompt ? "" : "​"));
}

/**
 * Boot output gathered into one line ("Booted Zephyr OS v4.1.0 (12 lines)") that opens on
 * click. level: "" | "w" | "e" when the boot printed warnings or errors.
 */
export function BootBlock({ summary, lines = [], level = "", open = false } = {}) {
  const sum = h("div", { class: cls("sum", level) }, summary);
  const blk = h("div", { class: cls("boot", open && "open") }, sum, h("div", { class: "body" }, lines.map((l) => (l instanceof Node ? l : TermLine(l)))));
  blk.dataset.n = String(lines.length);
  sum.addEventListener("click", () => blk.classList.toggle("open"));
  return blk;
}

/** The shell-command autocomplete list. options: [{ name, help, more }]; active is the highlighted index. */
export function Suggestions({ options = [], active = -1, onPick, footer = "Tab or ↑↓ to pick · Enter to send · Esc to close" } = {}) {
  const box = h("div", { class: "suggest", role: "listbox", hidden: options.length ? null : true });
  fill(box, options.map((c, i) => h("div", {
    class: cls("opt", i === active && "on"),
    onmousedown: onPick ? (ev) => { ev.preventDefault(); onPick(i); } : null,
  }, h("span", { class: "n" }, c.name, c.more ? " …" : ""), h("span", { class: "d" }, (c.help || "").split("\n")[0]))),
  options.length && footer ? h("div", { class: "foot" }, footer) : null);
  return box;
}

/**
 * The pill-shaped command line under the terminal. Pass your own input and send
 * elements to wire behaviour, or leave them out for a plain one. suggest is the
 * Suggestions list that pops up above it.
 */
export function CommandBar({ input, send, suggest, placeholder = "Type a command, Enter to send", disabled = false, onSubmit } = {}) {
  const field = input || h("input", { placeholder, autocomplete: "off", spellcheck: "false", disabled: disabled || null });
  const button = send || Button({ label: "Send", variant: "primary", type: "submit", disabled: disabled || null });
  return h("form", { class: "term-input", onsubmit: (ev) => { ev.preventDefault(); if (onSubmit) onSubmit(field.value); } },
    suggest || Suggestions(), field, button);
}

/**
 * The terminal card: channel tabs and View menu on top, the terminal, the command line,
 * and a hint line under it. channels: Tabs items. view: { fold, ts, prompt }.
 */
export function TermCard({ channels = [{ id: "all", label: "All" }], channel = "all", view = TERM_VIEW, lines = [], terminal, bar, help, hint, onChannel, onView } = {}) {
  return h("div", { class: "card term-card" },
    h("div", { class: "term-bar" },
      Tabs({ items: channels, active: channel, onSelect: onChannel }),
      CheckMenu({ label: "View", options: [
        { id: "fold", label: "Fold boot output", checked: view.fold },
        { id: "ts", label: "Show log timestamps", checked: view.ts },
        { id: "prompt", label: "Show shell prompts", checked: view.prompt },
      ], onChange: onView })),
    terminal || Terminal({ lines, view }),
    bar || CommandBar(),
    h("div", { class: "hint mono help" }, help || ""),
    h("div", { class: "hint" }, hint || ""));
}
