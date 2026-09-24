import assert from "node:assert/strict";
import { test } from "node:test";
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync, symlinkSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { compilePolicy, rootIdentity } from "../../../runtime/permission-policy.ts";
import { digest } from "../../../runtime/managed-types.ts";
import { descriptor } from "../../../runtime/tests/fixtures.ts";

function fixture(mode = "ordinary") {
  const root = mkdtempSync(join(tmpdir(), "policy-"));
  const source = join(root, "source"), candidate = join(root, "candidate");
  for (const path of [source, candidate]) {
    mkdirSync(path);
    for (const name of ["src", "src2", ".git"]) mkdirSync(join(path, name));
    writeFileSync(join(path, "src/file"), "before");
    writeFileSync(join(path, ".env"), "synthetic private config");
  }
  const project = mode === "managed" ? candidate : source;
  const roots = { project: { path: project, identity: rootIdentity(project) } };
  const tools = ["tk_read", "tk_write", "project_check"];
  const ceiling = { allowed_tools: tools, read_roots: ["project"], write_roots: ["project"] };
  const grant = mode === "managed" ? { ...descriptor(), allowed_tools: tools, read_roots: ["project"], write_roots: ["project"], workspace_write_lease_ids: ["writer-lease"] }
    : { schema_version: 1, grant_id: "operation-grant", operation_id: "ordinary-operation", instance_id: "instance", issuer_activation_id: "supervisor",
      execution_mode: mode, allowed_tools: tools, root_bindings: roots, grant_generation: 1,
      issued_at: "2026-09-16T00:00:00Z", expires_at: mode === "ordinary" ? null : "2026-09-16T01:00:00Z" };
  if (mode !== "managed") grant.grant_digest = digest(grant);
  const policy = { schema_version: 1, default: "deny", rules: [{ id: "files", kind: "file", effect: "allow", tool_ids: tools.slice(0, 2),
    operations: ["read", "write", "create", "rename"], root_ref: "project", relative_path: ".", match: "subtree" }] };
  const live = { generation: 1, writeLease: true };
  const options = { policy, inheritedDenials: [], roots, ceiling, grant, mode, grantKind: mode === "managed" ? "task" : "operation",
    verifyGrant: () => ({ valid: true, generation: live.generation }), workspaceLease: () => live.writeLease,
    sourceCheckout: source, now: () => Date.parse("2026-09-16T00:01:00Z") };
  return { project, source, candidate, options, live };
}
const deny = { id: "private", kind: "file", effect: "deny", tool_ids: ["read", "write"], operations: ["read", "write", "create", "rename"],
  root_ref: "project", relative_path: ".env", match: "exact" };

test("ordinary operations can write the authorized business root without a task grant", () => {
  const f = fixture();
  const policy = compilePolicy(f.options);
  const target = join(f.project, "src/file");
  policy.perform({ tool_id: "write", operation: "write", path: target }, () => writeFileSync(target, "after"));
  assert.equal(readFileSync(target, "utf8"), "after");
  assert.equal(policy.grant_kind, "operation");
});

test("deny wins independently of order and project-relative parent denials follow candidate", () => {
  for (const reverse of [false, true]) {
    const f = fixture("managed");
    f.options.inheritedDenials = [deny];
    if (reverse) f.options.policy.rules.unshift({ ...deny, id: "also-private" });
    const policy = compilePolicy(f.options);
    assert.throws(() => policy.authorize({ tool_id: "read", operation: "read", path: join(f.candidate, ".env") }), /PERMISSION_DENIED/);
    assert.throws(() => policy.authorize({ tool_id: "write", operation: "write", path: join(f.source, "src/file") }), /PERMISSION_DENIED/);
    assert.equal(policy.authorize({ tool_id: "read", operation: "read", path: join(f.candidate, "src/file") }).tool_id, "tk_read");
  }
});

test("subtree src does not match src2; rename validates both endpoints", () => {
  const f = fixture();
  f.options.policy.rules[0].relative_path = "src";
  const policy = compilePolicy(f.options);
  assert.throws(() => policy.authorize({ tool_id: "write", operation: "create", path: join(f.project, "src2/new") }), /PERMISSION_DENIED/);
  assert.throws(() => policy.authorize({ tool_id: "write", operation: "rename", path: join(f.project, "src/file"), destination: join(f.project, "src2/file") }), /PERMISSION_DENIED/);
});

