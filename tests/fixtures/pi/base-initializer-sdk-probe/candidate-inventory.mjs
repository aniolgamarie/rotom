// 只读完整安装树收据核对；准备函数不启动进程、不加载SDK、不保存/修改任何候选。
import fs from "node:fs";
import path from "node:path";
import { createHash } from "node:crypto";
const fail = () => { throw Error("MAIN_SDK_PROBE_CANDIDATE_INVALID"); };
const text = value => typeof value === "string" && value.length && !/[\p{Cc}\p{Cf}]/u.test(value);
const relative = name => text(name) && !path.isAbsolute(name) && path.normalize(name) === name && !name.split("/").includes("..");
const digest = bytes => createHash("sha256").update(bytes).digest("hex");
function filePin(file) {
  const info = fs.lstatSync(file); if (!info.isFile() || info.isSymbolicLink() || info.nlink !== 1 || info.size > 64 * 1024 * 1024) fail();
  const fd = fs.openSync(file, fs.constants.O_RDONLY | fs.constants.O_NOFOLLOW), hash = createHash("sha256"), buffer = Buffer.alloc(65536);
  let size = 0;
  try {
    const opened = fs.fstatSync(fd); if (opened.dev !== info.dev || opened.ino !== info.ino) fail();
    for (;;) { const count = fs.readSync(fd, buffer, 0, Math.min(buffer.length, info.size - size + 1), null); if (!count) break; size += count; if (size > info.size) fail(); hash.update(buffer.subarray(0, count)); }
    const final = fs.fstatSync(fd), named = fs.lstatSync(file);
    for (const next of [final, named]) if (next.dev !== info.dev || next.ino !== info.ino || next.size !== info.size || next.mode !== info.mode || next.uid !== info.uid || next.gid !== info.gid || next.nlink !== 1 || next.mtimeMs !== info.mtimeMs || next.ctimeMs !== info.ctimeMs) fail();
    if (size !== info.size) fail(); return { bytes: size, sha256: hash.digest("hex"), mode: info.mode & 0o777 };
  } finally { fs.closeSync(fd); }
}
export function verifyCandidateInventory({ candidateRoot, receiptPath, receiptSha256, receiptRootName = path.basename(candidateRoot) }) {
  try {
    if (![candidateRoot, receiptPath].every(value => text(value) && path.isAbsolute(value) && path.normalize(value) === value) || !/^[a-f0-9]{64}$/.test(receiptSha256)) fail();
    if (fs.realpathSync(candidateRoot) !== candidateRoot || !fs.lstatSync(candidateRoot).isDirectory()) fail();
    const stat = fs.lstatSync(receiptPath); if (!stat.isFile() || stat.isSymbolicLink() || stat.size > 16 * 1024 * 1024) fail();
    const receipt = fs.readFileSync(receiptPath); if (digest(receipt) !== receiptSha256) fail();
    const rows = JSON.parse(receipt.toString("utf8")); if (!Array.isArray(rows) || !rows.length || rows.length > 65536) fail();
    if (!text(receiptRootName) || receiptRootName.includes("/") || receiptRootName === "." || receiptRootName === "..") fail();
    const prefix = receiptRootName, expected = new Map(); let files = 0, total = 0;
    for (const row of rows) {
      if (!row || !relative(row.path) || row.path !== prefix && !row.path.startsWith(prefix + "/") || expected.has(row.path) || !["file", "directory", "symlink"].includes(row.kind)) fail();
      expected.set(row.path, row);
    }
    const seen = new Set();
    function visit(file, name, depth) {
      if (depth > 128 || seen.size >= 65536) fail(); const row = expected.get(name); if (!row) fail(); seen.add(name);
      const stat = fs.lstatSync(file);
      if (row.kind === "directory") {
        if (!stat.isDirectory() || stat.isSymbolicLink() || (stat.mode & 0o777) !== 0o700) fail();
        for (const entry of fs.readdirSync(file)) visit(path.join(file, entry), name + "/" + entry, depth + 1);
      } else if (row.kind === "file") {
        const pin = filePin(file), mode = row.original_mode & 0o111 ? 0o700 : 0o600;
        if (pin.bytes !== row.bytes || pin.sha256 !== row.sha256 || pin.mode !== mode) fail(); files++; total += pin.bytes; if (total > 512 * 1024 * 1024) fail();
      } else {
        if (!stat.isSymbolicLink() || !relative(row.target) && !(text(row.target) && !path.isAbsolute(row.target) && row.target.includes("..")) || fs.readlinkSync(file) !== row.target || !relative(row.resolved_relative) || !row.resolved_relative.startsWith(prefix + "/")) fail();
        const resolved = fs.realpathSync(file); if (resolved !== path.join(candidateRoot, row.resolved_relative.slice(prefix.length + 1)) || !resolved.startsWith(candidateRoot + "/") || !fs.statSync(resolved).isFile()) fail();
      }
    }
    visit(candidateRoot, prefix, 0); if (seen.size !== expected.size) fail();
    return { sha256: receiptSha256, entries: seen.size, file_count: files, bytes: total };
  } catch { fail(); }
}
