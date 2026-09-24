import { readFileSync, readdirSync, existsSync } from "node:fs";
import { join, relative } from "node:path";
import { fileURLToPath } from "node:url";
import { createHash } from "node:crypto";
import { ContractError } from "../contracts/primitives.ts";

const root = fileURLToPath(new URL("../..", import.meta.url));
function sourceDigest(): string {
  const files = ["index.ts", "package.json", "config.schema.json"].map(file => join(root, file));
  const visit = (directory: string) => {
    for (const entry of readdirSync(directory, { withFileTypes: true })) {
      const path = join(directory, entry.name);
      if (entry.isDirectory()) visit(path);
      else if (entry.isFile()) files.push(path);
      else throw new ContractError("TASK_KEEPER_SOURCE_NOT_REGULAR");
    }
  };
  visit(join(root, "src")); if (existsSync(join(root, "agents"))) visit(join(root, "agents"));
  const hash = createHash("sha256");
  for (const file of files.sort()) hash.update(relative(root, file)).update("\0").update(readFileSync(file)).update("\0");
  return hash.digest("hex");
}
const loadedSource = sourceDigest();
/** Hot edits cannot claim to be the code already loaded by a parent or child. */
export function taskKeeperRuntimeIdentity(): string {
  if (sourceDigest() !== loadedSource) throw new ContractError("TASK_KEEPER_RUNTIME_CHANGED_RELOAD_REQUIRED");
  return loadedSource;
}
