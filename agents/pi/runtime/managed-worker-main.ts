// 监督者的固定 worker 入口；按冻结运行包解析 SDK 和 Task Keeper，不使用全局安装。
import { existsSync, mkdirSync, realpathSync } from "node:fs";
import { dirname, isAbsolute, join, relative, resolve, sep } from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath, pathToFileURL } from "node:url";
import { privateFile, writePrivate } from "./launch.ts";
import { SupervisorClient } from "./supervisor-client.ts";
import { runManagedWorker, validateWorkerInput } from "./managed-worker.ts";
import { createGuardedTools } from "./guarded-tools.ts";
import { createRouteFetch } from "./route-fetch.ts";
import { assertProcess, canonical, digest, reject } from "./managed-types.ts";

function inside(root, value) {
  const tail = relative(root, realpathSync(value));
  if (isAbsolute(tail) || tail === ".." || tail.startsWith(".." + sep)) reject("WORKER_MODULE_BOUNDARY", 5);
  return realpathSync(value);
}
function emptyCredentials() {
  return { async read() { return undefined; }, async list() { return []; },
    async modify() { reject("WORKER_CREDENTIAL_MODIFY_FORBIDDEN", 5); }, async delete() { reject("WORKER_CREDENTIAL_MODIFY_FORBIDDEN", 5); } };
}

