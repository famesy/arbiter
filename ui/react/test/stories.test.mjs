// Every component needs its own stories file: Claude Design builds each component's
// preview card from its stories.
import { test } from "node:test";
import assert from "node:assert/strict";
import { existsSync } from "node:fs";

const react = await import("../dist/index.js");

test("every component has a stories file", () => {
  const missing = Object.keys(react).filter((k) => typeof react[k] === "function" && !existsSync(new URL(`../stories/${k}.stories.tsx`, import.meta.url)));
  assert.deepEqual(missing, []);
});
