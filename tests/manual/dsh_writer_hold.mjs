// 仅显式隔离验收：持公开 session write handle，不创建 Agent、不写 event。
// WRITER_HELD 只证明本句柄已打开，不提供停止/恢复批准或生产能力准入。
import { realpath } from "node:fs/promises";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const absolute = value => typeof value === "string" && value.length <= 4096
  && !/[\x00-\x1f\x7f]/.test(value) && path.isAbsolute(value)
  && path.normalize(value) === value && value !== path.parse(value).root;
const sessionId = value => typeof value === "string" && /^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$/.test(value);
const report = (stream, code) => { try { stream.write(code + "\n"); } catch {} };

function releaseInput(input) {
  // 先订阅再打开句柄；早到 release/EOF 不会丢失。EOF 仅触发清理，不确认释放协议成功。
  const command = Buffer.from("release\n");
  let bytes = Buffer.alloc(0);
  let invalid = false;
  let settled = false;
  let resolve;
  const ready = new Promise(done => { resolve = done; });
  const finish = bad => {
    invalid ||= bad;
    if (!settled) { settled = true; resolve(); }
  };
  const data = chunk => {
    if (settled || bytes.length + chunk.length > command.length) return finish(true);
    bytes = Buffer.concat([bytes, Buffer.from(chunk)]);
    if (!command.subarray(0, bytes.length).equals(bytes)) return finish(true);
    if (bytes.equals(command)) finish(false);
  };
  const end = () => finish(!bytes.equals(command));
  const error = () => finish(true);
  input.on("data", data);
  input.once("end", end);
  input.once("error", error);
  if (input.readableEnded) end();
  else if (input.destroyed) error();
  else input.resume();
  return { ready, close() {
    input.removeListener("data", data);
    input.removeListener("end", end);
    input.removeListener("error", error);
    input.pause();
    return invalid;
  } };
}

export async function holdWriter(api, root, id, { input = process.stdin,
    output = process.stdout, error = process.stderr } = {}) {
  if (!absolute(root) || !sessionId(id)) {
    report(error, "WRITER_ARGUMENT_INVALID");
    return 2;
  }
  let context;
  let handle;
  let release;
  let code = 0;
  let failure;
  let closed = false;
  let disposed = false;
  try {
    release = releaseInput(input);
    context = new api.Context();
    await context.plugin(api.JsonlSessionPersistence, { root });
    handle = await context.sessionPersistence.open(api.SessionId(id), "write");
    output.write("WRITER_HELD\n");
    await release.ready;
  } catch {
    code = 5;
    failure = "WRITER_OPEN_OR_WAIT_UNCONFIRMED";
  } finally {
    if (handle) {
      try { await handle.close(); closed = true; }
      catch { code = 5; failure = "WRITER_CLOSE_UNCONFIRMED"; }
    }
    if (context) {
      try { await context.fiber.dispose(); disposed = true; }
      catch { code = 5; failure = "WRITER_DISPOSE_UNCONFIRMED"; }
    }
    if (release) {
      try {
        if (release.close() && code === 0) { code = 2; failure = "WRITER_INPUT_INVALID"; }
      } catch { code = 5; failure = "WRITER_INPUT_UNCONFIRMED"; }
    }
  }
  if (closed && disposed) {
    try { output.write("WRITER_RELEASED\n"); }
    catch { code = 5; failure = "WRITER_OUTPUT_UNCONFIRMED"; }
  }
  if (failure) report(error, failure);
  return code;
}

export async function holdFromRuntime(runtimeRoot, root, id, streams) {
  if (!absolute(runtimeRoot) || !absolute(root) || !sessionId(id)) {
    report(streams?.error ?? process.stderr, "WRITER_ARGUMENT_INVALID");
    return 2;
  }
  try {
    const runtime = await realpath(runtimeRoot);
    const modules = await realpath(path.join(runtime, "node_modules"));
    if (modules !== path.join(runtime, "node_modules")) throw Error();
    const require = createRequire(path.join(runtime, "package.json"));
    const load = async name => {
      const resolved = await realpath(require.resolve(name));
      const relative = path.relative(modules, resolved);
      if (!relative || relative === ".." || relative.startsWith(".." + path.sep)
          || path.isAbsolute(relative)) throw Error();
      return import(pathToFileURL(resolved).href);
    };
    const { Context } = await load("@deepseek-ai/cordis");
    const { SessionId } = await load("@deepseek-ai/dsh-session");
    const JsonlSessionPersistence = await load("@deepseek-ai/dsh-session-persistence-jsonl");
    return await holdWriter({ Context, SessionId, JsonlSessionPersistence }, root, id, streams);
  } catch {
    report(streams?.error ?? process.stderr, "WRITER_RUNTIME_UNAVAILABLE");
    return 5;
  }
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const args = process.argv.slice(2);
  if (args.length !== 3) {
    report(process.stderr, "WRITER_ARGUMENT_INVALID");
    process.exitCode = 2;
  } else {
    process.exitCode = await holdFromRuntime(...args);
  }
}
