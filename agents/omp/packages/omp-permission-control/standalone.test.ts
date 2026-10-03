import { describe, expect, test } from "bun:test";
import { createStandalonePlugin, type StandaloneConfig, validateStandaloneConfig } from "./standalone";
import type { NativeBashRuntime, NativeSettingsSnapshot } from "./native-bash";
import { parseStandaloneReview, reviewCommand } from "./standalone-reviewer";
import { parseGenericCommands } from "./standalone-shell-analysis";

const digest = "a".repeat(64);
const baseConfig: StandaloneConfig = {
  schemaVersion: 2,
  defaultMode: "smart",
  reviewer: "session",
  pluginId: "omp-permission-control",
  pluginDigest: digest,
  policyVersion: digest,
  nativePatterns: [],
};

function model(provider = "primary", id = "reviewer") {
  return { provider, id, api: "openai-completions", baseUrl: "https://invalid.test/v1",
    requestModelId: undefined };
}

async function fakeHost(options: {
  config?: StandaloneConfig;
  response?: object | Error;
  fetchImpl?: (input: string, init: RequestInit) => Promise<Response>;
  currentModel?: ReturnType<typeof model>;
  select?: string | undefined;
  hasUI?: boolean;
  messages?: unknown[];
  loadingActionsThrow?: boolean;
  nativeRuntime?: any;
  nativeLoadError?: boolean;
  invokeImpl?: (...args: any[]) => Promise<any>;
} = {}) {
  const tools = new Map<string, any>();
  const commands = new Map<string, any>();
  const events = new Map<string, any>();
  const execCalls: any[] = [];
  const fetchCalls: any[] = [];
  const selectCalls: any[] = [];
  const notices: string[] = [];
  const invokeCalls: any[] = [];
  let current = options.currentModel ?? model();
  let loading = true;
  const branch = options.messages ?? [{ type: "message", message: { role: "user", content: "Run ls -la", timestamp: 1 } }];
  const host: any = {
    typebox: { Type: {
      String: (value?: unknown) => ({ type: "string", ...value as object }),
      Number: (value?: unknown) => ({ type: "number", ...value as object }),
      Optional: (value: unknown) => value,
      Object: (properties: unknown, extra: unknown) => ({ properties, ...extra as object }),
    } },
    getAllTools: () => {
      if (loading && options.loadingActionsThrow) throw new Error("runtime not initialized");
      return [...tools.values()];
    },
    getActiveTools: () => {
      if (loading && options.loadingActionsThrow) throw new Error("runtime not initialized");
      return ["bash", "read"];
    },
    setActiveTools: async (names: string[]) => { host.active = names; },
    registerTool: (tool: any) => tools.set(tool.name, tool),
    registerCommand: (name: string, command: any) => commands.set(name, command),
    on: (name: string, handler: any) => events.set(name, handler),
    exec: async (...args: any[]) => { execCalls.push(args); return { stdout: "ok", stderr: "", code: 0, killed: false }; },
  };
  await createStandalonePlugin({
    loadConfig: async () => options.config ?? baseConfig,
    fetch: (async (input: string, init: RequestInit) => {
      fetchCalls.push([input, init]);
      if (options.fetchImpl) return options.fetchImpl(input, init);
      if (options.response instanceof Error) throw options.response;
      return new Response(JSON.stringify(options.response ?? {
        choices: [{ message: { content: JSON.stringify({ decision: "allow", risk: "low",
          authorization: "sufficient", reasonCode: "LOW_RISK_AUTHORIZED" }) } }],
      }), { status: 200, headers: { "content-type": "application/json" } });
    }) as typeof fetch,
    loadNativeRuntime: options.nativeLoadError ? async () => { throw new Error("fixture load failure"); } :
      options.nativeRuntime ? async () => options.nativeRuntime : undefined,
  })(host);
  loading = false;
  const ctx: any = {
    hasUI: options.hasUI ?? true,
    cwd: "/repo",
    ui: { select: async (...args: any[]) => { selectCalls.push(args); return options.select; },
      notify: (message: string) => notices.push(message) },
    models: {
      current: () => current,
      resolve: (spec: string) => spec === `${current.provider}/${current.id}` ? current :
        spec === "remote/fallback" ? model("remote", "fallback") : undefined,
    },
    modelRegistry: { getApiKey: async () => "test-key" },
    sessionManager: { getBranch: () => branch, getSessionId: () => "session-1" },
    invokeTool: async (...args: any[]) => {
      invokeCalls.push(args);
      if (options.invokeImpl) return options.invokeImpl(...args);
      return { content: [{ type: "text", text: "native-ok" }], details: { native: true } };
    },
  };
  return { host, ctx, tools, commands, events, execCalls, fetchCalls, selectCalls, notices, invokeCalls,
    setCurrent: (value: any) => { current = value; } };
}

