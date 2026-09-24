import { readFileSync, readdirSync, mkdirSync, writeFileSync, renameSync } from "node:fs";
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { textHash, validateAcceptanceBundle, type AcceptanceBundle } from "../src/contracts/acceptance-plan.ts";
const root = fileURLToPath(new URL("..", import.meta.url));
const source = resolve(process.argv[2] ?? join(root, "../../../openspec/changes/add-pi-task-keeper"));
const files: Record<string, string> = {};
for (const name of ["proposal.md", "design.md", "config-contract.md", "test-plan.md", "scope-revision.json", "scenario-test-matrix.csv", "acceptance-cases.csv", "legacy-obligation-map.csv", "legacy-matrix-map.csv"])
  files[name] = readFileSync(join(source, name), "utf8");
for (const dir of readdirSync(join(source, "specs"))) files[`specs/${dir}/spec.md`] = readFileSync(join(source, "specs", dir, "spec.md"), "utf8");
// Progress metadata is not part of the execution/test contract.
const revision = JSON.parse(files["scope-revision.json"]);
files["scope-revision.json"] = JSON.stringify({ revision: revision.revision, scenarioCount: revision.scenarioCount, variantCount: revision.variantCount, specCount: revision.specCount, acceptanceCases: revision.acceptanceCases });
const history = join(source, "history/2026-09-14-p0-p3");
const hashes = JSON.parse(readFileSync(join(history, "snapshot-manifest.json"), "utf8")).files as Record<string, string>;
const legacyFiles = Object.fromEntries(Object.keys(hashes).map(file => [file, readFileSync(join(history, file), "utf8")]));
const bundle: AcceptanceBundle = { revision: "TK-R2", files, hashes: Object.fromEntries(Object.entries(files).map(([file, text]) => [file, textHash(text)])),
  legacy: { files: legacyFiles, hashes, matrices: JSON.parse(readFileSync(join(root, "docs/testing/expanded-matrices.json"), "utf8")) } };
const plan = validateAcceptanceBundle(bundle);
const destination = join(root, "tests/plan-r2"); mkdirSync(destination, { recursive: true });
writeFileSync(join(destination, "bundle.json.next"), JSON.stringify(bundle, null, 2) + "\n"); renameSync(join(destination, "bundle.json.next"), join(destination, "bundle.json"));
console.log(JSON.stringify({ revision: plan.revision, scenarios: plan.scenarios.length, cases: plan.cases.length, planDigest: plan.digest, legacyPreserved: true }));
