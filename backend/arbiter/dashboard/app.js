/* arbiter dashboard. No build step and no dependencies: it talks to arbiterd's
   HTTP API (/api/state, /api/admin/...) and two WebSockets (/api/events for state
   changes, /api/boards/{id}/console for the live terminal). */
"use strict";

// ------------------------------------------------------------------ helpers
const $ = (sel) => document.querySelector(sel);

function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "class") el.className = v;
    else if (v === true) el.setAttribute(k, "");
    else el.setAttribute(k, v);
  }
  for (const kid of kids.flat()) {
    if (kid === null || kid === undefined || kid === false) continue;
    el.append(kid instanceof Node ? kid : String(kid));
  }
  return el;
}

function fill(el, ...kids) {
  el.replaceChildren(...kids.flat().filter((k) => k !== null && k !== undefined && k !== false));
}

// Re-render only when the data changed, and never while the user is typing in it.
function renderIf(el, key, fn) {
  if (el.dataset.key === key) return;
  if (el.contains(document.activeElement) && document.activeElement.tagName === "INPUT") return;
  el.dataset.key = key;
  fill(el, fn());
}

function dur(s) {
  s = Math.max(0, Math.round(s));
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, "0")}s`;
  return `${Math.floor(s / 3600)}h ${String(Math.floor((s % 3600) / 60)).padStart(2, "0")}m`;
}

function clock(ts) {
  const d = new Date(ts * 1000);
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
}

function ua(v) {
  if (v === null || v === undefined) return "-";
  if (Math.abs(v) >= 1000) return `${(v / 1000).toFixed(2)} mA`;
  return `${v.toFixed(1)} µA`;
}

function who(s) {
  // "agent:claude: lte test" -> "claude: lte test"; "human:Fame" -> "Fame"
  return String(s || "").replace(/^(agent|human):/, "");
}

// ------------------------------------------------------------------ API
const TOKEN_KEY = "arbiter_token";
let token = null;

function initToken() {
  const url = new URL(location.href);
  const fromUrl = url.searchParams.get("token");
  if (fromUrl) {
    try { localStorage.setItem(TOKEN_KEY, fromUrl); } catch (e) { /* private mode */ }
    url.searchParams.delete("token");
    history.replaceState(null, "", url.pathname + url.search + url.hash);
    return fromUrl;
  }
  try { return localStorage.getItem(TOKEN_KEY); } catch (e) { return null; }
}

class ApiError extends Error {
  constructor(status, body) {
    super((body && body.message) || `HTTP ${status}`);
    this.status = status;
    this.code = body && body.error;
  }
}

async function api(method, path, body) {
  const res = await fetch(path, {
    method,
    headers: { authorization: `Bearer ${token}`, "content-type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  let data = null;
  try { data = await res.json(); } catch (e) { /* empty */ }
  if (!res.ok) {
    const err = data && data.error && typeof data.error === "object" ? data.error : data;
    throw new ApiError(res.status, err);
  }
  return data;
}

async function act(label, fn) {
  try {
    return await fn();
  } catch (e) {
    if (e.status === 401) return showLogin("The token was refused. arbiterd makes a new one each time it starts.");
    toast(`${label}: ${e.message}`, "err");
    return null;
  } finally {
    refreshSoon();
  }
}

function wsUrl(path) {
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  const sep = path.includes("?") ? "&" : "?";
  return `${proto}//${location.host}${path}${sep}token=${encodeURIComponent(token)}`;
}

// ------------------------------------------------------------------ state
let state = null;
let skew = 0; // daemon clock minus browser clock, seconds
let selected = null;
const feed = []; // newest last
const FEED_MAX = 400;
let lastSeq = 0;

const nowS = () => Date.now() / 1000 + skew;

async function refresh() {
  try {
    const s = await api("GET", "/api/state");
    setState(s);
  } catch (e) {
    if (e.status === 401) showLogin("The token was refused. arbiterd makes a new one each time it starts.");
  }
}

let refreshTimer = null;
function refreshSoon() {
  if (refreshTimer) return;
  refreshTimer = setTimeout(() => { refreshTimer = null; refresh(); }, 150);
}

function setState(s) {
  state = s;
  skew = s.now - Date.now() / 1000;
  if (!selected || !s.boards.some((b) => b.id === selected)) {
    selected = s.boards.length ? s.boards[0].id : null;
  }
  render();
}

// ------------------------------------------------------------------ board status
const STATUS = {
  AVAILABLE: "free",
  LEASED: "in use",
  PAUSED: "paused",
  HUMAN: "held by human",
  MAINTENANCE: "maintenance",
  OFFLINE: "offline",
  NEEDS_RECOVER: "needs attention",
};

function boardStatus(b) {
  const lease = b.lease;
  let text = STATUS[b.state] || b.state.toLowerCase();
  let level = "";
  if (b.state === "LEASED" && b.op && b.op.running) {
    text = { flash: "flashing", test: "testing", recover: "recovering", measure: "measuring" }[b.op.kind] || b.op.kind;
  }
  if (b.state === "HUMAN") text = `held by ${who(b.held_by) || "human"}`;
  if (lease && lease.state === "PAUSING") text = `pausing (finishing ${b.op ? b.op.kind : "operation"})`;
  if (lease && lease.state === "EXPIRING") { text = "agent not responding"; level = "warn"; }
  if (b.state === "OFFLINE" || b.state === "NEEDS_RECOVER") level = "err";
  if (b.supported === false) level = level || "warn";
  return { text, level };
}