export async function workerMain(argv) {
  if (argv.length !== 4 || argv[0] !== "--input" || argv[2] !== "--runtime-root" || !isAbsolute(argv[1]) || !isAbsolute(argv[3])) reject();
  const runtimeRoot = realpathSync(argv[3]);
  const installed = JSON.parse(privateFile(join(runtimeRoot, "runtime/profile.json")));
  const platform = process.platform + "-" + (process.arch === "x64" ? "x86_64" : process.arch);
  if (installed.engine !== "node" || process.version !== installed.toolchains.node || installed.platform !== platform
      || installed.sdk_package !== "@earendil-works/pi-coding-agent" || installed.sdk_version !== "0.84.4") reject("WORKER_RUNTIME_MISMATCH", 5);
  const input = validateWorkerInput(JSON.parse(privateFile(argv[1]))), { descriptor, context } = input;
  if (descriptor.runtime_digest !== installed.runtime_identity || process.env.AGENTCFG_EXECUTION_LEASE_ID !== context.lease_id
      || process.cwd() !== descriptor.cwd || join(context.database.root, context.database.filename) !== process.env.AGENTCFG_TASK_KEEPER_DATABASE) reject("WORKER_BINDING_MISMATCH", 4);
  const supervisor = new SupervisorClient({ python: process.env.AGENTCFG_PYTHON, client: process.env.AGENTCFG_SUPERVISOR_CLIENT,
    endpoint: process.env.AGENTCFG_SUPERVISOR_ENDPOINT, capability: process.env.AGENTCFG_SUPERVISOR_CAPABILITY });
  delete process.env.AGENTCFG_SUPERVISOR_CAPABILITY;
  const owner = await supervisor.call("handshake", {});
  if (owner.role !== "worker" || owner.runtime_identity !== installed.runtime_identity || owner.slice_identity !== installed.slice_identity) reject("WORKER_BINDING_MISMATCH", 4);
  assertProcess(owner.process_identity);
  if (owner.process_identity.pid !== process.pid) reject("WORKER_PROCESS_IDENTITY", 4);
  globalThis[Symbol.for("agentcfg.pi.runtime.v1")] = Object.freeze({ owner, installed, supervisor, runtimeRoot });
  const entry = inside(runtimeRoot, join(runtimeRoot, installed.entrypoint));
  const require = createRequire(entry);
  const sdk = await import(pathToFileURL(entry).href);
  const packagePath = inside(runtimeRoot, require.resolve("starter-pi-task-keeper/package.json"));
  const packageRoot = dirname(packagePath);
  const { createJiti } = await import(pathToFileURL(inside(runtimeRoot, require.resolve("jiti"))).href);
  const moduleLoader = createJiti(entry, { moduleCache: false });
  const load = name => moduleLoader.import(inside(runtimeRoot, join(packageRoot, name)));
  const [{ Store }, { RequestLedger }, { TaskLedgerStore }, { ChildReporter }, { ManagedHttpTransport }] = await Promise.all([
    load("src/store/database.ts"), load("src/store/request-ledger.ts"), load("src/store/request-ledger-store.ts"), load("src/adapters/child-reporter.ts"), load("src/adapters/http-transport.ts"),
  ]);
  if (!existsSync(join(context.database.root, context.database.filename))) reject("WORKER_DATABASE_MISSING", 4);
  const store = new Store(context.database.root, context.database.filename);
  let routeFetch;
  try {
    store.assertOwner(context.database.owner);
    const saved = store.get("agentcfg-descriptors-v1", descriptor.attempt_id);
    if (!saved || canonical(saved) !== canonical(descriptor)) reject("WORKER_ATTEMPT_MISMATCH", 4);
    const authorize = async () => {
      store.assertOwner(context.database.owner);
      const result = await supervisor.call("authorize", { lease_id: context.lease_id, grant_generation: descriptor.grant_generation });
      if (!result.valid) reject("GRANT_STALE", 4);
    };
    let tokenBounds = null;
    const ledger = new RequestLedger({ store: new TaskLedgerStore(store, context.database.owner, descriptor.task_id),
      task_id: descriptor.task_id, budget_scope_id: descriptor.budget_scope_id, minimum_remaining: context.minimum_remaining,
      limits: { model_requests: descriptor.request_ceiling, model_turns: descriptor.turn_ceiling, deadline: descriptor.deadline,
        ...(descriptor.token_limit === undefined ? {} : { token_limit: descriptor.token_limit }),
        ...(descriptor.cost_limit === undefined ? {} : { cost_limit: descriptor.cost_limit }) },
      verify: request => { store.assertOwner(context.database.owner); return { valid: request.grant_digest === digest(descriptor),
        route_id: descriptor.route_id, grant_digest: digest(descriptor),
        bounds_certified: tokenBounds !== null && descriptor.cost_limit === undefined
          && request.reserved_input_tokens === tokenBounds.input_tokens && request.reserved_output_tokens === tokenBounds.output_tokens }; } });
    await authorize();
    const agentDir = process.env.PI_CODING_AGENT_DIR;
    const modelRuntime = await sdk.ModelRuntime.create({ credentials: emptyCredentials(), modelsPath: join(agentDir, "models.json"),
      allowModelNetwork: false, refreshOnCreate: false });
    const modelDeclaration = JSON.parse(privateFile(join(agentDir, "models.json"))).providers[descriptor.provider_id].models[0];
    if ([modelDeclaration.contextWindow, modelDeclaration.maxTokens].every(value => Number.isSafeInteger(value) && value > 0)) {
      tokenBounds = { input_tokens: modelDeclaration.contextWindow, output_tokens: modelDeclaration.maxTokens, cost: null };
    }
    if (descriptor.cost_limit !== undefined || descriptor.token_limit !== undefined && tokenBounds === null) reject("UNBOUNDED_REQUEST", 2);
    routeFetch = await createRouteFetch(context.route, { proxyAgent: async (url, protocol) => {
      const name = protocol === "https:" ? "https-proxy-agent" : "http-proxy-agent";
      const module = await import(pathToFileURL(inside(runtimeRoot, require.resolve(name))).href);
      const authorization = process.env.AGENTCFG_PI_PROXY_AUTHORIZATION;
      if (authorization && /[\r\n]/.test(authorization)) reject("PROXY_CREDENTIAL_INVALID", 3);
      return new (protocol === "https:" ? module.HttpsProxyAgent : module.HttpProxyAgent)(url,
        authorization ? { headers: { "Proxy-Authorization": authorization } } : {});
    } });
    const reports = join(process.env.HOME, "reports");
    mkdirSync(reports, { mode: 0o700 });
    const recordEvent = event => writePrivate(join(reports,
      "event-" + digest(event.producer_id) + "-" + String(event.sequence).padStart(12, "0") + ".json"), canonical(event) + "\n");
    let transportSequence = 0;
    let structured = null;
    const observation = new ChildReporter(descriptor, owner.process_identity);
    const transport = new ManagedHttpTransport({ descriptor, route: context.route, ledger, fetchRoute: routeFetch,
      bounds: payload => {
        if (tokenBounds) {
          const output = payload.max_tokens ?? payload.max_completion_tokens;
          if (!Number.isSafeInteger(output) || output < 1 || output > tokenBounds.output_tokens) reject("UNBOUNDED_REQUEST", 5);
        }
        return tokenBounds ?? { input_tokens: null, output_tokens: null, cost: null };
      },
      report: async value => {
        observation.response(value);
        writePrivate(join(reports, "request-" + value.request_id + "-" + value.phase + ".json"), canonical(value) + "\n");
        recordEvent({ task_id: descriptor.task_id, step_id: descriptor.step_id, attempt_id: descriptor.attempt_id,
          manager_run_id: context.manager_run_id, producer_id: "transport-" + descriptor.attempt_id, sequence: ++transportSequence,
          event_id: value.request_id + "-" + value.phase, phase: value.phase, request_id: value.request_id, ordinal: value.ordinal ?? null,
          usage_id: value.usage_id ?? null, process_identity: owner.process_identity,
          active_tool_ids: [], external_work_ids: [], candidate_digest: observation.candidateDigest, result_digest: null, termination_confirmed: false });
      },
      observePayload: value => observation.delivered(value) });
    const tools = createGuardedTools({ descriptor, context, supervisor,
      submitResult: async (value, association) => {
        if (structured !== null && digest(structured.value) !== association.value_digest) reject("STRUCTURED_RESULT_CONFLICT", 4);
        structured = { value, ...association };
        writePrivate(join(reports, "structured.json"), canonical(structured) + "\n");
      } });
    await runManagedWorker({ sdk, input, agentDir, modelRuntime, transport, tools, supervisor, observation,
      report: async value => {
        if (value.event) recordEvent(value.event);
        else {
          if (value.result.state === "execution_settled" && descriptor.allowed_tools.includes("structured_output") && structured === null) reject("EVIDENCE_MISSING", 5);
          writePrivate(join(reports, "result.json"), canonical({ ...value.result, structured_result: structured, observation: observation.snapshot() }) + "\n");
        }
      } });
  } finally { routeFetch?.close(); store.close(); }
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  workerMain(process.argv.slice(2)).catch(error => { process.stderr.write("MANAGED_WORKER_FAILED\n"); process.exitCode = [2, 3, 4, 5, 6].includes(error.exitCode) ? error.exitCode : 5; });
}
