// 官方SDK初始化：仅用于已获准的实例启动。目录/账号可能由SDK创建，诊断与render不能调用。
import { createHash } from "node:crypto";
import { isAbsolute, join, resolve } from "node:path";
import { isDeepStrictEqual } from "node:util";
import { optionalPrivateBytes } from "./private-files.ts";
import { strictJson } from "./strict-json.ts";
import { createOfficialModelConfiguration, createOfficialModels } from "./official-models.ts";
import { createModelConfigSource } from "./model-config-source.ts";
import { createOfficialModelScope } from "./official-model-scope.ts";

const fail = (code, exitCode = 4) => { const error = new Error(code); error.exitCode = exitCode; throw error; };
const plain = value => value !== null && typeof value === "object" && !Array.isArray(value)
  && Object.getPrototypeOf(value) === Object.prototype && !Object.getOwnPropertySymbols(value).length
  && Object.values(Object.getOwnPropertyDescriptors(value)).every(item => Object.hasOwn(item, "value") && item.enumerable);
const string = value => typeof value === "string" && value.length > 0;
const providerId = value => string(value) && value.length <= 256 && !/[\p{Cc}\p{Cf}\p{Cs}]/u.test(value);
function freeze(value) {
  if (value && typeof value === "object") { Object.values(value).forEach(freeze); Object.freeze(value); }
  return value;
}
const sorted = rows => [...rows].sort((a, b) => a.providerId < b.providerId ? -1 : a.providerId > b.providerId ? 1 : 0);

function authenticationSources(manifest, authPath) {
  const bindings = manifest.provider_bindings;
  const native = Object.values(bindings).some(binding => binding.auth_kind === "oauth");
  if (Object.values(bindings).some(binding => binding.auth_kind === "oauth" && binding.owner !== "pi-native")) fail("pi-runtime-auth-owner-unsupported", 5);
  const checkOwner = (id, type) => {
    const binding = Object.hasOwn(bindings, id) ? bindings[id] : undefined;
    // API-key路线只由部署的环境引用供给，不允许原生账号记录或runtime override抢占。
    if (binding && (binding.auth_kind !== "oauth" || type !== "oauth")) fail("pi-runtime-auth-owner-conflict");
  };
  const read = () => {
    if (!native) return [];
    let value;
    try {
      const bytes = optionalPrivateBytes(authPath, 1024 * 1024);
      value = bytes === undefined ? {} : strictJson(new TextDecoder("utf8", { fatal: true }).decode(bytes));
    } catch { fail("pi-runtime-auth-private"); }
    if (!plain(value)) fail("pi-runtime-auth-format", 2);
    const rows = [];
    for (const [id, credential] of Object.entries(value)) {
      if (!providerId(id) || !plain(credential)) fail("pi-runtime-auth-format", 2);
      const type = credential.type;
      if (type === "oauth") {
        // OAuth公开格式允许提供者扩展字段；这里只读校验，不复制/散列/写回账号正文。
        if (!string(credential.access) || !string(credential.refresh) || typeof credential.expires !== "number"
            || !Number.isFinite(credential.expires) || credential.expires < 0) fail("pi-runtime-auth-format", 2);
      } else if (type === "api_key") {
        if (Object.keys(credential).some(key => !["type", "key", "env"].includes(key))
            || credential.key !== undefined && typeof credential.key !== "string"
            || credential.env !== undefined && (!plain(credential.env) || Object.values(credential.env).some(item => typeof item !== "string"))) fail("pi-runtime-auth-format", 2);
      } else fail("pi-runtime-auth-format", 2);
      checkOwner(id, type); rows.push({ providerId: id, type });
    }
    return sorted(rows);
  };
  const checkMetadata = (rows, expected) => {
    if (!Array.isArray(rows) || rows.length > 4096 || rows.some(row => !plain(row)
        || Object.keys(row).sort().join(",") !== "providerId,type" || !providerId(row.providerId) || !["oauth", "api_key"].includes(row.type))
        || new Set(rows.map(row => row.providerId)).size !== rows.length) fail("pi-runtime-auth-metadata");
    for (const row of rows) checkOwner(row.providerId, row.type);
    if (!isDeepStrictEqual(sorted(rows), expected)) fail("pi-runtime-auth-state-stale");
  };
  read();
  return { native, read, checkMetadata };
}

