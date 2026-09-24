import { readFileSync, realpathSync, statSync } from "node:fs";
import { dirname, isAbsolute, relative, resolve, sep } from "node:path";
import { recoveryAcceptance, type RecoveryAcceptanceInput } from "../src/evidence/recovery-acceptance.ts";
import { ContractError } from "../src/contracts/primitives.ts";

// Read-only evidence validation. No credentials, provider calls, or runtime lock writes.
const path = process.argv[2];
if (!path || process.argv.length !== 3) throw new ContractError("RECOVERY_INPUT_REQUIRED");
const input = JSON.parse(readFileSync(path, "utf8")) as RecoveryAcceptanceInput;
const report = recoveryAcceptance(input);
const root = realpathSync(dirname(resolve(path)));
for (const row of [...input.observations, ...input.effects, ...(input.terminal ? [input.terminal] : [])]) {
  const artifact = realpathSync(resolve(root, row.artifact)), local = relative(root, artifact);
  if (isAbsolute(row.artifact) || local === ".." || local.startsWith(`..${sep}`)
    || !statSync(artifact).isFile() || statSync(artifact).size === 0) throw new ContractError("INVALID_RECOVERY_ARTIFACT");
}
console.log(JSON.stringify(report, null, 2));
process.exitCode = report.recoveryQualified ? 0 : 1;
