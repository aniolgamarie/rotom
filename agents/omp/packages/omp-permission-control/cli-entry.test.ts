import { expect, test } from "bun:test";
import { mkdtempSync, writeFileSync, chmodSync, rmSync, renameSync, symlinkSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { resolveManagedCliEntry } from "./cli-entry";

test("managed compiled entry binds current regular executable identity without running it", () => {
  const root = mkdtempSync(join(tmpdir(), "omp-cli-entry-"));
  try {
    const path = join(root, "omp"); writeFileSync(path, "synthetic never executed\n"); chmodSync(path, 0o700);
    const input = { compiled: true, managedLocal: true, execPath: path };
    const entry = resolveManagedCliEntry(input);
    expect(entry.argv).toEqual([path]); expect(entry.identity.path).toBe(path);
    for (const key of ["dev", "ino", "mode", "size", "mtimeMs", "ctimeMs"])
      expect(typeof entry.identity[key as keyof typeof entry.identity]).toBe("number");
    writeFileSync(path, "changed synthetic payload\n");
    expect(resolveManagedCliEntry(input).identity).not.toEqual(entry.identity);
    renameSync(path, join(root, "old")); writeFileSync(path, "new inode\n"); chmodSync(path, 0o700);
    expect(resolveManagedCliEntry(input).identity.ino).not.toBe(entry.identity.ino);
    chmodSync(path, 0o600); expect(() => resolveManagedCliEntry(input)).toThrow();
  } finally { rmSync(root, { recursive: true, force: true }); }
});
test("source/SDK, missing, relative or linked entries have no fallback", () => {
  const root = mkdtempSync(join(tmpdir(), "omp-cli-entry-"));
  try {
    const path = join(root, "omp"); writeFileSync(path, "never executed"); chmodSync(path, 0o700);
    const base = { compiled: true, managedLocal: true, execPath: path };
    for (const override of [{ compiled: false }, { managedLocal: false }, { execPath: "omp" },
      { execPath: join(root, "missing") }, { execPath: root }])
      expect(() => resolveManagedCliEntry({ ...base, ...override })).toThrow();
    const link = join(root, "link"); symlinkSync(path, link);
    expect(() => resolveManagedCliEntry({ ...base, execPath: link })).toThrow();
  } finally { rmSync(root, { recursive: true, force: true }); }
});
