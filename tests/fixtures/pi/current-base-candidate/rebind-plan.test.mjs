import { test } from "node:test";
import assert from "node:assert/strict";
import { validatePlan } from "./initializer_rebind.mjs";
const plan = () => ({ lock_identity: "a".repeat(64), slice_identity: "b".repeat(64), runtime_identity: "c".repeat(64),
  package_path: "pi-base-" + "d".repeat(64) + "/package.json", runtime_files: Array.from({ length: 120 }, (_, i) => ({ path: "runtime/" + i + ".mjs", digest: "e".repeat(64) })) });
test("inert candidate rebind plan fixes all generated identities and runtime rows", () => { assert.deepEqual(validatePlan(plan()), plan()); });
test("unknown identity fields and escaping runtime paths are rejected without SDK import", () => {
  const bad = plan(); bad.extra = true; assert.throws(() => validatePlan(bad));
  const path = plan(); path.runtime_files[0].path = "../private"; assert.throws(() => validatePlan(path));
});
