# /design-sync notes for arbiter

What a sync needs to know about this repo. Config is in `config.json` next to this file.

- The design system is `ui/react` (`@arbiter/ui-react`): React twins of the plain DOM
  components in `backend/arbiter/dashboard/components/`. `ui/.storybook` is the plain
  components' Storybook and is not the one to sync. Use `ui/react/.storybook`.
- Build before syncing: `cd ui/react && npm ci && npm run build`. Then pass
  `--node-modules ui/react/node_modules --entry ui/react/dist/index.js`, and build the
  reference with `npx storybook build -c .storybook -o <repo>/.design-sync/sb-reference`
  from `ui/react`.
- Styles: `dist/style.css` is the dashboard's `app.css`, copied by the build. Components
  only set class names, so there is no theme provider and no decorators.
- [GENERAL] `[FONT_MISSING]` for Iowan Old Style, Palatino, Charter and Cascadia Mono is
  expected. The dashboard uses system font stacks on purpose and ships no font files;
  substitutes are the intended look.
- `[RENDER_THIN]` on Logo is a false positive: the mark is an SVG with no text. It renders.
- The plain `KV` component was renamed `KeyValues`, because the converter treats all-caps
  names as constants and dropped it.
- `cardMode: "column"` is set for the wide components (bars, tables, sheets, the terminal)
  so their cards don't crop.

## Re-sync risks

- A first build and validate ran in a cloud session on 2026-10-09: 55/55 previews
  rendered, validate exited 0. No compare grading or upload has been done yet; the first
  real sync must grade every component against `sb-reference`.
- `test/parity.test.mjs` in `ui/react` is what keeps the React components faithful to the
  dashboard. If it's ever skipped, previews can drift from the real UI unnoticed.
