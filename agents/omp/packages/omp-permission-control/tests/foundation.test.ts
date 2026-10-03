import { afterAll, beforeAll, describe, expect, test } from "bun:test";

import {
  PermissionContractError,
  parseManagedPermissionConfig,
  parseNativePermissionControl,
  parsePluginDeliveryIdentity,
} from "../types";

const DIGEST_A = "1".repeat(64);
const DIGEST_B = "2".repeat(64);

const managed = {
  runtime_variant: "permission-control-v1",
  default_mode: "smart",
  reviewer_model: "omp-reviewer/model-a",
  fallback_model: "local/lfm2.5-230m",
  plugin_selected: true,
};

const native = {
  schemaVersion: 1,
  defaultMode: "smart",
  reviewer: { provider: "fictional-provider", model: "fictional-reviewer" },
  fallback: { provider: "local", model: "lfm2.5-230m", installedOnly: true },
  bridgeAbi: "permission-control/v1",
  pluginId: "omp-permission-control",
  pluginDigest: DIGEST_A,
  runtimeIdentity: "omp-v18.3.0-permission-control-v1-linux-x64-test",
  policyVersion: DIGEST_B,
};

const delivery = {
  plugin_id: "omp-permission-control",
  plugin_tree_digest: DIGEST_A,
  manifest_path: "locks/omp/permission-control/manifest.json",
  runtime_variant: "permission-control-v1",
  runtime_identity: "omp-v18.3.0-permission-control-v1-linux-x64-test",
  bridge_abi: "permission-control/v1",
  load_state: "verified",
};

function changed<T extends Record<string, unknown>>(value: T, key: string, replacement: unknown): T {
  return { ...value, [key]: replacement };
}

function missing<T extends Record<string, unknown>>(value: T, key: string): Record<string, unknown> {
  const copy = { ...value };
  delete copy[key];
  return copy;
}

function expectCode(call: () => unknown, code: string): void {
  try {
    call();
    throw new Error("expected validator failure");
  } catch (error) {
    expect(error).toBeInstanceOf(PermissionContractError);
    expect((error as PermissionContractError).code).toBe(code);
    expect(error instanceof Error ? error.message : "").not.toContain("fictional-reviewer");
  }
}

function expectUnknownKeyRedacted(call: () => unknown, trustedPath: string): void {
  const sentinel = "secret-command-sentinel";
  try {
    call();
    throw new Error("expected validator failure");
  } catch (error) {
    expect(error).toBeInstanceOf(PermissionContractError);
    expect((error as PermissionContractError).code).toBe("UNKNOWN_FIELD");
    expect((error as PermissionContractError).path).toBe(trustedPath);
    expect(error instanceof Error ? error.message : "").not.toContain(sentinel);
  }
}

let fetchCalls = 0;
const originalFetch = globalThis.fetch;

beforeAll(() => {
  globalThis.fetch = (() => {
    fetchCalls += 1;
    throw new Error("network disabled in foundation tests");
  }) as typeof fetch;
});

afterAll(() => {
  globalThis.fetch = originalFetch;
  expect(fetchCalls).toBe(0);
});

