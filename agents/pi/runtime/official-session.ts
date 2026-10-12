// 官方1.0.1会话工厂：只组合公开接口。调用者负责经过准入的工具/扩展与监督者上下文。
// 本模块不签发执行许可，也不是可独立绕过部署/权限门槛的CLI入口。
import { join, isAbsolute, resolve } from "node:path";
import { isDeepStrictEqual } from "node:util";
import { digest, clone, sha } from "./managed-types.ts";
import { createOfficialResources } from "./official-resources.ts";
import { createOfficialSettings } from "./official-settings.ts";
import { createOfficialModels } from "./official-models.ts";

const fail = code => { throw new Error(code); };
const thinkingLevels = ["off", "minimal", "low", "medium", "high", "xhigh", "max"];
const id = value => typeof value === "string" && /^[A-Za-z0-9][A-Za-z0-9_.:/-]{0,255}$/.test(value);
const pair = value => value && id(value.provider) && id(value.model);
const sameModel = (model, binding) => model?.provider === binding.provider && model?.id === binding.model;
// 公开Model是数据描述；headers等可能含秘密，只保留私有内存副本比较，不序列化/哈希/输出。
function modelDescription(model) {
  try { return structuredClone(model); }
  catch { fail("pi-model-description-invalid"); }
}
const modelKey = model => JSON.stringify([model.provider, model.id]);
function lookup(modelRuntime, binding) {
  try {
    const model = modelRuntime.getModel(binding.provider, binding.model);
    // 查询自身可能才产生availability错误；必须在加载扩展/创建会话/签发快照前观察。
    if (modelRuntime.getError() !== undefined) fail("pi-model-runtime-error");
    return model;
  }
  catch { fail("pi-model-runtime-error"); }
}

function selectedModels(manifest) {
  const rows = manifest.allowed_models;
  if (!Array.isArray(rows) || !rows.length || rows.some(row => !pair(row) || Object.keys(row).sort().join(",") !== "model,provider")
      || new Set(rows.map(row => JSON.stringify([row.provider, row.model]))).size !== rows.length) fail("pi-model-binding-invalid");
  return rows;
}

function requireModel(modelRuntime, manifest, binding) {
  if (!pair(binding) || !selectedModels(manifest).some(row => row.provider === binding.provider && row.model === binding.model)) fail("pi-model-not-selected");
  const model = lookup(modelRuntime, binding);
  if (!model || !sameModel(model, binding)) fail("pi-main-model-unavailable");
  return model;
}

export function resolveOfficialModel({ manifest, modelRuntime, settings, sessionManager }) {
  // 不把undefined传给SDK，避免恢复失败后进入findInitialModel的自动换路由分支。
  if (manifest.bootstrap) fail("pi-main-model-unbound");
  selectedModels(manifest);
  const main = manifest.model_bindings?.main;
  if (!pair(main)) fail("pi-main-model-unbound");
  const context = sessionManager.buildSessionContext(), branch = sessionManager.getBranch();
  if (!Array.isArray(context?.messages) || !Array.isArray(branch)) fail("pi-session-context-invalid");
  // 显式受管选择优先于assistant物理响应；响应文本/元数据不能把恢复切到另一个账号路线。
  // 选择已消失时拒绝，不能采用SDK恢复到物理响应或默认provider的回退行为。
  const saved = branch.findLast(entry => entry?.type === "model_change");
  let binding;
  if (saved) binding = { provider: saved.provider, model: saved.modelId };
  else if (context.messages.length) {
    if (!context.model) fail("pi-session-model-missing");
    binding = { provider: context.model.provider, model: context.model.modelId };
  } else {
    const effective = settings.snapshot();
    if (effective.defaultProvider !== undefined || effective.defaultModel !== undefined) {
      binding = { provider: effective.defaultProvider, model: effective.defaultModel };
    } else binding = main;
  }
  return requireModel(modelRuntime, manifest, binding);
}

function freeze(value) {
  if (value && typeof value === "object") { Object.values(value).forEach(freeze); Object.freeze(value); }
  return value;
}

