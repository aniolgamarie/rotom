import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import test from "node:test";
import { fileURLToPath } from "node:url";

// 只运行仓库 launcher 和临时假模块，不安装或启动官方宿主。
const launch = fileURLToPath(new URL("../../agents/dsh/templates/launch.mjs", import.meta.url));

function fixture(run) {
  const root = mkdtempSync(path.join(os.tmpdir(), "rotom-resume-launch-"));
  try {
    const runtime = path.join(root, "runtime");
    const cwd = path.join(root, "synthetic-project");
    const home = path.join(root, "home");
    for (const directory of [runtime, cwd, home]) mkdirSync(directory, { mode: 0o700 });
    writeFileSync(path.join(runtime, "package.json"), '{"private":true}');
    const record = path.join(root, "record.json");
    const module = (name, exports) => {
      const directory = path.join(runtime, "node_modules", name);
      mkdirSync(directory, { recursive: true, mode: 0o700 });
      const mapping = {};
      for (const [subpath, body] of Object.entries(exports)) {
        const file = `${Object.keys(mapping).length}.mjs`;
        mapping[subpath] = `./${file}`;
        writeFileSync(path.join(directory, file), body);
      }
      writeFileSync(path.join(directory, "package.json"), JSON.stringify({ name, exports: mapping }));
    };
    module("@deepseek-ai/dsh", { "./profile-boot": `
      import { writeFileSync } from "node:fs";
      export async function runProfile(options) {
        const layer = options.environment[0];
        writeFileSync(process.env.FIXTURE_RECORD, JSON.stringify({
          profile: options.profile, patchFiles: options.patchFiles, args: options.args,
          source: layer.source, resume: layer.values.DSH_TUI_RESUME_SESSION,
          workspace: layer.values.DSH_TUI_WORKSPACE_TARGET,
          cwd: process.cwd(), packageArgs: options.packageManager.args.slice(1),
        }));
      }
    ` });
    module("@deepseek-ai/dsh-launch-environment", {
      ".": "export function createLaunchEnvironmentSnapshot(layers) { return layers; }",
    });
    module("rotom-dsh-execution-environment", {
      "./environment": "export function mcpArguments() { return []; }",
    });
    const patch = path.join(root, "synthetic.patch.yml");
    const invoke = (args, resume) => {
      const child = spawnSync(process.execPath, [launch, runtime, patch,
        "--profile", "agentcfg", ...args], {
        cwd, encoding: "utf8",
        env: { HOME: home, DSH_HOME: path.join(home, "dsh"),
          XDG_CONFIG_HOME: path.join(home, "config"), XDG_DATA_HOME: path.join(home, "data"),
          XDG_CACHE_HOME: path.join(home, "cache"), XDG_STATE_HOME: path.join(home, "state"),
          FIXTURE_RECORD: record,
          ...(resume === undefined ? {} : { DSH_TUI_RESUME_SESSION: resume }),
        },
      });
      assert.equal(child.status, 0, child.stderr);
      return JSON.parse(readFileSync(record, "utf8"));
    };
    run({ invoke, cwd, patch });
  } finally { rmSync(root, { recursive: true, force: true }); }
}

test("managed profile boot receives exact synthetic resume environment and patch", () => fixture(({ invoke, cwd, patch }) => {
  assert.deepEqual(invoke([], "session-example"), {
    profile: "agentcfg", patchFiles: [patch], args: [], source: "process",
    resume: "session-example", workspace: cwd, cwd,
    packageArgs: ["--deny-package-operation"],
  });
}));

test("native argv passes to profile boot without launcher-side resume parsing", () => fixture(({ invoke }) => {
  const observed = invoke(["--resume", "session-example"]);
  assert.deepEqual(observed.args, ["--resume", "session-example"]);
  assert.equal(Object.hasOwn(observed, "resume"), false);
}));

test("ordinary launch invents neither a resume target nor continuation input", () => fixture(({ invoke }) => {
  const observed = invoke([]);
  assert.deepEqual(observed.args, []);
  assert.equal(Object.hasOwn(observed, "resume"), false);
}));