function lastOp(boardId, kind) {
  const ops = (state.ops || []).filter((o) => o.board === boardId && o.kind === kind && !o.running);
  return ops.length ? ops[ops.length - 1] : null;
}

function flashResult(boardId) {
  const op = lastOp(boardId, "flash");
  if (!op) return null;
  const r = op.result || {};
  if (op.error || r.ok === false) return { text: "flash failed", level: "err", op };
  if (r.boot_confirmed === true) return { text: "boot confirmed", level: "", op };
  if (r.boot_confirmed === false) return { text: "flashed, boot not seen", level: "warn", op };
  return { text: "flashed", level: "", op };
}

function testFailed(op) {
  const r = op.result || {};
  return !!(op.error || r.ok === false || r.timed_out || (r.exit_code !== undefined && r.exit_code !== 0));
}

function consoleSource(b) {
  const c = b.console || {};
  const map = c.map;
  if (map && map.resolved && map.resolved !== "unknown") {
    const how = { config: ".config", elf: "ELF symbol", runtime: "runtime scan", manual: "set in config" }[map.method] || map.method;
    return `${map.resolved.toUpperCase()} (${how})`;
  }
  if (c.mode && c.mode !== "auto") return `${c.mode.toUpperCase()} (set in config)`;
  const prim = b.console_channels && b.console_channels.primary;
  return prim ? `${prim} (not detected yet)` : "-";
}

function queueFor(b) {
  return (state.queue || []).filter((e) => {
    const sel = e.selector || {};
    if (sel.board_id && sel.board_id !== b.id) return false;
    if (sel.platform && !(b.platform === sel.platform || b.platform.split("/")[0] === sel.platform)) return false;
    return (sel.tags || []).every((t) => (b.tags || []).includes(t));
  });
}

function leaseLeft(b) {
  const l = b.lease;
  if (!l || !l.expires_at) return null;
  if (l.state === "PAUSED" || l.state === "PAUSING") return "on hold";
  if (l.state === "EXPIRING" && l.grace_until) return `ends in ${dur(l.grace_until - nowS())}`;
  return dur(l.expires_at - nowS());
}

// ------------------------------------------------------------------ alerts
function alerts() {
  const out = [];
  for (const a of state.approvals || []) {
    const s = (state.sessions || []).find((x) => x.id === a.session);
    out.push({
      level: "warn",
      board: a.board,
      text: `${s ? s.label : a.session} asks to ${a.action.replace(/_/g, " ")} ${a.board}`,
      actions: [
        h("button", { onclick: () => act("Approve", () => api("POST", `/api/admin/approvals/${a.id}`, { approve: true })) }, "Approve"),
        h("button", { onclick: () => act("Deny", () => api("POST", `/api/admin/approvals/${a.id}`, { approve: false })) }, "Deny"),
      ],
    });
  }
  for (const b of state.boards) {
    if (b.state === "OFFLINE") out.push({ level: "err", board: b.id, text: `${b.id} is offline (probe not found)` });
    if (b.state === "NEEDS_RECOVER") out.push({ level: "err", board: b.id, text: `${b.id} needs attention${b.note ? `: ${b.note}` : ""}` });
    if (b.supported === false) out.push({ level: "warn", board: b.id, text: `${b.id}: ${b.support_note || "not supported on this host"}` });
    if (b.health && ["error", "missing"].includes(b.health)) {
      out.push({ level: b.health === "error" ? "err" : "warn", board: b.id, text: `${b.id}: ${b.health_note || `health ${b.health}`}` });
    }
    if (b.power && b.power.fault) out.push({ level: "err", board: b.id, text: `${b.id} power fault: ${b.power.fault}` });
    else if (b.power && b.power.supports.includes("switch") && !b.power.on) out.push({ level: "warn", board: b.id, text: `${b.id} is powered off` });
    if (b.lease && b.lease.state === "EXPIRING") {
      out.push({ level: "warn", board: b.id, text: `${who(b.lease.holder)} stopped responding on ${b.id}; the lease ends in ${leaseLeft(b)}` });
    }
    const fr = flashResult(b.id);
    if (fr && fr.level) {
      const msg = (fr.op.result && fr.op.result.warning) || (fr.op.error && fr.op.error.message) || "";
      out.push({ level: fr.level, board: b.id, text: `${b.id}: ${fr.text}${msg ? `. ${msg}` : ""}` });
    }
    const t = lastOp(b.id, "test");
    if (t && testFailed(t)) out.push({ level: "err", board: b.id, text: `${b.id}: last test run ${(t.result && t.result.verdict) || "failed"}` });
  }
  return out;
}

// ------------------------------------------------------------------ rendering
function render() {
  if (!state) return;
  const leased = state.boards.filter((b) => b.state === "LEASED").length;
  fill($("#summary"), `${state.boards.length} board${state.boards.length === 1 ? "" : "s"}, ${leased} in use, ${(state.queue || []).length} waiting`);
  $("#pause-all").disabled = leased === 0;

  const al = alerts();
  renderIf($("#alerts"), JSON.stringify(al.map((a) => [a.level, a.text])), () =>
    al.map((a) => h("div", { class: `alert ${a.level}` },
      h("span", { class: "text" }, a.text),
      a.board && a.board !== selected ? h("button", { class: "small", onclick: () => select(a.board) }, "Show") : null,
      a.actions || [])));

  fill($("#boards"), state.boards.map(boardCard));
  renderProbes();
  renderSessions();
  renderDetail();
  renderFeed();
}

