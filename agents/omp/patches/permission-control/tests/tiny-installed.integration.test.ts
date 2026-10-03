import { afterEach, expect, test } from "bun:test";
import * as fs from "node:fs";
import * as path from "node:path";
import { getTinyModelsCacheDir } from "@oh-my-pi/pi-utils";
import { declareWorkerHostEntry } from "@oh-my-pi/pi-utils/worker-host";
import { createTinyInstalledOnly, inspectInstalledTiny, PERMISSION_TINY_WORKER } from "../src/permission-control/tiny-installed";
import { loadInstalledTinyPipeline } from "../src/permission-control/tiny-installed-worker";

const spawn = Bun.spawn;
const version = "4.3.0";
const previousVersion = process.env.PI_TINY_TRANSFORMERS_VERSION;
const roots: string[] = [];
afterEach(() => {
  Bun.spawn = spawn;
  if (previousVersion === undefined) delete process.env.PI_TINY_TRANSFORMERS_VERSION;
  else process.env.PI_TINY_TRANSFORMERS_VERSION = previousVersion;
  for (const root of roots.splice(0)) fs.rmSync(root, { recursive: true, force: true });
});
function install(cacheRoot?: string) {
  const root = cacheRoot ?? path.join(fs.mkdtempSync(path.join(process.env.HOME!, "tiny-fixture-")), "tiny-models");
  expect(root.startsWith(process.env.HOME! + path.sep)).toBe(true);
  const model = path.join(root, "LiquidAI/LFM2.5-230M-ONNX");
  const runtime = path.join(path.dirname(root), "tiny-title-runtime", `transformers-${version}`);
  roots.push(model, runtime);
  const files = {
    [path.join(model, "config.json")]: '{"model_type":"lfm2"}',
    [path.join(model, "tokenizer_config.json")]: "{}",
    [path.join(model, "tokenizer.json")]: "synthetic tokenizer",
    [path.join(model, "onnx/model_q4.onnx")]: "synthetic model: never execute",
    [path.join(runtime, "node_modules/@huggingface/transformers/package.json")]: JSON.stringify({ version, main: "./dist/transformers.node.cjs" }),
    [path.join(runtime, "node_modules/@huggingface/transformers/dist/transformers.node.cjs")]: "synthetic runtime: never import",
    [path.join(runtime, "omp-sharp-stub.cjs")]: "module.exports = {};\n",
  };
  for (const [file, bytes] of Object.entries(files)) { fs.mkdirSync(path.dirname(file), { recursive: true }); fs.writeFileSync(file, bytes); }
  return { cacheRoot: root, model, runtime, resources: inspectInstalledTiny(root, version)! };
}
function request() {
  const controller = new AbortController(); let calls = 0;
  const call = { requestId: "tiny-request", model: { provider: "local", model: "lfm2.5-230m" }, installedOnly: true as const,
    input: "synthetic effects", maxOutputTokens: 128, maxOutputBytes: 1024, deadline: performance.now() + 5000,
    signal: controller.signal, onInferenceStarted: () => { calls++; } };
  return { call, controller, calls: () => calls };
}

test("missing, incomplete, linked or incompatible installed resources do not load any runtime", async () => {
  const value = install(); let loads = 0;
  expect(value.resources).toBeDefined();
  fs.unlinkSync(path.join(value.model, "onnx/model_q4.onnx"));
  expect(inspectInstalledTiny(value.cacheRoot, version)).toBeUndefined();
  await expect(loadInstalledTinyPipeline(value.resources, () => { loads++; throw new Error("INSTALL_DISABLED"); }))
    .rejects.toThrow("PERMISSION_TINY_UNAVAILABLE");
  expect(loads).toBe(0);
  expect(inspectInstalledTiny(value.cacheRoot, "../../outside")).toBeUndefined();
});

