// The components only set class names; their look is the dashboard's own app.css.
import { copyFileSync, mkdirSync } from "node:fs";

mkdirSync(new URL("../dist/", import.meta.url), { recursive: true });
copyFileSync(new URL("../../../backend/arbiter/dashboard/app.css", import.meta.url), new URL("../dist/style.css", import.meta.url));