function boardCard(b) {
  const st = boardStatus(b);
  const fr = flashResult(b.id);
  const q = queueFor(b);
  const left = leaseLeft(b);
  const level = st.level || (fr && fr.level === "err" ? "err" : "");
  return h("div", { class: `board ${b.id === selected ? "sel" : ""} ${level}`, onclick: () => select(b.id) },
    h("div", { class: "top" },
      h("span", { class: "name" }, b.id),
      h("span", { class: `tag ${st.level} ${b.state === "AVAILABLE" ? "" : "solid"}` }, st.text)),
    h("div", { class: "muted mono", style: "font-size:12px" }, b.platform, b.serial ? ` · probe ${b.serial}` : ""),
    h("div", { class: "rows" },
      b.lease ? [h("span", { class: "k" }, "holder"), h("span", {}, who(b.lease.holder))] : null,
      left ? [h("span", { class: "k" }, "lease"), h("span", {}, left)] : null,
      [h("span", { class: "k" }, "console"), h("span", {}, consoleSource(b))],
      fr ? [h("span", { class: "k" }, "last flash"), h("span", { class: fr.level }, fr.text)] : null,
      q.length ? [h("span", { class: "k" }, "waiting"), h("span", {}, q.map((e) => e.who).join(", "))] : null,
      b.power ? [h("span", { class: "k" }, "power"), h("span", { class: b.power.on ? "" : "warn" },
        b.power.on ? `on, ${(b.power.mv / 1000).toFixed(2)} V` : "off")] : null));
}

function renderProbes() {
  const ps = state.unassigned_probes || [];
  renderIf($("#probes"), JSON.stringify(ps), () => ps.length ? h("div", { class: "board", style: "cursor:default" },
    h("div", { class: "name" }, "New probe found"),
    ps.map((p) => h("div", { class: "mono", style: "font-size:12px" }, `${p.serial} ${p.kind || ""} ${p.board || ""}`)),
    h("div", { class: "hint muted" }, "Run ", h("code", {}, "arbiter discover"), " for a config block, add it to config.toml and restart arbiterd.")) : []);
}

function renderSessions() {
  const ss = (state.sessions || []).filter((s) => !s.ended);
  const holding = {};
  for (const b of state.boards) if (b.lease) holding[b.lease.session_id] = b.id;
  const waiting = {};
  for (const e of state.queue || []) waiting[e.session] = e.wants;
  renderIf($("#sessions"), JSON.stringify([ss, holding, waiting]), () => ss.length ? h("table", {},
    h("tr", {}, h("th", {}, "agent"), h("th", {}, "kind"), h("th", {}, "doing")),
    ss.map((s) => h("tr", { class: s.alive ? "" : "warn" },
      h("td", {}, s.label, s.branch ? h("div", { class: "muted", style: "font-size:12px" }, `${s.repo || ""} ${s.branch}`) : null),
      h("td", {}, s.agent_kind),
      h("td", {}, holding[s.id] ? `holds ${holding[s.id]}` : waiting[s.id] ? `waiting for ${waiting[s.id]}` : s.alive ? "idle" : "not responding")))) :
    h("div", { class: "muted" }, "No agents connected."));
}

// ------------------------------------------------------------------ detail
let detailFor = null;
const D = {}; // detail sub-elements

function select(id) {
  selected = id;
  render();
}

function renderDetail() {
  const root = $("#detail");
  const b = state.boards.find((x) => x.id === selected);
  if (!b) { fill(root, h("div", { class: "muted" }, "No boards configured.")); detailFor = null; term.close(); return; }
  if (detailFor !== b.id) {
    detailFor = b.id;
    D.head = h("div");
    D.controls = h("div", { class: "controls" });
    D.tabs = h("div", { class: "tabs" });
    D.term = h("pre", { id: "term" });
    D.input = h("input", { placeholder: "type a command for the board, Enter to send", autocomplete: "off", spellcheck: "false" });
    D.send = h("button", {}, "Send");
    D.hint = h("div", { class: "hint muted" });
    D.queue = h("div");
    D.power = h("div");
    D.tests = h("div");
    const form = h("form", { class: "term-input", onsubmit: (ev) => { ev.preventDefault(); sendLine(); } }, D.input, D.send);
    fill(root,
      D.head, D.controls,
      h("div", { class: "panel" }, h("h2", {}, "Terminal"), D.tabs, D.term, form, D.hint),
      h("div", { class: "panel" }, h("h2", {}, "Queue"), D.queue),
      D.power,
      h("div", { class: "panel" }, h("h2", {}, "Test runs"), D.tests));
    term.open(b.id, term.channel && term.board === b.id ? term.channel : "all");
  }
  const st = boardStatus(b);
  const left = leaseLeft(b);
  fill(D.head,
    h("div", { class: "detail-head" },
      h("span", { class: "name" }, b.id),
      h("span", { class: `tag ${st.level} solid` }, st.text),
      h("span", { class: "muted" }, b.platform),
      b.serial ? h("span", { class: "muted mono" }, `probe ${b.serial}`) : null,
      b.ports && b.ports.length ? h("span", { class: "muted mono" }, b.ports.map((p) => p.device || p.port || p.name || "").filter(Boolean).join(", ")) : null),
    b.lease ? h("div", {}, "Held by ", h("b", {}, who(b.lease.holder)),
      b.lease.reason ? ` for "${b.lease.reason}"` : "",
      left ? `, lease ${left}` : "",
      b.lease.paused_by ? `. Paused by ${who(b.lease.paused_by)}${b.lease.pause_reason ? `: ${b.lease.pause_reason}` : ""}` : "",
      b.op && b.op.running ? `. Running ${b.op.kind} for ${dur(b.op.elapsed_s)}` : "") : null,
    h("div", { class: "muted" }, "Console: ", consoleSource(b)));
  renderIf(D.controls, `${b.state}|${b.lease && b.lease.state}|${!!b.op}`, () => controls(b));
  renderTabs(b);
  renderTermHint(b);
  renderQueue(b);
  renderPower(b);
  renderTests(b);
}

