import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import test from "node:test";
import { fileURLToPath } from "node:url";

const launch = fileURLToPath(new URL("../../agents/dsh/templates/launch.mjs", import.meta.url));

function fixture(run) {
  const root = mkdtempSync(path.join(os.tmpdir(), "dsh-auth-launch-"));
  try {
    const runtime = path.join(root, "runtime");
    mkdirSync(runtime);
    writeFileSync(path.join(runtime, "package.json"), JSON.stringify({ private: true }));
    const record = path.join(root, "record.json");
    const module = (name, exports) => {
      const directory = path.join(runtime, "node_modules", name);
      mkdirSync(directory, { recursive: true });
      const mapping = {};
      for (const [subpath, body] of Object.entries(exports)) {
        const file = `${Object.keys(mapping).length}.mjs`;
        mapping[subpath] = `./${file}`;
        writeFileSync(path.join(directory, file), body);
      }
      writeFileSync(path.join(directory, "package.json"), JSON.stringify({ name, exports: mapping }));
    };
    module("rotom-dsh-ssh-subscription-auth", { "./cli": `
      import { writeFileSync } from "node:fs";
      export async function runAuth(argv) {
        writeFileSync(process.env.FIXTURE_RECORD, JSON.stringify({ kind: "auth", argv }));
        return 0;
      }
    ` });
    module("@deepseek-ai/dsh", { "./profile-boot": `
      import { writeFileSync } from "node:fs";
      export async function runProfile(options) {
        writeFileSync(process.env.FIXTURE_RECORD, JSON.stringify({ kind: "task", args: options.args,
          tuiTarget: process.env.DSH_TUI_WORKSPACE_TARGET, development: process.env.AGENTCFG_DEVELOPMENT_ENV,
          mcp: process.env.AGENTCFG_MCP_ENV_ARGS }));
      }
    ` });
    module("@deepseek-ai/dsh-launch-environment", { ".": "export function createLaunchEnvironmentSnapshot(sources) { return sources; }" });
    module("rotom-dsh-execution-environment", { "./environment": "export function mcpArguments() { return []; }" });
    const invoke = (args, overrides = {}) => spawnSync(process.execPath, [launch, runtime,
      path.join(root, "patch.yml"), "--profile", "agentcfg", ...args], {
      env: { PATH: path.dirname(process.execPath), HOME: root, DSH_HOME: path.join(root, "dsh"),
        FIXTURE_RECORD: record, AGENTCFG_DSH_EXECUTION: "ssh",
        AGENTCFG_DSH_REMOTE_WORKSPACE: "/srv/fixture/project",
        AGENTCFG_DSH_SUBSCRIPTION_PROVIDERS: '["codex","cursor"]',
        DSH_TUI_WORKSPACE_TARGET: "local-sentinel", AGENTCFG_DEVELOPMENT_ENV: "local-sentinel",
        AGENTCFG_MCP_ENV_ARGS: "local-sentinel", ...overrides }, encoding: "utf8",
    });
    run({ invoke, record: () => JSON.parse(readFileSync(record, "utf8")) });
  } finally { rmSync(root, { recursive: true, force: true }); }
}

test("SSH auth dispatch calls only the explicit authentication entry", () => fixture(({ invoke, record }) => {
  const result = invoke(["--subscription-auth", "codex", "status"]);
  assert.equal(result.status, 0, result.stderr);
  assert.deepEqual(record(), { kind: "auth", argv: ["codex", "status"] });
}));

test("unselected or invalid authentication arguments are refused before dispatch", () => fixture(({ invoke }) => {
  for (const args of [["--subscription-auth", "codex"], ["--subscription-auth", "fixture-private", "status"],
    ["--subscription-auth", "cursor", "login", "extra"]]) {
    const result = invoke(args);
    assert.notEqual(result.status, 0);
    assert.ok(!result.stderr.includes("fixture-private"));
  }
  assert.notEqual(invoke(["--subscription-auth", "cursor", "status"], {
    AGENTCFG_DSH_SUBSCRIPTION_PROVIDERS: '["codex"]',
  }).status, 0);
}));

test("ordinary SSH tasks keep native arguments and discard local path snapshots", () => fixture(({ invoke, record }) => {
  const result = invoke(["--json", "inspect fixture"]);
  assert.equal(result.status, 0, result.stderr);
  assert.deepEqual(record(), { kind: "task", args: ["--json", "inspect fixture"] });
}));
