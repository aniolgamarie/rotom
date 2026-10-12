// 纯公开 API mock；复制自有源码到临时 fixture，绝不挂载宿主或执行真实登录。
import fs from "node:fs";
import path from "node:path";
import os from "node:os";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { fileURLToPath, pathToFileURL } from "node:url";

const runtime = process.argv[2];
if (!runtime || !path.isAbsolute(runtime)) throw new Error("Specify an installed dependency runtime");
const repo = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const root = fs.mkdtempSync(path.join(os.tmpdir(), "rotom-cursor-panel-"));
for (const [name, suffix] of Object.entries({ HOME: "home", DSH_HOME: "dsh", XDG_CONFIG_HOME: "config", XDG_DATA_HOME: "data", XDG_CACHE_HOME: "cache" })) {
  process.env[name] = path.join(root, suffix);
  fs.mkdirSync(process.env[name], { mode: 0o700 });
}
const require = createRequire(path.join(runtime, "package.json"));
const fixture = path.join(root, "adapter");
fs.mkdirSync(fixture, { mode: 0o700 });
for (const name of ["index.mjs", "package.json"]) fs.copyFileSync(path.join(repo, "agents/dsh/packages/cursor-terminal", name), path.join(fixture, name));
for (const name of ["dsh-cursor-subscription", "@deepseek-harness-tui/dsh-tui"]) {
  const target = path.join(fixture, "node_modules", name);
  fs.mkdirSync(path.dirname(target), { recursive: true });
  fs.symlinkSync(path.dirname(require.resolve(name + "/package.json")), target);
}
fs.writeFileSync(path.join(fixture, "bridge.mjs"), 'export { QuestionBridge } from "@deepseek-harness-tui/dsh-tui/oauth";\n');
const { createLoginHandler, LoginLinkStore, resolveLoginAsk } = await import(pathToFileURL(path.join(fixture, "index.mjs")));
const { QuestionBridge } = await import(pathToFileURL(path.join(fixture, "bridge.mjs")));
const url = "https://cursor.com/cli/login?challenge=" + "a".repeat(330) + "&uuid=synthetic-test";
const handlers = [];
let unhandled = 0;
process.on("unhandledRejection", () => { unhandled++; });
let stage = "start";
const checks = {};
const waitFor = async predicate => {
  for (let i = 0; i < 100 && !predicate(); i++) await new Promise(resolve => setTimeout(resolve, 10));
  assert(predicate());
};
const invocation = (verb, signal = new AbortController().signal) => ({ rawInput: verb, signal });
function scenario(name, overrides = {}) {
  const home = path.join(root, name);
  fs.mkdirSync(home, { mode: 0o700 });
  const state = { starts: 0, cancels: 0, phase: "waiting_browser", authenticated: false, paused: 0, resumed: 0, errors: {}, questions: [], copies: [], opens: [] };
  const file = path.join(home, "cursor-login-url.txt");
  const coordinator = {
    start: async () => { state.starts++; return { id: name, phase: state.phase, authenticated: state.authenticated, authUrl: url }; },
    read: () => ({ id: name, phase: state.phase, authenticated: state.authenticated }),
    cancel: async () => { state.cancels++; state.phase = "cancelled"; },
    accountStatus: async () => { if (state.errors.status) throw new Error("synthetic hidden status body"); return { authenticated: state.authenticated, expiresAt: Date.now() + 10000 }; },
    logout: async () => { if (state.errors.logout) throw new Error("synthetic hidden logout body"); state.authenticated = false; },
  };
  const adapter = { cancelRequests: () => { state.paused++; }, resumeRequests: () => { state.resumed++; },
    listModelsForRpc: async () => { if (state.errors.models) throw new Error("synthetic hidden model body"); return Array.from({ length: 60 }, () => ({ id: "long-synthetic-model-id" })); } };
  const ask = request => new Promise((resolve, reject) => {
    const row = { request, answer: selected => { request.signal?.removeEventListener("abort", abort); resolve({ answers: [{ selected: [selected] }] }); } };
    const abort = () => reject(Object.assign(new Error("synthetic ask cancellation"), { code: "ASK_CANCELLED" }));
    request.signal?.addEventListener("abort", abort, { once: true });
    state.questions.push(row);
  });
  const store = new LoginLinkStore(file);
  const handler = createLoginHandler(coordinator, adapter, { linkStore: store, resolveAsk: () => ask,
    bridgeFactory: (request, abort) => new QuestionBridge(request, abort, { openUrl: value => { state.opens.push(value); return false; },
      copyText: async value => { state.copies.push(value); return true; } }), ...overrides });
  handlers.push(handler);
  return { state, file, handler, coordinator, store, ask };
}
try {
  stage = "public-command-caller-scope";
  const agent = { id: "fake-caller" };
  const request = { questions: [{ detail: "fake question" }], signal: new AbortController().signal };
  let routed;
  const context = { get: name => { assert.equal(name, "userQuestions"); return { ask: value => { routed = value; return "fake answer"; } }; } };
  assert.equal(resolveLoginAsk(context, { agent })(request), "fake answer");
  assert.equal(routed.agent, agent);
  assert.equal(routed.signal, request.signal);
  assert.equal(routed.questions, request.questions);
  assert.equal(resolveLoginAsk(context, {}), undefined);
  assert.equal(resolveLoginAsk({ get: () => undefined }, { agent }), undefined);
  checks.public_command_caller_scope = "PASS";
  stage = "long-url-copy-reopen";
  const first = scenario("first");
  const start = await first.handler(invocation("start"));
  assert(start.text.length <= 200 && !start.text.includes(url) && !start.text.includes("https://"));
  assert(start.text.includes(first.file));
  await waitFor(() => first.state.questions.length === 1);
  assert(first.state.questions[0].request.questions[0].detail.includes(url));
  assert.equal(fs.readFileSync(first.file, "utf8"), url + "\n");
  assert.equal(fs.statSync(first.file).mode & 0o777, 0o600);
  const choose = (row, index) => row.answer(row.request.questions[0].options[index].label);
  choose(first.state.questions[0], 0);
  await waitFor(() => first.state.copies.length === 1 && first.state.questions.length === 2);
  assert.equal(first.state.copies[0], url);
  choose(first.state.questions[1], 1);
  await waitFor(() => first.state.questions.length === 3);
  assert(first.state.opens.every(value => value === url));
  const mtime = fs.statSync(first.file).mtimeMs;
  await first.handler(invocation("url"));
  await first.handler(invocation("start"));
  assert.equal(first.state.starts, 1);
  assert.equal(first.state.cancels, 0);
  assert.equal(fs.statSync(first.file).mtimeMs, mtime);
  assert.equal(fs.readFileSync(first.file, "utf8"), url + "\n");
  checks.complete_copy_and_same_flow_reopen = "PASS";

  stage = "status-model-errors-retain-login";
  first.state.errors.status = true; first.state.errors.models = true;
  assert.equal((await first.handler(invocation("status"))).kind, "error");
  assert.equal((await first.handler(invocation("models"))).kind, "error");
  assert.equal(first.state.cancels, 0);
  assert(fs.existsSync(first.file));
  first.state.errors = {};
  const models = await first.handler(invocation("models"));
  const status = await first.handler(invocation("status"));
  assert(models.text.length <= 200 && models.text.includes("60") && !models.text.includes("long-synthetic-model-id"));
  assert(status.text.length <= 200 && status.text.includes("waiting_browser") && status.text.includes("expiry") && status.text.includes("usage unknown"));
  checks.other_command_error_isolation = "PASS";

  stage = "native-panel-cancel";
  await waitFor(() => first.state.questions.at(-1).request.signal.aborted === false);
  choose(first.state.questions.at(-1), 2);
  await waitFor(() => first.state.cancels === 1 && !fs.existsSync(first.file));
  assert.equal((await first.handler(invocation("url"))).kind, "error");
  checks.native_cancel = "PASS";

  stage = "terminal-failure-and-success-cleanup";
  for (const phase of ["failed", "authenticated"]) {
    const test = scenario("terminal-" + phase);
    await test.handler(invocation("start"));
    test.state.phase = phase; test.state.authenticated = phase === "authenticated";
    await waitFor(() => !fs.existsSync(test.file));
    assert.equal(test.state.cancels, 0);
    assert.equal((await test.handler(invocation("url"))).kind, "error");
  }
  checks.terminal_cleanup = "PASS";

  stage = "logout-refresh-failure-and-pause";
  const signedOut = scenario("signed-out"); signedOut.state.errors.models = true;
  assert.equal((await signedOut.handler(invocation("logout"))).kind, "success");
  assert.equal(signedOut.state.resumed, 1);
  const failedLogout = scenario("failed-logout"); failedLogout.state.errors.logout = true;
  assert.equal((await failedLogout.handler(invocation("logout"))).kind, "error");
  assert.equal(failedLogout.state.resumed, 0);
  assert((await failedLogout.handler(invocation("status"))).text.includes("requests paused"));
  failedLogout.state.errors = {};
  await failedLogout.handler(invocation("start"));
  failedLogout.state.phase = "authenticated"; failedLogout.state.authenticated = true;
  await waitFor(() => failedLogout.state.resumed === 1);
  assert((await failedLogout.handler(invocation("status"))).text.includes("requests ready"));
  checks.logout_recovery = "PASS";

  stage = "concurrent-start-and-panel-failure";
  const concurrent = scenario("concurrent");
  await Promise.all([concurrent.handler(invocation("start")), concurrent.handler(invocation("start"))]);
  assert.equal(concurrent.state.starts, 1); assert.equal(concurrent.state.cancels, 0);
  let failPanel = false;
  const badPanel = scenario("panel-failure", { resolveAsk: () => { if (failPanel) throw new Error("synthetic view error"); return concurrent.ask; } });
  await badPanel.handler(invocation("start"));
  failPanel = true;
  assert.equal((await badPanel.handler(invocation("url"))).kind, "error");
  assert.equal(badPanel.state.cancels, 0);
  assert(fs.existsSync(badPanel.file));
  const controllers = [];
  let factoryFails = false;
  const factory = scenario("factory-failure", { bridgeFactory: (request, abort) => {
    if (factoryFails) throw new Error("synthetic panel factory failure");
    controllers.push(abort);
    return new QuestionBridge(request, abort, { openUrl: () => false, copyText: async () => true });
  } });
  await factory.handler(invocation("start"));
  factoryFails = true;
  assert.equal((await factory.handler(invocation("start"))).kind, "error");
  assert.equal(factory.state.starts, 1); assert.equal(factory.state.cancels, 0); assert(fs.existsSync(factory.file));
  factoryFails = false;
  await factory.handler(invocation("url"));
  controllers[0].abort();
  await new Promise(resolve => setTimeout(resolve, 20));
  assert.equal(factory.state.cancels, 0); assert(fs.existsSync(factory.file));
  factory.state.phase = "authenticated"; factory.state.authenticated = true;
  await waitFor(() => !fs.existsSync(factory.file));
  factory.state.phase = "waiting_browser";
  const newer = url + "&generation=new";
  factory.coordinator.start = async () => { factory.state.starts++; return { id: "new-flow", authUrl: newer, phase: "waiting_browser" }; };
  await factory.handler(invocation("start"));
  controllers[1].abort();
  await new Promise(resolve => setTimeout(resolve, 20));
  assert.equal(fs.readFileSync(factory.file, "utf8"), newer + "\n");
  assert.equal(factory.state.cancels, 0);
  checks.concurrent_and_reopen_error_isolation = "PASS";

  stage = "fallback-file-and-drift";
  const fallback = scenario("fallback", { resolveAsk: () => undefined });
  const response = await fallback.handler(invocation("start"));
  assert(response.text.length <= 200 && response.text.includes(fallback.file));
  fs.writeFileSync(fallback.file, "user modified file\n");
  assert((await fallback.handler(invocation("cancel"))).text.includes("retained"));
  assert.equal(fs.readFileSync(fallback.file, "utf8"), "user modified file\n");
  const foreign = path.join(root, "foreign"); fs.writeFileSync(foreign, "outside sentinel\n");
  const symlink = scenario("symlink", { resolveAsk: () => undefined }); fs.symlinkSync(foreign, symlink.file);
  await symlink.handler(invocation("start")); await symlink.handler(invocation("cancel"));
  assert.equal(fs.readFileSync(foreign, "utf8"), "outside sentinel\n"); assert(fs.lstatSync(symlink.file).isSymbolicLink());
  const unsafe = path.join(root, "unsafe-parent"); fs.symlinkSync(path.dirname(fallback.file), unsafe);
  assert.throws(() => new LoginLinkStore(path.join(unsafe, "other.txt")).save(url));
  const owner = scenario("owner", { resolveAsk: () => undefined });
  await owner.handler(invocation("start"));
  const unrelated = scenario("unrelated", { resolveAsk: () => undefined, linkStore: new LoginLinkStore(owner.file) });
  await unrelated.handler(invocation("start")); await unrelated.handler(invocation("cancel"));
  assert.equal(fs.readFileSync(owner.file, "utf8"), url + "\n");
  await owner.handler(invocation("cancel")); assert(!fs.existsSync(owner.file));
  checks.private_file_and_drift_protection = "PASS";

  stage = "dispose-and-late-start";
  const disposed = scenario("dispose"); await disposed.handler(invocation("start")); await disposed.handler.dispose();
  assert.equal(disposed.state.cancels, 1); assert(!fs.existsSync(disposed.file));
  let resolveStart;
  const late = scenario("late-start");
  late.coordinator.start = () => new Promise(resolve => { resolveStart = resolve; });
  const pending = late.handler(invocation("start")); await waitFor(() => resolveStart !== undefined);
  const closing = late.handler.dispose();
  resolveStart({ id: "late-start", authUrl: url, phase: "waiting_browser" });
  await pending; await closing; assert(!fs.existsSync(late.file)); assert.equal(late.state.cancels, 1);
  await Promise.all(handlers.map(handler => handler.dispose()));
  await new Promise(resolve => setTimeout(resolve, 30)); assert.equal(unhandled, 0);
  checks.dispose_late_callback_and_no_unhandled_rejection = "PASS";
  console.log(JSON.stringify({ kind: "pure-public-QuestionBridge-no-host-no-account", checks, long_url_chars: url.length, unhandled_rejections: unhandled }));
} catch {
  console.error(JSON.stringify({ kind: "pure-public-QuestionBridge-no-host-no-account", error: "AUTH_PANEL_MOCK_FAILED", stage, checks }));
  process.exitCode = 1;
} finally {
  await Promise.allSettled(handlers.map(handler => handler.dispose()));
  fs.rmSync(root, { recursive: true, force: true });
}