function controls(b) {
  const bid = b.id;
  const post = (action, body, label) => act(label, () => api("POST", `/api/admin/boards/${encodeURIComponent(bid)}/${action}`, body || {}));
  const btn = (label, fn, attrs) => h("button", { ...(attrs || {}), onclick: fn }, label);
  const out = [];
  const ls = b.lease && b.lease.state;
  if (b.state === "LEASED") {
    out.push(btn("Pause agent", () => post("pause", {}, "Pause"),
      { title: "The agent keeps its lease but can't use the board. A flash in progress finishes first." }));
    out.push(btn("Take over", () => post("take", {}, "Take over"),
      { title: "You get the board now; the agent goes back to the front of the queue" }));
    out.push(btn("Extend 15 min", () => post("extend", { minutes: 15 }, "Extend")));
    out.push(btn("Revoke lease", () => confirm(`End ${who(b.lease.holder)}'s lease on ${bid}?`) && post("revoke", {}, "Revoke"), { class: "danger" }));
  } else if (b.state === "PAUSED") {
    out.push(btn(ls === "PAUSING" ? "Resume (pausing…)" : "Resume agent", () => post("resume", {}, "Resume")));
    out.push(btn("Take over", () => post("take", {}, "Take over")));
    out.push(btn("Revoke lease", () => confirm(`End ${who(b.lease && b.lease.holder)}'s lease on ${bid}?`) && post("revoke", {}, "Revoke"), { class: "danger" }));
  } else if (b.state === "HUMAN") {
    out.push(btn("Give back", () => post("release", {}, "Give back"), { title: "Release the board to the next agent in the queue" }));
  } else if (b.state === "AVAILABLE") {
    out.push(btn("Take board", () => post("take", {}, "Take")));
  }
  const canDrive = !["LEASED", "OFFLINE"].includes(b.state);
  if (b.capabilities.includes("reset")) out.push(btn("Reset", () => post("reset", {}, "Reset"), { disabled: !canDrive, title: canDrive ? null : "Pause the agent or take over first" }));
  if (b.capabilities.includes("recover")) {
    out.push(btn("Recover (erase)", () => confirm(`Erase and recover ${bid}? This wipes its flash.`) && post("recover", {}, "Recover"),
      { class: "danger", disabled: !canDrive, title: canDrive ? null : "Pause the agent or take over first" }));
  }
  if (b.state === "MAINTENANCE") out.push(btn("End maintenance", () => post("maintenance", { on: false }, "Maintenance")));
  else if (["AVAILABLE", "OFFLINE", "NEEDS_RECOVER"].includes(b.state)) out.push(btn("Maintenance", () => post("maintenance", { on: true }, "Maintenance"), { title: "Take the board out of service" }));
  return out;
}

function renderTabs(b) {
  const names = new Set(["all", ...((b.console && b.console.sources) || []), ...Object.keys((b.console_channels && b.console_channels.ends) || {})]);
  const prim = b.console_channels && b.console_channels.primary;
  const list = [...names];
  renderIf(D.tabs, JSON.stringify([list, term.channel, prim]), () => list.map((n) => h("button", {
    class: n === term.channel ? "on" : "",
    title: n === "all" ? "every channel, tagged" : n === prim ? "primary console" : null,
    onclick: () => { term.open(b.id, n); renderTabs(b); },
  }, n === prim ? `${n} *` : n)));
}

function renderTermHint(b) {
  const agentHolds = b.state === "LEASED";
  D.input.disabled = agentHolds || b.state === "OFFLINE";
  D.send.disabled = D.input.disabled;
  fill(D.hint, agentHolds
    ? `${who(b.lease.holder)} holds this board. Pause it or take over to type commands.`
    : term.channel === "all" ? "Commands go to the primary console." : `Commands go to ${term.channel}.`);
}

async function sendLine() {
  const data = D.input.value;
  if (!data.trim() || !selected) return;
  const body = { data };
  if (term.channel !== "all") body.channel = term.channel;
  const ok = await act("Send", () => api("POST", `/api/admin/boards/${encodeURIComponent(selected)}/write`, body));
  if (ok) D.input.value = "";
  D.input.focus();
}

