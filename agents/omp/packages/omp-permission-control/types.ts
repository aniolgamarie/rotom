export type PermissionMode = "smart" | "manual";

export interface ManagedPermissionConfig {
  runtime_variant: "permission-control-v1";
  default_mode: PermissionMode;
  reviewer_model?: string;
  remote_fallback_model?: string;
  fallback_model?: "local/lfm2.5-230m";
  plugin_selected: true;
}

export interface NativeReviewer {
  provider: string;
  model: string;
  /** 解析后的实际模型可携带；原生配置中的 reviewer/remoteFallback 不接受该字段。 */
  api?: string;
}

export interface NativeFallback {
  provider: "local";
  model: "lfm2.5-230m";
  installedOnly: true;
}

export interface NativePermissionControl {
  schemaVersion: 1;
  defaultMode: PermissionMode;
  reviewer: "session" | NativeReviewer;
  remoteFallback?: NativeReviewer;
  fallback?: NativeFallback;
  bridgeAbi: "permission-control/v1";
  pluginId: "omp-permission-control";
  pluginDigest: string;
  runtimeIdentity: string;
  policyVersion: string;
}

export type PluginLoadState =
  | "verified"
  | "missing"
  | "damaged"
  | "identity-mismatch"
  | "not-loaded"
  | "unhealthy";

export interface PluginDeliveryIdentity {
  plugin_id: "omp-permission-control";
  plugin_tree_digest: string;
  manifest_path: "locks/omp/permission-control/manifest.json";
  runtime_variant: "permission-control-v1";
  runtime_identity: string;
  bridge_abi: "permission-control/v1";
  load_state: PluginLoadState;
}

export type PermissionContractErrorCode =
  | "INVALID_OBJECT"
  | "UNKNOWN_FIELD"
  | "MISSING_FIELD"
  | "INVALID_LITERAL"
  | "INVALID_ENUM"
  | "INVALID_STRING"
  | "INVALID_SHA256"
  | "INVALID_REVIEWER"
  | "INVALID_FALLBACK"
  | "PLUGIN_NOT_SELECTED"
  | "REVIEWER_NOT_SELECTED";

export class PermissionContractError extends Error {
  readonly code: PermissionContractErrorCode;
  readonly path: string;

  constructor(code: PermissionContractErrorCode, path: string) {
    super(`${code}:${path}`);
    this.name = "PermissionContractError";
    this.code = code;
    this.path = path;
  }
}

type JsonObject = Record<string, unknown>;

const SHA256 = /^[0-9a-f]{64}$/;
const MODES = new Set<unknown>(["smart", "manual"]);
const LOAD_STATES = new Set<unknown>([
  "verified",
  "missing",
  "damaged",
  "identity-mismatch",
  "not-loaded",
  "unhealthy",
]);

function fail(code: PermissionContractErrorCode, path: string): never {
  throw new PermissionContractError(code, path);
}

function objectAt(value: unknown, path: string, code: PermissionContractErrorCode = "INVALID_OBJECT"): JsonObject {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    return fail(code, path);
  }
  const prototype = Object.getPrototypeOf(value);
  if (prototype !== Object.prototype && prototype !== null) {
    return fail(code, path);
  }
  return value as JsonObject;
}

function checkFields(value: JsonObject, path: string, required: readonly string[], optional: readonly string[] = []): void {
  const allowed = new Set([...required, ...optional]);
  for (const key of Object.keys(value)) {
    if (!allowed.has(key)) {
      fail("UNKNOWN_FIELD", path);
    }
  }
  for (const key of required) {
    if (!Object.hasOwn(value, key)) {
      fail("MISSING_FIELD", `${path}.${key}`);
    }
  }
}

function literal<T extends string | number | boolean>(value: unknown, expected: T, path: string): T {
  if (value !== expected) {
    return fail("INVALID_LITERAL", path);
  }
  return expected;
}

function mode(value: unknown, path: string): PermissionMode {
  if (!MODES.has(value)) {
    return fail("INVALID_ENUM", path);
  }
  return value as PermissionMode;
}

function safeString(value: unknown, path: string): string {
  if (typeof value !== "string" || value.length === 0 || /[\u0000-\u001f\u007f]/.test(value)) {
    return fail("INVALID_STRING", path);
  }
  return value;
}

function sha256(value: unknown, path: string): string {
  if (typeof value !== "string" || value.length !== 64 || !SHA256.test(value)) {
    return fail("INVALID_SHA256", path);
  }
  return value;
}

function parseReviewer(value: unknown): "session" | NativeReviewer {
  if (value === "session") {
    return "session";
  }
  const reviewer = objectAt(value, "NativePermissionControl.reviewer", "INVALID_REVIEWER");
  checkFields(reviewer, "NativePermissionControl.reviewer", ["provider", "model"]);
  return {
    provider: safeString(reviewer.provider, "NativePermissionControl.reviewer.provider"),
    model: safeString(reviewer.model, "NativePermissionControl.reviewer.model"),
  };
}

function parseFallback(value: unknown): NativeFallback {
  const fallback = objectAt(value, "NativePermissionControl.fallback", "INVALID_FALLBACK");
  checkFields(fallback, "NativePermissionControl.fallback", ["provider", "model", "installedOnly"]);
  return {
    provider: literal(fallback.provider, "local", "NativePermissionControl.fallback.provider"),
    model: literal(fallback.model, "lfm2.5-230m", "NativePermissionControl.fallback.model"),
    installedOnly: literal(fallback.installedOnly, true, "NativePermissionControl.fallback.installedOnly"),
  };
}

