import { test, assert, evidence } from "./recorded-test.ts";
import fs from "node:fs";
import { syncBuiltinESMExports } from "node:module";
import { Artifacts } from "../src/store/artifacts.ts";
import type { Store } from "../src/store/database.ts";

test("[U EVD-013 T47] artifact I/O faults cannot publish unavailable evidence or silently accept changed content", t => {
  const files = new Map<string, Buffer>(), records = new Map<string, unknown>();
  let diskFull = false, storeFailed = false;
  t.mock.method(fs, "mkdirSync", () => undefined);
  t.mock.method(fs, "lstatSync", () => ({ isFile: () => true, isSymbolicLink: () => false }));
  t.mock.method(fs, "writeFileSync", (path: string, data: Uint8Array) => {
    if (diskFull) throw Object.assign(new Error("fixture disk full"), { code: "ENOSPC" });
    files.set(String(path), Buffer.from(data));
  });
  t.mock.method(fs, "readFileSync", (path: string) => {
    const content = files.get(String(path));
    if (!content) throw Object.assign(new Error("fixture removed artifact"), { code: "ENOENT" });
    return Buffer.from(content);
  });
  syncBuiltinESMExports();
  t.after(() => { t.mock.restoreAll(); syncBuiltinESMExports(); });
  const store = { root: "/unit-artifacts", put(namespace: string, id: string, value: unknown) {
    if (storeFailed) throw Object.assign(new Error("fixture database full"), { code: "SQLITE_FULL" });
    records.set(`${namespace}:${id}`, value);
  }, get(namespace: string, id: string) { return records.get(`${namespace}:${id}`) ?? null; } } as unknown as Store;
  const artifacts = new Artifacts(store);
  diskFull = true;
  for (const id of ["EVD-013", "T47"]) evidence(id, () => {
    assert.throws(() => artifacts.pin("job", "tree", "original", "runtime"), { code: "ENOSPC" });
    assert.equal(records.size, 0); assert.equal(files.size, 0);
  });
  diskFull = false; storeFailed = true;
  for (const id of ["EVD-013", "T47"]) evidence(id, () => {
    assert.throws(() => artifacts.pin("job", "tree", "original", "runtime"), { code: "SQLITE_FULL" });
    assert.equal(records.size, 0);
  });
  storeFailed = false;
  const artifact = artifacts.pin("job", "tree", "original", "runtime"), path = `/unit-artifacts/artifacts/${artifact.id}`;
  const metadata = structuredClone(records);
  for (const content of [undefined, Buffer.from("changed!"), Buffer.from("short")]) {
    if (content) files.set(path, content); else files.delete(path);
    for (const id of ["EVD-013", "T47"]) evidence(id, () => {
      assert.throws(() => artifacts.read(artifact.id, "job", "tree"), { code: "ARTIFACT_MISSING_OR_CHANGED" });
      assert.deepEqual(records, metadata);
    });
  }
  files.set(path, Buffer.from("original"));
  for (const id of ["EVD-013", "T47"]) evidence(id, () => {
    assert.equal(artifacts.read(artifact.id, "job", "tree").content.toString(), "original");
    assert.throws(() => artifacts.read(artifact.id, "another-job", "tree"), { code: "ARTIFACT_SCOPE_MISMATCH" });
  });
});