function renderQueue(b) {
  const q = queueFor(b);
  const all = state.queue || [];
  renderIf(D.queue, JSON.stringify(q.map((e) => [e.ticket, e.priority, e.pinned, Math.floor(e.waiting_s / 10)])), () => {
    if (!q.length) return h("div", { class: "muted" }, "Nobody is waiting.");
    const qa = (e, action, body, label) => act(label, () => api("POST", `/api/admin/queue/${e.ticket}/${action}`, body || {}));
    return h("table", {},
      h("tr", {}, h("th", {}, "#"), h("th", {}, "agent"), h("th", {}, "wants"), h("th", {}, "priority"), h("th", {}, "waiting"), h("th", {})),
      q.map((e, i) => {
        // move takes an index in the whole queue without this entry
        const others = all.filter((x) => x.ticket !== e.ticket);
        const up = i > 0 ? others.indexOf(q[i - 1]) : -1;
        const down = i < q.length - 1 ? others.indexOf(q[i + 1]) + 1 : -1;
        const prio = Object.entries({ low: 0, normal: 50, high: 80, urgent: 100 }).find(([, v]) => v === e.priority);
        return h("tr", {},
          h("td", {}, i + 1),
          h("td", {}, e.who, e.reason ? h("div", { class: "muted", style: "font-size:12px" }, e.reason) : null),
          h("td", { class: "mono" }, e.wants),
          h("td", {}, prio ? prio[0] : e.priority, e.pinned ? " · front" : ""),
          h("td", {}, dur(e.waiting_s)),
          h("td", { class: "actions" },
            h("button", { class: "small", disabled: up < 0, title: "Move up", onclick: () => qa(e, "move", { index: up }, "Move") }, "↑"), " ",
            h("button", { class: "small", disabled: down < 0, title: "Move down", onclick: () => qa(e, "move", { index: down }, "Move") }, "↓"), " ",
            h("button", { class: "small", title: "Urgent: move to the front", onclick: () => qa(e, "priority", { priority: "urgent" }, "Urgent").then(() => qa(e, "pin", { pinned: true }, "Urgent")) }, "Urgent"), " ",
            h("button", { class: "small danger", title: "Remove from the queue", onclick: () => confirm(`Remove ${e.who} from the queue?`) && qa(e, "cancel", {}, "Remove") }, "Remove")));
      }));
  });
}

let powerHist = {}; // board -> [{ts, avg, peak}]

function renderPower(b) {
  const p = b.power;
  if (!p) { fill(D.power); delete D.power.dataset.key; return; }
  renderIf(D.power, JSON.stringify([p, b.state, (powerHist[b.id] || []).length]), () => {
    const lim = p.limits || {};
    const bid = b.id;
    const pw = (action, extra, label) => act(label, () => api("POST", `/api/admin/boards/${encodeURIComponent(bid)}/power`, { action, ...(extra || {}) }));
    const canDrive = b.state !== "LEASED";
    const sw = p.supports.includes("switch");
    const mvIn = h("input", { type: "number", step: "50", min: lim.mv_min, max: lim.mv_max, value: p.mv || lim.default_mv || "" });
    const m = p.last;
    const hist = powerHist[b.id] || [];
    return h("div", { class: "panel" },
      h("h2", {}, "Power"),
      h("div", { class: "power-row" },
        h("span", { class: `big ${p.on ? "" : "warn"}` }, p.on ? "On" : "Off"),
        p.mv ? h("span", { class: "big" }, `${(p.mv / 1000).toFixed(2)} V`) : null,
        h("span", { class: "muted" }, p.kind, p.fault ? "" : ""),
        p.fault ? h("span", { class: "tag err" }, `fault: ${p.fault}`) : null),
      sw ? h("div", { class: "power-row", style: "margin-top:8px" },
        h("button", { disabled: !canDrive || p.on, onclick: () => pw("on", null, "Power on") }, "On"),
        h("button", { disabled: !canDrive || !p.on, onclick: () => confirm(`Power off ${bid}?`) && pw("off", null, "Power off") }, "Off"),
        h("button", { disabled: !canDrive, onclick: () => pw("cycle", null, "Power cycle") }, "Cycle"),
        p.supports.includes("voltage") ? [mvIn, h("span", { class: "muted" }, "mV"),
          h("button", { disabled: !canDrive, onclick: () => pw("set_voltage", { mv: Number(mvIn.value) }, "Set voltage") }, "Set"),
          h("span", { class: "muted" }, `limits ${lim.mv_min}–${lim.mv_max} mV`)] : null) : null,
      !canDrive ? h("div", { class: "hint muted" }, "An agent holds this board. Pause it or take over to change power.") : null,
      m ? h("div", { class: `stats ${m.valid === false ? "warn" : ""}` },
        h("div", {}, h("div", { class: "k" }, "average"), h("div", { class: "big" }, ua(m.avg_ua))),
        h("div", {}, h("div", { class: "k" }, "peak"), h("div", { class: "big" }, ua(m.peak_ua))),
        h("div", {}, h("div", { class: "k" }, "min"), h("div", { class: "big" }, ua(m.min_ua))),
        h("div", {}, h("div", { class: "k" }, "window"), h("div", { class: "big" }, `${(m.duration_ms / 1000).toFixed(1)} s`)),
        m.valid === false ? h("div", {}, h("b", {}, "Not valid: "), m.invalid_reason || "debugger attached") : null) :
        p.supports.includes("measure") ? h("div", { class: "hint muted" }, "No current measurement yet. Agents measure with measure_current.") : null,
      hist.length > 1 ? sparkline(hist) : null);
  });
}

