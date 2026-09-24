// 工具仅解析只读意图；写入授权只在用户 CLI 与 supervisor 准入层处理。
import { realpathSync } from "node:fs";
import { isAbsolute, relative, sep } from "node:path";
import { closed, reject, text } from "@agentcfg/pi-runtime/managed-types";

export function resolveToolRequest(input: any, runtime: any) {
  if (!runtime || runtime.owner?.role !== "manager") reject("CAPABILITY_MISSING", 5);
  if (runtime.managedRequestScope?.getStore()) reject("UNMETERED_EXTERNAL_DELEGATE", 5);
  closed(input, ["mode", "preset", "task", "cwd", "timeout_seconds"], ["backend", "model", "model_role", "context_artifact"]);
  const options = runtime.manifest.options.model_delegate;
  if (!options?.enabled) reject("CAPABILITY_MISSING", 5);
  const backend = input.backend ?? (options.backends.length === 1 ? options.backends[0] : null);
  if (!backend || !options.backends.includes(backend) || !["pi", "codex"].includes(backend)) reject("DELEGATE_BACKEND_UNBOUND", 2);
  if (!["review", "investigate"].includes(input.mode) || !options.allowed_modes.includes(input.mode)) reject("DELEGATE_TOOL_READONLY", 2);
  if (!options.presets.includes(input.preset) || !["general", "context", "challenge", "plan", "research", "review", "scout"].includes(input.preset)
      || !text(input.task) || !input.task.trim() || input.task.length > 65536
      || !Number.isSafeInteger(input.timeout_seconds) || input.timeout_seconds <= 0 || input.timeout_seconds > options.max_run_seconds) reject("DELEGATE_REQUEST_INVALID", 2);
  if (Number(input.model !== undefined) + Number(input.model_role !== undefined) !== 1) reject("DELEGATE_MODEL_REQUIRED", 2);
  let model;
  if (backend === "codex") {
    const binding = input.model_role === undefined ? null : runtime.manifest.model_bindings[input.model_role];
    if (!options.codex?.model || (input.model_role !== undefined
        ? !binding || binding.provider !== "openai-codex" || binding.model !== options.codex.model
          || !runtime.manifest.allowed_models.some((value: any) => value.provider === binding.provider && value.model === binding.model)
        : input.model !== options.codex.model)) reject("DELEGATE_MODEL_UNBOUND", 2);
    model = { provider_id: "openai", model_id: options.codex.model };
  } else {
    const roles = options.pi?.model_roles ?? [];
    const allowed = roles.map((role: string) => runtime.manifest.model_bindings[role]).filter(Boolean);
    const matches = input.model_role !== undefined ? (roles.includes(input.model_role) ? [runtime.manifest.model_bindings[input.model_role]].filter(Boolean) : [])
      : allowed.filter((value: any) => value.provider + "/" + value.model === input.model);
    const unique = new Map(matches.map((value: any) => [value.provider + "/" + value.model, value]));
    if (unique.size !== 1) reject("DELEGATE_MODEL_UNBOUND", 2);
    const selected: any = [...unique.values()][0];
    if (!runtime.manifest.allowed_models.some((value: any) => value.provider === selected.provider && value.model === selected.model)) reject("DELEGATE_MODEL_UNBOUND", 2);
    model = { provider_id: selected.provider, model_id: selected.model };
  }
  if (!text(input.cwd) || !isAbsolute(input.cwd)) reject("DELEGATE_ROOT_UNBOUND", 2);
  let cwd;
  try { cwd = realpathSync(input.cwd); } catch { reject("DELEGATE_ROOT_UNBOUND", 2); }
  const roots = runtime.manifest.options.paths?.roots ?? {}, denied = runtime.manifest.options.permissions?.denied_roots ?? [];
  const inside = (root: string) => { const tail = relative(realpathSync(root), cwd); return tail === "" || !tail.startsWith(".." + sep) && tail !== ".." && !isAbsolute(tail); };
  if (!Object.entries(roots).some(([name, binding]: any) => !denied.includes(name) && inside(binding.path))
      || denied.some((name: string) => roots[name] && inside(roots[name].path))) reject("DELEGATE_ROOT_UNBOUND", 2);
  if (input.context_artifact !== undefined && (!text(input.context_artifact) || !/^[a-zA-Z0-9_.-]{1,200}$/.test(input.context_artifact))) reject("DELEGATE_CONTEXT_INVALID", 2);
  return { backend, mode: input.mode, preset: input.preset, task: input.task, cwd, model, timeout_seconds: input.timeout_seconds,
    context_artifact: input.context_artifact ?? null, execution_mode: "delegate-readonly" };
}
