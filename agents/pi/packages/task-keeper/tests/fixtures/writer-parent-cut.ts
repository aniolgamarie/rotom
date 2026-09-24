import { cpSync, readFileSync, writeFileSync, symlinkSync } from "node:fs";
import { join, relative } from "node:path";
/** Negative control: emulate a parent that issues a writer grant despite a zero policy. */
export function writerParentCut(source: string, root: string) {
  const copy = join(root, "writer-parent-runtime");
  cpSync(source, copy, { recursive: true, filter: path => !relative(source, path).split("/").some(part => ["node_modules", "test-results", "coverage", ".git"].includes(part)) });
  symlinkSync(join(source, "node_modules"), join(copy, "node_modules"));
  const path = join(copy, "src/adapters/subagents.ts"), text = readFileSync(path, "utf8");
  const target = 'if (input.role === "worker") assertWriterAllowed(this.config.limits.writersPerJob);';
  if (text.split(target).length !== 2) throw new Error("writer parent fault boundary changed");
  writeFileSync(path, text.replace(target, "/* test-only: bypass parent writer admission */"));
  writeFileSync(join(root, "writer-fault-manifest.json"), JSON.stringify({ file: "src/adapters/subagents.ts", removed: target, childGuard: "unchanged" }));
  return copy;
}
