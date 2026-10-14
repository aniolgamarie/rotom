// 通过真实命令输入和原生问题面板验证模拟 OAuth；不接触真实 provider。
import fs from "node:fs";
import path from "node:path";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { pathToFileURL } from "node:url";

const root = process.env.AGENTCFG_AUTH_PANEL_ROOT;
const output = process.env.AGENTCFG_AUTH_PANEL_RESULT;
const runtime = process.argv[2];
assert(root?.startsWith("/dev/shm/") && output?.startsWith(root + "/") && path.isAbsolute(runtime));
assert(["HOME", "DSH_HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME", "TMPDIR"]
  .every(name => process.env[name]?.startsWith(root + "/")));
const require = createRequire(path.join(runtime, "package.json"));
const moduleAt = name => import(pathToFileURL(require.resolve(name)).href);
const state = { kind: "native-pty-command-simulated-oauth", nonce: process.env.AGENTCFG_AUTH_PANEL_NONCE,
  stage: "host.boot", cases: [], model_calls: 0, network_calls: 0, browser_calls: 0, clipboard_calls: 0 };
const save = () => {
  fs.writeFileSync(output + ".tmp", JSON.stringify(state, null, 2) + "\n", { mode: 0o600 });
  fs.renameSync(output + ".tmp", output);
};
const wait = async test => {
  for (let i = 0; i < 6000 && !test(); i++) await new Promise(resolve => setTimeout(resolve, 10));
  assert(test());
};
let booted; let unregister; let unlisten;
try {
  save();
  const { runProfile } = await moduleAt("@deepseek-ai/dsh/profile-boot");
  const { createLaunchEnvironmentSnapshot } = await moduleAt("@deepseek-ai/dsh-launch-environment");
  const manifestPath = require.resolve("@deepseek-harness-tui/dsh-tui/package.json");
  const declared = JSON.parse(fs.readFileSync(manifestPath, "utf8")).exports["./oauth"];
  const { QuestionBridge } = await import(pathToFileURL(path.resolve(path.dirname(manifestPath), declared.import)));
  process.env.DSH_TUI_WORKSPACE_TARGET = process.cwd();
  booted = await runProfile({ environment: createLaunchEnvironmentSnapshot([{ source: "process", values: process.env }]),
    profile: "agentcfg", patchFiles: [process.env.AGENTCFG_AUTH_PANEL_PATCH], args: [],
    packageManager: { command: process.execPath, args: [process.env.AGENTCFG_AUTH_PANEL_LAUNCHER, "--deny-package-operation"], env: {} } });
  const { ctx } = booted;
  unlisten = ctx.on("llm/stream", () => { state.model_calls++; save(); throw new Error("Fixture forbids model calls"); });
  await wait(() => ctx.get("agents").list().length > 0);
  const main = ctx.get("agents").list()[0];
  assert.equal(main.session.header.cwd, process.cwd());
  const questions = ctx.get("userQuestions");
  unregister = main.ctx.get("commands").register({ name: "rotom-codex-auth-fixture",
    description: "Simulated provider OAuth fixture; no account or network", handler: async invocation => {
      const mode = invocation.rawInput.trim();
      assert(["direct-sync", "wizard-microtask", "device-cancel"].includes(mode));
      const row = { mode, stage: "command.enter", command_aborted: invocation.signal.aborted, asks: [], completed: 0 };
      state.cases.push(row); state.stage = "case.active"; save();
      const abort = new AbortController();
      const forward = () => {
        row.command_aborted = true; row.command_abort_stage = row.stage;
        abort.abort("fixture command signal cancelled"); save();
      };
      invocation.signal.addEventListener("abort", forward, { once: true });
      if (invocation.signal.aborted) forward();
      const bridge = new QuestionBridge(request => {
        const item = { id: request.questions[0].id, aborted_at_ask: request.signal?.aborted ?? false };
        row.asks.push(item); row.stage = item.id; save();
        request.signal?.addEventListener("abort", () => { item.signal_aborted = true; save(); }, { once: true });
        return questions.ask({ ...request, agent: invocation.agent }).then(answer => {
          item.resolved = true; save(); return answer;
        }, error => {
          item.error = ["ASK_ABORTED", "ASK_CANCELLED", "CALLER_NOT_LIVE", "NO_PROVIDER"].includes(error?.code) ? error.code : "QUESTION_FAILED";
          save(); throw error;
        });
      }, abort, { openUrl: () => false, copyText: async () => true });
      try {
        const flow = await bridge.prompt({ type: "select", message: "FIXTURE choose browser or device",
          options: [{ id: "browser", label: "FIXTURE browser" }, { id: "device", label: "FIXTURE device" }] });
        row.flow = flow; row.stage = "flow.selected"; save();
        if (flow === "browser") {
          row.stage = "browser.notify.before"; save();
          bridge.notify({ type: "auth_url", url: "https://fixture.invalid/oauth", instructions: "SIMULATED NO ACCOUNT" });
          row.stage = "browser.notify.after"; save();
          if (mode === "wizard-microtask") {
            await Promise.resolve(); row.stage = "browser.microtask.after"; save();
          }
          row.stage = "browser.prompt.before"; save();
          const code = await bridge.prompt({ type: "manual_code", message: "FIXTURE paste callback code" });
          assert.equal(code, "FIXTURE-CALLBACK-CODE");
          assert(!abort.signal.aborted); row.completed++;
        } else {
          bridge.notify({ type: "device_code", userCode: "FIXTURE-DEVICE", verificationUri: "https://fixture.invalid/device" });
          await new Promise(resolve => {
            if (abort.signal.aborted) resolve(); else abort.signal.addEventListener("abort", resolve, { once: true });
          });
          row.cancelled = true; assert.equal(row.completed, 0);
        }
        row.stage = "case.complete"; row.run_aborted = abort.signal.aborted; save();
        return { kind: "success", text: "FIXTURE simulated flow finished" };
      } catch (error) {
        row.stage_at_failure = row.stage; row.stage = "case.failed";
        row.run_aborted = abort.signal.aborted;
        row.error = error?.code === "ERR_ASSERTION" ? "ASSERTION_FAILED" : "SIMULATED_LOGIN_FAILED";
        state.error = row.error; save();
        return { kind: "error", text: "FIXTURE simulated flow failed" };
      } finally {
        invocation.signal.removeEventListener("abort", forward);
        await bridge.settle(); row.settled = true; save();
      }
    } });
  state.stage = "host.agent_ready"; save();
  await wait(() => fs.existsSync(process.env.AGENTCFG_AUTH_PANEL_READY));
  await wait(() => state.error || state.cases.length === 3 && state.cases.every(row => row.settled));
  unregister(); unregister = undefined; unlisten(); unlisten = undefined;
  state.native_complete = !state.error; state.stage = state.error ? "failed" : "complete"; save();
  await booted.shutdown.shutdown(state.error ? 1 : 0);
} catch (error) {
  state.error = error?.code === "ERR_ASSERTION" ? "ASSERTION_FAILED" : "NATIVE_FIXTURE_FAILED";
  state.error_location = state.stage; save(); unregister?.(); unlisten?.();
  if (booted) await booted.shutdown.shutdown(1); else process.exitCode = 1;
}
