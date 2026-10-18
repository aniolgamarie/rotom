import { existsSync } from "node:fs";
import path from "node:path";
import { randomUUID } from "node:crypto";

export const name = "rotom-ssh-subscription-auth";
export const inject = ["llm", "credentials"];

export function validateProviders(config) {
  if (!config || Object.keys(config).some(key => key !== "providers")
      || !Array.isArray(config.providers) || config.providers.length === 0
      || config.providers.some(provider => !["codex", "cursor"].includes(provider))
      || new Set(config.providers).size !== config.providers.length) {
    throw new Error("Subscription providers must be a non-empty unique subset of codex and cursor.");
  }
  return [...config.providers];
}

export function currentHome(env = process.env) {
  if (!env.DSH_HOME || !path.isAbsolute(env.DSH_HOME)) {
    throw new Error("An absolute DSH_HOME is required for subscription authentication.");
  }
  return env.DSH_HOME;
}

export async function loadDependencies(providers) {
  const dependencies = {};
  if (providers.includes("codex")) Object.assign(dependencies,
    await import("@deepseek-harness-tui/dsh-tui/oauth"));
  if (providers.includes("cursor")) {
    Object.assign(dependencies, await import("dsh-cursor-subscription"));
    Object.assign(dependencies, await import("rotom-dsh-cursor-terminal"));
  }
  return dependencies;
}

// 只允许本 profile 的官方文件来源；不继承进程或项目的同名账号。
export function fileCredentials(credentials) {
  return {
    resolve: async ref => {
      const hit = await credentials.resolve(ref);
      return hit?.source === "file" ? hit : undefined;
    },
    set: (...args) => credentials.set(...args),
    unset: (...args) => credentials.unset(...args),
  };
}

export async function createRuntime(ctx, config, { dependencies, env = process.env, ask } = {}) {
  const providers = validateProviders(config);
  const home = currentHome(env);
  const deps = dependencies ?? await loadDependencies(providers);
  const routes = new Map();
  if (providers.includes("codex")) {
    const profile = deps.buildOAuthProfile("openai-codex");
    profile.retryPolicy = { ...profile.retryPolicy, maxRetries: 0, retryableCodes: [] };
    const profiles = new Map([["openai-codex", profile]]);
    const store = new deps.CredentialFile(path.join(home, "dsh-auth", "credentials.json"));
    const adapter = new deps.CredentialGatedAdapter({ profiles: () => profiles,
      resolveApiKey: async () => undefined,
      auth: { credentials: store, authContext: {
        env: async key => env[key], fileExists: async file => existsSync(file),
      } },
      resolveAttachments: () => ctx.get("attachments"),
    }, async provider => (await store.read(provider)) !== undefined);
    const api = deps.createDshAuthApi({ profiles, store, resolveAsk: () => ask });
    routes.set("codex", { provider: "openai-codex", adapter, api, store, profile });
  }
  if (providers.includes("cursor")) {
    const store = new deps.CursorCredentialStore(fileCredentials(ctx.get("credentials")), deps.CREDENTIAL_REF);
    const auth = new deps.CursorAuthService(store);
    const loginSessionId = randomUUID();
    const coordinator = new deps.CursorLoginCoordinator(auth, { createId: () => loginSessionId });
    const adapter = new deps.TerminalCursorAdapter({ auth, retryCount: 0, fallbackModels: [],
      resolveAttachments: () => ctx.get("attachments"),
    });
    routes.set("cursor", { provider: "cursor-subscription", adapter, auth, coordinator, loginSessionId });
  }
  return { routes, async dispose() {
    for (const route of routes.values()) route.adapter.cancelRequests?.();
  } };
}

export async function apply(ctx, config) {
  const runtime = await createRuntime(ctx, config);
  ctx.effect(function* () {
    yield () => runtime.dispose();
    for (const route of runtime.routes.values()) {
      yield ctx.get("llm").registerAdapter([route.provider], route.adapter);
    }
  });
}
