import { afterEach, beforeEach, describe, expect, test } from "bun:test";
import { mkdir, mkdtemp, rm, symlink, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createNativeBashRuntime, executionRoute, type PlainBashParams } from "./native-bash";

function setting<T>(read: (settings: any) => T) {
  return { get: read };
}

function runtime(options: { approval?: unknown; policy?: string; revision?: number; split?: boolean;
  home?: string; env?: Record<string, string>; direnv?: string; shellArgs?: string[]; shell?: string;
  shellPath?: string; prefix?: string; executionRoute?: () => "local-embedded" | "unverified";
  executionRouteFingerprint?: () => string; legacyShellAllowed?: () => boolean } = {}) {
  const settings: any = {
    revision: options.revision ?? 1,
    getShellConfig: () => ({ shell: options.shell ?? "/bin/bash", args: options.shellArgs ?? ["-c"], prefix: options.prefix,
      env: { ...(options.home ? { HOME: options.home } : {}), ...options.env } }),
  };
  const globalSettings = options.split ? { ...settings, getShellConfig: settings.getShellConfig } : settings;
  const modules: any = {
    homeDir: () => options.home ?? "/fixture/home",
    executionRoute: options.executionRoute,
    executionRouteFingerprint: options.executionRouteFingerprint,
    legacyShellAllowed: options.legacyShellAllowed,
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
    cfgShellPath: setting(() => options.shellPath),
    cfgWorktreeClone: setting(() => false),
  };
  return { native: createNativeBashRuntime(modules), settings };
}

const params: PlainBashParams = { command: "ls -la", timeout: 2 };

