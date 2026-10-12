import { createHash } from "node:crypto";
import { assertDescriptor, canonical, clone, closed, digest, list, reject, sha, text } from "./managed-types.mjs";
const toolsAllowed = new Set([
    "tk_read",
    "tk_find",
    "tk_grep",
    "tk_ls",
    "tk_write",
    "tk_edit",
    "structured_output"
]);
export function validateWorkerInput(input) {
    closed(input, [
        "descriptor",
        "context"
    ]);
    assertDescriptor(input.descriptor);
    const descriptor = input.descriptor, context = input.context;
    closed(context, [
        "schema_version",
        "manager_run_id",
        "lease_id",
        "prompt",
        "role",
        "model",
        "route",
        "root_bindings",
        "artifacts",
        "result_schema",
        "database",
        "minimum_remaining"
    ]);
    if (!Number.isSafeInteger(context.minimum_remaining) || context.minimum_remaining < 0) reject();
    closed(context.database, [
        "root",
        "filename",
        "owner"
    ]);
    closed(context.database.owner, [
        "scopeId",
        "token",
        "epoch"
    ]);
    if (!text(context.database.root) || !context.database.root.startsWith("/") || context.database.filename !== "runtime.db" || !text(context.database.owner.scopeId) || !text(context.database.owner.token) || !Number.isSafeInteger(context.database.owner.epoch) || context.database.owner.epoch < 1) reject("WORKER_DATABASE_BINDING", 4);
    closed(context.role, [
        "id",
        "digest",
        "definition",
        "system_prompt",
        "tools"
    ]);
    closed(context.model, [
        "provider_id",
        "model_id",
        "model_digest",
        "api"
    ]);
    closed(context.route, [
        "id",
        "type",
        "base_url",
        "proxy_url"
    ]);
    if (context.schema_version !== 1 || ![
        context.manager_run_id,
        context.lease_id,
        context.prompt,
        context.role.system_prompt
    ].every(text) || context.role.id !== descriptor.role_id || context.role.digest !== descriptor.role_digest || !text(context.role.definition) || createHash("sha256").update(context.role.definition).digest("hex") !== descriptor.role_digest || !list(context.role.tools) || canonical(context.role.tools) !== canonical(descriptor.allowed_tools) || descriptor.allowed_tools.some((name)=>!toolsAllowed.has(name)) || context.model.provider_id !== descriptor.provider_id || context.model.model_id !== descriptor.model_id || context.model.model_digest !== descriptor.model_digest || context.model.api !== "openai-completions" || context.route.id !== descriptor.route_id || ![
        "direct",
        "proxy"
    ].includes(context.route.type) || !context.root_bindings || Object.getPrototypeOf(context.root_bindings) !== Object.prototype || !context.artifacts || Object.getPrototypeOf(context.artifacts) !== Object.prototype || digest(context.result_schema) !== descriptor.result_schema_digest) reject("WORKER_BINDING_MISMATCH", 5);
    for (const root of Object.values(context.root_bindings)){
        closed(root, [
            "path",
            "identity"
        ]);
        if (!text(root.path) || !root.path.startsWith("/") || !sha(root.identity)) reject("WORKER_BINDING_MISMATCH", 5);
    }
    if ([
        ...descriptor.read_roots,
        ...descriptor.write_roots
    ].some((root)=>!Object.hasOwn(context.root_bindings, root)) || Object.keys(context.artifacts).some((id)=>!descriptor.allowed_artifact_ids.includes(id))) reject("WORKER_BINDING_MISMATCH", 5);
    let base, proxy;
    try {
        base = new URL(context.route.base_url);
        proxy = context.route.proxy_url === null ? null : new URL(context.route.proxy_url);
    } catch  {
        reject("WORKER_ROUTE_INVALID", 2);
    }
    if (![
        "http:",
        "https:"
    ].includes(base.protocol) || base.username || base.password || base.search || base.hash || context.route.type === "direct" && proxy !== null || context.route.type === "proxy" && !proxy || proxy && (![
        "http:",
        "https:"
    ].includes(proxy.protocol) || proxy.username || proxy.password || proxy.search || proxy.hash)) reject("WORKER_ROUTE_INVALID", 2);
    return clone(input);
}
