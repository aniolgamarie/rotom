import assert from "node:assert/strict";
import { test } from "node:test";
import { validateOfficialFileResolution } from "../official-file-resolution.ts";

const hash = "a".repeat(64);
const options = toolName => ({ toolName, policyGeneration: 3, policyDigest: hash });
function fixture(tool = "read", approval = "human") {
  const write = ["write", "edit", "rename"].includes(tool);
  return { kind: "file", tool_name: tool, backend: "guarded-files-v1", network: "deny", services: [],
    target: { path: "/project/file", destination: tool === "rename" ? "/project/other" : null },
    read_roots: [{ path: "/project", identity: hash }], write_roots: write ? [{ path: "/project", identity: hash }] : [],
    workspace_keys: write ? [hash] : [], policy: { generation: 3, policy_digest: hash, ceiling_digest: hash,
      hard_policy: "allow", requires_human: approval === "human", approval } };
}
function rejected(value, opts = options(value?.tool_name ?? "read")) {
  assert.throws(() => validateOfficialFileResolution(value, opts), error => {
    assert.equal(error.message, "OPERATION_BINDING_INVALID"); assert.equal(error.exitCode, 4);
    assert.equal(error.cause, undefined); assert.equal(String(error).includes("SYNTHETIC_PRIVATE"), false); return true;
  });
}
for (const tool of ["read", "write", "edit", "rename", "ls", "find", "grep"]) {
  for (const approval of ["human", "reviewer", "deterministic-policy"]) test(`${tool} accepts bound ${approval}`, () => {
    const value = fixture(tool, approval), before = structuredClone(value);
    assert.equal(validateOfficialFileResolution(value, options(tool)), approval); assert.deepEqual(value, before);
  });
}
test("only complete old human policy is compatible", () => {
  const value = fixture(); delete value.policy.approval;
  assert.equal(validateOfficialFileResolution(value, options("read")), "human");
  value.policy.requires_human = false; rejected(value);
});
const mutations = {
  kind: r => r.kind = "command", backend: r => r.backend = "native", network: r => r.network = "allow",
  service: r => r.services.push("shell"), tool: r => r.tool_name = "bash", extra: r => r.source = "human",
  deny: r => r.policy.hard_policy = "deny", generation: r => r.policy.generation++, policyHash: r => r.policy.policy_digest = "b".repeat(64),
  ceiling: r => r.policy.ceiling_digest = "bad", flag: r => r.policy.requires_human = false,
  approvalNull: r => r.policy.approval = null, approvalUnknown: r => r.policy.approval = "allow",
  policyExtra: r => r.policy.source = "reviewer", pathRelative: r => r.target.path = "project/file",
  pathDot: r => r.target.path = "/project/../project/file", pathSlash: r => r.target.path = "/project//file",
  pathControl: r => r.target.path += "\n", pathCf: r => r.target.path += "\u200d", pathSurrogate: r => r.target.path += "\ud800",
  destination: r => r.target.destination = "/project/other", targetExtra: r => r.target.body = "SYNTHETIC_PRIVATE",
  rootEscape: r => r.target.path = "/project-other/file", noRead: r => r.read_roots = [],
  rootRelative: r => r.read_roots[0].path = "project", rootHash: r => r.read_roots[0].identity = "bad",
  rootExtra: r => r.read_roots[0].grant = true, duplicateRoot: r => r.read_roots.push({ ...r.read_roots[0] }),
  readWrite: r => r.write_roots.push({ path: "/project", identity: hash }), readWorkspace: r => r.workspace_keys.push(hash),
  rootLimit: r => r.read_roots = Array.from({ length: 4097 }, (_, i) => ({ path: "/" + i, identity: hash })),
};
for (const [name, mutate] of Object.entries(mutations)) test(`rejects ${name}`, () => { const r = fixture(); mutate(r); rejected(r, options("read")); });
for (const tool of ["write", "edit", "rename"]) for (const field of ["write_roots", "workspace_keys"]) test(`${tool} needs ${field}`, () => {
  const r = fixture(tool); r[field] = []; rejected(r);
});
test("rename destination uses write roots, edit additionally uses read roots", () => {
  for (const destination of [null, "relative", "/elsewhere/file"]) { const r = fixture("rename"); r.target.destination = destination; rejected(r); }
  const edit = fixture("edit"); edit.read_roots[0].path = "/elsewhere"; rejected(edit);
  const read = fixture(); read.read_roots[0].path = "/"; assert.equal(validateOfficialFileResolution(read, options("read")), "human");
});
test("workspace keys are unique bounded hashes", () => {
  for (const keys of [[hash, hash], ["bad"], Array(4097).fill(hash)]) { const r = fixture("write"); r.workspace_keys = keys; rejected(r); }
});
for (const patch of [{ toolName: "bash" }, { policyGeneration: true }, { policyGeneration: 0 }, { policyGeneration: 1.5 },
  { policyGeneration: Number.MAX_SAFE_INTEGER + 1 }, { policyDigest: "bad" }, { source: "human" }]) test(`rejects trusted option drift ${JSON.stringify(patch)}`, () => {
  rejected(fixture(), { ...options("read"), ...patch });
});
test("proxy/accessor/symbol/hole payloads fail without executing user code", () => {
  let calls = 0;
  const proxy = new Proxy(fixture(), { get() { calls++; throw Error("SYNTHETIC_PRIVATE"); }, ownKeys() { calls++; return []; } });
  rejected(proxy, options("read"));
  const value = fixture(); Object.defineProperty(value.policy, "approval", { enumerable: true, get() { calls++; throw Error("SYNTHETIC_PRIVATE"); } }); rejected(value);
  const option = options("read"); Object.defineProperty(option, "toolName", { enumerable: true, get() { calls++; return "read"; } }); rejected(fixture(), option);
  const symbol = fixture(); symbol[Symbol("private")] = true; rejected(symbol);
  const sparse = fixture(); sparse.read_roots = Array(1); rejected(sparse);
  const inherited = Object.create(fixture()); rejected(inherited, options("read"));
  assert.equal(calls, 0);
});
test("later mutation requires new validation and cannot change an earlier primitive result", () => {
  const r = fixture("write", "reviewer"), approved = validateOfficialFileResolution(r, options("write"));
  r.policy.approval = "human"; r.policy.requires_human = true;
  assert.equal(approved, "reviewer"); assert.equal(validateOfficialFileResolution(r, options("write")), "human");
});

for (const field of ["target", "destination", "read-root", "write-root"]) test(`rejects 4097-character ${field} path`, () => {
  const r = fixture(field === "destination" ? "rename" : field === "write-root" ? "write" : "read");
  const path = "/" + "a".repeat(4096);
  if (field === "target") { r.target.path = path; r.read_roots[0].path = "/"; }
  else if (field === "destination") { r.target.destination = path; r.write_roots[0].path = "/"; }
  else if (field === "read-root") r.read_roots.push({ path, identity: hash });
  else r.write_roots.push({ path, identity: hash });
  rejected(r);
});
test("4096-character canonical target and root remain valid", () => {
  const r = fixture(), path = "/" + "a".repeat(4095);
  r.target.path = path; r.read_roots[0].path = path;
  assert.equal(validateOfficialFileResolution(r, options("read")), "human");
});
