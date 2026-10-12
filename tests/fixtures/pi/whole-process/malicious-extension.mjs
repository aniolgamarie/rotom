// 合成恶意扩展直接IO/固定spawn绕过tool准入，专用于以后Q3整进程OS边界调查。
// import仅注册公开command，不执行任何攻击；本包默认测试绝不加载此模块。
import fs from "node:fs";
import { spawnSync } from "node:child_process";
import { localRoundTrip, deniedOutbound } from "./loopback.mjs";
const CASES = ["allowed-file-read-write", "denied-host-file-read", "denied-host-file-write", "denied-outbound-connect", "allowed-loopback-connect", "allowed-fixed-child", "denied-child-host-read", "container-credential-readable"];
function readable(file) {
  let fd; try { fd = fs.openSync(file, fs.constants.O_RDONLY); fs.readSync(fd, Buffer.alloc(64), 0, 64, 0); return true; }
  catch { return false; } finally { if (fd !== undefined) fs.closeSync(fd); }
}
async function observe(caseId) {
  const planStat = fs.lstatSync("/probe/whole-process/plan.json");
  if (!planStat.isFile() || planStat.isSymbolicLink() || planStat.size > 32768) throw Error("WHOLE_PROCESS_PRECONDITION");
  const plan = JSON.parse(fs.readFileSync("/probe/whole-process/plan.json", "utf8"));
  // 冻结标记是输入校验，不构成执行授权；实际授权及容器argv由父侧独立核对。
  if (plan.execution_state !== "frozen-pending-separate-authorization" || process.platform !== "linux" || process.arch !== "x64" || process.version !== "v24.14.0"
      || process.execPath !== "/node/bin/node" || !CASES.includes(caseId)) throw Error("WHOLE_PROCESS_PRECONDITION");
  let fact;
  if (caseId === "allowed-file-read-write") {
    fact = readable("/project/allowed.txt"); fs.writeFileSync("/project/allowed-output.txt", "OWN_ALLOWED_WRITE\n", { mode: 0o600, flag: "wx" });
  } else if (caseId === "denied-host-file-read") fact = readable("/outside-host/denied.txt");
  else if (caseId === "denied-host-file-write") { fact = false; try { fs.writeFileSync("/outside-host/denied.txt", "OWN_DENIED_WRITE\n"); fact = true; } catch { /* 不输出异常。 */ } }
  else if (caseId === "container-credential-readable") fact = readable("/state/pi-home/auth.json");
  else if (caseId === "allowed-loopback-connect") fact = await localRoundTrip();
  else if (caseId === "denied-outbound-connect") fact = await deniedOutbound();
  else {
    const mode = caseId === "allowed-fixed-child" ? "allow" : "deny";
    const child = spawnSync("/node/bin/node", ["/probe/whole-process/child.mjs", mode], { cwd: "/project", env: { HOME: "/state/pi-home", PATH: "/empty-bin" },
      shell: false, timeout: 2000, maxBuffer: 4096, stdio: ["ignore", "pipe", "pipe"] });
    if (child.error || child.status !== 0 || child.stderr.length || child.stdout.length > 256) throw Error("WHOLE_PROCESS_CHILD_UNKNOWN");
    const value = JSON.parse(child.stdout.toString("utf8"));
    if (Object.keys(value).sort().join() !== "mode,readable,schema_version" || value.schema_version !== 1 || value.mode !== mode || typeof value.readable !== "boolean") throw Error("WHOLE_PROCESS_CHILD_UNKNOWN");
    fact = value.readable;
  }
  const expected = ["allowed-file-read-write", "allowed-loopback-connect", "allowed-fixed-child", "container-credential-readable"].includes(caseId);
  return { schema_version: 1, case_id: caseId, fact, expected, status: fact === expected ? "observed" : "failed" };
}
export default function registerWholeProcessProbe(pi) {
  pi.registerCommand("whole-process-probe", { description: "Explicit own synthetic whole-process investigation only", handler: async (argument) => {
    if (typeof argument !== "string" || !CASES.includes(argument)) throw Error("WHOLE_PROCESS_CASE_INVALID");
    let result;
    try { result = await observe(argument); } catch { result = { schema_version: 1, case_id: argument, status: "failed", fact: null, expected: null }; }
    // 只写固定独占结果，不输出文件正文、账号内容或任意底层错误。
    fs.writeFileSync("/results/" + argument + ".json", JSON.stringify(result) + "\n", { mode: 0o600, flag: "wx" });
  } });
}
