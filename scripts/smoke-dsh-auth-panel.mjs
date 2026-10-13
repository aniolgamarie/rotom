// 真实原生 QuestionBridge 面板，登录/复制/浏览器均为明确标记的 fixture。
import fs from "node:fs";
import path from "node:path";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { pathToFileURL } from "node:url";

const root = process.env.AGENTCFG_AUTH_PANEL_ROOT;
const output = process.env.AGENTCFG_AUTH_PANEL_RESULT;
const runtime = process.argv[2];
if (!root || !output?.startsWith(root + "/") || !runtime || !path.isAbsolute(runtime)
    || !["HOME", "DSH_HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME"].every(name => process.env[name]?.startsWith(root + "/"))) {
  throw new Error("Explicit isolated native fixture environment required");
}
const require = createRequire(path.join(runtime, "package.json"));
const moduleAt = name => import(pathToFileURL(require.resolve(name)).href);
const state = { kind: "native-real-QuestionBridge-simulated-login", nonce: process.env.AGENTCFG_AUTH_PANEL_NONCE,
  stage: "host.boot", start_calls: 0, cancel_calls: 0, copy_calls: 0, ask_calls: 0, model_calls: 0,
  actual_account: "NOT RUN", actual_clipboard: "NOT RUN", actual_browser: "NOT RUN" };
const save = () => { fs.writeFileSync(output + ".tmp", JSON.stringify(state, null, 2) + "\n", { mode: 0o600 }); fs.renameSync(output + ".tmp", output); };
const wait = async test => {
  for (let i = 0; i < 6000 && !test(); i++) await new Promise(resolve => setTimeout(resolve, 10));
  assert(test());
};
const uri = "https://cursor.com/cli/login?challenge=FAKE_AUTH_PANEL_" + "a".repeat(400) + "&uuid=SIMULATED_NO_ACCOUNT";
let booted; let handler; let unregister; let unlisten;
try {
  save();
  const { runProfile } = await moduleAt("@deepseek-ai/dsh/profile-boot");
  const { createLaunchEnvironmentSnapshot } = await moduleAt("@deepseek-ai/dsh-launch-environment");
  const { createLoginHandler, LoginLinkStore, resolveLoginAsk } = await moduleAt("rotom-dsh-cursor-terminal");
  // 解析发布的 import 条件导出；不反射或猜测任何私有 chunk。
  const manifestPath = require.resolve("@deepseek-harness-tui/dsh-tui/package.json");
  const declared = JSON.parse(fs.readFileSync(manifestPath, "utf8")).exports["./oauth"];
  const { QuestionBridge } = await import(pathToFileURL(path.resolve(path.dirname(manifestPath), declared.import)));
  process.env.DSH_TUI_WORKSPACE_TARGET = process.cwd();
  booted = await runProfile({ environment: createLaunchEnvironmentSnapshot([{ source: "process", values: process.env }]),
    profile: "agentcfg", patchFiles: [process.env.AGENTCFG_AUTH_PANEL_PATCH], args: [],
    packageManager: { command: process.execPath, args: [process.env.AGENTCFG_AUTH_PANEL_LAUNCHER, "--deny-package-operation"], env: {} } });
  const { ctx } = booted;
  unlisten = ctx.on("llm/stream", () => { state.model_calls++; save(); throw new Error("Model calls disabled in simulated auth-panel acceptance"); });
  await wait(() => ctx.get("agents").list().length > 0);
  const main = ctx.get("agents").list()[0];
  assert.equal(main.session.header.cwd, process.cwd());
  state.stage = "host.agent_ready"; save();
  await wait(() => fs.existsSync(process.env.AGENTCFG_AUTH_PANEL_READY));
  const home = path.join(root, "fixture-link-home"); fs.mkdirSync(home, { mode: 0o700 });
  const file = path.join(home, "cursor-login-url.txt");
  let phase = "waiting_browser"; let reopened = false;
  const coordinator = { start: async () => { state.start_calls++; return { id: "fake-native-login", phase, authUrl: uri }; },
    read: id => { assert.equal(id, "fake-native-login"); return { id, phase, authenticated: false }; },
    cancel: async id => { assert.equal(id, "fake-native-login"); state.cancel_calls++; phase = "cancelled"; save(); },
    accountStatus: async () => ({ authenticated: false }), logout: async () => {} };
  const questions = ctx.get("userQuestions"); assert(questions && typeof questions.ask === "function");
  const scopedQuestions = { ask: request => {
      assert.equal(request.agent, main);
      state.caller_scope_verified = true;
      const question = request.questions[0];
      assert(question.detail.includes(uri)); assert.equal(question.options.length, 3);
      state.option_labels = question.options.map(option => option.label); state.ask_calls++;
      state.stage = reopened ? "panel.reopened_requested" : "panel.initial_requested"; save();
      return questions.ask(request).catch(error => {
        state.ask_error = ["NO_PROVIDER", "ASK_ABORTED", "CALLER_NOT_LIVE", "DELEGATED_CALLER"].includes(error?.code) ? error.code : "QUESTION_FAILED";
        save(); throw error;
      });
    } };
  handler = createLoginHandler(coordinator, { cancelRequests() {}, resumeRequests() {}, listModelsForRpc: async () => [] }, {
    linkStore: new LoginLinkStore(file), resolveAsk: invocation => resolveLoginAsk({ get: service => {
      assert.equal(service, "userQuestions"); return scopedQuestions;
    } }, invocation), bridgeFactory: (ask, abort) => new QuestionBridge(ask, abort, { openUrl: () => false,
      copyText: async value => { assert.equal(value, uri); state.copy_calls++; state.copy_exact = true;
        state.uri_chars = uri.length; state.stage = "copy.recorded"; save(); return true; } }) });
  unregister = main.ctx.get("commands").register({ name: "rotom-auth-panel-test", description: "Isolated simulated login panel acceptance", handler });
  const call = verb => ctx.get("commands").execute(main, "/rotom-auth-panel-test " + verb, [], new AbortController().signal);
  assert.equal((await call("start"))?.result?.kind, "success");
  await wait(() => state.copy_calls === 1);
  reopened = true; state.stage = "commands.reopen"; save();
  assert.equal((await call("url"))?.result?.kind, "success");
  await wait(() => state.ask_calls >= 3);
  assert.equal(state.start_calls, 1); assert.equal(fs.readFileSync(file, "utf8"), uri + "\n");
  state.stage = "panel.reopened_ready"; save();
  await wait(() => state.cancel_calls === 1 && !fs.existsSync(file));
  assert.equal(state.copy_calls, 1); assert(state.copy_exact); assert.equal(state.start_calls, 1);
  assert.equal(state.model_calls, 0);
  assert(state.caller_scope_verified);
  assert.equal((await call("url"))?.result?.kind, "error");
  await handler.dispose(); unregister(); unregister = undefined;
  unlisten(); unlisten = undefined;
  state.link_removed = true; state.native_complete = true; state.stage = "complete"; save();
  await booted.shutdown.shutdown(0);
} catch (error) {
  state.error = error?.code === "ERR_ASSERTION" ? "ASSERTION_FAILED" : "AUTH_PANEL_NATIVE_FAILED";
  state.error_location = state.stage; save();
  await handler?.dispose().catch(() => {});
  unregister?.();
  unlisten?.();
  if (booted) await booted.shutdown.shutdown(1); else process.exitCode = 1;
}
