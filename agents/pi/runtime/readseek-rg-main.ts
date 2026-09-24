import { spawn } from "node:child_process";
import { isAbsolute } from "node:path";
import { readseekRgArguments } from "./readseek-rg.ts";

try {
  const executable = process.env.AGENTCFG_READSEEK_RG;
  if (!executable || !isAbsolute(executable)) throw new Error();
  const argv = readseekRgArguments(process.argv.slice(2), process.env.AGENTCFG_READSEEK_SNAPSHOT);
  // SDK 可能因结果上限停止 shim；转发信号并等 rg 退出，避免孤立原生子进程。
  const child = spawn(executable, argv, { stdio: "inherit" });
  for (const signal of ["SIGTERM", "SIGINT"]) process.on(signal, () => { child.kill(signal); });
  child.on("error", () => { process.stderr.write("READSEEK_RG_FAILED\n"); process.exitCode = 5; });
  child.on("close", (code, signal) => { process.exitCode = code ?? (signal === "SIGINT" ? 130 : 143); });
} catch {
  process.stderr.write("READSEEK_RG_QUERY_INVALID\n"); process.exitCode = 2;
}