function sparkline(hist) {
  const W = 320, H = 60, pad = 2;
  const max = Math.max(...hist.map((x) => x.peak || x.avg)) || 1;
  const xs = (i) => pad + (i * (W - 2 * pad)) / (hist.length - 1);
  const ys = (v) => H - pad - (v / max) * (H - 2 * pad);
  const pts = (k) => hist.map((x, i) => `${xs(i).toFixed(1)},${ys(x[k] || 0).toFixed(1)}`).join(" ");
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.setAttribute("width", W);
  svg.setAttribute("height", H);
  for (const [k, dash] of [["peak", "3 3"], ["avg", ""]]) {
    const pl = document.createElementNS(ns, "polyline");
    pl.setAttribute("points", pts(k));
    pl.setAttribute("fill", "none");
    pl.setAttribute("stroke", "currentColor");
    pl.setAttribute("stroke-width", "1.5");
    if (dash) pl.setAttribute("stroke-dasharray", dash);
    svg.append(pl);
  }
  return h("div", { style: "margin-top:8px" }, h("div", { class: "k muted", style: "font-size:12px" },
    `last ${hist.length} measurements: average solid, peak dashed, up to ${ua(max)}`), svg);
}

function renderTests(b) {
  const runs = (state.ops || []).filter((o) => o.board === b.id && o.kind === "test").reverse();
  const sessions = Object.fromEntries((state.sessions || []).map((s) => [s.id, s.label]));
  renderIf(D.tests, JSON.stringify(runs.map((o) => [o.id, o.running, Math.floor(o.elapsed_s)])), () => runs.length ? h("table", {},
    h("tr", {}, h("th", {}, "started"), h("th", {}, "agent"), h("th", {}, "result"), h("th", {}, "duration")),
    runs.map((o) => {
      const r = o.result || {};
      const failed = !o.running && testFailed(o);
      return [h("tr", { class: failed ? "err" : "" },
        h("td", {}, clock(o.started)),
        h("td", {}, sessions[o.session] || o.session),
        h("td", { class: failed ? "err" : "" }, o.running ? "running" : r.verdict || (o.error && o.error.message) || (failed ? "failed" : "passed"),
          r.timed_out ? " (timed out)" : "", r.cancelled ? " (cancelled)" : ""),
        h("td", {}, dur(r.duration_s !== undefined ? r.duration_s : o.elapsed_s))),
      (r.tail && r.tail.length) || o.log_path ? h("tr", { class: failed ? "err" : "" }, h("td", { colspan: 4 },
        h("details", {}, h("summary", { class: "muted" }, "log"),
          h("div", { class: "mono muted", style: "font-size:12px" }, o.log_path || ""),
          r.junit ? h("div", { class: "mono muted", style: "font-size:12px" }, `junit: ${r.junit}`) : null,
          r.tail ? h("pre", { class: "tail" }, r.tail.join("\n")) : null))) : null];
    })) : h("div", { class: "muted" }, "No test runs on this board yet."));
}