async function ready(harness: Awaited<ReturnType<typeof fakeHost>>) {
  await harness.events.get("session_start")({}, harness.ctx);
  return harness.tools.get("permission_bash");
}

function fakeNativeRuntime(initial: Partial<NativeSettingsSnapshot> = {}) {
  const settings = {};
  let fingerprint = initial.fingerprint ?? "settings-1";
  let decision = initial.decision ?? "allow";
  let reasonCode = initial.reasonCode ?? "NATIVE_ALLOW";
  let recheckWait: Promise<void> | undefined;
  const snapshot = (): NativeSettingsSnapshot => ({ settings, fingerprint, decision, reasonCode,
    reviewContext: { sameSettingsInstance: true, nativeDecision: decision, shellContext: "standard" } });
  const runtime: NativeBashRuntime = {
    capture: async () => snapshot(),
    recheck: async () => { await recheckWait; return snapshot(); },
  };
  return { runtime,
    setFingerprint: (value: string) => { fingerprint = value; },
    setDecision: (value: NativeSettingsSnapshot["decision"], reason: NativeSettingsSnapshot["reasonCode"]) => {
      decision = value; reasonCode = reason;
    },
    setRecheckWait: (value: Promise<void> | undefined) => { recheckWait = value; },
  };
}

async function nativeReady(harness: Awaited<ReturnType<typeof fakeHost>>) {
  await ready(harness);
  return { tool: harness.tools.get("bash"), hook: harness.events.get("tool_call") };
}

describe("standalone shell analysis", () => {
  test("parses simple and compound commands without splitting quotes", () => {
    expect(parseGenericCommands("printf '%s; x' ok && ls -la")).toEqual({ status: "complete", commands: [
      { connector: "start", argv: ["printf", "%s; x", "ok"] },
      { connector: "&&", argv: ["ls", "-la"] },
    ] });
  });
  test("fails closed on dynamic syntax", () => {
    expect(parseGenericCommands("echo $(id)").status).toBe("unsupported");
    expect(parseGenericCommands("cat *.env").status).toBe("unsupported");
  });
});

