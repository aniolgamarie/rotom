// 启动实际 OAuth 插件；/auth 由 PTY 输入，不注册或替换任何认证处理器。
import fs from "node:fs";
import path from "node:path";
import assert from "node:assert/strict";
import diagnostics from "node:diagnostics_channel";
import { createRequire } from "node:module";
import { pathToFileURL } from "node:url";
const root = process.env.AGENTCFG_AUTH_PANEL_ROOT;
const output = process.env.AGENTCFG_AUTH_PANEL_RESULT;
const runtime = process.argv[2];
assert(process.execArgv.includes("--use-env-proxy"));
assert(process.env.HTTPS_PROXY?.startsWith("http://127.0.0.1:") && process.env.NO_PROXY === ""
  && process.env.NODE_EXTRA_CA_CERTS?.startsWith(root + "/"));
assert(root?.startsWith("/dev/shm/") && output?.startsWith(root + "/") && path.isAbsolute(runtime));
assert(["HOME", "DSH_HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME", "TMPDIR"]
  .every(name => process.env[name]?.startsWith(root + "/")));
const require = createRequire(path.join(runtime, "package.json"));
const moduleAt = name => import(pathToFileURL(require.resolve(name)).href);
const state = { kind: "native-pty-auth-real-codex-device-retry", nonce: process.env.AGENTCFG_AUTH_PANEL_NONCE,
  stage: "host.boot", model_calls: 0, remote_http_requests: 0, local_http_requests: 0, background_version_requests: 0, fixture_oauth_requests: 0 };
const save = () => {
  fs.writeFileSync(output + ".tmp", JSON.stringify(state, null, 2) + "\n", { mode: 0o600 });
  fs.renameSync(output + ".tmp", output);
};
const wait = async test => {
  for (let i = 0; i < 6000 && !test(); i++) await new Promise(resolve => setTimeout(resolve, 10));
  assert(test());
};
let booted; let unlisten;
const requestChannel = diagnostics.channel("undici:request:create");
const onRequest = ({ request }) => {
  // 原生启动会查询 npm 版本；这不属于 OAuth 或模型请求。只允许其 GET。
  // 授权 URL、path、headers、body 与 PKCE 均不保存。
  const hostname = new URL(String(request.origin)).hostname;
  if (["127.0.0.1", "localhost", "[::1]"].includes(hostname)) state.local_http_requests++;
  else if (hostname === "auth.openai.com" && request.method === "POST"
      && ["/api/accounts/deviceauth/usercode", "/api/accounts/deviceauth/token"].includes(request.path)
      && state.fixture_oauth_requests < 30) state.fixture_oauth_requests++;
  else if (hostname === "registry.npmjs.org" && request.method === "GET"
      && request.path.includes("deepseek-harness-tui") && request.path.endsWith("/latest")
      && state.background_version_requests < 2) state.background_version_requests++;
  else {
    state.remote_http_requests++;
    state.unexpected_request = {hostname, method: request.method, stage: state.stage};
    state.error = "REMOTE_REQUEST_OBSERVED";
  }
  save();
};
requestChannel.subscribe(onRequest);
try {
  save();
  const { runProfile } = await moduleAt("@deepseek-ai/dsh/profile-boot");
  const { createLaunchEnvironmentSnapshot } = await moduleAt("@deepseek-ai/dsh-launch-environment");
  process.env.DSH_TUI_WORKSPACE_TARGET = process.cwd();
  booted = await runProfile({ environment: createLaunchEnvironmentSnapshot([{ source: "process", values: process.env }]),
    profile: "agentcfg", patchFiles: [process.env.AGENTCFG_AUTH_PANEL_PATCH], args: [],
    packageManager: { command: process.execPath, args: [process.env.AGENTCFG_AUTH_PANEL_LAUNCHER, "--deny-package-operation"], env: {} } });
  const { ctx } = booted;
  unlisten = ctx.on("llm/stream", () => { state.model_calls++; save(); throw new Error("Model calls forbidden"); });
  await wait(() => ctx.get("agents").list().length > 0 && ctx.get("dshAuth")?.api);
  const api = ctx.get("dshAuth").api;
  assert((await api.providers()).some(row => row.provider === "openai-codex" && !row.signedIn));
  state.stage = "host.agent_ready"; save();
  await wait(() => state.error || fs.existsSync(process.env.AGENTCFG_AUTH_PANEL_READY)
    && fs.readFileSync(process.env.AGENTCFG_AUTH_PANEL_READY, "utf8") === "done\n");
  state.signed_in = (await api.providers()).some(row => row.signedIn);
  state.credential_file_created = fs.existsSync(path.join(process.env.DSH_HOME, "dsh-auth", "credentials.json"));
  assert(!state.signed_in && !state.credential_file_created && !state.error);
  unlisten(); unlisten = undefined;
  state.native_complete = true; state.stage = "complete"; save();
  await booted.shutdown.shutdown(0);
} catch (error) {
  state.error ??= error?.code === "ERR_ASSERTION" ? "ASSERTION_FAILED" : "NATIVE_DEVICE_FAILED";
  state.error_location = state.stage; save(); unlisten?.();
  if (booted) await booted.shutdown.shutdown(1); else process.exitCode = 1;
} finally {
  requestChannel.unsubscribe(onRequest);
}
