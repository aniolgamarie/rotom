import { cpSync, mkdirSync, readFileSync, writeFileSync, symlinkSync } from "node:fs";
import { join } from "node:path";
import { createHash } from "node:crypto";

/** Private mutation control: the transport gate must work even if host abort is ineffective. */
export function contextWithoutAbort(source: string, root: string) {
  const target = join(root, "context-gate-package"); mkdirSync(target);
  for (const path of ["src", "agents", "index.ts", "package.json", "config.schema.json"]) cpSync(join(source, path), join(target, path), { recursive: true });
  symlinkSync(join(source, "node_modules"), join(target, "node_modules"));
  const path = join(target, "index.ts"), before = readFileSync(path, "utf8"), needle = "context?.abort?.();";
  if (before.split(needle).length !== 2) throw new Error("Context abort fixture source boundary changed");
  const after = before.replace(needle, "/* private test: host abort deliberately ineffective */"); writeFileSync(path, after);
  const hash = (value: string) => createHash("sha256").update(value).digest("hex");
  writeFileSync(join(root, "context-abort-control.json"), JSON.stringify({ before: hash(before), after: hash(after), mutation: needle }), { mode: 0o600 });
  return target;
}