describe("standalone reviewer", () => {
  test("strictly rejects extra fields and invalid allow", () => {
    expect(parseStandaloneReview('{"decision":"allow","risk":"low","authorization":"sufficient","reasonCode":"LOW_RISK_AUTHORIZED","extra":1}')).toBeUndefined();
    expect(parseStandaloneReview('{"decision":"allow","risk":"high","authorization":"sufficient","reasonCode":"LOW_RISK_AUTHORIZED"}')).toBeUndefined();
  });
  test("explicit reviewer wins over session and transport failure falls back once", async () => {
    const calls: string[] = [];
    const result = await reviewCommand({ command: "ls", cwd: "/repo", userMessages: ["list"],
      reviewer: { provider: "explicit", model: "reviewer" }, remoteFallback: { provider: "remote", model: "fallback" } }, {
      current: () => model("session", "model"),
      resolve: spec => spec === "explicit/reviewer" ? model("explicit", "reviewer") : model("remote", "fallback"),
      getApiKey: async () => "key",
      fetch: async input => {
        calls.push(input);
        if (calls.length === 1) return new Response("bad", { status: 503 });
        return new Response(JSON.stringify({ choices: [{ message: { content:
          '{"decision":"deny","risk":"high","authorization":"insufficient","reasonCode":"HIGH_RISK"}' } }] }), { status: 200 });
      },
    });
    expect(result.source).toBe("remote");
    expect(result.review?.decision).toBe("deny");
    expect(calls).toHaveLength(2);
  });
  test("valid ask terminates without remote", async () => {
    let calls = 0;
    const result = await reviewCommand({ command: "ls", cwd: "/repo", userMessages: ["maybe"], reviewer: "session",
      remoteFallback: { provider: "remote", model: "fallback" } }, {
      current: () => model(), resolve: () => model("remote", "fallback"), getApiKey: async () => "key",
      fetch: async () => { calls++; return new Response(JSON.stringify({ choices: [{ message: { content:
        '{"decision":"ask","risk":"unknown","authorization":"unknown","reasonCode":"USER_CONFIRMATION_REQUIRED"}' } }] }), { status: 200 }); },
    });
    expect(result.review?.decision).toBe("ask");
    expect(calls).toBe(1);
  });
  test("valid deny terminates without remote", async () => {
    let calls = 0;
    const result = await reviewCommand({ command: "rm x", cwd: "/repo", userMessages: ["do not"], reviewer: "session",
      remoteFallback: { provider: "remote", model: "fallback" } }, {
      current: () => model(), resolve: () => model("remote", "fallback"), getApiKey: async () => "key",
      fetch: async () => { calls++; return new Response(JSON.stringify({ choices: [{ message: { content:
        '{"decision":"deny","risk":"high","authorization":"insufficient","reasonCode":"HIGH_RISK"}' } }] }), { status: 200 }); },
    });
    expect(result.review?.decision).toBe("deny");
    expect(calls).toBe(1);
  });
  test("primary timeout leaves budget for remote", async () => {
    let calls = 0;
    const result = await reviewCommand({ command: "ls", cwd: "/repo", userMessages: ["list"], reviewer: "session",
      remoteFallback: { provider: "remote", model: "fallback" } }, {
      deadlines: { totalMs: 100, primaryMs: 5 }, current: () => model(),
      resolve: () => model("remote", "fallback"), getApiKey: async () => "key",
      fetch: async () => {
        calls++;
        if (calls === 1) return new Promise<Response>(() => {});
        return new Response(JSON.stringify({ choices: [{ message: { content:
          '{"decision":"allow","risk":"low","authorization":"sufficient","reasonCode":"LOW_RISK_AUTHORIZED"}' } }] }), { status: 200 });
      },
    });
    expect(result.source).toBe("remote");
    expect(calls).toBe(2);
  });
  test("duplicate JSON keys and tool calls are invalid", async () => {
    for (const body of [
      '{"choices":[{"message":{"content":"{\\"decision\\":\\"deny\\",\\"decision\\":\\"allow\\",\\"risk\\":\\"low\\",\\"authorization\\":\\"sufficient\\",\\"reasonCode\\":\\"LOW_RISK_AUTHORIZED\\"}"}}]}',
      JSON.stringify({ choices: [{ message: { content: "{}", tool_calls: [{ id: "x" }] } }] }),
    ]) {
      const result = await reviewCommand({ command: "ls", cwd: "/repo", userMessages: ["list"], reviewer: "session" }, {
        current: () => model(), resolve: () => model(), getApiKey: async () => "key",
        fetch: async () => new Response(body, { status: 200 }),
      });
      expect(result.status).toBe("failure");
    }
  });
  test("a cancelled API key lookup cannot start fetch", async () => {
    const controller = new AbortController();
    let fetched = false;
    const result = await reviewCommand({ command: "ls", cwd: "/repo", userMessages: ["list"], reviewer: "session" }, {
      current: () => model(), resolve: () => model(),
      getApiKey: async () => { controller.abort(); return "late-key"; },
      fetch: async () => { fetched = true; throw new Error("must not fetch"); },
    }, controller.signal);
    expect(result.status).toBe("failure");
    expect(fetched).toBe(false);
  });
});

