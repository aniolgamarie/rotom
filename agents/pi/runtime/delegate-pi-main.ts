import { cursorDelegateTransport } from "./cursor-delegate.ts";
import { assertSessionCompatibility } from "./session-compatibility.ts";
// 固定 Pi 委托入口，不能作为通用 argv/模块加载器。
import { mkdirSync, realpathSync, readFileSync } from "node:fs";
import { dirname, isAbsolute, join, relative, resolve, sep } from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath, pathToFileURL } from "node:url";
import { privateFile, writePrivate } from "./launch.ts";
import { SupervisorClient } from "./supervisor-client.ts";
import { createGuardedTools } from "./guarded-tools.ts";
import { createRouteFetch } from "./route-fetch.ts";
import { runPiDelegate } from "./delegate-pi.ts";
import { canonical, digest, reject } from "./managed-types.ts";

export async function delegateMain(argv) {
  if (argv.length !== 2 || argv[0] !== "--input" || !isAbsolute(argv[1])) reject();
  const worker = JSON.parse(privateFile(argv[1])), { input } = worker, { request, grant } = input;
  if (request.execution_boundary !== "agentcfg-tools" || input.execution_policy?.boundary !== "agentcfg-tools"
      || digest(input.execution_policy) !== request.execution_policy_digest
      || digest(input.execution_policy.file_policy) !== request.policy_digest
      || "native_execution" in input.execution_policy
      || input.definition_digest !== digest(Object.fromEntries(Object.entries(input).filter(([key]) => key !== "definition_digest")))) {
    reject("DELEGATE_EXECUTION_POLICY_MISMATCH", 4);
  }
  const runtime = realpathSync(worker.runtime_root);
  const installed = JSON.parse(privateFile(join(runtime, "runtime/profile.json")));
  const engineMatches = installed.engine === "bun" ? globalThis.Bun?.version === installed.toolchains.bun : installed.engine === "node" && process.version === installed.toolchains.node;
  if (request.runtime_identity !== installed.runtime_identity || !engineMatches
      || installed.sdk_version !== "0.84.4" || process.cwd() !== request.cwd) reject("DELEGATE_RUNTIME_MISMATCH", 5);
  const inside = value => { const path = realpathSync(value), tail = relative(runtime, path);
    if (isAbsolute(tail) || tail === ".." || tail.startsWith(".." + sep)) reject("DELEGATE_MODULE_BOUNDARY", 5); return path; };
  const supervisor = new SupervisorClient({ python: process.env.AGENTCFG_PYTHON, client: process.env.AGENTCFG_SUPERVISOR_CLIENT,
    endpoint: process.env.AGENTCFG_SUPERVISOR_ENDPOINT, capability: process.env.AGENTCFG_SUPERVISOR_CAPABILITY });
  delete process.env.AGENTCFG_SUPERVISOR_CAPABILITY;
  const owner = await supervisor.call("handshake", {});
  if (owner.role !== "worker" || owner.lease_id !== request.lease_id || owner.process_identity.pid !== process.pid
      || owner.runtime_identity !== request.runtime_identity) reject("DELEGATE_PROCESS_IDENTITY", 4);
  globalThis[Symbol.for("agentcfg.pi.runtime.v1")] = Object.freeze({ owner, supervisor, installed, runtimeRoot: runtime });
  const sdkEntry = inside(join(runtime, installed.entrypoint)), sdk = await import(pathToFileURL(sdkEntry).href), require = createRequire(sdkEntry);
  const agentDir = process.env.PI_CODING_AGENT_DIR;
  const empty = { async read() { return undefined; }, async list() { return []; }, async modify() { reject("DELEGATE_AUTH_MODIFY_DENIED", 5); }, async delete() { reject("DELEGATE_AUTH_MODIFY_DENIED", 5); } };
  const modelsPath = join(agentDir, "models.json");
  const modelRuntime = await sdk.ModelRuntime.create({ credentials: empty, modelsPath, allowModelNetwork: false, refreshOnCreate: false });
  let nativeTransport = null;
  let auth = null;
  if (worker.auth_binding) {
    const binding = worker.auth_binding;
    if (binding.kind !== "oauth-access" || binding.provider_id !== request.requested_model.provider_id || !/^AGENTCFG_PI_CREDENTIAL_[A-F0-9]{16}$/.test(binding.environment)) reject("DELEGATE_AUTH_BINDING", 4);
    auth = { provider_id: binding.provider_id, apiKey: process.env[binding.environment], expires_at_ms: binding.expires_at_ms };
    delete process.env[binding.environment];
  }
  if (request.requested_model.provider_id === "cursor") {
    if (installed.engine !== "bun" || !auth || input.route.mode !== "direct" || input.retry_limit !== 0 || !worker.cursor_endpoint) reject("CURSOR_DELEGATE_UNBOUND", 5);
    const cursorEntry = inside(require.resolve("@rahularya01/pi-cursor"));
    const cursorPackage = JSON.parse(readFileSync(inside(join(dirname(dirname(cursorEntry)), "package.json")), "utf8"));
    if (cursorPackage.version !== "1.4.29") reject("CURSOR_DELEGATE_VERSION", 5);
    const plugin = await import(pathToFileURL(cursorEntry).href);
    const ai = await import(pathToFileURL(inside(require.resolve("@earendil-works/pi-ai"))).href);
    const http2 = (await import("node:http2")).default;
    nativeTransport = await cursorDelegateTransport({ plugin: plugin.default, modelRuntime, http2,
      createStream: ai.createAssistantMessageEventStream, selected: request.requested_model, endpoint: worker.cursor_endpoint, accessToken: auth.apiKey });
  }
  const declaration = modelRuntime.getModel(request.requested_model.provider_id, request.requested_model.model_id);
  if (!declaration) reject("DELEGATE_MODEL_UNBOUND", 5);
  const route = { id: input.route.id, type: input.route.mode, base_url: declaration.baseUrl, proxy_url: input.route.proxy_url ?? null };
  const fetchRoute = await createRouteFetch(route, { proxyAgent: async (url, protocol) => {
    const name = protocol === "https:" ? "https-proxy-agent" : "http-proxy-agent";
    const module = await import(pathToFileURL(inside(require.resolve(name))).href);
    const authorization = process.env.AGENTCFG_PI_PROXY_AUTHORIZATION;
    if (authorization && /[\r\n]/.test(authorization)) reject("DELEGATE_PROXY_CREDENTIAL", 3);
    return new (protocol === "https:" ? module.HttpsProxyAgent : module.HttpProxyAgent)(url, authorization ? { headers: { "Proxy-Authorization": authorization } } : {});
  } });
  const reports = worker.reports; mkdirSync(reports, { recursive: true, mode: 0o700 });
  const save = (name, value) => writePrivate(join(reports, name), canonical(value) + "\n");
  save("ready.json", { ready: true, run_id: request.run_id, lease_id: request.lease_id, request_digest: request.request_digest });
  if (worker.resume_token) assertSessionCompatibility(worker.resume_token, join(worker.instance_root, "pi-home/model-delegate/reports", request.continuation_of, "sessions"));
  const sessionManager = worker.resume_token ? sdk.SessionManager.forkFrom(worker.resume_token, request.cwd, join(reports, "sessions"))
    : sdk.SessionManager.create(request.cwd, join(reports, "sessions"));
  const tools = createGuardedTools({ descriptor: { attempt_id: request.attempt_id, grant_generation: request.grant_generation, allowed_tools: grant.allowed_tools }, context: { lease_id: request.lease_id },
    supervisor: { call: (_method, args) => supervisor.call("delegate_file_action", { ...args, run_id: request.run_id }) } });
  let result;
  try {
    result = await runPiDelegate({ sdk, input, modelRuntime, agentDir, sessionManager, tools, supervisor, auth, nativeTransport,
      fetchRoute: Object.assign((url, options) => fetchRoute(url, options, route), { close: fetchRoute.close }),
      report: async ({ event }) => save("event-" + String(event.seq).padStart(12, "0") + ".json", event) });
    writePrivate(join(reports, "final.md"), result.final);
  } catch {
    result = { host_completed: false, observed_model: null, resume_token: sessionManager.getSessionFile() ?? null,
      usage: { input_tokens: null, output_tokens: null, cost: null }, feedback_dispositions: [] };
  }
  const { final, ...facts } = result;
  save("result.json", { schema_version: 2, run_id: request.run_id, attempt_id: request.attempt_id, request_digest: request.request_digest,
    process_identity: owner.process_identity, ...facts });
  await modelRuntime.dispose?.();
  return result.host_completed ? 0 : 5;
}
if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  delegateMain(process.argv.slice(2)).then(code => { process.exitCode = code; }).catch(() => { process.stderr.write("DELEGATE_PI_FAILED\n"); process.exitCode = 5; });
}
