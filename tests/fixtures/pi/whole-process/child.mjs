// 自有固定child：只读两个固定合成路径，不能由参数指定argv/路径/代码。
import fs from "node:fs";
const mode = process.argv[2];
if (process.argv.length !== 3 || !["allow", "deny"].includes(mode)) { process.exitCode = 2; }
else {
  let readable = false;
  try { const fd = fs.openSync(mode === "allow" ? "/project/allowed.txt" : "/outside-host/denied.txt", fs.constants.O_RDONLY); try { fs.readSync(fd, Buffer.alloc(64), 0, 64, 0); readable = true; } finally { fs.closeSync(fd); } } catch { /* 仅保留事实，不输出底层路径/文件正文。 */ }
  process.stdout.write(JSON.stringify({ schema_version: 1, mode, readable }) + "\n");
  process.exitCode = readable === (mode === "allow") ? 0 : 1;
}