describe("standalone plugin", () => {
  test("loads by registration only before runtime actions are initialized", async () => {
const h = await fakeHost({ loadingActionsThrow: true });
    expect(h.tools.has("permission_bash")).toBe(true);
    expect(h.commands.has("permission-control")).toBe(true);
    expect(await ready(h)).toBeDefined();
  });
  test("ls -la reaches model and backend once with unchanged arguments", async () => {
const h = await fakeHost();
    const tool = await ready(h);
    const result = await tool.execute("call", { command: "ls -la", cwd: "/work", timeout: 2 }, undefined, undefined, h.ctx);
    expect(result.isError).toBeUndefined();
    expect(h.fetchCalls).toHaveLength(1);
    expect(h.execCalls).toEqual([["bash", ["--noprofile", "--norc", "-c", "ls -la"],
      { cwd: "/work", signal: expect.any(AbortSignal), timeout: 2000 }]]);
    expect(h.host.active).toEqual(["read", "permission_bash"]);
  });
  test("manual mode never calls model and exact Approve is required", async () => {
const h = await fakeHost({ config: { ...baseConfig, defaultMode: "manual" }, select: "Approve" });
    const result = await (await ready(h)).execute("call", { command: "echo ok" }, undefined, undefined, h.ctx);
    expect(result.isError).toBeUndefined();
    expect(h.fetchCalls).toHaveLength(0);
    expect(h.execCalls).toHaveLength(1);
    expect(h.selectCalls[0][0]).toContain('cwd: "/repo"');
    expect(h.selectCalls[0][0]).toContain('command: "echo ok"');
  });
  test("human prompt redacts credential values while showing the action", async () => {
const h = await fakeHost({ config: { ...baseConfig, defaultMode: "manual" }, select: "Deny" });
    await (await ready(h)).execute("call", { command: "API_KEY=sk-12345678901234567890 env", cwd: "/work" },
      undefined, undefined, h.ctx);
    const title = h.selectCalls[0][0];
    expect(title).toContain('cwd: "/work"');
    expect(title).toContain('command: "API_KEY=[REDACTED] env"');
    expect(title).not.toContain("sk-12345678901234567890");
  });
  test("human prompt renders control characters as explicit escapes", async () => {
    const h = await fakeHost({ config: { ...baseConfig, defaultMode: "manual" }, select: "Deny" });
    await (await ready(h)).execute("call", { command: "printf '\u001b[31m'\rnext", cwd: "/tmp\u001b]0;title\u0007" },
      undefined, undefined, h.ctx);
    const title = h.selectCalls[0][0];
    expect(title).toContain('cwd: "/tmp\\u001b]0;title\\u0007"');
    expect(title).toContain('command: "printf \'\\u001b[31m\'\\rnext"');
    expect(title).not.toContain("\u001b");
    expect(title).not.toContain("\r");
  });
  test("native deny and prompt cannot be overridden by model", async () => {
const deny = await fakeHost({ config: { ...baseConfig, nativePatterns: [{ match: "rm *", approval: "deny" }] } });
    expect((await (await ready(deny)).execute("call", { command: "rm file" }, undefined, undefined, deny.ctx)).isError).toBe(true);
    expect(deny.fetchCalls).toHaveLength(0);
const prompt = await fakeHost({ config: { ...baseConfig, nativePatterns: [{ match: "git *", approval: "prompt" }] }, select: "Deny" });
    expect((await (await ready(prompt)).execute("call", { command: "git status" }, undefined, undefined, prompt.ctx)).isError).toBe(true);
    expect(prompt.fetchCalls).toHaveLength(0);
  });
  test("control syntax cannot bypass a native deny pattern", async () => {
const h = await fakeHost({ config: { ...baseConfig, nativePatterns: [{ match: "rm *", approval: "deny" }] }, select: "Deny" });
    const result = await (await ready(h)).execute("call", { command: "if rm -rf /; then ls; fi" },
      undefined, undefined, h.ctx);
    expect(result.isError).toBe(true);
    expect(h.fetchCalls).toHaveLength(0);
    expect(h.selectCalls).toHaveLength(1);
  });
  test("model failure uses human and headless blocks", async () => {
const ui = await fakeHost({ response: new Error("offline"), select: "Approve" });
    expect((await (await ready(ui)).execute("call", { command: "ls" }, undefined, undefined, ui.ctx)).isError).toBeUndefined();
const headless = await fakeHost({ response: new Error("offline"), hasUI: false });
    expect((await (await ready(headless)).execute("call", { command: "ls" }, undefined, undefined, headless.ctx)).isError).toBe(true);
    expect(headless.execCalls).toHaveLength(0);
  });
  test("missing user provenance and secret-like text do not reach model", async () => {
const noUser = await fakeHost({ messages: [] });
    await (await ready(noUser)).execute("call", { command: "ls" }, undefined, undefined, noUser.ctx);
    expect(noUser.fetchCalls).toHaveLength(0);
const secret = await fakeHost({ messages: [{ type: "message", message: { role: "user", content: "API_KEY=sk-12345678901234567890", timestamp: 1 } }] });
    await (await ready(secret)).execute("call", { command: "env" }, undefined, undefined, secret.ctx);
    expect(secret.fetchCalls).toHaveLength(0);
  });
  test("model or generation change during review blocks execution", async () => {
    const h = await fakeHost();
    const tool = await ready(h);
    h.ctx.models.current = (() => {
      let calls = 0;
      return () => calls++ === 0 ? model() : model("changed", "model");
    })();
    const result = await tool.execute("call", { command: "ls" }, undefined, undefined, h.ctx);
    expect(result.isError).toBe(true);
    expect(h.execCalls).toHaveLength(0);
  });
  test("mode change cancels a pending review", async () => {
    let release!: () => void;
    const wait = new Promise<void>(resolve => { release = resolve; });
const h = await fakeHost({ fetchImpl: async () => {
      await wait;
      return new Response(JSON.stringify({ choices: [{ message: { content:
        '{"decision":"allow","risk":"low","authorization":"sufficient","reasonCode":"LOW_RISK_AUTHORIZED"}' } }] }), { status: 200 });
    } });
    const execution = (await ready(h)).execute("call", { command: "ls" }, undefined, undefined, h.ctx);
    await Promise.resolve();
    await h.commands.get("permission-control").handler("manual", h.ctx);
    release();
    expect((await execution).isError).toBe(true);
    expect(h.execCalls).toHaveLength(0);
  });
  test("mode change after raw queue acquisition releases the next request", async () => {
    const h = await fakeHost();
    const tool = await ready(h);
    const old = tool.execute("old", { command: "echo old" }, undefined, undefined, h.ctx);
    // 精确停在 acquire 返回后、execute 恢复前，验证过期分支释放队列。
    await Promise.resolve();
    await Promise.resolve();
    await h.commands.get("permission-control").handler("manual", h.ctx);
    await h.commands.get("permission-control").handler("smart", h.ctx);
    expect((await old).isError).toBe(true);
    expect(h.fetchCalls).toHaveLength(0);
    expect(h.execCalls).toHaveLength(0);
    const current = await tool.execute("new", { command: "echo new" }, undefined, undefined, h.ctx);
    expect(current.isError).toBeUndefined();
    expect(h.fetchCalls).toHaveLength(1);
    expect(h.execCalls).toHaveLength(1);
    expect(h.execCalls[0][1].at(-1)).toBe("echo new");
  }, 1000);
  test("preserves nonzero backend result as an error", async () => {
    const h = await fakeHost();
    h.host.exec = async (...args: any[]) => {
      h.execCalls.push(args);
      return { stdout: "", stderr: "failed", code: 7, killed: false };
    };
    const result = await (await ready(h)).execute("call", { command: "false" }, undefined, undefined, h.ctx);
    expect(result.isError).toBe(true);
    expect(result.details.code).toBe(7);
    expect(result.content[0].text).toContain("failed");
  });
  test("ask records the human approval chain and status layer identity", async () => {
const h = await fakeHost({ select: "Approve", response: { choices: [{ message: { content:
      '{"decision":"ask","risk":"unknown","authorization":"unknown","reasonCode":"USER_CONFIRMATION_REQUIRED"}' } }] } });
    await (await ready(h)).execute("call", { command: "ls" }, undefined, undefined, h.ctx);
    await h.commands.get("permission-control").handler("explain", h.ctx);
    const explain = JSON.parse(h.notices.at(-1)!);
    expect(explain.source).toBe("human");
    expect(explain.chain).toEqual(["primary", "human"]);
    await h.commands.get("permission-control").handler("status", h.ctx);
    const status = JSON.parse(h.notices.at(-1)!);
    expect(status.primary).toMatchObject({ configured: "session", actualModel: "primary/reviewer", calls: 1, health: "ready" });
    expect(status.human).toMatchObject({ calls: 1, health: "approved" });
    expect(status.fallback).toBe("disabled");
  });
  test("two valid concurrent requests are serialized and both execute", async () => {
    let release!: () => void;
    const wait = new Promise<void>(resolve => { release = resolve; });
    let calls = 0;
    const h = await fakeHost({ fetchImpl: async () => {
      calls++;
      if (calls === 1) await wait;
      return new Response(JSON.stringify({ choices: [{ message: { content:
        '{"decision":"allow","risk":"low","authorization":"sufficient","reasonCode":"LOW_RISK_AUTHORIZED"}' } }] }), { status: 200 });
    } });
    const tool = await ready(h);
    const old = tool.execute("old", { command: "echo old" }, undefined, undefined, h.ctx);
    await Promise.resolve();
    const current = tool.execute("new", { command: "echo new" }, undefined, undefined, h.ctx);
    release();
    expect((await old).isError).toBeUndefined();
    expect((await current).isError).toBeUndefined();
    expect(h.execCalls).toHaveLength(2);
    expect(h.execCalls.map(call => call[1].at(-1))).toEqual(["echo old", "echo new"]);
  });
  test("config rejects unknown fields and command state resets", async () => {
    expect(() => validateStandaloneConfig({ ...baseConfig, unknown: true })).toThrow();
    const h = await fakeHost();
    await ready(h);
    await h.commands.get("permission-control").handler("manual", h.ctx);
    await h.events.get("session_switch")({}, h.ctx);
    const notices: string[] = [];
    h.ctx.ui.notify = (message: string) => notices.push(message);
    await h.commands.get("permission-control").handler("status", h.ctx);
    expect(JSON.parse(notices[0]).mode).toBe("smart");
  });
});

