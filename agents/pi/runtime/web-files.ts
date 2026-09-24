// Web 的本地媒体只使用同一普通文件权限产生的不可变副本。
import { randomUUID, createHash } from "node:crypto";
import { constants, openSync, closeSync, fstatSync, readFileSync } from "node:fs";
import { dirname, basename, isAbsolute, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { requireOrdinaryHelper } from "./capability-policy.ts";
import { closed, reject } from "./managed-types.ts";
const files = new WeakMap(), slot = Symbol.for("agentcfg.pi.runtime.v1");
export async function webLocalFile(input) {
  const runtime = globalThis[slot];
  const operation = runtime?.web?.current();
  requireOrdinaryHelper(runtime, "pi-web", operation?.id ?? null);
  if (!operation) reject("WEB_OPERATION_CLOSED", 4);
  if (typeof input !== "string" || !input || input.length > 8192 || /[\x00-\x1f\x7f]/.test(input)) reject("WEB_FILE_PATH", 2);
  let path;
  try { path = input.startsWith("file:") ? fileURLToPath(input) : input; }
  catch { reject("WEB_FILE_PATH", 2); }
  if (!isAbsolute(path)) path = resolve(runtime.cwd, path);
  else path = resolve(path);
  let cache = files.get(operation);
  if (!cache) files.set(operation, cache = new Map());
  if (cache.has(path)) return cache.get(path);
  const pending = (async () => {
    operation.controller.signal.throwIfAborted();
    const value = await runtime.supervisor.call("ordinary_web_file_prepare", { operation_id: randomUUID(), cwd: runtime.cwd, path });
    const release = async () => {
      const result = await runtime.supervisor.call("ordinary_web_file_finish", { file_id: value.file_id });
      if (result.released !== true) reject("WEB_FILE_RELEASE_UNKNOWN", 4);
    };
    try {
      closed(value, ["file_id", "directory", "path", "size", "sha256"]);
      const root = join(dirname(dirname(dirname(runtime.supervisor.options.endpoint))), "activity/web-files");
      if (typeof value.file_id !== "string" || !/^[0-9a-f]{64}$/.test(value.file_id) || typeof value.directory !== "string"
          || dirname(value.directory) !== root || !/^[0-9a-f]{32}$/.test(basename(value.directory))
          || value.path !== path || !Number.isSafeInteger(value.size) || value.size < 0 || value.size > (runtime.manifest.options.web?.media?.max_file_bytes ?? 128 * 1024 * 1024)
          || typeof value.sha256 !== "string" || !/^[0-9a-f]{64}$/.test(value.sha256)) reject("WEB_FILE_SNAPSHOT_INVALID", 5);
      if (globalThis[slot] !== runtime) reject("WEB_FILE_STALE", 4);
      operation.controller.signal.throwIfAborted();
      runtime.web.cleanup(release);
      return { ...value, snapshot_path: join(value.directory, "input"), bytes() {
        if (globalThis[slot] !== runtime || runtime.web.current() !== operation) reject("WEB_FILE_STALE", 4);
        const fd = openSync(join(value.directory, "input"), constants.O_RDONLY | constants.O_NOFOLLOW);
        try {
          const info = fstatSync(fd);
          if (!info.isFile() || info.nlink !== 1 || info.size !== value.size) reject("WEB_FILE_CHANGED", 4);
          const bytes = readFileSync(fd);
          if (bytes.length !== value.size || createHash("sha256").update(bytes).digest("hex") !== value.sha256) reject("WEB_FILE_CHANGED", 4);
          return bytes;
        } finally { closeSync(fd); }
      } };
    } catch (error) {
      if (typeof value.file_id === "string") await release();
      throw error;
    }
  })();
  cache.set(path, pending); return pending;
}
export async function webReadLocalFile(path) { return (await webLocalFile(path)).bytes(); }
