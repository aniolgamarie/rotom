import { readFileSync, readdirSync } from "node:fs";
import { join, relative } from "node:path";
import { digest } from "../src/contracts/primitives.ts";

export function sourceLock(root: string): string {
  const files: string[] = [];
  function walk(path: string) {
    for (const entry of readdirSync(path, { withFileTypes: true })) {
      if (["node_modules", "test-results", "coverage", ".git", "docs", "README.md", "THIRD_PARTY_NOTICES.md"].includes(entry.name)) continue;
      const file = join(path, entry.name);
      if (entry.isDirectory()) walk(file); else files.push(file);
    }
  }
  walk(root);
  return digest(files.sort().map(file => [relative(root, file), digest(readFileSync(file).toString("base64"))]));
}
