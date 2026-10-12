// 固定现代worker入口：真实握手、封闭stdin引用、公开SDK模块，不接任意加载参数。
import { mkdirSync, realpathSync } from "node:fs";
import { dirname, join, resolve, relative, isAbsolute, sep } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { privateBytes, writePrivate } from "./private-files.ts";
import { strictJson } from "./strict-json.ts";
import { canonical, closed, digest } from "./managed-types.ts";
import { SupervisorClient, inheritedControlDirectory } from "./supervisor-client.ts";
import { resolveOfficialPackages } from "./official-launch.ts";
import { runOfficialDelegateWorker } from "./official-delegate-worker.ts";
const fail = () => { throw new Error("DELEGATE_MODERN_WORKER_FAILED"); };
const read = (path, cap) => strictJson(new TextDecoder("utf8", { fatal: true }).decode(privateBytes(path, cap)));
export async function officialDelegateMain(argv) {
  if (argv.length !== 2 || argv[0] !== "--input" || !isAbsolute(argv[1]) || resolve(argv[1]) !== argv[1]) fail();
  const worker = read(argv[1], 1024 * 1024);
  closed(worker, ["schema_version", "input", "reports", "runtime_root", "scoped_instance_root", "scoped_manifest", "budget", "logical_run_id"], ["resume_source_path"]);
  const { input } = worker, { request } = input;
  if (worker.schema_version !== 3 || input.definition_digest !== digest(Object.fromEntries(Object.entries(input).filter(([key]) => key !== "definition_digest")))
      || digest(input.execution_policy) !== request.execution_policy_digest || process.cwd() !== request.cwd) fail();
  const root = realpathSync(worker.runtime_root), installed = read(join(root, "runtime/profile.json"), 8 * 1024 * 1024);
  if (installed.schema_version !== 2 || installed.profile_id !== "pi-full" || installed.sdk_version !== "1.0.1"
      || installed.runtime_identity !== request.runtime_identity || installed.engine !== "node" || installed.toolchains.node !== process.version) fail();
  const supervisor = new SupervisorClient({ ...inheritedControlDirectory(), python: process.env.AGENTCFG_PYTHON, client: process.env.AGENTCFG_SUPERVISOR_CLIENT,
    endpoint: process.env.AGENTCFG_SUPERVISOR_ENDPOINT, capability: process.env.AGENTCFG_SUPERVISOR_CAPABILITY });
  delete process.env.AGENTCFG_SUPERVISOR_CAPABILITY;
  const owner = await supervisor.call("handshake", {});
  if (owner.role !== "worker" || owner.lease_id !== request.lease_id || owner.runtime_identity !== request.runtime_identity
      || owner.process_identity.pid !== process.pid) fail();
  const { sdkEntry, aiEntry } = resolveOfficialPackages({ installed, runtimeRoot: root });
  const coreEntry = fileURLToPath(import.meta.resolve("@earendil-works/pi-agent-core", pathToFileURL(sdkEntry).href));
  const tail = relative(dirname(join(root, installed.package_path)), realpathSync(coreEntry));
  if (isAbsolute(tail) || tail === ".." || tail.startsWith(".." + sep)) fail();
  const [sdk, ai, core] = await Promise.all([sdkEntry, aiEntry, coreEntry].map(path => import(pathToFileURL(path).href)));
  // 输入由原固定Python producer写入，报告另核其固定delegate run子目录。
  const reportTail = relative(join(dirname(dirname(dirname(worker.reports))), "model-delegate", "reports"), worker.reports);
  if (!isAbsolute(worker.reports) || reportTail !== request.run_id || !/^run-[0-9a-f]+$/.test(request.run_id)) fail();
  mkdirSync(worker.reports, { recursive: true, mode: 0o700 });
  const save = async (name, value) => {
    if (!/^(ready\.json|result\.json|session-v3\.json|final\.md|event-[0-9]{12}\.json|live-ack-[0-9a-f]{64}\.json)$/.test(name)) fail();
    const text = name === "final.md" ? value : canonical(value) + "\n";
    if (Buffer.byteLength(text) > 1024 * 1024) fail();
    writePrivate(join(worker.reports, name), text);
  };
  let pending = "", live, flight = false, failed = false;
  const receive = chunk => {
    pending += chunk.toString("utf8");
    if (Buffer.byteLength(pending) > 4096 || failed) { failed = true; process.stdin.pause(); return; }
    const end = pending.indexOf("\n");
    if (end < 0) return;
    const line = pending.slice(0, end); pending = pending.slice(end + 1);
    if (flight || pending || !live) { failed = true; process.stdin.pause(); return; }
    flight = true;
    Promise.resolve().then(async () => {
      const frame = strictJson(line);
      closed(frame, ["schema_version", "request_id", "action_key", "expected_physical_run_id", "input_ref"]);
      if (!/^[0-9a-f]{64}$/.test(frame.input_ref) || frame.input_ref !== frame.action_key) fail();
      const inputRoot = dirname(dirname(worker.reports));
      const action = read(join(inputRoot, "live-inputs-v3", frame.input_ref + ".json"), 1024 * 1024);
      await save("live-ack-" + frame.action_key + ".json", await live(frame, action));
    }).catch(() => { failed = true; }).finally(() => { flight = false; });
  };
  worker.owner = owner; worker.attachLive = callback => { live = callback; process.stdin.on("data", receive); };
  try {
    const result = await runOfficialDelegateWorker({ sdk, ai, core, worker, supervisor, save });
    return result.failed || failed ? 5 : 0;
  } finally { process.stdin.removeListener("data", receive); process.stdin.pause(); }
}
if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  officialDelegateMain(process.argv.slice(2)).then(code => { process.exitCode = code; })
    .catch(() => { process.stderr.write("DELEGATE_MODERN_WORKER_FAILED\n"); process.exitCode = 5; });
}
