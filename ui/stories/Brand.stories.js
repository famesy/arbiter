import { Brand, ConnPill, NavTabs, Menu, Button, h } from "../index.js";

export default { title: "Foundations/Brand" };

export const Wordmark = { render: () => h("header", { style: "position:static" }, Brand()) };

export const LoginWordmark = { render: () => h("div", { id: "login", style: "margin:0" }, h("div", { class: "card" }, Brand({ as: "h1" }))) };

export const Header = {
  render: () => h("header", { style: "position:static" },
    Brand(), ConnPill({ up: true }), h("span", { class: "spacer" }),
    NavTabs({ items: [{ id: "dash", label: "Dashboard", href: "#" }, { id: "settings", label: "Settings", href: "#settings" }], active: "dash" }),
    Menu({ id: "more", label: "⋯", ariaLabel: "More", items: [Button({ label: "Pause all agents" }), Button({ label: "Getting started guide" })] })),
};

export const HeaderReconnecting = {
  render: () => h("header", { style: "position:static" },
    Brand(), ConnPill({ up: false }), h("span", { class: "spacer" }),
    NavTabs({ items: [{ id: "dash", label: "Dashboard" }, { id: "settings", label: "Settings" }], active: "settings" })),
};
