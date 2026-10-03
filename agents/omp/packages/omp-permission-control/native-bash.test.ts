import { afterEach, beforeEach, describe, expect, test } from "bun:test";
import { mkdir, mkdtemp, rm, symlink, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createNativeBashRuntime, type PlainBashParams } from "./native-bash";

function setting<T>(read: (settings: any) => T) {
  return { get: read };
}

function runtime(options: { approval?: unknown; policy?: string; revision?: number; split?: boolean;
  home?: string; env?: Record<string, string>; direnv?: string; shellArgs?: string[] } = {}) {
  const settings: any = {
    revision: options.revision ?? 1,
    getShellConfig: () => ({ shell: "/bin/bash", args: options.shellArgs ?? ["-c"],
      env: { ...(options.home ? { HOME: options.home } : {}), ...options.env } }),
  };
  const globalSettings = options.split ? { ...settings, getShellConfig: settings.getShellConfig } : settings;
  const modules: any = {
    homeDir: () => options.home ?? "/fixture/home",
    findScopedSettings: () => settings,
    isSettingsInitialized: () => true,
    getGlobalSettings: async () => globalSettings,
    BashTool: class { approval() { return options.approval ?? "exec"; } },
    cfgToolsApproval: setting(() => options.policy ? { bash: options.policy } : {}),
    cfgToolsMaxTimeout: setting(() => 0),
    cfgAsyncEnabled: setting(() => false),
    cfgLaunchEnabled: setting(() => false),
    cfgBashAllowCompoundCommands: setting(() => false),
    cfgBashAutoBackgroundEnabled: setting(() => false),
    cfgBashAutoBackgroundThresholdMs: setting(() => 60_000),
    cfgBashPatterns: setting(() => []),
    cfgBashInterceptorEnabled: setting(() => true),
    cfgBashInterceptorPatterns: setting(() => []),
    cfgBashDirenv: setting(() => options.direnv ?? "auto"),
    cfgBashDirenvLoadTimeoutMs: setting(() => 30_000),
    cfgShellPath: setting(() => undefined),
    cfgWorktreeClone: setting(() => false),
  };
  return { native: createNativeBashRuntime(modules), settings };
}

const params: PlainBashParams = { command: "ls -la", timeout: 2 };

describe("native bash public approval adapter", () => {
  let root: string;
  let home: string;

  beforeEach(async () => {
    root = await mkdtemp(join(tmpdir(), "omp-native-bash-test-"));
    home = join(root, "home");
    await mkdir(home, { recursive: true });
  });

  afterEach(async () => {
    await rm(root, { recursive: true, force: true });
  });

  test("accepts a known native exec decision in the standard context", async () => {
    const { native } = runtime({ home });
    expect((await native.capture(root, params)).decision).toBe("allow");
  });

  test("preserves native deny and prompt decisions", async () => {
    expect((await runtime({ home, policy: "deny" }).native.capture(root, params)).decision).toBe("deny");
    expect((await runtime({ home, approval: { tier: "exec", override: true } }).native.capture(root, params)).decision)
      .toBe("prompt");
  });

  test("unknown native approval shapes fail closed to prompt", async () => {
    expect((await runtime({ home, approval: { unexpected: true } }).native.capture(root, params)).decision)
      .toBe("prompt");
  });

  test("settings revision changes invalidate the fingerprint", async () => {
    const { native, settings } = runtime({ home });
    const captured = await native.capture(root, params);
    settings.revision++;
    expect((await native.recheck(captured.settings, root, params)).fingerprint).not.toBe(captured.fingerprint);
  });

  test("envrc, symlinked startup files, and split settings require a human", async () => {
    await writeFile(join(root, ".envrc"), "export SAFE=1\n");
    expect((await runtime({ home }).native.capture(root, params)).reasonCode).toBe("UNSUPPORTED_EXECUTION_CONTEXT");
    await rm(join(root, ".envrc"));
    await writeFile(join(root, "startup"), "# fixture\n");
    await symlink(join(root, "startup"), join(home, ".bashrc"));
    expect((await runtime({ home }).native.capture(root, params)).reasonCode).toBe("UNSUPPORTED_EXECUTION_CONTEXT");
    await rm(join(home, ".bashrc"));
    expect((await runtime({ home, split: true }).native.capture(root, params)).reasonCode)
      .toBe("UNSUPPORTED_EXECUTION_CONTEXT");
  });

  test("native deny wins over an uncertain execution context", async () => {
    await writeFile(join(root, ".envrc"), "export SAFE=1\n");
    expect((await runtime({ home, approval: { tier: "exec", policy: "deny" } }).native.capture(root, params)).decision)
      .toBe("deny");
  });

  test("startup uncertainty is sticky after a file disappears", async () => {
    await writeFile(join(home, ".bashrc"), "# fixture\n");
    const { native } = runtime({ home });
    expect((await native.capture(root, params)).decision).toBe("prompt");
    await rm(join(home, ".bashrc"));
    expect((await native.capture(root, params)).reasonCode).toBe("UNSUPPORTED_EXECUTION_CONTEXT");
  });

  test("a sole bash login file requires a human and remains uncertain after removal", async () => {
    await writeFile(join(home, ".bash_login"), "# fixture\n");
    const { native } = runtime({ home, shellArgs: ["-l", "-c"] });
    const captured = await native.capture(root, params);
    expect(captured.decision).toBe("prompt");
    expect(captured.reasonCode).toBe("UNSUPPORTED_EXECUTION_CONTEXT");
    await rm(join(home, ".bash_login"));
    const checked = await native.recheck(captured.settings, root, params);
    expect(checked.decision).toBe("prompt");
    expect(checked.reasonCode).toBe("UNSUPPORTED_EXECUTION_CONTEXT");
    expect(checked.fingerprint).not.toBe(captured.fingerprint);
  });

  test("native deny wins when a bash login file exists", async () => {
    await writeFile(join(home, ".bash_login"), "# fixture\n");
    for (const options of [{ policy: "deny" }, { approval: { tier: "exec", policy: "deny" } }]) {
      const captured = await runtime({ home, shellArgs: ["-l", "-c"], ...options }).native.capture(root, params);
      expect(captured.decision).toBe("deny");
      expect(captured.reasonCode).toBe("NATIVE_DENY");
    }
  });

  test("inherited shell functions and a symlinked cwd require a human", async () => {
    expect((await runtime({ home, env: { "BASH_FUNC_fixture%%": "() { :; }" } }).native.capture(root, params))
      .reasonCode).toBe("UNSUPPORTED_EXECUTION_CONTEXT");
    const actual = join(root, "actual");
    const linked = join(root, "linked");
    await mkdir(actual);
    await symlink(actual, linked);
    expect((await runtime({ home }).native.capture(linked, params)).reasonCode)
      .toBe("UNSUPPORTED_EXECUTION_CONTEXT");
  });
});
