import { lstatSync } from "node:fs";
import { isAbsolute } from "node:path";

export interface CliEntryIdentity {
  path: string;
  dev: number;
  ino: number;
  mode: number;
  size: number;
  mtimeMs: number;
  ctimeMs: number;
}

// 仅描述受管 compiled CLI 的当前入口；不复刻 SDK/source、unlink 或 PATH 兜底。
export function resolveManagedCliEntry(input: { compiled: boolean; managedLocal: boolean; execPath: string }) {
  if (!input.compiled || !input.managedLocal || !isAbsolute(input.execPath))
    throw new Error("managed compiled entry unavailable");
  const stat = lstatSync(input.execPath);
  if (!stat.isFile() || stat.isSymbolicLink() || !(stat.mode & 0o111))
    throw new Error("managed executable entry unavailable");
  const identity: CliEntryIdentity = { path: input.execPath, dev: stat.dev, ino: stat.ino, mode: stat.mode,
    size: stat.size, mtimeMs: stat.mtimeMs, ctimeMs: stat.ctimeMs };
  return { argv: [input.execPath], identity };
}