export function createOfficialRuntimeInitializer({ sdk, ai, manifest, instanceRoot }) {
  if (typeof instanceRoot !== "string" || !isAbsolute(instanceRoot) || resolve(instanceRoot) !== instanceRoot
      || /[\p{Cc}\p{Cf}\p{Cs}]/u.test(instanceRoot)) fail("pi-runtime-location", 2);
  let fixed;
  try { fixed = freeze(structuredClone(manifest)); } catch { fail("pi-runtime-manifest", 2); }
  if (!["pi-base", "pi-full"].includes(fixed?.profile_id)) fail("pi-runtime-profile", 2);
  const directory = join(instanceRoot, "pi-home"), path = join(directory, "models.json"), authPath = join(directory, "auth.json");
  // 预检在SDK消费之前执行；初始化时还会重验，创建工厂不是长期有效的授权。
  const configuration = createOfficialModelConfiguration({ manifest: fixed, path });
  const auth = authenticationSources(fixed, authPath);
  if (typeof sdk?.ModelRuntime?.create !== "function" || typeof ai?.InMemoryModelsStore !== "function"
      || !auth.native && typeof ai?.InMemoryCredentialStore !== "function") fail("pi-runtime-sdk-incompatible", 5);
  let pending;
  const initialize = async () => {
    configuration.checkFile(); auth.read();
    const providers = Object.fromEntries(Object.entries(fixed.model_configuration.providers).filter(([, value]) => value.auth_kind === "api-key")
      .map(([route, value]) => [route, { ...value.config, apiKey: "$AGENTCFG_PI_CREDENTIAL_" + createHash("sha256").update(value.logical_id).digest("hex").slice(0, 16).toUpperCase() }]));
    // SDK读取自有、已unlink且由只读fd持有的inode，不能在预检后重新打开原配置路径。
    const source = createModelConfigSource({ directory, contents: JSON.stringify({ providers }) + "\n" });
    try {
      let modelRuntime;
      try {
        const options = { modelsPath: source.path, modelsStore: new ai.InMemoryModelsStore(), allowModelNetwork: false, refreshOnCreate: false };
        if (auth.native) options.authPath = authPath;
        else options.credentials = new ai.InMemoryCredentialStore();
        modelRuntime = await sdk.ModelRuntime.create(options);
      } catch { fail("pi-runtime-create-failed", 5); }
      const models = createOfficialModels({ manifest: fixed, path, modelRuntime });
      let scope;
      if (typeof modelRuntime.listCredentials !== "function") fail("pi-runtime-sdk-incompatible", 5);
      const check = async () => {
        source.check(); models.checkRuntime(); scope?.check();
        const expected = auth.read();
        let metadata;
        try { metadata = await modelRuntime.listCredentials(); }
        catch { fail("pi-runtime-auth-unavailable", 5); }
        auth.checkMetadata(metadata, expected);
        if (!isDeepStrictEqual(auth.read(), expected)) fail("pi-runtime-auth-state-stale");
        for (const row of fixed.allowed_models) {
          let model;
          try {
            model = modelRuntime.getModel(row.provider, row.model);
            if (modelRuntime.getError() !== undefined) fail("pi-runtime-model-error", 5);
          } catch { fail("pi-runtime-model-error", 5); }
          if (!model) {
            if (fixed.provider_bindings[row.provider].auth_kind === "api-key") fail("pi-main-model-unavailable", 5);
            continue;
          }
          models.describe(model);
        }
        source.check(); models.checkRuntime(); scope?.check();
      };
      await check();
      scope = createOfficialModelScope({ modelRuntime, manifest: fixed, describe: models.describe });
      scope.check();
      // 每个宿主进程创建一个initializer，/new复用其Runtime。成功后的fd保留至进程退出，
      // 不提供提前close：SDK未来refresh仍会按该path读，不能把fd号复用成另一文件。
      return Object.freeze({ modelRuntime: scope.modelRuntime, check, configurationDigest: configuration.declarationDigest });
    } catch (error) {
      try { source.close(); } catch { /* 初始化未交付，保留原固定错误；不关闭身份未知的外来fd。 */ }
      throw error;
    }
  };
  // 相同工厂的并发/重试共用同一次初始化；失败也不能隐式重复创建账号状态。
  return () => pending ??= initialize();
}
