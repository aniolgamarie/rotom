// 仅明确 guest 参数运行；默认单元测试只导入独立纯 facts。
import * as fs from "node:fs";
import { spawn } from "node:child_process";
import { captureBinding, matchesBinding, parseFdFlags } from "./facts.mjs";

const MAX = 65536;
function require(value) { if (!value) throw new Error("owner fd worker invalid"); }
function publish(name, value) {
  const raw = Buffer.from(JSON.stringify(value) + "\n"); require(raw.length <= MAX);
  const fd = fs.openSync(name, "wx", 0o600);
  try { fs.writeFileSync(fd, raw); fs.fsyncSync(fd); } finally { fs.closeSync(fd); }
  process.stdout.write(raw);
}
function ownStat(fd) { return fs.fstatSync(fd, { bigint: true }); }
function descendant(binding) {
  const names = fs.readdirSync("/proc/self/fd"); require(names.length <= 1024);
  const matches = [];
  for (const name of names) {
    require(/^(0|[1-9][0-9]*)$/.test(name) && Number.isSafeInteger(Number(name)));
    try {
      const info = ownStat(Number(name));
      if (info.dev === BigInt(binding.device) && info.ino === BigInt(binding.inode)) matches.push(Number(name));
    } catch (error) { if (!["ENOENT", "EBADF"].includes(error?.code)) throw new Error("owner fd descendant invalid"); }
  }
  return { schema: 1, kind: "descendant", scanned: names.length, matches };
}
async function child(binding) {
  const processChild = spawn("/node", ["/probe/worker.mjs", "--descendant", JSON.stringify(binding)], {
    env: { HOME: "/work/home", PATH: "/work/empty-bin", TMPDIR: "/work/tmp", OWNER_FD_GUEST: "1" }, stdio: ["ignore", "pipe", "pipe"], shell: false,
  });
  let output = Buffer.alloc(0), errors = Buffer.alloc(0), failed = false;
  let rejectCapture;
  const timer = setTimeout(() => { failed = true; rejectCapture(new Error("owner fd child timeout")); }, 6000);
  processChild.stdout.on("data", data => { if (output.length + data.length > MAX) { failed = true; rejectCapture(new Error("owner fd child output invalid")); } else output = Buffer.concat([output, data]); });
  processChild.stderr.on("data", data => { if (errors.length + data.length > MAX) { failed = true; rejectCapture(new Error("owner fd child output invalid")); } else errors = Buffer.concat([errors, data]); });
  let exit;
  try { exit = await new Promise((resolve, reject) => { rejectCapture = reject; processChild.once("error", reject); processChild.once("close", (code, signal) => resolve({ code, signal })); }); }
  finally { clearTimeout(timer); }
  require(!failed && exit.code === 0 && exit.signal === null && errors.length === 0 && output.length <= MAX);
  require(output.at(-1) === 10 && [...output].filter(byte => byte === 10).length === 1);
  const facts = JSON.parse(output.toString("utf8"));
  require(JSON.stringify(facts) + "\n" === output.toString("utf8"));
  require(Object.keys(facts).sort().join(",") === "kind,matches,scanned,schema" && facts.schema === 1 && facts.kind === "descendant"
    && Number.isSafeInteger(facts.scanned) && facts.scanned >= 0 && facts.scanned <= 1024 && Array.isArray(facts.matches) && facts.matches.length === 0);
  return { descendantSpawns: 1, descendantMatches: facts.matches.length, descendantExitCode: exit.code };
}
async function hold() {
  const end = Date.now() + 14000;
  while (Date.now() < end) {
    try {
      const value = fs.readFileSync("/work/node-command", { encoding: "utf8" }); require(Buffer.byteLength(value) <= 16 && value === "exit\n"); return;
    } catch (error) { if (error?.code !== "ENOENT") throw new Error("owner fd command invalid"); }
    await new Promise(resolve => setTimeout(resolve, 10));
  }
  throw new Error("owner fd command timeout");
}
async function main() {
  require(process.env.OWNER_FD_GUEST === "1" && process.argv.length === 4
    && process.platform === "linux" && process.arch === "x64" && process.version === "v24.14.0");
  const mode = process.argv[2], binding = captureBinding(JSON.parse(process.argv[3]));
  if (mode === "--descendant") {
    process.stdout.write(JSON.stringify(descendant(binding)) + "\n"); return;
  }
  require(mode === "--entry");
  let accepted = false;
  // 任何文件/fdinfo操作之前先物理核 fd3；拒绝时不显式关闭未知 fd。
  try { accepted = matchesBinding(ownStat(3), binding); } catch { accepted = false; }
  let facts = { accepted, cloexec: null, flags: null, descendantSpawns: 0, descendantMatches: null, descendantExitCode: null };
  if (accepted) {
    const fd = fs.openSync("/proc/self/fdinfo/3", "r"); let raw;
    try { const buffer = Buffer.alloc(4097); const count = fs.readSync(fd, buffer, 0, buffer.length, null); require(count <= 4096); raw = buffer.subarray(0, count).toString("utf8"); } finally { fs.closeSync(fd); }
    require(matchesBinding(ownStat(3), binding));
    const flags = parseFdFlags(raw); require(flags.cloexec);
    facts = { ...facts, ...flags, ...await child(binding) };
    require(matchesBinding(ownStat(3), binding));
  }
  publish("/work/node-entry.json", { schema: 1, kind: "entry", ...facts });
  await hold();
  if (accepted) require(matchesBinding(ownStat(3), binding));
}
main().catch(() => { process.stderr.write("owner fd worker failed\n"); process.exitCode = 2; });
