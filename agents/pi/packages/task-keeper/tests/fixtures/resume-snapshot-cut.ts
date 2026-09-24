import { cpSync, mkdirSync, readFileSync, symlinkSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { digest } from "../../src/contracts/primitives.ts";

export function resumeSnapshotCut(source: string, root: string) {
  const copy = join(root, "snapshot-cut-package"); mkdirSync(copy);
  for (const file of ["src", "agents", "index.ts", "package.json", "config.schema.json"]) cpSync(join(source, file), join(copy, file), { recursive: true });
  symlinkSync(join(source, "node_modules"), join(copy, "node_modules"));
  const path = join(copy, "src/orchestration/service.ts"), original = readFileSync(path, "utf8");
  const needle = "const epoch = job.controlEpoch, status = job.status, specVersion = plan.spec.version;\n    const captured = await this.capture(job);";
  if (original.split(needle).length !== 2) throw new Error("Ambiguous resume capture boundary");
  const body = original.replace(needle, `${needle}
    testWrite(${JSON.stringify(join(root, "snapshot-ready.json"))}, JSON.stringify({jobId:id,pid:process.pid,epoch,snapshot:captured.snapshot.id}));
    const testUntil = Date.now() + 15000;
    while (!testExists(${JSON.stringify(join(root, "snapshot-release"))})) {
      if (Date.now() > testUntil) throw new Error("Snapshot observer did not release barrier");
      await new Promise(resolve => setTimeout(resolve, 5));
    }
    testWrite(${JSON.stringify(join(root, "snapshot-returned"))}, "actual snapshot returned to resume");
  `);
  let instrumented = 'import {writeFileSync as testWrite, existsSync as testExists} from "node:fs";\n' + body;
  if (process.env.TASK_KEEPER_SNAPSHOT_GUARD_CUT) {
    const guard = `if (job.controlEpoch !== epoch || job.status !== status || job.cancelRequested
      || this.scheduler.job(id).spec.version !== specVersion
      || configurationPolicyDigest(this.currentConfig(job.sourceCwd)) !== job.policyDigest) throw new ContractError("RESUME_CONTROL_REVOKED");`;
    if (instrumented.split(guard).length !== 2) throw new Error("Ambiguous resume control guard");
    instrumented = instrumented.replace(guard, "// Negative control: stale resume is incorrectly permitted.");
  }
  writeFileSync(path, instrumented);
  writeFileSync(join(root, "snapshot-cut-manifest.json"), JSON.stringify({ file: "src/orchestration/service.ts", needle, before: digest(original), after: digest(instrumented) }));
  return copy;
}
