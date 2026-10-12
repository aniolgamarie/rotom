// 仅核对受信声明的结构和绑定；不证明物理根、政策资格或执行授权。
import { isAbsolute, resolve } from "node:path";
import { captureOperationInput } from "./private-operation-input.ts";
import { reject } from "./managed-types.ts";

const invalid = () => reject("OPERATION_BINDING_INVALID", 4);
const tools = ["read", "write", "edit", "rename", "ls", "find", "grep"];
const sha = value => typeof value === "string" && /^[a-f0-9]{64}$/.test(value);
const absolute = value => typeof value === "string" && value.length > 0 && value.length <= 4096
  && !/[\p{Cc}\p{Cf}\p{Cs}]/u.test(value) && isAbsolute(value) && resolve(value) === value;
const closed = (value, keys) => {
  if (!value || typeof value !== "object" || Array.isArray(value) || Object.getPrototypeOf(value) !== Object.prototype
      || Object.keys(value).length !== keys.length || keys.some(key => !Object.hasOwn(value, key))) invalid();
};
const bounded = value => { if (!Array.isArray(value) || value.length > 4096) invalid(); };
const covers = (root, target) => root === "/" || target === root || target.startsWith(root + "/");
function roots(value) {
  bounded(value);
  const paths = new Set();
  for (const root of value) {
    closed(root, ["path", "identity"]);
    if (!absolute(root.path) || !sha(root.identity) || paths.has(root.path)) invalid();
    paths.add(root.path);
  }
}

export function validateOfficialFileResolution(resolved, options) {
  try {
    // 捕获在任何用户属性读取之前拒绝Proxy/accessor，并保留独立有界副本。
    const r = captureOperationInput(resolved).value;
    const o = captureOperationInput(options).value;
    closed(o, ["toolName", "policyGeneration", "policyDigest"]);
    if (!tools.includes(o.toolName) || !Number.isSafeInteger(o.policyGeneration) || o.policyGeneration < 1 || !sha(o.policyDigest)) invalid();
    closed(r, ["kind", "tool_name", "target", "read_roots", "write_roots", "workspace_keys", "network", "services", "backend", "policy"]);
    if (r.kind !== "file" || r.tool_name !== o.toolName || r.backend !== "guarded-files-v1" || r.network !== "deny") invalid();
    bounded(r.services); if (r.services.length !== 0) invalid();
    const keys = ["generation", "policy_digest", "ceiling_digest", "hard_policy", "requires_human"];
    const hasApproval = r.policy && Object.hasOwn(r.policy, "approval");
    closed(r.policy, hasApproval ? [...keys, "approval"] : keys);
    const p = r.policy, approval = hasApproval ? p.approval : "human";
    if (!["human", "reviewer", "deterministic-policy"].includes(approval)
        || p.generation !== o.policyGeneration || p.policy_digest !== o.policyDigest || !sha(p.ceiling_digest)
        || p.hard_policy !== "allow" || p.requires_human !== (approval === "human")) invalid();
    closed(r.target, ["path", "destination"]);
    if (!absolute(r.target.path) || (o.toolName === "rename" ? !absolute(r.target.destination) : r.target.destination !== null)) invalid();
    roots(r.read_roots); roots(r.write_roots); bounded(r.workspace_keys);
    if (!r.workspace_keys.every(sha) || new Set(r.workspace_keys).size !== r.workspace_keys.length) invalid();
    const write = ["write", "edit", "rename"].includes(o.toolName);
    if (write ? r.write_roots.length === 0 || r.workspace_keys.length === 0
      : r.write_roots.length !== 0 || r.workspace_keys.length !== 0 || r.read_roots.length === 0) invalid();
    const selected = write ? r.write_roots : r.read_roots;
    for (const target of o.toolName === "rename" ? [r.target.path, r.target.destination] : [r.target.path]) {
      if (!selected.some(root => covers(root.path, target))) invalid();
    }
    if (o.toolName === "edit" && !r.read_roots.some(root => covers(root.path, r.target.path))) invalid();
    return approval;
  } catch { invalid(); }
}
