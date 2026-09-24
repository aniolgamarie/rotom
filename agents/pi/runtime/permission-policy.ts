// 唯一规则语言的权限决策层。实际 IO 仍须使用监督者核验过的目录句柄。
import { lstatSync, realpathSync } from "node:fs";
import { isAbsolute, join, relative, resolve, sep } from "node:path";
import { assertDescriptor, assertRule, canonical, clone, closed, digest, list, reject, sha, text } from "./managed-types.ts";

const aliases = Object.freeze({ read: "tk_read", grep: "tk_grep", find: "tk_find", ls: "tk_ls", write: "tk_write", edit: "tk_edit", rename: "tk_edit", bash: "bash", process: "process",
  tk_read: "tk_read", tk_grep: "tk_grep", tk_find: "tk_find", tk_ls: "tk_ls", tk_write: "tk_write", tk_edit: "tk_edit",
  project_check: "project_check", editor: "editor" });
const mutations = new Set(["write", "create", "delete", "rename"]);
const modes = ["ordinary", "managed", "delegate-readonly", "delegate-write"];
const toolId = value => Object.hasOwn(aliases, value) ? aliases[value] : undefined;
const inside = (root, path) => { const tail = relative(root, path); return tail !== ".." && !tail.startsWith(".." + sep) && !isAbsolute(tail); };
export function rootIdentity(path) {
  const info = lstatSync(realpathSync(path), { bigint: true });
  if (!info.isDirectory()) reject("ROOT_IDENTITY", 4);
  return digest({ device: info.dev.toString(), inode: info.ino.toString(), uid: info.uid.toString() });
}
function normalizeRules(rules, requireDeny = false) {
  if (!Array.isArray(rules)) reject("PERMISSION_UNREPRESENTABLE", 5);
  const ids = new Set();
  return rules.map(rule => {
    try { assertRule(rule); } catch { reject("PERMISSION_UNREPRESENTABLE", 5); }
    if (ids.has(rule.id) || requireDeny && rule.effect !== "deny" || rule.tool_ids.some(tool => !toolId(tool))) reject("PERMISSION_UNREPRESENTABLE", 5);
    ids.add(rule.id);
    return { ...clone(rule), tool_ids: [...new Set(rule.tool_ids.map(toolId))] };
  });
}
function operationGrant(grant, mode) {
  closed(grant, ["schema_version", "grant_id", "operation_id", "instance_id", "issuer_activation_id", "execution_mode",
    "allowed_tools", "root_bindings", "grant_generation", "issued_at", "expires_at", "grant_digest"]);
  if (grant.schema_version !== 1 || grant.execution_mode !== mode || !list(grant.allowed_tools)
      || ["grant_id", "operation_id", "instance_id", "issuer_activation_id"].some(key => !text(grant[key]))
      || !Number.isSafeInteger(grant.grant_generation) || grant.grant_generation < 1
      || !Number.isFinite(Date.parse(grant.issued_at))
      || !(grant.expires_at === null || Number.isFinite(Date.parse(grant.expires_at)))
      || grant.expires_at === null && mode !== "ordinary"
      || grant.grant_digest !== digest(Object.fromEntries(Object.entries(grant).filter(([key]) => key !== "grant_digest")))) reject("GRANT_INVALID", 4);
}
export function compilePolicy({ policy, inheritedDenials = [], roots, ceiling, grant, grantKind, mode,
    verifyGrant, workspaceLease, sourceCheckout = null, readonlyRoots = [], deniedRoots = [], secretRoots = [], commands = {}, now = () => Date.now() }) {
  closed(policy, ["schema_version", "default", "rules"]);
  closed(ceiling, ["allowed_tools", "read_roots", "write_roots"]);
  if (policy.schema_version !== 1 || policy.default !== "deny" || !modes.includes(mode)
      || !Object.values(ceiling).every(list) || typeof verifyGrant !== "function" || typeof workspaceLease !== "function") reject();
  if (mode === "managed") {
    if (grantKind !== "task") reject("GRANT_INVALID", 4);
    assertDescriptor(grant);
  } else {
    if (grantKind !== "operation") reject("GRANT_INVALID", 4);
    operationGrant(grant, mode);
  }
  const frozenGrant = clone(grant);
  const frozenCeiling = clone(ceiling);
  const rules = normalizeRules(policy.rules);
  const denials = normalizeRules(inheritedDenials, true);
  const bindings = Object.fromEntries(Object.entries(roots).map(([id, root]) => {
    closed(root, ["path", "identity"]);
    const path = realpathSync(root.path);
    if (rootIdentity(path) !== root.identity) reject("ROOT_IDENTITY", 4);
    if (mode !== "managed" && (!frozenGrant.root_bindings[id] || canonical(frozenGrant.root_bindings[id]) !== canonical(root))) reject("GRANT_INVALID", 4);
    return [id, { path, original_path: resolve(root.path), identity: root.identity }];
  }));
  if (readonlyRoots.some(id => !bindings[id]) || deniedRoots.some(id => !bindings[id])
      || [...rules, ...denials].some(rule => rule.kind === "file" && !bindings[rule.root_ref]
        || rule.kind === "command" && !commands[rule.command_ref])) reject("PERMISSION_UNREPRESENTABLE", 5);
  const source = sourceCheckout && realpathSync(sourceCheckout);
  const secrets = secretRoots.map(path => realpathSync(path));
  const commandBindings = clone(commands);
  for (const command of Object.values(commandBindings)) {
    closed(command, ["argv", "read_roots", "write_roots", "binding_digest"]);
    if (!Array.isArray(command.argv) || !command.argv.length || !command.argv.every(text)
        || !list(command.read_roots) || !list(command.write_roots)
        || [...command.read_roots, ...command.write_roots].some(id => !Object.hasOwn(bindings, id))
        || command.binding_digest !== digest({ argv: command.argv, read_roots: command.read_roots, write_roots: command.write_roots })) reject();
  }
  const metadata = Object.freeze({ policy_digest: digest(policy), parent_policy_digest: digest(denials), root_binding_digest: digest(bindings),
    alias_table_digest: digest(aliases), role_or_instance_ceiling_digest: digest(frozenCeiling), execution_mode: mode, grant_kind: grantKind,
    grant_generation: frozenGrant.grant_generation });
  function current() {
    const live = verifyGrant(clone(frozenGrant), metadata);
    const deadline = mode === "managed" ? frozenGrant.deadline : frozenGrant.expires_at;
    if (!live || live.valid !== true || live.generation !== frozenGrant.grant_generation || deadline !== null && Date.parse(deadline) <= now()) reject("GRANT_STALE", 4);
    for (const binding of Object.values(bindings)) {
      if (realpathSync(binding.original_path) !== binding.path || rootIdentity(binding.path) !== binding.identity) reject("ROOT_IDENTITY", 4);
    }
  }
  function matches(rule, tool, operation, targets, commandRef) {
    if (!rule.tool_ids.includes(tool) || !rule.operations.includes(operation)) return false;
    if (rule.kind === "command") return operation === "execute" && rule.command_ref === commandRef;
    return targets.some(target => rule.root_ref === target.root_ref && (rule.relative_path === target.relative_path
      || rule.match === "subtree" && (rule.relative_path === "." || target.relative_path.startsWith(rule.relative_path + "/"))));
  }
  function targets(path, operation) {
    if (!text(path)) reject();
    const absolute = resolve(bindings.project?.path ?? "/", path);
    const selected = [];
    for (const [id, binding] of Object.entries(bindings)) {
      const base = inside(binding.path, absolute) ? binding.path : inside(binding.original_path, absolute) ? binding.original_path : null;
      if (!base) continue;
      const tail = relative(base, absolute);
      const parts = tail ? tail.split(sep) : [];
      if (parts.includes(".git")) reject("PERMISSION_DENIED", 4);
      let cursor = binding.path;
      for (const part of parts) {
        cursor = join(cursor, part);
        try {
          if (lstatSync(cursor).isSymbolicLink()) reject("ROOT_IDENTITY", 4);
        } catch (error) {
          if (error.code !== "ENOENT" || !["write", "create", "rename"].includes(operation)) throw error;
        }
      }
      if (secrets.some(root => inside(root, cursor)) || deniedRoots.includes(id) || mutations.has(operation) && readonlyRoots.includes(id)) reject("PERMISSION_DENIED", 4);
      if (mutations.has(operation) && (mode === "delegate-readonly" || ["managed", "delegate-write"].includes(mode) && source && inside(source, cursor))) reject("PERMISSION_DENIED", 4);
      selected.push({ root_ref: id, relative_path: tail.split(sep).join("/") || ".", path: cursor });
    }
    if (!selected.length) reject("PERMISSION_DENIED", 4);
    return selected;
  }
  function authorize(action) {
    closed(action, ["tool_id", "operation"], ["path", "destination", "command_ref", "argv"]);
    current();
    const tool = toolId(action.tool_id);
    if (!tool || !frozenGrant.allowed_tools.map(toolId).includes(tool)
        || !frozenCeiling.allowed_tools.map(toolId).includes(tool)) reject("PERMISSION_DENIED", 4);
    let groups;
    if (action.operation === "execute") {
      if (Object.hasOwn(action, "path") || Object.hasOwn(action, "destination") || !text(action.command_ref)
          || !Array.isArray(action.argv) || canonical(action.argv) !== canonical(commandBindings[action.command_ref]?.argv)) reject("PERMISSION_DENIED", 4);
      const command = commandBindings[action.command_ref];
      for (const [kind, ids] of [["read_roots", command.read_roots], ["write_roots", command.write_roots]]) {
        if (ids.some(id => !frozenCeiling[kind].includes(id) || deniedRoots.includes(id)
            || mode === "managed" && !frozenGrant[kind].includes(id))) reject("PERMISSION_DENIED", 4);
      }
      if (command.write_roots.some(id => mode === "delegate-readonly" || readonlyRoots.includes(id)
          || ["managed", "delegate-write"].includes(mode) && source && (inside(source, bindings[id].path) || inside(bindings[id].path, source)))) reject("PERMISSION_DENIED", 4);
      if (command.write_roots.some(id => workspaceLease(id, metadata, clone(frozenGrant)) !== true)) reject("WORKSPACE_BUSY", 4);
      groups = [[]];
    } else {
      if (Object.hasOwn(action, "command_ref") || Object.hasOwn(action, "argv")
          || action.operation !== "rename" && Object.hasOwn(action, "destination")) reject();
      groups = [targets(action.path, action.operation)];
      if (action.operation === "rename") groups.push(targets(action.destination, action.operation));
    }
    const write = mutations.has(action.operation);
    for (const group of groups) {
      if ([...rules, ...denials].some(rule => rule.effect === "deny" && matches(rule, tool, action.operation, group, action.command_ref))) reject("PERMISSION_DENIED", 4);
      const allowedRoots = frozenCeiling[write ? "write_roots" : "read_roots"];
      const narrowed = group.filter(target => allowedRoots.includes(target.root_ref)
        && (mode !== "managed" || frozenGrant[write ? "write_roots" : "read_roots"].includes(target.root_ref)));
      if (!rules.some(rule => rule.effect === "allow" && matches(rule, tool, action.operation, narrowed, action.command_ref))) reject("PERMISSION_DENIED", 4);
      if (write && (!narrowed.length || !narrowed.some(target => workspaceLease(target.root_ref, metadata, clone(frozenGrant)) === true))) reject("WORKSPACE_BUSY", 4);
    }
    return { ...metadata, tool_id: tool, operation: action.operation, targets: groups.flat() };
  }
  return Object.freeze({ ...metadata, authorize, perform(action, operation) { const decision = authorize(action); return operation(decision); } });
}

