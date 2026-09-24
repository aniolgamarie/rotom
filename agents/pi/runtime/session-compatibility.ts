// 升级前只读取会话头；旧/未知格式不能由 SDK 在恢复时悄悄改写。
import { constants, closeSync, fstatSync, lstatSync, openSync, readSync } from "node:fs";
import { isAbsolute, join, relative, resolve, sep } from "node:path";
import { reject } from "./managed-types.ts";

const installed = new WeakMap();
export function assertSessionCompatibility(path, root, version = 3) {
  if (typeof path !== "string" || !isAbsolute(path)) reject("SESSION_SCOPE_REQUIRED", 4);
  const target = resolve(path), base = resolve(root), tail = relative(base, target);
  if (!tail || tail === ".." || tail.startsWith(".." + sep) || isAbsolute(tail)) reject("SESSION_SCOPE_REQUIRED", 4);
  let current = base;
  for (const part of ["", ...tail.split(sep).slice(0, -1)]) {
    if (part) current = join(current, part);
    const info = lstatSync(current);
    if (info.isSymbolicLink() || !info.isDirectory() || info.uid !== process.getuid() || (info.mode & 0o777) !== 0o700) reject("SESSION_SCOPE_REQUIRED", 4);
  }
  const fd = openSync(target, constants.O_RDONLY | constants.O_NOFOLLOW), buffer = Buffer.alloc(16384), one = Buffer.alloc(1);
  try {
    const info = fstatSync(fd);
    if (!info.isFile() || info.nlink !== 1 || info.uid !== process.getuid() || (info.mode & 0o777) !== 0o600) reject("SESSION_FILE_INVALID", 4);
    let size = 0, complete = false;
    while (size < buffer.length && readSync(fd, one, 0, 1, null) === 1) {
      if (one[0] === 10) { complete = true; break; }
      buffer[size++] = one[0];
    }
    if (!complete) reject("SESSION_HEADER_INVALID", 4);
    let header;
    try { header = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(buffer.subarray(0, size))); }
    catch { reject("SESSION_HEADER_INVALID", 4); }
    if (header.type !== "session" || header.version !== version || typeof header.id !== "string" || !header.id
        || typeof header.cwd !== "string" || !isAbsolute(header.cwd)) reject("SESSION_MIGRATION_REQUIRED", 4);
    const after = fstatSync(fd), actual = lstatSync(target);
    if (info.dev !== actual.dev || info.ino !== actual.ino || info.size !== after.size || info.mtimeMs !== after.mtimeMs) reject("SESSION_CHANGED", 4);
    return { version: header.version };
  } finally { closeSync(fd); }
}

export function installSessionCompatibility(sdk, root) {
  const manager = sdk.SessionManager;
  if (sdk.CURRENT_SESSION_VERSION !== 3 || typeof manager?.open !== "function" || typeof manager?.forkFrom !== "function"
      || typeof manager.prototype?._setSessionFile !== "function") reject("SESSION_SDK_INCOMPATIBLE", 5);
  let state = installed.get(manager);
  if (state) { state.root = root; return; }
  state = { root }; installed.set(manager, state);
  for (const name of ["open", "forkFrom"]) {
    const original = manager[name];
    manager[name] = function (path, ...args) { assertSessionCompatibility(path, state.root); return original.call(this, path, ...args); };
  }
  const original = manager.prototype._setSessionFile;
  manager.prototype._setSessionFile = function (path, ...args) { assertSessionCompatibility(path, state.root); return original.call(this, path, ...args); };
}
