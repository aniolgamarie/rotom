// 派生管理者只读取 launcher 传入的清单，不发现全局/项目角色或设置。
import { createHash } from "node:crypto";
import { closeSync, constants, fstatSync, openSync, readFileSync, realpathSync } from "node:fs";

export const RUNTIME_KEY = Symbol.for("agentcfg.pi.runtime.v1");
export const MANAGER_KEY = Symbol.for("pi-subagents:manager");
export const BRIDGE_KEY = Symbol.for("agentcfg.pi.managed.v1");

export function runtimeContext(): any {
  const context = (globalThis as any)[RUNTIME_KEY];
  if (!context || context.owner?.role !== "manager" || !context.supervisor) throw new Error("AGENTCFG_MANAGER_CONTEXT_REQUIRED");
  return context;
}

export function assertSingleManager(): void {
  runtimeContext();
  if ((globalThis as any)[MANAGER_KEY] !== undefined || (globalThis as any)[BRIDGE_KEY] !== undefined) {
    throw new Error("AGENTCFG_MANAGER_LISTENER_CONFLICT");
  }
}

export function controlledSettings() {
  runtimeContext();
  return { disableDefaultAgents: true, fallbackSubagent: "none", maxSubagentDepth: 0,
    maxConcurrent: 2, maxConcurrentForeground: 2, workflowsEnabled: false,
    schedulingEnabled: false, worktreeIsolation: false, strictAgentFiles: true,
    rememberAgents: false, scopeModels: true };
}

export function assertOrdinaryOptions(options: Record<string, unknown>): void {
  const allowed = new Set(["description", "model", "maxTurns", "thinkingLevel", "inheritContext", "isolated", "isBackground",
    "joinMode", "outputTranscript", "outputFile", "name", "cwd", "isolation", "signal"]);
  const forbidden = ["parentAgentId", "workflowId", "depth", "maxSubagentDepth", "configCwd", "rootSessionId",
    "resumeSessionFile", "reclaim", "blocking", "bypassQueue", "agentcfgExecution", "executor", "descriptor", "owner_nonce"];
  if (Object.keys(options).some(key => !allowed.has(key)) || forbidden.some(key => Object.hasOwn(options, key)) || Object.getOwnPropertySymbols(options).length) {
    throw new Error("AGENTCFG_SPAWN_FORBIDDEN");
  }
}

export function loadControlledRoles(parse: (text: string) => { body: string }, managed = false): Map<string, any> {
  const context = runtimeContext();
  const snapshot = context.roleManifest;
  if (snapshot?.schema_version !== 1 || !Array.isArray(snapshot.roles)) throw new Error("AGENTCFG_ROLE_MANIFEST_REQUIRED");
  const roles = new Map<string, any>();
  for (const role of snapshot.roles) {
    if (typeof role.managed !== "boolean" || roles.has(role.id)) throw new Error("AGENTCFG_ROLE_INVALID");
    const binding = context.manifest.role_bindings[role.id];
    if (!binding || JSON.stringify(binding.model) !== JSON.stringify(role.model)
        || JSON.stringify(binding.tools) !== JSON.stringify(role.tools) || binding.managed !== role.managed) throw new Error("AGENTCFG_ROLE_INVALID");
    // 所有角色都核对内容，不能让隐藏的 managed 角色污染另一份注册表。
    if (realpathSync(role.path) !== role.path) throw new Error("AGENTCFG_ROLE_PATH");
    const fd = openSync(role.path, constants.O_RDONLY | constants.O_NOFOLLOW);
    let content: string;
    try {
      const info = fstatSync(fd);
      if (!info.isFile() || info.nlink !== 1 || info.uid !== process.getuid!() || (info.mode & 0o777) !== 0o600) throw new Error("AGENTCFG_ROLE_PATH");
      content = readFileSync(fd, "utf8");
    } finally { closeSync(fd); }
    if (createHash("sha256").update(content).digest("hex") !== role.compiled_digest) throw new Error("AGENTCFG_ROLE_CHANGED");
    if (role.managed !== managed) continue;
    roles.set(role.id, { name: role.id, description: "agentcfg role " + role.id,
      builtinToolNames: [...role.tools], extSelectors: [], extensions: false, skills: false,
      allowedSubagents: false, inheritContext: false, memory: false, persistSession: false, isolation: "off",
      promptMode: "replace", systemPrompt: parse(content).body.trim(),
      model: role.model.provider + "/" + role.model.model, thinking: binding.thinking, source: "global", sourcePath: role.path, enabled: true });
  }
  return roles;
}
