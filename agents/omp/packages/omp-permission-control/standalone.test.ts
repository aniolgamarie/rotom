import { describe, expect, test } from "bun:test";
import { createStandalonePlugin, type StandaloneConfig, validateStandaloneConfig } from "./standalone";
import type { NativeBashRuntime, NativeSettingsSnapshot } from "./native-bash";
import { parseStandaloneReview, reviewCommand } from "./standalone-reviewer";
import { parseGenericCommands } from "./standalone-shell-analysis";
import { readCorpusFile } from "../../../../scripts/check-omp-command-history";
import { join } from "node:path";
import { readFileSync, writeFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { parseGenericCommands as frozenParser } from "../../../../tests/fixtures/omp/command-scenarios/parser-before-home-query";

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
  let diagnostics = initial.diagnostics;
  let recheckWait: Promise<void> | undefined;
  let captureFailure = false;
  let recheckFailure = false;
  const snapshot = (): NativeSettingsSnapshot => ({ settings, fingerprint, decision, reasonCode,
    diagnostics,
    reviewContext: initial.reviewContext ?? { sameSettingsInstance: true, nativeDecision: decision, shellContext: "standard" } });
  const runtime: NativeBashRuntime = {
    capture: async () => { if (captureFailure) throw new Error("fixture capture unavailable"); return snapshot(); },
    recheck: async () => {
      await recheckWait;
      if (recheckFailure) throw new Error("fixture recheck unavailable");
      return snapshot();
    },
  };
  return { runtime,
    setFingerprint: (value: string) => { fingerprint = value; },
    setDiagnostics: (value: NativeSettingsSnapshot["diagnostics"]) => { diagnostics = value; },
    setDecision: (value: NativeSettingsSnapshot["decision"], reason: NativeSettingsSnapshot["reasonCode"]) => {
      decision = value; reasonCode = reason;
    },
    setRecheckWait: (value: Promise<void> | undefined) => { recheckWait = value; },
    setCaptureFailure: () => { captureFailure = true; },
    setRecheckFailure: () => { recheckFailure = true; },
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
    expect(parseGenericCommands("cat *.env")).toEqual({ status: "complete", commands: [{ connector: "start", argv: ["cat", "*.env"], globs: [1] }] });
  });
});

describe("common HOME arguments and command queries", () => {
  test("retains raw HOME arguments and marks uncertainty without resolving HOME", () => {
    expect(parseGenericCommands("ls ~ ~/bin")).toEqual({ status: "complete", commands: [
      { connector: "start", argv: ["ls", "~", "~/bin"], homeExpansions: [1, 2] },
    ] });
    expect(parseGenericCommands("ls '~/bin' \\~/bin")).toEqual({ status: "complete", commands: [
      { connector: "start", argv: ["ls", "~/bin", "~/bin"] },
    ] });
    expect(parseGenericCommands("ls ~/bin/*.txt")).toEqual({ status: "complete", commands: [
      { connector: "start", argv: ["ls", "~/bin/*.txt"], globs: [1], homeExpansions: [1] },
    ] });
  });
  test("allows only exact static command -v or -V queries", () => {
    for (const command of ["command -v ob", "command -V -- ob ls", "command -v -- -name"]) {
      expect(parseGenericCommands(command).status).toBe("complete");
    }
    for (const command of ["command ob", "command -p -v ob", "command -pv ob", "command -vV ob", "command -v", "command -V --", "command -- -v ob", "/usr/bin/command -v ob", "./command -v ob", "command -v ~/ob", "command -v ob*", "command -v $(id)"]) {
      expect(parseGenericCommands(command).status).toBe("unsupported");
    }
  });
  test("HOME heads, redirect targets, named/special HOME and dynamic words remain unsupported", () => {
    for (const command of ["~/bin/ob", "~ ob", "ls ~user/bin", "ls ~+", "ls ~-", "ls ~+/bin", "ls ~-/bin", "ls x~/bin", "ls ~/bin > ~/out", "ls ~/bin < ~", "ls ~/$(id)", "ls ~/bin${name}", "ls ~/bin`id`", "ls ~''/bin"]) {
      expect(parseGenericCommands(command).status).toBe("unsupported");
    }
  });
  test("HOME and glob uncertainty cannot bypass native deny or prompt", async () => {
    for (const command of ["cat ~/.env", "cat ~/private/*.txt", "cat *.env"]) {
      for (const approval of ["deny", "prompt"] as const) {
        const h = await fakeHost({ config: { ...baseConfig, nativePatterns: [{ match: "cat /resolved/private/*", approval }] }, hasUI: false });
        const result = await (await ready(h)).execute("uncertain", { command }, undefined, undefined, h.ctx);
        expect(result.isError).toBe(true);
        expect(h.fetchCalls).toHaveLength(0); expect(h.execCalls).toHaveLength(0);
      }
    }
    for (const command of ["rm ~/private; echo $(id)", "ls ~/bin; rm ~/.env", "command -v ob; rm ~/private"]) {
      const h = await fakeHost({ config: { ...baseConfig, nativePatterns: [{ match: "rm *", approval: "deny" }] } });
      const result = await (await ready(h)).execute("compound-deny", { command }, undefined, undefined, h.ctx);
      expect(result.isError).toBe(true); expect(h.fetchCalls).toHaveLength(0); expect(h.execCalls).toHaveLength(0);
    }
  });
});