function controls(configuration, cwd) {
  const value = configuration(cwd);
  if (!value || Object.keys(value).sort().join(",") !== "policyDigest,projectConstraintsDigest"
      || !sha(value.policyDigest) || !sha(value.projectConstraintsDigest)) fail("pi-session-policy-context");
  return value;
}

// 只绑定显式声明的公开扩展工具；不复制/摘要可能含秘密的definition或参数。
function bindExtensionTools({ manifest, installed, selection, runtimeRoot, resourceLoader, tools }) {
  const declarations = Object.values(manifest.plugin_capabilities ?? {}).flatMap(row =>
    row.model_tools.map(name => ({ name, capability: row.capability_id })));
  if (declarations.some(row => tools.some(tool => tool.name === row.name))) fail("pi-session-extension-tools");
  const observe = () => {
    const extensions = resourceLoader.getExtensions().extensions;
    return declarations.map(({ name, capability }) => {
      const paths = installed.resources.extensions.filter(row => row.capability_id === capability
        && selection.resources.extensions.some(entry => entry.scope === "runtime" && entry.id === row.id
          && entry.path === resolve(runtimeRoot, row.path))).map(row => resolve(runtimeRoot, row.path));
      const matches = [];
      for (const extension of extensions) {
        for (const [key, registered] of extension.tools ?? []) {
          if (key === name || registered?.definition?.name === name) matches.push({ extension, key, registered });
        }
      }
      if (matches.length !== 1) fail("pi-session-extension-tools");
      const { extension, key, registered } = matches[0], definition = registered?.definition;
      if (!paths.includes(extension.path) || key !== name || definition?.name !== name
          || typeof definition.execute !== "function") fail("pi-session-extension-tools");
      return { name, path: extension.path, registered, definition, execute: definition.execute };
    });
  };
  const original = observe();
  return { names: original.map(row => row.name), check() {
    const current = observe();
    if (current.some((row, index) => row.path !== original[index].path || row.registered !== original[index].registered
        || row.definition !== original[index].definition || row.execute !== original[index].execute)) fail("pi-session-extension-tools");
  } };
}