describe("ManagedPermissionConfig", () => {
  test("accepts the closed managed entity and explicit selected reviewer", () => {
    expect(parseManagedPermissionConfig(managed, ["omp-reviewer/model-a"])).toEqual(managed);
    const remote = { ...managed, remote_fallback_model: "omp-reviewer/model-b" };
    expect(parseManagedPermissionConfig(remote, ["omp-reviewer/model-a", "omp-reviewer/model-b"])).toEqual(remote);
  });

  test("accepts omitted optional reviewer and fallback", () => {
    const minimal = missing(missing(managed, "reviewer_model"), "fallback_model");
    expect(parseManagedPermissionConfig(minimal, [])).toEqual(minimal);
  });

  for (const key of ["runtime_variant", "default_mode", "plugin_selected"]) {
    test(`rejects missing ${key}`, () => expectCode(() => parseManagedPermissionConfig(missing(managed, key), ["omp-reviewer/model-a"]), "MISSING_FIELD"));
  }

  test("rejects null and non-object inputs", () => {
    expectCode(() => parseManagedPermissionConfig(null, []), "INVALID_OBJECT");
    expectCode(() => parseManagedPermissionConfig([], []), "INVALID_OBJECT");
  });

  test("rejects unknown fields", () => expectCode(() => parseManagedPermissionConfig({ ...managed, timeout: 10 }, ["omp-reviewer/model-a"]), "UNKNOWN_FIELD"));
  test("does not echo an unknown field name", () => {
    expectUnknownKeyRedacted(
      () => parseManagedPermissionConfig({ ...managed, "secret-command-sentinel": true }, ["omp-reviewer/model-a"]),
      "ManagedPermissionConfig",
    );
  });
  test("rejects wrong runtime variant", () => expectCode(() => parseManagedPermissionConfig(changed(managed, "runtime_variant", "official"), ["omp-reviewer/model-a"]), "INVALID_LITERAL"));
  test("rejects invalid default mode", () => expectCode(() => parseManagedPermissionConfig(changed(managed, "default_mode", "yolo"), ["omp-reviewer/model-a"]), "INVALID_ENUM"));
  test("rejects false plugin selection", () => expectCode(() => parseManagedPermissionConfig(changed(managed, "plugin_selected", false), ["omp-reviewer/model-a"]), "PLUGIN_NOT_SELECTED"));
  test("rejects invalid fallback", () => expectCode(() => parseManagedPermissionConfig(changed(managed, "fallback_model", "remote/tiny"), ["omp-reviewer/model-a"]), "INVALID_LITERAL"));
  test("rejects null optional fields", () => {
    expectCode(() => parseManagedPermissionConfig(changed(managed, "reviewer_model", null), ["omp-reviewer/model-a"]), "INVALID_STRING");
    expectCode(() => parseManagedPermissionConfig(changed(managed, "fallback_model", null), ["omp-reviewer/model-a"]), "INVALID_LITERAL");
  });
  test("rejects unselected reviewer", () => expectCode(() => parseManagedPermissionConfig(managed, ["another/model"]), "REVIEWER_NOT_SELECTED"));
  test("rejects an unselected remote fallback reviewer", () => expectCode(() =>
    parseManagedPermissionConfig({ ...managed, remote_fallback_model: "omp-reviewer/model-b" },
      ["omp-reviewer/model-a"]), "REVIEWER_NOT_SELECTED"));
  test("rejects reviewer newlines", () => expectCode(() => parseManagedPermissionConfig(changed(managed, "reviewer_model", "omp-reviewer/model-a\nsecret"), ["omp-reviewer/model-a\nsecret"]), "INVALID_STRING"));
  test("rejects reviewer control characters", () => expectCode(() => parseManagedPermissionConfig(changed(managed, "reviewer_model", "omp-reviewer/model-a\0secret"), ["omp-reviewer/model-a\0secret"]), "INVALID_STRING"));
});

describe("NativePermissionControl", () => {
  test("accepts an optional independent remote fallback", () => {
    const value = { ...native, remoteFallback: { provider: "fixture", model: "remote" } };
    expect(parseNativePermissionControl(value)).toEqual(value);
  });
  test("remote fallback must be an explicit model object, never session", () =>
    expectCode(() => parseNativePermissionControl({ ...native, remoteFallback: "session" }), "INVALID_REVIEWER"));
  test("accepts the full native object", () => expect(parseNativePermissionControl(native)).toEqual(native));
  test("accepts session reviewer with fallback omitted", () => {
    const value = { ...missing(native, "fallback"), reviewer: "session" };
    expect(parseNativePermissionControl(value)).toEqual(value);
  });

  for (const key of ["schemaVersion", "defaultMode", "reviewer", "bridgeAbi", "pluginId", "pluginDigest", "runtimeIdentity", "policyVersion"]) {
    test(`rejects missing ${key}`, () => expectCode(() => parseNativePermissionControl(missing(native, key)), "MISSING_FIELD"));
  }

  test("rejects null input", () => expectCode(() => parseNativePermissionControl(null), "INVALID_OBJECT"));
  test("rejects a top-level unknown field", () => expectCode(() => parseNativePermissionControl({ ...native, approvalMode: "yolo" }), "UNKNOWN_FIELD"));
  test("does not echo nested unknown field names", () => {
    expectUnknownKeyRedacted(
      () => parseNativePermissionControl(changed(native, "reviewer", { provider: "p", model: "m", "secret-command-sentinel": true })),
      "NativePermissionControl.reviewer",
    );
  });
  test("rejects schema versions other than one", () => expectCode(() => parseNativePermissionControl(changed(native, "schemaVersion", 2)), "INVALID_LITERAL"));
  test("rejects invalid default mode", () => expectCode(() => parseNativePermissionControl(changed(native, "defaultMode", "automatic")), "INVALID_ENUM"));
  test("rejects reviewer null", () => expectCode(() => parseNativePermissionControl(changed(native, "reviewer", null)), "INVALID_REVIEWER"));
  test("rejects reviewer unknown fields", () => expectCode(() => parseNativePermissionControl(changed(native, "reviewer", { provider: "p", model: "m", token: "hidden" })), "UNKNOWN_FIELD"));
  test("rejects missing reviewer model", () => expectCode(() => parseNativePermissionControl(changed(native, "reviewer", { provider: "p" })), "MISSING_FIELD"));
  test("rejects reviewer provider newlines", () => expectCode(() => parseNativePermissionControl(changed(native, "reviewer", { provider: "p\nq", model: "m" })), "INVALID_STRING"));
  test("rejects fallback null", () => expectCode(() => parseNativePermissionControl(changed(native, "fallback", null)), "INVALID_FALLBACK"));
  test("rejects fallback unknown fields", () => expectCode(() => parseNativePermissionControl(changed(native, "fallback", { ...native.fallback, download: true })), "UNKNOWN_FIELD"));
  test("rejects non-local fallback provider", () => expectCode(() => parseNativePermissionControl(changed(native, "fallback", { ...native.fallback, provider: "remote" })), "INVALID_LITERAL"));
  test("rejects other fallback model", () => expectCode(() => parseNativePermissionControl(changed(native, "fallback", { ...native.fallback, model: "other" })), "INVALID_LITERAL"));
  test("requires installed-only fallback", () => expectCode(() => parseNativePermissionControl(changed(native, "fallback", { ...native.fallback, installedOnly: false })), "INVALID_LITERAL"));
  test("rejects wrong ABI and plugin identity", () => {
    expectCode(() => parseNativePermissionControl(changed(native, "bridgeAbi", "permission-control/v2")), "INVALID_LITERAL");
    expectCode(() => parseNativePermissionControl(changed(native, "pluginId", "other-plugin")), "INVALID_LITERAL");
  });
  test("rejects malformed and uppercase digests", () => {
    expectCode(() => parseNativePermissionControl(changed(native, "pluginDigest", "1".repeat(63))), "INVALID_SHA256");
    expectCode(() => parseNativePermissionControl(changed(native, "policyVersion", "A".repeat(64))), "INVALID_SHA256");
    expectCode(() => parseNativePermissionControl(changed(native, "policyVersion", null)), "INVALID_SHA256");
  });
  test("rejects a trailing newline on each native digest", () => {
    expectCode(() => parseNativePermissionControl(changed(native, "pluginDigest", `${DIGEST_A}\n`)), "INVALID_SHA256");
    expectCode(() => parseNativePermissionControl(changed(native, "policyVersion", `${DIGEST_B}\n`)), "INVALID_SHA256");
  });
  test("rejects empty or newline runtime identity", () => {
    expectCode(() => parseNativePermissionControl(changed(native, "runtimeIdentity", "")), "INVALID_STRING");
    expectCode(() => parseNativePermissionControl(changed(native, "runtimeIdentity", "asset\nother")), "INVALID_STRING");
    expectCode(() => parseNativePermissionControl(changed(native, "runtimeIdentity", "asset\u0007other")), "INVALID_STRING");
  });
});