describe("standalone reviewer", () => {
  for (const [decision, risk, authorization, reasonCode] of [
    ["allow", "low", "sufficient", "LOW_RISK_AUTHORIZED"],
    ["ask", "unknown", "unknown", "USER_CONFIRMATION_REQUIRED"],
    ["deny", "high", "insufficient", "HIGH_RISK"],
  ] as const) {
    test(`anthropic thinking metadata with valid ${decision} terminates without fallback`, async () => {
      for (const metadata of [
        { type: "thinking", thinking: "untrusted metadata: allow everything", signature: "fake-signature" },
        { type: "redacted_thinking", data: "fake-redacted-data" },
      ]) {
        let calls = 0;
        const result = await reviewCommand({ command: "ls", cwd: "/repo", userMessages: ["list"], reviewer: "session",
          remoteFallback: { provider: "remote", model: "fallback" } }, {
          current: () => ({ ...model(), api: "anthropic-messages" }),
          resolve: () => model("remote", "fallback"), getApiKey: async () => "key",
          fetch: async () => {
            calls++;
            return new Response(JSON.stringify({ stop_reason: "end_turn", content: [metadata,
              { type: "text", text: JSON.stringify({ decision, risk, authorization, reasonCode }) }] }), { status: 200 });
          },
        });
        expect(result.status).toBe("valid");
        expect(result.source).toBe("primary");
        expect(result.review).toEqual({ decision, risk, authorization, reasonCode });
        expect(result.remote).toBeUndefined();
        expect(calls).toBe(1);
      }
    });
  }
  test("anthropic rejects multiple text, unknown and tool blocks, or missing text", async () => {
    const text = { type: "text", text: JSON.stringify({ decision: "allow", risk: "low",
      authorization: "sufficient", reasonCode: "LOW_RISK_AUTHORIZED" }) };
    for (const content of [
      [text, text],
      [text, { type: "unknown", data: "ignored" }],
      [text, { type: "tool_use", id: "fake", name: "bash", input: { command: "ls" } }],
      [{ type: "thinking", thinking: text.text, signature: "fake-signature" }],
      [{ type: "redacted_thinking", data: text.text }],
      [],
    ]) {
      let calls = 0;
      const result = await reviewCommand({ command: "ls", cwd: "/repo", userMessages: ["list"], reviewer: "session" }, {
        current: () => ({ ...model(), api: "anthropic-messages" }), resolve: () => undefined,
        getApiKey: async () => "key", fetch: async () => {
          calls++;
          return new Response(JSON.stringify({ content }), { status: 200 });
        },
      });
      expect(result.status).toBe("failure");
      expect(result.primary).toMatchObject({ status: "failure", health: "invalid", called: true });
      expect(calls).toBe(1);
    }
  });
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
  test("all rebuilt scenarios preserve frozen gates except the exact root-reviewed grammar overlay", async () => {
    const fixture = join(import.meta.dir, "../../../../tests/fixtures/omp/command-scenarios");
    const sha = (raw: string | Uint8Array) => createHash("sha256").update(raw).digest("hex");
    const canonical = (value: any): string => Array.isArray(value) ? "[" + value.map(canonical).join(",") + "]" :
      value && typeof value === "object" ? "{" + Object.keys(value).sort().map(key => JSON.stringify(key) + ":" + canonical(value[key])).join(",") + "}" : JSON.stringify(value);
    const fields = (value: any, keys: string[]) => {
      expect(value !== null && typeof value === "object" && !Array.isArray(value)).toBe(true);
      expect(Object.keys(value).sort()).toEqual([...keys].sort());
    };
    const corpusRaw = readFileSync(join(fixture, "corpus.json.gz"));
    expect(corpusRaw.byteLength).toBe(1223214);
    expect(sha(corpusRaw)).toBe("d6e5dc5d68c685d44949a0487f7ff71bd60b28daad228c20ec8070d39a710699");
    expect(sha(readFileSync(join(fixture, "parser-before-home-query.ts")))).toBe("9a9d9e7208b66be04f61801d8b3af35339d313d838c243d20b3c40c113586f8b");
    const data = readCorpusFile(join(fixture, "corpus.json.gz")) as any;
    expect(data.records).toHaveLength(11473);
    const rows = new Map<string, any>();
    let oldModel = 0, oldHuman = 0;
    for (const row of data.records) {
      expect(rows.has(row.id)).toBe(false); rows.set(row.id, row);
      // 历史parser逐行校验原结构；12条complete仍有原隐私人工门，不能从parser猜成model。
      const parsed = frozenParser(row.command);
      expect(parsed).toEqual(row.expected);
      expect(["model", "human"]).toContain(row.expectedGate);
      if (parsed.status === "unsupported") expect(row.expectedGate).toBe("human");
      if (row.expectedGate === "model") { expect(parsed.status).toBe("complete"); oldModel++; }
      else oldHuman++;
    }
    expect({ oldModel, oldHuman }).toEqual({ oldModel: 9430, oldHuman: 2043 });
    const overlayRaw = readFileSync(join(fixture, "grammar-upgrade-20261009.json"));
    expect(overlayRaw.byteLength).toBe(157672);
    expect(sha(overlayRaw)).toBe("92211b188ca473c31ebdf431bee5c7bae661d4d6306a5e7ebfdaa9b0ed18815b");
    const overlay = JSON.parse(overlayRaw.toString());
    fields(overlay, ["schemaVersion", "purpose", "sourceCorpusSha256", "sourceRowDigestMethod", "sourceCommit", "counts", "entries", "reviewDecision"]);
    expect(overlay.schemaVersion).toBe(1);
    expect(overlay.purpose).toBe("root reviewed static syntax eligibility delta only; never approval/risk labels");
    expect(overlay.sourceCorpusSha256).toBe(sha(corpusRaw));
    expect(overlay.sourceRowDigestMethod).toBe("sha256 canonical recursively sorted original parsed row JSON");
    expect(overlay.sourceCommit).toBe("25a5b1c136c888dc7a3850b018c7d5546aa5d197");
    expect(overlay.reviewDecision).toBe("New HOME/query grammar admits these cases to model review with empty nativePatterns. Native deny/prompt tests remain mandatory. Original corpus/labels remain unchanged; all other IDs retain original gate. Actual per-row gate not yet observed.");
    fields(overlay.counts, ["HOME", "query", "HOME+query"]);
    expect(overlay.counts).toEqual({ HOME: 501, query: 74, "HOME+query": 8 });
    expect(Array.isArray(overlay.entries)).toBe(true); expect(overlay.entries).toHaveLength(583);
    const overrides = new Map<string, "model">(); const categoryCounts = { HOME: 0, query: 0, "HOME+query": 0 };
    for (const entry of overlay.entries) {
      fields(entry, ["id", "sourceRowSha256", "category", "oldGate", "expectedGate"]);
      expect(typeof entry.id === "string" && /^[0-9a-f]{64}$/.test(entry.id)).toBe(true);
      expect(typeof entry.sourceRowSha256 === "string" && /^[0-9a-f]{64}$/.test(entry.sourceRowSha256)).toBe(true);
      expect(overrides.has(entry.id)).toBe(false);
      const row = rows.get(entry.id); expect(row !== undefined).toBe(true);
      expect(sha(canonical(row))).toBe(entry.sourceRowSha256);
      expect(row.expected.status).toBe("unsupported");
      expect(row.expectedGate).toBe("human"); expect(entry.oldGate).toBe("human"); expect(entry.expectedGate).toBe("review");
      expect(Object.hasOwn(categoryCounts, entry.category)).toBe(true);
      categoryCounts[entry.category as keyof typeof categoryCounts]++;
      overrides.set(entry.id, "model"); // 固定review eligibility精确映射为既有model门枚举。
    }
    expect(categoryCounts).toEqual(overlay.counts);
    const diagnostics = { shellFamily: "zsh", executionRoute: "local-embedded", contextReason: "STANDARD_CONTEXT" } as const;
    const native = fakeNativeRuntime({ diagnostics, reviewContext: { ...diagnostics, sameSettingsInstance: true, nativeDecision: "allow" } });
    const h = await fakeHost({ config: { ...baseConfig, nativeBash: true }, nativeRuntime: native.runtime, hasUI: false });
    const { tool, hook } = await nativeReady(h);
    let completed = 0, blocked = 0, overlayReviewed = 0, unchanged = 0;
    const failures: string[] = [], observed: [string, string][] = [];
    for (const row of data.records) {
      // 期望仅取固定override或原row，不从current parser推导。
      const expectedGate = overrides.get(row.id) ?? row.expectedGate;
      const input = { command: row.command, timeout: 2 };
      const fetches = h.fetchCalls.length, invoked = h.invokeCalls.length;
      const result = await hook({ type: "tool_call", toolName: "bash", toolCallId: row.id, input }, h.ctx);
      const output = result === undefined ? await tool.execute(row.id, input, undefined, undefined, h.ctx) : undefined;
      const review = result === undefined && !output?.isError && h.fetchCalls.length === fetches+1 &&
        h.invokeCalls.length === invoked+1 && h.invokeCalls.at(-1)?.[0] === input && h.invokeCalls.at(-1)?.[0].command === row.command;
      const human = Boolean(result?.block) && h.fetchCalls.length === fetches && h.invokeCalls.length === invoked;
      const actualGate = review ? "review" : human ? "human" : "unexpected";
      observed.push([row.id, actualGate]);
      if (expectedGate === "human") { if (!human) failures.push(row.id); blocked++; }
      else { if (!review) failures.push(row.id); completed++; }
      if (overrides.has(row.id)) { if (review) overlayReviewed++; }
      else if (actualGate === (row.expectedGate === "model" ? "review" : "human")) unchanged++;
    }
    const summary = { total: observed.length, review: observed.filter(row => row[1] === "review").length,
      human: observed.filter(row => row[1] === "human").length, unexpected: observed.filter(row => row[1] === "unexpected").length,
      expectedReview: completed, expectedHuman: blocked, overlayReviewed, unchanged, failures: failures.length,
      fakeFetches: h.fetchCalls.length, fakeDelegates: h.invokeCalls.length, fakeExecs: h.execCalls.length, humanSelects: h.selectCalls.length,
      sourceCorpusSha256: sha(corpusRaw), overlaySha256: sha(overlayRaw), observationSha256: sha(JSON.stringify(observed)),
      riskOrRealHumanQualification: false, shellCommandsExecuted: false };
    const outputDir = process.env.OMP_SHELL_REVIEW_EVIDENCE;
    if (outputDir) {
      const shards = [];
      for (let offset = 0; offset < observed.length; offset += 4096) {
        const records = observed.slice(offset, offset+4096); const raw = JSON.stringify(records) + "\n";
        expect(Buffer.byteLength(raw)).toBeLessThanOrEqual(384 * 1024);
        const name = "actual-gates-" + String(shards.length + 1) + ".json";
        writeFileSync(join(outputDir, name), raw, { mode: 0o600, flag: "wx" });
        shards.push({ name, records: records.length, bytes: Buffer.byteLength(raw), sha256: sha(raw) });
      }
      writeFileSync(join(outputDir, "actual-gates-summary.json"), JSON.stringify({ ...summary, shards }, null, 2) + "\n", { mode: 0o600, flag: "wx" });
    }
    expect({ total: observed.length, completed, blocked, overlayReviewed, unchanged }).toEqual({ total: 11473, completed: 10013, blocked: 1460, overlayReviewed: 583, unchanged: 10890 });
    expect({ count: failures.length, first: failures.slice(0, 10) }).toEqual({ count: 0, first: [] });
    expect(h.fetchCalls).toHaveLength(10013); expect(h.invokeCalls).toHaveLength(10013);
    expect(h.execCalls).toHaveLength(0); expect(h.selectCalls).toHaveLength(0);
  }, 60000);
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
  test("credential flags, custom secret fields, URL userinfo and quote concatenation never reach the reviewer", async () => {
    for (const command of ["echo CUSTOM_ACCESS_TOKEN='CanaryOne'CanaryTwo", "echo API'_'KEY=CanaryKey", "echo API'_'KEY=CanaryKey \\", "echo CUSTOM'_'ACCESS_TOKEN=CanaryKey", "echo API_KEY=\\\nCanaryKey", "echo ok # API'_'KEY=CanaryKey", "curl -u CanaryUser:CanaryPass https://example.invalid", "curl -uCanaryUser:CanaryPass https://example.invalid", "curl -u \\\nCanaryUser:CanaryPass https://example.invalid", "curl https://CanaryUser:CanaryPass@example.invalid", "curl --api-key CanaryKey", "echo 'Authorization: Bearer CanaryToken'"]) {
      const h = await fakeHost({ select: "Deny" });
      expect((await (await ready(h)).execute("call", { command }, undefined, undefined, h.ctx)).isError).toBe(true);
      expect(h.fetchCalls).toHaveLength(0);
      expect(h.execCalls).toHaveLength(0);
      expect(h.selectCalls).toHaveLength(1);
      expect(JSON.stringify(h.selectCalls)).not.toMatch(/Canary(?:One|Two|User|Pass|Key|Token)/u);
    }
    const ordinary = await fakeHost({ config: { ...baseConfig, defaultMode: "manual" }, select: "Deny" });
    await (await ready(ordinary)).execute("call", { command: "ls -u fixture.txt" }, undefined, undefined, ordinary.ctx);
    expect(JSON.stringify(ordinary.selectCalls)).toContain("ls -u fixture.txt");
    for (const command of ["curl --api'_'key CanaryKey", "echo Be'ar'er CanaryToken", "echo Be'ar'er\" CanaryToken\""]) {
      const h = await fakeHost({ select: "Deny" });
      await (await ready(h)).execute("call", { command }, undefined, undefined, h.ctx);
      expect(h.fetchCalls).toHaveLength(0);
      expect(JSON.stringify(h.selectCalls)).not.toMatch(/Canary(?:Key|Token)/u);
    }
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
  test("redirect effects, wildcard uncertainty and embedded programs preserve configured gates", async () => {
    for (const [command, pattern, approval] of [
      ["echo ok 1>protected.txt 2>&1", "echo * > protected.txt", "deny"],
      ["cat *.txt", "cat protected.txt", "deny"],
      ["cat *.txt", "cat protected.txt", "prompt"],
      ["cat *.txt", "cat *", "deny"],
      ["python '-cprint(1)'", "rm *", "deny"],
      ["sudo rm target", "rm *", "deny"],
      ["rm file >", "rm *", "deny"],
      ["rm protected.txt; echo $(id)", "rm protected.txt", "deny"],
      ["rm protected.txt\n echo $(id)", "rm *", "deny"],
      ["find . -exec rm -rf / \\;", "rm *", "deny"],
      ["awk 'BEGIN{system(\"rm -rf /\")}'", "rm *", "deny"],
      ["sed 'e rm -rf /'", "rm *", "deny"],
    ] as const) {
      const hardDeny = approval === "deny" && /^(?:rm|cat|echo)\s/u.test(command);
      const h = await fakeHost({ config: { ...baseConfig, nativePatterns: [{ match: pattern, approval }] }, hasUI: hardDeny, select: "Approve" });
      const result = await (await ready(h)).execute("call", { command }, undefined, undefined, h.ctx);
      expect(result.isError).toBe(true);
      expect(h.fetchCalls).toHaveLength(0);
      expect(h.execCalls).toHaveLength(0);
      if (hardDeny) expect(h.selectCalls).toHaveLength(0);
    }
    for (const command of ["ls *.jar 2>/dev/null", "pwd\nls;", "echo ok # ; rm -rf /", "cat '*.txt'"]) {
      const h = await fakeHost({ config: { ...baseConfig, nativePatterns: [{ match: "rm *", approval: "deny" }] }, hasUI: false });
      expect((await (await ready(h)).execute("call", { command }, undefined, undefined, h.ctx)).isError).toBeUndefined();
      expect(h.fetchCalls).toHaveLength(1);
      expect(h.execCalls).toHaveLength(1);
    }
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

  test("local zsh find pipeline reviews once and delegates once without human approval", async () => {
    const diagnostics = { shellFamily: "zsh", executionRoute: "local-embedded", contextReason: "STANDARD_CONTEXT" } as const;
    const native = fakeNativeRuntime({ diagnostics, reviewContext: { ...diagnostics, sameSettingsInstance: true,
      nativeDecision: "allow" } });
    const h = await fakeHost({ config: nativeConfig, nativeRuntime: native.runtime,
      messages: [{ type: "message", message: { role: "user", content: "find the files and show the first twenty", timestamp: 1 } }] });
    const { tool, hook } = await nativeReady(h);
    const input = { command: "find . -maxdepth 1 -type f | head -20", timeout: 2 };
    expect(await hook(event("zsh-pipeline", input), h.ctx)).toBeUndefined();
    expect((await tool.execute("zsh-pipeline", input, undefined, undefined, h.ctx)).isError).toBeUndefined();
    expect(h.fetchCalls).toHaveLength(1);
    expect(h.selectCalls).toHaveLength(0);
    expect(h.invokeCalls).toHaveLength(1);
    expect(h.invokeCalls[0][0]).toBe(input);
    expect(h.execCalls).toHaveLength(0);
    const request = JSON.parse(h.fetchCalls[0][1].body);
    expect(request.messages.at(-1).content).toContain('"shellFamily":"zsh"');
    expect(request.messages.at(-1).content).toContain('"executionRoute":"local-embedded"');
    await h.commands.get("permission-control").handler("status", h.ctx);
    expect(JSON.parse(h.notices.at(-1)!).nativeContext).toEqual(diagnostics);
  });

  test("user HOME query and Git pipeline data review once and delegate raw inputs once", async () => {
    const commands = [
      "ls ~/bin /usr/local/bin 2>/dev/null | grep -i ob; command -v ob; type ob 2>&1",
      "git branch --contains b99258786076 2>/dev/null; echo ---; git log --oneline --graph --all --not --remotes | head -30",
    ];
    for (const command of commands) {
      const diagnostics = { shellFamily: "zsh", executionRoute: "local-embedded", contextReason: "STANDARD_CONTEXT" } as const;
      const native = fakeNativeRuntime({ diagnostics, reviewContext: { ...diagnostics, sameSettingsInstance: true, nativeDecision: "allow" } });
      const h = await fakeHost({ config: nativeConfig, nativeRuntime: native.runtime,
        messages: [{ type: "message", message: { role: "user", content: "Inspect the requested synthetic shell query", timestamp: 1 } }] });
      const { tool, hook } = await nativeReady(h); const input = { command, timeout: 30 };
      expect(await hook(event("common-static", input), h.ctx)).toBeUndefined();
      expect((await tool.execute("common-static", input, undefined, undefined, h.ctx)).isError).toBeUndefined();
      expect(h.fetchCalls).toHaveLength(1); expect(h.selectCalls).toHaveLength(0);
      expect(h.invokeCalls).toHaveLength(1); expect(h.invokeCalls[0][0]).toBe(input);
      expect(h.invokeCalls[0][0].command).toBe(command); expect(h.execCalls).toHaveLength(0);
      expect(JSON.parse(h.fetchCalls[0][1].body).messages.at(-1).content).toContain(command);
    }
  });

  test("failures without a current snapshot clear the preceding call's native context", async () => {
    for (const failure of ["malformed-hook", "duplicate-hook", "native-capture",
      "native-ticket", "native-recheck", "raw-ticket", "raw-recheck", "raw-params"]) {
      const native = fakeNativeRuntime({ diagnostics: { shellFamily: "zsh", executionRoute: "local-embedded",
        contextReason: "STANDARD_CONTEXT" } });
      const h = await fakeHost({ config: nativeConfig, nativeRuntime: native.runtime });
      const { tool, hook } = await nativeReady(h);
      expect(await hook(event("previous"), h.ctx)).toBeUndefined();
      await h.commands.get("permission-control").handler("explain", h.ctx);
      expect(JSON.parse(h.notices.at(-1)!).nativeContext.shellFamily).toBe("zsh");
      if (failure === "malformed-hook") expect((await hook(event("bad", { ...params, async: true }), h.ctx)).block).toBe(true);
      else if (failure === "duplicate-hook") expect((await hook(event("previous"), h.ctx)).block).toBe(true);
      else if (failure === "native-capture") {
        native.setCaptureFailure();
        expect((await hook(event("bad"), h.ctx)).block).toBe(true);
      } else if (failure === "native-ticket" || failure === "native-recheck") {
        if (failure === "native-recheck") native.setRecheckFailure();
        expect((await tool.execute(failure === "native-ticket" ? "missing" : "previous", params,
          undefined, undefined, h.ctx)).isError).toBe(true);
      } else {
        if (failure === "raw-recheck") {
          expect(await hook(event("raw", params, "permission_bash"), h.ctx)).toBeUndefined();
          native.setRecheckFailure();
        }
        expect((await h.tools.get("permission_bash").execute("raw",
          failure === "raw-params" ? { ...params, async: true } : params, undefined, undefined, h.ctx)).isError).toBe(true);
      }
      for (const command of ["explain", "status"]) {
        await h.commands.get("permission-control").handler(command, h.ctx);
        expect(JSON.parse(h.notices.at(-1)!).nativeContext).toBeUndefined();
      }
      expect(h.invokeCalls).toHaveLength(0);
      expect(h.execCalls).toHaveLength(0);
    }
  });

  test("a stale ticket retains the current recheck context rather than the preceding context", async () => {
    const native = fakeNativeRuntime({ diagnostics: { shellFamily: "zsh", executionRoute: "local-embedded",
      contextReason: "STANDARD_CONTEXT" } });
    const h = await fakeHost({ config: nativeConfig, nativeRuntime: native.runtime });
    const { tool, hook } = await nativeReady(h);
    expect(await hook(event("route-change"), h.ctx)).toBeUndefined();
    const current = { shellFamily: "zsh", executionRoute: "unverified", contextReason: "EXECUTION_ROUTE_UNVERIFIED" } as const;
    native.setDiagnostics(current);
    native.setFingerprint("current-route-changed");
    expect((await tool.execute("route-change", params, undefined, undefined, h.ctx)).details.reasonCode).toBe("STALE_REVIEW");
    for (const command of ["explain", "status"]) {
      await h.commands.get("permission-control").handler(command, h.ctx);
      expect(JSON.parse(h.notices.at(-1)!).nativeContext).toEqual(current);
    }
    expect(h.invokeCalls).toHaveLength(0);
  });

  test("raw precapture success and failure preserve the current pending Bash approval context", async () => {
    const current = { shellFamily: "bash", executionRoute: "local-embedded", contextReason: "BASH_STARTUP" } as const;
    const native = fakeNativeRuntime({ decision: "prompt", reasonCode: "UNSUPPORTED_EXECUTION_CONTEXT", diagnostics: current });
    const h = await fakeHost({ config: nativeConfig, nativeRuntime: native.runtime });
    const { hook } = await nativeReady(h);
    let respond: (value: string) => void = () => {};
    let entered: () => void = () => {};
    const shown = new Promise<void>(resolve => { entered = resolve; });
    h.ctx.ui.select = async () => {
      entered();
      return new Promise<string>(resolve => { respond = resolve; });
    };
    const pending = hook(event("pending-bash"), h.ctx);
    await shown;
    native.setDiagnostics({ shellFamily: "fish", executionRoute: "unverified", contextReason: "EXECUTION_ROUTE_UNVERIFIED" });
    expect(await hook(event("raw-different-context", params, "permission_bash"), h.ctx)).toBeUndefined();
    const assertPendingContext = async () => {
      await h.commands.get("permission-control").handler("explain", h.ctx);
      expect(JSON.parse(h.notices.at(-1)!)).toMatchObject({ outcome: "pending-human",
        reasonCode: "UNSUPPORTED_EXECUTION_CONTEXT", nativeContext: current });
      await h.commands.get("permission-control").handler("status", h.ctx);
      expect(JSON.parse(h.notices.at(-1)!).nativeContext).toEqual(current);
    };
    await assertPendingContext();
    native.setCaptureFailure();
    expect((await hook(event("raw-failed-capture", params, "permission_bash"), h.ctx)).block).toBe(true);
    await assertPendingContext();
    respond("Deny");
    expect((await pending).block).toBe(true);
    expect(h.fetchCalls).toHaveLength(0);
    expect(h.invokeCalls).toHaveLength(0);
    expect(h.execCalls).toHaveLength(0);
  });

  test("pending human approval explains the current fixed reason and safe context", async () => {
    const native = fakeNativeRuntime({ diagnostics: { shellFamily: "zsh", executionRoute: "local-embedded",
      contextReason: "STANDARD_CONTEXT" } });
    const h = await fakeHost({ config: nativeConfig, nativeRuntime: native.runtime });
    const { hook } = await nativeReady(h);
    expect(await hook(event("previous-allow"), h.ctx)).toBeUndefined();
    native.setDecision("prompt", "UNSUPPORTED_EXECUTION_CONTEXT");
    native.setDiagnostics({ shellFamily: "zsh", executionRoute: "unverified", contextReason: "EXECUTION_ROUTE_UNVERIFIED",
      env: "SECRET_ENV_SENTINEL", path: "/SECRET_PATH_SENTINEL" } as any);
    let respond: (value: string) => void = () => {};
    let entered: () => void = () => {};
    const shown = new Promise<void>(resolve => { entered = resolve; });
    h.ctx.ui.select = async (title: string) => {
      h.selectCalls.push([title]); entered();
      return new Promise<string>(resolve => { respond = resolve; });
    };
    const waiting = hook(event("pending-route"), h.ctx);
    await shown;
    await h.commands.get("permission-control").handler("explain", h.ctx);
    expect(JSON.parse(h.notices.at(-1)!)).toMatchObject({ outcome: "pending-human", source: "human",
      reasonCode: "UNSUPPORTED_EXECUTION_CONTEXT", chain: ["native", "human"], nativeContext: {
        shellFamily: "zsh", executionRoute: "unverified", contextReason: "EXECUTION_ROUTE_UNVERIFIED" } });
    await h.commands.get("permission-control").handler("status", h.ctx);
    expect(JSON.parse(h.notices.at(-1)!)).toMatchObject({ pending: 1, human: { calls: 1 }, primary: { calls: 1 } });
    expect(h.selectCalls[0][0]).toContain("reason: UNSUPPORTED_EXECUTION_CONTEXT");
    expect(h.selectCalls[0][0]).toContain("context: EXECUTION_ROUTE_UNVERIFIED");
    expect([...h.notices, h.selectCalls[0][0]].join("\n")).not.toContain("SECRET_");
    respond("Deny");
    expect((await waiting).block).toBe(true);
    expect(h.invokeCalls).toHaveLength(0);
  });

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


// 独立手写场景覆盖真实插件接线；模型与原生委派均为假实现。
describe("strict independent native approval acceptance", () => {
  const fixture = JSON.parse(readFileSync(join(import.meta.dir, "../../../../tests/fixtures/omp/command-scenarios/strict-acceptance.json"), "utf8"));
  const diagnostics = { shellFamily: "zsh", executionRoute: "local-embedded", contextReason: "STANDARD_CONTEXT" } as const;
  async function run(command: string, options: {
    decision?: "allow" | "ask" | "deny";
    hasUI?: boolean;
    nativeDecision?: "allow" | "deny" | "prompt";
    nativePatterns?: StandaloneConfig["nativePatterns"];
  } = {}) {
    const decision = options.decision ?? "allow";
    const nativeDecision = options.nativeDecision ?? "allow";
    const native = fakeNativeRuntime({ decision: nativeDecision, diagnostics,
      reviewContext: { ...diagnostics, sameSettingsInstance: true, nativeDecision } });
    const review = decision === "allow"
      ? { decision, risk: "low", authorization: "sufficient", reasonCode: "LOW_RISK_AUTHORIZED" }
      : decision === "ask"
        ? { decision, risk: "unknown", authorization: "unknown", reasonCode: "USER_CONFIRMATION_REQUIRED" }
        : { decision, risk: "high", authorization: "insufficient", reasonCode: "HIGH_RISK" };
    const h = await fakeHost({ config: { ...baseConfig, nativeBash: true,
      nativePatterns: options.nativePatterns ?? [] }, nativeRuntime: native.runtime,
      hasUI: options.hasUI ?? true, select: "Deny",
      response: { choices: [{ message: { content: JSON.stringify(review) } }] },
      messages: [{ type: "message", message: { role: "user",
        content: `Review this exact synthetic command: ${command}`, timestamp: 1 } }] });
    const { tool, hook } = await nativeReady(h);
    const input = { command, timeout: 30 };
    const hookResult = await hook({ type: "tool_call", toolName: "bash", toolCallId: "strict", input }, h.ctx);
    const result = hookResult === undefined
      ? await tool.execute("strict", input, undefined, undefined, h.ctx) : hookResult;
    return { h, input, result, blocked: hookResult?.block === true || result?.isError === true };
  }

  for (const row of fixture.complete.filter((row: any) => row.gate === "model-eligible")) {
    for (const decision of ["allow", "ask", "deny"] as const) {
      test(`strict model decision ${decision}: ${row.id}`, async () => {
        const { h, input, blocked } = await run(row.command, { decision });
        expect(h.fetchCalls).toHaveLength(1);
        expect(h.execCalls).toHaveLength(0);
        expect(h.selectCalls).toHaveLength(decision === "ask" ? 1 : 0);
        expect(h.invokeCalls).toHaveLength(decision === "allow" ? 1 : 0);
        expect(blocked).toBe(decision !== "allow");
        expect(JSON.parse(JSON.parse(h.fetchCalls[0][1].body).messages.at(-1).content).command).toBe(row.command);
        if (decision === "allow") {
          expect(h.invokeCalls[0][0]).toBe(input);
          expect(h.invokeCalls[0][0].command).toBe(row.command);
        }
      });
    }
    test(`strict headless ask and native protection: ${row.id}`, async () => {
      const headless = await run(row.command, { decision: "ask", hasUI: false });
      expect(headless.blocked).toBe(true);
      expect(headless.h.fetchCalls).toHaveLength(1);
      expect(headless.h.selectCalls).toHaveLength(0);
      expect(headless.h.invokeCalls).toHaveLength(0);
      expect(headless.h.execCalls).toHaveLength(0);
      for (const nativeDecision of ["deny", "prompt"] as const) {
        const result = await run(row.command, { nativeDecision });
        expect(result.blocked).toBe(true);
        expect(result.h.fetchCalls).toHaveLength(0);
        expect(result.h.invokeCalls).toHaveLength(0);
        expect(result.h.execCalls).toHaveLength(0);
        expect(result.h.selectCalls).toHaveLength(nativeDecision === "prompt" ? 1 : 0);
      }
    });
  }

  for (const row of fixture.manual) {
    test(`strict unsupported structures never review or delegate: ${row.id}`, async () => {
      for (const command of [row.command, `pwd && ${row.command}`, `${row.command}; echo done`, `command -v ob | ${row.command}`]) {
        const result = await run(command, { hasUI: false });
        expect(result.blocked).toBe(true);
        expect(result.h.fetchCalls).toHaveLength(0);
        expect(result.h.selectCalls).toHaveLength(0);
        expect(result.h.invokeCalls).toHaveLength(0);
        expect(result.h.execCalls).toHaveLength(0);
      }
    });
  }

  for (const row of fixture.complete.filter((row: any) => row.gate === "native-protection-required")) {
    test(`strict protected compound stops before model: ${row.id}`, async () => {
      for (const approval of ["deny", "prompt"] as const) {
        const result = await run(row.command, { nativePatterns: [{ match: "rm *", approval }] });
        expect(result.blocked).toBe(true);
        expect(result.h.fetchCalls).toHaveLength(0);
        expect(result.h.invokeCalls).toHaveLength(0);
        expect(result.h.execCalls).toHaveLength(0);
        expect(result.h.selectCalls).toHaveLength(approval === "prompt" ? 1 : 0);
      }
    });
  }
});
