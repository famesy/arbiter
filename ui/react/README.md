# arbiter UI components for React

React versions of the dashboard components, so Claude Design can build with them. The
dashboard itself still uses the plain ones in
[`backend/arbiter/dashboard/components/`](../../backend/arbiter/dashboard/components/) and
needs no Node.

Each React component renders the same markup and class names as its plain twin, so the
dashboard's own `app.css` styles both. The build copies it to `dist/style.css`.
`test/parity.test.mjs` renders every component both ways and fails if the HTML differs, so
change a component in both places.

```sh
cd ui/react
npm ci
npm test                 # build, then check React and plain render the same HTML
npm run storybook        # http://localhost:6007
```

```tsx
import { BoardCard } from "@arbiter/ui-react";
import "@arbiter/ui-react/style.css";

<BoardCard id="nrf9161dk-1" state="leased" status={{ text: "testing", tone: "busy" }} line="claude: lte test" />
```

Every component has a stories file in `stories/`, named after it. Claude Design builds each
component's preview card from those stories.

## Syncing to Claude Design

The settings for `/design-sync` are in [`.design-sync/`](../../.design-sync/) at the repo
root. Run `/design-sync` from the repo root in Claude Code on your own machine, after
`/design-login` once.
