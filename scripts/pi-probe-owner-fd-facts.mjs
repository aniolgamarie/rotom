// 纯事实校验；不访问文件、进程或锁，也不把元数据当权限。
import { types } from "node:util";
export function parseFdFlags(text) {
  if (typeof text !== "string" || Buffer.byteLength(text, "utf8") > 4096) throw new Error("owner fd facts invalid");
  const rows = text.split("\n").filter(row => /^\s*flags:/.test(row));
  if (rows.length !== 1 || !/^flags:\s+[0-7]{1,22}\s*$/.test(rows[0])) throw new Error("owner fd facts invalid");
  const flags = BigInt("0o" + rows[0].trim().split(/\s+/)[1]);
  if (flags > (1n << 64n) - 1n) throw new Error("owner fd facts invalid");
  return { flags: flags.toString(8), cloexec: (flags & 0o2000000n) !== 0n };
}

export function captureBinding(value) {
  if (!value || types.isProxy(value) || Object.getPrototypeOf(value) !== Object.prototype || Reflect.ownKeys(value).length !== 5) throw new Error("owner fd facts invalid");
  const output = Object.create(null);
  for (const name of ["device", "inode", "uid", "mode", "nlink"]) {
    const descriptor = Object.getOwnPropertyDescriptor(value, name);
    if (!descriptor || !("value" in descriptor) || !descriptor.enumerable) throw new Error("owner fd facts invalid");
    const field = descriptor.value;
    if (name === "device" || name === "inode") {
      if (typeof field !== "string" || !/^(0|[1-9][0-9]{0,19})$/.test(field) || BigInt(field) > (1n << 64n) - 1n || (name === "inode" && field === "0")) throw new Error("owner fd facts invalid");
    } else if (!Number.isSafeInteger(field) || field < 0) throw new Error("owner fd facts invalid");
    output[name] = field;
  }
  if (output.mode !== 0o600 || output.nlink !== 1) throw new Error("owner fd facts invalid");
  return Object.freeze(output);
}

export function matchesBinding(info, binding) {
  return info.dev === BigInt(binding.device) && info.ino === BigInt(binding.inode)
    && info.uid === BigInt(binding.uid) && (info.mode & 0o7777n) === 0o600n
    && (info.mode & 0o170000n) === 0o100000n && info.nlink === 1n;
}
