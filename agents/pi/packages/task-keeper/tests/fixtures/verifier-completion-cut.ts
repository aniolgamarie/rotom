import { cpSync, symlinkSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { createHash } from "node:crypto";

export function verifierCompletionCut(source: string, root: string) {
  const copy = join(root, "verifier-cut-package"); mkdirSync(copy);
  for (const file of ["src", "agents", "index.ts", "package.json", "config.schema.json"]) cpSync(join(source, file), join(copy, file), { recursive: true });
  symlinkSync(join(source, "node_modules"), join(copy, "node_modules"));
  const path = join(copy, "src/orchestration/service.ts"), original = readFileSync(path, "utf8");
  const needle = 'const verification = await runVerification(id, this.config.verificationBindings, { jobId, snapshot: job.snapshot!, cwd: job.cwd! }, { signal, onDispatch });';
  if (original.split(needle).length !== 2) throw new Error("Verifier completion cut no longer matches its production boundary");
  const instrumented = `import { writeFileSync as cutWrite, renameSync as cutRename, existsSync as cutExists } from "node:fs";
async function holdCompletedVerifier() {
  cutWrite(${JSON.stringify(join(root, "verifier-ready.tmp"))}, "completed");
  cutRename(${JSON.stringify(join(root, "verifier-ready.tmp"))}, ${JSON.stringify(join(root, "verifier-ready"))});
  const until = Date.now() + 10000;
  while (!cutExists(${JSON.stringify(join(root, "verifier-release"))})) {
    if (Date.now() > until) throw new Error("Completion cut was not released");
    await new Promise(resolve => setTimeout(resolve, 5));
  }
}
` + original.replace(needle, needle + '\n        if (id === "focused-tests") await holdCompletedVerifier();');
  writeFileSync(path, instrumented);
  const hash = (text: string) => createHash("sha256").update(text).digest("hex");
  writeFileSync(join(root, "verifier-cut-manifest.json"), JSON.stringify({ original: hash(original), instrumented: hash(instrumented), path }));
  return copy;
}
