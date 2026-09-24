// agentcfg 是唯一策略来源；原生引擎保留提示与审计接口，但不能扩展硬权限。
import { join } from "node:path";
import type { PolicyLoader, ResolvedPolicyPaths } from "./policy-loader";
import type { ScopeConfig } from "./types";

export function agentcfgRuntime(): any {
  const runtime = (globalThis as any)[Symbol.for("agentcfg.pi.runtime.v1")];
  if (!runtime?.permissionAccess || runtime.owner?.role !== "manager") throw new Error("AGENTCFG_PERMISSION_CAPABILITY_MISSING");
  runtime.permissionAccess.require();
  return runtime;
}

export class AgentcfgPolicyLoader implements PolicyLoader {
  loadGlobalConfig(): ScopeConfig { agentcfgRuntime(); return { permission: { "*": "ask" } }; }
  loadProjectConfig(): ScopeConfig { agentcfgRuntime(); return {}; }
  loadAgentConfig(): ScopeConfig { agentcfgRuntime(); return {}; }
  loadProjectAgentConfig(): ScopeConfig { agentcfgRuntime(); return {}; }
  getConfiguredMcpServerNames(): readonly string[] { return Object.keys(agentcfgRuntime().manifest.options.mcp?.servers ?? {}); }
  getCacheStamp(): string { const state = agentcfgRuntime().permissionAccess.require(); return state.policy_digest + ":" + state.generation; }
  getConfigIssues(): string[] { agentcfgRuntime(); return []; }
  getResolvedPolicyPaths(): ResolvedPolicyPaths {
    const runtime = agentcfgRuntime(), home = join(runtime.instanceRoot, "pi-home");
    return { globalConfigPath: join(home, "agentcfg-manifest.json"), globalConfigExists: true,
      projectConfigPath: null, projectConfigExists: false, agentsDir: join(home, "generated-roles"), agentsDirExists: true,
      projectAgentsDir: null, projectAgentsDirExists: false };
  }
}

export async function agentcfgGate(event: any, ctx: any, nativeGate: () => Promise<any>) {
  const access = agentcfgRuntime().permissionAccess;
  const ticket = await access.check(event, ctx);
  let approved = false;
  try {
    const verdict = await nativeGate();
    if (!verdict?.block) { access.approve(event, ticket, ctx); approved = true; }
    return verdict;
  } finally {
    if (!approved) await agentcfgRuntime().ordinaryOperations?.abort?.(ticket.result);
  }
}