// ------------------------------------------------------------------ terminal
const term = {
  ws: null,
  board: null,
  channel: null,
  gen: 0,
  partial: null, // element holding the current unfinished line
  pending: "",
  dim: false,
  lines: 0,

  open(board, channel) {
    this.close();
    this.board = board;
    this.channel = channel;
    const gen = ++this.gen;
    D.term.replaceChildren();
    this.partial = null;
    this.pending = "";
    this.dim = false;
    this.lines = 0;
    const dec = new TextDecoder();
    const ws = new WebSocket(wsUrl(`/api/boards/${encodeURIComponent(board)}/console?channel=${encodeURIComponent(channel)}&scrollback=65536`));
    ws.binaryType = "arraybuffer";
    ws.onmessage = (m) => {
      if (gen !== this.gen) return;
      if (typeof m.data === "string") { // an error from the daemon
        try { toast(JSON.parse(m.data).message || m.data, "err"); } catch (e) { toast(m.data, "err"); }
        return;
      }
      this.write(dec.decode(m.data, { stream: true }));
    };
    ws.onclose = (ev) => {
      if (gen !== this.gen) return;
      this.note(ev.code === 4404 ? "[dashboard] no such console channel" : "[dashboard] console disconnected, reconnecting");
      if (ev.code !== 4404) setTimeout(() => { if (gen === this.gen) this.open(board, channel); }, 2000);
    };
    this.ws = ws;
  },

  close() {
    this.gen++;
    if (this.ws) { try { this.ws.close(); } catch (e) { /* closed */ } }
    this.ws = null;
  },

  note(text) {
    this.write(`${this.pending ? "\n" : ""}\x1b[2m${text}\x1b[0m\n`);
  },

  write(text) {
    const el = D.term;
    const stick = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
    const parts = (this.pending + text).split("\n");
    this.pending = parts.pop();
    const frag = document.createDocumentFragment();
    if (this.partial) { this.partial.remove(); this.partial = null; }
    for (const line of parts) { frag.append(this.lineEl(line)); this.lines++; }
    if (this.pending) { this.partial = this.lineEl(this.pending, true); frag.append(this.partial); }
    el.append(frag);
    while (this.lines > 5000 && el.firstChild) { el.firstChild.remove(); this.lines--; }
    if (stick) el.scrollTop = el.scrollHeight;
  },

  lineEl(raw, partial) {
    // Keep only the ANSI state we show (dim = arbiter notes); drop colours and cursor codes.
    let dim = this.dim;
    const startDim = dim;
    raw.replace(/\x1b\[([0-9;]*)m/g, (_, codes) => {
      for (const c of (codes || "0").split(";")) {
        if (c === "2") dim = true;
        else if (c === "0" || c === "22" || c === "") dim = false;
      }
      return "";
    });
    if (!partial) this.dim = dim;
    const text = raw.replace(/\x1b\[[0-9;?]*[A-Za-z]/g, "").replace(/\r/g, "");
    let cls = "";
    if (startDim || /^\x1b\[2m/.test(raw)) cls = /^\[human:/.test(text) ? "h" : "d";
    if (/<err>|\bFAIL(ED)?\b|\bASSERTION FAIL|\bFATAL\b|Kernel panic/.test(text)) cls = "e";
    else if (/<wrn>|\bWARN(ING)?\b/.test(text)) cls = "w";
    return h("div", { class: cls }, text || "​");
  },
};

// ------------------------------------------------------------------ activity feed
// lease.op duplicates op.started/op.finished; approval.requested arrives again as a notify.
const HIDE = new Set(["queue.changed", "lease.state", "lease.op", "board.presence", "daemon.started", "approval.requested"]);

function describe(ev) {
  const d = ev;
  const lease = d.lease && typeof d.lease === "object" ? d.lease : null;
  const sess = (id) => {
    const s = state && (state.sessions || []).find((x) => x.id === id);
    return s ? s.label : id;
  };
  switch (d.kind) {
    case "session.registered": return d.session && d.session.label ? [`${d.session.label} connected (${d.session.agent_kind})`] : ["an agent connected"];
    case "session.ended": return [`${sess(d.session)} disconnected`];
    case "session.lost": return [`${sess(d.session)} stopped responding`, "warn"];
    case "lease.granted": return [`${sess(lease.session_id)} got ${d.board}${lease.reason ? `: ${lease.reason}` : ""}`];
    case "lease.ended": {
      const how = d.state || (lease && lease.state);
      const msg = `${sess(lease.session_id)} ${{ RELEASED: "released", REVOKED: "lost", EXPIRED: "lost (expired)" }[how] || "ended"} ${d.board}${lease.end_reason ? ` (${lease.end_reason})` : ""}`;
      return [msg, how === "EXPIRED" ? "warn" : ""];
    }
    case "lease.op": return [`${sess(lease ? lease.session_id : "")} ${typeof d.op === "string" ? d.op : JSON.stringify(d.op)} on ${d.board}`];
    case "board.state": return [`${d.board} is now ${(STATUS[d.state] || d.state).toLowerCase()}${d.held_by ? ` by ${who(d.held_by)}` : ""}${d.note ? `: ${d.note}` : ""}`,
      ["OFFLINE", "NEEDS_RECOVER"].includes(d.state) ? "err" : ""];
    case "board.console": return [`${d.board} console detected: ${d.console && d.console.resolved}${d.console && d.console.method ? ` (${d.console.method})` : ""}`];
    case "op.started": return [`${sess(d.op.session)} started ${d.op.kind} on ${d.op.board}`];
    case "op.finished": {
      const r = d.op.result || {};
      let res = d.op.error ? `failed: ${d.op.error.message}` : r.ok === false ? "failed" : "ok";
      let level = d.op.error || r.ok === false ? "err" : "";
      if (d.op.kind === "flash" && r.boot_confirmed === false && !level) { res = "ok, boot not seen"; level = "warn"; }
      if (d.op.kind === "test" && !d.op.error) { res = r.verdict || res; if (testFailed(d.op)) level = "err"; }
      return [`${sess(d.op.session)} ${d.op.kind} on ${d.op.board}: ${res} (${dur(d.op.elapsed_s)})`, level];
    }
    case "power.changed": return [`${d.board} power ${d.power.on ? "on" : "off"}${d.power.mv ? `, ${(d.power.mv / 1000).toFixed(2)} V` : ""}`, d.power.fault ? "err" : d.power.on ? "" : "warn"];
    case "power.measured": return [`${d.board} measured avg ${ua(d.measurement.avg_ua)}, peak ${ua(d.measurement.peak_ua)}${d.measurement.valid === false ? " (not valid)" : ""}`, d.measurement.valid === false ? "warn" : ""];
    case "approval.requested": return [`${d.who ? who(d.who) : sess(d.approval.session)} asks to ${d.approval.action.replace(/_/g, " ")} ${d.approval.board}`, "warn"];
    case "approval.changed": return [`${d.approval.action.replace(/_/g, " ")} on ${d.approval.board}: ${d.approval.state}${d.approval.decided_by ? ` by ${who(d.approval.decided_by)}` : ""}`];
    case "notify": return [String(d.text).replace(/^(agent|human):/, ""), "warn"];
    default: return [`${d.kind} ${d.board || ""}`];
  }
}

function boardOf(ev) {
  return ev.board || (ev.op && ev.op.board) || (ev.approval && ev.approval.board) || (ev.lease && ev.lease.board_id) || null;
}

function addEvent(ev) {
  if (HIDE.has(ev.kind)) return;
  let text, level;
  try { [text, level] = describe(ev); } catch (e) { text = ev.kind; level = ""; }
  feed.push({ ts: ev.ts || Date.now() / 1000, text, level: level || "", board: boardOf(ev), seq: ev.seq || 0 });
  // History from the audit log and live events can arrive out of order.
  if (feed.length > 1 && feed[feed.length - 2].ts > feed[feed.length - 1].ts) feed.sort((a, b) => a.ts - b.ts);
  if (feed.length > FEED_MAX) feed.splice(0, feed.length - FEED_MAX);
  if (ev.kind === "power.measured") {
    const hst = (powerHist[ev.board] = powerHist[ev.board] || []);
    hst.push({ ts: ev.ts, avg: ev.measurement.avg_ua, peak: ev.measurement.peak_ua });
    if (hst.length > 40) hst.shift();
  }
  return { text, level };
}

function renderFeed() {
  const only = $("#feed-filter").checked;
  const items = feed.filter((f) => !only || f.board === selected).slice(-200).reverse();
  renderIf($("#feed"), `${only}|${selected}|${feed.length}|${feed.length && feed[feed.length - 1].seq}`, () => items.length ? items.map((f) =>
    h("div", { class: `ev ${f.level}` }, h("span", { class: "t" }, clock(f.ts)), h("span", {}, f.text))) : h("div", { class: "muted" }, "Nothing yet."));
}

// ------------------------------------------------------------------ events socket
let evWs = null;
let evBackoff = 1000;

function connectEvents() {
  const ws = new WebSocket(wsUrl(`/api/events?since=${lastSeq}`));
  evWs = ws;
  ws.onopen = () => { evBackoff = 1000; setConn(true); };
  ws.onmessage = (m) => {
    let ev;
    try { ev = JSON.parse(m.data); } catch (e) { return; }
    if (ev.kind === "snapshot") { setState(ev.state); return; }
    if (ev.seq && ev.seq <= lastSeq) return;
    if (ev.seq) lastSeq = ev.seq;
    const shown = addEvent(ev);
    // Replayed history does not toast; only events from the last few seconds do.
    if ((ev.kind === "notify" || ev.kind === "session.lost") && ev.ts > nowS() - 5) {
      if (shown) { toast(shown.text, shown.level); notifyOs(shown.text); }
    }
    refreshSoon();
  };
  ws.onclose = (ev) => {
    setConn(false);
    if (ev.code === 4401) { showLogin("The token was refused. arbiterd makes a new one each time it starts."); return; }
    setTimeout(connectEvents, evBackoff);
    evBackoff = Math.min(evBackoff * 2, 10000);
  };
}

function setConn(up) {
  const el = $("#conn");
  el.className = up ? "muted" : "down";
  el.textContent = up ? "live" : "disconnected from arbiterd, retrying";
}

// ------------------------------------------------------------------ notifications
function toast(text, level) {
  const t = h("div", { class: `toast ${level || ""}` }, text);
  $("#toasts").append(t);
  setTimeout(() => t.remove(), level === "err" ? 9000 : 5000);
}

function notifyOs(text) {
  if (!("Notification" in window) || !document.hidden) return;
  if (Notification.permission === "granted") new Notification("arbiter", { body: text });
}

// ------------------------------------------------------------------ login + boot
function showLogin(msg) {
  $("#app").hidden = true;
  $("#login").hidden = false;
  const e = $("#login-error");
  e.hidden = !msg;
  e.textContent = msg || "";
  if (evWs) { evWs.onclose = null; evWs.close(); evWs = null; }
  term.close();
}

async function start() {
  try {
    const s = await api("GET", "/api/state");
    // The dashboard needs the admin token; an agent token is refused here.
    // History comes from the event socket, which replays the daemon's recent events.
    await api("GET", "/api/admin/audit?limit=1");
    $("#login").hidden = true;
    $("#app").hidden = false;
    setState(s);
    connectEvents();
  } catch (e) {
    showLogin(e.status === 401 ? "That token was refused. Use the admin token (admin.json), not the agent token." : `Can't reach arbiterd: ${e.message}`);
  }
}

$("#login-form").addEventListener("submit", (ev) => {
  ev.preventDefault();
  token = $("#login-token").value.trim();
  try { localStorage.setItem(TOKEN_KEY, token); } catch (e) { /* private mode */ }
  start();
});

$("#pause-all").addEventListener("click", async () => {
  const held = state.boards.filter((b) => b.state === "LEASED");
  if (!held.length || !confirm(`Pause ${held.length} agent${held.length === 1 ? "" : "s"}? Flashes in progress finish first.`)) return;
  await Promise.all(held.map((b) => act(`Pause ${b.id}`, () => api("POST", `/api/admin/boards/${encodeURIComponent(b.id)}/pause`, { reason: "pause all" }))));
});

$("#feed-filter").addEventListener("change", renderFeed);

// Lease countdowns tick locally between state updates.
setInterval(() => { if (state && !$("#app").hidden) render(); }, 1000);
// A slow poll as a safety net in case an event is missed.
setInterval(() => { if (token && !$("#app").hidden) refresh(); }, 15000);

document.addEventListener("click", () => {
  if ("Notification" in window && Notification.permission === "default") Notification.requestPermission();
}, { once: true });

token = initToken();
if (token) start();
else showLogin("");