// 父策略只接受声明过的三种形式；未知表达式不能降级成提示词或跳过。
function convertParent(snapshot, { roots, commands = {} }) {
  closed(snapshot, ["schema_version", "source_id", "source_digest", "rules"]);
  if (snapshot.schema_version !== 1 || !text(snapshot.source_id) || !sha(snapshot.source_digest) || !Array.isArray(snapshot.rules)) reject("PERMISSION_UNREPRESENTABLE", 5);
  const converted = snapshot.rules.map(input => {
    if (["file", "command"].includes(input?.kind)) {
      try { assertRule(input); } catch { reject("PERMISSION_UNREPRESENTABLE", 5); }
      if (input.tool_ids.some(name => !toolId(name))) reject("PERMISSION_UNREPRESENTABLE", 5);
      return { ...clone(input), tool_ids: [...new Set(input.tool_ids.map(toolId))] };
    }
    if (input?.kind === "absolute-file") {
      closed(input, ["id", "kind", "effect", "tool_ids", "operations", "path", "recursive"]);
      if (!text(input.path) || !isAbsolute(input.path) || /[*?\[\]{}]/.test(input.path) || typeof input.recursive !== "boolean") reject("PERMISSION_UNREPRESENTABLE", 5);
      const matches = Object.entries(roots).filter(([, root]) => inside(realpathSync(root.path), input.path));
      if (matches.length !== 1) reject("PERMISSION_UNREPRESENTABLE", 5);
      const [id, root] = matches[0];
      const result = { id: input.id, kind: "file", effect: input.effect, tool_ids: input.tool_ids,
        operations: input.operations, root_ref: id, relative_path: relative(realpathSync(root.path), input.path).split(sep).join("/") || ".", match: input.recursive ? "subtree" : "exact" };
      try { assertRule(result); } catch { reject("PERMISSION_UNREPRESENTABLE", 5); }
      if (result.tool_ids.some(name => !toolId(name))) reject("PERMISSION_UNREPRESENTABLE", 5);
      return { ...result, tool_ids: [...new Set(result.tool_ids.map(toolId))] };
    }
    if (input?.kind === "argv") {
      closed(input, ["id", "kind", "effect", "tool_ids", "executable", "args"]);
      if (!text(input.executable) || !isAbsolute(input.executable) || !Array.isArray(input.args) || !input.args.every(value => typeof value === "string" && !value.includes("\0"))) reject("PERMISSION_UNREPRESENTABLE", 5);
      const argv = [input.executable, ...input.args];
      const matches = Object.entries(commands).filter(([, binding]) => canonical(binding.argv) === canonical(argv));
      if (matches.length !== 1) reject("PERMISSION_UNREPRESENTABLE", 5);
      const result = { id: input.id, kind: "command", effect: input.effect, tool_ids: input.tool_ids, operations: ["execute"], command_ref: matches[0][0] };
      try { assertRule(result); } catch { reject("PERMISSION_UNREPRESENTABLE", 5); }
      if (result.tool_ids.some(name => !toolId(name))) reject("PERMISSION_UNREPRESENTABLE", 5);
      return { ...result, tool_ids: [...new Set(result.tool_ids.map(toolId))] };
    }
    reject("PERMISSION_UNREPRESENTABLE", 5);
  });
  if (new Set(converted.map(rule => rule.id)).size !== converted.length) reject("PERMISSION_UNREPRESENTABLE", 5);
  return { schema_version: 1, converter_version: 1, source_id: snapshot.source_id, source_digest: snapshot.source_digest,
    policy: { schema_version: 1, default: "deny", rules: converted }, conversion_digest: digest(converted) };
}

export function convertParentPolicy(snapshot, options) {
  try { return convertParent(snapshot, options); }
  catch { reject("PERMISSION_UNREPRESENTABLE", 5); }
}