function parseRemoteFallback(value: unknown): NativeReviewer {
  const reviewer = objectAt(value, "NativePermissionControl.remoteFallback", "INVALID_REVIEWER");
  checkFields(reviewer, "NativePermissionControl.remoteFallback", ["provider", "model"]);
  return { provider: safeString(reviewer.provider, "NativePermissionControl.remoteFallback.provider"),
    model: safeString(reviewer.model, "NativePermissionControl.remoteFallback.model") };
}

export function parseManagedPermissionConfig(
  input: unknown,
  selectedModelIds: readonly string[],
): ManagedPermissionConfig {
  const value = objectAt(input, "ManagedPermissionConfig");
  checkFields(
    value,
    "ManagedPermissionConfig",
    ["runtime_variant", "default_mode", "plugin_selected"],
    ["reviewer_model", "remote_fallback_model", "fallback_model"],
  );

  const parsed: ManagedPermissionConfig = {
    runtime_variant: literal(
      value.runtime_variant,
      "permission-control-v1",
      "ManagedPermissionConfig.runtime_variant",
    ),
    default_mode: mode(value.default_mode, "ManagedPermissionConfig.default_mode"),
    plugin_selected: true,
  };
  if (value.plugin_selected !== true) {
    fail("PLUGIN_NOT_SELECTED", "ManagedPermissionConfig.plugin_selected");
  }

  if (Object.hasOwn(value, "reviewer_model")) {
    const reviewer = safeString(value.reviewer_model, "ManagedPermissionConfig.reviewer_model");
    if (!selectedModelIds.includes(reviewer)) {
      fail("REVIEWER_NOT_SELECTED", "ManagedPermissionConfig.reviewer_model");
    }
    parsed.reviewer_model = reviewer;
  }

  if (Object.hasOwn(value, "remote_fallback_model")) {
    const reviewer = safeString(value.remote_fallback_model, "ManagedPermissionConfig.remote_fallback_model");
    if (!selectedModelIds.includes(reviewer)) {
      fail("REVIEWER_NOT_SELECTED", "ManagedPermissionConfig.remote_fallback_model");
    }
    parsed.remote_fallback_model = reviewer;
  }

  if (Object.hasOwn(value, "fallback_model")) {
    parsed.fallback_model = literal(
      value.fallback_model,
      "local/lfm2.5-230m",
      "ManagedPermissionConfig.fallback_model",
    );
  }
  return parsed;
}

export function parseNativePermissionControl(input: unknown): NativePermissionControl {
  const value = objectAt(input, "NativePermissionControl");
  checkFields(
    value,
    "NativePermissionControl",
    [
      "schemaVersion",
      "defaultMode",
      "reviewer",
      "bridgeAbi",
      "pluginId",
      "pluginDigest",
      "runtimeIdentity",
      "policyVersion",
    ],
    ["fallback", "remoteFallback"],
  );

  const parsed: NativePermissionControl = {
    schemaVersion: literal(value.schemaVersion, 1, "NativePermissionControl.schemaVersion"),
    defaultMode: mode(value.defaultMode, "NativePermissionControl.defaultMode"),
    reviewer: parseReviewer(value.reviewer),
    bridgeAbi: literal(value.bridgeAbi, "permission-control/v1", "NativePermissionControl.bridgeAbi"),
    pluginId: literal(value.pluginId, "omp-permission-control", "NativePermissionControl.pluginId"),
    pluginDigest: sha256(value.pluginDigest, "NativePermissionControl.pluginDigest"),
    runtimeIdentity: safeString(value.runtimeIdentity, "NativePermissionControl.runtimeIdentity"),
    policyVersion: sha256(value.policyVersion, "NativePermissionControl.policyVersion"),
  };
  if (Object.hasOwn(value, "fallback")) {
    parsed.fallback = parseFallback(value.fallback);
  }
  if (Object.hasOwn(value, "remoteFallback")) {
    parsed.remoteFallback = parseRemoteFallback(value.remoteFallback);
  }
  return parsed;
}

export function parsePluginDeliveryIdentity(input: unknown): PluginDeliveryIdentity {
  const value = objectAt(input, "PluginDeliveryIdentity");
  checkFields(value, "PluginDeliveryIdentity", [
    "plugin_id",
    "plugin_tree_digest",
    "manifest_path",
    "runtime_variant",
    "runtime_identity",
    "bridge_abi",
    "load_state",
  ]);
  if (!LOAD_STATES.has(value.load_state)) {
    fail("INVALID_ENUM", "PluginDeliveryIdentity.load_state");
  }
  return {
    plugin_id: literal(value.plugin_id, "omp-permission-control", "PluginDeliveryIdentity.plugin_id"),
    plugin_tree_digest: sha256(value.plugin_tree_digest, "PluginDeliveryIdentity.plugin_tree_digest"),
    manifest_path: literal(
      value.manifest_path,
      "locks/omp/permission-control/manifest.json",
      "PluginDeliveryIdentity.manifest_path",
    ),
    runtime_variant: literal(
      value.runtime_variant,
      "permission-control-v1",
      "PluginDeliveryIdentity.runtime_variant",
    ),
    runtime_identity: safeString(value.runtime_identity, "PluginDeliveryIdentity.runtime_identity"),
    bridge_abi: literal(value.bridge_abi, "permission-control/v1", "PluginDeliveryIdentity.bridge_abi"),
    load_state: value.load_state as PluginLoadState,
  };
}
