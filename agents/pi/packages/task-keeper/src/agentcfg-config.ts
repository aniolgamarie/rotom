// 从 agentcfg 的显式实例清单生成原业务配置，保留工作流/恢复/统计代码的配置接口。
import { readFileSync } from "node:fs";
import { join } from "node:path";
import type { Config } from "./config.ts";
import { ContractError } from "./contracts/primitives.ts";

export function fromAgentcfg(defaults: Config, runtime: any): Config {
  const config = structuredClone(defaults), manifest = runtime.manifest, options = manifest.options.task_keeper;
  config.storage.path = join(runtime.instanceRoot, "pi-home/task-keeper/runtime.db");
  config.enabled = options?.enabled === true;
  config.features.managedWorkflows = config.enabled;
  config.features.interactiveRecovery = false;
  config.features.crossProviderFailover = false;
  config.limits.activeChildrenPerHost = 2; config.limits.parallelReaders = 1; config.limits.writersPerJob = 1;
  if (!config.enabled) return config;
  const models = JSON.parse(readFileSync(join(runtime.instanceRoot, "pi-home/models.json"), "utf8")).providers;
  const pairs = [["scout", "task-keeper-reader"], ["worker", "task-keeper-writer"], ["reviewer", "task-keeper-reviewer"]];
  if (options.second_view_enabled) pairs.push(["second_view", "task-keeper-second-view"]);
  config.executionProfiles = {};
  for (const [name, id] of pairs) {
    const role = runtime.roleManifest.roles.find((value: any) => value.id === id && value.managed);
    if (!role) throw new ContractError("ROLE_BINDING_REQUIRED");
    const logical = role.model.provider.replace(/^agentcfg-/, "");
    const networks = Object.entries(manifest.options.network?.routes ?? {}).filter(([, value]: any) => value.provider_ids.includes(logical));
    if (networks.length !== 1) throw new ContractError("NETWORK_BINDING_REQUIRED");
    const [networkId, network] = networks[0] as [string, any];
    config.network[networkId] = network.mode === "direct" ? { type: "direct" } : { type: new URL(network.proxy_url).protocol === "https:" ? "https" : "http", endpoint: network.proxy_url };
    const routeId = "managed-" + name, quotaGroup = "quota-" + name;
    config.routes[routeId] = { provider: role.model.provider, model: role.model.model, accountBinding: "provider:" + role.model.provider,
      quotaGroup, transportDomain: networkId, network: networkId, protected: true };
    config.quotaGroups[quotaGroup] = { classifier: "http", rules: [], baseIntervalMs: 60000, tailIntervalsMs: [60000, 300000] };
    config.allowedRoutes.push(routeId);
    config.roles[name] = { route: routeId, profileRef: name };
    const model = models[role.model.provider]?.models.find((value: any) => value.id === role.model.model);
    config.executionProfiles[name] = { tools: name === "worker" ? ["read", "grep", "find", "ls", "write", "edit"] : ["read", "grep", "find", "ls"],
      requiredCapabilities: ["events", "termination", "workspace", "requestGate", ...(name === "worker" ? [] : ["readonly"])],
      timeoutMs: options.limits.wall_seconds * 1000, maxModelTurns: options.limits.model_turns, toolTimeoutMs: 30000,
      thinking: role.thinking ?? (model?.reasoning ? "medium" : "off") };
  }
  config.projectRouteApprovals = { "*": [...config.allowedRoutes] };
  config.budget.protectedAttemptsPerWorkScope = options.limits.model_requests * config.limits.jobsPerWorkScope;
  config.workflow.requiredChecks.inspect = [...options.check_ids, "scope-evidence-review"];
  config.workflow.requiredChecks.fix = [...new Set([...options.check_ids, "independent-review"])];
  for (const id of options.check_ids) {
    const binding = manifest.options.checks[id];
    config.verificationBindings[id] = { executable: binding.executable, args: binding.args, environment: {}, timeoutMs: binding.timeout_seconds * 1000,
      kind: binding.kind, parser: binding.parser, minimumTests: binding.minimum_tests, inputs: binding.inputs };
  }
  if (options.second_view_enabled) {
    const role = config.roles.second_view, route = config.routes[role.route];
    config.secondOpinion = { ...config.secondOpinion, enabled: true, model: { provider: route.provider, model: route.model },
      profileRef: role.profileRef, maxExchanges: options.max_second_view_rounds };
  }
  return config;
}
