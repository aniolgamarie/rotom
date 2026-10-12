import assert from "node:assert/strict";
import { test } from "node:test";
import fs from "node:fs";
import { validateLaunchPlan } from "../../../../scripts/pi-probe-base-launch-sdk.mjs";
test("launch plan is closed and cannot expand native scenarios", () => {
 const plan = JSON.parse(fs.readFileSync(new URL("./plan.json", import.meta.url)));
 assert.equal(validateLaunchPlan(plan), plan);
 assert.throws(() => validateLaunchPlan({ ...plan, argv: ["arbitrary"] }));
 assert.throws(() => validateLaunchPlan({ ...plan, cases: [...plan.cases, "extra"] }));
});

test("original launch help does not inspect SDK, initialize or Supervisor", async () => {
 const { launch } = await import("../../../../agents/pi/runtime/official-launch.ts");
 let accessed = 0;
 const bomb = new Proxy({}, { get() { accessed++; throw Error("unexpected access"); } });
 assert.equal((await launch({ sdk: bomb, supervisor: bomb, argv: ["--help"] })).code, 0);
 assert.equal(accessed, 0);
});
