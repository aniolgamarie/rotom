// 计算目录只有沙箱内文件；将实际内容摘要绑定到返回结果，父侧复制后重新校验。
import { constants, closeSync, fstatSync, lstatSync, openSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { join } from "node:path";

export function readseekArtifact(output, snapshotRoot) {
  const entries = []; let total = 0, visited = 0;
  function visit(directory, prefix) {
    if (++visited > 41000) throw new Error("READSEEK_RESULT_LIMIT");
    for (const name of readdirSync(directory).sort()) {
      if ([".git", ".readseek"].includes(name)) throw new Error("READSEEK_UNEXPECTED_FILE");
      const path = join(directory, name), relative = prefix ? prefix + "/" + name : name;
      const info = lstatSync(path);
      if (info.isDirectory() && !info.isSymbolicLink()) { visit(path, relative); continue; }
      if (!info.isFile() || info.isSymbolicLink() || info.nlink !== 1 || info.size > 16 * 1024 * 1024) throw new Error("READSEEK_UNEXPECTED_FILE");
      const fd = openSync(path, constants.O_RDONLY | constants.O_NOFOLLOW);
      try {
        const current = fstatSync(fd);
        if (!current.isFile() || current.nlink !== 1 || current.dev !== info.dev || current.ino !== info.ino || current.size > 16 * 1024 * 1024) throw new Error("READSEEK_SNAPSHOT_CHANGED");
        const body = readFileSync(fd);
        total += body.length;
        if (body.length > 16 * 1024 * 1024 || total > 128 * 1024 * 1024 || entries.length >= 10000) throw new Error("READSEEK_RESULT_LIMIT");
        entries.push({ path: relative, size: body.length, sha256: createHash("sha256").update(body).digest("hex") });
      } finally { closeSync(fd); }
    }
  }
  visit(snapshotRoot, "");
  return { ...output, computed_entries: entries.sort((a, b) => Buffer.compare(Buffer.from(a.path), Buffer.from(b.path))) };
}

export function writeReadseekArtifact(output, target) {
  const body = Buffer.from(JSON.stringify(output) + "\n");
  if (body.length > 32 * 1024 * 1024) throw new Error("READSEEK_RESULT_LIMIT");
  const fd = openSync(target, constants.O_CREAT | constants.O_EXCL | constants.O_WRONLY | constants.O_NOFOLLOW, 0o600);
  // 这是可丢弃计算产物；崩溃恢复依赖父侧持久提交日志，不能借此声明提交完成。
  try { writeFileSync(fd, body); } finally { closeSync(fd); }
  return { sha256: createHash("sha256").update(body).digest("hex"), bytes: body.length };
}
