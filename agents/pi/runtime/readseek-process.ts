// 固定的一次性沙箱入口。输入路径与运行包由监督器绑定，不接收脚本或扩展路径。
import { constants, closeSync, fstatSync, openSync, readFileSync, realpathSync } from "node:fs";
import { dirname, isAbsolute, join, relative, sep } from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath, pathToFileURL } from "node:url";
import { executeReadseek } from "./readseek-worker.ts";
import { readseekArtifact, writeReadseekArtifact } from "./readseek-artifact.ts";

function readInput(path, limit) {
  const fd = openSync(path, constants.O_RDONLY | constants.O_NOFOLLOW);
  try {
    const info = fstatSync(fd);
    if (!info.isFile() || info.nlink !== 1 || info.size > limit) throw new Error("READSEEK_INPUT_INVALID");
    const body = readFileSync(fd);
    if (body.length > limit) throw new Error("READSEEK_INPUT_INVALID");
    return JSON.parse(new TextDecoder("utf8", { fatal: true }).decode(body));
  } finally { closeSync(fd); }
}

try {
  if (process.argv.length !== 2) throw new Error("READSEEK_INPUT_INVALID");
  // 私人 cwd 按固定布局提供输入；没有 HOME/global 配置发现。
  const home = process.cwd();
  const runtimeRoot = dirname(dirname(fileURLToPath(import.meta.url)));
  const installed = readInput(join(runtimeRoot, "runtime/profile.json"), 1024 * 1024);
  const platform = process.platform + "-" + (process.arch === "x64" ? "x86_64" : process.arch);
  if (process.version !== installed.toolchains.node || installed.platform !== platform) throw new Error("READSEEK_RUNTIME_MISMATCH");
  function bound(path) {
    const resolved = realpathSync(path), tail = relative(runtimeRoot, resolved);
    if (isAbsolute(tail) || tail === ".." || tail.startsWith(".." + sep)) throw new Error("READSEEK_MODULE_BOUNDARY");
    return resolved;
  }
  const sdkEntry = bound(join(runtimeRoot, installed.entrypoint));
  const require = createRequire(sdkEntry);
  const { createJiti } = await import(pathToFileURL(bound(require.resolve("jiti"))).href);
  const loader = createJiti(sdkEntry, { moduleCache: false, fsCache: false });
  const request = readInput(join(home, "request.json"), 2 * 1024 * 1024);
  const contracts = readInput(new URL("./readseek-tool-contracts.json", import.meta.url), 1024 * 1024);
  process.chdir(request.working_directory);
  const output = await executeReadseek(request, contracts, async () => (await loader.import(bound(require.resolve("pi-readseek")))).default);
  const artifact = writeReadseekArtifact(readseekArtifact(output, request.snapshot_root), join(home, "result.json"));
  process.stdout.write(JSON.stringify({ jsonrpc: "2.0", type: "ready", operation_id: request.operation_id, ...artifact }) + "\n");
  // 父侧确认提交/拒绝后才退出。EOF 或重复/其他消息不会被当成成功。
  let received = "";
  await new Promise((resolve, reject) => {
    process.stdin.setEncoding("utf8");
    process.stdin.on("data", chunk => {
      received += chunk;
      if (Buffer.byteLength(received) > 1024) return reject(new Error("READSEEK_ACK_INVALID"));
      if (!received.includes("\n")) return;
      try {
        const ack = JSON.parse(received);
        if (Object.keys(ack).sort().join(",") !== "jsonrpc,operation_id,type" || ack.jsonrpc !== "2.0"
            || ack.type !== "accepted" || ack.operation_id !== request.operation_id) throw new Error("READSEEK_ACK_INVALID");
        process.stdin.pause(); resolve();
      } catch { reject(new Error("READSEEK_ACK_INVALID")); }
    });
    process.stdin.on("end", () => reject(new Error("READSEEK_ACK_MISSING")));
    process.stdin.on("error", reject);
  });
} catch {
  // 原生错误可能带源码或私人路径；公开通道只发固定失败码。
  process.stderr.write("READSEEK_COMPUTE_FAILED\n");
  process.exitCode = 5;
} finally { process.stdin.destroy(); }
