import { readFileSync, readdirSync } from "node:fs";
import { resolve, join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { parseCsv, planObligations, verifyScenarioMapping } from "../src/contracts/test-plan.ts";
import { readAcceptancePlan } from "./acceptance-plan.ts";

const packageRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const root = process.argv[2] ? resolve(process.argv[2]) : join(packageRoot, "tests/plan");
const scenarios = parseCsv(readFileSync(join(root, "scenario-test-matrix.csv"), "utf8"));
const faults = parseCsv(readFileSync(join(root, "fault-traceability.csv"), "utf8"));
const specs = Object.fromEntries(readdirSync(join(root, "specs")).map((name) => {
  const path = `specs/${name}/spec.md`;
  return [path, readFileSync(join(root, path), "utf8")];
}));
verifyScenarioMapping(specs, scenarios);
const obligations = planObligations(scenarios, faults);
if (!process.argv[2]) {
  const { plan } = readAcceptancePlan(packageRoot);
  console.log(JSON.stringify({ kind: "test-plan-static-check", revision: plan.revision, scenarios: plan.scenarios.length,
    acceptanceCases: plan.cases.length, variants: plan.cases.reduce((n, c) => n + c.variants.length, 0), planDigest: plan.digest,
    legacy: { scenarios: scenarios.length, faults: faults.length, obligations: obligations.length }, runtimeTestsExecuted: 0, passed: true }));
  process.exit(0);
}
console.log(JSON.stringify({ kind: "test-plan-static-check", scenarios: scenarios.length, faults: faults.length,
  obligations: obligations.length, runtimeTestsExecuted: 0, passed: true }));
