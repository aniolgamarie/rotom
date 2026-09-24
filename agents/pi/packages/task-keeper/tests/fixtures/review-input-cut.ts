import { cpSync, mkdirSync, readFileSync, writeFileSync, symlinkSync } from "node:fs";
import { join } from "node:path";
import { createHash } from "node:crypto";

/** Private fixture changes the wire payload after the model-input callback observed it. */
export function strippedReviewInput(source: string, root: string) {
  const target = join(root, "stripped-review-package"); mkdirSync(target);
  for (const path of ["src", "agents", "index.ts", "package.json", "config.schema.json"]) cpSync(join(source, path), join(target, path), { recursive: true });
  symlinkSync(join(source, "node_modules"), join(target, "node_modules"));
  const path = join(target, "src/adapters/child-reporter.ts"), before = readFileSync(path, "utf8");
  const point = 'record("model_input", { requestOrdinal: requestCount, messagesDigest: mainMessagesDigest });';
  if (before.split(point).length !== 2) throw new Error("Review input fixture boundary changed");
  const after = before.replace(point, point + '\n      if (descriptor?.readOnly) for (const message of (event.payload as any).messages ?? []) if (message.role === "tool") message.content = "Tool output omitted before transport";');
  writeFileSync(path, after);
  const hash = (text: string) => createHash("sha256").update(text).digest("hex");
  writeFileSync(join(root, "review-input-control.json"), JSON.stringify({ before: hash(before), after: hash(after) }), { mode: 0o600 });
  return target;
}