test("readonly delegation, missing writer lease and changed generation cannot be bypassed", () => {
  const readonly = fixture("delegate-readonly");
  assert.throws(() => compilePolicy(readonly.options).authorize({ tool_id: "write", operation: "write", path: join(readonly.project, "src/file") }), /PERMISSION_DENIED/);
  const f = fixture(), policy = compilePolicy(f.options);
  f.live.writeLease = false;
  assert.throws(() => policy.authorize({ tool_id: "write", operation: "write", path: join(f.project, "src/file") }), /WORKSPACE_BUSY/);
  f.live.generation = 2;
  assert.throws(() => policy.authorize({ tool_id: "read", operation: "read", path: join(f.project, "src/file") }), /GRANT_STALE/);
});

test("unknown parent rule languages, symlink escapes, .git and model-supplied mode fail closed", () => {
  const f = fixture();
  assert.throws(() => compilePolicy({ ...f.options, inheritedDenials: [{ kind: "regex", pattern: ".*" }] }), /PERMISSION_UNREPRESENTABLE/);
  const policy = compilePolicy(f.options);
  symlinkSync(f.candidate, join(f.project, "escape"));
  assert.throws(() => policy.authorize({ tool_id: "write", operation: "create", path: join(f.project, "escape/new") }), /ROOT_IDENTITY/);
  assert.throws(() => policy.authorize({ tool_id: "read", operation: "read", path: join(f.project, ".git") }), /PERMISSION_DENIED/);
  assert.throws(() => policy.authorize({ tool_id: "write", operation: "write", path: join(f.project, "src/file"), execution_mode: "ordinary" }), /PROTOCOL_INVALID/);
});

test("command ref freezes exact argv and writable checks require the shared lease", () => {
  const f = fixture();
  const command = { argv: ["/fixture/check", "--literal", "a b"], read_roots: ["project"], write_roots: ["project"] };
  command.binding_digest = digest(command);
  f.options.commands = { "check:unit": command };
  f.options.policy.rules.push({ id: "check", kind: "command", effect: "allow", tool_ids: ["project_check"], operations: ["execute"], command_ref: "check:unit" });
  const policy = compilePolicy(f.options);
  assert.throws(() => policy.authorize({ tool_id: "project_check", operation: "execute", command_ref: "check:unit", argv: ["/fixture/check", "--changed"] }), /PERMISSION_DENIED/);
  f.live.writeLease = false;
  assert.throws(() => policy.authorize({ tool_id: "project_check", operation: "execute", command_ref: "check:unit", argv: command.argv }), /WORKSPACE_BUSY/);
});

test("canonical protocol identities agree with Python's UTF-8 JSON contract", () => {
  assert.equal(digest({ z: false, a: ["测试", null, 1] }), "f93c707c4cf419d941c79de2fb605b828f6a7a9ed5f33b0dea5a3cdaac339c85");
});

test("parent absolute paths and exact argv convert without losing denials; ambiguous/glob rules refuse preflight", async () => {
  const { convertParentPolicy } = await import("../../../runtime/permission-policy.ts");
  const { mkdtempSync } = await import("node:fs");
  const { join } = await import("node:path");
  const { tmpdir } = await import("node:os");
  const root = mkdtempSync(join(tmpdir(), "parent-policy-"));
  const snapshot = { schema_version: 1, source_id: "fixture-native-policy", source_digest: "a".repeat(64), rules: [
    { id: "secret", kind: "absolute-file", effect: "deny", tool_ids: ["read"], operations: ["read"], path: join(root, ".env"), recursive: false },
    { id: "command", kind: "argv", effect: "deny", tool_ids: ["project_check"], executable: "/fixture/check", args: ["--literal", "a b"] },
  ] };
  const bindings = { roots: { project: { path: root } }, commands: { "check:unit": { argv: ["/fixture/check", "--literal", "a b"] } } };
  const converted = convertParentPolicy(snapshot, bindings);
  assert.equal(converted.policy.rules[0].root_ref, "project");
  assert.equal(converted.policy.rules[0].relative_path, ".env");
  assert.deepEqual(converted.policy.rules[0].tool_ids, ["tk_read"]);
  assert.equal(converted.policy.rules[1].command_ref, "check:unit");
  assert.throws(() => convertParentPolicy({ ...snapshot, rules: [{ ...snapshot.rules[0], path: join(root, "*.env") }] }, bindings), /PERMISSION_UNREPRESENTABLE/);
  assert.throws(() => convertParentPolicy(snapshot, { ...bindings, roots: { ...bindings.roots, alias: { path: root } } }), /PERMISSION_UNREPRESENTABLE/);
});
