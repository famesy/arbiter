// The dashboard loads components straight from /static with no bundler, so every import
// in the component folder must be a relative path to a file that exists there.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync, existsSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const dir = fileURLToPath(new URL("../../backend/arbiter/dashboard/components/", import.meta.url));

test("component imports are relative files the dashboard ships", () => {
  for (const name of readdirSync(dir).filter((f) => f.endsWith(".js"))) {
    const src = readFileSync(join(dir, name), "utf8");
    for (const [, spec] of src.matchAll(/^\s*(?:import|export)\b[^;]*?from\s+"([^"]+)"/gm)) {
      assert.ok(spec.startsWith("./") || spec.startsWith("../"), `${name} imports ${spec}; the dashboard has no bundler`);
      assert.ok(existsSync(join(dirname(join(dir, name)), spec)), `${name} imports missing ${spec}`);
    }
  }
});
