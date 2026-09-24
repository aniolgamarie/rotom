import { readFileSync, realpathSync, existsSync, statSync } from "node:fs";
import { join, basename, dirname, resolve, isAbsolute, sep, relative } from "node:path";
import { validateAcceptanceBundle, textHash, type AcceptanceBundle, type AcceptanceExecution, type AcceptanceEvidence, type AcceptancePlan } from "../src/contracts/acceptance-plan.ts";
import { ContractError } from "../src/contracts/primitives.ts";

export function readAcceptancePlan(root: string) {
  const bundle = JSON.parse(readFileSync(join(root, "tests/plan-r2/bundle.json"), "utf8")) as AcceptanceBundle;
  return { bundle, plan: validateAcceptanceBundle(bundle) };
}
export function recordedAcceptance(plan: AcceptancePlan, executions: AcceptanceExecution[], root: string, runDirectory: string, sourceDigest: string): AcceptanceEvidence[] {
  const records: AcceptanceEvidence[] = [];
  for (const execution of executions) for (const [key, assertions] of Object.entries(execution.matrixAssertions ?? {})) {
    if (!key.startsWith("r2-acceptance:")) continue;
    const variant = key.slice("r2-acceptance:".length), split = variant.indexOf("."), caseId = variant.slice(0, split), variantId = variant.slice(split + 1);
    const witness = execution.acceptanceWitnesses?.[key];
    if (!witness || !witness.artifact || !witness.observer || !witness.predicate) throw new ContractError("ACCEPTANCE_WITNESS_REQUIRED", key);
    const artifact = resolve(runDirectory, witness.artifact);
    const rel = relative(realpathSync(runDirectory), existsSync(artifact) ? realpathSync(artifact) : artifact);
    if (isAbsolute(witness.artifact) || rel === ".." || rel.startsWith(`..${sep}`) || !existsSync(artifact) || !statSync(artifact).isFile() || statSync(artifact).size === 0)
      throw new ContractError("INVALID_ACCEPTANCE_ARTIFACT", key);
    const file = `tests/${basename(execution.file)}`;
    if (basename(dirname(execution.file)) !== "tests" || !existsSync(join(root, file))) throw new ContractError("INVALID_ACCEPTANCE_TEST_FILE");
    records.push({ ...witness, caseId, variant: variantId, assertions, status: execution.status, file, name: execution.name,
      sourceDigest, planDigest: plan.digest, artifactDigest: textHash(readFileSync(artifact, "utf8")) });
  }
  return records;
}