describe("PluginDeliveryIdentity", () => {
  test("accepts every load state", () => {
    for (const load_state of ["verified", "missing", "damaged", "identity-mismatch", "not-loaded", "unhealthy"]) {
      expect(parsePluginDeliveryIdentity({ ...delivery, load_state }).load_state).toBe(load_state);
    }
  });

  for (const key of ["plugin_id", "plugin_tree_digest", "manifest_path", "runtime_variant", "runtime_identity", "bridge_abi", "load_state"]) {
    test(`rejects missing ${key}`, () => expectCode(() => parsePluginDeliveryIdentity(missing(delivery, key)), "MISSING_FIELD"));
  }

  test("rejects null and unknown fields", () => {
    expectCode(() => parsePluginDeliveryIdentity(null), "INVALID_OBJECT");
    expectCode(() => parsePluginDeliveryIdentity({ ...delivery, extra: true }), "UNKNOWN_FIELD");
  });
  test("does not echo an unknown field name", () => {
    expectUnknownKeyRedacted(
      () => parsePluginDeliveryIdentity({ ...delivery, "secret-command-sentinel": true }),
      "PluginDeliveryIdentity",
    );
  });
  test("rejects identity literal mismatches", () => {
    expectCode(() => parsePluginDeliveryIdentity(changed(delivery, "plugin_id", "other")), "INVALID_LITERAL");
    expectCode(() => parsePluginDeliveryIdentity(changed(delivery, "manifest_path", "locks/other.json")), "INVALID_LITERAL");
    expectCode(() => parsePluginDeliveryIdentity(changed(delivery, "runtime_variant", "official")), "INVALID_LITERAL");
    expectCode(() => parsePluginDeliveryIdentity(changed(delivery, "bridge_abi", "permission-control/v2")), "INVALID_LITERAL");
  });
  test("rejects malformed tree digest including trailing newline", () => {
    expectCode(() => parsePluginDeliveryIdentity(changed(delivery, "plugin_tree_digest", "1".repeat(63))), "INVALID_SHA256");
    expectCode(() => parsePluginDeliveryIdentity(changed(delivery, "plugin_tree_digest", `${DIGEST_A}\n`)), "INVALID_SHA256");
  });
  test("rejects invalid load state", () => expectCode(() => parsePluginDeliveryIdentity(changed(delivery, "load_state", "loaded")), "INVALID_ENUM"));
  test("rejects null load state", () => expectCode(() => parsePluginDeliveryIdentity(changed(delivery, "load_state", null)), "INVALID_ENUM"));
  test("rejects empty and newline runtime identity", () => {
    expectCode(() => parsePluginDeliveryIdentity(changed(delivery, "runtime_identity", "")), "INVALID_STRING");
    expectCode(() => parsePluginDeliveryIdentity(changed(delivery, "runtime_identity", "asset\nother")), "INVALID_STRING");
  });
});