export function createOfficialSessionFactory({ sdk, manifest, installed, instanceRoot, runtimeRoot, engine,
  settings, runtimeHandle, configuration, toolDefinitions, extensionFactories = [], thinkingLevel, commandGuard, nativeMcp }) {
  if (!["pi-base", "pi-full"].includes(manifest.profile_id) || !sha(installed.runtime_identity)) fail("pi-session-runtime-identity");
  if ([instanceRoot, runtimeRoot].some(path => typeof path !== "string" || !isAbsolute(path) || resolve(path) !== path || path.includes("\0"))) fail("pi-session-location-invalid");
  const modelRuntime = runtimeHandle?.modelRuntime, check = runtimeHandle?.check, configurationDigest = runtimeHandle?.configurationDigest;
  if (typeof check !== "function" || !sha(configurationDigest)) fail("pi-session-runtime-handle");
  if (!sdk || typeof sdk.createAgentSessionFromServices !== "function" || typeof modelRuntime?.getModel !== "function"
      || settings !== undefined && (typeof settings?.snapshot !== "function" || !settings.settingsManager) || typeof configuration !== "function") fail("pi-session-sdk-incompatible");
  if (!Array.isArray(toolDefinitions) || toolDefinitions.some(tool => !tool || !/^[a-zA-Z][a-zA-Z0-9_-]{0,63}$/.test(tool.name)
      || typeof tool.execute !== "function") || new Set(toolDefinitions.map(tool => tool.name)).size !== toolDefinitions.length) fail("pi-session-tools-invalid");
  if (thinkingLevel !== undefined && !thinkingLevels.includes(thinkingLevel)) fail("pi-session-thinking-invalid");
  // 固定本工厂的受信声明；后续外部数组修改不能扩大下一次/new的工具集合。
  const tools = toolDefinitions.map(tool => ({ ...tool }));
  const factories = extensionFactories.map(input => ({ ...input }));
  const mcpNames = [...(nativeMcp?.allowedToolNames ?? [])];
  if (nativeMcp && (typeof nativeMcp.snapshot !== "function" || !mcpNames.length
      || mcpNames.some(name => typeof name !== "string" || !/^[a-zA-Z][a-zA-Z0-9_-]{0,63}$/.test(name))
      || new Set(mcpNames).size !== mcpNames.length || mcpNames.some(name => tools.some(tool => tool.name === name)))) fail("pi-session-mcp-tools");
  const fixedManifest = freeze(clone(manifest));
  const fixedInstalled = freeze(clone(installed));
  const agentDir = join(instanceRoot, "pi-home"), runtimeIdentity = installed.runtime_identity;
  return async ({ cwd, agentDir: requestedAgentDir, sessionManager, sessionStartEvent }) => {
    if (!isAbsolute(cwd) || resolve(cwd) !== cwd || sessionManager?.getCwd?.() !== cwd
        || requestedAgentDir !== undefined && requestedAgentDir !== agentDir) fail("pi-session-location-invalid");
    // 异步检查先于settings读取、资源加载及SDK创建；check返回值不签发许可。
    await check();
    settings ??= createOfficialSettings({ sdk, path: join(agentDir, "settings.json") });
    controls(configuration, cwd);
    const models = createOfficialModels({ manifest: fixedManifest, path: join(agentDir, "models.json"), modelRuntime });
    if (configurationDigest !== models.declarationDigest) fail("pi-session-model-configuration");
    const model = resolveOfficialModel({ manifest: fixedManifest, modelRuntime, settings, sessionManager });
    const binding = { provider: model.provider, model: model.id };
    const admittedModels = new Map();
    for (const row of selectedModels(fixedManifest)) {
      const value = lookup(modelRuntime, row);
      if (!value) {
        if (fixedManifest.model_configuration.providers[row.provider].auth_kind === "api-key") fail("pi-main-model-unavailable");
        continue;
      }
      if (!sameModel(value, row)) fail("pi-model-binding-invalid");
      models.describe(value);
      admittedModels.set(modelKey(value), modelDescription(value));
    }
    const unchangedModel = value => value && admittedModels.has(modelKey(value))
      && isDeepStrictEqual(admittedModels.get(modelKey(value)), modelDescription(value));
    if (!unchangedModel(model)) fail("pi-session-model-changed");
    const { resourceLoader, selection, observeLoadedResources } = createOfficialResources({ sdk, manifest: fixedManifest, installed: fixedInstalled, instanceRoot,
      runtimeRoot, cwd, engine, settingsManager: settings.settingsManager, extensionFactories: factories, commandGuard });
    await resourceLoader.reload();
    await check();
    models.checkRuntime();
    // 加载选定扩展后重新解析，防止加载期间路由对象被替换。
    if (!unchangedModel(requireModel(modelRuntime, fixedManifest, binding)) || !unchangedModel(model)) fail("pi-session-model-changed");
    const extensionTools = bindExtensionTools({ manifest: fixedManifest, installed: fixedInstalled, selection,
      runtimeRoot, resourceLoader, tools });
    if (mcpNames.some(name => extensionTools.names.includes(name))) fail("pi-session-mcp-tools");
    const allowedTools = [...tools.map(tool => tool.name), ...extensionTools.names, ...mcpNames];
    const services = { cwd, agentDir, modelRuntime, settingsManager: settings.settingsManager, resourceLoader, diagnostics: [] };
    const scopedModels = selectedModels(fixedManifest).flatMap(row => {
      const value = lookup(modelRuntime, row);
      if (!value) return [];
      if (!sameModel(value, row)) fail("pi-model-binding-invalid");
      if (!unchangedModel(value)) fail("pi-session-model-changed");
      return [{ model: value }];
    });
    const result = await sdk.createAgentSessionFromServices({ services, sessionManager, sessionStartEvent, model, thinkingLevel,
      scopedModels, noTools: "all", tools: allowedTools, customTools: tools });
    try {
      if (result.modelFallbackMessage || !sameModel(result.session?.model, binding) || !unchangedModel(result.session.model)) fail("pi-session-model-changed");
      if (thinkingLevel !== undefined && result.session.thinkingLevel !== thinkingLevel) fail("pi-session-thinking-unsupported");
      const configurationSnapshot = async () => {
        await check();
        // 每次准入重新读取当前原生settings/model；resource变化只能重建会话，不能悄悄刷新旧证据。
        extensionTools.check();
        models.checkRuntime();
        const current = result.session.model;
        if (!current) fail("pi-main-model-unavailable");
        const actual = { provider: current.provider, model: current.id };
        if (!unchangedModel(requireModel(modelRuntime, fixedManifest, actual)) || !unchangedModel(current)) fail("pi-session-model-changed");
        if (!thinkingLevels.includes(result.session.thinkingLevel)) fail("pi-session-thinking-invalid");
        const context = controls(configuration, cwd);
        const activeTools = result.session.getActiveToolNames();
        if (!Array.isArray(activeTools) || new Set(activeTools).size !== activeTools.length
            || activeTools.some(name => !allowedTools.includes(name))) fail("pi-session-tools-changed");
        const mcpSnapshot = nativeMcp?.snapshot();
        const effectiveConfigDigest = digest({ cwd, pluginCapabilities: fixedManifest.plugin_capabilities ?? {},
          costReporting: fixedManifest.cost_reporting ?? null,
          ...(mcpSnapshot ? { nativeMcp: { bindings: mcpSnapshot.projection.bindings, allowedTools: mcpSnapshot.projection.allowed_tools } } : {}),
          settings: settings.snapshot(), resources: selection.digest,
          model: actual, modelConfiguration: models.declarationDigest, effectiveModel: models.describe(current),
          thinking: result.session.thinkingLevel, tools: [...activeTools].sort() });
        const configIdentity = digest({ profile: fixedManifest.profile_id, effective_config: effectiveConfigDigest,
          policy: context.policyDigest, project_constraints: context.projectConstraintsDigest });
        return freeze({ configIdentity, runtimeIdentity, effectiveConfigDigest, policyDigest: context.policyDigest,
          projectConstraintsDigest: context.projectConstraintsDigest, resourcesDigest: selection.digest,
          model: actual, thinking: result.session.thinkingLevel });
      };
      await configurationSnapshot();
      const resourceSnapshot = async () => {
        // 新诊断接口需要完整固定身份；旧session/configurationSnapshot兼容原缺字段输入。
        if (fixedInstalled.profile_id !== fixedManifest.profile_id || !sha(fixedInstalled.lock_identity)
            || !sha(fixedInstalled.slice_identity) || !sha(fixedInstalled.runtime_identity)) fail("pi-session-resource-identity");
        const current = await configurationSnapshot();
        const observation = observeLoadedResources();
        if (current.resourcesDigest !== selection.digest || observation.resourcesDigest !== selection.digest) fail("pi-session-resource-identity");
        const snapshot = { schemaVersion: 1, profileId: fixedManifest.profile_id, lockIdentity: fixedInstalled.lock_identity,
          sliceIdentity: fixedInstalled.slice_identity, runtimeIdentity: fixedInstalled.runtime_identity,
          configIdentity: current.configIdentity, resourcesDigest: selection.digest, observation };
        if (Buffer.byteLength(JSON.stringify(snapshot), "utf8") > 65536) fail("pi-resource-observation-invalid");
        return freeze(snapshot);
      };
      // 仅自有runtime闭包使用；角色固定在已验证manifest，不接受模型传入的查找参数。
      const semanticModelDescriptions = async () => {
        await configurationSnapshot();
        const rows=[];
        for(const [role,binding] of Object.entries(fixedManifest.model_bindings).sort(([a],[b])=>Buffer.compare(Buffer.from(a),Buffer.from(b)))) {
          const value=requireModel(modelRuntime,fixedManifest,binding);
          if(!unchangedModel(value))fail("pi-session-model-changed");
          rows.push({role_id:role,provider_id:binding.provider,model_id:binding.model,description:models.describe(value)});
        }
        await check();models.checkRuntime();
        for(const binding of Object.values(fixedManifest.model_bindings))if(!unchangedModel(requireModel(modelRuntime,fixedManifest,binding)))fail("pi-session-model-changed");
        return freeze(rows);
      };
      return { ...result, services, diagnostics: [], configurationSnapshot, resourceSnapshot, semanticModelDescriptions };
    } catch (error) {
      result.session?.dispose();
      throw error;
    }
  };
}
