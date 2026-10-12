import assert from "node:assert/strict";
import { test } from "node:test";
import { mkdtempSync, mkdirSync, readFileSync, writeFileSync, readdirSync, statSync, chmodSync, symlinkSync, readSync, closeSync, openSync, fstatSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { createModelConfigSource } from "../model-config-source.ts";

const supported = process.platform === "linux", CANARY = "synthetic-private-invalid-content";
const fixture = () => mkdtempSync(join(tmpdir(), "model-source-"));
const safeFailure = fn => assert.throws(fn, error => error.message.startsWith("pi-model-config-source-") && !error.message.includes(CANARY));
const contents = '{"providers":{"fixture":{"api":"synthetic","models":[]}}}';

test("unlinked private inode supplies the same bytes to each fake SDK path read", { skip: !supported }, () => {
  const directory = fixture(), source = createModelConfigSource({ directory, contents });
  try {
    assert.equal(Object.isFrozen(source), true); assert.deepEqual(Object.keys(source).sort(), ["check", "close", "path"]);
    assert.match(source.path, /^\/proc\/self\/fd\/\d+$/);
    assert.deepEqual(readdirSync(directory), []);
    const info = statSync(source.path); assert.equal(info.nlink, 0); assert.equal(info.mode & 0o777, 0o600); assert.equal(info.uid, process.getuid());
    const fakeSDK = { load(path) { return readFileSync(path, "utf8"); } };
    assert.equal(fakeSDK.load(source.path), contents); assert.equal(fakeSDK.load(source.path), contents);
    assert.equal(source.check(), undefined); assert.equal(fakeSDK.load(source.path), contents);
  } finally { source.close(); }
});

test("named configuration replacement leaves held source and unrelated files intact", { skip: !supported }, () => {
  const directory = fixture(), native = join(directory, "models.json"); writeFileSync(native, "initial named config", { mode: 0o600 });
  const source = createModelConfigSource({ directory, contents });
  try {
    writeFileSync(native, "replacement named config"); writeFileSync(join(directory, "sentinel"), "untouched", { mode: 0o600 });
    source.check(); assert.equal(readFileSync(source.path, "utf8"), contents);
    assert.deepEqual(readdirSync(directory).sort(), ["models.json", "sentinel"]);
    assert.equal(readFileSync(native, "utf8"), "replacement named config");
  } finally { source.close(); }
  assert.equal(readFileSync(join(directory, "sentinel"), "utf8"), "untouched");
});

test("check reads at fixed positions even when caller changes the original descriptor offset", { skip: !supported }, () => {
  const source = createModelConfigSource({ directory: fixture(), contents }), fd = Number(source.path.split("/").at(-1));
  try {
    const byte = Buffer.alloc(1); assert.equal(readSync(fd, byte, 0, 1, null), 1);
    source.check(); source.check(); assert.equal(readFileSync(source.path, "utf8"), contents);
  } finally { source.close(); }
});

test("same process can reopen proc path writable; check detects corruption instead of claiming a seal", { skip: !supported }, () => {
  const source = createModelConfigSource({ directory: fixture(), contents });
  try { writeFileSync(source.path, CANARY); safeFailure(() => source.check()); }
  finally { source.close(); }
});

test("close is idempotent and closed source cannot be checked or reopened", { skip: !supported }, () => {
  const source = createModelConfigSource({ directory: fixture(), contents }); source.close(); source.close();
  safeFailure(() => source.check()); assert.throws(() => readFileSync(source.path));
});

test("close never closes an unrelated descriptor that reused the original fd", { skip: !supported }, () => {
  const directory = fixture(), source = createModelConfigSource({ directory, contents }), fd = Number(source.path.split("/").at(-1));
  const foreignPath = join(directory, "foreign"); writeFileSync(foreignPath, "foreign sentinel", { mode: 0o600 });
  closeSync(fd); const handles = [];
  try {
    // writer的低编号槽已关闭；先用自有文件填充它，明确复用原reader槽。
    for (let index = 0; index < 32 && !handles.includes(fd); index++) handles.push(openSync(foreignPath, "r"));
    assert.ok(handles.includes(fd), "own isolated fd slot should be reused"); const foreign = fd;
    safeFailure(() => source.check()); source.close(); source.close();
    assert.ok(fstatSync(foreign).isFile()); assert.equal(readFileSync(foreignPath, "utf8"), "foreign sentinel");
  } finally { handles.forEach(closeSync); }
});

for (const fault of ["relative", "noncanonical", "missing", "mode", "symlink", "file"]) test("invalid directory rejects before creating content: " + fault, { skip: !supported }, () => {
  const root = fixture(); let directory = root;
  if (fault === "relative") directory = "relative";
  if (fault === "noncanonical") directory = root + "/../" + root.split("/").at(-1);
  if (fault === "missing") directory = join(root, "missing");
  if (fault === "mode") chmodSync(root, 0o755);
  if (fault === "symlink") { directory = join(root, "link"); symlinkSync(root, directory); }
  if (fault === "file") { directory = join(root, "file"); writeFileSync(directory, "sentinel", { mode: 0o600 }); }
  const before = readdirSync(root); safeFailure(() => createModelConfigSource({ directory, contents: CANARY })); assert.deepEqual(readdirSync(root), before);
});

for (const value of ["", CANARY + "x".repeat(1024 * 1024), null, { token: CANARY }]) test("invalid or oversize contents are rejected without echo or leftover files", { skip: !supported }, () => {
  const directory = fixture(); safeFailure(() => createModelConfigSource({ directory, contents: value })); assert.deepEqual(readdirSync(directory), []);
});