describe("managed local execution route", () => {
  const marker = "local-native-bash-v1";
  const prefix = ["/fixture/bin/omp", "/$bunfs/root/cli.js"];
  test("accepts only the explicit managed CLI options and local modes", () => {
    for (const args of [[], ["--profile", "fixture", "--no-title"], ["--print", "--no-session", "--no-skills"],
      ["--model", "acp", "--provider=fixture"], ["--smol", "fixture", "--slow", "fixture", "--plan", "fixture"],
      ["--thinking", "high", "--service-tier", "auto", "--max-time", "10"],
      ["--mode", "text"], ["--mode=json"], ["--mode", "rpc"], ["--", "--mode", "acp", "--unknown"]]) {
      expect(executionRoute(marker, [...prefix, ...args])).toBe("local-embedded");
    }
    expect(executionRoute(marker, ["/bin/node", "/fixture/cli.ts", "--mode", "rpc"])).toBe("local-embedded");
  });
  test("missing marker, ACP, rpc-ui, unknown modes and flags reject route proof", () => {
    for (const args of [["acp"], ["rpc-ui"], ["--mode", "acp"], ["--mode=rpc-ui"], ["--mode=unknown"],
      ["--extension", "/fixture/test.ts"], ["--unknown"], ["--mode"], ["--mode", ""], ["--model", "--"],
      ["--mode", "acp", "--mode", "text"]]) {
      expect(executionRoute(marker, [...prefix, ...args])).toBe("unverified");
    }
    expect(executionRoute(undefined, prefix)).toBe("unverified");
    expect(executionRoute("SECRET_INVALID_MARKER", prefix)).toBe("unverified");
    expect(executionRoute(marker, [])).toBe("unverified");
  });
});

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

  test("zsh standard login environment allows local Brush find pipeline to enter review", async () => {
    await writeFile(join(home, ".zshrc"), "# startup must not execute\n");
    const { native } = runtime({ home, shell: "/bin/zsh", shellArgs: ["-l", "-c"],
      executionRoute: () => "local-embedded" });
    const captured = await native.capture(root, { command: "find . -maxdepth 1 -type f | head -20" });
    expect(captured.decision).toBe("allow");
    expect(captured.reviewContext).toMatchObject({ shellFamily: "zsh", executionRoute: "local-embedded",
      contextReason: "STANDARD_CONTEXT" });
  });

  test("all configured shell families accept only official shapes on the local route", async () => {
    const families = ["bash", "sh", "zsh", "dash", "ash", "ksh", "mksh", "fish", "pwsh", "powershell", "cmd"];
    for (const family of families) {
      const shapes = family === "cmd" ? [["/c"]] : ["pwsh", "powershell"].includes(family)
        ? [["-NoLogo", "-Command"], ["-NoLogo", "-NoProfile", "-Command"]] : [["-c"], ["-l", "-c"]];
      for (const shell of [`/bin/${family}`, `C:\\Shells\\${family.toUpperCase()}.EXE`]) {
        for (const shellArgs of shapes) {
          const captured = await runtime({ home, shell, shellArgs, executionRoute: () => "local-embedded" })
            .native.capture(root, params);
          expect(captured.decision).toBe("allow");
          expect(captured.reviewContext.shellFamily).toBe(family);
        }
        const captured = await runtime({ home, shell, shellArgs: [...shapes[0], "--unknown"],
          executionRoute: () => "local-embedded" }).native.capture(root, params);
        expect(captured.decision).toBe("prompt");
        expect(captured.reviewContext.contextReason).toBe("SHELL_ARGUMENTS");
      }
    }
  });

  test("unknown shells and missing route for new families require human approval", async () => {
    for (const shell of ["zsh", "dash", "ash", "ksh", "mksh", "fish", "pwsh", "powershell", "cmd"]) {
      const shellArgs = shell === "cmd" ? ["/c"] : ["pwsh", "powershell"].includes(shell)
        ? ["-NoLogo", "-Command"] : ["-c"];
      expect((await runtime({ home, shell, shellArgs }).native.capture(root, params)).decision).toBe("prompt");
    }
    const unknown = await runtime({ home, shell: "/private/secret-shell", executionRoute: () => "local-embedded" })
      .native.capture(root, params);
    expect(unknown.reviewContext.shellFamily).toBe("unknown");
    expect(unknown.reviewContext.contextReason).toBe("SHELL_UNKNOWN");
    expect(JSON.stringify(unknown.reviewContext)).not.toContain("secret-shell");
  });

  test("known non-Bash custom paths and startup files are not executed locally", async () => {
    await mkdir(join(home, ".config", "fish"), { recursive: true });
    for (const file of [".zshenv", ".zshrc", ".zprofile", ".profile", join(".config", "fish", "config.fish")])
      await writeFile(join(home, file), "echo SECRET_STARTUP_SENTINEL > forbidden-sentinel\n");
    for (const shell of ["sh", "zsh", "dash", "ash", "ksh", "mksh", "fish", "pwsh", "powershell", "cmd"]) {
      const shellArgs = shell === "cmd" ? ["/c"] : ["pwsh", "powershell"].includes(shell)
        ? ["-NoLogo", "-Command"] : ["-c"];
      const captured = await runtime({ home, shell: `/custom/${shell}`, shellPath: `/custom/${shell}`, shellArgs,
        executionRoute: () => "local-embedded" }).native.capture(root, params);
      expect(captured.decision).toBe("allow");
      expect(captured.reviewContext.contextReason).toBe("STANDARD_CONTEXT");
      expect(JSON.stringify(captured.reviewContext)).not.toContain("SECRET_STARTUP_SENTINEL");
    }
  });

  test("custom Bash path, shell prefix and unknown custom path remain human gates", async () => {
    for (const options of [
      { shell: "/bin/bash", shellPath: "/custom/bash" },
      { shell: "/bin/zsh", prefix: "SECRET_PREFIX_SENTINEL" },
      { shell: "/bin/zsh", shellPath: "/custom/unknown-shell" },
    ]) {
      const captured = await runtime({ home, ...options, executionRoute: () => "local-embedded" }).native.capture(root, params);
      expect(captured.decision).toBe("prompt");
      expect(JSON.stringify(captured.reviewContext)).not.toContain("SECRET_PREFIX_SENTINEL");
      expect(JSON.stringify(captured.diagnostics)).not.toContain("/custom");
    }
  });

  test("route and shell changes invalidate the existing snapshot fingerprint", async () => {
    let route: "local-embedded" | "unverified" = "local-embedded";
    const { native, settings } = runtime({ home, shell: "/bin/zsh", executionRoute: () => route });
    const captured = await native.capture(root, params);
    route = "unverified";
    const missing = await native.recheck(captured.settings, root, params);
    expect(missing.decision).toBe("prompt");
    expect(missing.fingerprint).not.toBe(captured.fingerprint);
    route = "local-embedded";
    settings.getShellConfig = () => ({ shell: "/bin/fish", args: ["-c"], env: { HOME: home } });
    const changed = await native.recheck(captured.settings, root, params);
    expect(changed.decision).toBe("allow");
    expect(changed.fingerprint).not.toBe(captured.fingerprint);
  });

  test("invalid current CLI or wrong marker cannot downgrade Bash or sh to the legacy route", async () => {
    const prefix = ["/fixture/bin/omp", "/$bunfs/root/cli.js"];
    for (const shell of ["/bin/bash", "/bin/sh"]) {
      for (const [marker, args] of [
        ["local-native-bash-v1", ["acp"]], [undefined, ["--mode", "acp"]],
        ["local-native-bash-v1", ["--mode", "rpc-ui"]], [undefined, ["--mode", "unknown"]],
        ["local-native-bash-v1", ["--unknown"]], ["wrong-marker", ["--mode", "rpc"]],
      ] as const) {
        const argv = [...prefix, ...args];
        const captured = await runtime({ home, shell, executionRoute: () => executionRoute(marker, argv),
          legacyShellAllowed: () => marker === undefined && executionRoute("local-native-bash-v1", argv) === "local-embedded" })
          .native.capture(root, params);
        expect(captured.decision).toBe("prompt");
        expect(captured.reviewContext.contextReason).toBe("EXECUTION_ROUTE_UNVERIFIED");
      }
      const argv = [...prefix, "--profile", "fixture"];
      const legacy = await runtime({ home, shell, executionRoute: () => executionRoute(undefined, argv),
        legacyShellAllowed: () => executionRoute("local-native-bash-v1", argv) === "local-embedded" })
        .native.capture(root, params);
      expect(legacy.decision).toBe("allow");
      expect(legacy.reviewContext.executionRoute).toBe("unverified");
    }
  });

  test("current marker overrides cached shell env and every marker change alters fingerprint", async () => {
    const argv = ["/fixture/bin/omp", "/$bunfs/root/cli.js", "--mode", "rpc"];
    let marker: string | undefined;
    const { native } = runtime({ home, shell: "/bin/zsh", env: {
      ROTOM_PERMISSION_CONTROL_EXECUTION_ROUTE: "local-native-bash-v1", API_KEY: "SECRET_ENV_SENTINEL" },
      executionRoute: () => executionRoute(marker, argv), executionRouteFingerprint: () => marker ?? "missing",
      legacyShellAllowed: () => marker === undefined && executionRoute("local-native-bash-v1", argv) === "local-embedded" });
    const absent = await native.capture(root, params);
    expect(absent.decision).toBe("prompt");
    marker = "local-native-bash-v1";
    const verified = await native.recheck(absent.settings, root, params);
    expect(verified.decision).toBe("allow");
    expect(verified.fingerprint).not.toBe(absent.fingerprint);
    marker = "SECRET_WRONG_MARKER_ONE";
    const wrong = await native.recheck(verified.settings, root, params);
    expect(wrong.decision).toBe("prompt");
    marker = "SECRET_WRONG_MARKER_TWO";
    const changed = await native.recheck(wrong.settings, root, params);
    expect(changed.fingerprint).not.toBe(wrong.fingerprint);
    expect(JSON.stringify([changed.reviewContext, changed.diagnostics])).not.toContain("SECRET_");
  });

  test("verified local Bash preserves startup, inherited function, HOME and native deny guards", async () => {
    await writeFile(join(home, ".bashrc"), "# fixture\n");
    const { native } = runtime({ home, executionRoute: () => "local-embedded" });
    expect((await native.capture(root, params)).reviewContext.contextReason).toBe("BASH_STARTUP");
    await rm(join(home, ".bashrc"));
    expect((await native.capture(root, params)).reviewContext.contextReason).toBe("BASH_SNAPSHOT_UNCERTAIN");
    const envs: Record<string, string>[] = [{ "BASH_FUNC_fixture%%": "() { :; }" }, { HOME: join(root, "different-home") }];
    for (const env of envs) {
      expect((await runtime({ home, env, executionRoute: () => "local-embedded" }).native.capture(root, params)).decision)
        .toBe("prompt");
    }
    for (const options of [{ policy: "deny" }, { approval: { tier: "exec", policy: "deny" } }]) {
      const captured = await runtime({ home, shell: "/bin/zsh", prefix: "untrusted", ...options,
        executionRoute: () => "local-embedded" }).native.capture(root, params);
      expect(captured.reasonCode).toBe("NATIVE_DENY");
    }
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