describe("native bash delegation", () => {
  const nativeConfig = { ...baseConfig, nativeBash: true };
  const params = { command: "ls -la", cwd: "work", timeout: 2 };
  const event = (id: string, input: unknown = params, toolName = "bash") =>
    ({ type: "tool_call", toolName, toolCallId: id, input });

  test("mode change after native queue acquisition releases the next request", async () => {
    const h = await fakeHost({ config: nativeConfig, nativeRuntime: fakeNativeRuntime().runtime });
    const { tool, hook } = await nativeReady(h);
    const old = hook(event("old"), h.ctx);
    // 精确停在 acquire 返回后、hook 恢复前，验证过期分支释放队列。
    await Promise.resolve();
    await Promise.resolve();
    await h.commands.get("permission-control").handler("manual", h.ctx);
    await h.commands.get("permission-control").handler("smart", h.ctx);
    expect((await old).block).toBe(true);
    expect(h.fetchCalls).toHaveLength(0);
    expect(h.invokeCalls).toHaveLength(0);
    expect(await hook(event("new"), h.ctx)).toBeUndefined();
    expect((await tool.execute("new", params, undefined, undefined, h.ctx)).isError).toBeUndefined();
    expect(h.fetchCalls).toHaveLength(1);
    expect(h.invokeCalls).toHaveLength(1);
    expect(h.execCalls).toHaveLength(0);
  }, 1000);

  test("an approved call delegates once with unchanged parameters, signal, updates, and result", async () => {
    const native = fakeNativeRuntime();
    const h = await fakeHost({ config: nativeConfig, nativeRuntime: native.runtime });
    const { tool, hook } = await nativeReady(h);
    expect(h.host.active).toEqual(["bash", "read", "permission_bash"]);
    expect(await hook(event("native-1"), h.ctx)).toBeUndefined();
    const controller = new AbortController();
    const update = () => undefined;
    const result = await tool.execute("native-1", params, controller.signal, update, h.ctx);
    expect(result.details).toEqual({ native: true });
    expect(h.invokeCalls).toHaveLength(1);
    expect(h.invokeCalls[0][0]).toBe(params);
    expect(h.invokeCalls[0][1]).toEqual({ signal: controller.signal, onUpdate: update });
    expect(h.execCalls).toHaveLength(0);
    const request = JSON.parse((h.fetchCalls[0][1] as RequestInit).body as string);
    expect(request.messages.at(-1).content).toContain('"baseCwd":"/repo"');
    expect(request.messages.at(-1).content).toContain('"cwd":"work"');
    await h.commands.get("permission-control").handler("status", h.ctx);
    expect(JSON.parse(h.notices.at(-1)!).coverage).toBe("ready");
  });

  test("native deny and prompt stop before the reviewer and delegate", async () => {
    const denyRuntime = fakeNativeRuntime({ decision: "deny", reasonCode: "NATIVE_DENY" });
    const deny = await fakeHost({ config: nativeConfig, nativeRuntime: denyRuntime.runtime });
    const denyEntry = await nativeReady(deny);
    expect((await denyEntry.hook(event("deny"), deny.ctx)).block).toBe(true);
    expect(deny.fetchCalls).toHaveLength(0);
    expect(deny.invokeCalls).toHaveLength(0);

    const promptRuntime = fakeNativeRuntime({ decision: "prompt", reasonCode: "NATIVE_PROMPT" });
    const prompt = await fakeHost({ config: nativeConfig, nativeRuntime: promptRuntime.runtime,
      select: "Deny" });
    const promptEntry = await nativeReady(prompt);
    expect((await promptEntry.hook(event("prompt"), prompt.ctx)).block).toBe(true);
    expect(prompt.fetchCalls).toHaveLength(0);
    expect(prompt.invokeCalls).toHaveLength(0);
  });

  test("headless prompt, unknown fields, and duplicate ids fail closed", async () => {
    const promptRuntime = fakeNativeRuntime({ decision: "prompt", reasonCode: "NATIVE_PROMPT" });
    const headless = await fakeHost({ config: nativeConfig, nativeRuntime: promptRuntime.runtime, hasUI: false });
    const first = await nativeReady(headless);
    expect((await first.hook(event("headless"), headless.ctx)).block).toBe(true);

    const native = fakeNativeRuntime();
    const h = await fakeHost({ config: nativeConfig, nativeRuntime: native.runtime });
    const { tool, hook } = await nativeReady(h);
    expect(tool.parameters.additionalProperties).toBe(true);
    expect(h.tools.get("permission_bash").parameters.additionalProperties).toBe(true);
    for (const [id, extra] of [["async", { async: true }], ["service", { service: "start" }],
      ["pty", { pty: true }]] as const) {
      expect((await hook(event(id, { ...params, ...extra }), h.ctx)).block).toBe(true);
    }
    expect(await hook(event("duplicate"), h.ctx)).toBeUndefined();
    expect((await hook(event("duplicate"), h.ctx)).block).toBe(true);
    expect(h.invokeCalls).toHaveLength(0);
  });

  test("missing, changed, consumed, and stale tickets cannot delegate", async () => {
    const native = fakeNativeRuntime();
    const h = await fakeHost({ config: nativeConfig, nativeRuntime: native.runtime });
    const { tool, hook } = await nativeReady(h);
    expect((await tool.execute("missing", params, undefined, undefined, h.ctx)).isError).toBe(true);

    expect(await hook(event("changed"), h.ctx)).toBeUndefined();
    expect((await tool.execute("changed", { ...params, timeout: 3 }, undefined, undefined, h.ctx)).isError).toBe(true);

    expect(await hook(event("stale"), h.ctx)).toBeUndefined();
    native.setFingerprint("settings-2");
    expect((await tool.execute("stale", params, undefined, undefined, h.ctx)).isError).toBe(true);

    native.setFingerprint("settings-3");
    expect(await hook(event("once"), h.ctx)).toBeUndefined();
    expect((await tool.execute("once", params, undefined, undefined, h.ctx)).isError).toBeUndefined();
    expect((await tool.execute("once", params, undefined, undefined, h.ctx)).isError).toBe(true);

    expect(await hook(event("model-change"), h.ctx)).toBeUndefined();
    h.setCurrent(model("changed", "model"));
    expect((await tool.execute("model-change", params, undefined, undefined, h.ctx)).isError).toBe(true);
    expect(h.invokeCalls).toHaveLength(1);
  });

  test("mode change and cancellation during the execute recheck stop delegation", async () => {
    const native = fakeNativeRuntime();
    const h = await fakeHost({ config: nativeConfig, nativeRuntime: native.runtime });
    const { tool, hook } = await nativeReady(h);
    expect(await hook(event("race"), h.ctx)).toBeUndefined();
    let release!: () => void;
    native.setRecheckWait(new Promise<void>(resolve => { release = resolve; }));
    const controller = new AbortController();
    const execution = tool.execute("race", params, controller.signal, undefined, h.ctx);
    await Promise.resolve();
    controller.abort();
    await h.commands.get("permission-control").handler("manual", h.ctx);
    release();
    expect((await execution).isError).toBe(true);
    expect(h.invokeCalls).toHaveLength(0);
  });

  test("a missing delegate blocks and a delegate error is preserved", async () => {
    const native = fakeNativeRuntime();
    const missing = await fakeHost({ config: nativeConfig, nativeRuntime: native.runtime });
    const missingEntry = await nativeReady(missing);
    expect(await missingEntry.hook(event("missing-delegate"), missing.ctx)).toBeUndefined();
    delete missing.ctx.invokeTool;
    expect((await missingEntry.tool.execute("missing-delegate", params, undefined, undefined, missing.ctx)).details)
      .toEqual({ reasonCode: "NATIVE_DELEGATE_UNAVAILABLE" });

    const failure = new Error("native fixture failure");
    const throwing = await fakeHost({ config: nativeConfig, nativeRuntime: fakeNativeRuntime().runtime,
      invokeImpl: async () => { throw failure; } });
    const throwingEntry = await nativeReady(throwing);
    expect(await throwingEntry.hook(event("throw"), throwing.ctx)).toBeUndefined();
    await expect(throwingEntry.tool.execute("throw", params, undefined, undefined, throwing.ctx)).rejects.toBe(failure);
  });

  test("raw entrypoint cannot escape a native deny", async () => {
    const native = fakeNativeRuntime({ decision: "deny", reasonCode: "NATIVE_DENY" });
    const h = await fakeHost({ config: nativeConfig, nativeRuntime: native.runtime });
    const { hook } = await nativeReady(h);
    expect(await hook(event("raw-deny", params, "permission_bash"), h.ctx)).toBeUndefined();
    const result = await h.tools.get("permission_bash").execute("raw-deny", params,
      undefined, undefined, h.ctx);
    expect(result.isError).toBe(true);
    expect(h.fetchCalls).toHaveLength(0);
    expect(h.execCalls).toHaveLength(0);
  });

  test("native runtime load failure never creates a delegation window", async () => {
    const h = await fakeHost({ config: nativeConfig, nativeLoadError: true });
    await h.events.get("session_start")({}, h.ctx);
    expect(h.tools.has("bash")).toBe(false);
    const result = await h.tools.get("permission_bash").execute("raw", params, undefined, undefined, h.ctx);
    expect(result.isError).toBe(true);
    expect(h.invokeCalls).toHaveLength(0);
    expect(h.execCalls).toHaveLength(0);
  });
});