test("actual installed-only loader forces local files and never touches shared title worker", async () => {
  const value = install(); let inference = 0;
  const runtime = { env: { allowLocalModels: false, allowRemoteModels: true, useFSCache: true,
    useBrowserCache: true, localModelPath: "remote" }, LogLevel: { ERROR: "error" },
    pipeline: async (task: unknown, model: unknown, options: unknown) => {
      expect(task).toBe("text-generation"); expect(model).toBe(value.model);
      expect(options).toEqual({ device: "cpu", dtype: "q4", local_files_only: true });
      return Object.assign(async () => { inference++; return []; }, { tokenizer: {} });
    } };
  await loadInstalledTinyPipeline(value.resources, (() => runtime) as any);
  expect(runtime.env.allowRemoteModels).toBe(false); expect(runtime.env.allowLocalModels).toBe(true);
  expect(runtime.env.useFSCache).toBe(false); expect(runtime.env.useBrowserCache).toBe(false);
  expect(inference).toBe(0);
});

test("separate request-owned worker starts inference once after ready and is always killed", async () => {
  install(getTinyModelsCacheDir()); process.env.PI_TINY_TRANSFORMERS_VERSION = version;
  declareWorkerHostEntry();
  const value = request(); let launches = 0; let killed = 0; const messages: any[] = [];
  Bun.spawn = ((options: any) => {
    launches++; expect(options.cmd.at(-1)).toBe(PERMISSION_TINY_WORKER);
    expect(options.env).not.toHaveProperty("OMP_TINY_WORKER_SOCKET");
    expect(options.stderr).toBe("ignore");
    return { stdin: { write: (raw: string) => { messages.push(JSON.parse(raw)); }, flush: async () => 0 },
      stdout: new Response('{"state":"ready"}\n{"state":"result","text":"{\\"decision\\":\\"ask\\",\\"reasonCode\\":\\"USER_CONFIRMATION_REQUIRED\\"}","outputTokens":20}\n').body,
      kill: () => { killed++; } };
  }) as any;
  const service = createTinyInstalledOnly(value.call);
  const result = await service(value.call);
  expect(result.status).toBe("ok"); expect(value.calls()).toBe(1); expect(launches).toBe(1); expect(killed).toBe(1);
  expect(messages.map(message => message.type)).toEqual(["load", "generate"]);
  expect((await service(value.call)).status).toBe("cancelled"); expect(launches).toBe(1);
});

test("unavailable installation cannot spawn a worker or count inference", async () => {
  delete process.env.PI_TINY_TRANSFORMERS_VERSION;
  let launches = 0;
  Bun.spawn = (() => { launches++; throw new Error("WORKER_DISABLED"); }) as any;
  const value = request();
  expect((await createTinyInstalledOnly(value.call)(value.call)).status).toBe("unavailable");
  expect(launches).toBe(0); expect(value.calls()).toBe(0);
});

test("linked model file is unavailable even when its target has matching bytes", () => {
  const value = install(); const original = path.join(value.model, "tokenizer.json");
  fs.renameSync(original, original + ".real"); fs.symlinkSync(original + ".real", original);
  expect(inspectInstalledTiny(value.cacheRoot, version)).toBeUndefined();
});

test("cancellation during local loading kills only the dedicated process before inference", async () => {
  install(getTinyModelsCacheDir()); process.env.PI_TINY_TRANSFORMERS_VERSION = version; declareWorkerHostEntry();
  const value = request(); let killed = 0;
  let output!: ReadableStreamDefaultController<Uint8Array>;
  Bun.spawn = (() => ({ stdin: { write: () => { queueMicrotask(() => value.controller.abort()); }, flush: async () => 0 },
    stdout: new ReadableStream<Uint8Array>({ start(controller) { output = controller; } }),
    kill: () => { killed++; try { output.close(); } catch {} } })) as any;
  expect((await createTinyInstalledOnly(value.call)(value.call)).status).toBe("cancelled");
  expect(killed).toBeGreaterThanOrEqual(1); expect(value.calls()).toBe(0);
});
