# arbiter UI components

The pieces the dashboard is built from, with a Storybook that shows each one and its
variants. This is also what `/design-sync` uploads to Claude Design.

The components themselves live in
[`backend/arbiter/dashboard/components/`](../backend/arbiter/dashboard/components/), next to
`app.css`. They are plain ES modules that build DOM elements, so arbiterd serves them as
they are at `/static/components/` and the dashboard imports them with no build step.
Installing or running arbiter never needs Node. This folder holds only the workbench.

```sh
cd ui
npm ci
npm run storybook        # http://localhost:6006
npm run build-storybook  # static build in storybook-static/
npm test                 # every component import must be a file the dashboard ships
```

Styles come from the dashboard's own `app.css` (tokens on `:root`), so a story looks
exactly like the dashboard. Pastel panels, thick ink outlines and serif headings; yellow
and red only for warnings and errors; light only.

A component is a function that takes one props object and returns an element:

```js
import { h, cls } from "./dom.js";

export function Pill({ text, tone = "" } = {}) {
  return h("span", { class: cls("pill", tone) }, h("span", { class: "dot" }), text);
}
```

Add it to `components/index.js`, and add `ui/stories/<Name>.stories.js` with one story
per variant.

## What's there

| File | Components |
| --- | --- |
| `brand.js` | Logo, Brand |
| `controls.js` | Button, ButtonRow, Menu, CheckMenu, Tabs, NavTabs, Switch, ToggleRow, Check |
| `status.js` | Pill, ConnPill, Tag, Alert, Issue, Toast, Empty |
| `board.js` | BoardCard, ProbeChip, AgentRow, HolderRow, Chip, ChipStrip, BoardActions, BoardBar, KV |
| `terminal.js` | Terminal, TermLine, BootBlock, Suggestions, CommandBar, TermCard |
| `panels.js` | Sheet, QueueRow, QueueTable, Stat, StatStrip, Sparkline, PowerPanel, TestRunRow, TestRunsTable, EventRow |
| `guide.js` | Guide, GuideContent, GuideList, GuideRow, Tally, CmdBox, TourItem |
| `settings.js` | Section, Field, FieldGroup, CheckRow, BoardSettings |

`Pages/Dashboard` puts them together as the terminal-first dashboard. The `Docs` pages at the
top of the sidebar explain the colors, type and spacing, and how to use and add components.
